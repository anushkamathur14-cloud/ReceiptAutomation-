from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .main import run_pipeline

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_EXPENSES = ROOT / "data" / "sample_expenses.csv"
SAMPLE_POLICY = ROOT / "data" / "sample_policy.txt"
DEFAULT_POLICY_PDF = ROOT / "Expense-Receipt-Compliance-Bot.pdf"

app = FastAPI(
    title="Expense Receipt Compliance Bot",
    description="Five-agent expense compliance pipeline",
    version="1.0.0",
)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
    <html>
      <head>
        <title>Receipt Automation</title>
        <style>
          body { font-family: system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; }
          .ok { background: #e8f5e9; border: 1px solid #4caf50; padding: 1rem; border-radius: 8px; }
          a { color: #1565c0; }
          code { background: #f5f5f5; padding: 2px 6px; border-radius: 4px; }
          li { margin: 0.5rem 0; }
        </style>
      </head>
      <body>
        <div class="ok"><strong>Deployed and running.</strong> You are viewing the live app.</div>
        <h1>Expense Receipt Compliance Bot</h1>
        <p>Try these links on this same URL (your Railway domain):</p>
        <ul>
          <li><a href="/health">/health</a> — should show <code>{"status":"ok"}</code></li>
          <li><a href="/api/sample-run">/api/sample-run</a> — run demo and get results</li>
          <li><a href="/docs">/docs</a> — upload your CSV + policy</li>
        </ul>
        <p><strong>Not seeing this on Railway?</strong> Open your service → <strong>Settings</strong> →
        <strong>Networking</strong> → <strong>Generate Domain</strong>, then open that public URL.</p>
      </body>
    </html>
    """


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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
        }
        _register_run(run_id, output_dir)
        return result
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_RUNS: dict[str, Path] = {}


def _register_run(run_id: str, output_dir: Path) -> None:
    _RUNS[run_id] = output_dir


@app.get("/api/runs/{run_id}/{filename}")
def download_run_file(run_id: str, filename: str) -> FileResponse:
    output_dir = _RUNS.get(run_id)
    if output_dir is None:
        raise HTTPException(status_code=404, detail="Run not found or expired.")

    allowed = {"decisions.csv", "summary.json", "manager_report.pdf"}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Unknown file.")

    path = output_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    media = "application/pdf" if filename.endswith(".pdf") else "text/csv"
    if filename.endswith(".json"):
        media = "application/json"
    return FileResponse(path, media_type=media, filename=filename)


@app.get("/api/sample-run")
def sample_run() -> dict:
    policy_path = SAMPLE_POLICY if SAMPLE_POLICY.exists() else DEFAULT_POLICY_PDF
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
    }
    _register_run(run_id, output_dir)
    return result
