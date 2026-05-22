from __future__ import annotations

import io
import shutil
import tempfile
import uuid
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .excel_export import write_expense_workbook
from .main import run_pipeline
from .receipt_scanner import scan_receipt_file
from .session_store import (
    add_entry,
    entries_dataframe,
    get_session,
    import_csv_entries,
    set_results,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_EXPENSES = ROOT / "data" / "sample_expenses.csv"
SAMPLE_POLICY = ROOT / "data" / "sample_policy.txt"
DEFAULT_POLICY_PDF = ROOT / "Expense-Receipt-Compliance-Bot.pdf"

app = FastAPI(
    title="Expense Receipt Compliance Bot",
    description="Upload receipts, scan, review entries, export Excel",
    version="2.0.0",
)

_RUNS: dict[str, Path] = {}
_SESSION_RUNS: dict[str, str] = {}


def _register_run(run_id: str, output_dir: Path) -> None:
    _RUNS[run_id] = output_dir


def _default_policy_path() -> Path:
    return SAMPLE_POLICY if SAMPLE_POLICY.exists() else DEFAULT_POLICY_PDF


def _entries_to_csv(df: pd.DataFrame, path: Path) -> None:
    cols = [
        "expense_id",
        "employee_id",
        "category",
        "amount",
        "currency",
        "expense_date",
        "submission_date",
        "receipt_provided",
        "manager_approval",
        "pre_approval",
        "flight_class",
        "notes",
    ]
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = ""
    out[cols].to_csv(path, index=False)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Receipt Automation</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; margin: 0; background: #f4f6f8; color: #1a1a1a; }
    header { background: #0d47a1; color: #fff; padding: 1.25rem 2rem; }
    main { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
    .card { background: #fff; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.25rem; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    h2 { margin-top: 0; font-size: 1.1rem; }
    .row { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end; }
    label { display: block; font-size: 0.85rem; margin-bottom: 0.35rem; color: #444; }
    input, select, button { font: inherit; padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid #ccc; }
    button { background: #1565c0; color: #fff; border: none; cursor: pointer; }
    button:hover { background: #0d47a1; }
    button.secondary { background: #546e7a; }
    button.success { background: #2e7d32; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { border-bottom: 1px solid #e0e0e0; padding: 0.55rem 0.5rem; text-align: left; }
    th { background: #eceff1; position: sticky; top: 0; }
    .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
    .Approved { background: #e8f5e9; color: #2e7d32; }
    .Rejected { background: #ffebee; color: #c62828; }
    .Needs-Review { background: #fff8e1; color: #f57f17; }
    .Missing-Info { background: #e3f2fd; color: #1565c0; }
    #status { margin-top: 0.75rem; font-size: 0.9rem; color: #333; }
    .scan-preview { background: #f5f5f5; padding: 0.75rem; border-radius: 6px; font-size: 0.85rem; white-space: pre-wrap; max-height: 120px; overflow: auto; }
    .actions { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 1rem; }
    .empty { color: #777; padding: 1rem 0; }
  </style>
</head>
<body>
  <header>
    <h1>Expense Receipt Compliance Bot</h1>
    <p>Upload receipts to scan, review all entries, run compliance, download Excel.</p>
  </header>
  <main>
    <div class="card">
      <h2>1. Upload &amp; scan receipt</h2>
      <div class="row">
        <div>
          <label>Receipt image or PDF</label>
          <input type="file" id="receiptFile" accept=".png,.jpg,.jpeg,.webp,.pdf,.gif,.bmp" />
        </div>
        <div>
          <label>Employee ID (optional)</label>
          <input type="text" id="employeeId" placeholder="E-1001" />
        </div>
        <button type="button" id="scanBtn">Scan receipt</button>
      </div>
      <div id="scanPreview" class="scan-preview" style="display:none;margin-top:0.75rem;"></div>
      <div id="status"></div>
    </div>

    <div class="card">
      <h2>2. Or import expense CSV</h2>
      <div class="row">
        <input type="file" id="csvFile" accept=".csv" />
        <button type="button" class="secondary" id="importCsvBtn">Import CSV</button>
        <button type="button" class="secondary" id="loadSampleBtn">Load sample data</button>
      </div>
    </div>

    <div class="card">
      <h2>3. All expense entries</h2>
      <div class="actions">
        <button type="button" id="analyzeBtn" class="success">Run compliance check</button>
        <a id="excelLink" href="#" style="display:none;"><button type="button" class="secondary">Download Excel</button></a>
        <button type="button" class="secondary" id="clearBtn">Clear all entries</button>
      </div>
      <div style="overflow-x:auto;margin-top:1rem;">
        <table id="entriesTable">
          <thead>
            <tr>
              <th>ID</th><th>Employee</th><th>Category</th><th>Amount</th><th>Date</th>
              <th>Receipt</th><th>Decision</th><th>Risk</th><th>Reason</th><th>Notes</th>
            </tr>
          </thead>
          <tbody id="entriesBody">
            <tr><td colspan="10" class="empty">No entries yet. Scan a receipt or import CSV.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>
  <script>
    const SESSION_KEY = "receipt_session_id";
    let sessionId = localStorage.getItem(SESSION_KEY);
    if (!sessionId) {
      sessionId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
      localStorage.setItem(SESSION_KEY, sessionId);
    }

    const statusEl = document.getElementById("status");
    const tbody = document.getElementById("entriesBody");
    const excelLink = document.getElementById("excelLink");

    function setStatus(msg, isError) {
      statusEl.textContent = msg;
      statusEl.style.color = isError ? "#c62828" : "#333";
    }

    function decisionClass(d) {
      return (d || "").replace(/\\s+/g, "-");
    }

    async function refreshTable() {
      const res = await fetch(`/api/session/${sessionId}/entries`);
      const data = await res.json();
      if (!data.entries || data.entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty">No entries yet. Scan a receipt or import CSV.</td></tr>';
        excelLink.style.display = "none";
        return;
      }
      tbody.innerHTML = data.entries.map(e => `
        <tr>
          <td>${e.expense_id || ""}</td>
          <td>${e.employee_id || ""}</td>
          <td>${e.category || ""}</td>
          <td>${e.currency || "USD"} ${Number(e.amount || 0).toFixed(2)}</td>
          <td>${e.expense_date || ""}</td>
          <td>${e.receipt_provided || ""}</td>
          <td>${e.decision ? `<span class="badge ${decisionClass(e.decision)}">${e.decision}</span>` : "—"}</td>
          <td>${e.risk_score ?? "—"}</td>
          <td>${e.reason_text || e.reason_code || "—"}</td>
          <td>${(e.notes || "").slice(0, 60)}</td>
        </tr>
      `).join("");
      if (data.excel_url) {
        excelLink.href = data.excel_url;
        excelLink.style.display = "inline-block";
      }
    }

    document.getElementById("scanBtn").onclick = async () => {
      const file = document.getElementById("receiptFile").files[0];
      if (!file) { setStatus("Choose a receipt file first.", true); return; }
      const fd = new FormData();
      fd.append("receipt", file);
      const emp = document.getElementById("employeeId").value.trim();
      if (emp) fd.append("employee_id", emp);
      setStatus("Scanning receipt...");
      const res = await fetch(`/api/session/${sessionId}/scan-receipt`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) { setStatus(data.detail || "Scan failed", true); return; }
      document.getElementById("scanPreview").style.display = "block";
      document.getElementById("scanPreview").textContent =
        "Vendor: " + (data.entry.vendor || "—") + "\\nAmount: $" + data.entry.amount +
        "\\nCategory: " + data.entry.category + "\\nConfidence: " + data.entry.scan_confidence;
      setStatus("Receipt scanned and added as " + data.entry.expense_id);
      refreshTable();
    };

    document.getElementById("importCsvBtn").onclick = async () => {
      const file = document.getElementById("csvFile").files[0];
      if (!file) { setStatus("Choose a CSV file.", true); return; }
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`/api/session/${sessionId}/import-csv`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) { setStatus(data.detail || "Import failed", true); return; }
      setStatus("Imported " + data.imported + " rows.");
      refreshTable();
    };

    document.getElementById("loadSampleBtn").onclick = async () => {
      const res = await fetch(`/api/session/${sessionId}/load-sample`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) { setStatus(data.detail || "Failed", true); return; }
      setStatus("Loaded " + data.imported + " sample entries.");
      refreshTable();
    };

    document.getElementById("analyzeBtn").onclick = async () => {
      setStatus("Running compliance check...");
      const res = await fetch(`/api/session/${sessionId}/analyze`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) { setStatus(data.detail || "Analysis failed", true); return; }
      setStatus("Done. Approved: " + (data.summary?.decision_counts?.Approved || 0) +
        ", Needs Review: " + (data.summary?.decision_counts?.["Needs Review"] || 0));
      if (data.excel_url) {
        excelLink.href = data.excel_url;
        excelLink.style.display = "inline-block";
      }
      refreshTable();
    };

    document.getElementById("clearBtn").onclick = async () => {
      if (!confirm("Clear all entries?")) return;
      await fetch(`/api/session/${sessionId}/entries`, { method: "DELETE" });
      setStatus("Cleared.");
      refreshTable();
    };

    refreshTable();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return DASHBOARD_HTML


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/session/{session_id}/entries")
def list_entries(session_id: str) -> dict:
    session = get_session(session_id)
    df = session.results_df if session.results_df is not None else entries_dataframe(session)
    entries = df.to_dict(orient="records") if not df.empty else []
    excel_url = None
    if session.last_run_id and session.last_run_id in _RUNS:
        xlsx = _RUNS[session.last_run_id] / "expense_details.xlsx"
        if xlsx.exists():
            excel_url = f"/api/runs/{session.last_run_id}/expense_details.xlsx"
    return {"session_id": session_id, "entries": entries, "excel_url": excel_url}


@app.delete("/api/session/{session_id}/entries")
def clear_entries(session_id: str) -> dict:
    session = get_session(session_id)
    session.entries.clear()
    session.results_df = None
    session.last_run_id = None
    return {"cleared": True}


@app.post("/api/session/{session_id}/scan-receipt")
async def scan_receipt(
    session_id: str,
    receipt: UploadFile = File(...),
    employee_id: str = Form(default=""),
) -> dict:
    if not receipt.filename:
        raise HTTPException(status_code=400, detail="Receipt file required.")

    allowed = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".gif", ".bmp", ".tiff"}
    ext = Path(receipt.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Supported: PNG, JPG, PDF, WEBP, GIF, BMP.")

    work_dir = Path(tempfile.mkdtemp(prefix="receipt_"))
    receipt_path = work_dir / Path(receipt.filename).name
    try:
        receipt_path.write_bytes(await receipt.read())
        scanned = scan_receipt_file(receipt_path)
        entry = {
            "expense_id": "",
            "employee_id": employee_id or scanned.get("employee_id", "E-SCAN"),
            "category": scanned["category"],
            "amount": scanned["amount"],
            "currency": scanned["currency"],
            "expense_date": scanned["expense_date"],
            "submission_date": scanned["submission_date"],
            "receipt_provided": scanned["receipt_provided"],
            "manager_approval": scanned["manager_approval"],
            "pre_approval": scanned["pre_approval"],
            "flight_class": scanned.get("flight_class", ""),
            "notes": scanned["notes"],
            "vendor": scanned.get("vendor", ""),
            "receipt_filename": scanned.get("receipt_filename", ""),
            "scan_confidence": scanned.get("scan_confidence", ""),
        }
        saved = add_entry(session_id, entry)
        return {"entry": saved, "raw_text_preview": scanned.get("raw_text", "")[:500]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/api/session/{session_id}/import-csv")
async def import_csv(session_id: str, file: UploadFile = File(...)) -> dict:
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        count = import_csv_entries(session_id, df)
        return {"imported": count}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}") from exc


@app.post("/api/session/{session_id}/load-sample")
def load_sample(session_id: str) -> dict:
    if not SAMPLE_EXPENSES.exists():
        raise HTTPException(status_code=500, detail="Sample file missing.")
    df = pd.read_csv(SAMPLE_EXPENSES)
    count = import_csv_entries(session_id, df)
    return {"imported": count}


@app.post("/api/session/{session_id}/analyze")
def analyze_session(session_id: str) -> dict:
    session = get_session(session_id)
    if not session.entries:
        raise HTTPException(status_code=400, detail="Add entries first (scan receipt or import CSV).")

    run_id = uuid.uuid4().hex[:8]
    work_dir = Path(tempfile.mkdtemp(prefix=f"analyze_{run_id}_"))
    output_dir = work_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    expenses_df = entries_dataframe(session)
    expenses_path = work_dir / "expenses.csv"
    _entries_to_csv(expenses_df, expenses_path)

    try:
        result = run_pipeline(expenses_path, _default_policy_path(), output_dir)
        decisions_df = pd.read_csv(output_dir / "decisions.csv")
        merged = expenses_df.merge(decisions_df, on="expense_id", how="left")
        set_results(session_id, run_id, merged)
        _register_run(run_id, output_dir)
        _SESSION_RUNS[session_id] = run_id

        excel_url = f"/api/runs/{run_id}/expense_details.xlsx"
        return {
            "run_id": run_id,
            "summary": result["summary"],
            "excel_url": excel_url,
            "entries": merged.to_dict(orient="records"),
        }
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/{filename}")
def download_run_file(run_id: str, filename: str) -> FileResponse:
    output_dir = _RUNS.get(run_id)
    if output_dir is None:
        raise HTTPException(status_code=404, detail="Run not found or expired.")

    allowed = {
        "decisions.csv",
        "summary.json",
        "manager_report.pdf",
        "expense_details.xlsx",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Unknown file.")

    path = output_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    media_map = {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    media = media_map.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=filename)


@app.get("/api/session/{session_id}/download/excel")
def download_session_excel(session_id: str) -> FileResponse:
    run_id = _SESSION_RUNS.get(session_id)
    if not run_id or run_id not in _RUNS:
        raise HTTPException(status_code=404, detail="Run Excel file not found. Run compliance first.")

    path = _RUNS[run_id] / "expense_details.xlsx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Excel file not found.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="expense_details.xlsx",
    )


@app.post("/api/run")
async def run_compliance(
    expenses: UploadFile = File(...),
    policy: UploadFile = File(...),
) -> dict:
    if not expenses.filename or not expenses.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Expenses file must be a CSV.")
    if not policy.filename:
        raise HTTPException(status_code=400, detail="Policy file is required.")

    run_id = uuid.uuid4().hex[:8]
    work_dir = Path(tempfile.mkdtemp(prefix=f"run_{run_id}_"))
    output_dir = work_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    expenses_path = work_dir / "expenses.csv"
    policy_path = work_dir / Path(policy.filename).name

    try:
        expenses_path.write_bytes(await expenses.read())
        policy_path.write_bytes(await policy.read())
        result = run_pipeline(expenses_path, policy_path, output_dir)
        result["run_id"] = run_id
        result["download_urls"] = {
            "decisions_csv": f"/api/runs/{run_id}/decisions.csv",
            "summary_json": f"/api/runs/{run_id}/summary.json",
            "manager_report_pdf": f"/api/runs/{run_id}/manager_report.pdf",
            "expense_details_xlsx": f"/api/runs/{run_id}/expense_details.xlsx",
        }
        _register_run(run_id, output_dir)
        return result
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/sample-run")
def sample_run() -> dict:
    policy_path = _default_policy_path()
    if not SAMPLE_EXPENSES.exists() or not policy_path.exists():
        raise HTTPException(status_code=500, detail="Sample data files are missing.")

    run_id = uuid.uuid4().hex[:8]
    output_dir = Path(tempfile.mkdtemp(prefix=f"sample_{run_id}_")) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(SAMPLE_EXPENSES, policy_path, output_dir)
    result["run_id"] = run_id
    result["download_urls"] = {
        "decisions_csv": f"/api/runs/{run_id}/decisions.csv",
        "summary_json": f"/api/runs/{run_id}/summary.json",
        "manager_report_pdf": f"/api/runs/{run_id}/manager_report.pdf",
        "expense_details_xlsx": f"/api/runs/{run_id}/expense_details.xlsx",
    }
    _register_run(run_id, output_dir)
    return result
