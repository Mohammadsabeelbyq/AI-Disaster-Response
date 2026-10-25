"""Deterministic priority scoring and classification rules (ADM-23 / ADM-24).

Scores are 0–100 recommendations. The four risk factors are normalized over
available evidence only, so missing values are not treated as zero. Population
uses min(count / 25, 1); hazard and life-safety levels use the explicit mappings
below; urgency maps CRITICAL/HIGH/ELEVATED/LOW to 1/.75/.5/.2. When confidence
is present, its configured weight discounts the base risk score by
(1 - weight * (1 - mean_confidence)); missing confidence does not discount it.
Thresholds are inclusive at each band's lower bound (default: CRITICAL >= 75,
HIGH >= 55, MEDIUM >= 30, otherwise LOW). "OTHER" or entirely unknown evidence
produces no score or classification rather than a fabricated LOW result.
"""
import math
from collections.abc import Mapping

from app.services.errors import ValidationFailed

PRIORITY_ALGORITHM_VERSION = "priority-v1"

DEFAULT_PRIORITY_WEIGHTS = {
    "life_safety_risk": 0.35,
    "urgency": 0.25,
    "affected_population": 0.2,
    "hazard_level": 0.12,
    "evidence_confidence": 0.08,
}

DEFAULT_PRIORITY_THRESHOLDS = {
    "CRITICAL": 75.0,
    "HIGH": 55.0,
    "MEDIUM": 30.0,
    "LOW": 0.0,
}

PRIORITY_BANDS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
_URGENCY_SCORES = {"CRITICAL": 1.0, "HIGH": 0.75, "ELEVATED": 0.5, "LOW": 0.2}
_LIFE_SAFETY_SCORES = {
    "trapped": 1.0,
    "life-threatening": 1.0,
    "collapsed": 0.95,
    "missing": 0.9,
    "destroyed": 0.85,
    "injured": 0.75,
    "wounded": 0.75,
    "hurt": 0.65,
}
_HAZARD_SCORES = {
    "PEOPLE_TRAPPED": 1.0,
    "STRUCTURAL_DAMAGE": 0.95,
    "CHEMICAL": 0.9,
    "FIRE_OR_SMOKE": 0.85,
    "INJURY": 0.75,
    "FLOODWATER": 0.7,
    "BLOCKED_ACCESS": 0.5,
}
_CATEGORY_HAZARD_SCORES = {
    "EARTHQUAKE": 0.9,
    "BUILDING_COLLAPSE": 0.95,
    "LANDSLIDE": 0.85,
    "FIRE": 0.85,
    "CYCLONE": 0.8,
    "FLOOD": 0.7,
    "MEDICAL_EMERGENCY": 0.75,
    "ROAD_ACCIDENT": 0.65,
}


def validate_priority_weights(weights: Mapping) -> dict[str, float]:
    required = set(DEFAULT_PRIORITY_WEIGHTS)
    if not isinstance(weights, Mapping) or set(weights) != required:
        raise ValidationFailed(
            "Weights must include exactly: life_safety_risk, urgency, affected_population, "
            "hazard_level, evidence_confidence."
        )
    try:
        if any(isinstance(value, bool) for value in weights.values()):
            raise ValueError("boolean weight")
        normalized = {key: float(value) for key, value in weights.items()}
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationFailed("Priority weights must be finite, non-negative numbers.") from exc
    if any(not math.isfinite(value) or value < 0 for value in normalized.values()):
        raise ValidationFailed("Priority weights must be finite, non-negative numbers.")
    total = sum(normalized.values())
    if total <= 0 or abs(total - 1.0) > 0.01:
        raise ValidationFailed("Priority weights must sum to 1.0.")
    return normalized


