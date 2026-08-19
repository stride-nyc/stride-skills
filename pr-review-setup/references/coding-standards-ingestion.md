# Normalizing coding standards into coding-standards.md

This is step 6 of the setup workflow (see `SKILL.md`). Where the source material comes from changes
what "normalize" means, but the destination is always the same file:
`.claude/pr-review-data/<owner>-<repo>/coding-standards.md`.

## Case 1: an in-repo markdown file or directory

The easy case — e.g. an `AGENTS.md`, `CONTRIBUTING.md`, or a `docs/style-guide/` directory. Read it
directly. If it's a single reasonably-sized file, you can often use it close to verbatim (that's what
navigator.business.nj.gov's own `AGENTS.md` already is). If it's spread across many files, produce a
single consolidated document organized by topic (module structure, error handling, testing,
accessibility, etc.) rather than a wall of unrelated files concatenated in directory order.

## Case 2: a wiki (Confluence, Notion, GitHub wiki, ...)

Check what's actually available before asking the installer to do manual work: an MCP connector for
their wiki tool, or a raw export/URL they can hand you. For a large multi-page wiki, don't dump raw
HTML or every page verbatim — summarize per topic, the same way you would for Case 1's
multi-file case, and note which page each summary came from (a link back, if the format allows one)
so the installer can go verify or update the source later.

## Case 3: a public style guide URL

Fetch it, then **extract only what's relevant to the languages actually in this repo** rather than
reproducing the whole guide. A full copy of the Airbnb JavaScript style guide is not useful embedded
in a file meant to be read on every PR review; the 15-20 rules the repo's own linter config doesn't
already enforce are. Cross-reference against whatever lint config exists (Phase 3 territory, but
worth a glance here too) — a rule already enforced by ESLint/Rubocop/etc. doesn't need restating in
prose, since Phase 3 already catches violations mechanically.

## Case 4: nothing exists yet

Run `scripts/detect_languages.py` and present the suggested community standards for whatever
ecosystems it finds. Let the installer pick one (or several, for a polyglot repo), or say they'll
supply their own later. Either way, write what was decided into `coding-standards.md` — even if
that's just a pointer to an external URL for now rather than a summarized extract — so a future
review pass has *something* to check against instead of silently having no Phase 2 data.

## What the output should look like

Regardless of source, `coding-standards.md` should end up organized so the per-PR review pass
(`pr-review`, which only reads this file — it doesn't know or care where it came from) can act on it
directly:

```markdown
# Coding standards — <owner>/<repo>

**Source(s):** <where this came from — file path, wiki page links, or URL(s)>
**Last refreshed:** <date>

## <Topic, e.g. "Type safety">

<the actual rule(s), in plain language, close to how the source stated them>

## <Topic, e.g. "Error handling">

...
```

## Handling conflicts with Phase 1's review-patterns.md

If a written standard and a historical review pattern disagree — most often because the written
standard is stale and reviewers have moved on in practice, or because the pattern reflects an old
convention nobody bothered updating the docs for — don't silently pick one. Note the conflict in
`coding-standards.md` itself (a short "⚠️ conflicts with observed practice" callout under the relevant
rule) so the per-PR review pass can surface both sides rather than pretend they agree.
