from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pandas as pd


def write_expense_workbook(
    path: Path,
    expenses_df: pd.DataFrame,
    decisions_df: Optional[pd.DataFrame] = None,
    summary: Optional[Dict] = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        detail = expenses_df.copy()
        if decisions_df is not None and not decisions_df.empty:
            detail = expenses_df.merge(
                decisions_df,
                on="expense_id",
                how="left",
                suffixes=("", "_decision"),
            )
        detail.to_excel(writer, sheet_name="Expense Details", index=False)

        if decisions_df is not None and not decisions_df.empty:
            decisions_df.to_excel(writer, sheet_name="Compliance Decisions", index=False)

        if summary:
            summary_rows = []
            for key, value in summary.items():
                if isinstance(value, dict):
                    for sub_key, sub_val in value.items():
                        summary_rows.append({"metric": f"{key}.{sub_key}", "value": sub_val})
                elif isinstance(value, list):
                    summary_rows.append({"metric": key, "value": "; ".join(value)})
                else:
                    summary_rows.append({"metric": key, "value": value})
            pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)
