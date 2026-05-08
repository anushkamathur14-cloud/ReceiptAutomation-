from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from pypdf import PdfReader

from .models import Decision, DecisionResult, ExpenseRow
from .policy_rules import PolicyConfig, default_policy_config, rule_catalog


class ValidateAgent:
    REQUIRED_COLUMNS = {
        "expense_id",
        "employee_id",
        "category",
        "amount",
        "currency",
        "expense_date",
        "submission_date",
        "receipt_provided",
        "manager_approval",
    }

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y"}

    def run(self, expenses_df: pd.DataFrame) -> Tuple[List[ExpenseRow], List[DecisionResult]]:
        missing = self.REQUIRED_COLUMNS - set(expenses_df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        rows: List[ExpenseRow] = []
        validation_errors: List[DecisionResult] = []

        for _, row in expenses_df.iterrows():
            try:
                expense = ExpenseRow(
                    expense_id=str(row["expense_id"]),
                    employee_id=str(row["employee_id"]),
                    category=str(row["category"]).strip(),
                    amount=float(row["amount"]),
                    currency=str(row["currency"]).strip(),
                    expense_date=str(row["expense_date"]).strip(),
                    submission_date=str(row["submission_date"]).strip(),
                    receipt_provided=self._to_bool(row["receipt_provided"]),
                    manager_approval=self._to_bool(row["manager_approval"]),
                    pre_approval=self._to_bool(row.get("pre_approval", False)),
                    flight_class=str(row.get("flight_class", "")).strip() or None,
                    notes=str(row.get("notes", "")).strip() or None,
                )
                rows.append(expense)
            except Exception:
                validation_errors.append(
                    DecisionResult(
                        expense_id=str(row.get("expense_id", "UNKNOWN")),
                        decision=Decision.MISSING_INFO,
                        risk_score=90,
                        reason_code="VALIDATION_ERROR",
                        reason_text="Row contains invalid or missing required fields.",
                    )
                )

        return rows, validation_errors


class RetrievePolicyAgent:
    def run(self, policy_path: Path) -> Dict[str, str]:
        ext = policy_path.suffix.lower()
        if ext == ".pdf":
            text = self._read_pdf(policy_path)
        elif ext in {".txt", ".md"}:
            text = policy_path.read_text(encoding="utf-8", errors="ignore")
        elif ext == ".docx":
            # Fallback for no python-docx dependency in baseline.
            text = policy_path.read_bytes().decode("utf-8", errors="ignore")
        else:
            text = ""

        return {"raw_text": text, "rules": rule_catalog()}

    @staticmethod
    def _read_pdf(path: Path) -> str:
        reader = PdfReader(str(path))
        chunks: List[str] = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks)


class DecideAgent:
    def __init__(self, policy: PolicyConfig | None = None):
        self.policy = policy or default_policy_config()

    @staticmethod
    def _days_between(start_date: str, end_date: str) -> int:
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()
        return (end - start).days

    def _evaluate(self, e: ExpenseRow) -> Tuple[Decision, int, str]:
        cat = e.category.lower().strip()

        if e.amount > self.policy.receipt_required_over and not e.receipt_provided:
            return Decision.MISSING_INFO, 85, "MISSING_RECEIPT_OVER_THRESHOLD"

        if cat == "rideshare" and not e.receipt_provided:
            return Decision.MISSING_INFO, 80, "RIDESHARE_RECEIPT_REQUIRED"

        if cat == "meals" and e.amount > self.policy.meal_limit and not e.manager_approval:
            return Decision.NEEDS_REVIEW, 65, "MEAL_OVER_LIMIT"

        if cat == "hotels" and e.amount > self.policy.hotel_limit and not e.manager_approval:
            return Decision.NEEDS_REVIEW, 68, "HOTEL_OVER_LIMIT"

        if cat == "flights":
            flight_class = (e.flight_class or "").lower()
            if flight_class and flight_class != "economy" and not e.manager_approval:
                return Decision.REJECTED, 88, "FLIGHT_CLASS_RESTRICTED"

        if cat == "software" and e.amount > self.policy.software_limit and not e.pre_approval:
            return Decision.NEEDS_REVIEW, 70, "SOFTWARE_PREAPPROVAL_REQUIRED"

        if cat == "alcohol" and not e.manager_approval:
            return Decision.REJECTED, 92, "ALCOHOL_NON_REIMBURSABLE"

        if cat == "gifts" and e.amount > self.policy.gift_limit and not e.manager_approval:
            return Decision.NEEDS_REVIEW, 64, "GIFT_OVER_LIMIT"

        try:
            if self._days_between(e.expense_date, e.submission_date) > self.policy.late_submission_days:
                return Decision.NEEDS_REVIEW, 72, "LATE_SUBMISSION"
        except ValueError:
            return Decision.MISSING_INFO, 80, "VALIDATION_ERROR"

        return Decision.APPROVED, 15, "OK"

    def run(self, expenses: List[ExpenseRow]) -> List[DecisionResult]:
        results: List[DecisionResult] = []
        for e in expenses:
            decision, risk_score, reason_code = self._evaluate(e)
            results.append(
                DecisionResult(
                    expense_id=e.expense_id,
                    decision=decision,
                    risk_score=risk_score,
                    reason_code=reason_code,
                    reason_text="",
                )
            )
        return results


class ExplainAgent:
    def run(self, decisions: List[DecisionResult], rules: Dict[str, str]) -> List[DecisionResult]:
        enriched: List[DecisionResult] = []
        for d in decisions:
            text = rules.get(d.reason_code, "Policy evaluation result generated.")
            enriched.append(
                DecisionResult(
                    expense_id=d.expense_id,
                    decision=d.decision,
                    risk_score=d.risk_score,
                    reason_code=d.reason_code,
                    reason_text=text,
                )
            )
        return enriched


class SummarizeAgent:
    def run(self, decision_rows: List[DecisionResult]) -> Dict:
        total = len(decision_rows)
        by_decision = {
            Decision.APPROVED.value: 0,
            Decision.NEEDS_REVIEW.value: 0,
            Decision.REJECTED.value: 0,
            Decision.MISSING_INFO.value: 0,
        }
        top_reasons: Dict[str, int] = {}
        high_risk = 0

        for row in decision_rows:
            by_decision[row.decision.value] = by_decision.get(row.decision.value, 0) + 1
            top_reasons[row.reason_code] = top_reasons.get(row.reason_code, 0) + 1
            if row.risk_score >= 75:
                high_risk += 1

        return {
            "total_expenses": total,
            "decision_counts": by_decision,
            "high_risk_items": high_risk,
            "top_reason_codes": dict(sorted(top_reasons.items(), key=lambda x: x[1], reverse=True)),
            "manager_next_steps": [
                "Review all Rejected and Missing Info expenses first.",
                "Confirm approvals for Needs Review items above threshold.",
                "Validate recurring issues to improve policy communication.",
            ],
        }


def decisions_to_dataframe(decisions: List[DecisionResult]) -> pd.DataFrame:
    rows = []
    for d in decisions:
        row = asdict(d)
        row["decision"] = d.decision.value
        rows.append(row)
    return pd.DataFrame(rows)
