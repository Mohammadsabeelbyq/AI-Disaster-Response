import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertCircle, ArrowLeft, Check, LoaderCircle, Save } from 'lucide-react';
import { correctExtraction, getReport } from '../../api/reports.js';

const FACTS = [
  ['incident_category', 'Incident category'],
  ['urgency', 'Urgency'],
  ['affected_persons', 'Affected persons'],
  ['severity_cues', 'Severity cues'],
  ['hazards', 'Hazards'],
  ['requested_assistance', 'Requested assistance'],
  ['location_mentions', 'Location mentions'],
];

const LIST_FACTS = new Set([
  'severity_cues',
  'hazards',
  'requested_assistance',
  'location_mentions',
]);

function formatFact(value) {
  if (value == null || value === '') return 'Not identified';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'Not identified';
  return String(value);
}

function draftFrom(report) {
  return { ...(report.extraction.corrected_facts || report.extraction.extracted_facts) };
}

export default function ReportAnalysisPage() {
  const [searchParams] = useSearchParams();
  const reportId = searchParams.get('reportId');
  const [report, setReport] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    let active = true;
    setMessage(null);
    if (!reportId) {
      setReport(null);
      setDraft(null);
      setLoading(false);
      return () => { active = false; };
    }

    setLoading(true);
    setReport(null);
    setDraft(null);
    setMessage(null);
    getReport(reportId).then((result) => {
      if (!active) return;
      setReport(result);
      setDraft(result.extraction ? draftFrom(result) : null);
    }).catch((error) => {
      if (active) setMessage({ kind: 'error', text: error.message });
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [reportId]);

  const changes = useMemo(() => {
    if (!report?.extraction) return [];
    const extraction = report.extraction;
    return FACTS.map(([key, label]) => ({
      key,
      label,
      original: extraction.extracted_facts?.[key] ?? null,
      effective: extraction.effective_facts?.[key] ?? null,
    })).filter(({ original, effective }) => JSON.stringify(original) !== JSON.stringify(effective));
  }, [report]);

  async function saveCorrection(event) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const updated = await correctExtraction(reportId, draft);
      setReport(updated);
      setDraft(draftFrom(updated));
      setMessage({ kind: 'success', text: 'Changes saved. These effective facts will be used for planning.' });
    } catch (error) {
      setMessage({ kind: 'error', text: error.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="report-analysis-page">
      <Link className="button button--quiet report-analysis-back" to={`/review${reportId ? `?reportId=${encodeURIComponent(reportId)}` : ''}`}>
        <ArrowLeft size={15} />Back to review
      </Link>
      <section className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow__line" />REPORT ANALYSIS</div>
          <h1>Analysis & changes<span className="heading-period">.</span></h1>
          {report && <p>{report.disaster_type.replaceAll('_', ' ')} · {report.location_name || 'Location not provided'} · {report.id}</p>}
        </div>
      </section>

      {message && (
        <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>
          {message.kind === 'error' ? <AlertCircle size={17} /> : <Check size={17} />}
          {message.text}
        </div>
      )}
      {loading ? (
        <div className="review-loading"><LoaderCircle className="location-spinner" size={20} />Loading report analysis…</div>
      ) : !report ? (
        <section className="panel report-analysis-empty">
          <p>{reportId ? 'This report could not be loaded.' : 'Choose a report from the coordinator review workspace to view its analysis.'}</p>
          <Link className="button button--primary" to="/review">Open report review</Link>
        </section>
      ) : !report.extraction ? (
        <section className="panel report-analysis-empty">No extracted analysis is available for this report.</section>
      ) : (
        <>
          <section className="panel report-analysis-changes">
            <div className="panel-heading">
              <div>
                <span className="section-kicker">COORDINATOR CHANGES</span>
                <h2>{changes.length ? `${changes.length} fact${changes.length === 1 ? '' : 's'} changed` : 'No changes saved yet'}</h2>
              </div>
              <span className="report-analysis-version">{report.extraction.extractor_version}</span>
            </div>
            {changes.length ? (
              <div className="report-analysis-diff">
                {changes.map(({ key, label, original, effective }) => (
                  <article key={key}>
                    <strong>{label}</strong>
                    <div><small>Extracted</small><span>{formatFact(original)}</span></div>
                    <div><small>Used for planning</small><span>{formatFact(effective)}</span></div>
                  </article>
                ))}
              </div>
            ) : (
              <p className="plan-explanation">The extracted facts are still unchanged. Any corrections you save here will be shown as a comparison.</p>
            )}
            {report.extraction.reviewed_at && (
              <p className="review-history-note">
                Last corrected {new Date(report.extraction.reviewed_at).toLocaleString()} · {report.extraction.reviews.length} saved review{report.extraction.reviews.length === 1 ? '' : 's'}
              </p>
            )}
          </section>

          <section className="panel report-analysis-facts">
            <div className="panel-heading">
              <div><span className="section-kicker">EXTRACTED EVIDENCE</span><h2>Facts used by the planner</h2></div>
              <span className="confidence-scale">Support score: 0–1</span>
            </div>
            <div className="report-analysis-fact-list">
              {FACTS.map(([key, label]) => {
                const value = report.extraction.effective_facts?.[key] ?? null;
                const confidence = report.extraction.confidence?.[key];
                const evidence = report.extraction.evidence?.[key] || [];
                return (
                  <article key={key}>
                    <div><strong>{label}</strong><span>{formatFact(value)}</span></div>
                    <small>{confidence == null ? 'No support score' : `Support ${confidence.toFixed(2)}`}</small>
                    {evidence.length > 0 && <p>{evidence.join(' · ')}</p>}
                  </article>
                );
              })}
            </div>
            {report.extraction.image_analysis_status !== 'NOT_PROVIDED' && (
              <p className="image-analysis-state">
                Image analysis: <strong>{report.extraction.image_analysis_status.replaceAll('_', ' ')}</strong>
                {report.extraction.image_cues?.map((cue) => (
                  <span key={`${cue.cue}-${cue.evidence}`}>{cue.cue} ({cue.confidence.toFixed(2)}) · {cue.evidence}</span>
                ))}
              </p>
            )}
          </section>

          <details className="panel report-analysis-editor">
            <summary>Review or correct extracted facts</summary>
            <form onSubmit={saveCorrection}>
              <p className="plan-explanation">Original submission and first-pass extraction are preserved. Corrections update only the effective facts used downstream.</p>
              <div className="review-fields">
                <label className="field">
                  <span>Incident category</span>
                  <input value={draft?.incident_category || ''} onChange={(event) => setDraft((current) => ({ ...current, incident_category: event.target.value || null }))} placeholder="Unknown" />
                </label>
                <label className="field">
                  <span>Urgency</span>
                  <select value={draft?.urgency || ''} onChange={(event) => setDraft((current) => ({ ...current, urgency: event.target.value || null }))}>
                    <option value="">Unknown</option><option value="ELEVATED">Elevated</option><option value="HIGH">High</option><option value="CRITICAL">Critical</option>
                  </select>
                </label>
                <label className="field">
                  <span>Affected persons</span>
                  <input type="number" min="0" value={draft?.affected_persons ?? ''} onChange={(event) => setDraft((current) => ({ ...current, affected_persons: event.target.value === '' ? null : Number(event.target.value) }))} placeholder="Unknown" />
                </label>
                {FACTS.filter(([key]) => LIST_FACTS.has(key)).map(([key, label]) => (
                  <label className="field" key={key}>
                    <span>{label}</span>
                    <input
                      value={(draft?.[key] || []).join(', ')}
                      onChange={(event) => setDraft((current) => ({
                        ...current,
                        [key]: event.target.value.split(',').map((part) => part.trim()).filter(Boolean),
                      }))}
                      placeholder="Unknown"
                    />
                  </label>
                ))}
              </div>
              <div className="review-form-foot">
                <span className="review-safe-note">Corrections are saved with review history.</span>
                <button className="button button--primary" type="submit" disabled={saving}>
                  {saving ? <LoaderCircle className="location-spinner" size={15} /> : <Save size={15} />}
                  {saving ? 'Saving…' : 'Save corrections'}
                </button>
              </div>
            </form>
          </details>
        </>
      )}
    </main>
  );
}
