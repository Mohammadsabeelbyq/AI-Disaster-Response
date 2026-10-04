"""Rule-based report extraction plus optional advisory image analysis."""
import base64
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.models.extraction import ExtractionReview, ReportExtraction
from app.schemas.report import ExtractedFacts

log = logging.getLogger(__name__)
EXTRACTOR_VERSION = "rules-v1"

_CATEGORIES = {
    "FLOOD": ("flood", "flooding", "inundat"),
    "FIRE": ("fire", "flames", "burning", "smoke"),
    "EARTHQUAKE": ("earthquake", "seismic", "tremor"),
    "LANDSLIDE": ("landslide", "mudslide", "rockslide"),
    "CYCLONE": ("cyclone", "hurricane", "typhoon", "tropical storm"),
    "ROAD_ACCIDENT": ("crash", "collision", "road accident", "vehicle accident"),
    "BUILDING_COLLAPSE": ("building collapse", "collapsed building", "structure collapsed"),
    "MEDICAL_EMERGENCY": ("medical emergency", "medical help", "ambulance", "injured"),
}
_URGENCY = (
    ("CRITICAL", ("trapped", "life-threatening", "immediate danger", "urgent", "emergency")),
    ("HIGH", ("stranded", "rescue", "evacuate", "evacuation", "injured", "missing")),
    ("ELEVATED", ("rising", "spreading", "worsening", "blocked", "damage")),
)
_ASSISTANCE = {
    "RESCUE": ("rescue", "trapped", "stranded"),
    "MEDICAL": ("medical", "ambulance", "injured", "medicine", "first aid"),
    "FOOD": ("food", "meals"),
    "WATER": ("drinking water", "clean water", "water supply"),
    "SHELTER": ("shelter", "temporary housing"),
    "EVACUATION": ("evacuate", "evacuation"),
}
_HAZARDS = {
    "FLOODWATER": ("floodwater", "flood water", "water entered", "water rising"),
    "FIRE_OR_SMOKE": ("fire", "flames", "smoke", "burning"),
    "STRUCTURAL_DAMAGE": ("collapse", "collapsed", "structural damage", "cracked wall"),
    "INJURY": ("injured", "wounded", "hurt"),
    "PEOPLE_TRAPPED": ("trapped", "stuck inside"),
    "CHEMICAL": ("chemical", "gas leak", "toxic"),
    "BLOCKED_ACCESS": ("road blocked", "blocked road", "road is blocked"),
}


def _evidence_for(text: str, terms: tuple[str, ...]) -> list[str]:
    evidence = []
    for term in terms:
        match = re.search(re.escape(term), text, re.IGNORECASE)
        if match:
            evidence.append(match.group(0))
    return list(dict.fromkeys(evidence))


