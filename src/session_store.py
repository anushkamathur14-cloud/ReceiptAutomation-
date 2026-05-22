from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


def max_uploads_per_session() -> int:
    return int(os.getenv("MAX_UPLOADS_PER_SESSION", "2"))


@dataclass
class SessionData:
    entries: List[dict] = field(default_factory=list)
    last_run_id: Optional[str] = None
    results_df: Optional[pd.DataFrame] = None
    last_summary: Optional[dict] = None
    upload_count: int = 0


_SESSIONS: Dict[str, SessionData] = {}


def get_session(session_id: str) -> SessionData:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = SessionData()
    return _SESSIONS[session_id]


def upload_quota(session_id: str) -> Dict[str, int]:
    session = get_session(session_id)
    limit = max_uploads_per_session()
    used = session.upload_count
    return {"limit": limit, "used": used, "remaining": max(0, limit - used)}


def ensure_upload_allowed(session_id: str) -> None:
    if upload_quota(session_id)["remaining"] <= 0:
        limit = max_uploads_per_session()
        raise ValueError(
            f"Upload limit reached. Each user may upload at most {limit} file(s) "
            f"(receipt or CSV). Demo sample data does not count toward this limit."
        )


def record_upload(session_id: str) -> Dict[str, int]:
    session = get_session(session_id)
    session.upload_count += 1
    return upload_quota(session_id)


def next_expense_id(session: SessionData, prefix: str = "EXP") -> str:
    existing = [e.get("expense_id", "") for e in session.entries]
    nums = []
    for eid in existing:
        if eid.startswith(prefix + "-"):
            tail = eid.split("-", 1)[-1]
            if tail.isdigit():
                nums.append(int(tail))
    n = max(nums, default=0) + 1
    return f"{prefix}-{n:03d}"


def add_entry(session_id: str, entry: dict) -> dict:
    session = get_session(session_id)
    if "expense_id" not in entry or not entry["expense_id"]:
        entry["expense_id"] = next_expense_id(session)
    session.entries.append(entry)
    return entry


def import_csv_entries(session_id: str, df: pd.DataFrame) -> int:
    session = get_session(session_id)
    count = 0
    for _, row in df.iterrows():
        entry = {k: ("" if pd.isna(v) else v) for k, v in row.items()}
        entry["expense_id"] = str(entry.get("expense_id") or next_expense_id(session))
        session.entries.append(entry)
        count += 1
    return count


def entries_dataframe(session: SessionData) -> pd.DataFrame:
    if not session.entries:
        return pd.DataFrame()
    return pd.DataFrame(session.entries)


def set_results(
    session_id: str, run_id: str, df: pd.DataFrame, summary: Optional[dict] = None
) -> None:
    session = get_session(session_id)
    session.last_run_id = run_id
    session.results_df = df
    if summary is not None:
        session.last_summary = summary
