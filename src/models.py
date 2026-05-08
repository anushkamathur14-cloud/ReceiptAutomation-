from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    APPROVED = "Approved"
    NEEDS_REVIEW = "Needs Review"
    REJECTED = "Rejected"
    MISSING_INFO = "Missing Info"


@dataclass
class ExpenseRow:
    expense_id: str
    employee_id: str
    category: str
    amount: float
    currency: str
    expense_date: str
    submission_date: str
    receipt_provided: bool
    manager_approval: bool
    pre_approval: bool
    flight_class: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class DecisionResult:
    expense_id: str
    decision: Decision
    risk_score: int
    reason_code: str
    reason_text: str
