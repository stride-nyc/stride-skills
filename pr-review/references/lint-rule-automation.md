# Lint rule automation

Consulted by Phase 6 when a user marks a Phase 1+2 finding as relevant and the pattern is not
already enforced by the project's linters.

## Determining whether a rule is possible

First check whether the pattern is already caught — cross-reference against Phase 3's discovered
commands and config files. If it is, skip this entirely.

If it is not already caught, determine whether it can be expressed as a static analysis rule:

- **ESLint**: a built-in rule; a plugin rule already in `package.json`; or `no-restricted-syntax` /
  `no-restricted-imports` for structural patterns without a dedicated rule.
- **Ruff / flake8**: a rule code in `extend-select` or `per-file-ignores` in `pyproject.toml`.
- **Biome**: a linter rule entry in `biome.json`.
- **golangci-lint**: an enabled linter in `.golangci.yml`.

If the pattern is inherently judgment-based (e.g. "this abstraction is the wrong level"), it cannot
be encoded as a rule — skip this step silently. The score update alone is sufficient.

## Creating the branch

If a rule can be drafted, propose a new branch for it (e.g. `lint/enforce-<pattern-slug>`). A lint
config change is a separate concern from the PR being reviewed and must not be mixed into its diff.

Show the complete config diff and ask: "Want me to create a branch with this rule added?" If yes:

```bash
git stash -u 2>/dev/null
git checkout -b <branch-name>
# apply the config change
git add <config-file>
git commit -m "enforce <pattern> via <linter>"
git checkout -
git stash pop 2>/dev/null
```

After returning to the original branch, offer to open a PR for the lint branch (`gh pr create`) —
subject to the same explicit-confirmation rule as Phase 5.

## Escalating an existing rule (Phase 3 findings)

If the user wants to act on a finding that a linter already catches, the rule exists — "automate"
means escalating it. Offer to change its severity from `warn` to `error` in the linter config, or
add it to the CI failure threshold if it currently only runs in advisory mode. Apply on a new branch
for the same reason. Show the current config entry and proposed change; confirm before writing.