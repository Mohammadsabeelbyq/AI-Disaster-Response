import { useEffect, useState } from 'react';
import { AlertCircle, Check, LoaderCircle, Save } from 'lucide-react';
import {
  createPriorityConfig,
  getActivePriorityConfig,
  listPriorityConfigs,
} from '../../api/priority.js';

const weightFields = [
  ['life_safety_risk', 'Life safety risk'],
  ['urgency', 'Urgency'],
  ['affected_population', 'Affected population'],
  ['hazard_level', 'Hazard level'],
  ['evidence_confidence', 'Evidence confidence'],
];

const thresholdFields = [
  ['CRITICAL', 'Critical'],
  ['HIGH', 'High'],
  ['MEDIUM', 'Medium'],
  ['LOW', 'Low'],
];

function asDraft(config) {
  return {
    weights: Object.fromEntries(weightFields.map(([key]) => [key, String(config.weights[key])])),
    thresholds: Object.fromEntries(thresholdFields.map(([key]) => [key, String(config.thresholds[key])])),
    notes: '',
  };
}

function formatDate(value) {
  return new Date(value).toLocaleString();
}

export default function PriorityPolicyPage() {
  const [activeConfig, setActiveConfig] = useState(null);
  const [configs, setConfigs] = useState([]);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    let current = true;
    getActivePriorityConfig()
      .then((active) => listPriorityConfigs().then((history) => [active, history]))
      .then(([active, history]) => {
        if (!current) return;
        setActiveConfig(active);
        setDraft(asDraft(active));
        setConfigs(history);
      })
      .catch((error) => current && setMessage({ kind: 'error', text: error.message }))
      .finally(() => current && setLoading(false));
    return () => { current = false; };
  }, []);

  const weightTotal = draft
    ? Object.values(draft.weights).reduce((total, value) => total + Number(value || 0), 0)
    : 0;
  const thresholds = draft?.thresholds;
  const thresholdsValid = thresholds
    && Number(thresholds.CRITICAL) >= Number(thresholds.HIGH)
    && Number(thresholds.HIGH) >= Number(thresholds.MEDIUM)
    && Number(thresholds.MEDIUM) >= Number(thresholds.LOW)
    && Object.values(thresholds).every((value) => Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 100);
  const weightsValid = draft
    && Object.values(draft.weights).every((value) => Number.isFinite(Number(value)) && Number(value) >= 0)
    && Math.abs(weightTotal - 1) <= 0.01;
  const formValid = Boolean(weightsValid && thresholdsValid);

  function updateValue(group, key, value) {
    setDraft((current) => ({
      ...current,
      [group]: { ...current[group], [key]: value },
    }));
  }

  async function savePolicy(event) {
    event.preventDefault();
    if (!formValid || saving) return;

    setSaving(true);
    setMessage(null);
    try {
      const created = await createPriorityConfig({
        weights: Object.fromEntries(Object.entries(draft.weights).map(([key, value]) => [key, Number(value)])),
        thresholds: Object.fromEntries(Object.entries(draft.thresholds).map(([key, value]) => [key, Number(value)])),
        notes: draft.notes.trim() || null,
      });
      const [active, history] = await Promise.all([getActivePriorityConfig(), listPriorityConfigs()]);
      setActiveConfig(active);
      setConfigs(history);
      setDraft(asDraft(active));
      setMessage({ kind: 'success', text: `Policy ${created.version} is now active. New incident calculations will use it.` });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <section className="page-heading review-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow__line" />ADMINISTRATION</div>
          <h1>Priority policy<span className="heading-period">.</span></h1>
          <p>Create a versioned scoring policy. Existing incident classifications retain the rule version they were calculated with.</p>
        </div>
        {activeConfig && <span className="review-count">ACTIVE · {activeConfig.version}</span>}
      </section>

      {message && (
        <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.kind === 'error' ? <AlertCircle size={17} /> : <Check size={17} />}
          {message.text}
        </div>
      )}

      {loading ? (
        <div className="review-loading"><LoaderCircle className="location-spinner" size={20} />Loading policy…</div>
      ) : !activeConfig || !draft ? (
        <div className="panel review-empty">Priority policy could not be loaded.</div>
      ) : (
        <div className="priority-admin-layout">
          <form className="panel priority-policy-form" onSubmit={savePolicy}>
            <div className="panel-heading">
              <div><span className="section-kicker">NEW POLICY VERSION</span><h2>Scoring weights</h2></div>
              <span className="results-total">Weights total {weightTotal.toFixed(2)}</span>
            </div>
            <p className="priority-policy-help">Weights are proportions. They must be non-negative and total 1.00.</p>

            <div className="priority-weight-list">
              {weightFields.map(([key, label]) => (
                <label className="priority-weight-row" key={key}>
                  <span>{label}</span>
                  <span className="priority-number-field">
                    <input
                      aria-label={`${label} weight`}
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      value={draft.weights[key]}
                      onChange={(event) => updateValue('weights', key, event.target.value)}
                      required
                    />
                    <small>weight</small>
                  </span>
                </label>
              ))}
            </div>

            <div className="priority-threshold-section">
              <div className="panel-heading">
                <div><span className="section-kicker">CLASSIFICATION</span><h2>Band thresholds</h2></div>
                <span className="results-total">Score range 0–100</span>
              </div>
              <div className="priority-threshold-grid">
                {thresholdFields.map(([key, label]) => (
                  <label className="field" key={key}>
                    <span>{label} from</span>
                    <input
                      aria-label={`${label} threshold`}
                      type="number"
                      min="0"
                      max="100"
                      step="1"
                      value={draft.thresholds[key]}
                      onChange={(event) => updateValue('thresholds', key, event.target.value)}
                      required
                    />
                  </label>
                ))}
              </div>
              {!thresholdsValid && <p className="priority-validation">Thresholds must descend from Critical to Low and stay between 0 and 100.</p>}
            </div>

            <label className="field priority-notes-field">
              <span>Change note <small>OPTIONAL</small></span>
              <input
                type="text"
                maxLength="1000"
                value={draft.notes}
                onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))}
                placeholder="Reason for this policy update"
              />
            </label>

            <div className="form-actions priority-policy-actions">
              <span>Saving creates a new version and makes it active; previous versions remain in history.</span>
              <button className="button button--primary" type="submit" disabled={!formValid || saving}>
                {saving ? <LoaderCircle className="location-spinner" size={16} /> : <Save size={16} />}
                {saving ? 'Saving…' : 'Save new version'}
              </button>
            </div>
          </form>

          <aside className="priority-policy-aside">
            <section className="panel priority-active-panel">
              <div className="panel-heading">
                <div><span className="section-kicker">IN USE FOR NEW INCIDENTS</span><h2>{activeConfig.version}</h2></div>
                <span className="plan-status plan-status--approved">ACTIVE</span>
              </div>
              <dl className="priority-active-values">
                <div><dt>Created</dt><dd>{formatDate(activeConfig.created_at)}</dd></div>
                <div><dt>Change note</dt><dd>{activeConfig.notes || 'No note recorded'}</dd></div>
              </dl>
            </section>

            <section className="panel priority-history-panel">
              <div className="panel-heading">
                <div><span className="section-kicker">AUDIT TRAIL</span><h2>Policy versions</h2></div>
                <span className="results-total">{configs.length} total</span>
              </div>
              {configs.length === 0 ? <p className="priority-policy-help">No saved policy versions.</p> : (
                <ol className="priority-version-list">
                  {configs.map((config) => (
                    <li key={config.id} className={config.is_active ? 'priority-version priority-version--active' : 'priority-version'}>
                      <div className="priority-version__heading">
                        <strong>{config.version}</strong>
                        {config.is_active && <span>ACTIVE</span>}
                      </div>
                      <time dateTime={config.created_at}>{formatDate(config.created_at)}</time>
                      <small>{config.notes || 'No change note'}</small>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </aside>
        </div>
      )}
    </>
  );
}