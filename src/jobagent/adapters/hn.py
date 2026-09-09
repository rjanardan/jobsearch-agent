"""Hacker News "who is hiring" adapter via the public Algolia API."""

from __future__ import annotations

import httpx

ALGOLIA = "https://hn.algolia.com/api/v1"


def latest_hiring_thread_id(client: httpx.Client) -> int:
    """Find the newest 'Who is hiring?' story."""
    resp = client.get(
        f"{ALGOLIA}/search",
        params={"query": "Who is hiring", "tags": "story", "hitsPerPage": 5},
    )
    resp.raise_for_status()
    hits = resp.json()["hits"]
    # newest first by created_at; prefer current month
    return int(hits[0]["objectID"])


def fetch_thread_comments(client: httpx.Client, item_id: int, limit: int = 30) -> list[dict]:
    """Fetch the thread and flatten top-level comments into raw listings."""
    resp = client.get(f"{ALGOLIA}/items/{item_id}", timeout=30)
    resp.raise_for_status()
    item = resp.json()
    out: list[dict] = []
    for child in item.get("children", []):
        text = (child.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "source": "hn",
                "source_id": f"hn:{child.get('id', item_id)}",
                "raw_text": text,
                "posted_at": child.get("created_at"),
                "url": None,
            }
        )
        if len(out) >= limit:
            break
    return out
