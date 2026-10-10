import { useEffect, useState } from 'react';
import { AlertCircle, Check, CircleCheck, CircleX, LoaderCircle, Save, ShieldAlert } from 'lucide-react';
import {
  approveResponsePlan,
  confirmReport,
  correctExtraction,
  dismissReport,
  generateResponsePlan,
  getIncident,
  overrideIncidentPriority,
  listReports,
  rejectResponsePlan,
  startReportReview,
} from '../../api/reports.js';

const fields = [
  ['severity_cues', 'Severity cues'],
  ['hazards', 'Hazards'],
  ['requested_assistance', 'Requested assistance'],
  ['location_mentions', 'Location mentions'],
];

const factLabels = {
  incident_category: 'Incident category',
  urgency: 'Urgency',
  affected_persons: 'Affected persons',
  severity_cues: 'Severity cues',
  hazards: 'Hazards',
  requested_assistance: 'Requested assistance',
  location_mentions: 'Location mentions',
};

function formatFactValue(value) {
  if (value == null) return 'Unknown';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'Unknown';
  if (typeof value === 'number') return String(value);
  return String(value);
}

function draftFrom(report) {
  return { ...(report.extraction.corrected_facts || report.extraction.extracted_facts) };
}

export default function ReviewPage() {
  const [reports, setReports] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [incident, setIncident] = useState(null);
  const [plan, setPlan] = useState(null);
  const [decisionReason, setDecisionReason] = useState('');
  const [priorityReason, setPriorityReason] = useState('');
  const [priorityBand, setPriorityBand] = useState('HIGH');
  const selected = reports.find((report) => report.id === selectedId) || null;
  const factRows = (selected?.extraction ? [
    'incident_category', 'urgency', 'affected_persons', 'severity_cues', 'hazards', 'requested_assistance', 'location_mentions',
  ] : []).map((key) => {
    const extraction = selected.extraction;
    const originalValue = extraction.extracted_facts?.[key] ?? null;
    const correctedValue = extraction.corrected_facts?.[key] ?? null;
    const effectiveValue = extraction.effective_facts?.[key] ?? null;
    const evidence = extraction.evidence?.[key] || [];
    const confidence = extraction.confidence?.[key];
    const hasCorrection = JSON.stringify(originalValue) !== JSON.stringify(correctedValue) && correctedValue !== null;
    return {
      key,
      label: factLabels[key] || key.replaceAll('_', ' '),
      originalValue,
      correctedValue,
      effectiveValue,
      evidence,
      confidence,
      hasCorrection,
    };
  }).filter(({ originalValue, correctedValue, effectiveValue }) => {
    return originalValue !== null || correctedValue !== null || effectiveValue !== null;
  });

  useEffect(() => {
    listReports().then((items) => {
      setReports(items);
      if (items.length) {
        setSelectedId(items[0].id);
        setDraft(draftFrom(items[0]));
      }
    }).catch((error) => setMessage({ kind: 'error', text: error.message }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let active = true;
    if (!selected?.incident?.id) {
      setIncident(null);
      setPlan(null);
      return () => { active = false; };
    }
    getIncident(selected.incident.id).then((result) => {
      if (!active) return;
      setIncident(result);
      setPlan(result.plans.at(-1) || null);
    }).catch((error) => active && setMessage({ kind: 'error', text: error.message }));
    return () => { active = false; };
  }, [selected?.incident?.id]);

  function selectReport(report) {
    setSelectedId(report.id);
    setDraft(draftFrom(report));
    setMessage(null);
  }

  function updateReport(updated) {
    setReports((current) => current.map((report) => report.id === updated.id ? updated : report));
  }

  function setValue(key, value) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function saveCorrection(event) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const updated = await correctExtraction(selectedId, draft);
      setReports((current) => current.map((report) => report.id === updated.id ? updated : report));
      setDraft(draftFrom(updated));
      setMessage({ kind: 'success', text: 'Correction saved with review history.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  async function runWorkflowAction(action) {
    setWorkflowBusy(true);
    setMessage(null);
    try {
      if (action === 'review') {
        updateReport(await startReportReview(selectedId));
        setMessage({ kind: 'success', text: 'Report moved to UNDER_REVIEW.' });
      } else if (action === 'confirm') {
        const confirmed = await confirmReport(selectedId);
        setIncident(confirmed);
        updateReport({ ...selected, status: 'ACCEPTED', incident: { id: confirmed.id, status: confirmed.status } });
        setMessage({ kind: 'success', text: 'Incident confirmed. Generate a draft plan for coordinator review.' });
      } else if (action === 'dismiss') {
        const dismissed = await dismissReport(selectedId, decisionReason.trim() || null);
        updateReport(dismissed);
        setDecisionReason('');
        setMessage({ kind: 'success', text: 'Report dismissed. It will not enter response planning.' });
      } else if (action === 'generate') {
        const generated = await generateResponsePlan(incident.id);
        setPlan(generated);
        setIncident((current) => current ? { ...current, plans: [...current.plans, generated] } : current);
        setMessage({ kind: 'success', text: 'Draft generated from the current corrected facts.' });
      } else if (action === 'approve' || action === 'reject') {
        const decide = action === 'approve' ? approveResponsePlan : rejectResponsePlan;
        const decided = await decide(plan.id, decisionReason.trim() || null);
        setPlan(decided);
        setIncident((current) => current ? {
          ...current,
          plans: current.plans.map((item) => item.id === decided.id ? decided : item),
        } : current);
        setDecisionReason('');
        setMessage({ kind: 'success', text: action === 'approve'
          ? 'Plan approved. No dispatch was executed.' : 'Plan rejected and recorded.' });
      }
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setWorkflowBusy(false);
    }
  }

  async function applyPriorityOverride() {
    if (!incident) return;
    const trimmedReason = priorityReason.trim();
    if (!trimmedReason) {
      setMessage({ kind: 'error', text: 'Provide a reason before overriding the priority classification.' });
      return;
    }

    try {
      const updated = await overrideIncidentPriority(incident.id, {
        reason: trimmedReason,
        score: incident.priority_score ?? 0,
        band: priorityBand,
      });
      setIncident(updated);
      setPriorityReason('');
      setMessage({ kind: 'success', text: 'Priority override recorded and tied to the coordinator rationale.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    }
  }

  return (
    <>
      <section className="page-heading review-heading">
        <div><div className="eyebrow"><span className="eyebrow__line" />COORDINATOR WORKSPACE</div><h1>Report review<span className="heading-period">.</span></h1><p>Compare the original submission with evidence-backed extraction, then correct before planning.</p></div>
        <span className="review-count">{reports.length} REPORTS</span>
      </section>
      {message && <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.kind === 'error' ? <AlertCircle size={17} /> : <Check size={17} />}{message.text}</div>}
      {loading ? <div className="review-loading"><LoaderCircle className="location-spinner" size={20} />Loading reports…</div> : reports.length === 0 ? <div className="panel review-empty">No reports are available for review.</div> : (
        <div className="review-layout">
          <aside className="panel review-list" aria-label="Reports">
            <div className="review-list__header"><span className="section-kicker">INCOMING</span><strong>{reports.length}</strong></div>
            {reports.map((report) => (
              <button key={report.id} className={`review-item${selectedId === report.id ? ' review-item--active' : ''}`} onClick={() => selectReport(report)} type="button">
                <span className="review-item__meta"><strong>{report.disaster_type.replaceAll('_', ' ')}</strong><small>{new Date(report.submitted_at).toLocaleString()}</small></span>
                <span className="review-item__description">{report.description}</span>
                <span className="review-item__location">{report.location_name || `${report.latitude}, ${report.longitude}`}</span>
              </button>
            ))}
          </aside>

          {selected && draft && (
            <div className="review-detail">
              <section className="panel source-panel">
                <div className="panel-heading"><div><span className="section-kicker">SOURCE EVIDENCE</span><h2>Original submission</h2></div><span className="review-status">{selected.status}</span></div>
                <p className="source-description">{selected.description}</p>
                <dl className="source-meta"><div><dt>Reported category</dt><dd>{selected.disaster_type.replaceAll('_', ' ')}</dd></div><div><dt>Location</dt><dd>{selected.location_name || 'Not provided'}</dd></div><div><dt>Coordinates</dt><dd>{selected.latitude}, {selected.longitude}</dd></div><div><dt>Reference</dt><dd>{selected.id}</dd></div></dl>
                {selected.image && <a className="source-image-link" href={selected.image.url} target="_blank" rel="noreferrer">Open attached image</a>}
                <div className="workflow-actions">
                  {selected.status === 'SUBMITTED' && <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('review')}>Start review</button>}
                  {selected.status === 'UNDER_REVIEW' && (
                    <>
                      <button className="button button--primary" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('confirm')}><CircleCheck size={15} />Confirm incident</button>
                      <div className="workflow-dismiss">
                        <input aria-label="Dismissal reason" value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="Dismissal reason (optional)" />
                        <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('dismiss')}><CircleX size={15} />Dismiss</button>
                      </div>
                    </>
                  )}
                  {selected.status === 'ACCEPTED' && incident && <span className="incident-confirmed">CONFIRMED · {incident.id}</span>}
                  {selected.status === 'DISMISSED' && <span className="incident-dismissed">DISMISSED · excluded from planning</span>}
                </div>
              </section>

              {incident && (
                <section className="panel response-plan-panel">
                  <div className="panel-heading">
                    <div><span className="section-kicker">DOWNSTREAM WORKFLOW</span><h2>Response planning</h2></div>
                    <span className={`plan-status plan-status--${(plan?.status || incident.status).toLowerCase()}`}>{plan?.status || incident.status}</span>
                  </div>

                  <div style={{ marginBottom: '1rem', padding: '0.9rem 1rem', border: '1px solid rgba(148, 163, 184, 0.4)', borderRadius: '0.75rem', background: 'rgba(15, 23, 42, 0.32)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                      <strong>Priority classification</strong>
                      <span style={{ fontSize: '0.82rem', opacity: 0.8 }}>Rule v{incident.priority_rule_version || 'default'}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                      <span style={{ display: 'inline-flex', padding: '0.35rem 0.75rem', borderRadius: '999px', background: '#1d4ed8', color: '#fff', fontWeight: 700 }}>{incident.priority_band || 'LOW'}</span>
                      <strong>{Math.round(incident.priority_score ?? 0)} / 100</strong>
                    </div>
                    {incident.priority_is_overridden && (
                      <p style={{ margin: '0.75rem 0 0', color: '#fbbf24' }}>
                        Override reason: {incident.priority_override_reason || 'Not provided'}
                      </p>
                    )}
                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginTop: '0.9rem', flexWrap: 'wrap' }}>
                      <input
                        aria-label="Priority override reason"
                        value={priorityReason}
                        onChange={(event) => setPriorityReason(event.target.value)}
                        placeholder="Override reason"
                        style={{ flex: '1 1 200px', minWidth: '180px' }}
                      />
                      <select value={priorityBand} onChange={(event) => setPriorityBand(event.target.value)} aria-label="Override priority band" style={{ minWidth: '150px' }}>
                        <option value="LOW">LOW</option>
                        <option value="MEDIUM">MEDIUM</option>
                        <option value="HIGH">HIGH</option>
                        <option value="CRITICAL">CRITICAL</option>
                      </select>
                      <button className="button button--primary" type="button" onClick={applyPriorityOverride}>Apply override</button>
                    </div>
                  </div>

                  {!plan ? (
                    <>
                      <p className="plan-explanation">Generate a deterministic draft from the corrected facts. It will not name or assign responders because no verified resource registry is configured.</p>
                      <button className="button button--primary" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('generate')}>Generate draft plan</button>
                    </>
                  ) : (
                    <>
                      <div className="plan-source-facts"><strong>Facts used</strong><span>{Object.entries(plan.source_facts).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${Array.isArray(value) ? value.join(', ') : value ?? 'unknown'}`).join(' · ')}</span></div>
                      <div className="plan-action-list"><strong>Recommended coordinator actions</strong>{plan.recommended_actions.map((action) => <p key={action}>{action}</p>)}</div>
                      <div className="plan-gap"><ShieldAlert size={16} /><span>{plan.gaps.join(' ')}</span></div>
                      <p className="plan-safety-note">Approval records a human decision only. This prototype does not dispatch services or execute assignments.</p>
                      {plan.status === 'AWAITING_APPROVAL' && (
                        <div className="plan-decision-row">
                          <input aria-label="Plan decision reason" value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="Decision note (optional)" />
                          <button className="button button--primary" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('approve')}>Approve</button>
                          <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('reject')}>Reject</button>
                        </div>
                      )}
                      {plan.status === 'REJECTED' && (
                        <button className="button button--primary plan-regenerate" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('generate')}>
                          Generate revised draft
                        </button>
                      )}
                      {plan.decided_at && <p className="plan-decision-meta">Decision recorded {new Date(plan.decided_at).toLocaleString()}{plan.decision_reason ? ` · ${plan.decision_reason}` : ''}</p>}
                    </>
                  )}
                </section>
              )}

              <section className="panel extraction-panel">
                <div className="panel-heading"><div><span className="section-kicker">REPORT ANALYSIS · {selected.extraction.extractor_version}</span><h2>Review extracted facts</h2></div><span className="confidence-scale">Model score: 0–1</span></div>

                <div className="coordinator-note">
                  <strong>Coordinator review</strong>
                  <p>Correct extracted facts before planning. The original submission and first-pass extraction remain unchanged; only the effective facts used downstream are updated.</p>
                </div>

                <div className="fact-grid">
                  {factRows.map(({ key, label, originalValue, correctedValue, effectiveValue, evidence, confidence, hasCorrection }) => (
                    <div key={key} className={`fact-card${hasCorrection ? ' fact-card--corrected' : ''}`}>
                      <div className="fact-card__header">
                        <span>{label}</span>
                        {hasCorrection && <em>Corrected</em>}
                      </div>
                      <div className="fact-card__stack">
                        <div>
                          <small>Original extraction</small>
                          <strong>{formatFactValue(originalValue)}</strong>
                        </div>
                        {correctedValue !== null && (
                          <div>
                            <small>Coordinator value</small>
                            <strong>{formatFactValue(correctedValue)}</strong>
                          </div>
                        )}
                        <div>
                          <small>Used for planning</small>
                          <strong>{formatFactValue(effectiveValue)}</strong>
                        </div>
                      </div>
                      {(evidence.length || confidence != null) && (
                        <div className="fact-card__evidence">
                          <small>Evidence</small>
                          <ul>
                            {evidence.length ? evidence.map((item) => <li key={`${key}-${item}`}>{item}</li>) : <li>Evidence was not recorded for this field.</li>}
                          </ul>
                          {confidence != null && <span className="fact-card__score">Confidence: {confidence.toFixed(2)}</span>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="source-traceability">
                  <h3>Evidence traceability</h3>
                  {Object.keys(selected.extraction.evidence || {}).length ? (
                    <div className="trace-list">
                      {Object.entries(selected.extraction.evidence).map(([key, evidence]) => (
                        <p key={key}><strong>{factLabels[key] || key.replaceAll('_', ' ')}</strong><span>{evidence.join(' · ')}</span></p>
                      ))}
                    </div>
                  ) : (
                    <p>No extracted evidence is available.</p>
                  )}
                  {selected.image && (
                    <div className="source-traceability__image">
                      <span className="trace-badge">Traceable to attached image</span>
                      <a href={selected.image.url} target="_blank" rel="noreferrer">Open attached image</a>
                    </div>
                  )}
                  {selected.extraction.image_analysis_status !== 'NOT_PROVIDED' && (
                    <div className="image-analysis-state">
                      <span>Image analysis: <strong>{selected.extraction.image_analysis_status.replaceAll('_', ' ')}</strong></span>
                      {selected.extraction.image_cues?.length > 0 && selected.extraction.image_cues.map((cue) => (
                        <span key={`${cue.cue}-${cue.evidence}`}>{cue.cue} ({cue.confidence.toFixed(2)}) · {cue.evidence}</span>
                      ))}
                    </div>
                  )}
                </div>

                <form onSubmit={saveCorrection}>
                  <div className="review-fields">
                    <label className="field"><span>Incident category</span><input value={draft.incident_category || ''} onChange={(event) => setValue('incident_category', event.target.value || null)} placeholder="Unknown" /></label>
                    <label className="field"><span>Urgency</span><select value={draft.urgency || ''} onChange={(event) => setValue('urgency', event.target.value || null)}><option value="">Unknown</option><option value="ELEVATED">Elevated</option><option value="HIGH">High</option><option value="CRITICAL">Critical</option></select></label>
                    <label className="field"><span>Affected persons</span><input type="number" min="0" value={draft.affected_persons ?? ''} onChange={(event) => setValue('affected_persons', event.target.value === '' ? null : Number(event.target.value))} placeholder="Unknown" /></label>
                    {fields.map(([key, label]) => <label className="field" key={key}><span>{label}</span><input value={(draft[key] || []).join(', ')} onChange={(event) => setValue(key, event.target.value.split(',').map((part) => part.trim()).filter(Boolean))} placeholder="Unknown" /></label>)}
                  </div>
                  {selected.extraction.reviewed_at && <p className="review-history-note">Last corrected {new Date(selected.extraction.reviewed_at).toLocaleString()} · {selected.extraction.reviews.length} saved review{selected.extraction.reviews.length === 1 ? '' : 's'}</p>}
                  <div className="review-form-foot"><span className="review-safe-note">Submitted source text and first-pass extraction are preserved for audit and traceability.</span><button className="button button--primary" type="submit" disabled={saving}><Save size={16} />{saving ? 'Saving…' : 'Save correction'}</button></div>
                </form>
              </section>
            </div>
          )}
        </div>
      )}
    </>
  );
}