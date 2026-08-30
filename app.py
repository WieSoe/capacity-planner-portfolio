"""Streamlit app for Engineering Manager capacity planning."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from absences import get_absence_days, get_team_absence_total
from capacity import monte_carlo, robust_monte_carlo, rule_of_three
from jira_client import fetch_last_completed_sprints, fetch_throughput_history

TEAMS = {
	"Team Alpha": {
		"board_id": 123,
		"project_key": "ALPHA",
		"story_points_field": "customfield_10016",
	},
	"Team Beta": {
		"board_id": 456,
		"project_key": "BETA",
		"story_points_field": "customfield_10016",
	},
}

SPRINT_HISTORY_FILE = Path("sprint_history.json")


def _load_sprint_history() -> dict:
	"""Load sprint history from JSON file, or return empty dict if file doesn't exist."""
	if SPRINT_HISTORY_FILE.exists():
		try:
			with open(SPRINT_HISTORY_FILE) as f:
				return json.load(f)
		except Exception:
			return {}
	return {}


def _save_sprint_history(history: dict) -> None:
	"""Save sprint history to JSON file."""
	with open(SPRINT_HISTORY_FILE, "w") as f:
		json.dump(history, f, indent=2)


def _get_sprint_fte_value(team_name: str, sprint_name: str) -> float:
	"""Get saved historical Net FTE days for a sprint, or 0 if not found."""
	history = _load_sprint_history()
	value = history.get(team_name, {}).get(sprint_name, 0.0)
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0


def _extract_issue_counts(sprints: list[dict]) -> list[int]:
	"""Return closed issue counts in sprint order."""
	return [int(sprint.get("closed_issues", 0)) for sprint in sprints]


def _extract_story_points(sprints: list[dict]) -> list[float]:
	"""Return completed story points in sprint order."""
	return [float(sprint.get("completed_story_points", 0) or 0) for sprint in sprints]


def _count_working_days(start_date: date, end_date: date) -> int:
	"""Return number of business days (Mon-Fri) in an inclusive range."""
	if start_date > end_date:
		return 0
	return int(len(pd.bdate_range(start=start_date, end=end_date)))


