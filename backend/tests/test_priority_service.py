import math

import pytest

from app.services.errors import ValidationFailed
from app.services.priority_service import (
    DEFAULT_PRIORITY_THRESHOLDS,
    DEFAULT_PRIORITY_WEIGHTS,
    calculate_priority_score,
    classify_priority,
    validate_priority_thresholds,
    validate_priority_weights,
)


def test_representative_life_safety_urgency_and_hazard_raise_score():
    low_score, low_factors = calculate_priority_score(
        {"incident_category": "FLOOD", "urgency": "ELEVATED"})
    high_score, high_factors = calculate_priority_score({
        "incident_category": "BUILDING_COLLAPSE",
        "urgency": "CRITICAL",
        "severity_cues": ["trapped", "injured"],
        "hazards": ["STRUCTURAL_DAMAGE", "PEOPLE_TRAPPED"],
    })

    assert high_score is not None and low_score is not None
    assert high_score > low_score
    assert high_factors["life_safety_risk"] == 1.0
    assert high_factors["urgency"] == 1.0
    assert high_factors["hazard_level"] == 1.0
    assert "life_safety_risk" not in low_factors


def test_life_safety_and_urgency_each_increase_priority():
    urgency_only, _ = calculate_priority_score({"urgency": "HIGH"})
    life_safety_added, _ = calculate_priority_score({
        "urgency": "HIGH", "severity_cues": ["trapped"],
    })
    elevated, _ = calculate_priority_score({"urgency": "ELEVATED"})
    critical, _ = calculate_priority_score({"urgency": "CRITICAL"})

    assert life_safety_added > urgency_only
    assert critical > elevated


def test_affected_population_increases_score_at_documented_scale():
    scores = [
        calculate_priority_score({"affected_persons": count})[0]
        for count in (0, 5, 25, 100)
    ]

    assert scores == [0.0, 20.0, 100.0, 100.0]


def test_missing_or_unknown_inputs_do_not_create_a_score_or_factor_values():
    score, factors = calculate_priority_score({
        "urgency": "IMMEDIATE",
        "affected_persons": "many",
        "hazards": ["UNMAPPED_HAZARD"],
        "severity_cues": ["possibly dangerous"],
        "incident_category": "OTHER",
    })

    assert score is None
    assert factors == {}
    assert calculate_priority_score({}, {"unknown": 0.99}) == (None, {})
    assert calculate_priority_score({"affected_persons": 10**1000})[0] == 100.0


def test_confidence_only_adjusts_a_supported_risk_score():
    facts = {"urgency": "HIGH"}
    without_confidence, _ = calculate_priority_score(facts)
    low_confidence, low_factors = calculate_priority_score(facts, {"urgency": 0.2})
    high_confidence, high_factors = calculate_priority_score(facts, {"urgency": 0.9})
    confidence_without_risk, no_risk_factors = calculate_priority_score({}, {"urgency": 1.0})

    assert without_confidence == 75.0
    assert low_confidence < high_confidence <= without_confidence
    assert low_factors["evidence_confidence"] == 0.2
    assert high_factors["evidence_confidence"] == 0.9
    assert confidence_without_risk is None
    assert no_risk_factors == {}


def test_identical_inputs_and_rules_produce_identical_results():
    facts = {"severity_cues": ["injured"], "urgency": "HIGH", "affected_persons": 12}
    confidence = {"urgency": 0.75, "affected_persons": 0.9}

    assert calculate_priority_score(facts, confidence) == calculate_priority_score(facts, confidence)


def test_classification_covers_each_threshold_boundary_inclusively():
    assert classify_priority(75) == "CRITICAL"
    assert classify_priority(math.nextafter(75.0, 0.0)) == "HIGH"
    assert classify_priority(55) == "HIGH"
    assert classify_priority(math.nextafter(55.0, 0.0)) == "MEDIUM"
    assert classify_priority(30) == "MEDIUM"
    assert classify_priority(math.nextafter(30.0, 0.0)) == "LOW"
    assert classify_priority(0) == "LOW"
    assert classify_priority(None) is None


def test_classification_accepts_custom_configured_thresholds():
    custom = {"CRITICAL": 90, "HIGH": 65, "MEDIUM": 25, "LOW": 0}

    assert classify_priority(90, custom) == "CRITICAL"
    assert classify_priority(65, custom) == "HIGH"
    assert classify_priority(25, custom) == "MEDIUM"
    assert classify_priority(24.99, custom) == "LOW"


@pytest.mark.parametrize("score", [-0.01, 100.01, math.nan, math.inf, -math.inf])
def test_classification_rejects_scores_outside_valid_range(score):
    with pytest.raises(ValidationFailed):
        classify_priority(score)


def test_priority_rule_configuration_is_validated():
    assert validate_priority_weights(DEFAULT_PRIORITY_WEIGHTS) == DEFAULT_PRIORITY_WEIGHTS
    assert validate_priority_thresholds(DEFAULT_PRIORITY_THRESHOLDS) == DEFAULT_PRIORITY_THRESHOLDS

    invalid_thresholds = [
        {"CRITICAL": 75, "HIGH": 75, "MEDIUM": 30, "LOW": 0},
        {"CRITICAL": 75, "HIGH": 55, "MEDIUM": 30, "LOW": 1},
    ]
    for thresholds in invalid_thresholds:
        with pytest.raises(ValidationFailed):
            validate_priority_thresholds(thresholds)
    with pytest.raises(ValidationFailed):
        validate_priority_weights({**DEFAULT_PRIORITY_WEIGHTS, "urgency": -0.1})
    with pytest.raises(ValidationFailed):
        validate_priority_weights({})
