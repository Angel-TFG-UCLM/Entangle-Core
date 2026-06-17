"""
One-shot: re-fetch README text for repos that were truncated to ~1000 chars
under the old limit. Uses the GitHub REST API directly so we don't go through
the full enrichment pipeline.

After this script finishes:
    python -m src.ai.indexer --force      # re-index everything

Usage:
    python -m scripts.refresh_truncated_readmes [--limit N] [--dry-run] [--min-len 990]
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

# Allow running with `python -m scripts.refresh_truncated_readmes`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

from src.core.db import get_collection
from src.core.logger import logger


GITHUB_BASE = "https://api.github.com"
REQUEST_TIMEOUT_S = 15


def _gh_headers() -> Dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_readme(full_name: str) -> Optional[str]:
    url = f"{GITHUB_BASE}/repos/{full_name}/readme"
    resp = requests.get(url, headers=_gh_headers(), timeout=REQUEST_TIMEOUT_S)
    if resp.status_code == 200:
        content = base64.b64decode(resp.json().get("content", "")).decode("utf-8", errors="replace")
        return content or None
    if resp.status_code == 404:
        return None
    if resp.status_code == 403:
        # Rate limit; surface so caller can wait/back off
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        reset = resp.headers.get("X-RateLimit-Reset", "?")
        raise RuntimeError(f"GitHub rate limit (remaining={remaining}, reset={reset})")
    resp.raise_for_status()
    return None


def main():
    parser = argparse.ArgumentParser(description="Refresh truncated READMEs from GitHub")
    parser.add_argument("--limit", type=int, default=None, help="Max repos to process")
    parser.add_argument("--min-len", type=int, default=990,
                        help="Treat readme_text >= this length as truncated (default 990)")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes")
    args = parser.parse_args()

    coll = get_collection("repositories")

    # Filter: readme_text exists and is "suspiciously long" (truncated to ~1000)
    pipeline = [
        {"$match": {"readme_text": {"$exists": True, "$ne": None, "$type": "string"}}},
        {"$project": {
            "_id": 0, "id": 1, "full_name": 1, "name": 1,
            "len": {"$strLenCP": "$readme_text"},
        }},
        {"$match": {"len": {"$gte": args.min_len}}},
    ]
    if args.limit:
        pipeline.append({"$limit": args.limit})

    candidates = list(coll.aggregate(pipeline))
    logger.info("Found %d candidates with readme_text >= %d chars",
                len(candidates), args.min_len)

    stats = {"processed": 0, "updated": 0, "no_change": 0, "missing": 0, "errors": 0}
    t0 = time.time()
    consecutive_errors = 0

    for repo in candidates:
        stats["processed"] += 1
        full_name = repo.get("full_name") or repo.get("name")
        if not full_name:
            continue

        try:
            full_readme = _fetch_readme(full_name)
        except RuntimeError as exc:
            logger.warning("Rate limit hit, sleeping 60s: %s", exc)
            time.sleep(60)
            consecutive_errors += 1
            if consecutive_errors > 5:
                logger.error("Too many consecutive errors, aborting")
                break
            stats["errors"] += 1
            continue
        except requests.RequestException as exc:
            logger.warning("Network error on %s: %s", full_name, exc)
            stats["errors"] += 1
            consecutive_errors += 1
            continue

        consecutive_errors = 0

        if not full_readme:
            stats["missing"] += 1
            continue

        # No-op if shorter than current (rare): the GraphQL one might be more complete
        if len(full_readme) <= repo["len"]:
            stats["no_change"] += 1
            continue

        if args.dry_run:
            logger.info("[dry-run] %s: %d → %d chars", full_name, repo["len"], len(full_readme))
            stats["updated"] += 1
            continue

        try:
            coll.update_one(
                {"$or": [{"id": repo["id"]}, {"full_name": full_name}]},
                {"$set": {"readme_text": full_readme, "has_readme": True,
                          # Borrar el flag de indexación para forzar re-embed
                          "_indexing": None}},
            )
            stats["updated"] += 1
            if stats["updated"] % 20 == 0:
                elapsed = time.time() - t0
                logger.info("Progress: %d updated, %d processed, %.0fs",
                            stats["updated"], stats["processed"], elapsed)
        except Exception as exc:
            logger.error("Persist failed for %s: %s", full_name, exc)
            stats["errors"] += 1

    elapsed = time.time() - t0
    logger.info("✅ Done in %.0fs — %s", elapsed,
                ", ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    main()
