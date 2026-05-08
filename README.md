# Expense Receipt Compliance Bot

This project implements a modular **five-agent compliance pipeline** for reviewing employee expense submissions against policy rules and producing a manager-ready report.

## What it does

- Ingests expense data from CSV.
- Reads and parses policy content from PDF, TXT, or DOCX.
- Validates required fields and basic data quality.
- Applies policy decisions per line item:
  - `Approved`
  - `Needs Review`
  - `Rejected`
  - `Missing Info`
- Generates plain-English rationale for each decision.
- Produces:
  - line-level decisions (`CSV`)
  - manager summary (`JSON`)
  - manager report (`PDF`, default)

## Agent architecture

1. **Validate Agent**: normalizes and validates expense rows.
2. **Retrieve Policy Agent**: extracts policy text and compiles rules.
3. **Decide Agent**: evaluates each expense against policy rules.
4. **Explain Agent**: creates human-readable rationale.
5. **Summarize Agent**: aggregates outcomes and creates manager context.

## Quick start

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run:

```bash
python -m src.main --expenses data/sample_expenses.csv --policy data/sample_policy.txt --output output
```

If you use a PDF policy:

```bash
python -m src.main --expenses data/sample_expenses.csv --policy data/Expense-Receipt-Compliance-Bot.pdf --output output
```

## Input format

Expected CSV columns:

- `expense_id`
- `employee_id`
- `category`
- `amount`
- `currency`
- `expense_date` (YYYY-MM-DD preferred)
- `submission_date` (YYYY-MM-DD preferred)
- `receipt_provided` (`yes`/`no` or boolean-like)
- `manager_approval` (`yes`/`no` or boolean-like)
- `pre_approval` (`yes`/`no` or boolean-like, optional but recommended)
- `flight_class` (for flights, optional otherwise)
- `notes` (optional)

## Outputs

Generated in the output directory:

- `decisions.csv`
- `summary.json`
- `manager_report.pdf`

## Notes

- This is a deterministic rule-engine baseline designed for auditability.
- You can extend `src/policy_rules.py` with additional rules and thresholds.
