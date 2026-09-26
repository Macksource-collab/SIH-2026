import { useEffect, useMemo, useState } from "react";
import { apiDate, apiJson } from "./api.js";
import InspectionList from "./InspectionList.jsx";
import ReportsList from "./ReportsList.jsx";
import RuleManagement from "./RuleManagement.jsx";

const sections = ["Overview", "Users", "Inspections", "Reports", "Rules", "Audit Logs", "System Status"];

function Stat({ label, value }) { return <div className="stat-card"><p>{label}</p><h2>{value ?? "–"}</h2></div>; }

function UsersView() {
  const [users, setUsers] = useState(null); const [search, setSearch] = useState("");
  const [error, setError] = useState(""); const [busy, setBusy] = useState("");
  useEffect(() => { let active = true; apiJson("/admin/users?limit=100").then((data) => active && setUsers(data)).catch((error) => active && setError(error.message)); return () => { active = false; }; }, []);
  const visible = useMemo(() => (users || []).filter((user) => `${user.name} ${user.email} ${user.role}`.toLowerCase().includes(search.toLowerCase())), [users, search]);
  async function update(user, changes) { setBusy(user.id); setError(""); try { const updated = await apiJson(`/admin/users/${user.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) }); setUsers((items) => items.map((item) => item.id === updated.id ? updated : item)); } catch (error) { setError(error.message); } finally { setBusy(""); } }
  return <section className="panel inspection-panel"><h2>Users</h2><div className="filters"><label>Search<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, email, or role" /></label></div>
    {error && <p className="upload-error" role="alert">{error}</p>}{!users && !error && <p role="status">Loading users...</p>}
    {users && !visible.length && <div className="empty-state"><strong>No users found</strong></div>}
    {visible.length > 0 && <div className="table-scroll"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>{visible.map((user) => <tr key={user.id}><td>{user.name}</td><td>{user.email}</td><td><select aria-label={`Role for ${user.name}`} value={user.role} disabled={Boolean(busy)} onChange={(event) => update(user, { role: event.target.value })}><option value="inspector">Inspector</option><option value="admin">Admin</option></select></td><td><span className={`status ${user.is_active ? "compliant" : "violation"}`}>{user.is_active ? "Active" : "Inactive"}</span></td><td>{apiDate(user.created_at).toLocaleString()}</td><td><button className="secondary-button" disabled={Boolean(busy)} onClick={() => update(user, { is_active: !user.is_active })}>{user.is_active ? "Deactivate" : "Activate"}</button></td></tr>)}</tbody></table></div>}
  </section>;
}

function AuditView() {
  const [logs, setLogs] = useState(null); const [search, setSearch] = useState(""); const [page, setPage] = useState(0); const [error, setError] = useState("");
  useEffect(() => { let active = true; apiJson(`/admin/logs?limit=50&offset=${page * 50}`).then((data) => active && setLogs(data)).catch((error) => active && setError(error.message)); return () => { active = false; }; }, [page]);
  const visible = useMemo(() => (logs || []).filter((log) => `${log.actor_name} ${log.actor_email || ""} ${log.action} ${log.resource_type} ${log.resource_id || ""}`.toLowerCase().includes(search.toLowerCase())), [logs, search]);
  return <section className="panel inspection-panel"><h2>Audit Logs</h2><div className="filters"><label>Search this page<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Actor, action, or resource" /></label></div>
    {error && <p className="upload-error" role="alert">{error}</p>}{!logs && !error && <p role="status">Loading audit logs...</p>}
    {logs && !visible.length && <div className="empty-state"><strong>No audit events found</strong></div>}
    {visible.length > 0 && <div className="table-scroll"><table><thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Resource</th><th>Metadata</th></tr></thead><tbody>{visible.map((log) => <tr key={log.id}><td>{apiDate(log.created_at).toLocaleString()}</td><td>{log.actor_name}<br/><small>{log.actor_email}</small></td><td>{log.action}</td><td>{log.resource_type}<br/><small>{log.resource_id || "–"}</small></td><td>{Object.keys(log.metadata || {}).length ? <details><summary>View</summary><pre>{JSON.stringify(log.metadata, null, 2)}</pre></details> : "–"}</td></tr>)}</tbody></table></div>}
    <div className="pagination"><button className="secondary-button" disabled={!page} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page + 1}</span><button className="secondary-button" disabled={(logs?.length || 0) < 50} onClick={() => setPage((value) => value + 1)}>Next</button></div>
  </section>;
}

const componentLabels = { api: "API", database: "Database", upload_storage: "Upload Storage",
  report_storage: "Report Storage", ocr_worker: "OCR Worker", rule_engine: "Rule Engine" };

function SystemStatusView({ initialStatus }) {
  const [status, setStatus] = useState(initialStatus); const [warming, setWarming] = useState(false); const [error, setError] = useState("");
  async function refresh() { setError(""); try { setStatus(await apiJson("/admin/status")); } catch (error) { setError(error.message); } }
  async function warmup() { setWarming(true); setError(""); try { await apiJson("/admin/ocr/warmup", { method: "POST" }); await refresh(); } catch (error) { setError(error.message); await refresh(); } finally { setWarming(false); } }
  return <section className="panel inspection-panel"><div className="section-heading"><div><h2>System Status</h2><p>Live checks that do not initialize OCR automatically.</p></div><button className="secondary-button" onClick={refresh}>Refresh</button></div>
    {error && <p className="upload-error" role="alert">{error}</p>}{!status && <p role="status">Loading status...</p>}
    {status && <><p>Overall: <span className={`health-badge health-${status.overall_status.toLowerCase()}`}>{status.overall_status}</span></p><div className="status-list">{Object.entries(status.components).map(([name, item]) => <div className="system-item health-row" key={name}><div><strong>{componentLabels[name] || name}</strong><p>{item.detail}</p>{name === "ocr_worker" && <small>State: {item.state}{item.initialization_duration_seconds != null ? ` · initialized in ${item.initialization_duration_seconds}s` : ""}</small>}</div><span className={`health-badge health-${item.status.toLowerCase()}`}>{item.status}</span></div>)}</div>
      {status.components.ocr_worker.status !== "ONLINE" && <button className="primary-button" disabled={warming || status.components.ocr_worker.status === "OFFLINE" && status.components.ocr_worker.state === "RUNTIME_MISSING"} onClick={warmup}>{warming ? "Initializing OCR Model..." : "Warm Up OCR Worker"}</button>}</>}
  </section>;
}

export default function AdminPanel() {
  const [section, setSection] = useState("Overview"); const [stats, setStats] = useState(null); const [status, setStatus] = useState(null); const [error, setError] = useState(""); const [selectedInspection, setSelectedInspection] = useState(null);
  useEffect(() => { let active = true; Promise.all([apiJson("/admin/stats"), apiJson("/admin/status")]).then(([stats, status]) => { if (active) { setStats(stats); setStatus(status); } }).catch((error) => active && setError(error.message)); return () => { active = false; }; }, []);
  function openInspection(id) { setSelectedInspection(id); setSection("Inspections"); }
  return <div className="admin-layout"><nav className="admin-nav" aria-label="Admin sections">{sections.map((item) => <button key={item} className={section === item ? "active" : ""} onClick={() => { setSection(item); setSelectedInspection(null); }}>{item}</button>)}</nav><div className="admin-content">
    {error && <p className="upload-error" role="alert">{error}</p>}
    {section === "Overview" && <><section className="panel"><h2>Admin Overview</h2><p>Live totals from the PackSure database.</p></section><section className="stats-grid admin-stats"><Stat label="Total Users" value={stats?.total_users}/><Stat label="Active Inspectors" value={stats?.active_inspectors}/><Stat label="Total Inspections" value={stats?.total_inspections}/><Stat label="Compliant" value={stats?.compliant_inspections}/><Stat label="Non-compliant" value={stats?.non_compliant_inspections}/><Stat label="Review Required" value={stats?.review_required}/><Stat label="OCR Processed" value={stats?.ocr_processed_inspections}/><Stat label="Reports Generated" value={stats?.reports_generated}/></section>{stats?.total_inspections === 0 && <div className="empty-state"><strong>No inspections yet</strong><p>Inspector activity will appear here.</p></div>}</>}
    {section === "Users" && <UsersView/>}
    {section === "Inspections" && <InspectionList key={selectedInspection || "all"} admin initialInspection={selectedInspection}/>} 
    {section === "Reports" && <ReportsList admin onOpenInspection={openInspection}/>} 
    {section === "Rules" && <section className="panel inspection-panel"><RuleManagement/></section>}
    {section === "Audit Logs" && <AuditView/>}
    {section === "System Status" && <SystemStatusView initialStatus={status}/>} 
  </div></div>;
}
