from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class PolicyConfig:
    meal_limit: float = 75.0
    hotel_limit: float = 250.0
    software_limit: float = 300.0
    gift_limit: float = 50.0
    late_submission_days: int = 30
    receipt_required_over: float = 25.0


THRESHOLD_FIELDS: Dict[str, Dict[str, Any]] = {
    "meal_limit": {
        "label": "Meals — daily limit ($)",
        "description": "Over this amount requires manager approval.",
        "type": "currency",
        "min": 0,
        "max": 10000,
        "default": 75.0,
    },
    "hotel_limit": {
        "label": "Hotels — nightly limit ($)",
        "description": "Over this amount requires manager approval.",
        "type": "currency",
        "min": 0,
        "max": 50000,
        "default": 250.0,
    },
    "software_limit": {
        "label": "Software — pre-approval threshold ($)",
        "description": "Purchases over this amount need pre-approval.",
        "type": "currency",
        "min": 0,
        "max": 100000,
        "default": 300.0,
    },
    "gift_limit": {
        "label": "Gifts — approval threshold ($)",
        "description": "Gifts over this amount require manager approval.",
        "type": "currency",
        "min": 0,
        "max": 10000,
        "default": 50.0,
    },
    "late_submission_days": {
        "label": "Late submission window (days)",
        "description": "Expenses submitted after this many days need review.",
        "type": "integer",
        "min": 1,
        "max": 365,
        "default": 30,
    },
    "receipt_required_over": {
        "label": "Receipt required above ($)",
        "description": "Expenses over this amount must include a receipt.",
        "type": "currency",
        "min": 0,
        "max": 10000,
        "default": 25.0,
    },
}


def default_policy_config() -> PolicyConfig:
    return PolicyConfig()


def policy_config_to_dict(config: PolicyConfig) -> Dict[str, Any]:
    return asdict(config)


def _clamp_value(field: str, value: Any) -> Any:
    meta = THRESHOLD_FIELDS[field]
    if meta["type"] == "integer":
        val = int(round(float(value)))
    else:
        val = round(float(value), 2)
    return max(meta["min"], min(meta["max"], val))


def policy_config_from_dict(data: Dict[str, Any], base: PolicyConfig | None = None) -> PolicyConfig:
    current = policy_config_to_dict(base or default_policy_config())
    for field in THRESHOLD_FIELDS:
        if field in data and data[field] is not None:
            current[field] = _clamp_value(field, data[field])
    return PolicyConfig(**current)


def thresholds_schema() -> Dict[str, Any]:
    """Metadata for Lovable form builders."""
    return {
        "fields": [
            {"key": key, **meta, "value": meta["default"]}
            for key, meta in THRESHOLD_FIELDS.items()
        ]
    }


def thresholds_response(config: PolicyConfig) -> Dict[str, Any]:
    values = policy_config_to_dict(config)
    fields = []
    for key, meta in THRESHOLD_FIELDS.items():
        fields.append({"key": key, **meta, "value": values[key]})
    return {"thresholds": values, "fields": fields}


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
