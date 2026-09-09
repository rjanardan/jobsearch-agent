"""Policy enforcement for the pipeline.

Filters are data, not prompt text (FR-6): a job that violates policy is
excluded from match *scoring* entirely, and the exclusion reason is recorded.
The policy module is the only place filter rules live; graph nodes and the CLI
never inline filter logic.

Supported filter keys (all optional; absent = no restriction):
  excluded_titles  regex list run against the job title
  countries        job location must reference one of these (word match, so
                   "Indiana, United States" does not count as India)
  employment       allowed employment types; title/level scanned broadly and
                   description for employment-sense markers, unmarked roles
                   are assumed full-time
  locations        legacy metro allow-list (bypassed for remote-flagged roles)
  remote           any | yes | no
  levels           seniority keywords the level field must contain
  comp_min         minimum comp_max in the role's currency
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PolicyResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


# Employment-type markers, per kind as (title/level regex, description regex).
# Title/level is scanned broadly — a "(Contract)" suffix on a title is a real
# employment signal. The description tier is deliberately narrow: bare
# "contract" in a JD is usually testing terminology ("unit, integration,
# contract, and end-to-end tests") or vendor-contract boilerplate, so only
# employment senses (contractor, "contract role/position/to-hire", ...) count.
def _pats(title: str, desc: str | None = None) -> tuple[re.Pattern, re.Pattern]:
    return re.compile(title), re.compile(desc or title)


_EMP_MARKERS: dict[str, tuple[re.Pattern, re.Pattern]] = {
    "part-time": _pats(r"\b(part[ -]?time|half[ -]?time)\b"),
    "contract": _pats(
        r"\b(contract|contractor|freelance|fixed[ -]?term|c2c|temporary)\b",
        r"\b(contractor|contract (role|position|employment|job|basis|to[- ]hire)|"
        r"freelance|fixed[ -]?term|c2c|temporary)\b",
    ),
    "internship": _pats(r"\b(internship|intern)\b"),
}


def _infer_employment(role_text: str, desc_text: str = "") -> str:
    """Full-time unless an explicit counter-marker is present.

    Most ATS postings never state employment type, so absence of a marker
    means full-time. Documented assumption, not a perfect inference.
    """
    for kind, (title_re, desc_re) in _EMP_MARKERS.items():
        if title_re.search(role_text) or desc_re.search(desc_text):
            return kind
    return "full-time"


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

    employment = [e.lower() for e in (filters.get("employment") or [])]
    if employment:
        emp_type = _infer_employment(
            f"{title} {level}", (job.get("description") or "").lower()
        )
        if emp_type not in employment:
            reasons.append(f"employment: role reads as {emp_type}, policy allows {employment}")

    allowed_countries = [c.lower() for c in (filters.get("countries") or [])]
    if allowed_countries:
        if not location:
            reasons.append("country policy: location not stated, cannot verify allowed country")
        elif not any(re.search(rf"\b{re.escape(c)}\b", location) for c in allowed_countries):
            reasons.append(
                f"location '{job.get('location')}' outside allowed countries {allowed_countries}"
            )

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
