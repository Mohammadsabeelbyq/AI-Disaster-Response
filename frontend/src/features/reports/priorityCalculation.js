/**
 * Deterministic client-side priority calculation mirror for preliminary advisory triage (Epic 4.1 & 4.2).
 * Perfectly matches backend priority_service.py rules and weights.
 */

export const DEFAULT_PRIORITY_WEIGHTS = {
  life_safety_risk: 0.35,
  urgency: 0.25,
  affected_population: 0.2,
  hazard_level: 0.12,
  evidence_confidence: 0.08,
};

export const DEFAULT_PRIORITY_THRESHOLDS = {
  CRITICAL: 75.0,
  HIGH: 55.0,
  MEDIUM: 30.0,
  LOW: 0.0,
};

const LIFE_SAFETY_SCORES = {
  trapped: 1.0,
  'life-threatening': 1.0,
  collapsed: 0.95,
  missing: 0.9,
  destroyed: 0.85,
  injured: 0.75,
  wounded: 0.75,
  hurt: 0.65,
};

const URGENCY_SCORES = {
  CRITICAL: 1.0,
  HIGH: 0.75,
  ELEVATED: 0.5,
  LOW: 0.2,
};

const HAZARD_SCORES = {
  PEOPLE_TRAPPED: 1.0,
  STRUCTURAL_DAMAGE: 0.95,
  CHEMICAL: 0.9,
  FIRE_OR_SMOKE: 0.85,
  INJURY: 0.75,
  FLOODWATER: 0.7,
  BLOCKED_ACCESS: 0.5,
};

const CATEGORY_HAZARD_SCORES = {
  EARTHQUAKE: 0.9,
  BUILDING_COLLAPSE: 0.95,
  LANDSLIDE: 0.85,
  FIRE: 0.85,
  CYCLONE: 0.8,
  FLOOD: 0.7,
  MEDICAL_EMERGENCY: 0.75,
  ROAD_ACCIDENT: 0.65,
};

export function classifyPriority(score, thresholds = DEFAULT_PRIORITY_THRESHOLDS) {
  if (score == null || Number.isNaN(score)) return null;
  const num = Number(score);
  if (num >= thresholds.CRITICAL) return 'CRITICAL';
  if (num >= thresholds.HIGH) return 'HIGH';
  if (num >= thresholds.MEDIUM) return 'MEDIUM';
  return 'LOW';
}

export function calculatePreliminaryPriority(facts, confidence = null, weights = DEFAULT_PRIORITY_WEIGHTS) {
  if (!facts || typeof facts !== 'object') return null;

  const factors = {};
  const confidenceFields = [];

  // 1. Life safety risk (from severity cues)
  const cues = Array.isArray(facts.severity_cues) ? facts.severity_cues : [];
  const cueScores = cues
    .map((c) => LIFE_SAFETY_SCORES[String(c || '').trim().toLowerCase()])
    .filter((s) => s != null);
  if (cueScores.length > 0) {
    factors.life_safety_risk = Math.max(...cueScores);
    confidenceFields.push('severity_cues');
  }

  // 2. Urgency
  const urgencyKey = String(facts.urgency || '').trim().toUpperCase();
  if (URGENCY_SCORES[urgencyKey] != null) {
    factors.urgency = URGENCY_SCORES[urgencyKey];
    confidenceFields.push('urgency');
  }

  // 3. Affected population
  const population = Number(facts.affected_persons);
  if (facts.affected_persons != null && !Number.isNaN(population) && population >= 0) {
    factors.affected_population = Math.min(1.0, population / 25.0);
    confidenceFields.push('affected_persons');
  }

  // 4. Hazard level (from hazards list or incident category)
  const hazards = Array.isArray(facts.hazards) ? facts.hazards : [];
  const hazardScores = hazards
    .map((h) => HAZARD_SCORES[String(h || '').trim().toUpperCase()])
    .filter((s) => s != null);
  const categoryKey = String(facts.incident_category || '').trim().toUpperCase();
  if (CATEGORY_HAZARD_SCORES[categoryKey] != null) {
    hazardScores.push(CATEGORY_HAZARD_SCORES[categoryKey]);
  }
  if (hazardScores.length > 0) {
    factors.hazard_level = Math.max(...hazardScores);
    confidenceFields.push('hazards');
  }

  const factorKeys = Object.keys(factors);
  if (factorKeys.length === 0) return null;

  const availableWeight = factorKeys.reduce((sum, key) => sum + (weights[key] || 0), 0);
  if (availableWeight <= 0) return null;

  const baseScoreFraction = factorKeys.reduce(
    (sum, key) => sum + (weights[key] || 0) * factors[key],
    0,
  ) / availableWeight;
  const baseScorePoints = baseScoreFraction * 100.0;

  // Confidence discount
  let multiplier = 1.0;
  let meanConfidence = null;
  if (confidence && typeof confidence === 'object') {
    const validConfValues = confidenceFields
      .map((field) => confidence[field])
      .filter((v) => typeof v === 'number' && !Number.isNaN(v) && v >= 0 && v <= 1);
    if (validConfValues.length > 0) {
      meanConfidence = validConfValues.reduce((a, b) => a + b, 0) / validConfValues.length;
      multiplier = 1.0 - (weights.evidence_confidence || 0.08) * (1.0 - meanConfidence);
    }
  }

  const finalScore = Math.round(Math.max(0, Math.min(100, baseScorePoints * multiplier)) * 10) / 10;
  const band = classifyPriority(finalScore);

  const riskFactors = {};
  for (const key of factorKeys) {
    riskFactors[key] = {
      value: factors[key],
      configured_weight: weights[key],
      normalized_weight: weights[key] / availableWeight,
      score_points: Math.round(100.0 * (weights[key] / availableWeight) * factors[key] * multiplier * 10) / 10,
    };
  }

  return {
    score: finalScore,
    band,
    factors,
    breakdown: {
      risk_factors: riskFactors,
      confidence_adjustment: meanConfidence != null ? {
        mean_confidence: meanConfidence,
        score_points: Math.round(baseScorePoints * (multiplier - 1.0) * 10) / 10,
      } : null,
      final_score: finalScore,
    },
  };
}
