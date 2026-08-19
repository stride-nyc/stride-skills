"""Fixture-based self-test for find_ticket_reference.py.

Run via:
    python3 find_ticket_reference.py --self-test
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import find_ticket_reference as t  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def test_branch_trailing_number_like_navigator_convention() -> None:
    print("test_branch_trailing_number_like_navigator_convention")
    # Matches navigator.business.nj.gov's own documented convention: branches
    # follow "description-#NNNNN".
    result = t.find_ticket_references("fix-login-timeout-#42981", [])
    check("best candidate found", result["best"] is not None)
    check("best id is 42981", result["best"]["id"] == "42981")
    check("best source is branch", result["best"]["source"] == "branch")


def test_azure_devops_trailer_fallback() -> None:
    print("test_azure_devops_trailer_fallback")
    # No number in the branch name at all -- must fall back to the commit
    # trailer, exactly as navigator's create-pr-navigator.md documents.
    result = t.find_ticket_references(
        "fix-login-timeout",
        ["chore: cleanup unused import", "fix: race condition [AB#42981]"],
    )
    check("best candidate found from commit trailer", result["best"] is not None)
    check("best id is 42981", result["best"]["id"] == "42981")
    check("best system guess is azure-devops", result["best"]["system_guess"] == "azure-devops")
    check("best source is commit_subject", result["best"]["source"] == "commit_subject")


def test_azure_devops_trailer_not_double_counted_as_github_ref() -> None:
    print("test_azure_devops_trailer_not_double_counted_as_github_ref")
    candidates = t.find_in_text("fix: race condition [AB#42981]", "commit_subject", "x")
    check("exactly one candidate extracted from the trailer text", len(candidates) == 1)
    check("that candidate is the azure-devops one", candidates[0]["system_guess"] == "azure-devops")


def test_uppercase_jira_style_in_commit_subject() -> None:
    print("test_uppercase_jira_style_in_commit_subject")
    result = t.find_ticket_references(
        "eng-4521-fix-login-timeout",  # lowercase -- deliberately not matched, see below
        ["fix: correct login timeout (ENG-4521)"],
    )
    check(
        "lowercase branch key not matched (documented limitation, avoids false positives)",
        not any(c["source"] == "branch" and c.get("system_guess") == "jira-or-linear" for c in result["all_candidates"]),
    )
    jira_candidates = [c for c in result["all_candidates"] if c["system_guess"] == "jira-or-linear"]
    check("uppercase ENG-4521 found in commit subject", any(c["id"] == "ENG-4521" for c in jira_candidates))


def test_plain_github_issue_reference() -> None:
    print("test_plain_github_issue_reference")
    result = t.find_ticket_references(None, ["Fixes #123 by removing the retry loop"])
    check("best candidate found", result["best"] is not None)
    check("best id is 123", result["best"]["id"] == "123")
    check("best system guess is github", result["best"]["system_guess"] == "github")


def test_denylist_avoids_false_positives() -> None:
    print("test_denylist_avoids_false_positives")
    candidates = t.find_in_text(
        "Fix UTF-8 handling in CSV export (also touches ISO-8601 date parsing)",
        "commit_subject",
        "x",
    )
    ids = {c["id"] for c in candidates}
    check("UTF-8 not extracted as a ticket reference", "UTF-8" not in ids)
    check("ISO-8601 not extracted as a ticket reference", "ISO-8601" not in ids)
    check("no spurious candidates at all from this technical-jargon-only text", candidates == [])


def test_ab_style_denylist_prevents_bare_ab_hyphen_match() -> None:
    print("test_ab_style_denylist_prevents_bare_ab_hyphen_match")
    # "AB-123" (hyphen, not the "[AB#123]" trailer format) should not be picked
    # up as a Jira-style key -- too easily confused with the Azure DevOps
    # convention used elsewhere in the same org.
    candidates = t.find_in_text("random text mentioning AB-123 in passing", "commit_subject", "x")
    check("AB-123 not extracted", candidates == [])


def test_no_references_anywhere_returns_none() -> None:
    print("test_no_references_anywhere_returns_none")
    result = t.find_ticket_references("cleanup-dead-code", ["chore: remove unused helper"])
    check("best is None when nothing matches", result["best"] is None)
    check("all_candidates is empty", result["all_candidates"] == [])


def test_branch_checked_before_commits_when_both_present() -> None:
    print("test_branch_checked_before_commits_when_both_present")
    result = t.find_ticket_references(
        "fix-login-timeout-#111",
        ["fix: race condition [AB#42981]"],
    )
    check("branch match wins as 'best' over commit trailer", result["best"]["source"] == "branch")
    check("best id reflects the branch, not the commit", result["best"]["id"] == "111")
    # But the commit trailer should still be discoverable for a human/Claude to
    # notice a mismatch (e.g. branch renamed after ticket was reassigned).
    check(
        "commit trailer still present among all_candidates",
        any(c["id"] == "42981" for c in result["all_candidates"]),
    )


def run_all() -> int:
    test_branch_trailing_number_like_navigator_convention()
    test_azure_devops_trailer_fallback()
    test_azure_devops_trailer_not_double_counted_as_github_ref()
    test_uppercase_jira_style_in_commit_subject()
    test_plain_github_issue_reference()
    test_denylist_avoids_false_positives()
    test_ab_style_denylist_prevents_bare_ab_hyphen_match()
    test_no_references_anywhere_returns_none()
    test_branch_checked_before_commits_when_both_present()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
