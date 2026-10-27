import { useEffect, useMemo, useState } from "react";
import React from "react";
import {
  Activity, AlertOctagon, ArrowUpRight, Bell, BrainCircuit, Check, ChevronDown,
  CircleHelp, Clock3, Download, FileSearch, Filter, Gauge, LayoutDashboard, LogOut,
  ListFilter, LockKeyhole, Menu, Search, ShieldAlert, ShieldCheck, Users, RefreshCw,
  SlidersHorizontal, Upload, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

type Transaction = {
  id: string; amount: number; currency: string; country: string; risk_score: number;
  risk_category: "low" | "medium" | "high"; recommended_action: string; reasons: string[];
  review_status: "legitimate" | "confirmed_fraud" | "needs_review";
  review_note?: string; reviewer?: string | null; created_at: string;
  cross_border: boolean; transactions_last_hour: number; account_age_days: number; hour_of_day: number;
};
type Summary = {
  total_transactions: number; total_amount: number; high_risk_count: number;
  pending_reviews: number; confirmed_fraud_count: number; high_risk_amount: number;
  low_risk_count: number; medium_risk_count: number; data_mode: string;
};
type Evaluation = {
  status: string; source?: string; dataset: string; precision: number; recall: number; accuracy: number;
  f1?: number; pr_auc?: number | null; roc_auc?: number | null; threshold?: number;
  total_misclassification_cost?: number;
  confusion_matrix: { tp: number; fp: number; fn: number; tn: number }; warning: string;
};
type Page = "overview" | "transactions" | "investigations" | "model" | "policies" | "audit" | "team";
type SessionInfo = { id: string; current: boolean; created_at: string; expires_at: string; ip_address?: string | null; user_agent?: string | null };
type AuthUser = { id: string; email: string; role: "admin" | "analyst" | "viewer"; is_active: boolean; tenant_name?: string; created_at: string };
type AuthPayload = { access_token: string; token_type: "bearer"; expires_in: number; user: AuthUser };

const money = (amount: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 2,
}).format(amount);
const dateTime = (value: string) => new Date(value).toLocaleString([], {
  month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
});

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = window.localStorage.getItem("risklens_token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    if (response.status === 401 && path !== "/api/auth/login") {
      window.localStorage.removeItem("risklens_token");
      window.localStorage.removeItem("risklens_user");
      window.dispatchEvent(new Event("risklens:unauthorized"));
    }
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const navGroups: { title: string; items: { id: Page; label: string; icon: typeof LayoutDashboard; badge?: string }[] }[] = [
  { title: "WORKSPACE", items: [
    { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
    { id: "transactions" as const, label: "Transactions", icon: Activity },
    { id: "investigations" as const, label: "Investigations", icon: FileSearch, badge: "!" },
    { id: "team" as const, label: "Team & security", icon: Users },
  ]},
  { title: "INTELLIGENCE", items: [
    { id: "model" as const, label: "Model evaluation", icon: BrainCircuit },
    { id: "policies" as const, label: "Risk policies", icon: SlidersHorizontal },
    { id: "audit" as const, label: "Audit trail", icon: ShieldCheck },
  ]},
];

function RiskPill({ risk }: { risk: string }) {
  return <span className={`risk-pill risk-${risk}`}><span />{risk}</span>;
}
function StatusPill({ status }: { status: string }) {
  const label = status === "confirmed_fraud" ? "Confirmed fraud" : status === "needs_review" ? "Needs review" : "Legitimate";
  return <span className={`status-pill status-${status}`}>{label}</span>;
}
function ScoreRing({ score }: { score: number }) {
  return <div className={`score-ring ${score >= 65 ? "danger" : score >= 30 ? "warning" : "safe"}`} style={{ "--score": `${score * 3.6}deg` } as React.CSSProperties}>
    <div><strong>{score}</strong><span>RISK SCORE</span></div>
  </div>;
}

type AuthMode = "login" | "register" | "forgot" | "reset" | "invite";

function AuthScreen({ onAuthenticated }: { onAuthenticated: (payload: AuthPayload) => void }) {
  const query = new URLSearchParams(window.location.search);
  const resetToken = query.get("reset_token") || "";
  const invitationToken = query.get("invite_token") || "";
  const [mode, setMode] = useState<AuthMode>(resetToken ? "reset" : invitationToken ? "invite" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [actionToken] = useState(resetToken || invitationToken);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function switchMode(next: AuthMode) {
    setMode(next);
    setPassword("");
    setError("");
    setNotice("");
    if (next === "login" || next === "register" || next === "forgot") {
      window.history.replaceState({}, "", window.location.pathname);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (mode === "forgot") {
        const response = await api<{ message: string }>("/api/auth/password-reset/request", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email }),
        });
        setNotice(response.message);
        return;
      }
      if (mode === "reset") {
        await api("/api/auth/password-reset/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: actionToken, new_password: password }),
        });
        switchMode("login");
        setNotice("Your password was changed. Sign in with your new password.");
        return;
      }
      if (mode === "invite") {
        const invited = await api<AuthUser>("/api/auth/invitations/accept", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: actionToken, password }),
        });
        setEmail(invited.email);
        const loginPayload = await api<AuthPayload>("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ username: invited.email, password }),
        });
        window.history.replaceState({}, "", window.location.pathname);
        onAuthenticated(loginPayload);
        return;
      }
      if (mode === "register") {
        await api("/api/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
      }
      const payload = await api<AuthPayload>("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: email, password }),
      });
      onAuthenticated(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request could not be completed");
    } finally {
      setBusy(false);
    }
  }

  const title: Record<AuthMode, string> = {
    login: "Welcome back.",
    register: "Create your workspace.",
    forgot: "Reset your password.",
    reset: "Choose a new password.",
    invite: "Join your workspace.",
  };
  const description: Record<AuthMode, string> = {
    login: "Sign in to investigate risk and review transaction activity.",
    register: "Start a separate workspace. You will be its administrator.",
    forgot: "Enter your account email. If it exists, we will send a one-time recovery link.",
    reset: "Choose a strong password. This link expires after 30 minutes and can only be used once.",
    invite: "Choose a password to accept your workspace invitation.",
  };
  const needsEmail = mode === "login" || mode === "register" || mode === "forgot";
  const needsPassword = mode !== "forgot";

  return <div className="auth-screen">
    <form className="auth-card" onSubmit={(event) => void submit(event)}>
      <div className="auth-brand"><div className="brand-mark"><ShieldCheck size={22}/></div><div><strong>risklens<span> AI</span></strong><small>RISK INTELLIGENCE</small></div></div>
      <span className="auth-eyebrow">SECURE WORKSPACE</span>
      <h1>{title[mode]}</h1>
      <p>{description[mode]}</p>
      {needsEmail && <label>Email address<input autoComplete="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={320} placeholder="you@company.com"/></label>}
      {needsPassword && <label>{mode === "login" ? "Password" : "Password (12+ characters)"}<input autoComplete={mode === "login" ? "current-password" : "new-password"} type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={12} maxLength={128} placeholder="At least 12 characters"/></label>}
      {mode === "invite" && <div className="auth-info">Invitation links are one-time and expire after 72 hours.</div>}
      {notice && <div className="auth-notice" role="status">{notice}</div>}
      {error && <div className="auth-error" role="alert">{error}</div>}
      <button className="btn btn-primary auth-submit" type="submit" disabled={busy || ((mode === "reset" || mode === "invite") && !actionToken)}>{busy ? "Please wait…" : ({
        login: "Sign in securely",
        register: "Create workspace",
        forgot: "Send recovery instructions",
        reset: "Update password",
        invite: "Accept invitation",
      } as Record<AuthMode, string>)[mode]}</button>
      <div className="auth-switch-row">
        {mode === "login" && <button className="auth-switch" type="button" onClick={() => switchMode("forgot")}>Forgot password?</button>}
        {mode === "login" && <button className="auth-switch" type="button" onClick={() => switchMode("register")}>Create a workspace</button>}
        {(mode === "register" || mode === "forgot" || mode === "reset" || mode === "invite") && <button className="auth-switch" type="button" onClick={() => switchMode("login")}>Back to sign in</button>}
      </div>
      <small className="auth-footnote">Demo risk scores are decision-support signals, not live payment decisions.</small>
    </form>
  </div>;
}

