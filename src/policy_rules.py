from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class PolicyConfig:
    meal_limit: float = 75.0
    hotel_limit: float = 250.0
    software_limit: float = 300.0
    gift_limit: float = 50.0
    late_submission_days: int = 30
    receipt_required_over: float = 25.0


def default_policy_config() -> PolicyConfig:
    return PolicyConfig()


def rule_catalog() -> Dict[str, str]:
    return {
        "MEAL_OVER_LIMIT": "Meals over daily limit need manager approval.",
        "HOTEL_OVER_LIMIT": "Hotels over nightly limit need manager approval.",
        "FLIGHT_CLASS_RESTRICTED": "Flights must be economy unless manager approval is present.",
        "RIDESHARE_RECEIPT_REQUIRED": "Rideshare expenses require receipt.",
        "SOFTWARE_PREAPPROVAL_REQUIRED": "Software over threshold needs pre-approval.",
        "ALCOHOL_NON_REIMBURSABLE": "Alcohol is non-reimbursable unless manager approved for client entertainment.",
        "GIFT_OVER_LIMIT": "Gifts over threshold require manager approval.",
        "LATE_SUBMISSION": "Submission occurred after allowed window.",
        "MISSING_RECEIPT_OVER_THRESHOLD": "Receipt required for expenses over receipt threshold.",
        "VALIDATION_ERROR": "Missing or invalid required fields.",
        "OK": "Compliant with policy.",
    }
