"""Clickable demo app with mocked data and no external integrations."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from capacity import monte_carlo, robust_monte_carlo, rule_of_three

DEFAULT_SPRINTS = [
	{"Sprint": "Sprint 41", "Closed Issues": 23, "Story Points": 42.0, "Net FTE Days": 39.0},
	{"Sprint": "Sprint 42", "Closed Issues": 21, "Story Points": 38.0, "Net FTE Days": 37.5},
	{"Sprint": "Sprint 43", "Closed Issues": 26, "Story Points": 45.0, "Net FTE Days": 40.0},
]

DEFAULT_THROUGHPUT = [18, 20, 22, 17, 24, 19, 21, 25, 23, 20, 18, 26, 19, 27, 22, 24, 20, 23, 21, 25]


def _count_working_days(start_date: date, end_date: date) -> int:
	if start_date > end_date:
		return 0
	return int(len(pd.bdate_range(start=start_date, end=end_date)))


def _render_forecast_tab() -> None:
	st.caption("Click through this dummy using editable sample data. No Jira access required.")

	sprint_df = st.data_editor(
		pd.DataFrame(DEFAULT_SPRINTS),
		num_rows="fixed",
		use_container_width=True,
		key="demo_sprint_df",
	)

	sprint_date_col1, sprint_date_col2 = st.columns(2)
	sprint_start_date = sprint_date_col1.date_input("Sprint start date", value=date.today())
	sprint_end_date = sprint_date_col2.date_input("Sprint end date", value=date.today())

	team_col1, team_col2 = st.columns(2)
	team_size = team_col1.number_input("Total team size", min_value=1, value=5, step=1)
	other_reductions = team_col2.number_input(
		"Other capacity reductions this sprint (days)",
		min_value=0.0,
		value=2.0,
		step=0.5,
	)

	working_days = _count_working_days(sprint_start_date, sprint_end_date)
	total_absence_days = float(max((team_size * working_days) - float(sprint_df["Net FTE Days"].mean()), 0.0))
	net_fte_days = max((team_size * working_days) - total_absence_days - other_reductions, 0.0)

	cap_col1, cap_col2, cap_col3, cap_col4 = st.columns(4)
	cap_col1.metric("Team size", f"{team_size}")
	cap_col2.metric("Sprint working days", f"{working_days}")
	cap_col3.metric("Sample absence days", f"{total_absence_days:.1f}")
	cap_col4.metric("Net FTE days", f"{net_fte_days:.1f}")

	issue_counts = [int(value) for value in sprint_df["Closed Issues"].tolist()[:3]]
	story_points = [float(value) for value in sprint_df["Story Points"].tolist()[:3]]
	historical_fte = [float(value) for value in sprint_df["Net FTE Days"].tolist()[:3]]
	historical_avg_fte = sum(historical_fte) / len(historical_fte)
	capacity_ratio = 0.0 if historical_avg_fte == 0 else net_fte_days / historical_avg_fte

	task_rule_forecast = rule_of_three(issue_counts)
	task_mc = monte_carlo(issue_counts)
	story_points_rule_forecast = rule_of_three(story_points)
	story_points_mc = monte_carlo(story_points)

	st.caption(
		f"Historical avg FTE: {historical_avg_fte:.1f} days | "
		f"Current FTE: {net_fte_days:.1f} days | "
		f"Ratio: {capacity_ratio * 100:.1f}%"
	)

	st.subheader("Task throughput")
	t_col1, t_col2, t_col3, t_col4, t_col5 = st.columns(5)
	t_col1.metric("Expected throughput", f"{task_rule_forecast:.0f} tasks")
	t_col2.metric("Capacity-adjusted", f"{task_rule_forecast * capacity_ratio:.0f} tasks")
	t_col3.metric("p50", f"{task_mc['p50']:.0f} tasks")
	t_col4.metric("p85", f"{task_mc['p85']:.0f} tasks")
	t_col5.metric("p95", f"{task_mc['p95']:.0f} tasks")

	st.subheader("Story point velocity")
	s_col1, s_col2, s_col3, s_col4, s_col5 = st.columns(5)
	s_col1.metric("Expected velocity", f"{story_points_rule_forecast:.1f} points")
	s_col2.metric("Capacity-adjusted", f"{story_points_rule_forecast * capacity_ratio:.1f} points")
	s_col3.metric("p50", f"{story_points_mc['p50']:.1f} points")
	s_col4.metric("p85", f"{story_points_mc['p85']:.1f} points")
	s_col5.metric("p95", f"{story_points_mc['p95']:.1f} points")

	st.subheader("Closed Issues Per Sprint")
	st.bar_chart(sprint_df, x="Sprint", y="Closed Issues")


def _render_quarterly_tab() -> None:
	st.caption("Estimate feature capacity with simple controls and sample assumptions.")

	quarter_date_col1, quarter_date_col2 = st.columns(2)
	quarter_start = quarter_date_col1.date_input("Quarter start date", value=date.today())
	quarter_end = quarter_date_col2.date_input("Quarter end date", value=date.today())

	settings_col1, settings_col2, settings_col3 = st.columns(3)
	team_size = settings_col1.number_input("Team size", min_value=1, value=5, step=1, key="q_team_size")
	num_sprints = settings_col2.number_input("Number of sprints in quarter", min_value=1, value=6, step=1)
	capacity_reductions = settings_col3.number_input(
		"Total capacity reductions this quarter (days)",
		min_value=0.0,
		value=12.0,
		step=0.5,
	)

	reserve_maintenance = st.checkbox("Reserve 20% for maintenance and support", value=True)
	reserve_project_work = st.checkbox("Reserve 20% for project work / community", value=True)

	sprint_working_days = 10.0
	total_quarter_team_days = float(int(num_sprints) * int(team_size)) * sprint_working_days
	net_quarter_team_days = max(total_quarter_team_days - capacity_reductions, 0.0)
	total_quarter_capacity_sprints = net_quarter_team_days / (float(int(team_size)) * sprint_working_days)

	maintenance_reserved = total_quarter_capacity_sprints * 0.20 if reserve_maintenance else 0.0
	project_reserved = total_quarter_capacity_sprints * 0.20 if reserve_project_work else 0.0
	feature_sprints = max(total_quarter_capacity_sprints - maintenance_reserved - project_reserved, 0.0)

	st.metric("Feature sprints available for new work", f"{feature_sprints:.2f}")
	st.caption(f"Quarter range: {quarter_start} to {quarter_end}")


def _render_monte_carlo_tab() -> None:
	st.caption("Run a robust simulation with editable throughput history.")
	throughput_df = st.data_editor(
		pd.DataFrame({"Throughput": DEFAULT_THROUGHPUT}),
		num_rows="dynamic",
		use_container_width=True,
		key="demo_throughput_df",
	)

	history = [
		int(value)
		for value in throughput_df["Throughput"].dropna().tolist()
		if float(value) >= 0
	]

	if len(history) < 3:
		st.warning("Enter at least 3 throughput values to run simulation.")
		return

	result = robust_monte_carlo(history)
	mc_col1, mc_col2, mc_col3 = st.columns(3)
	mc_col1.metric("p50", f"{result['p50']:.0f} issues")
	mc_col2.metric("p85", f"{result['p85']:.0f} issues")
	mc_col3.metric("p95", f"{result['p95']:.0f} issues")



def main() -> None:
	st.set_page_config(page_title="Capacity Planner Click Dummy", layout="wide")
	st.title("Capacity Planner: Click Dummy")
	st.caption("Portfolio demo mode: full UI walkthrough without local Jira or HR data setup.")

	tab_forecast, tab_quarterly, tab_monte = st.tabs(
		["Sprint Forecast", "Quarterly Planning", "Monte Carlo Throughput"]
	)

	with tab_forecast:
		_render_forecast_tab()
	with tab_quarterly:
		_render_quarterly_tab()
	with tab_monte:
		_render_monte_carlo_tab()


if __name__ == "__main__":
	main()
