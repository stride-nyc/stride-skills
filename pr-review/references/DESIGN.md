# Automated PR Pre-Review Skill — Architecture

Status: v3 · 2026-08-16
Test repo used to ground this design: [`newjersey/navigator.business.nj.gov`](https://github.com/newjersey/navigator.business.nj.gov)
Session scope: all five phases implemented and tested (fixture-based, plus direct validation against
the real navigator.business.nj.gov checkout where the sandbox's network limits allowed it — see
Limitations for the one piece that couldn't be: a live `gh api` pull of real PR history).
v2 change: split into two Claude Code skills (`pr-review-setup`, `pr-review`) sharing a fixed data
directory, instead of one skill whose SKILL.md carried both install and per-PR steps — see
"Two-part lifecycle" below.
v3 change: built Phases 2–5 (coding standards ingestion, linter discovery, ticket/acceptance-criteria
verification, PR description drafting) — previously designed only. Each phase's deterministic half is
a tested script; each phase's judgment half is a references/ doc, same division of labor Phase 1
established.

## Goal

Give an org a pair of Claude Code skills that run a thorough automated pass over a pull request
before a human reviewer ever looks at it — catching the things a human would otherwise have to say,
so human review time gets spent on judgment calls instead of repeated nitpicks. It needs to work for
any organization and any language, which means it must discover an org's conventions rather than
assume them.

## Why navigator.business.nj.gov is a good test repo

Pulling it down and reading its top-level files turned up almost the exact shape of infrastructure
this skill is meant to generalize, which makes it a strong design reference even before phases 2–5
are built:

- `AGENTS.md` (symlinked from `CLAUDE.md`) is already a hand-written coding-standards document —
  module structure, TypeScript conventions, async patterns, logging, error handling, accessibility
  rules, and a "Done Criteria" checklist. This is exactly the artifact Phase 2 needs to ingest.
- `.github/pull_request_template.md` has a real checklist (rebase, self-review, no relative imports,
  migration files, CMS config, env values) that a PR description draft needs to reproduce faithfully.
- `.claude/commands/create-pr-navigator.md` is a hand-rolled version of Phase 5 already: it reads the
  diff, finds the ticket number from the branch name or commit trailers, calls
  `scripts/fetch_ado_ticket.py` to pull the Azure DevOps ticket's title/description/acceptance
  criteria, and drafts the PR body — while explicitly preserving the checklist state on updates. This
  validates the Phase 4 + Phase 5 design below almost line for line.
- It's a Yarn 4 workspaces monorepo (TypeScript, Next.js, Express/Lambda, Python scripts, a separate
  pnpm/Biome sub-package) with ESLint, Prettier, Jest, and `yarn typecheck` all wired up — a good
  stress test for "discover the linters, don't hardcode them."
- CONTRIBUTING.MD is explicit that "reviewers do not check for formatting or style issues — those are
  enforced automatically by CI. Human review time is for things machines cannot catch." That is the
  thesis of this entire skill, stated independently by a real engineering org.

One inconsistency worth flagging back to that repo's own maintainers, spotted while reading: CONTRIBUTING.MD
says "Biome is enforced automatically on every commit and in CI," but the root and `web`/`api`/`shared`
packages actually run ESLint + Prettier (`.eslintrc.json`, `.prettierrc`); only `packages/static-site` uses
Biome. Not a defect in the design, just a reminder that even good docs drift from reality — which is
exactly why Phase 3 discovers tooling from config files instead of trusting prose.

## Non-goals

- This is not a CI gate. It runs interactively, before the human review request, and it drafts
  findings for the author to accept or dismiss — it never blocks a push or silently fixes code.
- It doesn't replace linters/CI; Phase 3 runs the org's *existing* tools rather than reimplementing
  static analysis.
- It doesn't auto-post to GitHub without confirmation. Posting a PR comment, creating a PR, or editing
  a PR description are all side-effecting actions and require the user's explicit go-ahead each time,
  consistent with how any assistant acting on someone's GitHub account should behave.

## Two-part lifecycle

This isn't one skill — it's two, on purpose. **`pr-review-setup`** does the install-time pass (run
once per repo, then periodically refreshed): the expensive, slow-changing, judgment-heavy work of
mining history and locating standards. **`pr-review`** does the per-PR pass (run every time someone
wants a pre-review) and is deliberately lean — it has no fetching or clustering logic of its own, it
only reads what setup already produced. Nobody wants to re-download years of review comments before
every review, and nobody wants the fast, every-PR skill's SKILL.md cluttered with install-only steps
it doesn't need on 99% of its invocations.

```
pr-review-setup (once, then quarterly-ish refresh)
  Phase 1: Mine PR review history      -> review-patterns.md
  Phase 2: Ingest coding standards      -> coding-standards.md

pr-review (every time)
  Phase 3: Run linters/static analysis  -> lint-results.md (ephemeral)
  Phase 4: Verify against user story    -> story-verification.md (ephemeral)
  Phase 5: Draft/update PR description  -> shown to user, posted only on confirmation
```

The two skills' *only* contract is a fixed, shared data directory in the target repo:
`.claude/pr-review-data/<owner>-<repo>/`, containing `manifest.json` (source paths/URLs and a
`lastRefreshed` timestamp), `raw-comments.jsonl`, `review-patterns.md`, and eventually
`coding-standards.md`. It deliberately lives outside either skill's own installed directory — under
`.claude/skills/pr-review-setup/` or `.claude/skills/pr-review/`, depending on how the org installs
skills — so either skill can be reinstalled, updated, or run from a different machine without the
other needing to know or care where it's installed. `pr-review` never reaches into `pr-review-setup`'s
files or vice versa; it only reads this shared path. The installer is asked whether to commit that
directory (shared team benefit, reviewable) or gitignore it (personal, always-fresh).

---

## Phase 1 — Mine PR review history (built this session)

**Goal:** find the things human reviewers at this org keep having to say, so the automated pass can
catch them before a human has to say them again.

**Inputs:** repo slug (auto-detected via `gh repo view` when run inside a checkout), lookback window
(default 2 years, configurable), and a bot-account denylist (auto-populated with common bot logins:
dependabot, renovate, github-actions, and anything with `user.type == "Bot"` per the GitHub API).

**Mechanism:**

1. `gh pr list --state merged --search "merged:>=<cutoff-date>"` enumerates merged PRs in the window.
   Merged-only is deliberate — abandoned/closed-without-merge PRs skew toward incomplete work, not
   the kind of feedback that generalizes.
2. For each PR, fetch three comment surfaces via `gh api --paginate`: inline review comments
   (`pulls/{n}/comments`), review verdicts with summary bodies (`pulls/{n}/reviews`), and general
   conversation comments (`issues/{n}/comments`). Reviewers put different kinds of feedback in
   different places — a inline nit versus a "this whole approach needs to change" review-level
   comment — and both matter.
3. Filter out bot authors, empty/approval-only bodies (`lgtm`, `+1`, `looks good`, single emoji), and
   comments under a length threshold that are almost never substantive.
4. Write everything else to an append-only JSONL file, checkpointing the last fully-processed PR
   number after each PR so a rate-limit hit or interrupted run resumes instead of restarting from
   scratch. This matters in practice: `gh api` unauthenticated GitHub App tokens hit secondary rate
   limits fast when paging through hundreds of PRs.
5. **Deliberately stops short of automated NLP clustering.** The script's job ends at "clean,
   deduplicated, structured raw comments." Turning free-text review feedback into named categories
   ("reviewers frequently flag missing null checks on API responses," "reviewers frequently ask for
   tests on new domain-logic branches") is a judgment call that regex/keyword clustering does badly
   and Claude does well when reading the same batch of comments a human reviewer would have read.
   `references/mine-history-clustering.md` gives Claude the taxonomy to produce: category name,
   one-line description, 2–3 anonymized example quotes, affected file types, frequency, and a
   concrete "check for this" instruction the Phase 3/5 review pass can act on later.

**Output:** `.claude/pr-review-data/<owner>-<repo>/raw-comments.jsonl` (intermediate,
gitignore-by-default) and `review-patterns.md` in the same directory (the durable artifact, meant to
be committed and refreshed periodically as conventions evolve, and read by the separate `pr-review`
skill).

**Built and tested this session** — lives entirely in the `pr-review-setup` skill:
`pr-review-setup/scripts/mine_pr_history.py` plus its fixture-based self-test. The `pr-review` skill
has no copy of this script and no fetching logic at all — it only reads the JSONL/markdown this one
produces. Live testing against the real navigator.business.nj.gov PR history was not possible from
this sandbox (see Limitations below); the script is ready for a real dry run on a machine with an
authenticated `gh` CLI.

---

## Phase 2 — Ingest coding standards (built this session)

**Goal:** a second, standards-based pass distinct from Phase 1's "what has this specific team
historically complained about." An org's *written* standards (even unenforced ones) matter
independently of what reviewers happened to catch.

**Mechanism:**

1. At install time, ask the installer where standards live. In descending order of how common this
   turned out to be while reading real repos: a markdown file or directory in-repo (navigator's own
   `AGENTS.md` is exactly this shape), a wiki (Confluence/Notion/GitHub wiki — reachable via whatever
   MCP connector the org has, or a raw export), or a public style guide URL (Airbnb JS style guide,
   PEP 8, Google style guides, etc.).
2. If none exist, don't leave the installer empty-handed: detect the primary language(s) from the
   repo's manifest files and suggest the well-known community standard for each (e.g. **TypeScript /
   JavaScript** → Airbnb or the TypeScript-ESLint recommended rules; **Python** → PEP 8 + Google Python
   Style Guide; **Go** → Effective Go + Google Go Style Guide; **Ruby** → the Ruby Style Guide;
   **Java** → Google Java Style Guide). The installer picks one or points to their own.
3. Normalize whatever is found into `.claude/pr-review-data/<owner>-<repo>/coding-standards.md` —
   a single, Claude-readable document, alongside Phase 1's `review-patterns.md`. For a large
   multi-page wiki, summarize per-topic rather than dumping raw HTML; for a public style guide,
   extract the rules relevant to the languages actually in the repo rather than the whole document.
   This is `pr-review-setup` work, same as Phase 1 — `pr-review` only ever reads the result.
4. Re-fetching on refresh should diff against the previous version so the installer can see what
   changed in the org's standards since the last install, not just silently replace it.

**Built and tested this session** — `pr-review-setup/scripts/detect_languages.py` handles step 2's
language detection and standards suggestion deterministically (fixture-tested, plus verified against
the real navigator.business.nj.gov checkout: correctly detects its node+python polyglot shape across
all 9 `package.json` files in the workspace). Steps 1, 3, and 4 (finding/summarizing an in-repo doc,
wiki, or URL) are inherently judgment calls and are specified as instructions for Claude in
`pr-review-setup/references/coding-standards-ingestion.md` rather than as script logic — there's
nothing to unit-test there beyond "does the guidance make sense," the same reasoning as Phase 1's
clustering step.

**Interaction with Phase 1:** Phase 1 patterns and Phase 2 standards can overlap or even conflict (a
written standard the team has stopped enforcing in practice, or a historical pattern that contradicts
the written doc). When they conflict, the review pass should surface both and say so explicitly rather
than picking one silently — that's a signal the org's docs are stale, which is useful information on
its own.

---

## Phase 3 — Run linters and static analysis (built this session)

**Goal:** don't reinvent static analysis — run what the project already has, so the "catch what
machines can catch" pass is defined by the project's own tooling instead of a hardcoded list.

**Discovery, in order:**

1. Look for a `package.json` `scripts.lint` / `scripts.typecheck` / `scripts.test` (and workspace
   variants — navigator.business.nj.gov's root `lint` script is
   `yarn workspaces foreach --all run lint`, which fans out per-package).
2. Look for known config files regardless of language: `.eslintrc*`, `biome.json`, `.prettierrc*`,
   `pyproject.toml` (ruff/black/mypy sections), `.flake8`, `Rubocop.yml`, `.golangci.yml`,
   `Cargo.toml` (clippy is implicit), `.editorconfig`.
3. Look for CI workflow files (`.github/workflows/*.yml`) and read what commands they actually run —
   this is often the most reliable source of truth, since it's what "green CI" really means to the
   team. navigator.business.nj.gov's `build-and-test.yml` is the canonical example: whatever commands
   that workflow runs are, by definition, this repo's real quality gate.
4. Run only the read-only/check-mode variants (`--check`, lint without `--fix`, typecheck) against the
   changed files (or the whole project if the tool doesn't support scoping) — never the mutating
   `--fix`/`--write` variants without being asked, since silently reformatting someone's PR is a
   surprise, not a review.

**Output:** a structured, ephemeral `lint-results.md` for this PR — tool, file, line, message —
merged into the final review report. Nothing here needs to persist between runs.

**Built and tested this session** — `pr-review/scripts/discover_lint_commands.py` implements
discovery steps 1–3 as pure filesystem/text inspection (no execution; running the discovered commands
is left to the review pass itself, via Bash, since that needs the live repo's installed toolchain).
Fixture-tested against the *actual* `scripts` blocks from navigator.business.nj.gov's root and
`web/package.json` — including the exact case that makes this hard: the repo has both a mutating
`prettier` script and a checking `prettier:check` script with nearly identical names, and both a
`test` and root-level `test:ci`. The discovery script correctly includes `lint`, `typecheck`,
`prettier:check`, and `test:ci` while excluding `lint:fix` and bare `prettier` — verified against the
real repo directly, not just the fixtures (see the script's test file for the exact commands each
produced).

---

## Phase 4 — Verify against the user story / acceptance criteria (built this session)

**Goal:** confirm the diff actually does what the ticket asked, not just that it's well-formatted.

**Locating the story:**

1. Check what's already in context: PR description, branch name, or commit trailers for a ticket
   reference. navigator.business.nj.gov's own `create-pr-navigator.md` command shows a real pattern
   worth reusing directly: check the branch name for a `#NNNNN` suffix first, then fall back to
   `[AB#NNNNN]` commit-message trailers (their commit-msg hook enforces that prefix, so it's the more
   reliable source when present).
2. If a ticket ID is found, try to fetch it: a connected tracker MCP (Jira, Linear, Asana, Azure
   DevOps) if the org has one, or a repo-specific fetch script if it exists (again,
   `scripts/fetch_ado_ticket.py` in the test repo is exactly this — an org-specific script the skill
   should try before giving up).
3. If no ticket can be found or fetched, don't guess. Ask the user directly for a short description of
   the story and its acceptance criteria, and be explicit that this step only works as well as what
   they type in — vague acceptance criteria in means a vague verification pass out.

**Verification:** once acceptance criteria exist (fetched or user-supplied), walk them one at a time
against the diff and classify each as met, partially met, not addressed, or not verifiable from the
diff alone (e.g. "must be accessible to screen readers" often needs a manual check a diff can't
settle). Report every criterion's status — silently dropping the ones that look satisfied would hide
exactly the information a human reviewer needs to skip re-checking them.

**Built and tested this session** — `pr-review/scripts/find_ticket_reference.py` implements step 1
(locating a reference) deterministically: branch-name suffix first, then Azure DevOps `[AB#NNNNN]`
commit trailers exactly as navigator.business.nj.gov's own tooling does, then generic GitHub `#123`
and Jira/Linear-style `ABC-123` patterns for orgs using other trackers, with a denylist to avoid
false positives like `UTF-8`/`ISO-8601` being read as ticket keys. Steps 2–3 (fetching, asking the
user) and the verification pass itself are judgment calls, specified in
`pr-review/references/acceptance-criteria-verification.md` rather than as script logic.

---

## Phase 5 — Draft the PR description (built this session)

**Goal:** produce a PR description the author can send as their own, using whatever template the repo
already has.

**Mechanism:**

1. Look for `.github/pull_request_template.md` (or `PULL_REQUEST_TEMPLATE.md`, or a
   `.github/PULL_REQUEST_TEMPLATE/` directory with multiple templates). Use it verbatim as the
   structure; don't invent a different shape.
2. If a PR already exists for the branch (`gh pr view`), treat this as an update, not a fresh draft:
   regenerate the descriptive sections from the current diff, but preserve any checklist section
   (ticked/unticked state) byte-for-byte, exactly as navigator.business.nj.gov's own
   `create-pr-navigator.md` command already does. Silently resetting someone's checklist progress on
   every re-run would make the feature actively annoying.
3. If no template exists at all, fall back to a minimal generic structure (summary, why, how to test,
   related issue) and offer to work with the installer to write a real template for the repo as part
   of install — a repo with no PR template is itself a gap worth closing once, not something to paper
   over on every single PR.
4. Fold in the outputs of the other phases: link the verified acceptance criteria, note any
   unresolved lint findings, and flag anything from Phase 1/2 that the author should double check
   before requesting review.
5. Show the full title and body in chat and get explicit confirmation before running
   `gh pr create`/`gh pr edit` — this is a side-effecting GitHub action and must never happen silently,
   matching how the rest of this environment treats "send on someone's behalf" actions.

**Built and tested this session** — `pr-review/scripts/pr_template.py` implements template discovery
(step 1, including the multi-template-directory case and case-insensitive filename matching) and
checklist-preserving splitting (step 2) deterministically. Fixture-tested against
navigator.business.nj.gov's real `.github/pull_request_template.md`, copied verbatim into the test
file — including a case with some checkboxes ticked, to confirm the split preserves exact byte-for-byte
state rather than just the checklist's text. Steps 3–5 (drafting prose, folding in other phases'
findings, the confirmation gate before any `gh pr create`/`gh pr edit`) are SKILL.md instructions for
Claude, not script logic — drafting a PR description is exactly the kind of judgment call this design
keeps out of scripts throughout.

---

## Cross-cutting design decisions

**Language-agnostic by discovery, not by configuration.** Every phase inspects the repo (manifest
files, config files, CI workflows) to figure out what tools/conventions exist, rather than asking the
installer to declare a language up front. This is what makes the skill "generic" rather than
JS-specific — navigator.business.nj.gov alone mixes TypeScript, Python, and CDK/infra config in one
repo, and a single hardcoded toolchain would miss two of the three.

**Everything expensive is cached; everything side-effecting is confirmed.** Phases 1–2 are the slow,
API-heavy install steps and get cached per-repo. Phases 3–5 run fresh every time (fast, local) but
their side-effecting outputs (posting PR comments, creating/editing the actual PR) always stop for
confirmation — never auto-posted.

**Every pass explains itself, not just states a verdict.** "Reviewers frequently flag X" needs example
quotes; "criterion not met" needs which criterion and why; "template not found" needs to say so and
offer the fallback. The point of the skill is to save a human reviewer's time, which means its output
has to be actionable and specific enough to skip the back-and-forth a human would otherwise need.

## Limitations hit while building this in a cloud sandbox

Worth recording since they explain why Phase 1 (and only Phase 1) is validated with fixtures rather
than a live pull:

- This session's sandbox has `git` access to `github.com` (clone worked) but a proxy in front of
  `api.github.com` blocks REST/GraphQL calls outright, and `gh` itself isn't installed. `WebFetch`
  against `github.com` pages is also blocked by that site's `robots.txt`. None of this reflects a
  limitation of the design — a real Claude Code session on a developer's machine with an authenticated
  `gh` CLI (the target environment, per the chosen "gh CLI" access method) has none of these
  restrictions.
- Because of that, Phase 1's script is validated against realistic fixture data shaped like real
  `gh api` responses (see `pr-review-setup/scripts/tests/`) rather than navigator.business.nj.gov's
  actual three years of PR comments. The fixture content is modeled on real patterns visible in that
  repo's own `AGENTS.md` and PR checklist (e.g. flagging `any` usage, missing tests on new domain
  logic, relative imports) so the clustering step has something realistic to chew on, but it is not
  real historical data. A worked example built from that fixture run — raw comments through to a
  clustered `review-patterns.md` — lives in `example-output/` alongside this doc, kept out of both
  packaged skills so nobody installs someone else's fake NJ data by accident. A live dry run on an
  authenticated machine is the natural next step.
- Phases 2–5 don't touch `api.github.com` at all (Phase 2's language detection is a filesystem walk,
  Phase 3's discovery is filesystem/text inspection, Phase 4's ticket-reference extraction is regex
  over a branch name and commit subjects, Phase 5's template handling is filesystem + text splitting),
  so every one of them was validated directly against the real cloned navigator.business.nj.gov
  checkout in this sandbox, not just fixtures — see each phase's "Built and tested this session" note
  above for specifics.

## Next steps

1. Live dry run of Phase 1 (and Phase 2's wiki/URL ingestion paths, which need a live MCP connector or
   `WebFetch` this sandbox couldn't exercise either) against navigator.business.nj.gov or the
   installer's own repo, on a machine with `gh` authenticated.
2. Actually execute Phase 3's discovered lint/typecheck/test commands against a real installed
   toolchain (this session validated discovery — which commands to run — but not execution, since that
   needs `node_modules`/`pip install`/etc. actually present).
3. Try Phase 4 against a real connected tracker MCP (Jira/Linear/Azure DevOps) to validate the
   fetch-after-locate step, which this session could only specify, not exercise.
4. Try Phase 5 end to end against a real open PR on the test repo (or any repo) to see the drafted
   description and confirmation flow in practice, including the multi-template-directory case if a
   repo with one is available.
5. Run the full skill-creator eval loop (test prompts, with/without-skill comparison, benchmark
   viewer) now that all five phases exist and can be exercised end to end.
