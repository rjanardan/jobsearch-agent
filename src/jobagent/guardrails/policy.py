"""Policy enforcement for the pipeline.

Filters are data, not prompt text (FR-6): a job that violates policy is
excluded from match *scoring* entirely, and the exclusion reason is recorded.
The policy module is the only place filter rules live; graph nodes and the CLI
never inline filter logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PolicyResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def apply_policy(job: dict, filters: dict | None) -> PolicyResult:
    """Evaluate one normalized job dict against the filter policy.

    `filters` mirrors config/filters.yaml; every key is optional and absent
    keys mean "no restriction". Unknown filter keys are ignored (forward
    compatibility). A job is rejected on the first violated rule.
    """
    filters = filters or {}
    reasons: list[str] = []
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    level = (job.get("level") or "").lower()

    for pattern in filters.get("excluded_titles", []) or []:
        if re.search(pattern.lower(), title):
            reasons.append(f"title excluded by policy ({pattern})")

    allowed_locations = filters.get("locations") or []
    if allowed_locations and location and not any(
        metro.lower() in location for metro in allowed_locations
    ) and job.get("remote") != "yes":
        reasons.append(f"location '{job.get('location')}' outside allowed metros")

    remote_rule = (filters.get("remote") or "any").lower()
    if remote_rule == "yes" and job.get("remote") != "yes":
        reasons.append("remote-only policy, role is not remote")
    elif remote_rule == "no" and job.get("remote") == "yes":
        reasons.append("onsite-only policy, role is remote")

    allowed_levels = filters.get("levels") or []
    if allowed_levels and level and not any(lv.lower() in level for lv in allowed_levels):
        reasons.append(f"level '{job.get('level')}' outside allowed levels")

    comp_floor = filters.get("comp_min")
    if comp_floor is not None and job.get("comp_max") is not None and job["comp_max"] < comp_floor:
        reasons.append(f"comp max below policy floor ({comp_floor})")

    return PolicyResult(allowed=not reasons, reasons=reasons)
