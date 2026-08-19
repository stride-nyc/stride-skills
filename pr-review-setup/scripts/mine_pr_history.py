#!/usr/bin/env python3
"""Phase 1 of the pr-review skill: mine years of merged-PR review comments into a
clean, deduplicated, checkpointed JSONL file for a later clustering pass to read.

This script deliberately does the *deterministic* work only (enumerate PRs, fetch
comments, filter bots/noise, checkpoint, write JSONL). Turning that into named
"patterns to avoid" is a judgment call left to Claude reading references/
mine-history-clustering.md against the output -- see SKILL.md step 4.

Usage:
    python3 mine_pr_history.py --years 2 --out data/newjersey-navigator.business.nj.gov
    python3 mine_pr_history.py --owner newjersey --repo navigator.business.nj.gov --years 3 --out data/x

Requires: the `gh` CLI installed and authenticated (`gh auth status`). Run from
inside a checkout of the target repo, or pass --owner/--repo explicitly.

Self-test (no gh/network required):
    python3 mine_pr_history.py --self-test
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

BOT_LOGIN_SUFFIXES = ("[bot]",)
BOT_LOGIN_DENYLIST = {
    "dependabot",
    "renovate",
    "github-actions",
    "codecov",
    "vercel",
    "netlify",
}

# Comments that are purely an approval/ack carry no generalizable review pattern.
LOW_SIGNAL_BODIES = {
    "lgtm",
    "lgtm!",
    "looks good",
    "looks good to me",
    "+1",
    ":+1:",
    "ship it",
    "approved",
    "nice",
    "nice!",
    "nit",
    "thanks",
    "thanks!",
}

MIN_BODY_LENGTH = 8  # characters, after stripping -- shorter is almost never substantive


def is_bot(login: str, user_type: str | None) -> bool:
    if user_type and user_type.lower() == "bot":
        return True
    login_lower = (login or "").lower()
    if login_lower in BOT_LOGIN_DENYLIST:
        return True
    return any(login_lower.endswith(suffix) for suffix in BOT_LOGIN_SUFFIXES)


def is_low_signal(body: str) -> bool:
    normalized = (body or "").strip().lower().rstrip("!.")
    if len(normalized) < MIN_BODY_LENGTH:
        return True
    if normalized in LOW_SIGNAL_BODIES:
        return True
    return False


def should_keep(login: str, user_type: str | None, body: str) -> bool:
    if is_bot(login, user_type):
        return False
    if is_low_signal(body):
        return False
    return True


# ---------------------------------------------------------------------------
# Record shaping -- these three functions each map one `gh api` response shape
# onto the common record format written to raw-comments.jsonl.
# ---------------------------------------------------------------------------


def shape_review_comment(pr_number: int, pr_url: str, raw: dict) -> dict | None:
    user = raw.get("user") or {}
    body = raw.get("body") or ""
    if not should_keep(user.get("login", ""), user.get("type"), body):
        return None
    return {
        "pr_number": pr_number,
        "pr_url": pr_url,
        "surface": "review_comment",
        "path": raw.get("path"),
        "author": user.get("login"),
        "created_at": raw.get("created_at"),
        "body": body,
    }


def shape_review(pr_number: int, pr_url: str, raw: dict) -> dict | None:
    user = raw.get("user") or {}
    body = raw.get("body") or ""
    if not should_keep(user.get("login", ""), user.get("type"), body):
        return None
    return {
        "pr_number": pr_number,
        "pr_url": pr_url,
        "surface": "review",
        "path": None,
        "author": user.get("login"),
        "created_at": raw.get("submitted_at"),
        "body": body,
    }


def shape_issue_comment(pr_number: int, pr_url: str, raw: dict) -> dict | None:
    user = raw.get("user") or {}
    body = raw.get("body") or ""
    if not should_keep(user.get("login", ""), user.get("type"), body):
        return None
    return {
        "pr_number": pr_number,
        "pr_url": pr_url,
        "surface": "issue_comment",
        "path": None,
        "author": user.get("login"),
        "created_at": raw.get("created_at"),
        "body": body,
    }


def process_pr_comments(
    pr_number: int,
    pr_url: str,
    review_comments: list[dict],
    reviews: list[dict],
    issue_comments: list[dict],
) -> list[dict]:
    """Pure function: raw gh-api-shaped payloads in, filtered common-format records out.
    Kept separate from any subprocess/gh call so it can be exercised by the self-test
    with fixture data and no network access.
    """
    out: list[dict] = []
    for raw in review_comments:
        rec = shape_review_comment(pr_number, pr_url, raw)
        if rec:
            out.append(rec)
    for raw in reviews:
        rec = shape_review(pr_number, pr_url, raw)
        if rec:
            out.append(rec)
    for raw in issue_comments:
        rec = shape_issue_comment(pr_number, pr_url, raw)
        if rec:
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# gh CLI wrappers
# ---------------------------------------------------------------------------


class GhError(RuntimeError):
    pass


def run_gh(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False, timeout=120
        )
    except FileNotFoundError as exc:
        raise GhError(
            "The `gh` CLI isn't installed. Install it and run `gh auth login` first."
        ) from exc
    if result.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def detect_owner_repo() -> tuple[str, str]:
    out = run_gh(["repo", "view", "--json", "owner,name"])
    data = json.loads(out)
    return data["owner"]["login"], data["name"]


def list_merged_prs(owner: str, repo: str, since: datetime) -> list[dict]:
    cutoff = since.strftime("%Y-%m-%d")
    out = run_gh(
        [
            "pr",
            "list",
            "--repo",
            f"{owner}/{repo}",
            "--state",
            "merged",
            "--search",
            f"merged:>={cutoff}",
            "--json",
            "number,url,mergedAt",
            "--limit",
            "5000",
        ]
    )
    return json.loads(out)


def fetch_paginated(owner: str, repo: str, path: str) -> list[dict]:
    out = run_gh(["api", f"repos/{owner}/{repo}/{path}", "--paginate"])
    # `gh api --paginate` concatenates one JSON array per page back-to-back when the
    # endpoint returns arrays; each page is valid JSON on its own but multiple pages
    # printed together are not automatically a single valid JSON document. Parse
    # defensively page-by-page using a streaming decoder.
    decoder = json.JSONDecoder()
    records: list[dict] = []
    idx = 0
    out = out.strip()
    while idx < len(out):
        page, end = decoder.raw_decode(out, idx)
        if isinstance(page, list):
            records.extend(page)
        idx = end
        while idx < len(out) and out[idx] in " \t\r\n":
            idx += 1
    return records


# ---------------------------------------------------------------------------
# Main mining loop with checkpointing
# ---------------------------------------------------------------------------


def load_checkpoint(checkpoint_path: Path) -> set[int]:
    if not checkpoint_path.exists():
        return set()
    return set(json.loads(checkpoint_path.read_text()).get("processed_pr_numbers", []))


def save_checkpoint(checkpoint_path: Path, processed: set[int]) -> None:
    checkpoint_path.write_text(json.dumps({"processed_pr_numbers": sorted(processed)}, indent=2))


def mine(owner: str, repo: str, years: float, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw-comments.jsonl"
    checkpoint_path = out_dir / ".checkpoint.json"

    since = datetime.now(timezone.utc) - timedelta(days=int(years * 365))
    prs = list_merged_prs(owner, repo, since)
    processed = load_checkpoint(checkpoint_path)

    total_records = 0
    with raw_path.open("a", encoding="utf-8") as f:
        for pr in prs:
            number = pr["number"]
            if number in processed:
                continue
            review_comments = fetch_paginated(owner, repo, f"pulls/{number}/comments")
            reviews = fetch_paginated(owner, repo, f"pulls/{number}/reviews")
            issue_comments = fetch_paginated(owner, repo, f"issues/{number}/comments")
            records = process_pr_comments(
                number, pr["url"], review_comments, reviews, issue_comments
            )
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total_records += len(records)
            processed.add(number)
            save_checkpoint(checkpoint_path, processed)

    return {
        "prs_in_window": len(prs),
        "prs_processed_this_run_or_before": len(processed),
        "records_written_this_run": total_records,
        "raw_comments_path": str(raw_path),
    }


# ---------------------------------------------------------------------------
# Self-test (no gh / network required) -- see scripts/tests/README.md
# ---------------------------------------------------------------------------


def run_self_test() -> int:
    tests_dir = Path(__file__).parent / "tests"
    sys.path.insert(0, str(tests_dir))
    import test_mine_pr_history  # type: ignore

    return test_mine_pr_history.run_all()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", help="Repo owner. Auto-detected via `gh repo view` if omitted.")
    parser.add_argument("--repo", help="Repo name. Auto-detected via `gh repo view` if omitted.")
    parser.add_argument(
        "--years", type=float, default=2.0, help="How far back to mine (default: 2 years)."
    )
    parser.add_argument(
        "--out", required=False, help="Output directory for raw-comments.jsonl and checkpoint."
    )
    parser.add_argument(
        "--self-test", action="store_true", help="Run the fixture-based self-test and exit."
    )
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if not args.out:
        parser.error("--out is required unless --self-test is passed")

    try:
        owner, repo = (args.owner, args.repo) if args.owner and args.repo else detect_owner_repo()
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        summary = mine(owner, repo, args.years, Path(args.out))
    except GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
