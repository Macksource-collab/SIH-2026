import { useEffect, useState } from "react";
import { apiFetch, apiJson } from "./api.js";

const label = (value) => value.replaceAll("_", " ");
const percent = (value) => `${Math.round(value * 100)}%`;

function EvidenceViewer({ inspectionId, field, onClose, onSaved }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [correction, setCorrection] = useState(field.corrected_value?.display || field.machine_value?.display || field.normalized_value.display || "");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    let objectUrl;
    async function load() {
      try {
        const response = await apiFetch(`/inspections/${inspectionId}/images/${field.image_id}/evidence`);
        if (!response.ok) throw new Error("No reliable evidence image is available. Manual inspection recommended.");
        objectUrl = URL.createObjectURL(await response.blob());
        if (active) setUrl(objectUrl); else URL.revokeObjectURL(objectUrl);
      } catch (error) { if (active) setError(error.message); }
    }
    load();
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [inspectionId, field.image_id]);
  async function saveCorrection(event) {
    event.preventDefault();
    setSaving(true); setError("");
    try {
      const data = await apiJson(`/inspections/${inspectionId}/fields/${field.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ corrected_value: correction }),
      });
      onSaved(data, field.id);
    } catch (error) { setError(error.message); } finally { setSaving(false); }
  }
  const machine = field.machine_value || field.normalized_value;
  return <section className="evidence-panel" aria-label="Evidence viewer">
    <div className="result-heading"><h3>Review: {label(field.field_name)}</h3><button className="secondary-button" onClick={onClose}>Close</button></div>
    <p>Side: {field.image_side} | Confidence: {percent(field.confidence)}</p>
    <p><strong>Machine Extracted:</strong> {machine.display}</p>
    <p><strong>Raw OCR Evidence:</strong> {field.source_text}</p>
    {field.human_reviewed && <p className="human-reviewed"><strong>Human Corrected:</strong> {field.corrected_value.display}<br/><small>Reviewed at {new Date(field.corrected_at).toLocaleString()}</small></p>}
    <form className="correction-form" onSubmit={saveCorrection}>
      <label htmlFor={`correction-${field.id}`}>Manual correction</label>
      <input id={`correction-${field.id}`} value={correction} maxLength="500" required disabled={saving} onChange={(event) => setCorrection(event.target.value)} />
      <button className="primary-button" disabled={saving || !correction.trim()}>{saving ? "Saving Correction..." : "Save Human Correction"}</button>
      <small>Saving keeps the machine value and raw OCR evidence, then reevaluates configured rules without rerunning OCR.</small>
    </form>
    {field.confidence < 0.8 && <p className="review-note">No reliable evidence detected. Manual inspection recommended. The uncertain OCR region is shown below.</p>}
    {error && <p role="alert">{error}</p>}
    {url && <div className="evidence-image">
      <img src={url} alt={`${field.image_side} package source`} />
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-label="Highlighted OCR evidence bounding box">
        <polygon points={field.bounding_box.map(([x, y]) => `${x * 1000},${y * 1000}`).join(" ")} />
      </svg>
    </div>}
  </section>;
}

export default function AnalysisPanel({ inspectionId }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState(null);
  const [reportReady, setReportReady] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  useEffect(() => {
    let active = true;
    apiFetch(`/inspections/${inspectionId}/result`).then(async (response) => {
      if (response.status === 404) return;
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load results.");
      if (active) { setResult(data); setReportReady(Boolean(data.report_ready)); }
    }).catch((error) => { if (active) setError(error.message); }).finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [inspectionId]);
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl); }, [pdfUrl]);

  async function run(force = false) {
    setLoading(true); setError(""); setEvidence(null); setPdfUrl(""); setReportReady(false);
    try {
      const data = await apiJson(`/inspections/${inspectionId}/analyze?force=${force}`, { method: "POST" });
      setResult(data);
      window.dispatchEvent(new Event("packsure-data-changed"));
    } catch (error) { setError(error.message); } finally { setLoading(false); }
  }
  async function report() {
    setReportBusy(true); setError("");
    try {
      await apiJson(`/inspections/${inspectionId}/report`, { method: "POST" });
      setReportReady(true);
      window.dispatchEvent(new Event("packsure-data-changed"));
    } catch (error) { setError(error.message); } finally { setReportBusy(false); }
  }
  async function viewReport() {
    setReportBusy(true); setError("");
    try {
      const response = await apiFetch(`/inspections/${inspectionId}/report`);
      if (!response.ok) throw new Error((await response.json()).detail);
      setPdfUrl(URL.createObjectURL(await response.blob()));
    } catch (error) { setError(error.message); } finally { setReportBusy(false); }
  }
  function correctionSaved(data, fieldId) {
    setResult(data); setReportReady(false); setPdfUrl("");
    const updated = data.declarations.find((field) => field.id === fieldId);
    if (updated) setEvidence(updated);
    window.dispatchEvent(new Event("packsure-data-changed"));
  }

  return <section className="panel analysis-panel" aria-label="Inspection analysis">
    <div className="result-heading"><h2>Inspection Analysis</h2><span className="demo-badge">DEMO / PROVISIONAL</span></div>
    <p>Inspection ID: {inspectionId}</p>
    <p className="review-note">Configured checks require official-source verification. PackSure assists human inspection; it does not provide legal certification.</p>
    <div className="analysis-actions">
      <button className="primary-button" disabled={loading || checking || reportBusy} onClick={() => run(false)}>{loading ? "Analysis Running..." : "Run Analysis"}</button>
      {result && <button className="secondary-button" disabled={loading || reportBusy} onClick={() => run(true)}>Re-read Images (Force OCR)</button>}
    </div>
    {loading && <div role="status" className="analysis-progress"><strong>Processing package images. The first run may take several minutes.</strong>
      <p>Preparing images → Reading label text → Extracting declarations → Checking compliance → Preparing results</p>
      <small>This describes the workflow, not live server stages. One request is in progress.</small></div>}
    {checking && <p role="status">Checking saved results...</p>}
    {error && <p className="upload-error" role="alert">{error}</p>}
    {result && <>
      <h2 className={`overall ${result.overall_status.toLowerCase()}`}>{label(result.overall_status)}</h2>
      {result.reused_analysis && <p className="upload-success">Loaded the current saved analysis. OCR was not run again.</p>}
      {result.availability_message && <p className="upload-error" role="alert">{result.availability_message}</p>}
      <p><small>Analysis duration: {result.analysis_duration_seconds ?? result.ocr_summary?.duration_seconds ?? "–"} seconds</small></p>
      {result.stale && <p className="upload-error">Images, OCR, or rule applicability have changed. Run Analysis again before generating a report.</p>}
      <p>Analysis created: {new Date(result.created_at).toLocaleString()}</p>
      <h3>Image quality</h3>
      <div className="quality-grid">{result.images.map((image) => <div className="image-card" key={image.image_id}>
        <strong>{image.image_side}: {label(image.quality)}</strong><p>{image.texts.length} OCR regions{image.cached ? " (reused)" : ""}</p>
        <p>{image.error || image.metrics.notes?.join(" ") || "Heuristic checks found no major quality issue."}</p>
      </div>)}</div>
      <h3>Declarations and evidence</h3>
      <div className="table-scroll"><table><thead><tr><th>Declaration</th><th>Machine Extracted</th><th>Human Corrected</th><th>Confidence</th><th>Status</th><th>Evidence</th></tr></thead><tbody>
        {result.declaration_names.flatMap((name) => {
          const fields = result.declarations.filter((field) => field.field_name === name);
          const fieldStatus = (field) => {
            const checks = result.rule_evaluations.filter((rule) => rule.field_name === name || rule.evidence_field_id === field.id);
            return checks.some((rule) => rule.status === "REVIEW") ? "REVIEW" : checks.some((rule) => rule.status === "FAIL") ? "FAIL" : checks.length ? "PASS" : "Not checked";
          };
          return fields.length ? fields.map((field) => <tr key={field.id}><td>{label(name)}</td>
            <td>{(field.machine_value || field.normalized_value).display}<br/><small>Machine Extracted</small></td>
            <td>{field.human_reviewed ? <><strong>{field.corrected_value.display}</strong><br/><span className="human-badge">Human Reviewed</span></> : "Not corrected"}</td>
            <td>{percent(field.confidence)}<br/><small>machine confidence</small></td><td>{fieldStatus(field)}</td>
            <td><button className="secondary-button" onClick={() => setEvidence(field)} aria-label={`Review or correct ${label(name)} on ${field.image_side}`}>Review / Correct</button></td></tr>)
            : [<tr key={name}><td>{label(name)}</td><td>Not confidently detected</td><td>Not available</td><td>—</td><td>REVIEW</td><td>No reliable evidence detected. Manual inspection recommended.</td></tr>];
        })}
      </tbody></table></div>
      {evidence && <EvidenceViewer key={`${evidence.id}-${evidence.corrected_at || "machine"}`} inspectionId={inspectionId} field={evidence} onClose={() => setEvidence(null)} onSaved={correctionSaved} />}
      <h3>Rule evaluations</h3>
      <div className="table-scroll"><table><thead><tr><th>Rule</th><th>Status</th><th>Reason</th><th>Severity</th><th>Source / reference</th></tr></thead><tbody>
        {result.rule_evaluations.map((rule) => <tr key={rule.rule_id}><td>{rule.title}<br/><small>{rule.rule_code} v{rule.version}</small></td><td>{rule.status}</td><td>{rule.reason}</td><td>{rule.severity}</td>
          <td>{rule.source_document}<br/>{rule.source_reference || "No verified official reference"}<br/>{rule.is_demo_or_provisional && <strong>DEMO / PROVISIONAL</strong>}</td></tr>)}
      </tbody></table></div>
      {!result.rule_evaluations.length && <p className="review-note">No active applicable rules. Manual review required.</p>}
      <details><summary>Show OCR Text</summary>{result.images.map((image) => <section key={image.image_id}><h4>{image.image_side}</h4>
        {image.texts.length ? image.texts.map((row, index) => <p key={index}>{row.text} <small>({percent(row.confidence)})</small></p>) : <p>No usable OCR text.</p>}</section>)}</details>
      <div className="analysis-actions"><button className="primary-button" disabled={loading || reportBusy || result.stale} onClick={report}>{reportBusy ? "Preparing Report..." : "Generate Report"}</button>
        {reportReady && <button className="secondary-button" disabled={loading || reportBusy || result.stale} onClick={viewReport}>View / Download Report</button>}
        {pdfUrl && <a className="secondary-button" href={pdfUrl} download={`PackSure-${inspectionId}.pdf`}>Download PDF</a>}</div>
      {pdfUrl && <p>If the PDF preview is blank, use Download PDF and open it in your browser or PDF reader.</p>}
      {pdfUrl && <iframe className="report-preview" title="PackSure PDF report" src={pdfUrl} />}
    </>}
  </section>;
}
