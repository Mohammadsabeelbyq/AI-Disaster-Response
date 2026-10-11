"""Rule-based report extraction plus local image classification."""
from functools import lru_cache
from io import BytesIO
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app.models.extraction import ExtractionReview, ReportExtraction
from app.schemas.report import ExtractedFacts

log = logging.getLogger(__name__)
EXTRACTOR_VERSION = "rules-v2-resnet50"
_MODEL_PATH = Path(__file__).resolve().parents[3] / "weights" / "model.weights.h5"
_MODEL_CONFIG_PATH = _MODEL_PATH.with_name("config.json")
_CLASS_LABELS = (
    "Damaged_Infrastructure", "Fire_Disaster", "Human_Damage",
    "Land_Disaster", "Non_Damage", "Water_Disaster",
)

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
    evidence = {}
    if category_evidence:
        evidence["incident_category"] = category_evidence
    if severity_evidence:
        evidence["severity_cues"] = severity_evidence
    if urgency is not None:
        evidence["urgency"] = urgency_evidence
    if people_match:
        evidence["affected_persons"] = affected_evidence
    for field, values in (("hazards", hazard_evidence), ("requested_assistance", assistance_evidence)):
        matched = [phrase for phrases in values.values() for phrase in phrases]
        if matched:
            evidence[field] = list(dict.fromkeys(matched))
    if location_mentions:
        evidence["location_mentions"] = [location_name] if location_name else location_mentions
    return facts, {}, evidence


@lru_cache(maxsize=1)
def _load_classifier():
    from tensorflow import keras
    from tensorflow.keras.applications.resnet50 import preprocess_input

    config = json.loads(_MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
    model = keras.models.model_from_json(
        json.dumps(config), custom_objects={"preprocess_input": preprocess_input})
    model.load_weights(_MODEL_PATH)
    return model


def analyze_image(data: bytes, mime_type: str) -> tuple[str, list[dict] | None]:
    """Run the bundled six-class classifier on an uploaded image."""
    try:
        import numpy as np
        from PIL import Image

        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGB").resize((224, 224))
        batch = np.asarray(image, dtype=np.float32)[None, ...]
        scores = _load_classifier().predict(batch, verbose=0)[0]
        if len(scores) != len(_CLASS_LABELS):
            raise ValueError("Classifier output does not match the configured class labels.")
        prediction = int(np.argmax(scores))
        cue = {
            "cue": _CLASS_LABELS[prediction],
            "confidence": float(scores[prediction]),
            "evidence": "Predicted by the local image classifier",
        }
        return "COMPLETED", [cue]
    except Exception:
        log.exception("Local image classification failed")
        return "FAILED", None


def apply_image_classification(extraction: ReportExtraction, data: bytes, mime_type: str) -> None:
    status, cues = analyze_image(data, mime_type)
    extraction.image_analysis_status = status
    extraction.image_cues = cues
    if cues:
        label = cues[0]["cue"]
        confidence = float(cues[0].get("confidence", 0.0))
        context_text = f"Attached image suggests {label} (confidence {confidence:.2f})."
        extraction.evidence = {
            **extraction.evidence,
            "image_context": [context_text],
        }


def create_extraction(report, image=None) -> ReportExtraction:
    facts, confidence, evidence = extract_text(
        report.description, report.disaster_type, report.location_name)
    extraction = ReportExtraction(
        extractor_version=EXTRACTOR_VERSION,
        extracted_facts=facts,
        confidence=confidence,
        evidence=evidence,
        image_analysis_status="NOT_PROVIDED",
        image_cues=None,
    )
    if image:
        apply_image_classification(extraction, image.data, image.mime_type)
    return extraction


def correct_extraction(extraction: ReportExtraction, actor_id, facts: dict) -> None:
    previous = extraction.corrected_facts or extraction.extracted_facts
    extraction.reviews.append(ExtractionReview(
        actor_id=actor_id, previous_facts=previous, corrected_facts=facts))
    extraction.corrected_facts = facts
    extraction.reviewed_by = actor_id
    extraction.reviewed_at = datetime.now(timezone.utc)