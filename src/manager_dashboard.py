from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .session_store import max_uploads_per_session


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def build_dashboard_payload(
    df: pd.DataFrame,
    summary: Optional[Dict] = None,
    excel_url: Optional[str] = None,
) -> Dict[str, Any]:
    if df.empty:
        return {
            "has_data": False,
            "kpis": {
                "total_expenses": 0,
                "total_amount": 0.0,
                "currency": "USD",
                "approved": 0,
                "needs_review": 0,
                "rejected": 0,
                "missing_info": 0,
                "high_risk": 0,
                "pending_review": 0,
            },
            "decision_breakdown": [],
            "spend_by_category": [],
            "action_items": [
                "Load expense data (sample CSV, import, or scan receipts).",
                "Run compliance check to generate manager review metrics.",
            ],
            "priority_exceptions": [],
            "entries": [],
            "summary": summary,
            "excel_url": excel_url,
            "analyzed": False,
            "upload_quota": {
                "limit": max_uploads_per_session(),
                "used": 0,
                "remaining": max_uploads_per_session(),
            },
        }

    has_decisions = "decision" in df.columns
    amounts = df["amount"].apply(_safe_float) if "amount" in df.columns else pd.Series([0.0] * len(df))
    total_amount = round(float(amounts.sum()), 2)
    currency = str(df["currency"].iloc[0]) if "currency" in df.columns and len(df) else "USD"

    decision_counts = {"Approved": 0, "Needs Review": 0, "Rejected": 0, "Missing Info": 0}
    high_risk = 0
    if has_decisions:
        for _, row in df.iterrows():
            d = str(row.get("decision", "") or "")
            if d in decision_counts:
                decision_counts[d] += 1
            if _safe_float(row.get("risk_score")) >= 75:
                high_risk += 1
    else:
        decision_counts = summary.get("decision_counts", decision_counts) if summary else decision_counts
        high_risk = summary.get("high_risk_items", 0) if summary else 0

    if summary and summary.get("decision_counts"):
        decision_counts = {**decision_counts, **summary["decision_counts"]}

    total = len(df)
    pending = total - sum(decision_counts.values()) if has_decisions else total

    breakdown = []
    colors = {
        "Approved": "#2e7d32",
        "Needs Review": "#f57f17",
        "Rejected": "#c62828",
        "Missing Info": "#1565c0",
    }
    for label, count in decision_counts.items():
        pct = round(100 * count / total, 1) if total else 0
        breakdown.append(
            {"label": label, "count": count, "percent": pct, "color": colors.get(label, "#607d8b")}
        )

    spend_by_category: List[Dict] = []
    if "category" in df.columns:
        grp = df.groupby("category")["amount"].apply(lambda s: sum(_safe_float(x) for x in s))
        for cat, amt in grp.sort_values(ascending=False).items():
            spend_by_category.append({"category": str(cat), "amount": round(float(amt), 2)})

    action_items = list(summary.get("manager_next_steps", [])) if summary else []
    if not action_items and has_decisions:
        if decision_counts.get("Rejected", 0):
            action_items.append(f"Review {decision_counts['Rejected']} rejected expense(s) immediately.")
        if decision_counts.get("Missing Info", 0):
            action_items.append(f"Request receipts for {decision_counts['Missing Info']} missing-info item(s).")
        if decision_counts.get("Needs Review", 0):
            action_items.append(f"Approve or deny {decision_counts['Needs Review']} item(s) over policy limits.")
        if high_risk:
            action_items.append(f"Prioritize {high_risk} high-risk exception(s) (risk score ≥ 75).")
    if not action_items:
        action_items = ["Run compliance check to populate manager actions."]

    priority: List[Dict] = []
    if has_decisions:
        order = {"Rejected": 0, "Missing Info": 1, "Needs Review": 2, "Approved": 3}
        sorted_df = df.copy()
        sorted_df["_sort"] = sorted_df["decision"].map(lambda d: order.get(str(d), 9))
        if "risk_score" in sorted_df.columns:
            sorted_df["_risk"] = sorted_df["risk_score"].apply(_safe_float)
        else:
            sorted_df["_risk"] = 0
        sorted_df = sorted_df.sort_values(["_sort", "_risk"], ascending=[True, False])
        for _, row in sorted_df.head(8).iterrows():
            if str(row.get("decision")) in ("Rejected", "Missing Info", "Needs Review") or _safe_float(
                row.get("risk_score")
            ) >= 65:
                priority.append(row.drop(labels=["_sort", "_risk"], errors="ignore").to_dict())

    entries = df.to_dict(orient="records")
    for e in entries:
        for k, v in list(e.items()):
            if pd.isna(v):
                e[k] = ""

    return {
        "has_data": True,
        "analyzed": has_decisions,
        "kpis": {
            "total_expenses": total,
            "total_amount": total_amount,
            "currency": currency,
            "approved": decision_counts.get("Approved", 0),
            "needs_review": decision_counts.get("Needs Review", 0),
            "rejected": decision_counts.get("Rejected", 0),
            "missing_info": decision_counts.get("Missing Info", 0),
            "high_risk": high_risk,
            "pending_review": pending if pending > 0 else 0,
        },
        "decision_breakdown": breakdown,
        "spend_by_category": spend_by_category,
        "action_items": action_items,
        "priority_exceptions": priority,
        "entries": entries,
        "summary": summary,
        "excel_url": excel_url,
    }


