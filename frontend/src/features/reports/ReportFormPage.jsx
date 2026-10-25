import { useRef, useState } from 'react';
import { ArrowRight, Check, ImagePlus, LoaderCircle, MapPin, Upload, X } from 'lucide-react';
import { analyzeReport, submitReport } from '../../api/reports.js';
import LocationPicker from './LocationPicker.jsx';
import { validateCoordinates } from './mapLocation.js';
import { calculatePreliminaryPriority } from './priorityCalculation.js';

const disasterTypes = [
  ['FLOOD', 'Flood'], ['FIRE', 'Fire'], ['EARTHQUAKE', 'Earthquake'], ['LANDSLIDE', 'Landslide'],
  ['CYCLONE', 'Cyclone'], ['ROAD_ACCIDENT', 'Road accident'], ['BUILDING_COLLAPSE', 'Building collapse'],
  ['MEDICAL_EMERGENCY', 'Medical emergency'], ['OTHER', 'Other'],
];
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export default function ReportFormPage() {
  const formRef = useRef(null);
  const fileRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState(null);
  const [analysisFacts, setAnalysisFacts] = useState(null);
  const [location, setLocation] = useState({ latitude: '', longitude: '', location_name: '' });
  const [locationError, setLocationError] = useState('');

  function invalidateAnalysis() {
    setAnalysis(null);
    setAnalysisFacts(null);
  }

  function updateCoordinate(field, value) {
    setLocation((current) => ({ ...current, [field]: value, location_name: '' }));
    setLocationError('');
    setMessage(null);
    invalidateAnalysis();
  }

  async function analyzeDescription() {
    const form = new FormData(formRef.current);
    const disasterType = form.get('disaster_type');
    const description = String(form.get('description') || '').trim();
    if (!disasterType || !description) {
      setMessage({ kind: 'error', text: 'Choose an incident type and enter a description before analysis.' });
      return;
    }

    setAnalyzing(true);
    setMessage(null);
    try {
      const result = await analyzeReport({
        disaster_type: disasterType,
        description,
        location_name: location.location_name || null,
      });
      setAnalysis(result);
      setAnalysisFacts({ ...result.facts });
      setMessage({
        kind: result.analysis_status === 'GROQ' ? 'success' : 'error',
        text: result.analysis_status === 'GROQ'
          ? 'AI suggestions are ready. Review or correct every field before submitting.'
          : `${result.analysis_error || 'Groq analysis is unavailable.'} The fields are left unknown; enter any facts you can verify.`,
      });
      return result;
    } catch (requestError) {
      setAnalysis(null);
      setAnalysisFacts(null);
      setMessage({ kind: 'error', text: requestError.message });
      return null;
    } finally {
      setAnalyzing(false);
    }
  }

  function updateAnalysisFact(field, value) {
    setAnalysisFacts((current) => ({ ...current, [field]: value }));
  }

  function handleFile(file) {
    setMessage(null);
    if (!file) { setSelectedFile(null); return; }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setMessage({ kind: 'error', text: 'Choose a JPEG, PNG, or WebP image.' });
      fileRef.current.value = '';
      setSelectedFile(null);
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setMessage({ kind: 'error', text: 'The image must be 5 MB or smaller.' });
      fileRef.current.value = '';
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setMessage(null);
    const coordinates = validateCoordinates(location.latitude, location.longitude);
    if (coordinates.kind === 'error') {
      setLocationError(coordinates.message);
      return;
    }
    setLocationError('');
    if (!analysis || !analysisFacts) {
      await analyzeDescription();
      return;
    }
    setSubmitting(true);
    try {
      const formData = new FormData(formRef.current);
      formData.append('analysis_payload', JSON.stringify({
        extractor_version: analysis.extractor_version,
        facts: analysis.facts,
        confidence: analysis.confidence,
        evidence: analysis.evidence,
        reviewed_facts: analysisFacts,
      }));
      const result = await submitReport(formData);
      setMessage({ kind: 'success', text: `Report received. Reference ${result.id}${result.image ? ' · photo attached' : ''}. Submitted at ${result.submitted_at}.` });
      setAnalysis(null);
      setAnalysisFacts(null);
      formRef.current.reset();
      setSelectedFile(null);
      setLocation({ latitude: '', longitude: '', location_name: '' });
      setLocationError('');
    } catch (requestError) {
      setMessage({ kind: 'error', text: requestError.message });
    } finally { setSubmitting(false); }
  }

  const preliminaryPriority = analysisFacts && analysis
    ? calculatePreliminaryPriority(
      analysisFacts,
      analysis.confidence,
      analysis.priority_policy.weights,
      analysis.priority_policy.thresholds,
    )
    : null;
  const evidenceItems = Object.entries(analysis?.evidence || {}).flatMap(
    ([field, phrases]) => phrases.map((text, index) => ({ field, text, index })),
  );
  const reportFieldChanged = () => invalidateAnalysis();

  return (
    <>
      <section className="page-heading">
        <div><div className="eyebrow"><span className="eyebrow__line" />WEB FORM</div><h1>Report an incident<span className="heading-period">.</span></h1><p>Submit a description, location, and optional photo evidence.</p></div>
      </section>

      <div className="form-layout">
        <form className="panel report-form" ref={formRef} onSubmit={handleSubmit}>
          <div className="form-section-heading"><span className="form-step">01</span><div><h2>Incident details</h2><p>Fields marked with * are required.</p></div></div>
          <label className="field"><span>Incident type <b>*</b></span><select name="disaster_type" required defaultValue="" onChange={reportFieldChanged}><option value="" disabled>Select a type</option>{disasterTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="field"><span>Description <b>*</b></span><textarea name="description" required minLength="1" maxLength="5000" rows="5" placeholder="What is happening? Who or what is affected?" onChange={reportFieldChanged} /></label>
          <p className="extraction-note">Submitting first analyzes the description with Groq using the active admin priority policy. Review or correct the suggested fields before final submission.</p>
          <LocationPicker value={location} onChange={(value) => { setLocation(value); invalidateAnalysis(); }} />
          <div className="field-grid">
            <label className="field"><span>Latitude <b>*</b></span><input name="latitude" type="number" step="any" placeholder="Enter latitude" value={location.latitude} onChange={(event) => updateCoordinate('latitude', event.target.value)} aria-invalid={Boolean(locationError)} /></label>
            <label className="field"><span>Longitude <b>*</b></span><input name="longitude" type="number" step="any" placeholder="Enter longitude" value={location.longitude} onChange={(event) => updateCoordinate('longitude', event.target.value)} aria-invalid={Boolean(locationError)} /></label>
          </div>
          <p className="location-hint">Enter coordinates directly or choose a point on the map. Latitude: -90 to 90; longitude: -180 to 180.</p>
          {locationError && <p className="location-error" role="alert">{locationError}</p>}
          <label className="field"><span>Location name <small>AUTO-FILLED</small></span><div className="input-with-icon"><MapPin size={17} /><input name="location_name" maxLength="255" placeholder="Choose a point on the map" value={location.location_name} readOnly /></div></label>
          <div className="field"><span>Photo <small>OPTIONAL</small></span>
            <input ref={fileRef} className="visually-hidden" name="image" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => handleFile(event.target.files?.[0])} />
            {selectedFile ? (
              <div className="selected-file"><ImagePlus size={19} /><span><strong>{selectedFile.name}</strong><small>{(selectedFile.size / 1024 / 1024).toFixed(2)} MB · image evidence</small></span><button type="button" className="icon-button" aria-label="Remove image" onClick={() => { fileRef.current.value = ''; setSelectedFile(null); }}><X size={17} /></button></div>
            ) : (
              <button type="button" className="upload-zone" onClick={() => fileRef.current?.click()}><Upload size={19} /><span><strong>Choose a photo</strong><small>JPEG, PNG, or WebP · up to 5 MB</small></span></button>
            )}
          </div>
          {message && <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.kind === 'success' && <Check size={17} />}{message.text}</div>}
          {analysis && analysisFacts && (
            <section className="extraction-results" aria-live="polite" aria-label="Review AI-proposed incident details">
              <div className="panel-heading">
                <div><span className="section-kicker">REPORT ANALYSIS · {analysis.extractor_version}</span><h2>Review suggested details</h2></div>
                <span className={`result-status ${analysis.analysis_status === 'GROQ' ? 'result-status--accepted' : ''}`}>
                  {analysis.analysis_status === 'GROQ' ? 'Groq analyzed' : 'Manual entry'}
                </span>
              </div>
              {analysis.analysis_status === 'UNAVAILABLE' && (
                <p className="extraction-note">Groq could not analyze this report: {analysis.analysis_error || 'provider unavailable'}. No classification was guessed; enter only facts you can verify.</p>
              )}
              <div className="review-fields">
                <label className="field"><span>Incident category</span><input value={analysisFacts.incident_category || ''} onChange={(event) => updateAnalysisFact('incident_category', event.target.value || null)} placeholder="Unknown" /></label>
                <label className="field"><span>Urgency</span><input value={analysisFacts.urgency || ''} onChange={(event) => updateAnalysisFact('urgency', event.target.value || null)} placeholder="Unknown" /></label>
                <label className="field"><span>Affected people</span><input type="number" min="0" step="1" value={analysisFacts.affected_persons ?? ''} onChange={(event) => updateAnalysisFact('affected_persons', event.target.value === '' ? null : Number(event.target.value))} placeholder="Unknown" /></label>
                <label className="field"><span>Severity cues <small>COMMA-SEPARATED</small></span><input value={(analysisFacts.severity_cues || []).join(', ')} onChange={(event) => updateAnalysisFact('severity_cues', event.target.value.split(',').map((part) => part.trim()).filter(Boolean))} placeholder="Unknown" /></label>
                <label className="field"><span>Hazards <small>COMMA-SEPARATED</small></span><input value={(analysisFacts.hazards || []).join(', ')} onChange={(event) => updateAnalysisFact('hazards', event.target.value.split(',').map((part) => part.trim()).filter(Boolean))} placeholder="Unknown" /></label>
                <label className="field"><span>Requested assistance <small>COMMA-SEPARATED</small></span><input value={(analysisFacts.requested_assistance || []).join(', ')} onChange={(event) => updateAnalysisFact('requested_assistance', event.target.value.split(',').map((part) => part.trim()).filter(Boolean))} placeholder="Unknown" /></label>
                <label className="field"><span>Location mentions <small>COMMA-SEPARATED</small></span><input value={(analysisFacts.location_mentions || []).join(', ')} onChange={(event) => updateAnalysisFact('location_mentions', event.target.value.split(',').map((part) => part.trim()).filter(Boolean))} placeholder="Unknown" /></label>
              </div>
              <details className="extraction-evidence">
                <summary>View extraction evidence ({evidenceItems.length})</summary>
                {evidenceItems.length
                  ? <ul>{evidenceItems.map((item) => <li key={`${item.field}-${item.index}`}><strong>{item.field.replaceAll('_', ' ')}:</strong> “{item.text}”</li>)}</ul>
                  : <p>No evidence quotes were returned.</p>}
              </details>
              <p className="extraction-note">Review these suggestions. Your edits are saved separately from Groq’s original extraction.</p>
              {preliminaryPriority && (
                <div className="priority-review-card" style={{ marginTop: '14px' }}>
                  <div className="priority-review-header">
                    <div><strong>Priority Assessment</strong><span className="priority-review-rule"> · Admin policy {analysis.priority_policy.version}</span></div>
                    <span className="priority-advisory-tag">Advisory Triage</span>
                  </div>
                  <div className="priority-review-score-row">
                    <span className={`priority-badge priority-badge--${preliminaryPriority.band.toLowerCase()}`}>{preliminaryPriority.band}</span>
                    <strong className="priority-score-number">{preliminaryPriority.score} / 100</strong>
                  </div>
                  <div className="priority-factor-breakdown">
                    <div className="priority-factor-title">Factor Contribution Breakdown</div>
                    {Object.entries(preliminaryPriority.breakdown.risk_factors).map(([key, item]) => (
                      <div key={key} className="priority-factor-row">
                        <span className="priority-factor-name">{key.replaceAll('_', ' ')}</span>
                        <div className="priority-factor-bar-bg" title={`${Math.round(item.value * 100)}% input`}>
                          <div className="priority-factor-bar-fill" style={{ width: `${Math.min(100, Math.max(0, item.value * 100))}%` }} />
                        </div>
                        <span className="priority-factor-pts">+{item.score_points.toFixed(1)} pts</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}
          <div className="form-actions">
            <span>Reports are recorded as <strong>SUBMITTED</strong> for review.</span>
            <button className="button button--primary" type="submit" disabled={submitting || analyzing}>
              {analyzing ? <><LoaderCircle className="location-spinner" size={15} />Analyzing with Groq…</> : submitting ? 'Sending…' : analysisFacts ? 'Submit reviewed report' : 'Analyze & review report'}<ArrowRight size={16} />
            </button>
          </div>
        </form>

      </div>
    </>
  );
}