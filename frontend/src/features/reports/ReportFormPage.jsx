import { useRef, useState } from 'react';
import { ArrowRight, Check, ImagePlus, MapPin, Upload, X } from 'lucide-react';
import { submitReport } from '../../api/reports.js';

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
    setSubmitting(true);
    try {
      const result = await submitReport(new FormData(formRef.current));
      setMessage({ kind: 'success', text: `Report received. Reference ${result.id}${result.image ? ' · photo attached' : ''}.` });
      formRef.current.reset();
      setSelectedFile(null);
    } catch (requestError) {
      setMessage({ kind: 'error', text: requestError.message });
    } finally { setSubmitting(false); }
  }

  return (
    <>
      <section className="page-heading">
        <div><div className="eyebrow"><span className="eyebrow__line" />WEB FORM</div><h1>Report an incident<span className="heading-period">.</span></h1><p>Submit a description, location, and optional photo evidence.</p></div>
      </section>

      <div className="form-layout">
        <form className="panel report-form" ref={formRef} onSubmit={handleSubmit}>
          <div className="form-section-heading"><span className="form-step">01</span><div><h2>Incident details</h2><p>Fields marked with * are required.</p></div></div>
          <label className="field"><span>Incident type <b>*</b></span><select name="disaster_type" required defaultValue=""><option value="" disabled>Select a type</option>{disasterTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="field"><span>Description <b>*</b></span><textarea name="description" required minLength="1" maxLength="5000" rows="5" placeholder="What is happening? Who or what is affected?" /></label>
          <div className="field-grid">
            <label className="field"><span>Latitude <b>*</b></span><input name="latitude" type="number" step="any" min="-90" max="90" placeholder="10.027" required /></label>
            <label className="field"><span>Longitude <b>*</b></span><input name="longitude" type="number" step="any" min="-180" max="180" placeholder="76.308" required /></label>
          </div>
          <label className="field"><span>Location name <small>OPTIONAL</small></span><div className="input-with-icon"><MapPin size={17} /><input name="location_name" maxLength="255" placeholder="Neighbourhood, road, or landmark" /></div></label>
          <div className="field"><span>Photo <small>OPTIONAL</small></span>
            <input ref={fileRef} className="visually-hidden" name="image" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => handleFile(event.target.files?.[0])} />
            {selectedFile ? (
              <div className="selected-file"><ImagePlus size={19} /><span><strong>{selectedFile.name}</strong><small>{(selectedFile.size / 1024 / 1024).toFixed(2)} MB · image evidence</small></span><button type="button" className="icon-button" aria-label="Remove image" onClick={() => { fileRef.current.value = ''; setSelectedFile(null); }}><X size={17} /></button></div>
            ) : (
              <button type="button" className="upload-zone" onClick={() => fileRef.current?.click()}><Upload size={19} /><span><strong>Choose a photo</strong><small>JPEG, PNG, or WebP · up to 5 MB</small></span></button>
            )}
          </div>
          {message && <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.kind === 'success' && <Check size={17} />}{message.text}</div>}
          <div className="form-actions"><span>Reports are recorded as <strong>SUBMITTED</strong> for review.</span><button className="button button--primary" type="submit" disabled={submitting}>{submitting ? 'Sending…' : 'Submit report'}<ArrowRight size={16} /></button></div>
        </form>

      </div>
    </>
  );
}