MANAGER_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Manager Dashboard | Expense Compliance</title>
  <style>
    :root {
      --bg: #0f172a;
      --surface: #1e293b;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --accent: #2563eb;
      --accent-dark: #1d4ed8;
      --green: #16a34a;
      --amber: #d97706;
      --red: #dc2626;
      --blue: #2563eb;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: "Segoe UI", system-ui, sans-serif; background: #f1f5f9; color: var(--text); min-height: 100vh; }
    .topbar {
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
      color: #fff; padding: 1.25rem 2rem;
      display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 1rem;
    }
    .topbar h1 { font-size: 1.35rem; font-weight: 600; }
    .topbar p { font-size: 0.85rem; opacity: 0.85; margin-top: 0.25rem; }
    .topbar-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .btn {
      font: inherit; padding: 0.5rem 1rem; border-radius: 8px; border: none; cursor: pointer;
      font-weight: 500; transition: background 0.15s;
    }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { background: var(--accent-dark); }
    .btn-ghost { background: rgba(255,255,255,0.15); color: #fff; }
    .btn-ghost:hover { background: rgba(255,255,255,0.25); }
    .btn-outline { background: #fff; color: var(--accent); border: 1px solid #cbd5e1; }
    .btn-success { background: var(--green); color: #fff; }
    main { max-width: 1400px; margin: 0 auto; padding: 1.5rem 2rem 3rem; }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .kpi {
      background: var(--card); border-radius: 12px; padding: 1.1rem 1.25rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
      border-left: 4px solid var(--accent);
    }
    .kpi.green { border-left-color: var(--green); }
    .kpi.amber { border-left-color: var(--amber); }
    .kpi.red { border-left-color: var(--red); }
    .kpi.blue { border-left-color: var(--blue); }
    .kpi-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
    .kpi-value { font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; }
    .kpi-sub { font-size: 0.8rem; color: var(--muted); margin-top: 0.15rem; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-bottom: 1.25rem; }
    @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }
    .panel {
      background: var(--card); border-radius: 12px; padding: 1.25rem;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .panel h2 { font-size: 1rem; margin-bottom: 1rem; color: var(--text); }
    .bar-row { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.65rem; font-size: 0.85rem; }
    .bar-label { width: 110px; flex-shrink: 0; }
    .bar-track { flex: 1; height: 10px; background: #e2e8f0; border-radius: 5px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 5px; transition: width 0.4s ease; }
    .bar-count { width: 36px; text-align: right; font-weight: 600; }
    .actions-list { list-style: none; }
    .actions-list li {
      padding: 0.75rem 1rem; margin-bottom: 0.5rem; background: #f8fafc;
      border-radius: 8px; border-left: 3px solid var(--accent);
      font-size: 0.9rem; line-height: 1.4;
    }
    .actions-list li.urgent { border-left-color: var(--red); background: #fef2f2; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th, td { padding: 0.6rem 0.5rem; text-align: left; border-bottom: 1px solid #e2e8f0; }
    th { background: #f8fafc; font-weight: 600; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; }
    tr:hover td { background: #f8fafc; }
    .badge {
      display: inline-block; padding: 0.2rem 0.55rem; border-radius: 999px;
      font-size: 0.72rem; font-weight: 600;
    }
    .badge-Approved { background: #dcfce7; color: #166534; }
    .badge-Needs-Review { background: #fef9c3; color: #a16207; }
    .badge-Rejected { background: #fee2e2; color: #b91c1c; }
    .badge-Missing-Info { background: #dbeafe; color: #1d4ed8; }
    .empty-state {
      text-align: center; padding: 3rem 2rem; color: var(--muted);
    }
    .empty-state h3 { color: var(--text); margin-bottom: 0.5rem; }
    .tools {
      display: none; margin-bottom: 1.25rem;
    }
    .tools.open { display: block; }
    .tools-inner { background: var(--card); border-radius: 12px; padding: 1.25rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
    .tools .row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end; margin-top: 0.75rem; }
    #toast {
      position: fixed; bottom: 1.5rem; right: 1.5rem; background: #0f172a; color: #fff;
      padding: 0.75rem 1.25rem; border-radius: 8px; font-size: 0.9rem;
      opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 100;
    }
    #toast.show { opacity: 1; }
    .risk-high { color: var(--red); font-weight: 700; }
  </style>
</head>
<body>
  <header class="topbar">
    <div>
      <h1>Manager Expense Compliance Dashboard</h1>
      <p id="subtitle">Topline overview · exceptions · recommended actions</p>
    </div>
    <div class="topbar-actions">
      <button class="btn btn-ghost" id="togglePolicy">Policy thresholds</button>
      <button class="btn btn-ghost" id="toggleTools">+ Add expenses</button>
      <button class="btn btn-ghost" id="loadSampleBtn">Load demo data</button>
      <button class="btn btn-primary" id="analyzeBtn">Run compliance</button>
      <a id="excelLink" href="#" style="display:none;"><button class="btn btn-success">Download Excel</button></a>
    </div>
  </header>

  <main>
    <section class="tools" id="policyPanel">
      <div class="tools-inner">
        <h2 style="font-size:1rem;margin-bottom:0.5rem;">Approval thresholds</h2>
        <p style="font-size:0.85rem;color:#64748b;margin-bottom:0.75rem;">
          Adjust limits used by the Decide Agent. Save, then re-run compliance.
        </p>
        <div id="policyFields" class="row" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;"></div>
        <div style="margin-top:1rem;display:flex;gap:0.5rem;">
          <button class="btn btn-primary" id="savePolicyBtn" type="button">Save thresholds</button>
          <button class="btn btn-outline" id="resetPolicyBtn" type="button">Reset to defaults</button>
        </div>
      </div>
    </section>

    <section class="tools" id="toolsPanel">
      <div class="tools-inner">
        <h2 style="font-size:1rem;margin-bottom:0.5rem;">Add expenses</h2>
        <p id="uploadQuota" style="font-size:0.85rem;color:#64748b;margin-bottom:0.5rem;"></p>
        <div class="row">
          <div>
            <label style="font-size:0.8rem;color:#64748b;">Receipt (scan with AI)</label><br/>
            <input type="file" id="receiptFile" accept=".png,.jpg,.jpeg,.webp,.pdf,.gif,.bmp" />
          </div>
          <div>
            <label style="font-size:0.8rem;color:#64748b;">Employee ID</label><br/>
            <input type="text" id="employeeId" placeholder="E-1001" />
          </div>
          <button class="btn btn-outline" id="scanBtn">Scan receipt</button>
          <div>
            <label style="font-size:0.8rem;color:#64748b;">Import CSV</label><br/>
            <input type="file" id="csvFile" accept=".csv" />
          </div>
          <button class="btn btn-outline" id="importCsvBtn">Import</button>
        </div>
      </div>
    </section>

    <div id="emptyState" class="panel empty-state" style="display:none;">
      <h3>No expense data yet</h3>
      <p>Load demo data or add receipts to generate your managerial review dashboard.</p>
      <button class="btn btn-primary" style="margin-top:1rem;" onclick="document.getElementById('loadSampleBtn').click()">Load demo data</button>
    </div>

    <div id="dashboardContent">
      <div class="kpi-grid" id="kpiGrid"></div>

      <div class="grid-2">
        <div class="panel">
          <h2>Decision breakdown</h2>
          <div id="decisionBars"></div>
        </div>
        <div class="panel">
          <h2>Spend by category</h2>
          <div id="categoryBars"></div>
        </div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <h2>Manager actions required</h2>
          <ul class="actions-list" id="actionList"></ul>
        </div>
        <div class="panel">
          <h2>Priority exceptions</h2>
          <div style="overflow-x:auto;" id="priorityTable"></div>
        </div>
      </div>

      <div class="panel" style="margin-top:0;">
        <h2>All expense entries</h2>
        <div style="overflow-x:auto;margin-top:0.75rem;" id="fullTable"></div>
      </div>
    </div>
  </main>
  <div id="toast"></div>

  <script>
    const SESSION_KEY = "receipt_session_id";
    let sessionId = localStorage.getItem(SESSION_KEY);
    if (!sessionId) {
      sessionId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
      localStorage.setItem(SESSION_KEY, sessionId);
    }

    const toast = (msg) => {
      const el = document.getElementById("toast");
      el.textContent = msg;
      el.classList.add("show");
      setTimeout(() => el.classList.remove("show"), 3000);
    };

    const badge = (d) => {
      const cls = (d || "").replace(/\\s+/g, "-");
      return d ? `<span class="badge badge-${cls}">${d}</span>` : "—";
    };

    const renderBars = (containerId, items, valueKey, labelKey, colorKey) => {
      const el = document.getElementById(containerId);
      if (!items || !items.length) {
        el.innerHTML = '<p style="color:#64748b;font-size:0.9rem;">No data</p>';
        return;
      }
      const max = Math.max(...items.map(i => i[valueKey] || 0), 1);
      el.innerHTML = items.map(i => `
        <div class="bar-row">
          <span class="bar-label">${i[labelKey]}</span>
          <div class="bar-track"><div class="bar-fill" style="width:${((i[valueKey]/max)*100).toFixed(0)}%;background:${i[colorKey] || '#2563eb'}"></div></div>
          <span class="bar-count">${i[valueKey]}</span>
        </div>
      `).join("");
    };

    const renderDashboard = (data) => {
      const empty = document.getElementById("emptyState");
      const content = document.getElementById("dashboardContent");
      if (!data.has_data) {
        empty.style.display = "block";
        content.style.display = "none";
        return;
      }
      empty.style.display = "none";
      content.style.display = "block";

      const k = data.kpis;
      document.getElementById("kpiGrid").innerHTML = `
        <div class="kpi"><div class="kpi-label">Total expenses</div><div class="kpi-value">${k.total_expenses}</div></div>
        <div class="kpi blue"><div class="kpi-label">Total spend</div><div class="kpi-value">${k.currency} ${k.total_amount.toLocaleString()}</div></div>
        <div class="kpi green"><div class="kpi-label">Approved</div><div class="kpi-value">${k.approved}</div></div>
        <div class="kpi amber"><div class="kpi-label">Needs review</div><div class="kpi-value">${k.needs_review}</div></div>
        <div class="kpi red"><div class="kpi-label">Rejected</div><div class="kpi-value">${k.rejected}</div></div>
        <div class="kpi"><div class="kpi-label">High risk</div><div class="kpi-value">${k.high_risk}</div><div class="kpi-sub">Risk score ≥ 75</div></div>
      `;

      renderBars("decisionBars", data.decision_breakdown.map(d => ({
        label: d.label, count: d.count, color: d.color
      })), "count", "label", "color");

      const catItems = (data.spend_by_category || []).map(c => ({
        label: c.category, count: c.amount, color: "#6366f1"
      }));
      renderBars("categoryBars", catItems, "count", "label", "color");

      document.getElementById("actionList").innerHTML = (data.action_items || []).map((a, i) =>
        `<li class="${i < 2 && data.kpis.rejected + data.kpis.missing_info > 0 ? 'urgent' : ''}">${a}</li>`
      ).join("");

      const pri = data.priority_exceptions || [];
      document.getElementById("priorityTable").innerHTML = pri.length ? `
        <table><thead><tr><th>ID</th><th>Category</th><th>Amount</th><th>Decision</th><th>Risk</th><th>Reason</th></tr></thead>
        <tbody>${pri.map(e => `<tr>
          <td>${e.expense_id}</td><td>${e.category}</td><td>$${Number(e.amount||0).toFixed(2)}</td>
          <td>${badge(e.decision)}</td>
          <td class="${Number(e.risk_score)>=75?'risk-high':''}">${e.risk_score??'—'}</td>
          <td>${(e.reason_text||e.reason_code||'').slice(0,50)}</td>
        </tr>`).join("")}</tbody></table>
      ` : '<p style="color:#64748b;font-size:0.9rem;">No exceptions — or run compliance first.</p>';

      const entries = data.entries || [];
      document.getElementById("fullTable").innerHTML = entries.length ? `
        <table><thead><tr>
          <th>ID</th><th>Employee</th><th>Category</th><th>Amount</th><th>Date</th>
          <th>Decision</th><th>Risk</th><th>Reason</th><th>Notes</th>
        </tr></thead><tbody>
        ${entries.map(e => `<tr>
          <td>${e.expense_id}</td><td>${e.employee_id}</td><td>${e.category}</td>
          <td>${e.currency||'USD'} ${Number(e.amount||0).toFixed(2)}</td><td>${e.expense_date||''}</td>
          <td>${badge(e.decision)}</td>
          <td class="${Number(e.risk_score)>=75?'risk-high':''}">${e.risk_score??'—'}</td>
          <td>${(e.reason_text||e.reason_code||'—').slice(0,40)}</td>
          <td>${(e.notes||'').slice(0,35)}</td>
        </tr>`).join("")}
        </tbody></table>
      ` : '';

      if (data.excel_url) {
        const link = document.getElementById("excelLink");
        link.href = data.excel_url;
        link.style.display = "inline-block";
      }

      document.getElementById("subtitle").textContent = data.analyzed
        ? "Compliance review complete · " + k.total_expenses + " expenses · $" + k.total_amount.toLocaleString() + " total"
        : "Data loaded · run compliance to see decisions and actions";

      const q = data.upload_quota || { limit: 2, used: 0, remaining: 2 };
      const quotaEl = document.getElementById("uploadQuota");
      const atLimit = q.remaining <= 0;
      quotaEl.textContent = atLimit
        ? `Upload limit reached (${q.used}/${q.limit}). Use Load demo data or clear session.`
        : `Uploads: ${q.used} of ${q.limit} used (${q.remaining} remaining per user)`;
      quotaEl.style.color = atLimit ? "#c62828" : "#64748b";
      document.getElementById("scanBtn").disabled = atLimit;
      document.getElementById("importCsvBtn").disabled = atLimit;
      document.getElementById("receiptFile").disabled = atLimit;
      document.getElementById("csvFile").disabled = atLimit;
    };

    async function refreshDashboard() {
      const res = await fetch(`/api/session/${sessionId}/dashboard`);
      const data = await res.json();
      renderDashboard(data);
    }

    function renderPolicyFields(policy) {
      const wrap = document.getElementById("policyFields");
      const fields = policy?.fields || [];
      wrap.innerHTML = fields.map(f => `
        <div>
          <label style="font-size:0.8rem;color:#64748b;">${f.label}</label>
          <input type="number" data-key="${f.key}" value="${f.value}"
            min="${f.min}" max="${f.max}" step="${f.type === 'integer' ? 1 : 0.01}"
            style="width:100%;margin-top:0.25rem;padding:0.5rem;border:1px solid #ccc;border-radius:6px;" />
          <span style="font-size:0.72rem;color:#94a3b8;">${f.description || ''}</span>
        </div>
      `).join("");
    }

    async function loadPolicyThresholds() {
      const res = await fetch(`/api/session/${sessionId}/policy-thresholds`);
      const data = await res.json();
      renderPolicyFields(data);
    }

    document.getElementById("togglePolicy").onclick = () => {
      document.getElementById("policyPanel").classList.toggle("open");
      loadPolicyThresholds();
    };

    document.getElementById("savePolicyBtn").onclick = async () => {
      const body = {};
      document.querySelectorAll("#policyFields input[data-key]").forEach(inp => {
        const key = inp.getAttribute("data-key");
        body[key] = inp.step === "1" ? parseInt(inp.value, 10) : parseFloat(inp.value);
      });
      const res = await fetch(`/api/session/${sessionId}/policy-thresholds`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) return toast(data.detail || "Save failed");
      toast(data.message || "Thresholds saved");
      renderPolicyFields(data);
    };

    document.getElementById("resetPolicyBtn").onclick = async () => {
      const schema = await (await fetch("/api/policy-thresholds/schema")).json();
      const body = {};
      (schema.fields || []).forEach(f => { body[f.key] = f.default; });
      const res = await fetch(`/api/session/${sessionId}/policy-thresholds`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) return toast("Reset failed");
      toast("Reset to default thresholds");
      renderPolicyFields(data);
    };

    document.getElementById("toggleTools").onclick = () => {
      document.getElementById("toolsPanel").classList.toggle("open");
    };

    document.getElementById("loadSampleBtn").onclick = async () => {
      const res = await fetch(`/api/session/${sessionId}/load-sample`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return toast(data.detail || "Failed");
      toast("Loaded " + data.imported + " demo expenses");
      refreshDashboard();
    };

    document.getElementById("analyzeBtn").onclick = async () => {
      toast("Running compliance agents...");
      const res = await fetch(`/api/session/${sessionId}/analyze`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) return toast(data.detail || "Analysis failed");
      toast("Compliance complete");
      renderDashboard(await (await fetch(`/api/session/${sessionId}/dashboard`)).json());
    };

    document.getElementById("scanBtn").onclick = async () => {
      const file = document.getElementById("receiptFile").files[0];
      if (!file) return toast("Choose a receipt");
      const fd = new FormData();
      fd.append("receipt", file);
      const emp = document.getElementById("employeeId").value.trim();
      if (emp) fd.append("employee_id", emp);
      const res = await fetch(`/api/session/${sessionId}/scan-receipt`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) return toast(data.detail || "Scan failed");
      toast("Added " + data.entry.expense_id);
      refreshDashboard();
    };

    document.getElementById("importCsvBtn").onclick = async () => {
      const file = document.getElementById("csvFile").files[0];
      if (!file) return toast("Choose CSV");
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/session/${sessionId}/import-csv`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) return toast(data.detail || "Import failed");
      toast("Imported " + data.imported + " rows");
      refreshDashboard();
    };

    refreshDashboard();
  </script>
</body>
</html>
"""
