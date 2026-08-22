# GitHub Actions workflow for automated reaction collection

Add this workflow to `.github/workflows/pr-review-react.yml` in your repo. It triggers when a PR
is merged, waits a short window for reactions to settle, then runs `collect_reactions.py` against
that PR and commits the updated `pattern-scores.json` back to the default branch.

```yaml
name: pr-review-react

on:
  pull_request:
    types: [closed]

jobs:
  collect-reactions:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: read

    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Wait for reactions to settle
        run: sleep 300  # 5 minutes — adjust to your team's review cadence

      - name: Collect reactions and update scores
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python3 .claude/skills/pr-review-react/scripts/collect_reactions.py \
            --root . \
            --pr ${{ github.event.pull_request.number }}

      - name: Commit updated pattern scores
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .claude/pr-review-data/
          git diff --cached --quiet || git commit -m "chore: update pr-review pattern scores from PR #${{ github.event.pull_request.number }} reactions"
          git push
```

## Notes

- **Skill path**: Update the `python3` path to wherever the skill is installed in your repo. If
  installed via Stride skills at `.claude/skills/pr-review-react/`, the path above is correct.
- **Wait time**: 5 minutes is a conservative default. For teams that review PRs quickly, 1–2
  minutes may be enough. For async teams across time zones, consider running the collection on a
  schedule instead of on PR merge.
- **Scheduled alternative**: If your team tends to react to findings long after a PR merges, replace
  the `on: pull_request` trigger with a nightly schedule that scans the last 20 merged PRs:

  ```yaml
  on:
    schedule:
      - cron: "0 2 * * *"  # 2am UTC daily
  ```

  And change the `collect_reactions.py` invocation to omit `--pr` (uses `--limit 20` by default).

- **Branch protection**: If your default branch has required status checks or push restrictions,
  use a bot token with write access instead of `GITHUB_TOKEN`, or open a PR for the score update
  rather than pushing directly.