def main() -> None:
	"""Render the capacity planning UI."""
	st.set_page_config(page_title="Capacity Planning Team Alpha", layout="wide")
	st.markdown(
		"""
		<style>
			.stAppDeployButton {display: none;}
		</style>
		""",
		unsafe_allow_html=True,
	)

	if "sprint_data" not in st.session_state:
		st.session_state.sprint_data = []
	if "absence_file" not in st.session_state:
		st.session_state.absence_file = None
	if "team_size" not in st.session_state:
		st.session_state.team_size = 1
	if "jira_board_id" not in st.session_state:
		st.session_state.jira_board_id = 1
	if "mc_history" not in st.session_state:
		st.session_state.mc_history = []
	if "mc_result" not in st.session_state:
		st.session_state.mc_result = None
	if "selected_team" not in st.session_state:
		st.session_state.selected_team = list(TEAMS.keys())[0]

	selected_team = st.sidebar.selectbox("Select team", list(TEAMS.keys()), key="team_selector")
	st.session_state.selected_team = selected_team

	st.title(f"Capacity Planning {selected_team}")

	uploaded_absence_file = st.sidebar.file_uploader(
		"Upload absence file (CSV or XLSX)",
		type=["csv", "xlsx", "xls"],
	)
	if uploaded_absence_file is not None:
		st.session_state.absence_file = uploaded_absence_file

	st.session_state.team_size = st.sidebar.number_input(
		"Total team size",
		min_value=1,
		value=st.session_state.team_size,
		step=1,
	)

	absence_file = st.session_state.absence_file
	team_size = st.session_state.team_size

	sprint_data = st.session_state.sprint_data

	with st.container(border=True):
		tab_forecast, tab_quarterly, tab_monte_carlo = st.tabs(
			["Sprint Forecast", "Quarterly Planning", "Monte Carlo Throughput"]
		)

	with tab_forecast:
		st.caption("How many issues and story points will we complete next sprint?")
		st.caption("Use tasks for unplanned work (bugs, security). Use story points for planned feature work.")

		board_id = st.number_input(
			"Jira Board ID",
			min_value=1,
			value=int(TEAMS[selected_team]["board_id"]),
			step=1,
			key="forecast_board_id_input",
			help=(
				"Your Jira board ID, found in the board URL: "
				"/boards/123 -> enter 123. "
				"The tool fetches the last 3 completed sprints from this board "
				"as the basis for your throughput forecast and Simplified Monte Carlo simulation."
			),
		)

		sprint_date_col1, sprint_date_col2 = st.columns(2)
		sprint_start_date = sprint_date_col1.date_input("Sprint start date", value=date.today())
		sprint_end_date = sprint_date_col2.date_input("Sprint end date", value=date.today())
		public_holidays_sprint = st.number_input(
			"Other capacity reductions this sprint (days)",
			min_value=0.0,
			value=0.0,
			step=0.5,
			help=(
				"Include public holidays that apply to your team members. "
				"Calculate manually: count how many team members are affected "
				"per holiday day. Example: International Women's Day (March 8) "
				"only applies in Berlin - if 2 out of 5 engineers are based "
				"in Berlin, enter 2. Check public holidays per Bundesland at: "
				"https://publicholidays.de"
			),
		)

		if st.button("Load Sprints"):
			try:
				st.session_state.jira_board_id = int(board_id)
				st.session_state.sprint_data = fetch_last_completed_sprints(
					board_id=int(board_id),
					sprint_count=3,
					project_key=TEAMS[selected_team]["project_key"],
					story_points_field=TEAMS[selected_team]["story_points_field"],
				)
				st.session_state.pop("sprint_fte_values", None)
				if not st.session_state.sprint_data:
					st.warning("No completed sprints found for this board.")
			except Exception as exc:  # pragma: no cover - UI guardrail
				st.error(f"Failed to load sprint data: {exc}")

		sprint_data = st.session_state.sprint_data
		if not sprint_data:
			st.info("Enter your Jira Board ID and click Load Sprints to see the forecast.")
		st.divider()

		if sprint_data:
			table_rows = [
				{
					"Sprint": sprint.get("sprint_name", "Unknown Sprint"),
					"Closed Issues": int(sprint.get("closed_issues", 0)),
				}
				for sprint in sprint_data
			]
			st.table(table_rows)

			st.subheader("Historical Net FTE Days")
			st.caption("Enter the net FTE days available in each of the last 3 sprints.")

			fte_input_values: dict[str, float] = {}
			history = _load_sprint_history()
			team_history = history.get(selected_team, {})

			for index, sprint in enumerate(sprint_data[:3]):
				sprint_name = sprint.get("sprint_name", "Unknown Sprint")
				default_value = _get_sprint_fte_value(selected_team, sprint_name)
				fte_input_values[sprint_name] = st.number_input(
					sprint_name,
					min_value=0.0,
					value=float(default_value),
					step=0.5,
					key=f"fte_{selected_team}_{sprint_name}",
				)

			save_and_calculate_clicked = st.button("Update Forecast")
		else:
			save_and_calculate_clicked = False

		if sprint_start_date > sprint_end_date:
			st.warning("Sprint start date must be on or before sprint end date.")

		if sprint_data:
			sprint_working_days = _count_working_days(sprint_start_date, sprint_end_date)
			team_days = float(team_size * sprint_working_days)
			total_absence_days = 0.0
			if absence_file is not None and sprint_start_date <= sprint_end_date:
				try:
					absence_file.seek(0)
					absence_by_worker = get_absence_days(absence_file)
					absence_table_rows = [
						{"Name": worker, "Absence Days": float(days)}
						for worker, days in sorted(absence_by_worker.items())
					]
					st.subheader("Absences In Selected Sprint")
					if absence_table_rows:
						st.table(absence_table_rows)
					else:
						st.info("No absences found in the uploaded file.")

					total_absence_days = float(sum(absence_by_worker.values()))
				except Exception as exc:  # pragma: no cover - UI guardrail
					st.error(f"Failed to read absence file: {exc}")

			net_fte_days = max(team_days - total_absence_days - float(public_holidays_sprint), 0.0)

			cap_col1, cap_col2, cap_col3, cap_col4 = st.columns(4)
			cap_col1.metric("Team size", f"{team_size}")
			cap_col2.metric("Sprint working days", f"{sprint_working_days}")
			cap_col3.metric("Total absence days", f"{total_absence_days:.1f}")
			cap_col4.metric("Net FTE days", f"{net_fte_days:.1f}")

			if absence_file is None:
				st.caption(
					"No absence file uploaded — absence days not included. "
					"Use 'Other capacity reductions' to manually enter absences."
				)

			if save_and_calculate_clicked:
				if any(v == 0 for v in fte_input_values.values()):
					st.warning("Enter Net FTE days for all 3 sprints before updating the forecast.")
				else:
					history = _load_sprint_history()
					if selected_team not in history:
						history[selected_team] = {}
					for sprint_name, fte_value in fte_input_values.items():
						history[selected_team][sprint_name] = float(fte_value)
					_save_sprint_history(history)
					st.session_state.sprint_fte_values = dict(fte_input_values)
					st.success("FTE values saved.")

			sprint_fte_values = st.session_state.get("sprint_fte_values")
			if sprint_fte_values and all(v > 0 for v in sprint_fte_values.values()):
				historical_avg_fte = sum(sprint_fte_values.values()) / len(sprint_fte_values)
				capacity_ratio = net_fte_days / historical_avg_fte if historical_avg_fte > 0 else 0.0
				st.caption(
					f"Historical avg FTE: {historical_avg_fte:.1f} days | "
					f"Current FTE: {net_fte_days:.1f} days | "
					f"Ratio: {capacity_ratio * 100:.1f}%"
				)
			else:
				capacity_ratio = None

			issue_counts = _extract_issue_counts(sprint_data)
			story_points = _extract_story_points(sprint_data)
			try:
				task_rule_forecast = rule_of_three(issue_counts)
				task_mc = monte_carlo(issue_counts)
				story_points_rule_forecast = rule_of_three(story_points)
				story_points_mc = monte_carlo(story_points)

				st.divider()

				st.subheader("Task throughput (all issue types)")
				st.caption("How many tasks can we complete?")
				if capacity_ratio is not None:
					task_adjusted_forecast = task_rule_forecast * capacity_ratio
					col1, col2, col3, col4, col5 = st.columns(5)
					col1.metric("Expected throughput", f"{task_rule_forecast:.0f} tasks")
					col2.metric("Capacity-adjusted", f"{task_adjusted_forecast:.0f} tasks")
					col3.metric(
						"p50",
						f"{task_mc['p50']:.0f} tasks",
					)
					col4.metric(
						"p85",
						f"{task_mc['p85']:.0f} tasks",
					)
					col5.metric(
						"p95",
						f"{task_mc['p95']:.0f} tasks",
					)
				else:
					col1, col2, col3, col4 = st.columns(4)
					col1.metric("Expected throughput", f"{task_rule_forecast:.0f} tasks")
					col2.metric(
						"p50",
						f"{task_mc['p50']:.0f} tasks",
					)
					col3.metric(
						"p85",
						f"{task_mc['p85']:.0f} tasks",
					)
					col4.metric(
						"p95",
						f"{task_mc['p95']:.0f} tasks",
					)

				st.divider()

				st.subheader("Story point velocity (planned features only)")
				st.caption("How many story points can we deliver?")
				if capacity_ratio is not None:
					story_points_adjusted_forecast = story_points_rule_forecast * capacity_ratio
					col1, col2, col3, col4, col5 = st.columns(5)
					col1.metric("Expected velocity", f"{story_points_rule_forecast:.1f} points")
					col2.metric("Capacity-adjusted", f"{story_points_adjusted_forecast:.1f} points")
					col3.metric(
						"p50",
						f"{story_points_mc['p50']:.1f} points",
					)
					col4.metric(
						"p85",
						f"{story_points_mc['p85']:.1f} points",
					)
					col5.metric(
						"p95",
						f"{story_points_mc['p95']:.1f} points",
					)
				else:
					col1, col2, col3, col4 = st.columns(4)
					col1.metric("Expected velocity", f"{story_points_rule_forecast:.1f} points")
					col2.metric(
						"p50",
						f"{story_points_mc['p50']:.1f} points",
					)
					col3.metric(
						"p85",
						f"{story_points_mc['p85']:.1f} points",
					)
					col4.metric(
						"p95",
						f"{story_points_mc['p95']:.1f} points",
					)
				st.caption(
					"Note: this is a simplified simulation based on only 3 sprints. "
					"For a statistically robust forecast, at least 10-20 sprints "
					"of historical data are recommended."
				)

				st.caption(
					"p50 means: in 50% of sprints the team completes at least this many tasks. "
					"Use p85 for conservative planning."
				)

				chart_rows = [
					{
						"Sprint": sprint.get("sprint_name", "Unknown Sprint"),
						"Closed Issues": int(sprint.get("closed_issues", 0)),
					}
					for sprint in sprint_data
				]
				st.subheader("Closed Issues Per Sprint")
				st.bar_chart(chart_rows, x="Sprint", y="Closed Issues")
			except Exception as exc:  # pragma: no cover - UI guardrail
				st.error(f"Failed to calculate sprint forecast: {exc}")

	with tab_quarterly:
		st.caption(
			"How many features fit into your quarter based on the net "
			"sprint capacity? Use this to scope themes by t-shirt size: "
			"XL = 5 sprints | L = 4 sprints | M = 2 sprints | S = 1 sprint"
		)
		st.caption("Upload an absence file in the sidebar for automatic absence calculation.")

		quarter_date_col1, quarter_date_col2 = st.columns(2)
		quarter_start_date = quarter_date_col1.date_input("Quarter start date", value=date.today())
		quarter_end_date = quarter_date_col2.date_input("Quarter end date", value=date.today())
		public_holidays_quarter = st.number_input(
			"Other capacity reductions this quarter (days)",
			min_value=0.0,
			value=0.0,
			step=0.5,
			help=(
				"Include public holidays that apply to your team members. "
				"Calculate manually: count how many team members are affected "
				"per holiday day. Example: International Women's Day (March 8) "
				"only applies in Berlin - if 2 out of 5 engineers are based "
				"in Berlin, enter 2. Check public holidays per Bundesland at: "
				"https://publicholidays.de"
			),
		)

		if quarter_start_date > quarter_end_date:
			st.warning("Quarter start date must be on or before quarter end date.")

		q_num_sprints = st.number_input("Number of sprints in quarter", min_value=1, value=6, step=1)
		reserve_maintenance = st.checkbox("Reserve 20% for maintenance and support")
		reserve_project_work = st.checkbox("Reserve 20% for project work / community")

		try:
			total_absence_days_quarter = 0.0
			if absence_file is not None and quarter_start_date <= quarter_end_date:
				absence_file.seek(0)
				total_absence_days_quarter = get_team_absence_total(absence_file)
				st.metric("Total absence days this quarter", f"{total_absence_days_quarter:.1f}")
			else:
				st.info("Upload an absence file in the sidebar to auto-calculate quarter absences.")

			total_capacity_reduction_days = total_absence_days_quarter + float(public_holidays_quarter)
			sprint_working_days = 10.0
			total_quarter_team_days = float(int(q_num_sprints) * int(team_size)) * sprint_working_days
			net_quarter_team_days = max(total_quarter_team_days - total_capacity_reduction_days, 0.0)
			total_quarter_capacity_sprints = (
				0.0
				if int(team_size) <= 0
				else net_quarter_team_days / (float(int(team_size)) * sprint_working_days)
			)

			maintenance_reserved_sprints = (
				total_quarter_capacity_sprints * 0.20 if reserve_maintenance else 0.0
			)
			project_work_reserved_sprints = (
				total_quarter_capacity_sprints * 0.20 if reserve_project_work else 0.0
			)
			feature_sprints = max(
				total_quarter_capacity_sprints
				- maintenance_reserved_sprints
				- project_work_reserved_sprints,
				0.0,
			)

			st.metric(
				"Feature sprints available for new work this quarter",
				f"{feature_sprints:.2f}",
			)
			if reserve_maintenance:
				st.caption(f"{maintenance_reserved_sprints:.2f} sprints reserved for maintenance")
			if reserve_project_work:
				st.caption(f"{project_work_reserved_sprints:.2f} sprints reserved for project work")
		except Exception as exc:  # pragma: no cover - UI guardrail
			st.error(f"Failed to calculate quarterly capacity: {exc}")

	with tab_monte_carlo:
		st.caption("Run a robust throughput simulation based on a larger sprint history.")
		sim_date_col1, sim_date_col2 = st.columns(2)
		sim_start_date = sim_date_col1.date_input("Simulation start date", value=date.today())
		sim_end_date = sim_date_col2.date_input("Simulation end date", value=date.today())
		sprint_length_days = st.number_input(
			"Sprint length (working days)",
			min_value=1,
			value=10,
			step=1,
			help=(
				"Number of working days (Mon-Fri) per sprint. "
				"A standard 2-week sprint = 10 working days."
			),
		)
		st.caption("Simulation is based on the last 20 completed sprints as historical data.")

		working_days_in_period = _count_working_days(sim_start_date, sim_end_date)
		num_sprints_in_period = float(working_days_in_period / float(sprint_length_days))
		if sim_start_date > sim_end_date:
			st.warning("Simulation start date must be on or before simulation end date.")
			working_days_in_period = 0
			num_sprints_in_period = 0.0

		mc_board_id = st.number_input(
			"Jira Board ID",
			min_value=1,
			value=int(TEAMS[selected_team]["board_id"]),
			step=1,
			key="mc_board_id_input",
			help=(
				"Your Jira board ID, found in the board URL: "
				"/boards/123 -> enter 123."
			),
		)

		if st.button("Run Monte Carlo"):
			try:
				st.session_state.jira_board_id = int(mc_board_id)
				history = fetch_throughput_history(
					board_id=int(mc_board_id),
					sprint_count=20,
					project_key=TEAMS[selected_team]["project_key"],
					story_points_field=TEAMS[selected_team]["story_points_field"],
				)
				st.session_state.mc_history = history
				st.session_state.mc_result = robust_monte_carlo(history)
			except Exception as exc:  # pragma: no cover - UI guardrail
				st.error(f"Failed to run Monte Carlo throughput simulation: {exc}")

		st.caption(
			"Note: results are based on historical throughput from Jira. "
			"If your team size has changed significantly recently, "
			"older sprint data may not reflect current capacity."
		)

		mc_history = st.session_state.mc_history
		mc_result = st.session_state.mc_result
		if mc_history and mc_result:
			history_rows = [
				{"Sprint": index + 1, "Closed Issues": int(value)}
				for index, value in enumerate(mc_history)
			]
			st.subheader("Historical Throughput")
			st.table(history_rows)

			st.subheader("Per Sprint Throughput")
			col1, col2, col3 = st.columns(3)
			col1.metric("p50", f"{mc_result['p50']:.0f} tasks")
			col2.metric("p85", f"{mc_result['p85']:.0f} tasks")
			col3.metric("p95", f"{mc_result['p95']:.0f} tasks")

			p50_total = float(mc_result["p50"] * num_sprints_in_period)
			p85_total = float(mc_result["p85"] * num_sprints_in_period)
			p95_total = float(mc_result["p95"] * num_sprints_in_period)

			st.subheader("Full-Period Throughput")
			total_col1, total_col2, total_col3 = st.columns(3)
			total_col1.metric("p50 total", f"{p50_total:.0f} tasks")
			total_col2.metric("p85 total", f"{p85_total:.0f} tasks")
			total_col3.metric("p95 total", f"{p95_total:.0f} tasks")

			st.caption(f"Based on {len(mc_history)} sprints, 10,000 simulations")
			st.caption(
				f"Based on {working_days_in_period} working days = "
				f"{num_sprints_in_period:.2f} sprints of {int(sprint_length_days)} working days each."
			)
			st.caption(
				"p50 is the typical throughput outcome, p85 is a conservative planning target, "
				"and p95 is the worst-case planning guardrail."
			)
		else:
			st.info("Set your board and sprint range, then run Monte Carlo.")


if __name__ == "__main__":
	main()
