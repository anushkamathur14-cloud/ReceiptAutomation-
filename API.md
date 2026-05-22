# API reference (for Lovable / external frontend)

Base URL: your Railway domain, e.g. `https://receiptautomation-production-xxxx.up.railway.app`

Interactive docs: `{BASE_URL}/docs`

## Health

```
GET /health
```

Response:
```json
{
  "status": "ok",
  "llm_configured": true,
  "llm_model": "gpt-4o-mini",
  "agents": ["ReceiptAnalysisAgent (LLM)", "..."]
}
```

## Session model

Generate a `session_id` on the client (e.g. `crypto.randomUUID()`) and send it on every request. Entries are stored per session.

---

## Upload limit

Each user session is limited to **2 file uploads** (receipt scan or CSV import combined).

- `POST /api/session/{id}/scan-receipt` — counts as 1 upload
- `POST /api/session/{id}/import-csv` — counts as 1 upload
- `POST /api/session/{id}/load-sample` — does **not** count (demo only)

When limit is reached, API returns **429** with a clear error message.  
`GET /api/session/{id}/dashboard` includes `upload_quota`: `{ "limit": 2, "used": 1, "remaining": 1 }`.

Override via env: `MAX_UPLOADS_PER_SESSION=2`

---

## Receipt scan (LLM agent)

```
POST /api/session/{session_id}/scan-receipt
Content-Type: multipart/form-data
```

| Field | Type | Required |
|-------|------|----------|
| `receipt` | file | yes (PNG, JPG, PDF, WEBP, GIF, BMP) |
| `employee_id` | string | no |

Response:
```json
{
  "entry": {
    "expense_id": "EXP-001",
    "employee_id": "E-1001",
    "category": "Meals",
    "amount": 18.75,
    "currency": "USD",
    "expense_date": "2026-04-01",
    "submission_date": "2026-05-07",
    "receipt_provided": "yes",
    "manager_approval": "no",
    "vendor": "Starbucks",
    "analysis_method": "llm_agent",
    "agent_reasoning": "..."
  },
  "analysis_method": "llm_agent",
  "raw_text_preview": "..."
}
```

---

## Policy approval thresholds (Lovable)

Managers can change the dollar/day limits used by the **Decide Agent** before running compliance.

### Get form schema (labels, min, max, defaults)

```
GET /api/policy-thresholds/schema
```

### Get current thresholds for session

```
GET /api/session/{session_id}/policy-thresholds
```

Response:
```json
{
  "thresholds": {
    "meal_limit": 75,
    "hotel_limit": 250,
    "software_limit": 300,
    "gift_limit": 50,
    "late_submission_days": 30,
    "receipt_required_over": 25
  },
  "fields": [
    {
      "key": "meal_limit",
      "label": "Meals — daily limit ($)",
      "description": "Over this amount requires manager approval.",
      "type": "currency",
      "min": 0,
      "max": 10000,
      "default": 75,
      "value": 75
    }
  ]
}
```

### Update thresholds (partial or full)

```
PUT /api/session/{session_id}/policy-thresholds
Content-Type: application/json
```

Body (send only fields to change):

```json
{
  "meal_limit": 100,
  "hotel_limit": 300,
  "receipt_required_over": 50
}
```

Also supported: `PATCH` with the same body.

After saving, call `POST /api/session/{id}/analyze` again so decisions use the new thresholds.

`GET /api/session/{id}/dashboard` includes `policy_thresholds` with the same shape.

### Lovable example

```javascript
const API = "https://YOUR-RAILWAY-URL";
const sessionId = localStorage.getItem("sessionId");

// Build form from schema
const schema = await fetch(`${API}/api/policy-thresholds/schema`).then(r => r.json());

// Save user edits
await fetch(`${API}/api/session/${sessionId}/policy-thresholds`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    meal_limit: 100,
    hotel_limit: 275,
  }),
});

// Re-run compliance with new rules
await fetch(`${API}/api/session/${sessionId}/analyze`, { method: "POST" });
```

| Field | Meaning |
|-------|---------|
| `meal_limit` | Meals over $ → needs review |
| `hotel_limit` | Hotels over $/night → needs review |
| `software_limit` | Software over $ → needs pre-approval |
| `gift_limit` | Gifts over $ → needs review |
| `late_submission_days` | Days after expense date → late |
| `receipt_required_over` | Amount above which receipt is required |

---

## Manager dashboard (Lovable / JSON)

```
GET /api/session/{session_id}/dashboard
```

Returns KPIs, decision breakdown, spend by category, manager action items, priority exceptions, and full entries — same data as the `/` manager UI.

---

## List entries (table data)

```
GET /api/session/{session_id}/entries
```

Response:
```json
{
  "session_id": "abc123",
  "entries": [ { "expense_id": "...", "decision": "Approved", ... } ],
  "excel_url": "/api/runs/{run_id}/expense_details.xlsx"
}
```

---

## Import CSV

```
POST /api/session/{session_id}/import-csv
Content-Type: multipart/form-data
```

| Field | Type |
|-------|------|
| `file` | CSV file |

---

## Load sample data

```
POST /api/session/{session_id}/load-sample
```

---

## Run compliance (all agents)

```
POST /api/session/{session_id}/analyze
```

Response:
```json
{
  "run_id": "a1b2c3d4",
  "summary": { "total_expenses": 10, "decision_counts": { ... } },
  "excel_url": "/api/runs/a1b2c3d4/expense_details.xlsx",
  "entries": [ ... ]
}
```

---

## Download Excel

```
GET /api/runs/{run_id}/expense_details.xlsx
```

Or after analyze, use `excel_url` from the analyze response (prepend base URL).

Sheets: **Expense Details**, **Compliance Decisions**, **Summary**

---

## Clear session

```
DELETE /api/session/{session_id}/entries
```

---

## Lovable example (fetch)

```javascript
const API = "https://YOUR-RAILWAY-URL.up.railway.app";
const sessionId = localStorage.getItem("sessionId") ?? crypto.randomUUID();

// Scan receipt
const form = new FormData();
form.append("receipt", file);
form.append("employee_id", "E-1001");
const res = await fetch(`${API}/api/session/${sessionId}/scan-receipt`, {
  method: "POST",
  body: form,
});
const data = await res.json();

// Run compliance
await fetch(`${API}/api/session/${sessionId}/analyze`, { method: "POST" });

// Download Excel
window.open(`${API}${data.excel_url}`, "_blank");
```

## Railway variables (backend)

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM receipt + explain agents |
| `LLM_MODEL` | e.g. `gpt-4o-mini` |
| `USE_LLM_VISION` | `true` for image receipts |
| `CORS_ORIGINS` | Lovable URL, e.g. `https://your-app.lovable.app,https://localhost:5173` |
