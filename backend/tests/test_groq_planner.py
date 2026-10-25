from unittest.mock import Mock, patch

import pytest
import httpx

from app.services.groq_planner import (
    GroqPlannerError,
    generate_plan_draft,
    generate_report_analysis,
)


def test_groq_request_is_bounded_json_and_carries_database_snapshot():
    snapshot = {
        "region": {"latitude": 10.0, "longitude": 76.0},
        "eligible_resources": [{"id": "resource-1", "availability": "AVAILABLE"}],
    }
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": (
        '{"recommended_actions":["Verify access."],"resource_ids":["resource-1"],'
        '"rationale":"An eligible resource is available.",'
        '"constraints_considered":["distance"]}'
    )}}]}
    response.raise_for_status.return_value = None

    with patch("app.services.groq_planner.httpx.post", return_value=response) as post:
        draft = generate_plan_draft(
            snapshot,
            api_key="test-key",
            model="test-model",
            timeout_seconds=3,
            max_tokens=400,
            temperature=0,
        )

    kwargs = post.call_args.kwargs
    assert post.call_args.args[0].endswith("/chat/completions")
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")
    assert kwargs["headers"]["Authorization"].endswith("test-key")
    assert kwargs["timeout"] == 3
    assert kwargs["json"]["model"] == "test-model"
    assert kwargs["json"]["max_tokens"] == 400
    assert kwargs["json"]["response_format"] == {"type": "json_object"}
    assert '"eligible_resources"' in kwargs["json"]["messages"][1]["content"]
    assert draft.resource_ids == ["resource-1"]


def test_groq_report_analysis_receives_admin_weights_and_preserves_negation_context():
    snapshot = {
        "disaster_type_selected_by_reporter": "FLOOD",
        "description": "No one was injured.",
        "admin_priority_policy": {
            "version": "v4",
            "weights": {"life_safety_risk": 0.6, "urgency": 0.1},
            "thresholds": {"CRITICAL": 75, "HIGH": 55, "MEDIUM": 30, "LOW": 0},
        },
    }
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": (
        '{"facts":{"incident_category":"FLOOD","severity_cues":[],"urgency":null,'
        '"affected_persons":null,"hazards":[],"requested_assistance":[],"location_mentions":[]},'
        '"confidence":{},"evidence":{}}'
    )}}]}
    response.raise_for_status.return_value = None

    with patch("app.services.groq_planner.httpx.post", return_value=response) as post:
        analysis = generate_report_analysis(
            snapshot,
            api_key="test-key",
            model="test-model",
            timeout_seconds=3,
            max_tokens=400,
            temperature=0,
        )

    request = post.call_args.kwargs["json"]
    assert post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")
    assert post.call_args.kwargs["headers"]["Authorization"].endswith("test-key")
    assert '"admin_priority_policy"' in request["messages"][1]["content"]
    assert "including negation" in request["messages"][0]["content"]
    assert "non-negative integer or null" in request["messages"][0]["content"]
    assert analysis.facts.severity_cues == []


def test_groq_report_analysis_explains_schema_errors_without_logging_response_data(caplog):
    response = Mock()
    response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
        "content": (
            '{"facts":{"incident_category":"FLOOD","severity_cues":[],"urgency":null,'
            '"affected_persons":"private report detail","hazards":[],"requested_assistance":[],'
            '"location_mentions":[]},"confidence":{},"evidence":{}}'
        ),
    }}]}
    response.raise_for_status.return_value = None

    with patch("app.services.groq_planner.httpx.post", return_value=response):
        with pytest.raises(GroqPlannerError, match="facts.affected_persons:int_parsing"):
            generate_report_analysis(
                {},
                api_key="test-key",
                model="test-model",
                timeout_seconds=1,
                max_tokens=100,
                temperature=0,
            )

    assert "facts.affected_persons:int_parsing" in caplog.text
    assert "private report detail" not in caplog.text


def test_groq_report_analysis_warns_when_invalid_response_was_truncated():
    response = Mock()
    response.json.return_value = {"choices": [{"finish_reason": "length", "message": {
        "content": '{"facts":',
    }}]}
    response.raise_for_status.return_value = None

    with patch("app.services.groq_planner.httpx.post", return_value=response):
        with pytest.raises(GroqPlannerError, match="increase GROQ_MAX_TOKENS"):
            generate_report_analysis(
                {},
                api_key="test-key",
                model="test-model",
                timeout_seconds=1,
                max_tokens=100,
                temperature=0,
            )


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "Check GROQ_API_KEY"),
        (403, "Check GROQ_API_KEY"),
        (404, "Check GROQ_MODEL"),
        (429, "rate limit or quota"),
    ],
)
def test_groq_report_analysis_explains_provider_http_errors(status_code, expected):
    response = Mock()
    response.status_code = status_code
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "provider response", request=Mock(), response=response,
    )
    with patch("app.services.groq_planner.httpx.post", return_value=response):
        with pytest.raises(GroqPlannerError, match=expected):
            generate_report_analysis(
                {},
                api_key="test-key",
                model="test-model",
                timeout_seconds=1,
                max_tokens=100,
                temperature=0,
            )


@pytest.mark.parametrize("content", ["not json", "{}", "[]"])
def test_groq_rejects_malformed_or_incomplete_plan(content):
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    response.raise_for_status.return_value = None

    with patch("app.services.groq_planner.httpx.post", return_value=response):
        with pytest.raises(GroqPlannerError):
            generate_plan_draft(
                {},
                api_key="test-key",
                model="test-model",
                timeout_seconds=1,
                max_tokens=100,
                temperature=0,
            )