export default function App() {
  const [authToken, setAuthToken] = useState(() => window.localStorage.getItem("risklens_token") || "");
  const [authUser, setAuthUser] = useState<AuthUser | null>(() => {
    try { return JSON.parse(window.localStorage.getItem("risklens_user") || "null") as AuthUser | null; }
    catch { return null; }
  });
  const [page, setPage] = useState<Page>("overview");
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [selected, setSelected] = useState<Transaction | null>(null);
  const [search, setSearch] = useState("");
  const [riskFilter, setRiskFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [policyLow, setPolicyLow] = useState(29);
  const [policyReview, setPolicyReview] = useState(64);
  const [uploadRows, setUploadRows] = useState<Record<string, unknown>[]>([]);
  const [auditRows, setAuditRows] = useState<Record<string, unknown>[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "analyst" | "viewer">("analyst");
  const [inviteUrl, setInviteUrl] = useState("");
  const [teamNotice, setTeamNotice] = useState("");
  const [teamError, setTeamError] = useState("");
  const [teamBusy, setTeamBusy] = useState(false);
  const [reviewNote, setReviewNote] = useState("");
  const [scoringForm, setScoringForm] = useState({
    amount: "1250", country: "US", cross_border: false,
    transactions_last_hour: "2", account_age_days: "120", hour_of_day: "12",
  });
  const [singleScore, setSingleScore] = useState<Record<string, unknown> | null>(null);

  async function refresh() {
    try {
      setApiError("");
      const [s, t, e, p] = await Promise.all([
        api<Summary>("/api/summary"),
        api<{items: Transaction[]}>("/api/transactions"),
        api<Evaluation>("/api/evaluation"),
        api<{low_max: number; review_max: number}>("/api/policies"),
      ]);
      setSummary(s);
      setTransactions(t.items);
      setEvaluation(e);
      setPolicyLow(p.low_max);
      setPolicyReview(p.review_max);
      if (selected) {
        const updated = t.items.find((row) => row.id === selected.id);
        if (updated) setSelected(updated);
      }
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not reach API");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!authToken) { setLoading(false); return; }
    let cancelled = false;
    (async () => {
      try {
        const user = await api<AuthUser>("/api/auth/me");
        if (cancelled) return;
        setAuthUser(user);
        window.localStorage.setItem("risklens_user", JSON.stringify(user));
        await refresh();
      } catch {
        if (cancelled) return;
        window.localStorage.removeItem("risklens_token");
        window.localStorage.removeItem("risklens_user");
        setAuthToken("");
        setAuthUser(null);
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [authToken]);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const filtered = useMemo(() => transactions.filter((t) => {
    const matchesSearch = !search || `${t.id} ${t.country}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch && (riskFilter === "all" || t.risk_category === riskFilter)
      && (statusFilter === "all" || t.review_status === statusFilter)
      && (page !== "investigations" || t.review_status === "needs_review");
  }), [transactions, search, riskFilter, statusFilter, page]);

  async function submitReview(id: string, decision: "confirmed_fraud" | "legitimate" | "needs_review") {
    try {
      await api(`/api/reviews/${id}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, note: reviewNote, reviewer: "demo-analyst" }),
      });
      setToast(`Review saved: ${id.replace("txn_", "#")}`);
      setReviewNote("");
      await refresh();
      const detail = await api<Transaction>(`/api/transactions/${id}`);
      setSelected(detail);
    } catch (error) { setToast(error instanceof Error ? error.message : "Could not save review"); }
  }

  async function savePolicy() {
    try {
      await api("/api/policies", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ low_max: policyLow, review_max: policyReview }),
      });
      setToast("Demo policy updated");
      await refresh();
    } catch (error) { setToast(error instanceof Error ? error.message : "Policy could not be saved"); }
  }

  async function runScore() {
    try {
      const result = await api<Record<string, unknown>>("/api/transactions/score", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount: Number(scoringForm.amount), country: scoringForm.country,
          currency: "USD", cross_border: scoringForm.cross_border,
          transactions_last_hour: Number(scoringForm.transactions_last_hour),
          account_age_days: Number(scoringForm.account_age_days),
          hour_of_day: Number(scoringForm.hour_of_day),
        }),
      });
      setSingleScore(result);
    } catch (error) { setToast(error instanceof Error ? error.message : "Scoring failed"); }
  }

  async function handleUpload(file?: File) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    try {
      const result = await api<{items: Record<string, unknown>[]}>("/api/transactions/batch", { method: "POST", body });
      setUploadRows(result.items);
      setToast(`Scored ${result.items.length} rows`);
    } catch (error) { setToast(error instanceof Error ? error.message : "CSV scoring failed"); }
  }

  async function loadAudit() {
    try {
      const result = await api<{items: Record<string, unknown>[], total: number}>("/api/audit");
      setAuditRows(result.items);
    } catch (error) { setToast(error instanceof Error ? error.message : "Could not load audit log"); }
  }
  async function loadSessions() {
    try {
      const result = await api<{items: SessionInfo[]}>("/api/auth/sessions");
      setSessions(result.items);
    } catch (error) {
      setTeamError(error instanceof Error ? error.message : "Could not load sessions");
    }
  }
  async function createInvitation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTeamBusy(true);
    setTeamError("");
    setTeamNotice("");
    setInviteUrl("");
    try {
      const result = await api<{email: string; role: string; expires_at: string; invite_url?: string}>(
        "/api/auth/invitations",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
        },
      );
      setInviteUrl(result.invite_url || "");
      setTeamNotice(`Invitation created for ${result.email} as ${result.role}. Expires ${dateTime(result.expires_at)}.`);
      setInviteEmail("");
      await loadSessions();
    } catch (error) {
      setTeamError(error instanceof Error ? error.message : "Could not create invitation");
    } finally {
      setTeamBusy(false);
    }
  }
  async function revokeSession(sessionId: string) {
    setTeamBusy(true);
    setTeamError("");
    setTeamNotice("");
    try {
      await api(`/api/auth/sessions/${encodeURIComponent(sessionId)}/revoke`, { method: "POST" });
      setTeamNotice("Session revoked. That session can no longer use its access token.");
      await loadSessions();
    } catch (error) {
      setTeamError(error instanceof Error ? error.message : "Could not revoke session");
    } finally {
      setTeamBusy(false);
    }
  }
  function clearLocalSession() {
    window.localStorage.removeItem("risklens_token");
    window.localStorage.removeItem("risklens_user");
    setAuthToken("");
    setAuthUser(null);
    setSelected(null);
    setLoading(false);
  }
  async function signOutAllSessions() {
    setTeamBusy(true);
    try {
      await api("/api/auth/logout-all", { method: "POST" });
      clearLocalSession();
    } catch (error) {
      setTeamError(error instanceof Error ? error.message : "Could not revoke sessions");
    } finally {
      setTeamBusy(false);
    }
  }
  useEffect(() => { if (page === "audit") void loadAudit(); }, [page]);
  useEffect(() => { if (page === "team") { setTeamError(""); setTeamNotice(""); void loadSessions(); } }, [page]);
  useEffect(() => {
    const handleUnauthorized = () => {
      setAuthToken("");
      setAuthUser(null);
      setSelected(null);
      setLoading(false);
    };
    window.addEventListener("risklens:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("risklens:unauthorized", handleUnauthorized);
  }, []);

  function exportTransactions() {
    const headers = ["id", "amount", "currency", "country", "risk_score", "risk_category", "review_status", "reasons"];
    const lines = [headers.join(","), ...filtered.map((t) => headers.map((key) => {
      const value = (t as unknown as Record<string, unknown>)[key];
      return csvCell(value);
    }).join(","))];
    downloadCsv(lines.join("\n"), "risklens-transactions.csv");
  }

  const trend = [
    { time: "09:00", volume: 48, risky: 5 }, { time: "09:15", volume: 62, risky: 8 },
    { time: "09:30", volume: 56, risky: 7 }, { time: "09:45", volume: 74, risky: 14 },
    { time: "10:00", volume: 66, risky: 11 }, { time: "10:15", volume: 88, risky: 18 },
    { time: "10:30", volume: 79, risky: 12 }, { time: "10:45", volume: 96, risky: 20 },
    { time: "11:00", volume: 83, risky: 15 },
  ];
  const pageTitle = ({
    overview: "Risk overview", transactions: "Transactions", investigations: "Investigations",
    model: "Model evaluation", policies: "Risk policies", audit: "Audit trail", team: "Team & security",
  } satisfies Record<Page, string>)[page];

  if (!authToken || !authUser) return <AuthScreen onAuthenticated={(payload) => {
    window.localStorage.setItem("risklens_token", payload.access_token);
    window.localStorage.setItem("risklens_user", JSON.stringify(payload.user));
    setAuthToken(payload.access_token);
    setAuthUser(payload.user);
    setLoading(true);
  }} />;

  return <div className="app-shell">
    <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
      <div className="brand">
        <div className="brand-mark"><ShieldCheck size={21} strokeWidth={2.4} /></div>
        <div><strong>risklens<span> AI</span></strong><small>RISK INTELLIGENCE</small></div>
        <button className="icon-button mobile-close" onClick={() => setMobileNav(false)} aria-label="Close navigation"><X size={18}/></button>
      </div>
      <div className="workspace-switch"><div className="workspace-avatar">{(authUser.tenant_name || "Workspace").slice(0, 1).toUpperCase()}</div><div><strong>{authUser.tenant_name || "Workspace"}</strong><small>{authUser.tenant_name === "Northstar Payments" ? "Demo workspace" : "Tenant workspace"}</small></div><ChevronDown size={15}/></div>
      <nav>
        {navGroups.map((group) => <div className="nav-group" key={group.title}>
          <div className="nav-label">{group.title}</div>
          {group.items.filter(({ id }) => id !== "audit" || authUser.role !== "viewer").map(({ id, label, icon: Icon, badge }) => <button key={id} className={`nav-item ${page === id ? "active" : ""}`} onClick={() => { setPage(id); setMobileNav(false); }}>
            <Icon size={17}/><span>{label}</span>{badge && <em>{summary?.pending_reviews ?? "!"}</em>}
          </button>)}
        </div>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="model-status"><span className="pulse-dot"/><div><strong>Demo rules engine</strong><small>API connected when online</small></div></div>
        <button className="nav-item" onClick={() => setToast("Demo environment: no real payments are connected.")}><CircleHelp size={17}/><span>Help & documentation</span></button>
        <div className="profile-row"><div className="profile-avatar">{authUser.email.slice(0, 2).toUpperCase()}</div><div><strong>{authUser.email}</strong><small>{authUser.role} account</small></div><button className="icon-button" title="Sign out" aria-label="Sign out" onClick={() => { void api("/api/auth/logout", { method: "POST" }).catch(() => undefined).finally(clearLocalSession); }}><LogOut size={16}/></button></div>
      </div>
    </aside>

    {mobileNav && <button className="mobile-overlay" aria-label="Close navigation overlay" onClick={() => setMobileNav(false)}/>}

    <main className="main-area">
      <header className="topbar">
        <div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={19}/></button><div className="breadcrumbs">Risk operations <span>/</span> <strong>{pageTitle}</strong></div></div>
        <div className="topbar-actions"><div className="environment-chip"><span/> DEMO ENVIRONMENT</div><button className="icon-button notification-button" onClick={() => setPage("investigations")} aria-label="Open reviews"><Bell size={18}/>{(summary?.pending_reviews ?? 0) > 0 && <i/>}</button><div className="topbar-divider"/><div className="topbar-date"><strong>Risk operations</strong><small>Analyst workspace</small></div></div>
      </header>

      <div className="page-content">
        {apiError && <div className="error-banner"><AlertOctagon size={18}/><div><strong>API connection issue</strong><span>{apiError}. Start the FastAPI server using the README instructions, then refresh.</span></div><button onClick={() => void refresh()}>Retry</button></div>}
        <div className="page-heading"><div><div className="eyebrow"><span className="pulse-dot"/> MONITORING CENTER <span className="heading-dot">·</span> {new Date().toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}</div><h1>{pageTitle}<span>.</span></h1><p>{page === "overview" ? "A clear view of transaction risk, review priorities, and operational signals." : page === "investigations" ? "Resolve flagged transactions with a clear decision trail." : page === "model" ? "Understand how the current risk rules behave. Demo metrics are not benchmark results." : page === "policies" ? "Tune demo thresholds and see changes flow into transaction scoring." : page === "audit" ? "Review policy changes and analyst actions recorded during this session." : "Search, filter, inspect, and export transaction risk signals."}</p></div>
          <div className="heading-actions"><button className="btn btn-secondary" onClick={() => void refresh()}><Activity size={15}/> Refresh</button>{page === "transactions" && <button className="btn btn-primary" onClick={exportTransactions}><Download size={15}/> Export CSV</button>}</div>
        </div>

        {loading && !summary ? <div className="loading-state"><div className="spinner"/><span>Connecting to risk intelligence API…</span></div> :
          <>
            {page === "overview" && summary && <Overview summary={summary} trend={trend} evaluation={evaluation} transactions={transactions} onSelect={setSelected} onPage={setPage}/>}
            {(page === "transactions" || page === "investigations") && <section className="panel transaction-panel">
              <div className="panel-heading"><div><h2>{page === "investigations" ? "Cases requiring review" : "Transaction stream"}</h2><p>{page === "investigations" ? "Human decision required before a case is resolved." : "Risk-scored sample activity in the demo workspace."}</p></div><div className="table-count"><span className="pulse-dot"/>{filtered.length} records</div></div>
              <div className="table-toolbar"><div className="search-box"><Search size={16}/><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search transaction or country…"/>{search && <button onClick={() => setSearch("")} aria-label="Clear search"><X size={14}/></button>}</div><div className="toolbar-filters"><label><ListFilter size={15}/><select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}><option value="all">All risks</option><option value="low">Low risk</option><option value="medium">Medium risk</option><option value="high">High risk</option></select></label><label><Filter size={15}/><select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">All statuses</option><option value="needs_review">Needs review</option><option value="confirmed_fraud">Confirmed fraud</option><option value="legitimate">Legitimate</option></select></label><label className="upload-button"><Upload size={15}/> Import CSV<input type="file" accept=".csv,text/csv" onChange={(e) => void handleUpload(e.target.files?.[0])}/></label></div></div>
              <TransactionTable rows={filtered} onSelect={setSelected}/>
              {filtered.length === 0 && <div className="empty-state">No transactions match these filters.</div>}
              {uploadRows.length > 0 && <div className="upload-result"><div><strong><Check size={16}/> Batch scoring complete</strong><span>{uploadRows.length} CSV rows evaluated with the demo rules engine.</span></div><button className="btn btn-secondary btn-small" onClick={() => downloadRows(uploadRows)}>Download results <Download size={14}/></button><button className="icon-button" onClick={() => setUploadRows([])} aria-label="Dismiss batch results"><X size={15}/></button></div>}
            </section>}

            {page === "model" && evaluation && <ModelPage evaluation={evaluation} scoringForm={scoringForm} setScoringForm={setScoringForm} runScore={runScore} singleScore={singleScore}/>}
            {page === "policies" && <section className="panel policy-panel"><div className="panel-heading"><div><h2>Risk routing thresholds</h2><p>Scores are demo rule points, not fraud probabilities.</p></div><span className="tag tag-amber">DEMO CONFIGURATION</span></div><div className="policy-scale"><div className="scale-segment safe-segment">LOW <span>0–{policyLow}</span></div><div className="scale-segment medium-segment">REVIEW <span>{policyLow + 1}–{policyReview}</span></div><div className="scale-segment high-segment">HIGH <span>{policyReview + 1}–100</span></div></div><div className="policy-controls"><label><span><strong>Low risk maximum</strong><small>Scores up to this value stay in the low-risk band.</small></span><input type="number" min={0} max={98} value={policyLow} onChange={(e) => setPolicyLow(Number(e.target.value))}/></label><label><span><strong>Manual review maximum</strong><small>Higher scores route to priority review.</small></span><input type="number" min={1} max={100} value={policyReview} onChange={(e) => setPolicyReview(Number(e.target.value))}/></label></div>{policyReview <= policyLow && <div className="inline-error">Review threshold must be greater than low-risk threshold.</div>}<div className="policy-footer"><p><LockKeyhole size={14}/> Changes are saved to the configured database. Thresholds are still illustrative demo rules.</p>{authUser.role === "admin" && <button disabled={policyReview <= policyLow || policyLow < 0 || policyReview > 100} className="btn btn-primary" onClick={() => void savePolicy()}>Save policy <Check size={15}/></button>}</div></section>}

            {page === "audit" && <section className="panel"><div className="panel-heading"><div><h2>Recent audit events</h2><p>Review and policy events recorded by the API during this process.</p></div><button className="btn btn-secondary btn-small" onClick={() => void loadAudit()}><Activity size={14}/> Refresh log</button></div>{auditRows.length === 0 ? <div className="empty-state">No events yet. Review a transaction or update a risk policy to create an audit event.</div> : <div className="audit-list">{auditRows.map((row) => <div className="audit-item" key={String(row.id)}><div className="audit-icon"><ShieldCheck size={16}/></div><div><strong>{String(row.event_type).replaceAll("_", " ")}</strong><span>Actor: {String(row.actor)} · Transaction: {String(row.transaction_id)}</span><small>{dateTime(String(row.timestamp))}</small><code>{JSON.stringify(row.details)}</code></div></div>)}</div>}</section>}
          </>}
        <footer className="page-footer"><span>RiskLens AI <span className="footer-dot">·</span> Transaction risk intelligence</span><span><span className="footer-status"/> API-backed demo <span className="footer-dot">·</span> Synthetic records only</span></footer>
      </div>
    </main>

    {selected && <div className="drawer-backdrop" onClick={() => setSelected(null)} role="presentation"><aside className="detail-drawer" onClick={(e) => e.stopPropagation()}><div className="drawer-header"><div><span className="eyebrow">TRANSACTION INSPECTOR</span><h2>{selected.id}</h2></div><button className="icon-button" onClick={() => setSelected(null)} aria-label="Close transaction details"><X size={18}/></button></div><div className="drawer-body"><div className="drawer-score"><ScoreRing score={selected.risk_score}/><div><RiskPill risk={selected.risk_category}/><h3>{money(selected.amount)}</h3><span className="muted">{selected.country} · {selected.currency}</span><p className="muted">{dateTime(selected.created_at)}</p></div></div><div className="drawer-section"><div className="section-title">RECOMMENDED ROUTING</div><div className="recommendation"><ShieldAlert size={18}/><div><strong>{selected.recommended_action.replaceAll("_", " ")}</strong><p>Recommendation only. No payment action is connected.</p></div></div></div><div className="drawer-section"><div className="section-title">WHY WAS THIS FLAGGED?</div><div className="reason-list">{selected.reasons.map((reason) => <div key={reason}><span><Check size={13}/></span>{reason}</div>)}</div></div><div className="drawer-section"><div className="section-title">SIGNALS</div><div className="signal-grid"><Signal label="Account age" value={`${selected.account_age_days} days`}/><Signal label="Txns / hour" value={String(selected.transactions_last_hour)}/><Signal label="Transaction hour" value={`${selected.hour_of_day}:00`}/><Signal label="Cross-border" value={selected.cross_border ? "Yes" : "No"}/></div></div><div className="drawer-section"><div className="section-title">REVIEW STATUS</div><StatusPill status={selected.review_status}/>{authUser.role !== "viewer" ? <><textarea className="review-note" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} maxLength={1000} placeholder="Add a note to the review audit trail…"/><div className="review-actions"><button className="btn btn-danger" onClick={() => void submitReview(selected.id, "confirmed_fraud")}>Confirm fraud</button><button className="btn btn-secondary" onClick={() => void submitReview(selected.id, "legitimate")}>Mark legitimate</button></div><button className="review-reset" onClick={() => void submitReview(selected.id, "needs_review")}>Keep in review queue</button></> : <p className="muted">Read-only account. An analyst or admin must record review decisions.</p>}</div><div className="drawer-disclaimer"><LockKeyhole size={14}/> Demo-only scoring. Always validate signals and use human judgment.</div></div></aside></div>}

    {toast && <div className="toast"><Check size={16}/>{toast}<button onClick={() => setToast("")} aria-label="Dismiss notification"><X size={14}/></button></div>}
  </div>;
}

function Overview({ summary, trend, evaluation, transactions, onSelect, onPage }: {
  summary: Summary; trend: {time: string; volume: number; risky: number}[]; evaluation: Evaluation | null;
  transactions: Transaction[]; onSelect: (t: Transaction) => void; onPage: (p: Page) => void;
}) {
  return <>
    <div className="data-notice"><div className="notice-icon"><Activity size={17}/></div><div><strong>Demo workspace · Synthetic activity</strong><span>Transactions and labels are illustrative. Scoring is a transparent heuristic, not a validated fraud model.</span></div><span className="notice-pill">SANDBOX</span></div>
    <div className="metric-grid">
      <Metric label="Transactions analyzed" value={summary.total_transactions.toLocaleString()} delta="Current demo session" icon={<Activity size={17}/>} tone="blue" />
      <Metric label="High-risk flagged" value={summary.high_risk_count.toString()} delta={money(summary.high_risk_amount) + " flagged volume"} icon={<ShieldAlert size={17}/>} tone="red" />
      <Metric label="Pending investigations" value={summary.pending_reviews.toString()} delta="Awaiting analyst action" icon={<Clock3 size={17}/>} tone="amber" />
      <Metric label="Reviewed as fraud" value={summary.confirmed_fraud_count.toString()} delta="Human review outcomes" icon={<ShieldCheck size={17}/>} tone="green" />
    </div>
    <div className="dashboard-grid">
      <section className="panel chart-panel"><div className="panel-heading"><div><h2>Activity signals</h2><p>Illustrative hourly transaction activity</p></div><span className="tag tag-blue"><span/> SAMPLE SERIES</span></div><div className="chart-legend"><span><i className="legend-volume"/> Transaction volume</span><span><i className="legend-risk"/> Flagged signals</span></div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={trend} margin={{top:8,right:8,left:-24,bottom:0}}><defs><linearGradient id="volumeGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#5d8cff" stopOpacity={0.22}/><stop offset="100%" stopColor="#5d8cff" stopOpacity={0}/></linearGradient><linearGradient id="riskGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ed777e" stopOpacity={0.2}/><stop offset="100%" stopColor="#ed777e" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#e8ecf3" strokeDasharray="3 5" vertical={false}/><XAxis dataKey="time" axisLine={false} tickLine={false} tick={{fontSize:11,fill:"#8993a6"}} dy={8}/><YAxis axisLine={false} tickLine={false} tick={{fontSize:11,fill:"#8993a6"}}/><Tooltip contentStyle={{border:"1px solid #e5e9f1",borderRadius:12,fontSize:12,boxShadow:"0 8px 28px #12204412"}}/><Area type="monotone" dataKey="volume" name="Transaction volume" stroke="#5d8cff" strokeWidth={2.4} fill="url(#volumeGradient)"/><Area type="monotone" dataKey="risky" name="Flagged signals" stroke="#e47780" strokeWidth={2} fill="url(#riskGradient)"/></AreaChart></ResponsiveContainer></div><div className="chart-foot"><span><span className="footer-status"/> Sample series for visual preview</span><span>Not live processor traffic</span></div></section>
      <section className="panel distribution-panel"><div className="panel-heading"><div><h2>Risk distribution</h2><p>Current rule-score bands</p></div><Gauge size={17} className="heading-muted"/></div><div className="distribution-total"><strong>{summary.total_transactions}</strong><span>transactions</span></div><div className="distribution-bar"><span className="dist-low" style={{width:`${summary.total_transactions ? summary.low_risk_count/summary.total_transactions*100 : 0}%`}}/><span className="dist-medium" style={{width:`${summary.total_transactions ? summary.medium_risk_count/summary.total_transactions*100 : 0}%`}}/><span className="dist-high" style={{width:`${summary.total_transactions ? summary.high_risk_count/summary.total_transactions*100 : 0}%`}}/></div><div className="distribution-legend"><DistRow color="low" label="Low risk" count={summary.low_risk_count} total={summary.total_transactions}/><DistRow color="medium" label="Medium risk" count={summary.medium_risk_count} total={summary.total_transactions}/><DistRow color="high" label="High risk" count={summary.high_risk_count} total={summary.total_transactions}/></div><div className="distribution-note"><ShieldCheck size={15}/><span>Threshold based. No automatic blocking.</span></div></section>
    </div>
    <section className="panel recent-panel"><div className="panel-heading"><div><h2>Priority transactions</h2><p>Highest demo risk scores to inspect first</p></div><button className="text-button" onClick={() => onPage("transactions")}>View all transactions <span>→</span></button></div><TransactionTable rows={[...transactions].sort((a,b)=>b.risk_score-a.risk_score).slice(0,5)} onSelect={onSelect}/></section>
    <div className="bottom-grid"><section className="panel attention-panel"><div className="panel-heading"><div><h2>Investigation queue</h2><p>Cases needing a human decision</p></div><button className="text-button" onClick={() => onPage("investigations")}>Open queue →</button></div>{transactions.filter(t=>t.review_status==="needs_review").slice(0,3).map(t=><button className="queue-row" key={t.id} onClick={()=>onSelect(t)}><div className="queue-risk">{t.risk_score}</div><div className="queue-info"><strong>{t.id}</strong><span>{t.reasons[0]}</span></div><strong>{money(t.amount)}</strong><ChevronDown size={15}/></button>)}</section><section className="panel quality-panel"><div className="panel-heading"><div><h2>Model validation</h2><p>Evaluation status</p></div><BrainCircuit size={17} className="heading-muted"/></div><div className="validation-status"><span className="validation-icon"><CircleHelp size={18}/></span><div><strong>{evaluation?.status === "benchmark_evaluated" ? "Held-out benchmark loaded" : "Benchmark not yet evaluated"}</strong><span>{evaluation?.dataset ?? "Evaluation not loaded"}</span></div></div><div className="quality-stats"><div><span>Precision</span><strong>{evaluation?.status === "benchmark_evaluated" ? (evaluation.precision*100).toFixed(1)+"%" : "—"}</strong></div><div><span>Recall</span><strong>{evaluation?.status === "benchmark_evaluated" ? (evaluation.recall*100).toFixed(1)+"%" : "—"}</strong></div><div><span>PR-AUC</span><strong>{evaluation?.status === "benchmark_evaluated" && evaluation.pr_auc != null ? evaluation.pr_auc.toFixed(3) : "—"}</strong></div></div><button className="btn btn-secondary full-width" onClick={()=>onPage("model")}>Open evaluation lab <ArrowUpRight size={15}/></button></section></div>
  </>;
}

function Metric({label,value,delta,icon,tone}:{label:string;value:string;delta:string;icon:React.ReactNode;tone:string}){
  return <div className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong><div className="metric-delta">{delta}</div><div className="metric-sparkline"><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/><span className={tone}/></div></div>;
}
function DistRow({color,label,count,total}:{color:string;label:string;count:number;total:number}){return <div className="dist-row"><span className={`dist-key ${color}`}/><span>{label}</span><strong>{count}</strong><small>{total?Math.round(count/total*100):0}%</small></div>}
function Signal({label,value}:{label:string;value:string}){return <div className="signal-item"><span>{label}</span><strong>{value}</strong></div>}
function TransactionTable({rows,onSelect}:{rows:Transaction[];onSelect:(t:Transaction)=>void}){
  return <div className="table-scroll"><table className="transactions-table"><thead><tr><th>TRANSACTION</th><th>AMOUNT</th><th>RISK SCORE</th><th>RISK LEVEL</th><th>REVIEW STATUS</th><th>TIME</th><th></th></tr></thead><tbody>{rows.map((t)=> <tr key={t.id} onClick={()=>onSelect(t)} tabIndex={0} onKeyDown={(e)=>{if(e.key==="Enter")onSelect(t)}}><td><div className="transaction-id"><span className="transaction-glyph"><Activity size={14}/></span><span><strong>{t.id}</strong><small>{t.country} · {t.cross_border?"Cross-border":"Domestic"}</small></span></div></td><td className="amount-cell">{money(t.amount)}</td><td><div className="score-cell"><span>{t.risk_score}</span><div className="score-track"><i style={{width:`${t.risk_score}%`}} className={t.risk_category}/></div></div></td><td><RiskPill risk={t.risk_category}/></td><td><StatusPill status={t.review_status}/></td><td className="time-cell">{dateTime(t.created_at)}</td><td><button className="row-action" aria-label={`Inspect ${t.id}`}><ArrowUpRight size={15}/></button></td></tr>)}</tbody></table></div>;
}

function ModelPage({evaluation,scoringForm,setScoringForm,runScore,singleScore}:{evaluation:Evaluation;scoringForm:{amount:string;country:string;cross_border:boolean;transactions_last_hour:string;account_age_days:string;hour_of_day:string};setScoringForm:(v:{amount:string;country:string;cross_border:boolean;transactions_last_hour:string;account_age_days:string;hour_of_day:string})=>void;runScore:()=>void;singleScore:Record<string,unknown>|null}){
  const isBenchmark = evaluation.status === "benchmark_evaluated";
  const fields: ["amount" | "country" | "transactions_last_hour" | "account_age_days" | "hour_of_day", string, string][]=[["amount","Amount (USD)","number"],["country","Country code","text"],["transactions_last_hour","Transactions in last hour","number"],["account_age_days","Account age (days)","number"],["hour_of_day","Transaction hour (0–23)","number"]];
  return <div className="model-layout"><section className={`panel model-warning ${isBenchmark ? "model-warning-success" : ""}`}><div className="notice-icon">{isBenchmark ? <ShieldCheck size={18}/> : <AlertOctagon size={18}/>}</div><div><strong>{isBenchmark ? "Held-out benchmark evaluation available" : "Evaluation integrity notice"}</strong><p>{evaluation.warning}{isBenchmark ? ` Dataset: ${evaluation.dataset}. The threshold was selected on validation data; these metrics are from the separate held-out test partition.` : " Synthetic examples are only for exercising the interface and must not be quoted as model performance."}</p></div></section><div className="model-metrics"><Metric label={isBenchmark ? "Precision · test set" : "Precision · demo only"} value={`${(evaluation.precision*100).toFixed(1)}%`} delta={isBenchmark ? "Held-out benchmark" : "Synthetic labels"} icon={<Gauge size={17}/>} tone="blue"/><Metric label={isBenchmark ? "Recall · test set" : "Recall · demo only"} value={`${(evaluation.recall*100).toFixed(1)}%`} delta={isBenchmark ? "Held-out benchmark" : "Synthetic labels"} icon={<ShieldCheck size={17}/>} tone="amber"/><Metric label={isBenchmark ? "PR-AUC · test set" : "PR-AUC · demo only"} value={evaluation.pr_auc == null ? "—" : evaluation.pr_auc.toFixed(3)} delta={isBenchmark ? "Average precision" : "No benchmark loaded"} icon={<Activity size={17}/>} tone="red"/><Metric label={isBenchmark ? "F1 · test set" : "F1 · demo only"} value={evaluation.f1 == null ? "—" : evaluation.f1.toFixed(3)} delta={isBenchmark ? "Held-out benchmark" : "Synthetic labels"} icon={<Gauge size={17}/>} tone="green"/></div><section className="panel"><div className="panel-heading"><div><h2>Confusion matrix</h2><p>{isBenchmark ? `Held-out test partition · decision threshold ${evaluation.threshold?.toFixed(3) ?? "reported in artifact"}` : "Demo rules score versus hand-authored sample labels"}</p></div></div><div className="confusion-grid"><div className="confusion-empty"/><div className="confusion-head">Predicted positive</div><div className="confusion-head">Predicted negative</div><div className="confusion-label">Actual positive</div><div className="confusion-cell tp"><strong>{evaluation.confusion_matrix.tp}</strong><span>True positive</span></div><div className="confusion-cell fn"><strong>{evaluation.confusion_matrix.fn}</strong><span>False negative</span></div><div className="confusion-label">Actual negative</div><div className="confusion-cell fp"><strong>{evaluation.confusion_matrix.fp}</strong><span>False positive</span></div><div className="confusion-cell tn"><strong>{evaluation.confusion_matrix.tn}</strong><span>True negative</span></div></div><p className="small-note">{isBenchmark ? `Accuracy: ${(evaluation.accuracy*100).toFixed(1)}%. These results are a held-out estimate for the named public dataset, not a guarantee of production performance. Cost assumptions and dataset limitations must be reviewed before reuse.` : "A real benchmark pipeline and held-out test evaluation are required before these metrics can be interpreted as model quality."}</p></section><section className="panel score-playground"><div className="panel-heading"><div><h2>Try a transaction</h2><p>Run the current explainable demo rules on custom values.</p></div><span className="tag tag-amber">RULES ENGINE</span></div><div className="score-form">{fields.map(([key,label,type])=><label key={key}>{label}<input type={type} value={scoringForm[key]} min={key==="hour_of_day"?0:0} max={key==="hour_of_day"?23:undefined} onChange={(e)=>setScoringForm({...scoringForm,[key]:e.target.value})}/></label>)}<label className="check-field"><input type="checkbox" checked={scoringForm.cross_border} onChange={(e)=>setScoringForm({...scoringForm,cross_border:e.target.checked})}/> Cross-border transaction</label><button className="btn btn-primary" onClick={runScore}>Calculate risk score <Activity size={15}/></button></div>{singleScore&&<div className="score-result"><ScoreRing score={Number(singleScore.risk_score??0)}/><div><RiskPill risk={String(singleScore.risk_category)}/><h3>{String(singleScore.risk_score)} / 100 risk points</h3><p>{String(singleScore.disclaimer)}</p><strong>Triggered signals</strong><ul>{(singleScore.reasons as string[]).map(reason=><li key={reason}>{reason}</li>)}</ul></div></div>}</section></div>;
}

function csvCell(value: unknown): string {
  const raw = Array.isArray(value) ? value.join("; ") : String(value ?? "");
  // Prevent formula execution when exported CSV is opened in spreadsheet software.
  const formulaPrefix = ["=", "+", "-", "@"].includes(raw.trimStart().charAt(0));
  const safe = formulaPrefix ? `'${raw}` : raw;
  return `"${safe.replaceAll('"', '""')}"`;
}
function downloadRows(rows:Record<string,unknown>[]){
  if(!rows.length)return;
  const keys=Object.keys(rows[0]);
  const csv=[keys.join(","),...rows.map(row=>keys.map(key=>csvCell(row[key])).join(","))].join("\n");
  downloadCsv(csv,"risklens-batch-scores.csv");
}
function downloadCsv(csv: string, filename: string) {
  const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url);
}
