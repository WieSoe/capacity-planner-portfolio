"""Capacity planning helpers for sprint forecasting."""

from __future__ import annotations

import random
import statistics


def rule_of_three(sprint_issues: list[int]) -> float:
	"""Return the average closed issues from the last three sprints.

	Args:
		sprint_issues: Closed issue counts from the last 3 sprints.

	Returns:
		Average closed issues as the baseline forecast.

	Raises:
		ValueError: If the list does not contain exactly 3 entries.
	"""
	if len(sprint_issues) != 3:
		raise ValueError("sprint_issues must contain exactly 3 sprint values")

	return float(sum(sprint_issues) / 3)


def net_capacity(
	forecast: float,
	absence_days: float,
	team_size: int,
	sprint_days: int,
) -> float:
	"""Calculate the net sprint capacity percentage after absences.

	Args:
		forecast: Forecasted output (for example from ``rule_of_three``).
		absence_days: Total absence days across the team in the sprint.
		team_size: Number of team members.
		sprint_days: Number of working days in the sprint.

	Returns:
		Net capacity as a percentage where 100 means no capacity loss.

	Raises:
		ValueError: If team size or sprint days are not positive,
			or if absence days are negative.
	"""
	if team_size <= 0:
		raise ValueError("team_size must be greater than 0")
	if sprint_days <= 0:
		raise ValueError("sprint_days must be greater than 0")
	if absence_days < 0:
		raise ValueError("absence_days cannot be negative")

	total_days = float(team_size * sprint_days)
	available_days = max(total_days - absence_days, 0.0)

	if forecast == 0:
		return 0.0

	adjusted_forecast = forecast * (available_days / total_days)
	return float((adjusted_forecast / forecast) * 100.0)


def split_capacity(net: float) -> dict[str, float]:
	"""Split net capacity into planning buckets.

	Allocation:
		- 60% new features
		- 20% maintenance
		- 20% project work / community

	Args:
		net: Net capacity value to split.

	Returns:
		Dictionary with the three capacity buckets.
	"""
	return {
		"new_features": net * 0.60,
		"maintenance": net * 0.20,
		"project_work_community": net * 0.20,
	}


def monte_carlo(historical_issues: list[int], simulations: int = 1000) -> dict[str, float]:
	"""Run a Monte Carlo forecast using historical sprint throughput.

	Note:
		This is a simplified Monte Carlo approach. In this project it is
		typically run with only the last 3 completed sprints, so results
		should be treated as directional rather than statistically robust.

	A random historical value is sampled for each simulation. The resulting
	distribution is summarized as:
		- p50: median (typical forecast)
		- p85: 15th percentile (conservative forecast at 85% confidence)
		- p95: 5th percentile (worst-case forecast at 95% confidence)

	Args:
		historical_issues: Closed issue counts from previous sprints.
		simulations: Number of random samples to generate.

	Returns:
		Dictionary with p50, p85, and p95 forecast values.

	Raises:
		ValueError: If no historical data is provided or simulations < 1.
	"""
	if not historical_issues:
		raise ValueError("historical_issues cannot be empty")
	if simulations < 1:
		raise ValueError("simulations must be at least 1")

	samples = [random.choice(historical_issues) for _ in range(simulations)]
	samples.sort()

	def percentile_rank(percentile: float) -> float:
		index = int(round((len(samples) - 1) * percentile))
		return float(samples[index])

	return {
		"p50": float(statistics.median(samples)),
		"p85": percentile_rank(0.15),
		"p95": percentile_rank(0.05),
	}


def robust_monte_carlo(historical_issues: list[int], simulations: int = 10000) -> dict[str, float]:
	"""Run a statistically robust Monte Carlo forecast using historical throughput.

	This version is recommended when at least 10 completed sprints are available,
	so the simulation reflects a broader and more stable historical baseline.

	A random historical value is sampled for each simulation. The resulting
	distribution is summarized as:
		- p50: median (typical forecast)
		- p85: 15th percentile (conservative forecast at 85% confidence)
		- p95: 5th percentile (worst-case forecast at 95% confidence)

	Args:
		historical_issues: Closed issue counts from previous sprints.
		simulations: Number of random samples to generate.

	Returns:
		Dictionary with p50, p85, and p95 forecast values.

	Raises:
		ValueError: If no historical data is provided or simulations < 1.
	"""
	if not historical_issues:
		raise ValueError("historical_issues cannot be empty")
	if simulations < 1:
		raise ValueError("simulations must be at least 1")

	samples = [random.choice(historical_issues) for _ in range(simulations)]
	samples.sort()

	def percentile_rank(percentile: float) -> float:
		index = int(round((len(samples) - 1) * percentile))
		return float(samples[index])

	return {
		"p50": float(statistics.median(samples)),
		"p85": percentile_rank(0.15),
		"p95": percentile_rank(0.05),
	}


def quarterly_forecast(
	sprint_forecast: float,
	num_sprints: int = 6,
	absence_days: float = 0.0,
	team_size: int = 1,
	sprint_days: int = 10,
) -> dict[str, float | int]:
	"""Forecast quarterly feature planning capacity for Engineering Managers.

	Calculation flow:
		1. Compute quarter total capacity from sprint forecast and sprint count.
		2. Apply ``net_capacity`` to get the capacity percentage after absences.
		3. Apply ``split_capacity`` and use the 60% new-feature allocation.
		4. Convert feature capacity to sprint-equivalents (``feature_sprints``).

	Args:
		sprint_forecast: Forecasted total capacity per sprint.
		num_sprints: Number of sprints in the quarter.
		absence_days: Total team absence days in the quarter.
		team_size: Number of team members.
		sprint_days: Number of working days per sprint.

	Returns:
		Dictionary with:
			- num_sprints
			- total_capacity
			- net_capacity_percent
			- feature_sprints

	Raises:
		ValueError: If sprint_forecast is negative or num_sprints < 1.
	"""
	if sprint_forecast < 0:
		raise ValueError("sprint_forecast cannot be negative")
	if num_sprints < 1:
		raise ValueError("num_sprints must be at least 1")

	total_capacity = float(sprint_forecast * num_sprints)
	net_capacity_percent = net_capacity(
		forecast=total_capacity,
		absence_days=absence_days,
		team_size=team_size,
		sprint_days=sprint_days * num_sprints,
	)

	net_total_capacity = total_capacity * (net_capacity_percent / 100.0)
	feature_capacity = split_capacity(net_total_capacity)["new_features"]
	feature_sprints = 0.0 if sprint_forecast == 0 else float(feature_capacity / sprint_forecast)

	return {
		"num_sprints": num_sprints,
		"total_capacity": total_capacity,
		"net_capacity_percent": net_capacity_percent,
		"feature_sprints": feature_sprints,
	}
