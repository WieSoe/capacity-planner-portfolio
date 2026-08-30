"""Generic absence parser for CSV or XLSX files."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ["Name", "Absence Days"]


def _read_dataframe(filepath: str | Any) -> pd.DataFrame:
	"""Load a CSV or XLSX file and normalize the required columns."""
	if hasattr(filepath, "read") and not isinstance(filepath, (str, bytes)):
		payload = filepath.read()
		buffer = BytesIO(payload)
		filename = str(getattr(filepath, "name", "")).lower()
		if filename.endswith(".csv"):
			df = pd.read_csv(buffer)
		else:
			df = pd.read_excel(buffer)
	else:
		path = str(filepath)
		if path.lower().endswith(".csv"):
			df = pd.read_csv(path)
		else:
			df = pd.read_excel(path)

	columns = {str(column).strip(): column for column in df.columns}
	name_key = None
	absence_key = None

	for key in columns:
		normalized = key.strip().lower()
		if normalized == "name":
			name_key = columns[key]
		if normalized in {"absence days", "absence_days", "absence-days"}:
			absence_key = columns[key]

	if name_key is None or absence_key is None:
		raise ValueError(
			"Expected a file with exactly these columns: 'Name' and 'Absence Days'."
		)

	df = df[[name_key, absence_key]].copy()
	df.columns = REQUIRED_COLUMNS
	df["Name"] = df["Name"].astype(str).str.strip()
	df["Absence Days"] = pd.to_numeric(df["Absence Days"], errors="coerce")
	df = df.dropna(subset=["Name", "Absence Days"])
	return df


def get_absence_days(
	filepath: str | Any,
	start_date: Any | None = None,
	end_date: Any | None = None,
) -> dict[str, float]:
	"""Return absence days per person from a generic CSV/XLSX absence file."""
	_ = start_date, end_date
	df = _read_dataframe(filepath)
	grouped = df.groupby("Name", dropna=True)["Absence Days"].sum().sort_index()
	return {name: float(days) for name, days in grouped.items()}


def get_team_absence_total(
	filepath: str | Any,
	start_date: Any | None = None,
	end_date: Any | None = None,
) -> float:
	"""Return the total absence days across all people in the imported file."""
	_ = start_date, end_date
	absence_by_worker = get_absence_days(filepath)
	return float(sum(absence_by_worker.values()))
