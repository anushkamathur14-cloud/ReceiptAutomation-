from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from pypdf import PdfReader

from .llm_client import chat_json, is_llm_configured
from .models import Decision, DecisionResult, ExpenseRow
from .policy_rules import PolicyConfig, default_policy_config, rule_catalog


RECEIPT_ANALYSIS_SYSTEM = """You are the Receipt Analysis Agent for an enterprise expense compliance system.
Extract structured expense fields from receipt text (and image if provided).
Return ONLY valid JSON with these keys:
- vendor (string)
- category (one of: Meals, Hotels, Flights, Rideshare, Software, Alcohol, Gifts, Other)
- amount (number, total paid)
- currency (string, e.g. USD)
- expense_date (ISO date YYYY-MM-DD if possible, else best estimate)
- notes (short plain-English summary of the purchase)
- confidence (high | medium | low)
- agent_reasoning (1-2 sentences explaining your extraction)
Use business expense categories. If alcohol is visible, category must be Alcohol."""


class ReceiptAnalysisAgent:
    """Agent 0: LLM-powered receipt understanding (falls back to OCR heuristics)."""

    def run(self, receipt_path: Path, employee_id: str = "") -> dict:
        from .receipt_scanner import extract_text_from_file, parse_receipt_text

        ocr_text = extract_text_from_file(receipt_path)
        if not ocr_text.strip():
            ocr_text = f"Receipt filename: {receipt_path.name}"

        if is_llm_configured():
            try:
                parsed = self._analyze_with_llm(receipt_path, ocr_text, employee_id)
                parsed["analysis_method"] = "llm_agent"
                parsed["receipt_filename"] = receipt_path.name
                return parsed
            except Exception as exc:
                parsed = parse_receipt_text(ocr_text, receipt_path.name)
                parsed["analysis_method"] = "ocr_fallback"
                parsed["llm_error"] = str(exc)
        else:
            parsed = parse_receipt_text(ocr_text, receipt_path.name)
            parsed["analysis_method"] = "ocr_rules"

        parsed["receipt_filename"] = receipt_path.name
        parsed["employee_id"] = employee_id or parsed.get("employee_id", "E-SCAN")
        return parsed

    def _analyze_with_llm(self, receipt_path: Path, ocr_text: str, employee_id: str) -> dict:
        user_prompt = (
            f"Employee ID: {employee_id or 'E-SCAN'}\n"
            f"Receipt filename: {receipt_path.name}\n\n"
            f"OCR text from receipt:\n{ocr_text[:6000]}"
        )
        data = chat_json(RECEIPT_ANALYSIS_SYSTEM, user_prompt, image_path=receipt_path)
        today = date.today().isoformat()
        amount = float(data.get("amount") or 0)
        return {
            "employee_id": employee_id or "E-SCAN",
            "category": str(data.get("category") or "Other"),
            "amount": round(amount, 2),
            "currency": str(data.get("currency") or "USD"),
            "expense_date": str(data.get("expense_date") or today),
            "submission_date": today,
            "receipt_provided": "yes",
            "manager_approval": "no",
            "pre_approval": "no",
            "flight_class": "",
            "notes": str(data.get("notes") or f"LLM analyzed receipt: {data.get('vendor', 'Unknown')}"),
            "vendor": str(data.get("vendor") or "Unknown"),
            "scan_confidence": str(data.get("confidence") or "medium"),
            "agent_reasoning": str(data.get("agent_reasoning") or ""),
            "raw_text": ocr_text[:2000],
        }


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
    EXPLAIN_SYSTEM = """You are the Explain Agent for expense compliance.
Given policy rule codes and decisions, write clear plain-English explanations for managers.
Return JSON: {"explanations": [{"expense_id": "...", "reason_text": "..."}]}"""

    def run(self, decisions: List[DecisionResult], rules: Dict[str, str]) -> List[DecisionResult]:
        if is_llm_configured() and decisions:
            try:
                return self._run_with_llm(decisions, rules)
            except Exception:
                pass
        return self._run_rules_only(decisions, rules)

    def _run_rules_only(
        self, decisions: List[DecisionResult], rules: Dict[str, str]
    ) -> List[DecisionResult]:
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

    def _run_with_llm(
        self, decisions: List[DecisionResult], rules: Dict[str, str]
    ) -> List[DecisionResult]:
        payload = [
            {
                "expense_id": d.expense_id,
                "decision": d.decision.value,
                "reason_code": d.reason_code,
                "risk_score": d.risk_score,
                "policy_rule": rules.get(d.reason_code, ""),
            }
            for d in decisions
        ]
        user_prompt = f"Explain these compliance decisions:\n{json.dumps(payload, indent=2)}"
        data = chat_json(self.EXPLAIN_SYSTEM, user_prompt)
        explanation_map = {
            item["expense_id"]: item.get("reason_text", "")
            for item in data.get("explanations", [])
            if item.get("expense_id")
        }
        enriched: List[DecisionResult] = []
        for d in decisions:
            text = explanation_map.get(d.expense_id) or rules.get(
                d.reason_code, "Policy evaluation result generated."
            )
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
