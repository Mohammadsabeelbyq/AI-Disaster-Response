import test from 'node:test';
import assert from 'node:assert/strict';
import { calculatePreliminaryPriority, classifyPriority } from './priorityCalculation.js';

test('classifies threshold boundaries correctly', () => {
  assert.equal(classifyPriority(100), 'CRITICAL');
  assert.equal(classifyPriority(75), 'CRITICAL');
  assert.equal(classifyPriority(74.9), 'HIGH');
  assert.equal(classifyPriority(55), 'HIGH');
  assert.equal(classifyPriority(54.9), 'MEDIUM');
  assert.equal(classifyPriority(30), 'MEDIUM');
  assert.equal(classifyPriority(29.9), 'LOW');
  assert.equal(classifyPriority(0), 'LOW');
  assert.equal(classifyPriority(null), null);
});

test('calculates priority for flooded scenario with trapped people', () => {
  const facts = {
    incident_category: 'FLOOD',
    severity_cues: ['trapped'],
    urgency: 'CRITICAL',
    affected_persons: 15,
    hazards: ['PEOPLE_TRAPPED'],
  };
  const result = calculatePreliminaryPriority(facts);
  assert.ok(result);
  assert.equal(result.band, 'CRITICAL');
  assert.ok(result.score >= 90);
  assert.equal(result.factors.urgency, 1.0);
  assert.equal(result.factors.life_safety_risk, 1.0);
  assert.equal(result.factors.affected_population, 0.6);
  assert.ok(result.breakdown.risk_factors.life_safety_risk);
});

test('uses the active admin weights and thresholds for the intake preview', () => {
  const facts = {
    severity_cues: ['injured'],
    urgency: 'LOW',
    hazards: ['PEOPLE_TRAPPED'],
  };
  const weights = {
    life_safety_risk: 0.05,
    urgency: 0.05,
    affected_population: 0.05,
    hazard_level: 0.8,
    evidence_confidence: 0.05,
  };
  const thresholds = { CRITICAL: 80, HIGH: 65, MEDIUM: 40, LOW: 0 };
  const result = calculatePreliminaryPriority(facts, null, weights, thresholds);
  assert.ok(result);
  assert.equal(result.band, 'CRITICAL');
  assert.ok(result.score > calculatePreliminaryPriority(facts).score);
});

test('handles missing factors safely', () => {
  assert.equal(calculatePreliminaryPriority({}), null);
  assert.equal(calculatePreliminaryPriority(null), null);
});