def validate_priority_thresholds(thresholds: Mapping) -> dict[str, float]:
    required = set(DEFAULT_PRIORITY_THRESHOLDS)
    if not isinstance(thresholds, Mapping) or set(thresholds) != required:
        raise ValidationFailed("Thresholds must include exactly: CRITICAL, HIGH, MEDIUM, LOW.")
    try:
        if any(isinstance(value, bool) for value in thresholds.values()):
            raise ValueError("boolean threshold")
        values = {band: float(value) for band, value in thresholds.items()}
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationFailed("Priority thresholds must be finite numbers between 0 and 100.") from exc
    if any(not math.isfinite(value) or value < 0 or value > 100 for value in values.values()):
        raise ValidationFailed("Priority thresholds must be finite numbers between 0 and 100.")
    if not (values["CRITICAL"] > values["HIGH"] > values["MEDIUM"] > values["LOW"] == 0):
        raise ValidationFailed(
            "Thresholds must be strictly ordered CRITICAL > HIGH > MEDIUM > LOW, with LOW equal to 0."
        )
    return values


def priority_policy_guidance() -> dict:
    """Expose the scoring inputs alongside admin weights for model-backed extraction."""
    return {
        "factor_inputs": {
            "life_safety_risk": {
                "source": "severity_cues",
                "mapping": _LIFE_SAFETY_SCORES,
                "combination": "highest matching cue",
            },
            "urgency": {
                "source": "urgency",
                "mapping": _URGENCY_SCORES,
            },
            "affected_population": {
                "source": "affected_persons",
                "mapping": "min(count / 25, 1)",
            },
            "hazard_level": {
                "sources": ["hazards", "incident_category"],
                "hazard_mapping": _HAZARD_SCORES,
                "category_mapping": _CATEGORY_HAZARD_SCORES,
                "combination": "highest matching hazard or category",
            },
            "evidence_confidence": {
                "source": "confidence of extracted factor evidence",
                "application": "discount the base score in proportion to uncertainty",
            },
        },
        "score_method": (
            "Normalize configured weights over factors with supported evidence, "
            "calculate the weighted 0-100 score, then apply the evidence-confidence "
            "adjustment and the inclusive lower-bound thresholds."
        ),
    }


def _valid_confidence(confidence: object, relevant_fields: set[str]) -> list[float]:
    if not isinstance(confidence, Mapping):
        return []
    values = []
    for field in sorted(relevant_fields):
        value = confidence.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            normalized = float(value)
        except (OverflowError, ValueError):
            continue
        if math.isfinite(normalized) and 0.0 <= normalized <= 1.0:
            values.append(normalized)
    return values


