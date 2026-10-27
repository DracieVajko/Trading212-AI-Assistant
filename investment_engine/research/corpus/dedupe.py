"""Phase 5 deduplication: canonical URLs + fuzzy titles, first-seen wins."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

_TRACKER_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "u",
})


def normalize_url(url: str) -> str:
    """Lowercase host, drop query/fragment/trackers and trailing slash."""
    text = (url or "").strip()
    try:
        parts = urlparse(text)
    except Exception:
        return text.lower()
    host = (parts.hostname or "").lower()
    path = (parts.path or "").rstrip("/") or "/"
    query = "&".join(
        p for p in (parts.query or "").split("&")
        if p and p.split("=")[0].lower() not in _TRACKER_PARAMS)
    norm = f"{parts.scheme.lower()}://{host}{path}"
    if query:
        norm += f"?{query}"
    return norm


def item_id(url: str) -> str:
    return hashlib.md5(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def _tokens(title: str) -> set[str]:
    return set(t for t in re.findall(r"[a-z0-9]{3,}", (title or "").lower()))


def titles_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """Token-Jaccard similarity on 3+ char tokens."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def dedupe(items: list[dict]) -> list[dict]:
    """First-seen wins on canonical URL; fuzzy-title collapse across URLs.

    Dropped syndicated copies are NOT independent confirmations, but their
    publishers are merged into the kept item's ``event_sources`` so the
    corroboration count reflects every observed copy. Drop behavior itself
    is unchanged (first-seen wins).
    """
    seen_ids: set[str] = set()
    kept_titles: list[str] = []
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        uid = item.get("id") or item_id(str(item.get("canonical_url", "")))
        if uid in seen_ids:
            continue
        title = str(item.get("title", ""))
        match_idx = next((i for i, kept in enumerate(kept_titles)
                          if titles_similar(title, kept)), None)
        if match_idx is not None:
            # Syndicated copy: merge its publisher into the kept item.
            try:
                kept = out[match_idx]
                pub = str(item.get("publisher") or "").strip()
                sources = kept.setdefault("event_sources", [])
                if pub and pub not in sources:
                    sources.append(pub)
                kept["corroboration"] = len(sources) or 1
            except Exception:
                pass
            continue
        seen_ids.add(uid)
        kept_titles.append(title)
        out.append(item)
    assign_events(out)
    return out


def _event_entities(item: dict) -> set[str]:
    tags = {str(t or "").strip().upper() for t in (item.get("ticker_tags") or []) if t}
    queried = str(item.get("queried_for") or "").strip().upper()
    if queried:
        tags.add(f"Q:{queried}")
    return tags


def assign_events(items: list[dict]) -> list[dict]:
    """Group items into events in place. Returns the same list.

    Same event = similar titles AND overlapping entity sets. Each group gets
    ``event_id`` (first item's id), ``corroboration`` (independent publisher
    count) and ``event_sources`` (publisher list). Never raises.
    """
    try:
        groups: list[dict] = []  # {key_title, entities, members}
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", ""))
            entities = _event_entities(item)
            placed = False
            for group in groups:
                if titles_similar(title, group["key_title"]) and (entities & group["entities"]):
                    group["members"].append(item)
                    group["entities"] |= entities
                    placed = True
                    break
            if not placed:
                groups.append({"key_title": title, "entities": set(entities), "members": [item]})
        for group in groups:
            members = group["members"]
            event_id = str(members[0].get("id") or "") if members else ""
            publishers: list[str] = []
            for member in members:
                # Seed with sources already merged from dropped syndicated
                # copies (dedupe merges publishers before dropping).
                for s in (member.get("event_sources") or []):
                    if s and s not in publishers:
                        publishers.append(s)
                pub = str(member.get("publisher") or distributor_origin(member) or "unknown").strip()
                if pub and pub not in publishers:
                    publishers.append(pub)
            for member in members:
                try:
                    member["event_id"] = event_id
                    member["corroboration"] = len(publishers)
                    member["event_sources"] = list(publishers)
                except Exception:
                    continue
    except Exception:
        pass
    return items


def distributor_origin(item: dict) -> str:
    """Origin publisher when a distributor carried the story."""
    try:
        return str(item.get("publisher") or "").strip()
    except Exception:
        return ""
