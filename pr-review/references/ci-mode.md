# CI mode

When `pr-review` detects a non-interactive environment it switches to CI mode: findings are posted
as GitHub PR comments instead of an in-chat report, and Phase 6 is skipped (reactions on those
comments serve the same purpose, collected asynchronously by the `pr-review-react` skill).

## Detection

Check at startup before any phase runs:

```bash
[[ "${GITHUB_ACTIONS}" == "true" || "${CI}" == "true" ]]
```

The user can also force CI mode explicitly with a `--ci` flag if running from a script outside of
GitHub Actions.

## What changes in CI mode

**Phase 1+2 findings:** Post each matched finding as a separate PR comment. Embed the pattern name
in an HTML comment so `pr-review-react` can map reactions back to scores:

```
gh pr comment {pr_number} --body "{comment_body}"
```

Comment body format:

```
**[PR Review] {pattern_name}**

{finding details — file, line, what was flagged and why, historical frequency}

<!-- pr-review-pattern: {pattern_name} -->
```

Before posting, check whether a comment for this pattern already exists on the PR to avoid
duplicates on re-runs:

```bash
gh api /repos/{owner}/{repo}/issues/{pr_number}/comments \
  --jq '[.[] | select(.body | contains("<!-- pr-review-pattern: {pattern_name} -->"))] | length'
```

Skip posting if the count is greater than zero.

**Phase 3 (lint) findings:** Post as a single summary comment listing all failures. Lint findings
come from the project's own tooling and don't need individual reaction scoring.

**Phase 4 (acceptance criteria):** Post as a summary comment with the criteria table.

**Phase 5 (PR description):** Draft the description and post it as a comment for the author to
review and copy manually. Never auto-run `gh pr create` or `gh pr edit` in CI — there is no human
in the loop to confirm.

**Phase 6 (feedback loop):** Skip entirely. Reactions on the Phase 1+2 comments fill this role and
are collected by the `pr-review-react` skill.

## Getting the PR number in CI

In GitHub Actions, `${{ github.event.pull_request.number }}` is available as an env var. Pass it
to the skill or read it from `GITHUB_REF` if not available directly.