# Phase 6 — Post-review feedback and pattern tuning

Loaded only when the user agrees to give feedback after the final report.

## Collecting feedback

Don't force the user through every finding one by one. Show a numbered summary of the Phase 1+2
findings surfaced this run and ask: "Any of these worth adjusting?" The user can call out specific
findings by number, or say "all good" to skip.

For each finding the user calls out, ask them to classify it:

| Response | What it means | Score change |
|---|---|---|
| "Good catch / relevant" | This pattern matters for our codebase | +2 |
| "Not relevant this PR, but keep it" | Situational; don't penalize | 0 |
| "Rarely comes up, deprioritize" | Lower its prominence | −1 |
| "Never relevant here" | Suppress it after a few more hits | −3 |
| "Ignore permanently" | Never show it again, regardless of score | Sets `explicitlyIgnored: true` |

Suppression is gradual, not immediate: a single "never relevant here" drops the score by 3 but
doesn't suppress the pattern until it crosses ≤ −10. In a multi-person project, a pattern needs
consistent dismissal across multiple runs to get suppressed. The user can always force immediate
suppression with "ignore permanently."

Phase 3 (lint) findings are not scored here — they come from the project's own tooling. If the
user wants to act on a lint finding, use the lint rule automation path below.

## Writing `pattern-scores.json`

Lives at `.claude/pr-review-data/<owner>-<repo>/pattern-scores.json`. Create if absent. Schema:

```json
{
  "version": 1,
  "patterns": {
    "Missing null checks on API responses": {
      "score": -2,
      "accepts": 1,
      "dismissals": 3,
      "explicitlyIgnored": false,
      "source": "Phase 1",
      "lastSeen": "2026-08-22"
    }
  }
}
```

Batch all score updates from the session into a single write at the end of triage. Show the user a
brief summary of what will be written ("Updating scores for 3 patterns") and confirm before writing.

## Suggesting a lint rule for relevant findings

When a user marks a finding as relevant ("Good catch / relevant"), check whether the pattern is
already enforced by the project's linters. If it can be expressed as a new rule, suggest creating a
branch for it. Full decision logic, per-linter rule formats, and the branch workflow are in
[`lint-rule-automation.md`](lint-rule-automation.md).