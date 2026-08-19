---
name: pr-review
description: >-
  Runs a thorough automated pre-review of a pull request or branch before a human reviewer looks at
  it, using data already prepared by the companion `pr-review-setup` skill: cross-checks the diff
  against this repo's historical review feedback and coding standards, discovers and runs whatever
  linters/typecheckers already exist, verifies the change against the linked story's acceptance
  criteria, and drafts a PR description from the repo's own template. Use for "review my PR before I
  request review," "pre-review this branch," "check this diff before sending it out," "run the PR
  review checklist," or drafting/updating a pull request description — even unnamed. Only *consumes*
  prepared data; if none exists, says so and points to `pr-review-setup` instead of mining anything
  itself. Never posts/creates/edits on GitHub without showing the user first and getting confirmation.
compatibility: Reads data produced by the `pr-review-setup` skill at
  `.claude/pr-review-data/<owner>-<repo>/`. Run `pr-review-setup` first if that directory doesn't
  exist yet. Uses the GitHub CLI (`gh`) for anything that touches an actual PR (viewing, creating,
  editing) — read-only diff/log inspection works with plain `git`.
---

# PR pre-review

## What this is

The per-PR half of a two-skill pair. This skill has no mining, clustering, or history-fetching logic
of its own — all of that lives in the separate `pr-review-setup` skill, which is slow, occasional, and
judgment-heavy. This skill is meant to be fast and run on every single PR: it reads what setup already
prepared, discovers and runs the project's own tooling, and does the four things a human reviewer
would otherwise have to do by hand.

Full design rationale — why the phases are split this way, what's been built versus just designed,
and what was tested against a real monorepo — is in [`references/DESIGN.md`](references/DESIGN.md).

**Current status:** all five phases are implemented. Phases 1–2 (historical patterns, coding
standards) are produced by `pr-review-setup` and only *read* here. Phases 3–5 (linting, story
verification, PR description drafting) are implemented directly in this skill, below.

## Before anything else: check setup has run

