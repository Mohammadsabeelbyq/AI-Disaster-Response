import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertCircle, Check, CircleCheck, CircleX, LoaderCircle, Save, ShieldAlert, Trash2 } from 'lucide-react';
import {
  approveResponsePlan,
  assignResponsePlanResources,
  closeIncident,
  confirmReport,
  correctReportLocation,
  deleteReport,
  dismissReport,
  generateResponsePlan,
  getIncident,
  getReport,
  linkReportToIncident,
  listIncidents,
  overrideIncidentPriority,
  listReports,
  rejectResponsePlan,
  reopenDismissedReport,
  reopenIncident,
  releaseResponsePlanAssignment,
  unlinkReportFromIncident,
} from '../../api/reports.js';
import { listResources } from '../../api/resources.js';
import { validateCoordinates } from './mapLocation.js';

function locationDraftFrom(report) {
  return {
    latitude: String(report.location_correction?.latitude ?? report.latitude),
    longitude: String(report.location_correction?.longitude ?? report.longitude),
    location_name: report.location_correction?.location_name ?? report.location_name ?? '',
  };
}

export default function ReviewPage() {
  const [searchParams] = useSearchParams();
  const [reports, setReports] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [locationDraft, setLocationDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [locationSaving, setLocationSaving] = useState(false);
  const [workflowBusy, setWorkflowBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [incident, setIncident] = useState(null);
  const [plan, setPlan] = useState(null);
  const [decisionReason, setDecisionReason] = useState('');
  const [priorityReason, setPriorityReason] = useState('');
  const [incidentLifecycleReason, setIncidentLifecycleReason] = useState('');
  const [assignmentReason, setAssignmentReason] = useState('');
  const [assignmentResourceIds, setAssignmentResourceIds] = useState([]);
  const [assignmentBusy, setAssignmentBusy] = useState(false);
  const [assignmentResources, setAssignmentResources] = useState([]);
  const [assignmentResourcesLoading, setAssignmentResourcesLoading] = useState(false);
  const [priorityBand, setPriorityBand] = useState('HIGH');
  const [linkTargetId, setLinkTargetId] = useState('');
  const [linkReason, setLinkReason] = useState('');
  const [unlinkReason, setUnlinkReason] = useState('');
  const [deleteReason, setDeleteReason] = useState('');
  const selected = reports.find((report) => report.id === selectedId) || null;
  const selectedIncidentLink = selected?.incident_links?.[0] || null;
  const availableAssignmentResources = assignmentResources.filter(
    (resource) => resource.availability === 'AVAILABLE',
  );
  const unassignedResourceCount = availableAssignmentResources.filter((resource) => (
    resource.department?.is_active
    && resource.resource_type
    && resource.latitude != null
    && resource.longitude != null
  )).length;
  const linkableIncidents = incidents.filter((item) => (
    ['CONFIRMED', 'ACTIVE'].includes(item.status)
    && item.merged_into_id == null
    && item.id !== selected?.incident?.id
  ));
  const canLinkSelectedReport = selected
    && !selected.incident_links?.length
    && (
      ['SUBMITTED', 'UNDER_REVIEW'].includes(selected.status)
      || ['CONFIRMED', 'ACTIVE'].includes(selected.incident?.status)
    );
  const canUnlinkSelectedReport = Boolean(selectedIncidentLink);
  useEffect(() => {
    Promise.all([listReports(), listIncidents()]).then(([items, activeIncidents]) => {
      setReports(items);
      setIncidents(activeIncidents);
      setLinkTargetId(activeIncidents.find((item) => (
        ['CONFIRMED', 'ACTIVE'].includes(item.status)
      ))?.id || '');
      if (items.length) {
        const requestedReport = items.find((report) => report.id === searchParams.get('reportId'));
        const initialReport = requestedReport || items[0];
        setSelectedId(initialReport.id);
        setLocationDraft(locationDraftFrom(initialReport));
      }
    }).catch((error) => setMessage({ kind: 'error', text: error.message }))
      .finally(() => setLoading(false));
  }, [searchParams]);

  useEffect(() => {
    let active = true;
    if (!selected?.incident?.id) {
      setIncident(null);
      setPlan(null);
      setAssignmentResourceIds([]);
      return () => { active = false; };
    }
    getIncident(selected.incident.id).then((result) => {
      if (!active) return;
      setIncident(result);
      const latestPlan = result.plans.at(-1) || null;
      setPlan(latestPlan);
      const activeIds = new Set(
        (latestPlan?.assignments || [])
          .filter((assignment) => assignment.is_active)
          .map((assignment) => assignment.resource_id),
      );
      setAssignmentResourceIds(
        (latestPlan?.resource_candidates || [])
          .map((item) => item.id)
          .filter((id) => !activeIds.has(id)),
      );
    }).catch((error) => active && setMessage({ kind: 'error', text: error.message }));
    return () => { active = false; };
  }, [selected?.incident?.id]);

  useEffect(() => {
    let active = true;
    if (plan?.status !== 'APPROVED') {
      setAssignmentResources([]);
      setAssignmentResourcesLoading(false);
      return () => { active = false; };
    }
    setAssignmentResourcesLoading(true);
    listResources().then((resources) => {
      if (!active) return;
      setAssignmentResources(resources);
      const assignableIds = new Set(resources
        .filter((resource) => (
          resource.availability === 'AVAILABLE'
          && resource.department?.is_active
          && resource.resource_type
          && resource.latitude != null
          && resource.longitude != null
        ))
        .map((resource) => resource.id));
      setAssignmentResourceIds((current) => current.filter((id) => assignableIds.has(id)));
    }).catch((error) => {
      if (active) setMessage({ kind: 'error', text: error.message });
    }).finally(() => {
      if (active) setAssignmentResourcesLoading(false);
    });
    return () => { active = false; };
  }, [plan?.id, plan?.status]);

  function selectReport(report) {
    setSelectedId(report.id);
    setLocationDraft(locationDraftFrom(report));
    setLinkTargetId((current) => (
      incidents.some((item) => (
        item.id === current
        && item.id !== report.incident?.id
        && ['CONFIRMED', 'ACTIVE'].includes(item.status)
      ))
        ? current
        : incidents.find((item) => (
          item.id !== report.incident?.id
          && ['CONFIRMED', 'ACTIVE'].includes(item.status)
        ))?.id || ''
    ));
    setLinkReason('');
    setUnlinkReason('');
    setDeleteReason('');
    setMessage(null);
  }

  function updateReport(updated) {
    setReports((current) => current.map((report) => report.id === updated.id ? updated : report));
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
    const targetIncidentId = linkableIncidents.some((item) => item.id === linkTargetId)
      ? linkTargetId
      : linkableIncidents[0]?.id;
    if (!targetIncidentId || !reason) {
      setMessage({ kind: 'error', text: 'Choose an incident and provide a reason for linking this report.' });
      return;
    }
    setWorkflowBusy(true);
    setMessage(null);
    try {
      await linkReportToIncident(targetIncidentId, selected.id, reason);
      const [updated, target, activeIncidents] = await Promise.all([
        getReport(selected.id), getIncident(targetIncidentId), listIncidents(),
      ]);
      updateReport(updated);
      setIncident(target);
      const latestPlan = target.plans.at(-1) || null;
      setPlan(latestPlan);
      const assignedResourceIds = new Set(
        (latestPlan?.assignments || [])
          .filter((assignment) => assignment.is_active)
          .map((assignment) => assignment.resource_id),
      );
      setAssignmentResourceIds(
        (latestPlan?.resource_candidates || [])
          .map((resource) => resource.id)
          .filter((id) => !assignedResourceIds.has(id)),
      );
      setIncidents(activeIncidents);
      setLinkReason('');
      setMessage({
        kind: 'success',
        text: selected.incident
          ? 'Incident report linked to the selected canonical incident. Original records remain available.'
          : 'Report linked to the selected incident. The original report remains available.',
      });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setWorkflowBusy(false);
    }
  }

  async function unlinkSelectedReport() {
    const reason = unlinkReason.trim();
    if (!selectedIncidentLink || !reason) {
      setMessage({ kind: 'error', text: 'Provide a reason before unlinking this report.' });
      return;
    }
    const isMerge = selected?.incident?.status === 'MERGED';
    const confirmation = isMerge
      ? 'Unlink this report and restore its incident as a separate open incident?'
      : 'Remove this report from the linked incident?';
    if (!window.confirm(confirmation)) return;

    setWorkflowBusy(true);
    setMessage(null);
    try {
      await unlinkReportFromIncident(
        selectedIncidentLink.incident_id, selected.id, reason,
      );
      const [updated, activeIncidents] = await Promise.all([
        getReport(selected.id),
        listIncidents(),
      ]);
      updateReport(updated);
      setIncidents(activeIncidents);
      setLinkReason('');
      setUnlinkReason('');
      if (updated.incident?.id) {
        const restored = await getIncident(updated.incident.id);
        setIncident(restored);
        setPlan(restored.plans.at(-1) || null);
      } else {
        setIncident(null);
        setPlan(null);
      }
      setMessage({
        kind: 'success',
        text: isMerge
          ? 'The incident was unmerged and restored as a separate open incident.'
          : 'The report was unlinked and returned to the submitted queue.',
      });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setWorkflowBusy(false);
    }
  }

  async function deleteSelectedReport() {
    const reason = deleteReason.trim();
    if (!reason) {
      setMessage({ kind: 'error', text: 'Provide a reason before deleting this report.' });
      return;
    }
    if (!window.confirm(
      'Permanently delete this report and its incident workflow? Active assignments will be released, and other linked reports will return to the submitted queue.',
    )) return;

    setWorkflowBusy(true);
    setMessage(null);
    try {
      await deleteReport(selected.id, reason);
      const [nextReports, activeIncidents] = await Promise.all([
        listReports(),
        listIncidents(),
      ]);
      setReports(nextReports);
      setIncidents(activeIncidents);
      setSelectedId(nextReports[0]?.id || null);
      setLocationDraft(nextReports[0] ? locationDraftFrom(nextReports[0]) : null);
      setIncident(null);
      setPlan(null);
      setDeleteReason('');
      setMessage({ kind: 'success', text: 'Report and its dependent incident workflow were deleted.' });
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
      if (action === 'confirm') {
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
      } else if (action === 'reopen-report') {
        const reason = decisionReason.trim();
        if (!reason) throw new Error('Provide a reason before reopening this report.');
        const reopened = await reopenDismissedReport(selectedId, reason);
        updateReport(reopened);
        setDecisionReason('');
        setMessage({ kind: 'success', text: 'Report reopened and returned to coordinator review.' });
      } else if (action === 'generate') {
        if (!incident || !['CONFIRMED', 'ACTIVE'].includes(incident.status)) {
          throw new Error('Reopen the incident before generating a response plan.');
        }
        const generated = await generateResponsePlan(incident.id);
        setPlan(generated);
        setAssignmentResourceIds(generated.resource_candidates.map((item) => item.id));
        setIncident((current) => current ? { ...current, plans: [...current.plans, generated] } : current);
        setMessage({
          kind: 'success',
          text: generated.planner_provider === 'GROQ'
            ? `Groq generated the response-plan draft${generated.planner_model ? ` with ${generated.planner_model}` : ''}. Coordinator review is required.`
            : 'Groq was unavailable or not configured; a deterministic fallback draft was generated. Coordinator review is required.',
        });
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
          ? 'Plan approved.' : 'Plan rejected and recorded.' });
      } else if (action === 'close' || action === 'reopen') {
        const reason = incidentLifecycleReason.trim();
        if (!reason) {
          throw new Error(`Provide a reason before you ${action} this incident.`);
        }
        const updateStatus = action === 'close' ? closeIncident : reopenIncident;
        const updated = await updateStatus(incident.id, reason);
        setIncident(updated);
        setIncidents((current) => current.map((item) => item.id === updated.id ? updated : item));
        setIncidentLifecycleReason('');
        setMessage({
          kind: 'success',
          text: action === 'close'
            ? 'Incident closed. Reopen it if new information requires further response.'
            : 'Incident reopened and returned to active response.',
        });
      }
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setWorkflowBusy(false);
    }
  }

  async function assignSelectedResources() {
    const reason = assignmentReason.trim();
    if (!plan || !assignmentResourceIds.length || !reason) {
      setMessage({ kind: 'error', text: 'Select at least one available resource and provide an assignment reason.' });
      return;
    }
    setAssignmentBusy(true);
    setMessage(null);
    try {
      const updated = await assignResponsePlanResources(plan.id, assignmentResourceIds, reason);
      const activeIds = new Set(
        updated.assignments.filter((assignment) => assignment.is_active)
          .map((assignment) => assignment.resource_id),
      );
      setPlan(updated);
      setAssignmentResourceIds((current) => current.filter((id) => !activeIds.has(id)));
      setIncident((current) => current ? {
        ...current,
        plans: current.plans.map((item) => item.id === updated.id ? updated : item),
      } : current);
      setAssignmentReason('');
      try {
        setAssignmentResources(await listResources());
        setMessage({ kind: 'success', text: 'Resources assigned and recorded.' });
      } catch (error) {
        setMessage({
          kind: 'error',
          text: `Resources were assigned, but the available resource list could not be refreshed: ${error.message}`,
        });
      }
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setAssignmentBusy(false);
    }
  }

  async function releaseAssignment(assignmentId) {
    const reason = assignmentReason.trim();
    if (!plan || !reason) {
      setMessage({ kind: 'error', text: 'Provide a reason before releasing this resource assignment.' });
      return;
    }
    setAssignmentBusy(true);
    setMessage(null);
    try {
      const updated = await releaseResponsePlanAssignment(plan.id, assignmentId, reason);
      setPlan(updated);
      setIncident((current) => current ? {
        ...current,
        plans: current.plans.map((item) => item.id === updated.id ? updated : item),
      } : current);
      setAssignmentReason('');
      try {
        setAssignmentResources(await listResources());
        setMessage({ kind: 'success', text: 'Resource assignment released and recorded.' });
      } catch (error) {
        setMessage({
          kind: 'error',
          text: `The resource assignment was released, but the available resource list could not be refreshed: ${error.message}`,
        });
      }
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setAssignmentBusy(false);
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
        <div><div className="eyebrow"><span className="eyebrow__line" />COORDINATOR WORKSPACE</div><h1>Report review<span className="heading-period">.</span></h1><p>Confirm or dismiss reports, review linked context, and plan the response.</p></div>
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

          {selected && locationDraft && (
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
                  {['SUBMITTED', 'UNDER_REVIEW'].includes(selected.status) && (
                    <>
                      <button className="button button--primary" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('confirm')}><CircleCheck size={15} />Confirm incident</button>
                      <div className="workflow-dismiss">
                        <input aria-label="Dismissal reason" value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="Dismissal reason (optional)" />
                        <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('dismiss')}><CircleX size={15} />Dismiss report</button>
                      </div>
                    </>
                  )}
                  {selected.status === 'ACCEPTED' && incident && <span className="incident-confirmed">CONFIRMED · {incident.id}</span>}
                  {selected.status === 'DISMISSED' && (
                    <div className="workflow-dismiss">
                      <span className="incident-dismissed">DISMISSED · excluded from planning</span>
                      <input aria-label="Report reopen reason" value={decisionReason}
                        onChange={(event) => setDecisionReason(event.target.value)}
                        placeholder="Reason for reopening (required)" />
                      <button className="button button--primary" type="button" disabled={workflowBusy}
                        onClick={() => runWorkflowAction('reopen-report')}>Reopen report</button>
                    </div>
                  )}
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
                    <strong>This report belongs to a linked incident.</strong>
                    <span>Canonical incident: {selected.incident.merged_into_id}. The original incident and report remain available for history.</span>
                  </div>
                )}
                {canUnlinkSelectedReport && (
                  <div className="report-link-controls">
                    <strong>{selected.incident?.status === 'MERGED' ? 'Unlink / unmerge incident' : 'Unlink report'}</strong>
                    <p>{selected.incident?.status === 'MERGED'
                      ? 'Restore the source incident and its linked reports as a separate open incident.'
                      : 'Remove this report association and return the report to the submitted queue.'}</p>
                    <div className="report-link-controls__row">
                      <input
                        aria-label="Reason for unlinking report"
                        value={unlinkReason}
                        onChange={(event) => setUnlinkReason(event.target.value)}
                        placeholder="Reason for unlinking (required)"
                      />
                      <button className="button button--quiet" type="button" disabled={workflowBusy || !unlinkReason.trim()} onClick={unlinkSelectedReport}>
                        {selected.incident?.status === 'MERGED' ? 'Unlink / unmerge' : 'Unlink report'}
                      </button>
                    </div>
                  </div>
                )}
                {canLinkSelectedReport && linkableIncidents.length > 0 && (
                  <div className="report-link-controls">
                    <strong>Link report to an incident</strong>
                    <p>
                      Link this report to the canonical incident. If it already has a confirmed incident,
                      that incident is consolidated here while its report and history are preserved.
                    </p>
                    <div className="report-link-controls__row">
                      <select aria-label="Target incident" value={linkableIncidents.some((item) => item.id === linkTargetId) ? linkTargetId : ''} onChange={(event) => setLinkTargetId(event.target.value)}>
                        <option value="">Choose incident</option>
                        {linkableIncidents.map((item) => <option key={item.id} value={item.id}>{item.priority_band || 'UNRATED'} · {item.report.location_name || item.report.description.slice(0, 60)} · {item.id.slice(0, 8)}</option>)}
                      </select>
                      <input aria-label="Reason for linking report" value={linkReason} onChange={(event) => setLinkReason(event.target.value)} placeholder="Reason for linking (required)" />
                      <button className="button button--quiet" type="button" disabled={workflowBusy || !linkableIncidents.some((item) => item.id === linkTargetId)} onClick={linkSelectedReport}>Link to incident</button>
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
                <div className="report-delete-controls">
                  <input
                    aria-label="Reason for deleting report"
                    value={deleteReason}
                    onChange={(event) => setDeleteReason(event.target.value)}
                    placeholder="Reason for deletion (required)"
                  />
                  <button className="button button--danger" type="button" disabled={workflowBusy || !deleteReason.trim()} onClick={deleteSelectedReport}>
                    <Trash2 size={15} />Delete report
                  </button>
                </div>
              </section>

              {incident && incident.status !== 'MERGED' && (
                <section className="panel response-plan-panel">
                  <div className="panel-heading">
                    <div><span className="section-kicker">DOWNSTREAM WORKFLOW</span><h2>Plan the response</h2></div>
                    <span className={`plan-status plan-status--${(plan?.status || incident.status).toLowerCase()}`}>{plan?.status || incident.status}</span>
                  </div>
                  <details className="incident-lifecycle">
                    <summary>Incident lifecycle</summary>
                    <div className="plan-decision-row">
                      <input
                        aria-label={incident.status === 'CLOSED' ? 'Incident reopen reason' : 'Incident close reason'}
                        value={incidentLifecycleReason}
                        onChange={(event) => setIncidentLifecycleReason(event.target.value)}
                        placeholder={incident.status === 'CLOSED' ? 'Reason for reopening (required)' : 'Reason for closing (required)'}
                      />
                      {incident.status === 'CLOSED' ? (
                        <button className="button button--primary" type="button" disabled={workflowBusy}
                          onClick={() => runWorkflowAction('reopen')}>Reopen incident</button>
                      ) : ['CONFIRMED', 'ACTIVE'].includes(incident.status) ? (
                        <button className="button button--quiet" type="button" disabled={workflowBusy}
                          onClick={() => runWorkflowAction('close')}>Close incident</button>
                      ) : null}
                    </div>
                  </details>
                  {incident.status === 'CLOSED' && (
                    <p className="plan-explanation">This incident is closed. Reopen it before generating plans, approving plans, or assigning resources.</p>
                  )}

                  {incident.status !== 'CLOSED' && (
                  <>
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

                    <details className="priority-review-details">
                      <summary>Scoring details and coordinator override</summary>
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
                    </details>
                  </div>

                  {!plan ? (
                    <>
                      <p className="plan-explanation">Draft recommendations from this report, linked reports, and nearby available resources. Groq is tried first; the rules-based planner is used if it is unavailable. You review the draft before any assignment.</p>
                      <button className="button button--primary plan-generate-button" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('generate')}>
                        {workflowBusy ? <LoaderCircle className="location-spinner" size={15} /> : <ShieldAlert size={15} />}
                        Generate response plan
                      </button>
                    </>
                  ) : (
                    <>
                      <p className="plan-explanation">
                        Planner: <strong>{plan.planner_provider === 'GROQ' ? `Groq${plan.planner_model ? ` · ${plan.planner_model}` : ''}` : 'Deterministic fallback (Groq unavailable or not configured)'}</strong>
                      </p>
                      <details className="plan-audit-details">
                        <summary>Planning context and evidence</summary>
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

                      {plan.evidence && plan.evidence.length > 0 && (
                        <div className="plan-evidence">
                          <strong>Verified resource evidence</strong>
                          {plan.evidence.map((ev) => (
                            <div key={ev.resource_id}>
                              <small>Resource ID: {ev.resource_id}</small>
                              <ul>{ev.facts.map((fact, idx) => <li key={idx}>{fact}</li>)}</ul>
                            </div>
                          ))}
                        </div>
                      )}
                      </details>

                      <div className="plan-action-list"><strong>Recommended coordinator actions</strong>{plan.recommended_actions.map((action) => <p key={action}>{action}</p>)}</div>
                      <div className="plan-resource-candidates">
                        <strong>Verified available resource candidates</strong>
                        {plan.resource_candidates.length ? plan.resource_candidates.map((resource) => (
                          <p key={resource.id}><b>{resource.code}</b> · {resource.name} · {resource.department_name} · {resource.distance_m} m · matches {resource.matched_capabilities.join(', ')}</p>
                        )) : <p>No available registered resource matches the reported assistance needs.</p>}
                      </div>
                      <p className="plan-safety-note">Approval does not assign resources. Coordinators reserve available registered units separately; AI suggestions are advisory.</p>
                      {plan.status === 'APPROVED' && (
                        <div className="plan-assignment-controls">
                          <strong>Assign recommended resources</strong>
                          <p>All available registered resources are listed. AI-suggested resources are highlighted; you can also choose another unit. Availability and operational status are rechecked when you assign.</p>
                          <div className="plan-assignment-list">
                            {assignmentResourcesLoading ? (
                              <p className="assignment-guidance">Loading available resources…</p>
                            ) : availableAssignmentResources.length ? availableAssignmentResources.map((resource) => {
                              const aiSuggested = plan.resource_candidates.some(
                                (candidate) => candidate.id === resource.id,
                              );
                              const ineligibleReason = !resource.department?.is_active
                                ? 'Department inactive'
                                : !resource.resource_type || resource.latitude == null || resource.longitude == null
                                  ? 'Complete resource type and location before assigning'
                                  : null;
                              return (
                                <label
                                  key={resource.id}
                                  className={aiSuggested ? 'plan-assignment-list__suggested' : ''}
                                >
                                  <input
                                    type="checkbox"
                                    checked={assignmentResourceIds.includes(resource.id)}
                                    disabled={assignmentBusy || assignmentResourcesLoading || Boolean(ineligibleReason)}
                                    onChange={(event) => setAssignmentResourceIds((current) => (
                                      event.target.checked
                                        ? [...new Set([...current, resource.id])]
                                        : current.filter((id) => id !== resource.id)
                                    ))}
                                  />
                                  <span>
                                    <b>{resource.code}</b> · {resource.name} · {resource.department.name}
                                    <small>{resource.capabilities.join(', ')}</small>
                                    {ineligibleReason && <small>{ineligibleReason}</small>}
                                  </span>
                                  {aiSuggested && <strong className="plan-assignment-list__badge">AI suggested</strong>}
                                </label>
                              );
                            }) : (
                              <p className="assignment-guidance">No currently available resources can be assigned.</p>
                            )}
                          </div>
                          <input
                            aria-label="Resource assignment reason"
                            value={assignmentReason}
                            onChange={(event) => setAssignmentReason(event.target.value)}
                            placeholder="Assignment reason (required)"
                          />
                          {unassignedResourceCount === 0 ? (
                            <p className="assignment-guidance" role="status">
                              No available resources are currently eligible for assignment. Update the registry or release an active assignment.
                            </p>
                          ) : !assignmentResourceIds.length ? (
                            <p className="assignment-guidance">Select at least one available resource to continue.</p>
                          ) : !assignmentReason.trim() ? (
                            <p className="assignment-guidance">Enter an assignment reason to continue.</p>
                          ) : null}
                          <button
                            className="button button--primary"
                            type="button"
                            disabled={assignmentBusy || !assignmentResourceIds.length || !assignmentReason.trim()}
                            aria-busy={assignmentBusy}
                            onClick={assignSelectedResources}
                          >
                            {assignmentBusy ? (
                              <><LoaderCircle className="location-spinner" size={15} />Assigning resources…</>
                            ) : unassignedResourceCount === 0 ? (
                              'No available resources'
                            ) : (
                              'Assign selected resources'
                            )}
                          </button>
                        </div>
                      )}
                      {plan.assignments?.length > 0 && (
                        <div className="plan-assignment-history">
                          <strong>Assignment history</strong>
                          {plan.assignments.map((assignment) => {
                            const resource = assignmentResources.find(
                              (item) => item.id === assignment.resource_id,
                            ) || plan.resource_candidates.find(
                              (item) => item.id === assignment.resource_id,
                            );
                            return (
                              <div key={assignment.id}>
                                <span>{resource?.code || assignment.resource_id} · {assignment.is_active ? 'Active' : 'Released'} · {assignment.reason}</span>
                                {assignment.is_active && (
                                  <button
                                    className="button button--quiet"
                                    type="button"
                                    disabled={assignmentBusy}
                                    onClick={() => releaseAssignment(assignment.id)}
                                  >
                                    Release
                                  </button>
                                )}
                                {assignment.release_reason && <small>Release reason: {assignment.release_reason}</small>}
                              </div>
                            );
                          })}
                        </div>
                      )}
                      {plan.status === 'AWAITING_APPROVAL' && (
                        <div className="plan-decision-row">
                          <input aria-label="Plan decision reason" value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="Decision note (optional)" />
                          <button className="button button--primary" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('approve')}>Approve</button>
                          <button className="button button--quiet" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('reject')}>Reject</button>
                        </div>
                      )}
                      {['REJECTED', 'APPROVED'].includes(plan.status) && (
                        <button className="button button--primary plan-regenerate" type="button" disabled={workflowBusy} onClick={() => runWorkflowAction('generate')}>
                          {plan.status === 'APPROVED' ? 'Refresh recommendations' : 'Generate revised draft'}
                        </button>
                      )}
                      {plan.planner_provider !== 'GROQ' && (
                        <button className="button button--quiet plan-regenerate" type="button" disabled={workflowBusy}
                          onClick={() => runWorkflowAction('generate')}>
                          {workflowBusy ? 'Retrying…' : 'Try Groq again (new draft)'}
                        </button>
                      )}
                      {plan.decided_at && <p className="plan-decision-meta">Decision recorded {new Date(plan.decided_at).toLocaleString()}{plan.decision_reason ? ` · ${plan.decision_reason}` : ''}</p>}
                    </>
                  )}
                  </>
                  )}
                </section>
              )}

              {selected.extraction && (
                <section className="panel report-analysis-shortcut">
                  <div>
                    <span className="section-kicker">REPORT ANALYSIS</span>
                    <p>View extracted evidence, coordinator changes, and the facts used for planning.</p>
                  </div>
                  <Link className="button button--quiet" to={`/report-analysis?reportId=${encodeURIComponent(selected.id)}`}>
                    Open report analysis
                    {selected.extraction.reviews?.length > 0 && <span className="report-analysis-change-count">{selected.extraction.reviews.length} saved</span>}
                  </Link>
                </section>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}