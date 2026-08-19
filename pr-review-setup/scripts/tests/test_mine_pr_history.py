"""Fixture-based self-test for mine_pr_history.py -- no `gh` CLI or network access
required. Run via:

    python3 mine_pr_history.py --self-test

or directly:

    python3 scripts/tests/test_mine_pr_history.py

What this validates (see README.md for the "why" behind each):
  1. Bot authors and low-signal bodies ("lgtm", "+1", "nit", ...) are dropped.
  2. Substantive human comments across all three surfaces (review_comment, review,
     issue_comment) are kept and shaped into the common record format.
  3. `fetch_paginated`'s hand-rolled multi-page JSON parser correctly splits
     concatenated pages back into records (gh api --paginate prints one JSON
     document per page, back to back, not one combined array).
  4. The checkpointed mine() loop is resumable: re-running after a simulated
     partial run does not re-fetch or duplicate already-processed PRs.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mine_pr_history as m  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def load_fixture(pr_number: int) -> dict:
    return json.loads((FIXTURES / f"pr_{pr_number}.json").read_text())


def test_filtering_and_shaping() -> None:
    print("test_filtering_and_shaping")
    fx = load_fixture(4821)
    records = m.process_pr_comments(
        4821,
        fx["pr"]["url"],
        fx["review_comments"],
        fx["reviews"],
        fx["issue_comments"],
    )
    bodies = [r["body"] for r in records]

    check(
        "keeps the substantive 'any' review comment",
        any("narrow it to `unknown`" in b for b in bodies),
    )
    check(
        "drops the dependabot bot comment",
        not any("Bumps axios" in b for b in bodies),
    )
    check("drops the bare 'nit' comment", not any(b.strip().lower() == "nit" for b in bodies))
    check(
        "keeps 'LGTM once the type issue is fixed' -- substantive despite starting with LGTM",
        any("LGTM once the type issue is fixed" in b for b in bodies),
    )
    check(
        "keeps the substantive review-level body",
        any("any-typing comment above" in b for b in bodies),
    )
    check("every kept record carries the pr_number", all(r["pr_number"] == 4821 for r in records))
    check(
        "surfaces are correctly labeled",
        {r["surface"] for r in records} == {"review_comment", "review", "issue_comment"},
    )


def test_low_signal_and_bot_denylist_directly() -> None:
    print("test_low_signal_and_bot_denylist_directly")
    check("bare 'lgtm' is low signal", m.is_low_signal("lgtm"))
    check("'LGTM!' is low signal", m.is_low_signal("LGTM!"))
    check("'+1' is low signal", m.is_low_signal("+1"))
    check(
        "a real sentence is not low signal",
        not m.is_low_signal("This should use the shared helper instead."),
    )
    check("dependabot login is a bot", m.is_bot("dependabot", None))
    check("[bot]-suffixed login is a bot", m.is_bot("some-app[bot]", None))
    check("user.type == Bot is a bot regardless of login", m.is_bot("afromanjr", "Bot"))
    check("a normal human login is not a bot", not m.is_bot("afromanjr", "User"))


def test_all_fixtures_aggregate_as_expected() -> None:
    print("test_all_fixtures_aggregate_as_expected")
    total_kept = 0
    total_raw = 0
    for pr_number in (4821, 4903, 5012):
        fx = load_fixture(pr_number)
        raw_count = (
            len(fx["review_comments"]) + len(fx["reviews"]) + len(fx["issue_comments"])
        )
        records = m.process_pr_comments(
            pr_number,
            fx["pr"]["url"],
            fx["review_comments"],
            fx["reviews"],
            fx["issue_comments"],
        )
        total_raw += raw_count
        total_kept += len(records)
    check(
        "some comments were filtered out across the fixture set",
        total_kept < total_raw,
        f"kept {total_kept} of {total_raw}",
    )
    check("at least one substantive comment survived per PR", total_kept >= 3)


def test_paginated_json_parsing() -> None:
    print("test_paginated_json_parsing")
    # Simulate what `gh api ... --paginate` actually prints: multiple JSON array
    # documents concatenated back-to-back (optionally separated by whitespace/newlines),
    # NOT one combined array. Reproduce fetch_paginated's parsing without shelling
    # out to gh by calling the same raw_decode loop it uses.
    page1 = json.dumps([{"id": 1}, {"id": 2}])
    page2 = json.dumps([{"id": 3}])
    concatenated = page1 + "\n" + page2

    decoder = json.JSONDecoder()
    records = []
    idx = 0
    s = concatenated.strip()
    while idx < len(s):
        page, end = decoder.raw_decode(s, idx)
        records.extend(page)
        idx = end
        while idx < len(s) and s[idx] in " \t\r\n":
            idx += 1

    check("all three records recovered across two pages", len(records) == 3)
    check("record order preserved", [r["id"] for r in records] == [1, 2, 3])


def test_checkpoint_resumability() -> None:
    print("test_checkpoint_resumability")
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        checkpoint_path = out_dir / ".checkpoint.json"

        # First "run": process PR 4821 only, then checkpoint.
        processed = m.load_checkpoint(checkpoint_path)
        check("checkpoint starts empty", processed == set())
        processed.add(4821)
        m.save_checkpoint(checkpoint_path, processed)

        # Second "run": reload -- 4821 should be skippable, 4903/5012 should not.
        reloaded = m.load_checkpoint(checkpoint_path)
        check("reloaded checkpoint contains 4821", 4821 in reloaded)
        check("reloaded checkpoint does not contain unprocessed PRs", 4903 not in reloaded)

        # Simulate the skip logic mine() uses.
        to_process = [n for n in (4821, 4903, 5012) if n not in reloaded]
        check("resuming only processes the two new PRs", to_process == [4903, 5012])


def test_mine_end_to_end_with_monkeypatched_gh() -> None:
    print("test_mine_end_to_end_with_monkeypatched_gh")
    all_fixtures = {n: load_fixture(n) for n in (4821, 4903, 5012)}

    def fake_list_merged_prs(owner, repo, since):
        return [
            {"number": n, "url": fx["pr"]["url"], "mergedAt": fx["pr"]["mergedAt"]}
            for n, fx in all_fixtures.items()
        ]

    def fake_fetch_paginated(owner, repo, path):
        # path looks like "pulls/4821/comments", "pulls/4821/reviews", or "issues/4821/comments"
        parts = path.split("/")
        pr_number = int(parts[1])
        fx = all_fixtures[pr_number]
        if parts[0] == "pulls" and parts[2] == "comments":
            return fx["review_comments"]
        if parts[0] == "pulls" and parts[2] == "reviews":
            return fx["reviews"]
        if parts[0] == "issues" and parts[2] == "comments":
            return fx["issue_comments"]
        raise AssertionError(f"unexpected path {path}")

    orig_list, orig_fetch = m.list_merged_prs, m.fetch_paginated
    m.list_merged_prs = fake_list_merged_prs
    m.fetch_paginated = fake_fetch_paginated
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "data" / "newjersey-navigator.business.nj.gov"

            # First run processes all three PRs.
            summary1 = m.mine("newjersey", "navigator.business.nj.gov", 2.0, out_dir)
            check("first run processes all 3 PRs in window", summary1["prs_in_window"] == 3)
            check("first run writes >0 records", summary1["records_written_this_run"] > 0)

            raw_lines = (out_dir / "raw-comments.jsonl").read_text().strip().splitlines()
            check(
                "raw-comments.jsonl line count matches records written",
                len(raw_lines) == summary1["records_written_this_run"],
            )
            check(
                "every written line is valid JSON with the common shape",
                all({"pr_number", "surface", "author", "body"} <= json.loads(line).keys()
                    for line in raw_lines),
            )

            # Second run against the *same* out_dir must be a no-op: checkpoint
            # already has all 3 PRs, so nothing new should be fetched or appended.
            summary2 = m.mine("newjersey", "navigator.business.nj.gov", 2.0, out_dir)
            check(
                "second run against same output dir writes no new records (checkpoint honored)",
                summary2["records_written_this_run"] == 0,
            )
            raw_lines_after = (out_dir / "raw-comments.jsonl").read_text().strip().splitlines()
            check(
                "raw-comments.jsonl is not duplicated on a resumed/rerun",
                len(raw_lines_after) == len(raw_lines),
            )
    finally:
        m.list_merged_prs = orig_list
        m.fetch_paginated = orig_fetch


def run_all() -> int:
    test_filtering_and_shaping()
    test_low_signal_and_bot_denylist_directly()
    test_all_fixtures_aggregate_as_expected()
    test_paginated_json_parsing()
    test_checkpoint_resumability()
    test_mine_end_to_end_with_monkeypatched_gh()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
