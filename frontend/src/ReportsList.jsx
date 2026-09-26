import { useEffect, useMemo, useState } from "react";
import { apiDate, apiFetch, apiJson } from "./api.js";

export default function ReportsList({ admin = false, onOpenInspection }) {
  const [reports, setReports] = useState(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => {
    let active = true;
    apiJson(admin ? "/admin/reports?limit=200" : "/inspections/reports?limit=200")
      .then((data) => { if (active) setReports(data); }).catch((error) => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [admin]);
  const visible = useMemo(() => (reports || []).filter((report) => `${report.report_id} ${report.inspection_id} ${report.product_name || ""} ${report.creator_name}`.toLowerCase().includes(search.trim().toLowerCase())), [reports, search]);
  async function openReport(report, download) {
    setBusy(report.report_id); setError("");
    try {
      const response = await apiFetch(`/inspections/${report.inspection_id}/reports/${report.report_id}?download=${download}`);
      if (!response.ok) { const data = await response.json(); throw new Error(data.detail || "Could not open report."); }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url;
      if (download) link.download = `PackSure-${report.inspection_id}.pdf`; else link.target = "_blank";
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { setError(error.message); } finally { setBusy(""); }
  }
  return <section className="panel inspection-panel"><h2>Reports</h2><p>Securely view or download generated inspection reports.</p>
    <div className="filters"><label>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Report, inspection, product, or creator" /></label></div>
    {error && <p className="upload-error" role="alert">{error}</p>}{!reports && !error && <p role="status">Loading reports...</p>}
    {reports && visible.length === 0 && <div className="empty-state"><strong>No reports found</strong><p>Generate an inspection report to see it here.</p></div>}
    {visible.length > 0 && <div className="table-scroll"><table><thead><tr><th>Report</th><th>Inspection</th><th>Creator</th><th>Created</th><th>Actions</th></tr></thead><tbody>{visible.map((report) => <tr key={report.report_id}>
      <td><small>{report.report_id}</small></td><td><strong>{report.product_name || "Unnamed product"}</strong><br/><button className="link-button" onClick={() => onOpenInspection?.(report.inspection_id)}>{report.inspection_id}</button></td><td>{report.creator_name}</td><td>{apiDate(report.created_at).toLocaleString()}</td>
      <td className="action-cell"><button className="secondary-button" disabled={busy === report.report_id} onClick={() => openReport(report, false)}>View</button><button className="secondary-button" disabled={busy === report.report_id} onClick={() => openReport(report, true)}>Download</button></td>
    </tr>)}</tbody></table></div>}
  </section>;
}
