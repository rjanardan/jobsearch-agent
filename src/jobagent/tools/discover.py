"""Discovery orchestration: fetch -> extract -> normalize -> persist (FR-3..5)."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from jobagent.adapters import ats, hn, rss
from jobagent.store.jobs import touch_source, upsert_jobs

_STRUCTURED_SOURCES = {"ats:greenhouse", "ats:lever", "ats:ashby"}


def _fingerprint(bucket: str, raw: dict, extracted: dict | None) -> str:
    """Cross-source fingerprint when company+title+location known; else source-keyed."""
    company = (extracted or {}).get("company") or raw.get("company")
    title = (extracted or {}).get("title") or raw.get("title")
    location = (extracted or {}).get("location") or raw.get("location")
    if company and title:
        key = f"{str(company).lower()}|{str(title).lower()}|{location or ''}"
        return hashlib.sha1(key.encode()).hexdigest()
    return hashlib.sha1(f"{bucket}|{raw['source_id']}".encode()).hexdigest()


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _needs_extraction(raw: dict) -> bool:
    return "raw_text" in raw and raw.get("source") not in _STRUCTURED_SOURCES


def _ingest(session: Session, raw_listings: list[dict], bucket: str, summary: dict) -> None:
    """Extract (when needed, in parallel), normalize, upsert, record health."""
    fetched = len(raw_listings)

    # Local-LLM extraction for unstructured sources (HN, RSS). Serialized:
    # ollama serves one generation slot (-np 1); concurrent requests wedged
    # its scheduler, so one worker is both safer and no slower.
    if any(_needs_extraction(r) for r in raw_listings):
        from jobagent.tools.extract import extract_listing

        def _extract(raw: dict) -> tuple[dict, dict | None]:
            if _needs_extraction(raw):
                return raw, extract_listing(raw["raw_text"])
            return raw, None

        with ThreadPoolExecutor(max_workers=1) as pool:
            pairs = list(pool.map(_extract, raw_listings))
    else:
        pairs = [(r, None) for r in raw_listings]

    normalized: list[dict] = []
    for raw, extracted in pairs:
        if extracted is None and _needs_extraction(raw):
            continue  # classified as non-job or extraction failed
        remote_raw = (extracted or {}).get("remote") if extracted else None
        normalized.append(
            {
                "source": raw["source"] if raw.get("source") else bucket,
                "source_id": raw.get("source_id"),
                "fingerprint": _fingerprint(bucket, raw, extracted),
                "title": (extracted or {}).get("title") or raw.get("title") or "untitled",
                "company_name": (extracted or {}).get("company") if extracted else raw.get("company"),
                "location": (extracted or {}).get("location") if extracted else raw.get("location"),
                "remote": "yes" if remote_raw == "yes" else "no" if remote_raw == "no" else None,
                "level": (extracted or {}).get("level") if extracted else raw.get("level"),
                "url": (extracted or {}).get("url") if extracted else raw.get("url"),
                "posted_at": _parse_date(raw.get("posted_at")),
                "raw": raw if len(str(raw)) < 2000 else {"truncated": True},
                "active": True,
            }
        )
    result = upsert_jobs(session, normalized)
    touch_source(session, bucket, ok=True, cursor=str(fetched))
    summary[bucket] = {"fetched": fetched, **result}


def run_discovery(session: Session, sources_cfg: dict, companies: list[dict]) -> dict:
    """Run every enabled source; a failing source is recorded, never fatal."""
    summary: dict[str, dict] = {}
    client = httpx.Client(timeout=30)

    hn_cfg = sources_cfg.get("discovery", {}).get("hn_whoishiring", {})
    if hn_cfg.get("enabled", True):
        print("discover: hn fetch+extract...", flush=True)
        try:
            thread_id = hn.latest_hiring_thread_id(client)
            raw = hn.fetch_thread_comments(client, thread_id, limit=hn_cfg.get("max_comments", 12))
            _ingest(session, raw, "hn", summary)
            print(f"discover: hn done -> {summary.get('hn', {}).get('inserted', 0)} new", flush=True)
        except Exception as exc:  # noqa: BLE001
            touch_source(session, "hn", ok=False, error=str(exc))
            summary["hn"] = {"error": str(exc)}
            print(f"discover: hn failed: {exc}", flush=True)
    client.close()

    rss_cfg = sources_cfg.get("discovery", {}).get("rss", {})
    if rss_cfg.get("enabled") and rss_cfg.get("feeds"):
        for feed_url in rss_cfg["feeds"]:
            print(f"discover: rss {feed_url}...", flush=True)
            try:
                raw = rss.fetch_feed(feed_url, limit=rss_cfg.get("limit", 10))
                _ingest(session, raw, "rss", summary)
                print(f"discover: rss done -> {summary.get('rss', {}).get('inserted', 0)} new", flush=True)
            except Exception as exc:  # noqa: BLE001
                touch_source(session, "rss", ok=False, error=str(exc))
                summary["rss"] = {"error": str(exc)}
                print(f"discover: rss failed: {exc}", flush=True)

    ats_cfg = sources_cfg.get("ats_scan", {})
    if ats_cfg.get("enabled", True):
        ats_companies = [c for c in companies if c.get("careers_type") in {"greenhouse", "lever", "ashby"}]
        print("discover: ats scan...", flush=True)
        try:
            raw = ats.fetch_ats(ats_companies)
            _ingest(session, raw, "ats", summary)
            print(f"discover: ats done -> {summary.get('ats', {}).get('inserted', 0)} new", flush=True)
        except Exception as exc:  # noqa: BLE001
            touch_source(session, "ats", ok=False, error=str(exc))
            summary["ats"] = {"error": str(exc)}
            print(f"discover: ats failed: {exc}", flush=True)
    return summary
