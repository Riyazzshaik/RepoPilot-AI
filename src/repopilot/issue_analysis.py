"""Explainable, deterministic issue analysis."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Iterable

from repopilot.config import LONG_OPEN_ISSUE_DAYS
from repopilot.github.models import IssueInfo

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("security", ("security", "vulnerability", "cve")),
    ("bug", ("bug", "defect", "error", "failure", "regression")),
    ("feature", ("feature", "enhancement", "proposal")),
    ("documentation", ("documentation", "docs", "doc")),
    ("performance", ("performance", "optimization", "slow")),
    ("dependency", ("dependency", "dependencies", "deps")),
    ("question", ("question", "help", "support")),
)

_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("errors and failures", ("error", "exception", "failure", "crash")),
    ("documentation", ("docs", "documentation", "readme")),
    ("performance", ("slow", "latency", "performance", "optimization")),
    ("dependencies", ("dependency", "dependencies", "upgrade", "version")),
    ("authentication and access", ("auth", "login", "permission", "token")),
)


def analyze_issues(
    issues: Iterable[IssueInfo],
    *,
    now: datetime | None = None,
    long_open_days: int = LONG_OPEN_ISSUE_DAYS,
) -> dict[str, Any]:
    """Return findings whose rules and evidence can be inspected by callers."""
    if long_open_days < 1:
        raise ValueError("long_open_days must be at least 1")
    issue_list = list(issues)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    long_open_cutoff = current - timedelta(days=long_open_days)
    assessments: list[dict[str, Any]] = []
    no_label_numbers: list[int] = []
    long_open_numbers: list[int] = []
    category_counts: Counter[str] = Counter()
    theme_counts: Counter[str] = Counter()

    for issue in issue_list:
        category = _categorize(issue)
        category_counts[category] += 1
        text = f"{issue.title} {issue.body or ''}".lower()
        themes = [theme for theme, keywords in _THEME_RULES if any(_contains_term(text, keyword) for keyword in keywords)]
        theme_counts.update(themes)
        no_labels = not issue.labels
        is_long_open = issue.state.lower() == "open" and _parse_timestamp(issue.created_at) <= long_open_cutoff
        if no_labels:
            no_label_numbers.append(issue.number)
        if is_long_open:
            long_open_numbers.append(issue.number)
        assessments.append(
            {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "category": category,
                "labels": list(issue.labels),
                "themes": themes,
                "no_labels": no_labels,
                "long_open": is_long_open,
                "evidence_url": issue.html_url,
            }
        )

    recurring_themes = [
        {"theme": theme, "issue_count": count}
        for theme, count in theme_counts.most_common()
        if count >= 2
    ]
    recommendations: list[dict[str, Any]] = []
    if no_label_numbers:
        recommendations.append({
            "action": "triage_unlabeled_issues",
            "reason": "Assign labels so issue ownership and prioritization are easier to review.",
            "issue_numbers": no_label_numbers,
        })
    if long_open_numbers:
        recommendations.append({
            "action": "review_long_open_issues",
            "reason": f"Review open issues older than {long_open_days} days for stale status, blockers, or prioritization.",
            "issue_numbers": long_open_numbers,
        })
    for theme in recurring_themes:
        recommendations.append({
            "action": "group_recurring_theme",
            "reason": f"Investigate recurring theme '{theme['theme']}' before opening more duplicate work.",
            "issue_count": theme["issue_count"],
        })
    return {
        "issue_count": len(issue_list),
        "open_count": sum(issue.state.lower() == "open" for issue in issue_list),
        "closed_count": sum(issue.state.lower() == "closed" for issue in issue_list),
        "category_counts": dict(category_counts),
        "recurring_themes": recurring_themes,
        "unlabeled_issue_numbers": no_label_numbers,
        "long_open_issue_numbers": long_open_numbers,
        "assessments": assessments,
        "recommendations": recommendations,
        "analysis_method": "Deterministic labels, keyword rules, issue state, and creation timestamps; not an AI prediction.",
    }


def _categorize(issue: IssueInfo) -> str:
    labels = " ".join(issue.labels).lower()
    for category, keywords in _CATEGORY_RULES:
        if any(_contains_term(labels, keyword) for keyword in keywords):
            return category
    text = f"{issue.title} {issue.body or ''}".lower()
    for category, keywords in _CATEGORY_RULES:
        if any(_contains_term(text, keyword) for keyword in keywords):
            return category
    return "uncategorized"


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid issue timestamp: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
