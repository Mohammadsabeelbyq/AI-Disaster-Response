import { useEffect, useState } from 'react';
import { AlertCircle, Check, CircleCheck, CircleX, LoaderCircle, Save, ShieldAlert } from 'lucide-react';
import {
  approveResponsePlan,
  confirmReport,
  correctExtraction,
  correctReportLocation,
  decideReportRelationship,
  detectPotentialReportRelationships,
  dismissReport,
  generateResponsePlan,
  getIncident,
  getReport,
  linkReportToIncident,
  listIncidents,
  overrideIncidentPriority,
  listReports,
  listReportRelationships,
  mergeIncidentInto,
  rejectResponsePlan,
  startReportReview,
} from '../../api/reports.js';
import { validateCoordinates } from './mapLocation.js';

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

function locationDraftFrom(report) {
  return {
    latitude: String(report.location_correction?.latitude ?? report.latitude),
    longitude: String(report.location_correction?.longitude ?? report.longitude),
    location_name: report.location_correction?.location_name ?? report.location_name ?? '',
  };
}

export default function ReviewPage() {
  const [reports, setReports] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [locationDraft, setLocationDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [locationSaving, setLocationSaving] = useState(false);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [incident, setIncident] = useState(null);
  const [plan, setPlan] = useState(null);
  const [decisionReason, setDecisionReason] = useState('');
  const [priorityReason, setPriorityReason] = useState('');
  const [priorityBand, setPriorityBand] = useState('HIGH');
  const [relationshipBusy, setRelationshipBusy] = useState(false);
  const [relationshipReason, setRelationshipReason] = useState('');
  const [linkTargetId, setLinkTargetId] = useState('');
  const [linkReason, setLinkReason] = useState('');
  const [mergeTargetId, setMergeTargetId] = useState('');
  const [mergeReason, setMergeReason] = useState('');
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
    Promise.all([listReports(), listIncidents()]).then(([items, activeIncidents]) => {
      setReports(items);
      setIncidents(activeIncidents);
      setLinkTargetId(activeIncidents[0]?.id || '');
      if (items.length) {
        setSelectedId(items[0].id);
        if (items[0].extraction) setDraft(draftFrom(items[0]));
        setLocationDraft(locationDraftFrom(items[0]));
      }
    }).catch((error) => setMessage({ kind: 'error', text: error.message }))
      .finally(() => setLoading(false));
    listReportRelationships().then(setRelationships)
      .catch((error) => setMessage({ kind: 'error', text: error.message }));
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
    setDraft(report.extraction ? draftFrom(report) : null);
    setLocationDraft(locationDraftFrom(report));
    setMessage(null);
  }

  function updateReport(updated) {
    setReports((current) => current.map((report) => report.id === updated.id ? updated : report));
  }

  function setValue(key, value) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function findPotentialRelationships() {
    setRelationshipBusy(true);
    setMessage(null);
    try {
      await detectPotentialReportRelationships(selectedId);
      setRelationships(await listReportRelationships());
      setMessage({ kind: 'success', text: 'Potential relationships refreshed. No reports were merged.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setRelationshipBusy(false);
    }
  }

  async function decideRelationship(relationshipId, decision) {
    setRelationshipBusy(true);
    setMessage(null);
    try {
      const updated = await decideReportRelationship(relationshipId, decision, relationshipReason);
      setRelationships((current) => current.map((item) => item.id === updated.id ? updated : item));
      setRelationshipReason('');
      setMessage({
        kind: 'success',
        text: decision === 'confirm'
          ? 'Relationship confirmed and recorded. The reports remain separate.'
          : 'Potential relationship rejected and recorded.',
      });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setRelationshipBusy(false);
    }
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

  function updateLocationCoordinate(field, value) {
    setLocationDraft((current) => ({ ...current, [field]: value, location_name: '' }));
  }

  async function saveLocationCorrection(event) {
    event.preventDefault();
    const coordinates = validateCoordinates(locationDraft.latitude, locationDraft.longitude);
    if (coordinates.kind === 'error') {
      setMessage({ kind: 'error', text: coordinates.message });
      return;
    }

    setLocationSaving(true);
    setMessage(null);
    try {
      const updated = await correctReportLocation(selectedId, {
        ...coordinates,
        location_name: locationDraft.location_name.trim() || null,
      });
      updateReport(updated);
      setLocationDraft(locationDraftFrom(updated));
      setMessage({ kind: 'success', text: 'Map location saved. The original submitted coordinates are preserved.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setLocationSaving(false);
    }
  }

  async function linkSelectedReport() {
    const reason = linkReason.trim();
    if (!linkTargetId || !reason) {
      setMessage({ kind: 'error', text: 'Choose an incident and provide a reason for linking this report.' });
      return;
    }
    setWorkflowBusy(true);
    setMessage(null);
    try {
      await linkReportToIncident(linkTargetId, selected.id, reason);
      const [updated, target, activeIncidents] = await Promise.all([
        getReport(selected.id), getIncident(linkTargetId), listIncidents(),
      ]);
      updateReport(updated);
      setIncident(target);
      setIncidents(activeIncidents);
      setLinkReason('');
      setMessage({ kind: 'success', text: 'Original report preserved and linked to the selected incident.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setWorkflowBusy(false);
    }
  }

  async function mergeSelectedIncident() {
    const reason = mergeReason.trim();
    if (!incident || !mergeTargetId || !reason) {
      setMessage({ kind: 'error', text: 'Choose a canonical incident and provide a reason for merging.' });
      return;
    }
    setWorkflowBusy(true);
    setMessage(null);
    try {
      await mergeIncidentInto(incident.id, mergeTargetId, reason);
      const [updatedReport, mergedSource, activeIncidents] = await Promise.all([
        getReport(selected.id), getIncident(incident.id), listIncidents(),
      ]);
      updateReport(updatedReport);
      setIncident(mergedSource);
      setPlan(null);
      setIncidents(activeIncidents);
      setMergeReason('');
      setMessage({ kind: 'success', text: 'Incident merged into the canonical incident. Both source reports remain available.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setWorkflowBusy(false);
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
        const activeIncidents = await listIncidents();
        setIncidents(activeIncidents);
        if (!linkTargetId) setLinkTargetId(confirmed.id);
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

          {selected && draft && locationDraft && (
            <div className="review-detail">
              <section className="panel source-panel">
                <div className="panel-heading"><div><span className="section-kicker">SOURCE EVIDENCE</span><h2>Original submission</h2></div><span className="review-status">{selected.status}</span></div>
                <p className="source-description">{selected.description}</p>
                <dl className="source-meta"><div><dt>Reported category</dt><dd>{selected.disaster_type.replaceAll('_', ' ')}</dd></div><div><dt>Location</dt><dd>{selected.location_name || 'Not provided'}</dd></div><div><dt>Coordinates</dt><dd>{selected.latitude}, {selected.longitude}</dd></div><div><dt>Reference</dt><dd>{selected.id}</dd></div></dl>
                {selected.status !== 'DISMISSED' && (
                  <form className="review-location-editor" onSubmit={saveLocationCorrection}>
                    <div className="review-location-editor__heading">
                      <strong>Map location</strong>
                      <small>Corrections are saved separately; original submitted coordinates remain unchanged.</small>
                    </div>
                    <div className="field-grid">
                      <label className="field"><span>Latitude <b>*</b></span><input aria-label="Corrected latitude" type="number" step="any" value={locationDraft.latitude} onChange={(event) => updateLocationCoordinate('latitude', event.target.value)} /></label>
                      <label className="field"><span>Longitude <b>*</b></span><input aria-label="Corrected longitude" type="number" step="any" value={locationDraft.longitude} onChange={(event) => updateLocationCoordinate('longitude', event.target.value)} /></label>
                    </div>
                    <label className="field"><span>Corrected location name <small>OPTIONAL</small></span><input aria-label="Corrected location name" maxLength="255" value={locationDraft.location_name} onChange={(event) => setLocationDraft((current) => ({ ...current, location_name: event.target.value }))} /></label>
                    {selected.location_correction && <p className="location-hint">Last corrected {new Date(selected.location_correction.corrected_at).toLocaleString()}.</p>}
                    <button className="button button--quiet review-location-editor__save" type="submit" disabled={locationSaving}>
                      {locationSaving ? <LoaderCircle className="location-spinner" size={15} /> : <Save size={15} />}
                      {locationSaving ? 'Saving…' : 'Save map location'}
                    </button>
                  </form>
                )}
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
                {selected.incident_links?.length > 0 && (
                  <div className="report-relationship-note">
                    <strong>Linked to an incident</strong>
                    {selected.incident_links.map((relationship) => (
                      <p key={relationship.id}>
                        {relationship.relationship_type.replaceAll('_', ' ')} · {relationship.incident_id}
                        <span>{relationship.reason}</span>
                      </p>
                    ))}
                  </div>
                )}
                {selected.incident?.status === 'MERGED' && (
                  <div className="report-relationship-note" role="status">
                    <strong>This source incident was merged into {selected.incident.merged_into_id}.</strong>
                    <span>The original incident and report are retained for review.</span>
                  </div>
                )}
                {!selected.incident && selected.incident_links?.length === 0
                  && ['SUBMITTED', 'UNDER_REVIEW'].includes(selected.status) && (
                    <div className="report-link-controls">
                      <strong>Link this report to an existing incident</strong>
                      <p>The source report stays unchanged and remains retrievable.</p>
                      <div className="report-link-controls__row">
                        <select aria-label="Canonical incident" value={linkTargetId} onChange={(event) => setLinkTargetId(event.target.value)}>
                          <option value="">Choose incident</option>
                          {incidents.map((item) => <option key={item.id} value={item.id}>{item.priority_band || 'UNRATED'} · {item.report.location_name || item.report.description.slice(0, 60)} · {item.id.slice(0, 8)}</option>)}
                        </select>
                        <input aria-label="Report link reason" value={linkReason} onChange={(event) => setLinkReason(event.target.value)} placeholder="Reason for linking (required)" />
                        <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={linkSelectedReport}>Link report</button>
                      </div>
                    </div>
                  )}
                {selected.incident && incident && incident.status !== 'MERGED' && (
                  <div className="report-link-controls">
                    <strong>Merge duplicate incident into canonical incident</strong>
                    <p>This retains the source incident, its report, and the recorded merge history.</p>
                    <div className="report-link-controls__row">
                      <select aria-label="Merge target incident" value={mergeTargetId} onChange={(event) => setMergeTargetId(event.target.value)}>
                        <option value="">Choose canonical incident</option>
                        {incidents.filter((item) => item.id !== incident.id).map((item) => <option key={item.id} value={item.id}>{item.priority_band || 'UNRATED'} · {item.report.location_name || item.report.description.slice(0, 60)} · {item.id.slice(0, 8)}</option>)}
                      </select>
                      <input aria-label="Incident merge reason" value={mergeReason} onChange={(event) => setMergeReason(event.target.value)} placeholder="Reason for merging (required)" />
                      <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={mergeSelectedIncident}>Merge into selected</button>
                    </div>
                  </div>
                )}
                {incident?.report_links?.length > 0 && (
                  <div className="report-relationship-note">
                    <strong>Related original reports</strong>
                    {incident.report_links.map((relationship) => {
                      const relatedReport = reports.find((report) => report.id === relationship.report_id);
                      return (
                        <p key={relationship.id}>
                          <button className="header-link header-link--button" type="button" onClick={() => relatedReport && selectReport(relatedReport)}>
                            {relationship.relationship_type.replaceAll('_', ' ')} · {relationship.report_id}
                          </button>
                          <span>{relatedReport?.description || 'Source report is available by its report ID.'}</span>
                          <span>{relationship.reason}</span>
                        </p>
                      );
                    })}
                  </div>
                )}
              </section>

              <section className="panel report-relationships">
                <div className="panel-heading">
                  <div><span className="section-kicker">POTENTIAL RELATIONSHIPS</span><h2>Related reports</h2></div>
                  {selected.status !== 'DISMISSED' && (
                    <button className="button button--quiet" type="button" disabled={relationshipBusy} onClick={findPotentialRelationships}>
                      {relationshipBusy ? <LoaderCircle className="location-spinner" size={15} /> : null}
                      {relationshipBusy ? 'Checking…' : 'Find potential matches'}
                    </button>
                  )}
                </div>
                <p className="relationship-safety-note">Suggestions use submission time and corrected map distance. Semantic similarity is included only when enabled. A relationship decision never merges records.</p>
                {relationships.filter((item) => (
                  item.report.id === selected.id || item.related_report.id === selected.id
                )).length === 0 ? (
                  <p className="relationship-empty">No potential relationships are available for this report.</p>
                ) : (
                  <div className="relationship-list">
                    {relationships.filter((item) => (
                      item.report.id === selected.id || item.related_report.id === selected.id
                    )).map((item) => {
                      const other = item.report.id === selected.id ? item.related_report : item.report;
                      return (
                        <article className="relationship-item" key={item.id}>
                          <div className="relationship-item__heading">
                            <strong>{other.disaster_type.replaceAll('_', ' ')}</strong>
                            <span className={`relationship-status relationship-status--${item.status.toLowerCase()}`}>{item.status}</span>
                          </div>
                          <p>{other.description}</p>
                          <small>{other.location_name || `${other.latitude}, ${other.longitude}`} · {new Date(other.submitted_at).toLocaleString()}</small>
                          <div className="relationship-evidence">
                            <span>{item.evidence.time_difference_hours} h apart</span>
                            <span>{item.evidence.distance_km} km apart</span>
                            {item.evidence.semantic_matching_enabled && item.evidence.semantic_similarity != null && (
                              <span>Semantic similarity {Math.round(item.evidence.semantic_similarity * 100)}%</span>
                            )}
                          </div>
                          {item.status === 'PROPOSED' ? (
                            <div className="relationship-decision">
                              <input
                                aria-label="Relationship decision note"
                                value={relationshipReason}
                                onChange={(event) => setRelationshipReason(event.target.value)}
                                placeholder="Decision note (optional)"
                              />
                              <button className="button button--primary" type="button" disabled={relationshipBusy} onClick={() => decideRelationship(item.id, 'confirm')}>Confirm link</button>
                              <button className="button button--quiet" type="button" disabled={relationshipBusy} onClick={() => decideRelationship(item.id, 'reject')}>Reject</button>
                            </div>
                          ) : (
                            <small className="relationship-decision-meta">
                              Decision recorded {item.decided_at ? new Date(item.decided_at).toLocaleString() : ''}
                              {item.decision_reason ? ` · ${item.decision_reason}` : ''}
                            </small>
                          )}
                        </article>
                      );
                    })}
                  </div>
                )}
              </section>

              {incident && incident.status !== 'MERGED' && (
                <section className="panel response-plan-panel">
                  <div className="panel-heading">
                    <div><span className="section-kicker">DOWNSTREAM WORKFLOW</span><h2>Response planning</h2></div>
                    <span className={`plan-status plan-status--${(plan?.status || incident.status).toLowerCase()}`}>{plan?.status || incident.status}</span>
                  </div>

                  <div className="priority-review-card">
                    <div className="priority-review-header">
                      <div>
                        <strong>Priority Classification</strong>
                        <span className="priority-review-rule"> · Rule {incident.priority_rule_version || 'v1'} ({incident.priority_algorithm_version || 'priority-v1'})</span>
                      </div>
                      <span className="priority-advisory-tag">Advisory · Human review required</span>
                    </div>

                    <div className="priority-review-score-row">
                      <span className={`priority-badge priority-badge--${(incident.priority_band || 'LOW').toLowerCase()}`}>
                        {incident.priority_band || 'LOW'}
                      </span>
                      <strong className="priority-score-number">
                        {incident.priority_score != null ? `${Math.round(incident.priority_score)} / 100` : 'Not scored'}
                      </strong>
                    </div>

                    {incident.priority_breakdown?.risk_factors && Object.keys(incident.priority_breakdown.risk_factors).length > 0 && (
                      <div className="priority-factor-breakdown">
                        <div className="priority-factor-title">Contributing Factors Breakdown</div>
                        {Object.entries(incident.priority_breakdown.risk_factors).map(([key, item]) => {
                          const labels = {
                            life_safety_risk: 'Life-safety risk',
                            urgency: 'Urgency',
                            affected_population: 'Affected population',
                            hazard_level: 'Hazard level',
                          };
                          return (
                            <div key={key} className="priority-factor-row">
                              <span className="priority-factor-name">{labels[key] || key.replaceAll('_', ' ')}</span>
                              <div className="priority-factor-bar-bg" title={`${Math.round(item.value * 100)}% input · ${(item.configured_weight * 100).toFixed(0)}% weight`}>
                                <div className="priority-factor-bar-fill" style={{ width: `${Math.min(100, Math.max(0, item.value * 100))}%` }} />
                              </div>
                              <span className="priority-factor-pts">+{item.score_points.toFixed(1)} pts</span>
                            </div>
                          );
                        })}
                        {incident.priority_breakdown.confidence_adjustment && (
                          <div className="priority-confidence-note">
                            Confidence adjustment: {Math.round(incident.priority_breakdown.confidence_adjustment.mean_confidence * 100)}% confidence ({incident.priority_breakdown.confidence_adjustment.score_points.toFixed(1)} pts discount)
                          </div>
                        )}
                      </div>
                    )}

                    {incident.priority_is_overridden && (
                      <p className="priority-override-notice">
                        Overridden from calculated {incident.priority_original_band} ({Math.round(incident.priority_original_score ?? 0)}/100). Reason: {incident.priority_override_reason || 'Not provided'}
                      </p>
                    )}

                    <div className="priority-override-box">
                      <small style={{ color: 'var(--color-muted)', fontSize: '9px', fontWeight: 600 }}>COORDINATOR OVERRIDE</small>
                      <div className="priority-override-row">
                        <input
                          aria-label="Priority override reason"
                          value={priorityReason}
                          onChange={(event) => setPriorityReason(event.target.value)}
                          placeholder="Override reason (required)"
                        />
                        <select
                          value={priorityBand}
                          onChange={(event) => setPriorityBand(event.target.value)}
                          aria-label="Override priority band"
                        >
                          <option value="LOW">LOW</option>
                          <option value="MEDIUM">MEDIUM</option>
                          <option value="HIGH">HIGH</option>
                          <option value="CRITICAL">CRITICAL</option>
                        </select>
                        <button className="button button--primary" type="button" onClick={applyPriorityOverride}>
                          Apply override
                        </button>
                      </div>
                    </div>
                  </div>

                  {!plan ? (
                    <>
                      <p className="plan-explanation">Generate a deterministic draft from corrected facts and currently available registered resources. The coordinator remains responsible for review; approval does not dispatch or assign responders.</p>
                      <button className="button button--primary" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('generate')}>Generate draft plan</button>
                    </>
                  ) : (
                    <>
                      <div className="plan-source-facts"><strong>Facts used</strong><span>{Object.entries(plan.source_facts).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${Array.isArray(value) ? value.join(', ') : value ?? 'unknown'}`).join(' · ')}</span></div>
                      
                      {plan.rationale && (
                        <div className="plan-rationale" style={{ marginTop: '12px', padding: '10px', background: 'var(--color-surface-subtle, #f8f9fa)', borderRadius: '6px', borderLeft: '3px solid #2b7256' }}>
                          <strong style={{ display: 'block', fontSize: '11px', color: 'var(--color-ink-strong)' }}>Planner Rationale</strong>
                          <span style={{ fontSize: '12px', color: 'var(--color-ink-soft)' }}>{plan.rationale}</span>
                        </div>
                      )}

                      {plan.constraints_considered && plan.constraints_considered.length > 0 && (
                        <div className="plan-constraints" style={{ marginTop: '10px', fontSize: '11px', color: 'var(--color-muted)' }}>
                          <strong>Constraints Evaluated: </strong>{plan.constraints_considered.join(' · ')}
                        </div>
                      )}

                      {plan.response_option && plan.response_option.resources && plan.response_option.resources.length > 0 && (
                        <div className="plan-resources" style={{ marginTop: '12px' }}>
                          <strong style={{ fontSize: '11px' }}>Recommended Registered Resources</strong>
                          <ul style={{ margin: '6px 0 0', padding: 0, listStyle: 'none', display: 'grid', gap: '8px' }}>
                            {plan.response_option.resources.map((res) => (
                              <li key={res.resource_id} style={{ padding: '8px', border: '1px solid var(--color-line)', borderRadius: '4px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                  <strong>{res.name}</strong>
                                  <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', background: '#e1f5fe', color: '#0277bd', fontWeight: 600 }}>{res.status.toUpperCase()}</span>
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--color-muted)', marginTop: '2px' }}>
                                  Type: {res.type || 'Unknown'} · Distance: {res.distance_m != null ? `${res.distance_m}m` : 'Unknown'}
                                </div>
                                <div style={{ fontSize: '10px', color: 'var(--color-ink-soft)', marginTop: '2px' }}>
                                  Capabilities: {Array.isArray(res.capabilities) ? res.capabilities.join(', ') : res.capability}
                                </div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {plan.evidence && plan.evidence.length > 0 && (
                        <div className="plan-evidence" style={{ marginTop: '12px', padding: '10px', background: '#f5f5f5', borderRadius: '6px' }}>
                          <strong style={{ fontSize: '11px' }}>Inspectable Evidence Facts</strong>
                          {plan.evidence.map((ev) => (
                            <div key={ev.resource_id} style={{ marginTop: '6px' }}>
                              <small style={{ fontWeight: 600, color: 'var(--color-muted)' }}>Resource ID: {ev.resource_id}</small>
                              <ul style={{ margin: '4px 0 0 16px', padding: 0, fontSize: '11px' }}>
                                {ev.facts.map((fact, idx) => (
                                  <li key={idx} style={{ marginBottom: '2px' }}>{fact}</li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      )}

                      <div className="plan-action-list"><strong>Recommended coordinator actions</strong>{plan.recommended_actions.map((action) => <p key={action}>{action}</p>)}</div>
                      <div className="plan-resource-candidates">
                        <strong>Verified available resource candidates</strong>
                        {plan.resource_candidates.length ? plan.resource_candidates.map((resource) => (
                          <p key={resource.id}><b>{resource.code}</b> · {resource.name} · {resource.department_name} · matches {resource.matched_capabilities.join(', ')}</p>
                        )) : <p>No available registered resource matches the reported assistance needs.</p>}
                      </div>
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