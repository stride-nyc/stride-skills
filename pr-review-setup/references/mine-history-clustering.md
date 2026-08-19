# Clustering raw review comments into patterns-to-avoid

Input: `.claude/pr-review-data/<owner>-<repo>/raw-comments.jsonl`, one JSON object per line:

```json
{
  "pr_number": 4821,
  "pr_url": "https://github.com/<owner>/<repo>/pull/4821",
  "surface": "review_comment",
  "path": "web/src/lib/session.ts",
  "author": "some-login",
  "created_at": "2024-11-03T18:22:04Z",
  "body": "This should use the shared `getSession` helper instead of hitting the API client directly."
}
```

`surface` is one of `review_comment` (inline diff comment), `review` (top-level review verdict body),
or `issue_comment` (general PR conversation). Bots and low-signal noise are already filtered out by
the script — everything in this file was written by a human and has something to say.

## What you're building

`review-patterns.md`, structured as a list of pattern entries. Aim for the recurring, generalizable
stuff — not a one-off comment that happened once in four years. As a rough bar: a pattern worth
recording usually shows up at least 3-4 times across distinct PRs (in your own words if the exact
wording varies, since reviewers rarely repeat themselves verbatim). Something that happened exactly
once, however sharply worded, is noise for this purpose — it doesn't tell the review pass anything
generalizable about what to check for on the *next* PR.

For each pattern, write:

```markdown
### <short, specific name — e.g. "Missing null checks on external API responses">

**Seen:** <N> times across <M> PRs, most recently <date>
**Where:** <file types / areas, e.g. "API route handlers", "*.tsx components", "database migrations">

<1-2 sentence description of the pattern in plain language>

**Example feedback** (anonymized):
> "<verbatim quote 1>"
> "<verbatim quote 2>"

**Check for this:** <a concrete, actionable instruction the per-PR review pass can literally act on —
not "watch for null issues" but "flag any `.data` access on an API response object that isn't guarded
by an `if (response.ok)` or equivalent check first">
```

## Guidance

- **Anonymize quotes.** Strip usernames and any text that names a specific person, even in a
  self-deprecating or complimentary way ("nice catch by @so-and-so on the last PR"). The pattern
  matters; who said it doesn't.
- **Prefer specific over vague.** "Reviewers often ask for better error handling" is nearly useless to
  a future automated check. "Reviewers repeatedly ask for a specific error type instead of re-throwing
  the caught error unchanged" is something a check can actually look for.
- **Group near-duplicates, don't split hairs.** "Add a test for this" and "needs test coverage" and
  "can you add a unit test here" are the same pattern with different wording — one entry, count all
  three occurrences.
- **Separate style/formatting from substance.** If the repo has CI-enforced formatting (Prettier,
  Biome, gofmt, etc.), historical comments asking for formatting fixes predate that tooling and aren't
  useful going forward — skip them. Comments about naming, structure, or missing error handling are
  substance and belong in the output even if a linter could theoretically catch some of them.
- **Note contradictions if you see them.** If two eras of the same repo's history show opposite
  guidance (e.g. older PRs demand default exports, newer ones demand named exports), record the more
  recent one as the active pattern and mention the shift in one line rather than silently picking a
  side.
- **It's fine to end up with a short list.** A well-run repo with a small, disciplined team might
  genuinely only have 5-6 recurring patterns after years of history. Don't manufacture categories to
  pad the list — a shorter, higher-confidence `review-patterns.md` is more useful than a padded one.
- **Sort by frequency**, most common first. That's the order the review pass should check them in, and
  the order a human skimming the file would want too.
