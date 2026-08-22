#!/usr/bin/env python3
"""
Collect GitHub reactions on pr-review CI comments and compute pattern score deltas.

Usage:
    collect_reactions.py --root <repo-root> [--pr <number>] [--limit <n>] [--dry-run]
    collect_reactions.py --self-test
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

PATTERN_MARKER = "pr-review-pattern:"
SCORE_THUMBS_UP = 2
SCORE_THUMBS_DOWN = -1


# ---------------------------------------------------------------------------
# gh CLI helpers
# ---------------------------------------------------------------------------

def _gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gh error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def _gh_api_list(endpoint):
    """Fetch all pages from an array-returning endpoint, one item per line via jq."""
    result = subprocess.run(
        ["gh", "api", "--paginate", "--jq", ".[]", endpoint],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    items = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def get_repo():
    info = json.loads(_gh("repo", "view", "--json", "owner,name"))
    return info["owner"]["login"], info["name"]


def get_merged_pr_numbers(limit):
    output = _gh(
        "pr", "list",
        "--state", "merged",
        "--limit", str(limit),
        "--json", "number",
        "--jq", "[.[].number]",
    )
    return json.loads(output)


def get_issue_comments(owner, repo, pr_number):
    return _gh_api_list(f"/repos/{owner}/{repo}/issues/{pr_number}/comments")


def get_comment_reactions(owner, repo, comment_id):
    return _gh_api_list(f"/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions")


# ---------------------------------------------------------------------------
# Core logic (pure — easy to test)
# ---------------------------------------------------------------------------

def extract_pattern_name(body):
    """Return the pattern name embedded in a pr-review CI comment, or None."""
    for line in body.splitlines():
        if PATTERN_MARKER in line:
            start = line.index(PATTERN_MARKER) + len(PATTERN_MARKER)
            end = line.find("-->", start)
            if end != -1:
                return line[start:end].strip()
    return None


def compute_delta_from_reactions(reactions):
    """
    Given a list of GitHub reaction objects, return (delta, up_count, down_count).
    Deduplicates per user per reaction type — a user's 👍 and 👎 are counted independently.
    """
    up_users = set()
    down_users = set()
    for r in reactions:
        content = r.get("content", "")
        user_id = r.get("user", {}).get("id")
        if user_id is None:
            continue
        if content == "+1":
            up_users.add(user_id)
        elif content == "-1":
            down_users.add(user_id)

    up = len(up_users)
    down = len(down_users)
    delta = up * SCORE_THUMBS_UP + down * SCORE_THUMBS_DOWN
    return delta, up, down


def collect_deltas(owner, repo, pr_numbers):
    """
    Scan PR comments across the given PR numbers. Return a dict:
      { pattern_name: {"delta": int, "accepts": int, "dismissals": int, "prs": [int]} }
    """
    deltas = {}

    for pr_number in pr_numbers:
        comments = get_issue_comments(owner, repo, pr_number)
        for comment in comments:
            pattern = extract_pattern_name(comment.get("body", ""))
            if not pattern:
                continue

            reactions = get_comment_reactions(owner, repo, comment["id"])
            delta, up, down = compute_delta_from_reactions(reactions)

            if up == 0 and down == 0:
                continue

            if pattern not in deltas:
                deltas[pattern] = {"delta": 0, "accepts": 0, "dismissals": 0, "prs": []}
            deltas[pattern]["delta"] += delta
            deltas[pattern]["accepts"] += up
            deltas[pattern]["dismissals"] += down
            if pr_number not in deltas[pattern]["prs"]:
                deltas[pattern]["prs"].append(pr_number)

    return deltas


def load_scores(scores_path):
    if scores_path.exists():
        with open(scores_path) as f:
            return json.load(f)
    return {"version": 1, "patterns": {}}


def apply_deltas(scores, deltas, today):
    for pattern, d in deltas.items():
        if pattern not in scores["patterns"]:
            scores["patterns"][pattern] = {
                "score": 0,
                "accepts": 0,
                "dismissals": 0,
                "explicitlyIgnored": False,
                "source": "CI reactions",
                "lastSeen": today,
            }
        entry = scores["patterns"][pattern]
        entry["score"] += d["delta"]
        entry["accepts"] += d["accepts"]
        entry["dismissals"] += d["dismissals"]
        entry["lastSeen"] = today
    return scores


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    failures = []

    def check(label, got, want):
        if got != want:
            failures.append(f"{label}: got {got!r}, want {want!r}")

    # extract_pattern_name
    body_with_marker = "Some finding text\n<!-- pr-review-pattern: Missing null checks -->"
    check("extract pattern", extract_pattern_name(body_with_marker), "Missing null checks")
    check("extract pattern absent", extract_pattern_name("No marker here"), None)
    check("extract pattern extra whitespace",
          extract_pattern_name("<!-- pr-review-pattern:   Trailing space  -->"),
          "Trailing space")

    # compute_delta_from_reactions
    reactions = [
        {"content": "+1", "user": {"id": 1}},
        {"content": "+1", "user": {"id": 2}},
        {"content": "-1", "user": {"id": 3}},
        {"content": "+1", "user": {"id": 1}},  # duplicate — should not double-count
    ]
    delta, up, down = compute_delta_from_reactions(reactions)
    check("delta", delta, 2 * SCORE_THUMBS_UP + 1 * SCORE_THUMBS_DOWN)
    check("up count", up, 2)
    check("down count", down, 1)

    # all thumbs up
    delta2, up2, down2 = compute_delta_from_reactions([
        {"content": "+1", "user": {"id": 10}},
        {"content": "+1", "user": {"id": 11}},
    ])
    check("all up delta", delta2, 2 * SCORE_THUMBS_UP)

    # empty reactions
    delta3, up3, down3 = compute_delta_from_reactions([])
    check("empty delta", delta3, 0)
    check("empty up", up3, 0)
    check("empty down", down3, 0)

    # apply_deltas
    scores = {"version": 1, "patterns": {}}
    deltas = {"Missing null checks": {"delta": 4, "accepts": 2, "dismissals": 0, "prs": [1]}}
    result = apply_deltas(scores, deltas, "2026-08-22")
    entry = result["patterns"]["Missing null checks"]
    check("apply delta score", entry["score"], 4)
    check("apply delta accepts", entry["accepts"], 2)

    # apply_deltas accumulates across calls
    deltas2 = {"Missing null checks": {"delta": -1, "accepts": 0, "dismissals": 1, "prs": [2]}}
    result2 = apply_deltas(result, deltas2, "2026-08-23")
    check("accumulate score", result2["patterns"]["Missing null checks"]["score"], 3)

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        sys.exit(1)
    print(f"All self-tests passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repo root directory")
    parser.add_argument("--pr", type=int, help="Specific PR number to scan")
    parser.add_argument("--limit", type=int, default=20,
                        help="Number of recent merged PRs to scan (default 20)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print score changes without writing")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    if not args.root:
        parser.error("--root is required")

    owner, repo = get_repo()
    pr_numbers = [args.pr] if args.pr else get_merged_pr_numbers(args.limit)

    if not pr_numbers:
        print("No merged PRs found.")
        return

    print(f"Scanning {len(pr_numbers)} PR(s) for pr-review reaction comments...")
    deltas = collect_deltas(owner, repo, pr_numbers)

    if not deltas:
        print("No pr-review reaction comments found — nothing to update.")
        return

    data_dir = Path(args.root) / ".claude" / "pr-review-data" / f"{owner}-{repo}"
    scores_path = data_dir / "pattern-scores.json"
    scores = load_scores(scores_path)
    today = date.today().isoformat()

    print(f"\nProposed score changes:\n")
    for pattern, d in sorted(deltas.items(), key=lambda x: abs(x[1]["delta"]), reverse=True):
        current = scores["patterns"].get(pattern, {}).get("score", 0)
        new = current + d["delta"]
        sign = "+" if d["delta"] >= 0 else ""
        prs_str = ", ".join(f"#{n}" for n in d["prs"])
        print(f"  {pattern}")
        print(f"    score: {current} -> {new} ({sign}{d['delta']})  "
              f"👍 {d['accepts']}  👎 {d['dismissals']}  from {prs_str}")

    if args.dry_run:
        print("\n[dry run] No changes written.")
        return

    updated = apply_deltas(scores, deltas, today)
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(scores_path, "w") as f:
        json.dump(updated, f, indent=2)
    print(f"\nUpdated {scores_path}")


if __name__ == "__main__":
    main()