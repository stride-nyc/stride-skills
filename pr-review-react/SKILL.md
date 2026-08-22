---
name: pr-review-react
description: >-
  Reads GitHub 👍/👎 reactions on comments posted by pr-review in CI mode and updates
  pattern-scores.json to feed team feedback back into the review scoring system. Run periodically
  or after a batch of PRs merge. Use for "collect reaction feedback from PRs", "sync review scores
  from GitHub reactions", "update pattern scores from PR comments", or "run pr-review-react".
  Companion to the `pr-review` skill — requires pr-review to have run in CI mode on at least one PR.
compatibility: Requires `pr-review` to have run with CI=true or GITHUB_ACTIONS=true, which posts
  findings as GitHub PR comments with embedded pattern metadata. Reads and writes
  `.claude/pr-review-data/<owner>-<repo>/pattern-scores.json`. Uses the GitHub CLI (`gh`).
---

# pr-review-react

Closes the feedback loop for teams running `pr-review` automatically in CI. When `pr-review` runs
non-interactively it posts each Phase 1+2 finding as a GitHub PR comment. Team members react with
👍 (relevant — good catch) or 👎 (not relevant). This skill collects those reactions, maps them
back to patterns, and updates `pattern-scores.json` — the same file Phase 6 updates interactively.

Each 👍 from a unique reviewer adds +2 to the pattern's score; each 👎 adds −1. Multiple people
reacting compounds naturally, which is the intended behaviour for team-wide signal.

## Steps

1. Determine owner/repo: `gh repo view --json owner,name`.
2. Run `python3 scripts/collect_reactions.py --root . [--pr <number>] [--limit 20] [--dry-run]`
   to collect reaction data across recently merged PRs (or a specific one).
3. Show a summary of proposed score changes — pattern name, current score, delta, new score — and
   confirm before writing.
4. Write the updated `pattern-scores.json`. If running in CI (no interactive confirmation possible),
   commit and push it directly; if running interactively, show the diff and wait for confirmation.

Use `--dry-run` to preview changes without writing anything.

## Files

- `scripts/collect_reactions.py` — fetches PR comments and reactions via `gh api`, computes score
  deltas, outputs a structured summary. Self-test via `--self-test`.
- `scripts/tests/test_collect_reactions.py` — fixture-based tests for comment parsing and delta
  computation.
- `references/github-action.md` — sample GitHub Actions workflow for automated reaction collection
  on PR merge.