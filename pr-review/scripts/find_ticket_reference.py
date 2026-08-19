#!/usr/bin/env python3
"""Phase 4 helper for the pr-review skill: locate a ticket/issue reference from
the branch name or recent commit subjects, before falling back to asking the
user (see DESIGN.md, Phase 4, step 1).

Modeled directly on a real pattern found in navigator.business.nj.gov's own
`.claude/commands/create-pr-navigator.md`: check the branch name for a trailing
`#NNNNN` first, then fall back to an `[AB#NNNNN]` commit-message trailer (their
commit-msg hook enforces that prefix, which is exactly why it's a *more*
reliable fallback than scanning commit prose freely). This script generalizes
that to also recognize plain GitHub issue refs and Jira/Linear-style project-key
tickets (ABC-123), since not every org uses Azure DevOps.

This only *locates* a candidate reference -- it does not fetch the ticket. Once
a system is guessed (github/azure-devops/jira-or-linear), fetching is either a
connected tracker MCP or an org-specific script (like navigator's own
`fetch_ado_ticket.py`), which is inherently org-specific and out of scope for a
generic script.

Usage:
    python3 find_ticket_reference.py --branch <name> [--commit-subject SUBJ ...]
    python3 find_ticket_reference.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Azure DevOps commit trailer, e.g. "fix: race condition [AB#42981]". Checked
# first among commit-subject patterns since, where present, it's enforced by a
# commit-msg hook and therefore more reliable than free-text scanning.
AZURE_DEVOPS_TRAILER = re.compile(r"\[AB#(\d+)\]")

# A branch name ending in a bare ticket number, e.g. "fix-login-bug-#12345" or
# "fix-login-bug-12345". The leading separator (-, _, or /) is optional.
BRANCH_TRAILING_NUMBER = re.compile(r"[-_/]#?(\d+)$")

# Generic GitHub issue/PR reference, e.g. "#123". Applied after masking out
# spans already claimed by AZURE_DEVOPS_TRAILER so "[AB#42981]" doesn't also
# get read as a bare "#42981" GitHub reference.
GITHUB_ISSUE_REF = re.compile(r"#(\d+)\b")

# Jira/Linear-style PROJECT-123 references. Common non-ticket lookalikes
# (UTF-8, ISO-8601, RFC-1234, SHA-256, HTTP-2, ES-256...) are excluded by a
# denylist of the project-key part, since the pattern alone can't tell them
# apart from a real ticket prefix.
JIRA_STYLE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d+)\b")
JIRA_STYLE_DENYLIST_PREFIXES = {
    "UTF",
    "ISO",
    "RFC",
    "SHA",
    "HTTP",
    "HTTPS",
    "ES",
    "IPV",
    "PEP",
    "TLS",
    "SSL",
    "MD",
    "AB",  # already handled by AZURE_DEVOPS_TRAILER; avoid double-counting AB#NNNN
}


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def find_in_text(text: str, source: str, source_detail: str) -> list[dict]:
    """Find every ticket-like reference in a single piece of text (a branch name
    or one commit subject). Returns a list of candidates, not yet deduplicated
    or ranked across multiple texts -- that's find_ticket_references' job.
    """
    candidates: list[dict] = []
    claimed_spans: list[tuple[int, int]] = []

    for m in AZURE_DEVOPS_TRAILER.finditer(text):
        candidates.append(
            {
                "system_guess": "azure-devops",
                "id": m.group(1),
                "raw_match": m.group(0),
                "source": source,
                "source_detail": source_detail,
            }
        )
        claimed_spans.append(m.span())

    masked = _mask(text, claimed_spans)

    for m in JIRA_STYLE.finditer(masked):
        prefix = m.group(1)
        if prefix in JIRA_STYLE_DENYLIST_PREFIXES:
            continue
        candidates.append(
            {
                "system_guess": "jira-or-linear",
                "id": f"{prefix}-{m.group(2)}",
                "raw_match": m.group(0),
                "source": source,
                "source_detail": source_detail,
            }
        )

    for m in GITHUB_ISSUE_REF.finditer(masked):
        candidates.append(
            {
                "system_guess": "github",
                "id": m.group(1),
                "raw_match": m.group(0),
                "source": source,
                "source_detail": source_detail,
            }
        )

    return candidates


def find_ticket_references(branch_name: str | None, commit_subjects: list[str]) -> dict:
    """Returns {"best": <candidate or None>, "all_candidates": [...]}.

    Priority, matching DESIGN.md Phase 4 step 1: a trailing number in the branch
    name first (checked as a bare branch-suffix pattern, distinct from the
    in-text patterns above since a branch name isn't prose), then commit-subject
    patterns in the order found -- Azure DevOps trailers before generic
    GitHub/Jira-style references, since a hook-enforced trailer is more
    deliberate than an incidental "#123" mention.
    """
    all_candidates: list[dict] = []

    if branch_name:
        m = BRANCH_TRAILING_NUMBER.search(branch_name)
        if m:
            all_candidates.append(
                {
                    "system_guess": "unknown",  # a bare trailing number in a branch name
                    # doesn't by itself say which tracker it belongs to.
                    "id": m.group(1),
                    "raw_match": m.group(0),
                    "source": "branch",
                    "source_detail": branch_name,
                }
            )
        # Also check the branch name for the same in-text patterns (a branch
        # like "fix-ENG-4521-login-bug" carries a Jira-style key mid-string,
        # not just at the end).
        all_candidates.extend(find_in_text(branch_name, "branch", branch_name))

    for subject in commit_subjects:
        all_candidates.extend(find_in_text(subject, "commit_subject", subject))

    best = all_candidates[0] if all_candidates else None
    return {"best": best, "all_candidates": all_candidates}


def run_self_test() -> int:
    tests_dir = Path(__file__).parent / "tests"
    sys.path.insert(0, str(tests_dir))
    import test_find_ticket_reference  # type: ignore

    return test_find_ticket_reference.run_all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch")
    parser.add_argument("--commit-subject", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    result = find_ticket_references(args.branch, args.commit_subject)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
