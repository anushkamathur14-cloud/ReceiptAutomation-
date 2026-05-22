from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def write_outputs(
    output_dir: Path,
    decisions_df: pd.DataFrame,
    summary: Dict,
    expenses_df: pd.DataFrame | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions_df.to_csv(output_dir / "decisions.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_manager_pdf(output_dir / "manager_report.pdf", decisions_df, summary)

    if expenses_df is not None:
        from .excel_export import write_expense_workbook

        write_expense_workbook(
            output_dir / "expense_details.xlsx",
            expenses_df,
            decisions_df,
            summary,
        )


def write_manager_pdf(path: Path, decisions_df: pd.DataFrame, summary: Dict) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 0.75 * inch

    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.75 * inch, y, "Expense Receipt Compliance Report")
    y -= 0.4 * inch

    c.setFont("Helvetica", 10)
    c.drawString(0.75 * inch, y, f"Total expenses: {summary.get('total_expenses', 0)}")
    y -= 0.2 * inch
    c.drawString(0.75 * inch, y, f"High risk items: {summary.get('high_risk_items', 0)}")
    y -= 0.3 * inch

    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, "Decision Counts")
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)
    for key, value in summary.get("decision_counts", {}).items():
        c.drawString(1.0 * inch, y, f"- {key}: {value}")
        y -= 0.18 * inch

    y -= 0.1 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, "Top Reasons")
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)
    for key, value in list(summary.get("top_reason_codes", {}).items())[:8]:
        c.drawString(1.0 * inch, y, f"- {key}: {value}")
        y -= 0.18 * inch

    y -= 0.1 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, "Manager Next Steps")
    y -= 0.2 * inch
    c.setFont("Helvetica", 10)
    for step in summary.get("manager_next_steps", []):
        c.drawString(1.0 * inch, y, f"- {step}")
        y -= 0.18 * inch

    y -= 0.2 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(0.75 * inch, y, "Sample Decisions")
    y -= 0.2 * inch
    c.setFont("Helvetica", 9)
    sample = decisions_df.head(12)
    for _, row in sample.iterrows():
        line = (
            f"{row['expense_id']} | {row['decision']} | "
            f"Risk {row['risk_score']} | {row['reason_code']}"
        )
        c.drawString(0.9 * inch, y, line[:110])
        y -= 0.16 * inch
        if y < 0.8 * inch:
            c.showPage()
            y = height - 0.75 * inch
            c.setFont("Helvetica", 9)

    c.save()
