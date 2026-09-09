"""ATS board adapters: Greenhouse, Lever, Ashby public JSON APIs.

Board tokens map to company careers pages (config/companies.yaml).
Greenhouse list responses omit job descriptions unless ?content=true is
passed; descriptions feed the matcher and artifact stages, so they are
fetched with the list in one round trip.
"""

from __future__ import annotations

import httpx

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{board}?mode=json"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def _clean_html(html: str | None) -> str:
    """Crude but sufficient HTML→text for job descriptions (entities + tags)."""
    import html as _html
    import re

    text = _html.unescape(html or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(p|div|li|h\d|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _gh(client: httpx.Client, board: str) -> list[dict]:
    resp = client.get(GREENHOUSE.format(board=board), timeout=30)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    return [
        {
            "source": "ats:greenhouse",
            "source_id": f"gh:{board}:{j['id']}",
            "company": _board_name(board),
            "title": j.get("title"),
            "location": (j.get("location") or {}).get("name") if isinstance(j.get("location"), dict) else None,
            "url": j.get("absolute_url"),
            "posted_at": j.get("updated_at"),
            "description": _clean_html(j.get("content")),
        }
        for j in jobs
    ]


def _lever(client: httpx.Client, board: str) -> list[dict]:
    resp = client.get(LEVER.format(board=board), timeout=30)
    resp.raise_for_status()
    jobs = resp.json()
    out = []
    for j in jobs:
        cat = j.get("categories") or {}
        out.append(
            {
                "source": "ats:lever",
                "source_id": f"lever:{board}:{j.get('id')}",
                "company": _board_name(board),
                "title": j.get("text"),
                "location": cat.get("location"),
                "url": j.get("hostedUrl"),
                "posted_at": j.get("createdAt"),
                "description": _clean_html(j.get("description") or j.get("descriptionPlain")),
            }
        )
    return out


def _ashby(client: httpx.Client, board: str) -> list[dict]:
    resp = client.get(ASHBY.format(board=board), timeout=30)
    resp.raise_for_status()
    jobs = resp.json().get("jobs", [])
    out = []
    for j in jobs:
        comp = (j.get("compensation") or {}).get("compensationTierSummary") if isinstance(j.get("compensation"), dict) else None
        out.append(
            {
                "source": "ats:ashby",
                "source_id": f"ashby:{board}:{j.get('id')}",
                "company": _board_name(board),
                "title": j.get("title"),
                "location": j.get("location") or (j.get("secondaryLocations") or [None])[0],
                "url": j.get("jobUrl"),
                "posted_at": j.get("publishedAt"),
                "description": _clean_html(j.get("descriptionHtml") or j.get("descriptionPlain")),
                "raw_text": f"remote={j.get('isRemote')} employment={j.get('employmentType')} comp={comp}",
            }
        )
    return out


_BOARD_CACHE: dict[str, str] = {}


def _board_name(board: str) -> str:
    """Board tokens are usually the company slug; prettify by capitalizing."""
    if board not in _BOARD_CACHE:
        _BOARD_CACHE[board] = board.replace("-", " ").title()
    return _BOARD_CACHE[board]


def fetch_ats(companies: list[dict]) -> list[dict]:
    """Fetch jobs for all ATS-type companies. One failing company is logged, not fatal."""
    out: list[dict] = []
    errors: list[str] = []
    with httpx.Client() as client:
        for c in companies:
            ctype = (c.get("careers_type") or "").lower()
            board = c.get("slug")
            if not board:
                continue
            try:
                if ctype == "greenhouse":
                    out.extend(_gh(client, board))
                elif ctype == "lever":
                    out.extend(_lever(client, board))
                elif ctype == "ashby":
                    out.extend(_ashby(client, board))
            except Exception as exc:  # noqa: BLE001 - per-company degradation (NFR-6)
                errors.append(f"{board}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    return out
