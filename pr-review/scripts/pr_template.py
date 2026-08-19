#!/usr/bin/env python3
"""Phase 5 helper for the pr-review skill: find the repo's own PR template (don't
invent a different shape), and when updating an existing PR, split its current
body into the descriptive sections versus the checklist so the checklist's
ticked/unticked state can be preserved verbatim (see DESIGN.md, Phase 5).

Modeled on navigator.business.nj.gov's real `.github/pull_request_template.md`
and on its own `.claude/commands/create-pr-navigator.md`, which already
implements exactly this "preserve the checklist, regenerate the rest" pattern
by hand for that one repo. This generalizes it: template *discovery* (several
possible filenames/locations) and checklist *splitting* (finding wherever the
checklist heading happens to be, not a fixed line number) both need to work for
a repo this script has never seen.

This only discovers/parses -- it never writes to GitHub. Actually creating or
editing the PR (`gh pr create`/`gh pr edit`) happens after the user confirms the
drafted title/body in chat, per SKILL.md.

Usage:
    python3 pr_template.py --find --root .
    python3 pr_template.py --split-checklist path/to/current_body.md
    python3 pr_template.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Search locations in priority order. GitHub itself recognizes several of
# these; where it matters we match case-insensitively since conventions vary
# (navigator.business.nj.gov uses lowercase, plenty of repos use uppercase).
SINGLE_TEMPLATE_LOCATIONS = [
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "docs/pull_request_template.md",
    "PULL_REQUEST_TEMPLATE.md",
    "pull_request_template.md",
]
MULTI_TEMPLATE_DIR = ".github/PULL_REQUEST_TEMPLATE"

# A heading is treated as "the checklist" if its text contains "checklist"
# (case-insensitive) -- deliberately not hardcoded to navigator's exact
# "Code author checklist" wording, since other repos will phrase it differently.
CHECKLIST_HEADING = re.compile(r"^(#{1,4})\s*.*checklist.*$", re.IGNORECASE | re.MULTILINE)

CHECKBOX_LINE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*(.*)$", re.MULTILINE)

DEFAULT_TEMPLATE = """## Summary

<!-- What changed, and why -->

## Related issue

<!-- Link to the ticket/issue this addresses, if any -->

## How to test

<!-- Steps for a reviewer to verify this works -->
"""


def _case_insensitive_lookup(root: Path, rel_path: str) -> Path | None:
    """Resolve rel_path under root allowing case-insensitive matches on each path
    segment, since filesystems and git conventions disagree on case-sensitivity
    and we shouldn't miss a template just because of casing.
    """
    current = root
    for segment in Path(rel_path).parts:
        if not current.is_dir():
            return None
        match = None
        try:
            entries = list(current.iterdir())
        except (PermissionError, FileNotFoundError):
            return None
        for entry in entries:
            if entry.name == segment:
                match = entry
                break
        if match is None:
            for entry in entries:
                if entry.name.lower() == segment.lower():
                    match = entry
                    break
        if match is None:
            return None
        current = match
    return current if current.is_file() else None


def find_template(root: Path) -> dict:
    """Returns one of:
    {"kind": "single", "path": "<relpath>"}
    {"kind": "multiple", "paths": ["<relpath>", ...]}
    {"kind": "none"}
    """
    multi_dir = root / MULTI_TEMPLATE_DIR
    if multi_dir.is_dir():
        templates = sorted(p for p in multi_dir.glob("*.md") if p.is_file())
        if templates:
            return {"kind": "multiple", "paths": [str(p.relative_to(root)) for p in templates]}

    for candidate in SINGLE_TEMPLATE_LOCATIONS:
        found = _case_insensitive_lookup(root, candidate)
        if found:
            return {"kind": "single", "path": str(found.relative_to(root))}

    return {"kind": "none"}


def split_checklist(body: str) -> dict:
    """Split a PR body into everything before the checklist heading and the
    checklist section itself (heading through end of body), preserved verbatim.
    Returns {"description": "...", "checklist": "..." | None}.
    """
    match = CHECKLIST_HEADING.search(body)
    if not match:
        return {"description": body, "checklist": None}
    start = match.start()
    return {"description": body[:start].rstrip() + "\n", "checklist": body[start:]}


def count_checkboxes(checklist_text: str) -> dict:
    """Summarize checkbox state -- useful for reporting ("N of M already
    checked") without needing to reproduce the checklist text in chat.
    """
    total = 0
    checked = 0
    for m in CHECKBOX_LINE.finditer(checklist_text or ""):
        total += 1
        if m.group(1).lower() == "x":
            checked += 1
    return {"total": total, "checked": checked}


def run_self_test() -> int:
    tests_dir = Path(__file__).parent / "tests"
    sys.path.insert(0, str(tests_dir))
    import test_pr_template  # type: ignore

    return test_pr_template.run_all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--find", action="store_true", help="Find this repo's PR template.")
    parser.add_argument(
        "--split-checklist",
        metavar="FILE",
        help="Read FILE as an existing PR body and split it into description/checklist.",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    if args.split_checklist:
        body = Path(args.split_checklist).read_text()
        result = split_checklist(body)
        result["checkbox_summary"] = count_checkboxes(result["checklist"] or "")
        print(json.dumps(result, indent=2))
        return 0

    if args.find:
        print(json.dumps(find_template(Path(args.root).resolve()), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
