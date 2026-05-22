from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd

from .agents import (
    DecideAgent,
    ExplainAgent,
    RetrievePolicyAgent,
    SummarizeAgent,
    ValidateAgent,
    decisions_to_dataframe,
)
from .policy_rules import PolicyConfig, default_policy_config
from .reporting import write_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expense Receipt Compliance Bot")
    parser.add_argument("--expenses", required=True, help="Path to expenses CSV")
    parser.add_argument("--policy", required=True, help="Path to policy file (PDF/TXT/DOCX)")
    parser.add_argument("--output", default="output", help="Output directory")
    return parser.parse_args()


def run_pipeline(
    expenses_path: Path,
    policy_path: Path,
    output_dir: Path,
    policy_config: Optional[PolicyConfig] = None,
) -> dict:
    expenses_df = pd.read_csv(expenses_path)
    config = policy_config or default_policy_config()

    validate_agent = ValidateAgent()
    policy_agent = RetrievePolicyAgent()
    decide_agent = DecideAgent(config)
    explain_agent = ExplainAgent()
    summarize_agent = SummarizeAgent()

    valid_expenses, validation_errors = validate_agent.run(expenses_df)
    policy_context = policy_agent.run(policy_path)
    decisions = decide_agent.run(valid_expenses)
    explained = explain_agent.run(decisions + validation_errors, policy_context["rules"])
    summary = summarize_agent.run(explained)
    decisions_df = decisions_to_dataframe(explained)

    write_outputs(output_dir, decisions_df, summary, expenses_df=expenses_df)
    return {
        "summary": summary,
        "output_dir": str(output_dir),
        "files": {
            "decisions_csv": str(output_dir / "decisions.csv"),
            "summary_json": str(output_dir / "summary.json"),
            "manager_report_pdf": str(output_dir / "manager_report.pdf"),
            "expense_details_xlsx": str(output_dir / "expense_details.xlsx"),
        },
    }


def main() -> None:
    args = parse_args()
    run_pipeline(Path(args.expenses), Path(args.policy), Path(args.output))


if __name__ == "__main__":
    main()
