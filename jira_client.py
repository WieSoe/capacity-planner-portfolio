"""Jira API client helpers for sprint completion metrics.

This module loads credentials from a .env file and fetches the last completed
sprints for a given board ID, including completed story points and the number
of closed issues in each sprint.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

COUNTABLE_ISSUE_TYPES = ["Task", "Bug", "Spike", "Technical Debt", "Security Vulnerability"]


@dataclass
class SprintMetrics:
	"""Normalized sprint metrics returned by this module."""

	sprint_id: int
	sprint_name: str
	state: str
	start_date: str | None
	end_date: str | None
	complete_date: str | None
	closed_issues: int
	completed_story_points: float


class JiraClient:
	"""Lightweight Jira Agile API client for sprint analytics."""

	def __init__(
		self,
		base_url: str | None = None,
		email: str | None = None,
		api_token: str | None = None,
		project_key: str | None = None,
		timeout_seconds: int = 30,
		story_points_field: str | None = None,
	) -> None:
		self.base_url = (base_url or os.getenv("JIRA_BASE_URL", "")).rstrip("/")
		self.email = email or os.getenv("JIRA_EMAIL", "")
		self.api_token = api_token or os.getenv("JIRA_API_TOKEN", "")
		self.project_key = project_key or os.getenv("JIRA_PROJECT_KEY", "ALPHA")
		self.timeout_seconds = timeout_seconds
		self.story_points_field = story_points_field or "customfield_10016"

		missing: list[str] = []
		if not self.base_url:
			missing.append("JIRA_BASE_URL")
		if not self.email:
			missing.append("JIRA_EMAIL")
		if not self.api_token:
			missing.append("JIRA_API_TOKEN")
		if missing:
			missing_joined = ", ".join(missing)
			raise ValueError(f"Missing required environment variables: {missing_joined}")

		self.session = requests.Session()
		self.session.auth = HTTPBasicAuth(self.email, self.api_token)
		self.session.headers.update(
			{
				"Accept": "application/json",
				"Content-Type": "application/json",
			}
		)

	def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
		response = self.session.get(
			f"{self.base_url}{path}",
			params=params,
			timeout=self.timeout_seconds,
		)
		response.raise_for_status()
		return response.json()

	def _get_closed_sprints(self, board_id: int) -> list[dict[str, Any]]:
		sprints: list[dict[str, Any]] = []
		start_at = 0
		max_results = 50

		while True:
			payload = self._get(
				f"/rest/agile/1.0/board/{board_id}/sprint",
				params={
					"state": "closed",
					"startAt": start_at,
					"maxResults": max_results,
				},
			)
			values = payload.get("values", [])
			sprints.extend(values)

			if payload.get("isLast", False):
				break

			start_at += payload.get("maxResults", max_results)

		sprints.sort(
			key=lambda sprint: _parse_date(sprint.get("completeDate"))
			or _parse_date(sprint.get("endDate"))
			or datetime.min,
			reverse=True,
		)
		return sprints

	def _get_completed_issues(self, sprint_id: int) -> list[dict[str, Any]]:
		issues: list[dict[str, Any]] = []
		start_at = 0
		max_results = 100
		
		issue_types_str = ", ".join(f'"{it}"' for it in COUNTABLE_ISSUE_TYPES)
		jql = f"project = {self.project_key} AND issueType in ({issue_types_str}) AND statusCategory = Done"

		while True:
			payload = self._get(
				f"/rest/agile/1.0/sprint/{sprint_id}/issue",
				params={
					"jql": jql,
					"fields": self.story_points_field,
					"startAt": start_at,
					"maxResults": max_results,
				},
			)
			page_issues = payload.get("issues", [])
			issues.extend(page_issues)

			total = payload.get("total", 0)
			fetched = len(issues)
			if fetched >= total:
				break

			start_at += payload.get("maxResults", max_results)

		return issues

	def fetch_last_completed_sprints(
		self, board_id: int, sprint_count: int = 3
	) -> list[dict[str, Any]]:
		"""Fetch the latest closed sprints and aggregate completion metrics."""
		closed_sprints = self._get_closed_sprints(board_id)
		selected_sprints = closed_sprints[:sprint_count]
		results: list[dict[str, Any]] = []

		for sprint in selected_sprints:
			sprint_id = sprint["id"]
			completed_issues = self._get_completed_issues(sprint_id)
			story_points = sum(
				float(issue.get("fields", {}).get(self.story_points_field) or 0)
				for issue in completed_issues
			)

			metrics = SprintMetrics(
				sprint_id=sprint_id,
				sprint_name=sprint.get("name", "Unknown Sprint"),
				state=sprint.get("state", "unknown"),
				start_date=sprint.get("startDate"),
				end_date=sprint.get("endDate"),
				complete_date=sprint.get("completeDate"),
				closed_issues=len(completed_issues),
				completed_story_points=story_points,
			)
			results.append(asdict(metrics))

		return results

	def fetch_throughput_history(self, board_id: int, sprint_count: int = 20) -> list[int]:
		"""Fetch closed issue throughput for the latest completed sprints."""
		closed_sprints = self._get_closed_sprints(board_id)
		selected_sprints = closed_sprints[:sprint_count]
		throughput_history: list[int] = []

		for sprint in selected_sprints:
			sprint_id = sprint["id"]
			completed_issues = self._get_completed_issues(sprint_id)
			throughput_history.append(len(completed_issues))

		return throughput_history


def fetch_last_completed_sprints(board_id: int, sprint_count: int = 3, project_key: str | None = None, story_points_field: str | None = None) -> list[dict[str, Any]]:
	"""Convenience function for fetching sprint metrics without manual client setup."""
	client = JiraClient(project_key=project_key, story_points_field=story_points_field)
	return client.fetch_last_completed_sprints(board_id=board_id, sprint_count=sprint_count)


def fetch_throughput_history(board_id: int, sprint_count: int = 20, project_key: str | None = None, story_points_field: str | None = None) -> list[int]:
	"""Convenience function for fetching historical closed-issue throughput."""
	client = JiraClient(project_key=project_key, story_points_field=story_points_field)
	return client.fetch_throughput_history(board_id=board_id, sprint_count=sprint_count)


def _parse_date(value: str | None) -> datetime | None:
	if not value:
		return None
	try:
		return datetime.fromisoformat(value.replace("Z", "+00:00"))
	except ValueError:
		return None


if __name__ == "__main__":
	board_id_raw = os.getenv("JIRA_BOARD_ID", "")
	if not board_id_raw:
		raise ValueError("Set JIRA_BOARD_ID in your .env file to run this module directly.")

	board_id = int(board_id_raw)
	data = fetch_last_completed_sprints(board_id=board_id, sprint_count=3)
	for sprint in data:
		print(sprint)
