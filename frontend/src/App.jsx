import { useEffect, useRef, useState } from "react";

import "./App.css";

import { apiFetch, apiDate } from "./api.js";

import AdminPanel from "./AdminPanel.jsx";

import InspectionList from "./InspectionList.jsx";

import InspectionForm from "./InspectionForm.jsx";
import ReportsList from "./ReportsList.jsx";



function App({ user, onLogout }) {

  const [backendStatus, setBackendStatus] = useState("Checking...");
  const [systemHealth, setSystemHealth] = useState(null);

  const [showInspection, setShowInspection] = useState(false);

  const [inspectionId, setInspectionId] = useState(null);

  const [starting, setStarting] = useState(false);

  const [sessionError, setSessionError] = useState("");

  const [view, setView] = useState("dashboard");

  const [summary, setSummary] = useState(null);
  const [selectedInspection, setSelectedInspection] = useState(null);

  const creatingSession = useRef(false);



  async function openInspection(startAnother = false) {

    setView("dashboard");

    setShowInspection(true);

    if (creatingSession.current || (inspectionId && !startAnother)) return;

    creatingSession.current = true;

    setStarting(true);

    setSessionError("");

    try {

      const response = await apiFetch("/inspections", {

        method: "POST", signal: AbortSignal.timeout(15000),

      });

      if (!response.ok) throw new Error("Could not start an inspection. Please try again.");

      const data = await response.json();
      setSystemHealth(data.components || null);

      setInspectionId(data.inspection_id);

    } catch (error) {

      setSessionError(error instanceof TypeError ? "Cannot reach the backend. Please try again." : error.message);

    } finally {

      creatingSession.current = false;

      setStarting(false);

    }

  }



useEffect(() => {

  let alive = true;

  async function refreshSummary() {

    try {

      const response = await apiFetch("/inspections/summary");

      if (response.ok && alive) setSummary(await response.json());

    } catch { /* Health indicator reports connection problems. */ }

  }

  refreshSummary();
  window.addEventListener("packsure-data-changed", refreshSummary);

  const timer = setInterval(refreshSummary, 15000);

  return () => { alive = false; clearInterval(timer); window.removeEventListener("packsure-data-changed", refreshSummary); };

}, [view, inspectionId]);



useEffect(() => {

  async function checkBackend() {

    try {

      const response = await apiFetch(

        "/health"

      );



      if (!response.ok) {

        throw new Error("Backend unavailable");

      }



      const data = await response.json();



      if (data.status === "healthy") {

        setBackendStatus("Online");

      } else {

        setBackendStatus("Unavailable");

      }

    } catch (error) {

      console.error("Backend health check failed:", error);

      setBackendStatus("Offline");

    }

  }



  checkBackend();

}, []);

  return (

    <div className="app">

      <aside className="sidebar">

        <div className="brand">

          <h2>PackSure AI</h2>

          <p>Legal Metrology</p>

        </div>



        <nav>

          <button className={`nav-item ${view === "dashboard" && !showInspection ? "active" : ""}`} onClick={() => { setShowInspection(false); setView("dashboard"); }}>

            Dashboard

          </button>



          <button className={`nav-item ${showInspection ? "active" : ""}`} onClick={() => openInspection()} disabled={starting}>

            New Inspection

          </button>



          <button className={`nav-item ${view === "inspections" ? "active" : ""}`} onClick={() => { setSelectedInspection(null); setView("inspections"); setShowInspection(false); }}>

            Inspections

          </button>



          <button className={`nav-item ${view === "reports" ? "active" : ""}`} onClick={() => { setView("reports"); setShowInspection(false); }}>

            Reports

          </button>



          {user.role === "admin" && <button className={`nav-item ${view === "admin" ? "active" : ""}`} onClick={() => { setView("admin"); setShowInspection(false); }}>Admin</button>}

          <p>{user.name} ({user.role})</p>

          <button className="nav-item" onClick={onLogout}>Logout</button>

        </nav>

      </aside>



      <main className="main-content">

        <header className="topbar">

          <div>

            <h1>Inspection Dashboard</h1>

            <p>

              Monitor packaged commodity compliance

            </p>

          </div>



          <button className="primary-button" onClick={() => openInspection()} disabled={starting}>

            + New Inspection

          </button>

        </header>



        {view === "admin" && user.role === "admin" && <AdminPanel />}
        {view === "inspections" && <InspectionList key={selectedInspection || "history"} initialInspection={selectedInspection} />}
        {view === "reports" && <ReportsList onOpenInspection={(id) => { setSelectedInspection(id); setView("inspections"); }} />}

        <div hidden={!showInspection}>

          {starting && <p role="status">Starting inspection…</p>}

          {sessionError && <div className="upload-error" role="alert">{sessionError} <button type="button" onClick={() => openInspection(true)}>Retry</button></div>}

          {inspectionId && <InspectionForm key={inspectionId} inspectionId={inspectionId} onStartAnother={() => openInspection(true)} />}

        </div>



        {view === "dashboard" && !showInspection && <><section className="stats-grid inspector-stats">

          <div className="stat-card">

            <p>Total Inspections</p>

            <h2>{summary?.total ?? "-"}</h2>

          </div>



          <div className="stat-card">

            <p>Compliant</p>

            <h2>{summary?.compliant ?? "-"}</h2>

          </div>



          <div className="stat-card">

            <p>Non-compliant</p>

            <h2>{summary?.non_compliant ?? "-"}</h2>

          </div>



          <div className="stat-card">

            <p>Pending Review</p>

            <h2>{summary?.review ?? "-"}</h2>

          </div>

          <div className="stat-card">
            <p>Reports Generated</p>
            <h2>{summary?.reports_generated ?? "-"}</h2>
          </div>

        </section>



        <section className="content-grid">

          <div className="panel">

            <h3>Recent Inspections</h3>



            <table>

              <thead>

                <tr>

                  <th>Product</th>

                  <th>Status</th>

                  <th>Date</th>

                </tr>

              </thead>



              <tbody>

                {summary?.recent.map(item => <tr key={item.inspection_id} className="clickable-row" onClick={() => { setSelectedInspection(item.inspection_id); setView("inspections"); }}>

                  <td>{item.product_name || `Inspection ${item.inspection_id.slice(0, 8)}`}</td>

                  <td>{(item.overall_status || item.status).replaceAll("_", " ")}</td>

                  <td>{apiDate(item.created_at).toLocaleDateString()}</td>

                </tr>)}

                {summary?.recent.length === 0 && <tr><td colSpan="3"><div className="empty-state"><strong>No inspections yet</strong><p>Start a new inspection to build your history.</p></div></td></tr>}

              </tbody>

            </table>

          </div>



          <div className="panel">

            <h3>System Status</h3>



            <div className="system-item">

              <span>Backend API</span>

              <span className={`status ${backendStatus === "Online" ? "online" : "offline"}`}>

                {backendStatus}

              </span>

            </div>



            <div className="system-item">

              <span>OCR Engine</span>

              <span>{systemHealth?.ocr_worker?.status || "Checking..."}</span>

            </div>



            <div className="system-item">

              <span>Database</span>

              <span>{systemHealth?.database?.status || (backendStatus === "Online" ? "ONLINE" : "OFFLINE")}</span>

            </div>



            <div className="system-item">

              <span>Rule Engine</span>

              <span>{systemHealth?.rule_engine?.status || "Checking..."}</span>

            </div>

          </div>

        </section></>}

      </main>

    </div>

  );

  

}



export default App;

