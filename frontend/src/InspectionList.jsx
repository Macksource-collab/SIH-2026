import { useEffect, useMemo, useState } from "react";
import { apiDate, apiJson } from "./api.js";
import AnalysisPanel from "./AnalysisPanel.jsx";

const readable = (value) => (value || "NOT_ANALYZED").replaceAll("_", " ");

export default function InspectionList({ admin = false, initialInspection = null }) {
  const [selected, setSelected] = useState(initialInspection);
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState("newest");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  useEffect(() => {
    let active = true;
    apiJson(admin ? "/admin/inspections?limit=100" : "/inspections?limit=100")
      .then((data) => { if (active) setItems(data); })
      .catch((error) => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [admin]);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (items || []).filter((item) => {
      const resultStatus = item.overall_status || "NOT_ANALYZED";
      const created = apiDate(item.created_at);
      const afterStart = !dateFrom || created >= new Date(`${dateFrom}T00:00:00`);
      const beforeEnd = !dateTo || created <= new Date(`${dateTo}T23:59:59.999`);
      return (!needle || item.inspection_id.toLowerCase().includes(needle) || (item.product_name || "").toLowerCase().includes(needle)) &&
        (status === "all" || resultStatus === status) && afterStart && beforeEnd;
    }).sort((a, b) => (sort === "newest" ? -1 : 1) * (apiDate(a.created_at) - apiDate(b.created_at)));
  }, [items, search, status, sort, dateFrom, dateTo]);
  if (selected) return <section className="panel inspection-panel">
    <button className="secondary-button" onClick={() => setSelected(null)}>← Back to inspection history</button>
    <AnalysisPanel key={selected} inspectionId={selected} />
  </section>;
  return <section className="panel inspection-panel">
    <div className="section-heading"><div><h2>{admin ? "All Inspections" : "Inspection History"}</h2><p>Open saved results without rerunning OCR.</p></div></div>
    <div className="filters">
      <label>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Inspection ID or product name" /></label>
      <label>Status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option><option value="COMPLIANT">Compliant</option><option value="NON_COMPLIANT">Non-compliant</option><option value="REVIEW_REQUIRED">Review required</option><option value="NOT_ANALYZED">Not analyzed</option></select></label>
      <label>Sort<select value={sort} onChange={(event) => setSort(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
      <label>From<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label>To<input type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => setDateTo(event.target.value)} /></label>
    </div>
    {error && <p role="alert" className="upload-error">{error}</p>}
    {!items && !error && <p role="status">Loading inspections...</p>}
    {items && visible.length === 0 && <div className="empty-state"><strong>No inspections found</strong><p>{items.length ? "Try a different search or status filter." : "Create an inspection to see it here."}</p></div>}
    {visible.length > 0 && <div className="table-scroll"><table><thead><tr><th>Inspection / product</th>{admin && <th>Inspector</th>}<th>Status</th><th>Reports</th><th>Created / updated</th><th></th></tr></thead><tbody>{visible.map((item) => <tr key={item.inspection_id}>
      <td><strong>{item.product_name || "Unnamed product"}</strong><br/><small className="inspection-id">{item.inspection_id}</small></td>
      {admin && <td>{item.inspector_name}<br/><small>{item.inspector_email}</small></td>}
      <td><span className={`status status-${(item.overall_status || "not_analyzed").toLowerCase()}`}>{readable(item.overall_status)}</span></td><td>{item.reports_generated}</td>
      <td>{apiDate(item.created_at).toLocaleString()}<br/><small>Updated {apiDate(item.updated_at).toLocaleString()}</small></td>
      <td><button className="secondary-button" onClick={() => setSelected(item.inspection_id)}>Open saved result</button></td>
    </tr>)}</tbody></table></div>}
  </section>;
}
