"""Fixture-based self-test for pr_template.py. The template text below is the
*real* `.github/pull_request_template.md` from navigator.business.nj.gov,
copied verbatim, so the checklist-splitting logic is validated against an
actual production template rather than an invented simplified one.

Run via:
    python3 pr_template.py --self-test
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_template as p  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


REAL_NAVIGATOR_TEMPLATE = """<!-- Please complete the following sections as necessary. -->

## Description

<!-- Summary of the changes, related issue, relevant motivation, and context -->

### Ticket

<!-- Link to ticket in ADO. Append ticket_id to the URL for the board that owns it.
     Board routing is not a clean cutover; run `python3 scripts/fetch_ado_ticket.py <id>`
     or check scripts/ado-boards.json for the current cutover and exceptions list. -->

This pull request resolves [#0000](https://dev.azure.com/NJInnovation/BizX/_workitems/edit/0000).

### Approach

<!-- Any changed dependencies, e.g. requires an install/update/migration, etc. -->

### Steps to Test

<!-- If this work affects a user's experience, provide steps to test these changes in-app. -->

### Notes

<!-- Additional information, key learnings, and future development considerations. -->

## Code author checklist

- [ ] I have rebased this branch from the latest main branch
- [ ] I have performed a self-review of my code
- [ ] My code follows the style guide
- [ ] I have created and/or updated relevant documentation on the engineering documentation website
- [ ] I have not used any relative imports
- [ ] I have pruned any instances of unused code
- [ ] I have not added any markdown to labels, titles and button text in config
- [ ] If I added/updated any values in `userData` (including `profileData`, `formationData` etc), then I added a new migration file
- [ ] I have checked for and removed instances of unused config from CMS
- [ ] If I added any new collections to the CMS config, then I updated the search tool and `cmsCollections.ts` (see CMS Additions in Engineering Reference/FAQ on the engineering documentation site)
- [ ] I have updated relevant `.env` values in `.env-template`, in Bitwarden, and in our workspaces
- [ ] I have added the `pr-show` or `pr-review` label on GitHub to show or request reviews
"""


def test_find_single_lowercase_template() -> None:
    print("test_find_single_lowercase_template")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github").mkdir()
        (root / ".github" / "pull_request_template.md").write_text(REAL_NAVIGATOR_TEMPLATE)

        result = p.find_template(root)
        check("kind is single", result["kind"] == "single")
        check("path matches the real navigator location", result["path"] == ".github/pull_request_template.md")


def test_find_uppercase_template_case_insensitively() -> None:
    print("test_find_uppercase_template_case_insensitively")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".github").mkdir()
        (root / ".github" / "PULL_REQUEST_TEMPLATE.MD").write_text("## Summary\n")
        # SINGLE_TEMPLATE_LOCATIONS lists "pull_request_template.md" lowercase;
        # the case-insensitive lookup should still find the uppercase file on disk.
        result = p._case_insensitive_lookup(root, ".github/pull_request_template.md")
        check("uppercase file found via case-insensitive lookup", result is not None)


def test_find_multiple_templates_directory() -> None:
    print("test_find_multiple_templates_directory")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        multi_dir = root / ".github" / "PULL_REQUEST_TEMPLATE"
        multi_dir.mkdir(parents=True)
        (multi_dir / "bugfix.md").write_text("## Bug\n")
        (multi_dir / "feature.md").write_text("## Feature\n")

        result = p.find_template(root)
        check("kind is multiple", result["kind"] == "multiple")
        check("both templates listed", len(result["paths"]) == 2)


def test_no_template_found() -> None:
    print("test_no_template_found")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = p.find_template(root)
        check("kind is none", result["kind"] == "none")


def test_split_real_navigator_checklist() -> None:
    print("test_split_real_navigator_checklist")
    result = p.split_checklist(REAL_NAVIGATOR_TEMPLATE)
    check("description does not contain the checklist heading", "Code author checklist" not in result["description"])
    check("description retains the Description/Ticket/Approach sections", "### Ticket" in result["description"])
    check("checklist starts at the checklist heading", result["checklist"].startswith("## Code author checklist"))
    check(
        "checklist preserves every checkbox line verbatim",
        result["checklist"].count("- [ ]") == 12,
    )
    summary = p.count_checkboxes(result["checklist"])
    check("checkbox summary counts 12 total, 0 checked", summary == {"total": 12, "checked": 0})


def test_split_preserves_mixed_checked_state() -> None:
    print("test_split_preserves_mixed_checked_state")
    body = REAL_NAVIGATOR_TEMPLATE.replace(
        "- [ ] I have rebased this branch from the latest main branch",
        "- [x] I have rebased this branch from the latest main branch",
    ).replace(
        "- [ ] I have performed a self-review of my code",
        "- [x] I have performed a self-review of my code",
    )
    result = p.split_checklist(body)
    summary = p.count_checkboxes(result["checklist"])
    check("2 of 12 checked, preserved exactly", summary == {"total": 12, "checked": 2})
    check(
        "the specific checked line is byte-for-byte preserved",
        "- [x] I have rebased this branch from the latest main branch" in result["checklist"],
    )


def test_body_with_no_checklist_heading_at_all() -> None:
    print("test_body_with_no_checklist_heading_at_all")
    body = "## Summary\n\nJust a quick fix, no template used.\n"
    result = p.split_checklist(body)
    check("description is the whole body", result["description"] == body)
    check("checklist is None", result["checklist"] is None)


def test_default_template_has_no_checklist_to_invent() -> None:
    print("test_default_template_has_no_checklist_to_invent")
    result = p.split_checklist(p.DEFAULT_TEMPLATE)
    check("generic fallback template has no checklist section", result["checklist"] is None)


def run_all() -> int:
    test_find_single_lowercase_template()
    test_find_uppercase_template_case_insensitively()
    test_find_multiple_templates_directory()
    test_no_template_found()
    test_split_real_navigator_checklist()
    test_split_preserves_mixed_checked_state()
    test_body_with_no_checklist_heading_at_all()
    test_default_template_has_no_checklist_to_invent()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