def extract_text(description: str, disaster_type: str, location_name: str | None) -> tuple[dict, dict, dict]:
    text = description.strip()
    category_evidence = _evidence_for(text, _CATEGORIES.get(disaster_type, ()))
    if not category_evidence and disaster_type != "OTHER":
        category_evidence = [f"Submitted incident category: {disaster_type}"]

    severity_terms = ("trapped", "injured", "missing", "destroyed", "collapsed", "life-threatening")
    severity_evidence = _evidence_for(text, severity_terms)
    urgency = None
    urgency_evidence = []
    for level, terms in _URGENCY:
        urgency_evidence = _evidence_for(text, terms)
        if urgency_evidence:
            urgency = level
            break

    people_match = re.search(r"\b(\d{1,7})\s+(?:people|persons|residents|famil(?:y|ies)|children|victims)\b", text, re.I)
    affected_evidence = [people_match.group(0)] if people_match else []
    assistance_evidence = {key: _evidence_for(text, terms) for key, terms in _ASSISTANCE.items()}
    hazard_evidence = {key: _evidence_for(text, terms) for key, terms in _HAZARDS.items()}
    location_mentions = []
    for match in re.finditer(r"\b(?:near|at|in|on)\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*){0,3})", text):
        mention = match.group(1).strip(".,;:")
        if mention and mention.lower() not in {"the", "a", "an"}:
            location_mentions.append(mention)
    if location_name and location_name.strip():
        location_mentions.append(location_name.strip())
    location_mentions = list(dict.fromkeys(location_mentions))

    facts = ExtractedFacts(
        incident_category=disaster_type if category_evidence else None,
        severity_cues=severity_evidence,
        urgency=urgency,
        affected_persons=int(people_match.group(1)) if people_match else None,
        hazards=[name for name, evidence in hazard_evidence.items() if evidence],
        requested_assistance=[name for name, evidence in assistance_evidence.items() if evidence],
        location_mentions=location_mentions,
    ).model_dump()
    confidence = {}
    evidence = {}
    if category_evidence:
        confidence["incident_category"] = 0.95 if category_evidence[0].startswith("Submitted") else 0.9
        evidence["incident_category"] = category_evidence
    if severity_evidence:
        confidence["severity_cues"] = 0.85
        evidence["severity_cues"] = severity_evidence
    if urgency is not None:
        confidence["urgency"] = 0.85
        evidence["urgency"] = urgency_evidence
    if people_match:
        confidence["affected_persons"] = 0.95
        evidence["affected_persons"] = affected_evidence
    for field, values in (("hazards", hazard_evidence), ("requested_assistance", assistance_evidence)):
        matched = [phrase for phrases in values.values() for phrase in phrases]
        if matched:
            confidence[field] = 0.85
            evidence[field] = list(dict.fromkeys(matched))
    if location_mentions:
        confidence["location_mentions"] = 0.9 if location_name else 0.7
        evidence["location_mentions"] = [location_name] if location_name else location_mentions
    return facts, confidence, evidence


def analyze_image(data: bytes, mime_type: str) -> tuple[str, list[dict] | None]:
    settings = get_settings()
    if not settings.enable_image_analysis:
        return "DISABLED", None
    if not settings.gemini_api_key:
        return "NOT_CONFIGURED", None
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{quote(settings.gemini_model, safe='')}:generateContent")
    schema = {
        "type": "OBJECT",
        "properties": {"cues": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "cue": {"type": "STRING"}, "confidence": {"type": "NUMBER"},
            "evidence": {"type": "STRING"}}, "required": ["cue", "confidence", "evidence"]}}},
        "required": ["cues"],
    }
    try:
        response = httpx.post(
            url,
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [
                    {"text": "Return only visible disaster-related cues as advisory labels. Do not infer facts that are not visible. Confidence must be between 0 and 1. An empty cues list is valid."},
                    {"inline_data": {"mime_type": mime_type,
                                     "data": base64.b64encode(data).decode("ascii")}},
                ]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema},
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        cues = json.loads(payload).get("cues", [])
        valid_cues = [cue for cue in cues if isinstance(cue, dict)
                      and isinstance(cue.get("cue"), str)
                      and isinstance(cue.get("confidence"), (int, float))
                      and 0 <= cue["confidence"] <= 1]
        return "COMPLETED", valid_cues
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        log.exception("Optional image analysis failed")
        return "FAILED", None


def create_extraction(report, image=None) -> ReportExtraction:
    facts, confidence, evidence = extract_text(
        report.description, report.disaster_type, report.location_name)
    image_status, image_cues = analyze_image(image.data, image.mime_type) if image else ("NOT_PROVIDED", None)
    return ReportExtraction(
        extractor_version=EXTRACTOR_VERSION,
        extracted_facts=facts,
        confidence=confidence,
        evidence=evidence,
        image_analysis_status=image_status,
        image_cues=image_cues,
    )


def correct_extraction(extraction: ReportExtraction, actor_id, facts: dict) -> None:
    previous = extraction.corrected_facts or extraction.extracted_facts
    extraction.reviews.append(ExtractionReview(
        actor_id=actor_id, previous_facts=previous, corrected_facts=facts))
    extraction.corrected_facts = facts
    extraction.reviewed_by = actor_id
    extraction.reviewed_at = datetime.now(timezone.utc)