"""Groq-backed report intake analysis and policy-grounded priority preview."""
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.report import ReportAnalysisRequest, ReportAnalysisResult
from app.services.groq_planner import (
    GROQ_REPORT_ANALYSIS_VERSION,
    GroqPlannerError,
    generate_report_analysis,
)
from app.services.priority_service import (
    calculate_priority_score,
    classify_priority,
    priority_policy_guidance,
)

logger = logging.getLogger(__name__)
UNAVAILABLE_ANALYSIS_VERSION = "groq-report-analysis-unavailable-v1"


def analyze_report(db: Session, request: ReportAnalysisRequest) -> ReportAnalysisResult:
    from app.services.incident_service import get_active_priority_config

    settings = get_settings()
    policy = get_active_priority_config(db)
    policy_snapshot = {
        "version": policy.version,
        "weights": policy.weights,
        "thresholds": policy.thresholds,
    }
    snapshot = {
        "disaster_type_selected_by_reporter": request.disaster_type,
        "description": request.description,
        "location_name": request.location_name,
        "admin_priority_policy": policy_snapshot,
        "priority_policy_guidance": priority_policy_guidance(),
    }

    analysis_status = "GROQ"
    extractor_version = GROQ_REPORT_ANALYSIS_VERSION
    analysis_error = None
    confidence = {}
    evidence = {}
    if settings.groq_api_key:
        try:
            analysis = generate_report_analysis(
                snapshot,
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                timeout_seconds=settings.groq_timeout_seconds,
                max_tokens=settings.groq_max_tokens,
                temperature=settings.groq_temperature,
            )
            facts = analysis.facts.model_dump()
            source_text = " ".join(filter(None, (
                request.description,
                request.disaster_type,
                request.location_name,
            ))).casefold()
            evidence = {
                field: [
                    quote for quote in quotes
                    if quote.casefold() in source_text
                ]
                for field, quotes in analysis.evidence.items()
            }
            evidence = {field: quotes for field, quotes in evidence.items() if quotes}
            confidence = {
                field: value for field, value in analysis.confidence.items()
                if field in evidence
            }
        except GroqPlannerError as exc:
            logger.warning(
                "Groq report analysis failed; returning editable unknown facts: %s",
                exc,
            )
            analysis_status = "UNAVAILABLE"
            extractor_version = UNAVAILABLE_ANALYSIS_VERSION
            analysis_error = str(exc)
            facts = _empty_facts()
    else:
        analysis_status = "UNAVAILABLE"
        extractor_version = UNAVAILABLE_ANALYSIS_VERSION
        analysis_error = "Groq API key is not configured on the backend."
        facts = _empty_facts()

    score, _, breakdown = calculate_priority_score(
        facts, confidence, policy.weights)
    band = classify_priority(score, policy.thresholds)
    return ReportAnalysisResult(
        extractor_version=extractor_version,
        analysis_status=analysis_status,
        analysis_error=analysis_error,
        facts=facts,
        confidence=confidence,
        evidence=evidence,
        priority_policy=policy_snapshot,
        priority_score=score,
        priority_band=band,
        priority_breakdown=breakdown,
    )


def _empty_facts() -> dict:
    from app.schemas.report import ExtractedFacts

    return ExtractedFacts().model_dump()
