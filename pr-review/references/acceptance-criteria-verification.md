# Verifying the diff against acceptance criteria

This is Phase 4's judgment step (see `SKILL.md`), run after a ticket has been located and fetched (or
the user has supplied a description directly). There's no script for this part — deciding whether a
diff satisfies a criterion requires actually reading both, the same way a human reviewer would.

## Classify each criterion into exactly one of four states

- **Met** — the diff clearly implements this criterion. Point at the specific file/function that does
  it.
- **Partially met** — some but not all of the criterion is addressed (e.g. the happy path works but an
  edge case named in the criterion isn't handled). Say specifically what's missing.
- **Not addressed** — nothing in the diff relates to this criterion at all. Worth double-checking
  before reporting this — it might mean the criterion is handled by code that isn't part of this diff
  (already existing, or intentionally out of scope), not necessarily a gap.
- **Not verifiable from the diff alone** — the criterion describes something a diff can't settle by
  inspection (e.g. "must load in under 2 seconds," "must be usable with a screen reader," "must match
  the Figma design"). Say so plainly rather than guessing at a verdict, and note what *would* verify it
  (a manual check, a Lighthouse run, a design review).

## Report every criterion, not just the failures

Silently dropping criteria that look satisfied hides exactly the information a human reviewer needs in
order to *skip* re-checking them. The output should be a full list, one line of verdict + reasoning per
criterion, even when every single one is "met" — a full green list is itself useful information
("author verified all N criteria, human review can focus elsewhere"), not a set of items to elide
because they weren't interesting.

## When acceptance criteria are vague

If the user supplied their own story description rather than one being fetched from a tracker, and the
acceptance criteria are thin or missing entirely ("just needs to work"), say so directly rather than
inventing specific criteria to check against. A one-line "the story didn't specify concrete acceptance
criteria, so this pass only confirms the diff matches the described *behavior*, not a checklist" is
more honest than fabricating a checklist that looks authoritative but wasn't actually specified by
anyone.

## When the fetched ticket and the diff clearly describe different work

Occasionally the branch's ticket reference is stale (rebased onto the wrong ticket, or the scope
changed after the ticket was written and nobody updated the PR). If the diff looks like it's doing
something unrelated to every criterion, say that plainly and ask whether the right ticket was found —
don't force-fit a verdict onto criteria that don't apply.
