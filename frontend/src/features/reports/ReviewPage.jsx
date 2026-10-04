import { useEffect, useState } from 'react';
import { AlertCircle, Check, LoaderCircle, Save } from 'lucide-react';
import { correctExtraction, listReports } from '../../api/reports.js';

const fields = [
  ['severity_cues', 'Severity cues'],
  ['hazards', 'Hazards'],
  ['requested_assistance', 'Requested assistance'],
  ['location_mentions', 'Location mentions'],
];

function draftFrom(report) {
  return { ...(report.extraction.corrected_facts || report.extraction.extracted_facts) };
}

export default function ReviewPage() {
  const [reports, setReports] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const selected = reports.find((report) => report.id === selectedId) || null;

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

  function selectReport(report) {
    setSelectedId(report.id);
    setDraft(draftFrom(report));
    setMessage(null);
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
              </section>

              <section className="panel extraction-panel">
                <div className="panel-heading"><div><span className="section-kicker">TEXT EXTRACTION · {selected.extraction.extractor_version}</span><h2>Review extracted facts</h2></div><span className="confidence-scale">Confidence: 0–1</span></div>
                <form onSubmit={saveCorrection}>
                  <div className="review-fields">
                    <label className="field"><span>Incident category</span><input value={draft.incident_category || ''} onChange={(event) => setValue('incident_category', event.target.value || null)} placeholder="Unknown" /></label>
                    <label className="field"><span>Urgency</span><select value={draft.urgency || ''} onChange={(event) => setValue('urgency', event.target.value || null)}><option value="">Unknown</option><option value="ELEVATED">Elevated</option><option value="HIGH">High</option><option value="CRITICAL">Critical</option></select></label>
                    <label className="field"><span>Affected persons</span><input type="number" min="0" value={draft.affected_persons ?? ''} onChange={(event) => setValue('affected_persons', event.target.value === '' ? null : Number(event.target.value))} placeholder="Unknown" /></label>
                    {fields.map(([key, label]) => <label className="field" key={key}><span>{label}</span><input value={(draft[key] || []).join(', ')} onChange={(event) => setValue(key, event.target.value.split(',').map((part) => part.trim()).filter(Boolean))} placeholder="Unknown" /></label>)}
                  </div>
                  <div className="evidence-block"><h3>Extraction evidence and confidence</h3>{Object.keys(selected.extraction.evidence).length ? Object.entries(selected.extraction.evidence).map(([key, evidence]) => <p key={key}><strong>{key.replaceAll('_', ' ')} · {selected.extraction.confidence[key]?.toFixed(2)}</strong><span>{evidence.join(' · ')}</span></p>) : <p>No fields had enough evidence to assign confidence.</p>}</div>
                  <div className="image-analysis-state">Image analysis: <strong>{selected.extraction.image_analysis_status.replaceAll('_', ' ')}</strong>{selected.extraction.image_cues?.length > 0 && selected.extraction.image_cues.map((cue) => <span key={`${cue.cue}-${cue.evidence}`}>{cue.cue} ({cue.confidence.toFixed(2)}) · {cue.evidence}</span>)}</div>
                  {selected.extraction.reviewed_at && <p className="review-history-note">Last corrected {new Date(selected.extraction.reviewed_at).toLocaleString()} · {selected.extraction.reviews.length} saved review{selected.extraction.reviews.length === 1 ? '' : 's'}</p>}
                  <div className="form-actions"><span>Submitted source and first-pass extraction remain unchanged.</span><button className="button button--primary" type="submit" disabled={saving}><Save size={16} />{saving ? 'Saving…' : 'Save correction'}</button></div>
                </form>
              </section>
            </div>
          )}
        </div>
      )}
    </>
  );
}