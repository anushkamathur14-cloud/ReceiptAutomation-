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

0. **Receipt Analysis Agent** (LLM): reads receipt image/PDF + OCR text, extracts vendor, amount, category, date, and reasoning. Falls back to OCR rules if no API key.
1. **Validate Agent**: normalizes and validates expense rows.
2. **Retrieve Policy Agent**: extracts policy text and compiles rules.
3. **Decide Agent**: evaluates each expense against policy rules.
4. **Explain Agent** (LLM when configured): plain-English rationale for each decision.
5. **Summarize Agent**: aggregates outcomes and creates manager context.

### Enable the LLM agents

1. Copy `.env.example` to `.env` (local) or add variables in **Railway → Variables**.
2. Set `OPENAI_API_KEY` (or `LLM_API_KEY` + optional `LLM_BASE_URL` for compatible providers).
3. Optional: `LLM_MODEL=gpt-4o-mini`, `USE_LLM_VISION=true`.
4. Restart the app. Check `/health` — `llm_configured` should be `true`.

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
- `expense_details.xlsx`

## Frontend on Lovable

The backend is API-only friendly. See **[API.md](./API.md)** for all endpoints.

| Feature | API |
|---------|-----|
| Manager dashboard data | `GET /api/session/{id}/dashboard` |
| Edit approval thresholds | `PUT /api/session/{id}/policy-thresholds` |
| Receipt scan (LLM agent) | `POST /api/session/{id}/scan-receipt` |
| Run compliance | `POST /api/session/{id}/analyze` |
| Download Excel | `GET /api/runs/{run_id}/expense_details.xlsx` |

Set `CORS_ORIGINS` on Railway to your Lovable app URL (e.g. `https://your-app.lovable.app`).

## Manager dashboard (deployed at `/`)

Single-page managerial review:

- Topline KPIs (spend, approved, needs review, rejected, high risk)
- Decision breakdown & spend by category
- Manager action items & priority exceptions
- Full expense table + Excel export
- **Policy thresholds** panel — amend meal/hotel/software/gift/receipt/late limits
- **2 uploads per user** (receipt or CSV); demo sample load is unlimited

## Web app flows

1. **Load demo data** or upload receipts (max 2 per session).
2. **Adjust policy thresholds** (optional).
3. **Run compliance** — all agents run; table updates with decisions.
4. **Download Excel** — multi-sheet workbook for finance/managers.

## Deploy on Railway

This repo includes a web API so Railway can run it as a service:

- `Dockerfile` — build image
- `railway.toml` — Railway build/deploy settings
- `src/app.py` — FastAPI server

After deploy:

1. Open your Railway public URL (generate domain in **Settings → Networking**).
2. Visit `/` or `/health` to confirm the service is up.
3. Try `/api/sample-run` for a demo run.
4. Use `/docs` to upload your own CSV + policy via `POST /api/run`.

## Notes

- This is a deterministic rule-engine baseline designed for auditability.
- You can extend `src/policy_rules.py` with additional rules and thresholds.
