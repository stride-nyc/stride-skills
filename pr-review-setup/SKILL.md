---
name: pr-review-setup
description: >-
  One-time (then periodically refreshed) setup for the pr-review skill: mines years of this repo's
  merged-PR review comments via the GitHub CLI and clusters them into recurring patterns reviewers
  keep flagging, then ingests the org's written coding standards (an in-repo doc, a wiki, a public
  style guide, or a suggested community standard if none exists). Writes its output to a fixed,
  shared data directory that the separate `pr-review` skill reads from — this skill never runs a
  per-PR review itself. Use this whenever the user asks to "set up PR review for this repo," "install
  the PR review skill," "mine our PR history for review patterns," "refresh our review data," "index
  our coding standards," or "find our style guide" — even if they don't name this skill directly. If
  someone asks for a per-PR review and no data exists yet for this repo, this is the skill to run
  first.
compatibility: Requires the GitHub CLI (`gh`) installed and authenticated, and to be run from inside a
  git checkout of the target repo.
---

# PR review — setup

## What this is

The install-time half of a two-skill pair. This skill does the slow, API-heavy, judgment-heavy work of
building up a picture of how this specific team reviews code — and nothing else. It never reviews a
PR. The companion `pr-review` skill does that, and only reads what this skill produces; it doesn't
know how to mine or cluster anything itself. Keeping these separate means the fast, every-PR skill
stays lean, and the slow, occasional-use skill can be re-run (a full history remine, a standards
refresh) without touching the review logic at all.

Full design rationale is in [`references/DESIGN.md`](references/DESIGN.md) — read it for the "why,"
including why clustering is a judgment call left to you rather than automated in the script, and what
was actually tested versus designed-but-not-built when this was created.

**Current status:** Phase 1 (mine PR history) and Phase 2 (coding standards ingestion) are both
implemented below. Phases 3–5 (linting, story verification, PR description drafting) live in the
`pr-review` skill, not here — this skill only ever prepares data, it never reviews a PR.

## The shared data contract

Everything this skill produces goes under a fixed path in the target repo, independent of where either
skill itself happens to be installed:

```
.claude/pr-review-data/<owner>-<repo>/
├── manifest.json          # what's been built, when, and how (see step 7 below)
├── raw-comments.jsonl      # intermediate — filtered, structured review comments
├── review-patterns.md      # Phase 1 durable output
└── coding-standards.md     # Phase 2 durable output
```

`<owner>-<repo>` is the GitHub owner/name joined with a hyphen (e.g. `newjersey-navigator.business.nj.gov`).
This is the *only* contract between the two skills — `pr-review` never reaches into this skill's own
directory, and this skill never reaches into `pr-review`'s. That's deliberate: either skill can be
installed, updated, or reinstalled independently without breaking the other, as long as this path and
the files in it keep their shape.

## Setup workflow (run once per repo, refresh periodically)

1. Confirm you're inside a git checkout of the target repo and `gh auth status` succeeds. If `gh`
   isn't installed or authenticated, stop and tell the user what to run — don't attempt API calls
   without it.
2. Determine `<owner>-<repo>` via `gh repo view --json owner,name` (or let the mining script do this
   itself — it auto-detects when `--owner`/`--repo` are omitted).
3. Ask how far back to mine PR history (default 2 years — say so and let them override) and whether
   `.claude/pr-review-data/` should be committed to the repo (shared, reviewable by the team) or
   gitignored (personal, always current, no risk of stale data getting reviewed as if fresh). Note
   the decision either way — it goes in the manifest.
4. Run the mining script:

   ```bash
   python3 scripts/mine_pr_history.py --years <N> --out .claude/pr-review-data/<owner>-<repo>
   ```

   This is the deterministic part only: it enumerates merged PRs in the window, pulls their review
   comments, review verdicts, and conversation comments via `gh api`, filters out bots and low-signal
   noise ("lgtm", "+1", etc.), and writes `raw-comments.jsonl`. It checkpoints as it goes
   (`.checkpoint.json` in the same directory) so a rate-limit hit or interruption resumes instead of
   restarting. Expect this to take a while on a repo with years of history — `gh api` secondary rate
   limits mean it deliberately paces itself.

5. Once it finishes, **you** (not the script) turn the raw comments into patterns — this is a
   judgment call that clustering code does badly. Read
   [`references/mine-history-clustering.md`](references/mine-history-clustering.md) for the exact
   taxonomy, then read `raw-comments.jsonl` and write `review-patterns.md` in the same directory:
   named categories of recurring feedback, each with a short description, 2–3 anonymized example
   quotes (strip usernames), the file types/areas it shows up in, how often, and a concrete
   instruction the `pr-review` skill can act on ("flag any `any` cast introduced outside a declared
   `unknown`-narrowing boundary").
6. **Ingest coding standards (Phase 2).** Ask the installer where their standards live: an in-repo
   markdown file/directory, a wiki, a public style guide URL, or "we don't have one yet." Then follow
   [`references/coding-standards-ingestion.md`](references/coding-standards-ingestion.md) for how to
   turn whatever they point you to into `coding-standards.md` — the four cases (in-repo doc, wiki,
   URL, nothing yet) each need slightly different handling, and that file walks through all of them.

   If they have nothing yet, run:

   ```bash
   python3 scripts/detect_languages.py --root .
   ```

   to see which language ecosystems this repo actually uses, and present the suggested community
   standards for each (Airbnb/typescript-eslint for JS/TS, PEP 8/Google for Python, Effective
   Go/Google Go Style for Go, and so on — the script prints the full list with URLs). Let them pick
   one per ecosystem, or say they'll supply their own later; either way, record the decision in
   `coding-standards.md` rather than leaving it unwritten.

   This step is genuinely optional to *finish* on the first run — an installer who wants to come back
   to it later shouldn't be blocked from finishing setup. Just don't silently skip mentioning it: say
   plainly whether `coding-standards.md` was produced this run or deferred.

7. Write/update `manifest.json`:

   ```json
   {
     "repo": "<owner>/<repo>",
     "lastRefreshed": "<ISO date>",
     "historyWindowYears": <N>,
     "committedToRepo": <true|false>,
     "codingStandardsSource": "<where coding-standards.md came from, or null if step 6 was deferred>"
   }
   ```

   This is the file `pr-review` checks for to know whether setup has run at all — always write it,
   even on a refresh, so its `lastRefreshed` stays meaningful.

## Files

- `scripts/mine_pr_history.py` — Phase 1 fetch/filter/checkpoint script. Run it, don't reimplement
  it; it handles pagination, bot filtering, and resumability correctly, and by hand those are easy to
  get subtly wrong (e.g. forgetting `--paginate`, or re-fetching PRs already processed).
- `scripts/detect_languages.py` — Phase 2 helper: scans the repo for manifest files and maps them to
  language ecosystems, with a suggested community standard per ecosystem for when the installer has
  none of their own.
- `scripts/tests/` — fixture-based self-tests for both scripts (no `gh`/network required):
  `python3 scripts/mine_pr_history.py --self-test` and `python3 scripts/detect_languages.py
  --self-test`. Run these if you've changed either script, not as part of a normal setup pass.
- `references/mine-history-clustering.md` — the taxonomy/instructions for turning raw comments into
  `review-patterns.md`. Read this before step 5.
- `references/coding-standards-ingestion.md` — how to turn each of the four standards sources into
  `coding-standards.md`. Read this before step 6.
- `references/DESIGN.md` — full five-phase design and the reasoning behind the setup/review split.
