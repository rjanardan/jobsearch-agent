"""RSS job-feed adapter (feedparser)."""

from __future__ import annotations

import hashlib

import feedparser

JOB_POST_MARKERS = ("hiring", "is looking for", "@", "careers", "position", "role")


def fetch_feed(feed_url: str, limit: int = 20) -> list[dict]:
    parsed = feedparser.parse(feed_url)
    out: list[dict] = []
    for entry in parsed.entries[:limit]:
        title = (entry.get("title") or "").strip()
        link = entry.get("link") or entry.get("id") or ""
        if not title or not any(m in title.lower() for m in JOB_POST_MARKERS):
            continue
        out.append(
            {
                "source": "rss",
                "source_id": f"rss:{hashlib.sha1((feed_url + title).encode()).hexdigest()[:16]}",
                "raw_text": title,
                "posted_at": entry.get("published") or entry.get("updated"),
                "url": link,
                "extra": {"feed": feed_url},
            }
        )
    return out
