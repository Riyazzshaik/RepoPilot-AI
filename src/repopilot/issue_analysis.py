"""Explainable, deterministic issue analysis."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
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

_PRIORITY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("critical", ("p0", "critical", "urgent")),
    ("high", ("p1", "high")),
    ("medium", ("p2", "medium")),
    ("low", ("p3", "low")),
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
        created_at = _parse_timestamp(issue.created_at)
        updated_at = _parse_timestamp(issue.updated_at) if issue.updated_at else created_at
        age_days = max(0, (current - created_at).days)
        inactivity_days = max(0, (current - updated_at).days)
        is_long_open = issue.state.lower() == "open" and age_days >= long_open_days
        is_stale = issue.state.lower() == "open" and (
            age_days >= long_open_days or inactivity_days >= long_open_days
        )
        priority, priority_evidence = _priority(issue.labels)
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
                "stale": is_stale,
                "age_days": age_days,
                "inactivity_days": inactivity_days,
                "priority": priority,
                "priority_evidence": priority_evidence,
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
            "issue_urls": [_issue_url(issue_list, number) for number in no_label_numbers],
        })
    if long_open_numbers:
        recommendations.append({
            "action": "review_long_open_issues",
            "reason": f"Review open issues older than {long_open_days} days for stale status, blockers, or prioritization.",
            "issue_numbers": long_open_numbers,
            "issue_urls": [_issue_url(issue_list, number) for number in long_open_numbers],
        })
    priority_numbers = [item["number"] for item in assessments if item["priority"] in {"critical", "high"}]
    if priority_numbers:
        recommendations.append({
            "action": "review_explicit_priority",
            "reason": "Review issues carrying explicit high or critical priority labels before lower-priority work.",
            "issue_numbers": priority_numbers,
            "issue_urls": [_issue_url(issue_list, number) for number in priority_numbers],
        })
    for theme in recurring_themes:
        recommendations.append({
            "action": "group_recurring_theme",
            "reason": f"Investigate recurring theme '{theme['theme']}' before opening more duplicate work.",
            "issue_count": theme["issue_count"],
        })
    duplicate_candidates = _duplicate_candidates(issue_list)
    for candidate in duplicate_candidates:
        recommendations.append({
            "action": "review_duplicate_candidate",
            "reason": "Compare these similar issues and consolidate only after human review confirms they describe the same problem.",
            "issue_numbers": candidate["issue_numbers"],
            "issue_urls": candidate["evidence_urls"],
            "similarity": candidate["similarity"],
        })
    return {
        "issue_count": len(issue_list),
        "open_count": sum(issue.state.lower() == "open" for issue in issue_list),
        "closed_count": sum(issue.state.lower() == "closed" for issue in issue_list),
        "category_counts": dict(category_counts),
        "recurring_themes": recurring_themes,
        "unlabeled_issue_numbers": no_label_numbers,
        "long_open_issue_numbers": long_open_numbers,
        "stale_issue_numbers": [item["number"] for item in assessments if item["stale"]],
        "priority_counts": dict(Counter(item["priority"] for item in assessments if item["priority"])),
        "duplicate_candidates": duplicate_candidates,
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


def _priority(labels: tuple[str, ...]) -> tuple[str | None, str | None]:
    for priority, keywords in _PRIORITY_RULES:
        for label in labels:
            normalized = label.lower().replace("-", " ").replace("_", " ")
            if any(_contains_term(normalized, keyword) for keyword in keywords):
                return priority, f"label:{label}"
    return None, None


def _duplicate_candidates(issues: list[IssueInfo]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, left in enumerate(issues):
        left_title = _normalize_text(left.title)
        left_text = _normalize_text(f"{left.title} {left.body or ''}")
        for right in issues[index + 1 :]:
            title_similarity = SequenceMatcher(None, left_title, _normalize_text(right.title)).ratio()
            text_similarity = SequenceMatcher(
                None,
                left_text,
                _normalize_text(f"{right.title} {right.body or ''}"),
            ).ratio()
            similarity = max(title_similarity, text_similarity)
            if title_similarity >= 0.82 or text_similarity >= 0.78:
                candidates.append({
                    "issue_numbers": [left.number, right.number],
                    "similarity": round(similarity, 3),
                    "title_similarity": round(title_similarity, 3),
                    "text_similarity": round(text_similarity, 3),
                    "evidence_urls": [left.html_url, right.html_url],
                })
    return candidates


def _normalize_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _issue_url(issues: list[IssueInfo], number: int) -> str | None:
    return next((issue.html_url for issue in issues if issue.number == number), None)


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid issue timestamp: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
