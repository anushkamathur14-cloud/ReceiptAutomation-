from __future__ import annotations

import io
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from .main import run_pipeline
from .manager_dashboard import MANAGER_DASHBOARD_HTML, build_dashboard_payload
from .receipt_scanner import scan_receipt_file
from .session_store import (
    add_entry,
    entries_dataframe,
    ensure_upload_allowed,
    get_session,
    import_csv_entries,
    record_upload,
    set_results,
    upload_quota,
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

_cors_origins = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return MANAGER_DASHBOARD_HTML


@app.get("/dashboard", response_class=HTMLResponse)
def manager_dashboard_page() -> str:
    return MANAGER_DASHBOARD_HTML


@app.get("/health")
def health() -> dict:
    from .llm_client import is_llm_configured, default_model

    return {
        "status": "ok",
        "llm_configured": is_llm_configured(),
        "llm_model": default_model() if is_llm_configured() else None,
        "agents": [
            "ReceiptAnalysisAgent (LLM)",
            "ValidateAgent",
            "RetrievePolicyAgent",
            "DecideAgent",
            "ExplainAgent (LLM when configured)",
            "SummarizeAgent",
        ],
    }


def _session_excel_url(session_id: str) -> Optional[str]:
    session = get_session(session_id)
    if session.last_run_id and session.last_run_id in _RUNS:
        xlsx = _RUNS[session.last_run_id] / "expense_details.xlsx"
        if xlsx.exists():
            return f"/api/runs/{session.last_run_id}/expense_details.xlsx"
    return None


@app.get("/api/session/{session_id}/dashboard")
def session_dashboard(session_id: str) -> dict:
    session = get_session(session_id)
    df = session.results_df if session.results_df is not None else entries_dataframe(session)
    payload = build_dashboard_payload(
        df,
        summary=session.last_summary,
        excel_url=_session_excel_url(session_id),
    )
    payload["upload_quota"] = upload_quota(session_id)
    return payload


@app.get("/api/session/{session_id}/entries")
def list_entries(session_id: str) -> dict:
    session = get_session(session_id)
    df = session.results_df if session.results_df is not None else entries_dataframe(session)
    entries = df.to_dict(orient="records") if not df.empty else []
    return {
        "session_id": session_id,
        "entries": entries,
        "excel_url": _session_excel_url(session_id),
    }


@app.delete("/api/session/{session_id}/entries")
def clear_entries(session_id: str) -> dict:
    session = get_session(session_id)
    session.entries.clear()
    session.results_df = None
    session.last_run_id = None
    session.last_summary = None
    session.upload_count = 0
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

    try:
        ensure_upload_allowed(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    work_dir = Path(tempfile.mkdtemp(prefix="receipt_"))
    receipt_path = work_dir / Path(receipt.filename).name
    try:
        receipt_path.write_bytes(await receipt.read())
        scanned = scan_receipt_file(receipt_path, employee_id=employee_id)
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
            "analysis_method": scanned.get("analysis_method", ""),
            "agent_reasoning": scanned.get("agent_reasoning", ""),
        }
        saved = add_entry(session_id, entry)
        quota = record_upload(session_id)
        return {
            "entry": saved,
            "raw_text_preview": scanned.get("raw_text", "")[:500],
            "analysis_method": scanned.get("analysis_method"),
            "upload_quota": quota,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/api/session/{session_id}/import-csv")
async def import_csv(session_id: str, file: UploadFile = File(...)) -> dict:
    try:
        ensure_upload_allowed(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
        count = import_csv_entries(session_id, df)
        quota = record_upload(session_id)
        return {"imported": count, "upload_quota": quota}
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
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
        set_results(session_id, run_id, merged, summary=result["summary"])
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
