import { useEffect, useState } from "react";
import { apiJson } from "./api.js";

export default function RuleManagement() {
  const [rules, setRules] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [importText, setImportText] = useState("");
  const [preview, setPreview] = useState(null);
  const [importMessage, setImportMessage] = useState("");
  const [verifiedAcknowledged, setVerifiedAcknowledged] = useState(false);
  function loadRules(active = true) {
    return apiJson("/admin/rules").then((rules) => { if (active) setRules(rules); });
  }
  useEffect(() => {
    let active = true;
    loadRules(active).catch((error) => { if (active) setError(error.message); });
    return () => { active = false; };
  }, []);
  async function toggle(rule) {
    setBusy(rule.id); setError("");
    try {
      const updated = await apiJson(`/admin/rules/${rule.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !rule.is_active }) });
      setRules((rules) => rules.map((item) => item.id === updated.id ? updated : item));
    } catch (error) { setError(error.message); } finally { setBusy(""); }
  }
  function parsedImport() {
    const parsed = JSON.parse(importText);
    return Array.isArray(parsed) ? { rules: parsed } : parsed;
  }
  async function validateImport() {
    setBusy("import"); setError(""); setImportMessage(""); setPreview(null);
    try {
      const data = await apiJson("/admin/rules/import/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(parsedImport()) });
      setPreview(data); setVerifiedAcknowledged(false); setImportMessage(data.valid ? "Validation passed. Review the actions before committing." : "Resolve conflicts before committing.");
    } catch (error) { setError(error instanceof SyntaxError ? "Rule import must be valid JSON." : error.message); } finally { setBusy(""); }
  }
  async function commitImport() {
    setBusy("import"); setError("");
    try {
      const payload = { ...parsedImport(), preview_digest: preview.preview_digest, verified_review_acknowledged: verifiedAcknowledged };
      const data = await apiJson("/admin/rules/import/commit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      setImportMessage(`Import complete: ${data.created} created, ${data.unchanged} unchanged.`); setPreview(null); setImportText(""); await loadRules();
    } catch (error) { setError(error.message); } finally { setBusy(""); }
  }
  return <section><h3>Rule Management</h3><p className="review-note">DEMO / PROVISIONAL rules require official-source verification. A toggle does not make a rule official. Structured configurations are read-only.</p>
    {error && <p className="upload-error" role="alert">{error}</p>}
    <div className="table-scroll"><table><thead><tr><th>Code / title</th><th>Field / validator</th><th>Version / effective dates</th><th>Source / status</th><th>Active</th></tr></thead><tbody>
      {rules.map((rule) => <tr key={rule.id}><td>{rule.rule_code}<br/>{rule.title}<details><summary>Configuration</summary><pre>{JSON.stringify(rule.validator_config, null, 2)}</pre></details></td>
        <td>{rule.field_name}<br/>{rule.validator_type}</td><td>v{rule.version}<br/>{rule.effective_from} to {rule.effective_to || "open-ended"}</td>
        <td>{rule.source_document}<br/>{rule.source_reference || "Unverified reference"}<br/><span className={`verification-badge verification-${rule.verification_status.toLowerCase()}`}>{rule.verification_status}</span></td>
        <td><button className="secondary-button" disabled={Boolean(busy)} onClick={() => toggle(rule)}>{rule.is_active ? "Disable" : "Enable"}</button></td></tr>)}
    </tbody></table></div>
    <details className="rule-import"><summary>Import structured rules</summary><p>Paste the JSON object from the documented rule format. Validation never executes imported content.</p>
      <label htmlFor="rule-import-json">Rule JSON</label><textarea id="rule-import-json" rows="10" value={importText} onChange={(event) => { setImportText(event.target.value); setPreview(null); }} placeholder={'{"rules": [...]}'}/>
      {preview?.rules.some((item) => item.verification_status === "VERIFIED") && <label className="verified-acknowledgement"><input type="checkbox" checked={verifiedAcknowledged} onChange={(event) => setVerifiedAcknowledged(event.target.checked)}/> I confirm an authorized external legal review assigned VERIFIED status. PackSure does not verify legal authority automatically.</label>}
      <div className="analysis-actions"><button className="secondary-button" disabled={!importText.trim() || Boolean(busy)} onClick={validateImport}>Validate / Preview</button>{preview?.valid && <button className="primary-button" disabled={Boolean(busy) || (preview.rules.some((item) => item.verification_status === "VERIFIED") && !verifiedAcknowledged)} onClick={commitImport}>Commit Import</button>}</div>
      {importMessage && <p className="upload-success">{importMessage}</p>}{preview && <ul>{preview.rules.map((item) => <li key={`${item.rule_code}-${item.version}`}>{item.rule_code} v{item.version}: {item.action} ({item.verification_status})</li>)}</ul>}
    </details>
  </section>;
}
