# Self-test for `mine_pr_history.py`

No `gh` CLI, GitHub token, or network access needed -- everything runs against the
JSON fixtures in `fixtures/`, which are shaped exactly like real `gh api` responses
for `pulls/{n}/comments`, `pulls/{n}/reviews`, and `issues/{n}/comments`.

Run it with:

```bash
python3 ../mine_pr_history.py --self-test
# or
python3 test_mine_pr_history.py
```

## Why fixtures instead of a live run

This skill was built in a sandbox where `api.github.com` is not reachable (see
`DESIGN.md`'s Limitations section) and `gh` isn't installed, so a live pull against
navigator.business.nj.gov's real PR history wasn't possible from here. The fixtures
below are invented, but modeled on real conventions visible in that repo's own
`AGENTS.md` and PR checklist, so the filtering/shaping logic has realistic input to
prove itself against:

- `fixtures/pr_4821.json` -- an `any`-typing comment (AGENTS.md: "Use specific
  TypeScript types... do not use `any`"), mixed with a dependabot comment and a
  bare "nit" that should both be dropped.
- `fixtures/pr_4903.json` -- a missing-test comment and a relative-import comment
  (PR checklist: "I have not used any relative imports"), mixed with a renovate
  bot comment and a bare "+1".
- `fixtures/pr_5012.json` -- a second missing-test comment (to prove recurrence
  across PRs is detectable) and an accessibility comment (AGENTS.md: "User-facing
  UI must be accessible"), mixed with a github-actions coverage-bot comment.

## What's checked

1. Bots (`dependabot`, `renovate`, `github-actions`, anything `[bot]`-suffixed or
   `user.type == "Bot"`) are dropped regardless of what they said.
2. Low-signal acks (`lgtm`, `+1`, `nit`, ...) are dropped, but a comment that merely
   *starts* with "LGTM" while adding real content is kept -- the filter matches
   full normalized bodies, not substrings, on purpose.
3. Substantive comments on all three surfaces (inline review comments, top-level
   review verdicts, general PR conversation) are kept and correctly labeled.
4. The hand-rolled multi-page JSON parser in `fetch_paginated` correctly splits
   concatenated pages -- `gh api --paginate` prints one JSON array per page,
   back-to-back, which is not itself valid single-document JSON.
5. The checkpoint file makes re-runs skip already-processed PRs, so an
   interrupted or rate-limited run resumes instead of restarting.

## What this does *not* test

Nothing here calls the real `gh` CLI or hits the network -- so `list_merged_prs`,
`fetch_paginated`'s actual subprocess call, and `detect_owner_repo` are exercised
structurally (their output-parsing logic is what's under test) but not against a
live GitHub API. That's the live dry run noted as a next step in `DESIGN.md`.