Look for `.claude/pr-review-data/<owner>-<repo>/manifest.json` (owner/repo from `gh repo view --json
owner,name`, or from the git remote if `gh` isn't set up). If it's missing:

- Don't try to fetch or cluster anything yourself — that's `pr-review-setup`'s job, not this skill's.
- Tell the user no review data exists for this repo yet, and that running the `pr-review-setup` skill
  (e.g. "set up PR review for this repo") will build it. Offer to do that if they want, but as a
  clearly separate step, not folded silently into this one.
- You can still run Phases 3–5 without it (they don't depend on setup's output) — say so, and offer to
  proceed with just those if the user would rather not set up history/standards mining right now.

If the manifest exists but looks stale (`lastRefreshed` more than a few months old, or older than the
oldest commit on the current branch's base), mention that too — it's a judgment call for the user
whether to refresh before relying on it, not something to block on automatically.

## Phase 1+2 — Check the diff against historical patterns and standards

1. Get the current diff: `git diff <base-branch>...HEAD` (default base to `origin/main` unless told
   otherwise).
2. Read `.claude/pr-review-data/<owner>-<repo>/review-patterns.md` if it exists. For each pattern,
   check whether the diff matches its "check for this" instruction. Report matches with the specific
   file and line, and name which historical pattern it echoes (with its frequency, so the user can
   weigh a pattern seen 40 times differently from one seen twice) — point at the specific historical
   basis for flagging it, not just "this might be an issue."
3. Read `.claude/pr-review-data/<owner>-<repo>/coding-standards.md` if it exists, and cross-check
   against it too, in a clearly separate section — historical patterns and written standards are
   different kinds of evidence, and conflating them hides useful information (e.g. a standard the team
   has stopped enforcing in practice; call out any such conflicts explicitly).

## Phase 3 — Run the project's own linters and static analysis

1. Run `python3 scripts/discover_lint_commands.py --root .` to find what's already configured. It
   returns check-mode commands only (never `--fix`/`--write` variants) plus a `skipped_mutating` list
   (commands that exist but would mutate files — mention these exist without running them) and
   `ci_evidence` (lint/typecheck-related lines from `.github/workflows/*.yml`, useful for
   sanity-checking the discovered commands against what CI actually enforces).
2. Before running everything discovered, check for redundancy: in a workspace/monorepo, a root-level
   command that already fans out (e.g. `yarn workspaces foreach --all run lint`, `lerna run lint`,
   `nx run-many -t lint`) covers what each individual package's own `lint` script would do separately.
   Prefer running the root fan-out command once over running N per-package copies of the same check.
3. Run the remaining commands (via Bash), ideally scoped to changed files where the tool supports it,
   otherwise across the whole project. Capture pass/fail and the actual output for anything that fails
   — a reviewer needs the specific error, not just "lint failed."
4. Summarize results per tool: passed, failed (with the specific findings), or not run (and why — e.g.
   a discovered command needs a toolchain that isn't installed here).

## Phase 4 — Verify against the user story / acceptance criteria

1. Locate a ticket reference:

   ```bash
   python3 scripts/find_ticket_reference.py --branch "$(git branch --show-current)" \
     --commit-subject "$(git log <base-branch>..HEAD --pretty=format:%s | sed 's/^/--commit-subject /')"
   ```

   (or call `find_ticket_references()` directly if scripting this in Python is more convenient than
   shelling out per commit subject). This checks the branch name first, then commit-message trailers,
   per the same convention navigator.business.nj.gov's own tooling already uses — see the script's
   docstring for exactly which patterns it recognizes and why.
2. If a reference was found, try to fetch it: a connected tracker MCP (Jira, Linear, Asana, Azure
   DevOps) if one's available, or an org-specific fetch script if the repo has one (check for anything
   like `scripts/fetch_*ticket*.py` before assuming none exists). If fetching fails or nothing is
   configured, say so — don't silently fall back to guessing.
3. If no reference can be found or fetched, ask the user directly for a short description of the story
   and its acceptance criteria. Be explicit that this step only works as well as what they provide.
4. Verify the diff against each acceptance criterion following
   [`references/acceptance-criteria-verification.md`](references/acceptance-criteria-verification.md)
   — classify each as met/partially met/not addressed/not verifiable from the diff, and report all of
   them, not just the failures.

## Phase 5 — Draft (or update) the PR description

1. Find the repo's template: `python3 scripts/pr_template.py --find --root .`. If it returns multiple
   templates (a `.github/PULL_REQUEST_TEMPLATE/` directory), ask which one applies, or infer from
   context (e.g. a template named `bugfix.md` for a branch that looks like a bug fix) and confirm. If
   none is found, use `DEFAULT_TEMPLATE` from the script and mention that this repo has no PR template
   of its own — worth fixing once, separately, not something to paper over silently on every PR.
2. Check whether a PR already exists for this branch: `gh pr view --json body,title 2>/dev/null`.
   - **If one exists:** run `python3 scripts/pr_template.py --split-checklist <file with current
     body>` to separate the existing checklist from the description sections. Regenerate only the
     description sections from the current diff and the Phase 4 verification; splice the checklist
     back in **verbatim, byte for byte** — never reset someone's progress on it.
   - **If none exists:** draft fresh, using the full template structure (blank checklist included, if
     the template has one).
3. Fold in what the other phases found: the ticket link (from Phase 4), a one-line note on any
   unresolved lint findings (from Phase 3), and anything from Phase 1/2 the author should double-check
   before requesting review.
4. Formatting matters for how GitHub renders it: no em dashes (use a comma, period, or parentheses
   instead), and end every list item/paragraph with a real line break with a blank line between
   paragraphs — GitHub does not collapse soft-wrapped text the way some editors do.
5. **Show the complete title and body in chat and get explicit confirmation before running `gh pr
   create` or `gh pr edit`.** This is a side-effecting GitHub action on the user's account and must
   never happen silently, no matter how confident the draft is.

## Final report

Summarize all five phases together: what was checked, what data it was checked against (with the
manifest's `lastRefreshed` date so the user knows how current Phases 1–2 are), pass/fail from Phase 3,
the acceptance-criteria table from Phase 4, and the drafted PR description from Phase 5 awaiting
confirmation. If any phase was skipped (no setup data, no ticket found and user declined to describe
one, no lint tooling discovered), say so explicitly in the summary rather than letting its absence
just look like a clean bill of health.

## Files

- `scripts/discover_lint_commands.py` — Phase 3 discovery. Fixture-tested against real script blocks
  from navigator.business.nj.gov's own `package.json` files; self-test via `--self-test`.
- `scripts/find_ticket_reference.py` — Phase 4 ticket-reference extraction from branch names/commit
  subjects. Self-test via `--self-test`.
- `scripts/pr_template.py` — Phase 5 template discovery and checklist-preserving split. Fixture-tested
  against navigator.business.nj.gov's real PR template; self-test via `--self-test`.
- `references/acceptance-criteria-verification.md` — how to classify and report Phase 4 findings.
- `references/DESIGN.md` — full five-phase design, including why this skill and `pr-review-setup` are
  split the way they are.
