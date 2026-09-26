import { useEffect, useState } from "react";
import App from "./App.jsx";
import { apiJson, logout, TOKEN_KEY } from "./api.js";

export default function AuthApp() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    const signedOut = () => setUser(null);
    window.addEventListener("packsure-logout", signedOut);
    async function restore() {
      try {
        if (localStorage.getItem(TOKEN_KEY)) {
          const account = await apiJson("/auth/me");
          if (active) setUser(account);
        }
      } catch {
        if (active) setError("Please log in again. If the backend is offline, start it first.");
      } finally {
        if (active) setChecking(false);
      }
    }
    restore();
    return () => { active = false; window.removeEventListener("packsure-logout", signedOut); };
  }, []);

  async function login(event) {
    event.preventDefault();
    setError("");
    setLoading(true);
    const form = new FormData(event.currentTarget);
    try {
      const data = await apiJson("/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
        signal: AbortSignal.timeout(15000),
      });
      localStorage.setItem(TOKEN_KEY, data.access_token);
      setUser(data.user);
    } catch (error) {
      setError(error instanceof TypeError ? "Cannot reach the backend. Please try again." : error.message);
    } finally {
      setLoading(false);
    }
  }

  if (checking) return <div className="auth-page"><p role="status">Checking your session...</p></div>;
  if (user) return <App key={user.id} user={user} onLogout={logout} />;
  return <main className="auth-page"><section className="panel auth-panel">
    <h1>PackSure AI</h1><p>Sign in to your inspection workspace.</p>
    <form onSubmit={login}>
      <label htmlFor="login-email">Email</label>
      <input id="login-email" name="email" type="email" required autoComplete="username" />
      <label htmlFor="login-password">Password</label>
      <input id="login-password" name="password" type="password" required autoComplete="current-password" />
      <button className="primary-button" disabled={loading}>{loading ? "Signing in..." : "Log In"}</button>
      {error && <p className="upload-error" role="alert">{error}</p>}
    </form>
  </section></main>;
}