def calculate_priority_score(
    facts: Mapping | None,
    confidence: Mapping | None = None,
    weights: Mapping | None = None,
) -> tuple[float | None, dict[str, float], dict]:
    """Return the score, normalized factor values, and an auditable contribution breakdown."""
    weights = validate_priority_weights(
        DEFAULT_PRIORITY_WEIGHTS if weights is None else weights
    )
    facts = facts if isinstance(facts, Mapping) else {}
    factors: dict[str, float] = {}

    factor_confidence_sources: dict[str, set[str]] = {}
    severity_cues = facts.get("severity_cues")
    if isinstance(severity_cues, (list, tuple, set)):
        scores = [
            _LIFE_SAFETY_SCORES[str(cue).strip().lower()]
            for cue in severity_cues
            if isinstance(cue, str) and str(cue).strip().lower() in _LIFE_SAFETY_SCORES
        ]
        if scores:
            factors["life_safety_risk"] = max(scores)
            factor_confidence_sources["life_safety_risk"] = {"severity_cues"}

    urgency = facts.get("urgency")
    if isinstance(urgency, str) and urgency.strip().upper() in _URGENCY_SCORES:
        factors["urgency"] = _URGENCY_SCORES[urgency.strip().upper()]
        factor_confidence_sources["urgency"] = {"urgency"}

    population = facts.get("affected_persons")
    if isinstance(population, int) and not isinstance(population, bool) and population >= 0:
        factors["affected_population"] = min(1.0, population / 25.0) if population < 25 else 1.0
        factor_confidence_sources["affected_population"] = {"affected_persons"}
    elif isinstance(population, float) and math.isfinite(population) and population >= 0:
        factors["affected_population"] = min(1.0, population / 25.0)
        factor_confidence_sources["affected_population"] = {"affected_persons"}

    hazard_values: list[float] = []
    hazard_confidence_sources: set[str] = set()
    hazards = facts.get("hazards")
    if isinstance(hazards, (list, tuple, set)):
        for hazard in hazards:
            if isinstance(hazard, str) and str(hazard).strip().upper() in _HAZARD_SCORES:
                hazard_values.append(_HAZARD_SCORES[str(hazard).strip().upper()])
                hazard_confidence_sources.add("hazards")
    category = facts.get("incident_category")
    if isinstance(category, str) and category.strip().upper() in _CATEGORY_HAZARD_SCORES:
        hazard_values.append(_CATEGORY_HAZARD_SCORES[category.strip().upper()])
        hazard_confidence_sources.add("incident_category")
    if hazard_values:
        factors["hazard_level"] = max(hazard_values)
        factor_confidence_sources["hazard_level"] = hazard_confidence_sources

    if not factors:
        return None, {}, {}

    available_weight = sum(weights[name] for name in factors)
    if available_weight <= 0:
        return None, {}, {}
    base_score = sum(weights[name] * factors[name] for name in factors) / available_weight

    relevant_confidence_fields = set().union(*(
        factor_confidence_sources[name] for name in factor_confidence_sources
    ))
    confidence_values = _valid_confidence(confidence, relevant_confidence_fields)
    confidence_multiplier = 1.0
    mean_confidence = None
    if confidence_values:
        mean_confidence = sum(confidence_values) / len(confidence_values)
        factors["evidence_confidence"] = mean_confidence
        confidence_weight = weights["evidence_confidence"]
        confidence_multiplier = 1.0 - confidence_weight * (1.0 - mean_confidence)

    base_score_points = base_score * 100.0
    risk_breakdown = {
        name: {
            "value": factors[name],
            "configured_weight": weights[name],
            "normalized_weight": weights[name] / available_weight,
            "score_points_before_confidence": (
                100.0 * weights[name] / available_weight * factors[name]
            ),
            "score_points": (
                100.0 * weights[name] / available_weight * factors[name]
                * confidence_multiplier
            ),
        }
        for name in factor_confidence_sources
    }
    breakdown = {
        "risk_factors": risk_breakdown,
        "base_score": round(base_score_points, 4),
        "confidence_adjustment": None,
    }
    if mean_confidence is not None:
        breakdown["confidence_adjustment"] = {
            "mean_confidence": mean_confidence,
            "configured_weight": weights["evidence_confidence"],
            "multiplier": confidence_multiplier,
            "score_points": base_score_points * (confidence_multiplier - 1.0),
        }
    score = round(max(0.0, min(100.0, base_score_points * confidence_multiplier)), 2)
    breakdown["final_score"] = score

    return score, factors, breakdown


def classify_priority(score: float | None, thresholds: Mapping | None = None) -> str | None:
    """Map a valid 0–100 score to exactly one band using inclusive lower bounds."""
    if score is None:
        return None
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValidationFailed("Priority score must be a finite number between 0 and 100.")
    try:
        score = float(score)
    except (OverflowError, ValueError) as exc:
        raise ValidationFailed("Priority score must be a finite number between 0 and 100.") from exc
    if not math.isfinite(score) or score < 0 or score > 100:
        raise ValidationFailed("Priority score must be a finite number between 0 and 100.")
    values = validate_priority_thresholds(
        DEFAULT_PRIORITY_THRESHOLDS if thresholds is None else thresholds
    )
    if score >= values["CRITICAL"]:
        return "CRITICAL"
    if score >= values["HIGH"]:
        return "HIGH"
    if score >= values["MEDIUM"]:
        return "MEDIUM"
    return "LOW"
