import { useRef, useState } from 'react';
import { ArrowDownToLine, Check, CloudUpload, FileJson2, FileSpreadsheet, X } from 'lucide-react';
import { importReports } from '../../api/reports.js';

function downloadSample(kind) {
  const content = kind === 'json'
    ? JSON.stringify([{ disaster_type: 'FLOOD', description: 'Water entering homes near the main road', latitude: 10.027, longitude: 76.308, location_name: 'Edappally' }], null, 2)
    : 'disaster_type,description,latitude,longitude,location_name\nFLOOD,"Water entering homes near the main road",10.027,76.308,Edappally\n';
  const blob = new Blob([content], { type: kind === 'json' ? 'application/json' : 'text/csv' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `incident-reports-sample.${kind}`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function ImportPage() {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);
  const [summary, setSummary] = useState(null);

  function selectFile(nextFile) {
    setSummary(null);
    setMessage(null);
    setFile(nextFile || null);
  }

  async function handleImport() {
    if (!file) { setMessage({ kind: 'error', text: 'Choose a JSON or CSV file first.' }); return; }
    const kind = file.name.toLowerCase().endsWith('.json') ? 'json' : file.name.toLowerCase().endsWith('.csv') ? 'csv' : null;
    if (!kind) { setMessage({ kind: 'error', text: 'Only .json and .csv files are supported.' }); return; }
    setLoading(true);
    setMessage(null);
    setSummary(null);
    try {
      const result = await importReports(kind, await file.text());
      setSummary(result);
      setMessage({ kind: result.rejected ? 'warning' : 'success', text: `${result.accepted} accepted · ${result.rejected} rejected · ${result.total} total records` });
    } catch (requestError) {
      setMessage({ kind: 'error', text: requestError.message });
    } finally { setLoading(false); }
  }

  return (
    <>
      <section className="page-heading">
        <div><div className="eyebrow"><span className="eyebrow__line" />STRUCTURED IMPORT</div><h1>Import reports<span className="heading-period">.</span></h1><p>Submit JSON or CSV records and review accepted and rejected rows.</p></div>
      </section>

      <div className="import-layout">
        <section className="panel import-panel">
          <div className="form-section-heading"><span className="form-step">02</span><div><h2>Choose a data file</h2><p>Each record is checked and stored independently.</p></div></div>
          <input ref={inputRef} className="visually-hidden" type="file" accept=".json,.csv,application/json,text/csv" onChange={(event) => selectFile(event.target.files?.[0])} />
          {file ? (
            <div className="selected-file selected-file--import"><FileSpreadsheet size={21} /><span><strong>{file.name}</strong><small>{(file.size / 1024).toFixed(1)} KB · {file.name.toLowerCase().endsWith('.json') ? 'JSON file' : 'CSV file'}</small></span><button type="button" className="icon-button" aria-label="Remove file" onClick={() => { inputRef.current.value = ''; selectFile(null); }}><X size={17} /></button></div>
          ) : (
            <button type="button" className="drop-zone" onClick={() => inputRef.current?.click()} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); selectFile(event.dataTransfer.files?.[0]); }}>
              <span className="drop-zone__icon"><CloudUpload size={24} /></span><strong>Drop a file here or <u>browse</u></strong><small>JSON or CSV · maximum 1,000 records</small>
            </button>
          )}
          <div className="field-map">
            <div className="section-kicker">REQUIRED FIELDS</div>
            <div className="field-map__items"><span>disaster_type</span><span>description</span><span>latitude</span><span>longitude</span></div>
            <div className="field-map__optional">Optional: <code>location_name</code></div>
          </div>
          {message && <div className={`notice notice--${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.kind === 'success' && <Check size={17} />}{message.text}</div>}
          <div className="import-actions"><span>Accepted records are saved even when another row is rejected.</span><button className="button button--primary" type="button" disabled={loading} onClick={handleImport}>{loading ? 'Importing…' : 'Import file'}<ArrowDownToLine size={16} /></button></div>
        </section>

        <aside className="import-aside">
          <div className="section-kicker">TEMPLATES</div>
          <h2>Start with a clean file.</h2>
          <p>Use the sample format to avoid column and field mismatches.</p>
          <button className="template-link" type="button" onClick={() => downloadSample('csv')}><FileSpreadsheet size={19} /><span><strong>CSV template</strong><small>Header row included</small></span><ArrowDownToLine size={17} /></button>
          <button className="template-link" type="button" onClick={() => downloadSample('json')}><FileJson2 size={19} /><span><strong>JSON template</strong><small>Array of report objects</small></span><ArrowDownToLine size={17} /></button>
        </aside>
      </div>

      {summary && <section className="panel import-results"><div className="panel-heading"><div><div className="section-kicker">IMPORT RESPONSE</div><h2>Record results</h2></div><span className="results-total">{summary.total} records</span></div>
        <div className="report-table-wrap"><table className="report-table"><thead><tr><th>ROW</th><th>RESULT</th><th>DETAILS</th></tr></thead><tbody>{summary.results.map((result) => <tr key={result.record}><td>#{result.record}</td><td><span className={`result-status result-status--${result.status}`}>{result.status === 'accepted' ? <Check size={14} /> : <X size={14} />}{result.status}</span></td><td>{result.status === 'accepted' ? result.reportId : (result.errors || []).join('; ')}</td></tr>)}</tbody></table></div>
      </section>}
    </>
  );
}