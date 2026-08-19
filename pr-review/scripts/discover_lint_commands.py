#!/usr/bin/env python3
"""Phase 3 helper for the pr-review skill: discover which linters/typecheckers/
static-analysis commands a repo already has configured, so the per-PR review
pass runs the project's *own* tooling instead of a hardcoded, language-specific
list (see DESIGN.md, Phase 3).

Deliberately conservative: only surfaces commands that check rather than mutate
(no `--fix`, no `--write`, no bare `prettier`/`black` invocations that would
reformat files). Anything that looks like it would mutate is reported separately
in `skipped_mutating` with a reason, not silently dropped and not silently run.

This script only *discovers* commands -- it does not execute them. Running the
discovered commands (via Bash, scoped to whatever's actually installed) is the
review pass's job, once it has this list; that keeps this script runnable and
testable without needing every ecosystem's toolchain actually installed.

Usage:
    python3 discover_lint_commands.py [--root .] [--max-depth 3]
    python3 discover_lint_commands.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".turbo",
    ".yarn",
}

# Node package.json scripts worth surfacing, by exact name. Deliberately a
# strict allowlist rather than substring matching on "lint"/"test" -- a script
# named "lint-staged-and-commit" or "test-data-seed" is not something we want
# to guess about.
SAFE_NODE_SCRIPT_NAMES = {
    "lint",
    "lint:check",
    "typecheck",
    "type-check",
    "test",
    "test:ci",
    "verify",
    "check",
}

# Names where the script body still needs a --check/--list-different-style flag
# to count as non-mutating -- "format" and "prettier" are ambiguous by name alone
# (navigator.business.nj.gov has both a mutating "prettier" and a checking
# "prettier:check").
AMBIGUOUS_NODE_SCRIPT_NAMES = {"format", "format:check", "prettier", "prettier:check"}

MUTATING_MARKERS = ("--fix", "--write", "--in-place", " -w ")
CHECK_MARKERS = ("--check", "--list-different", "--dry-run", "--verify-no-changes")

# Non-Node ecosystems: config-file presence -> a command to suggest. Values can
# be a single (tool, command) tuple or a list of them (e.g. Rust has both a
# formatter and a linter check worth running).
CONFIG_FILE_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "go.mod": [("go vet", "go vet ./...")],
    ".golangci.yml": [("golangci-lint", "golangci-lint run")],
    ".golangci.yaml": [("golangci-lint", "golangci-lint run")],
    "Cargo.toml": [
        ("cargo fmt --check", "cargo fmt --check"),
        ("cargo clippy", "cargo clippy --all-targets -- -D warnings"),
    ],
    ".rubocop.yml": [("rubocop", "bundle exec rubocop")],
    ".flake8": [("flake8", "flake8 .")],
    "phpcs.xml": [("phpcs", "vendor/bin/phpcs")],
    ".php-cs-fixer.php": [("php-cs-fixer", "vendor/bin/php-cs-fixer fix --dry-run --diff")],
}

DOTNET_SUFFIXES = (".csproj", ".sln")

# pyproject.toml [tool.X] section -> command. Checked by simple substring match
# on the raw file text rather than a full TOML parse, since we only need to know
# whether the section header is present, not its contents.
PYPROJECT_TOOL_SECTIONS = {
    "[tool.ruff]": ("ruff", "ruff check ."),
    "[tool.black]": ("black --check", "black --check ."),
    "[tool.mypy]": ("mypy", "mypy ."),
}

CI_EVIDENCE_KEYWORDS = re.compile(
    r"\b(lint|typecheck|type-check|vet|clippy|rubocop|flake8|ruff|mypy|black|prettier)\b",
    re.IGNORECASE,
)


def is_mutating(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in MUTATING_MARKERS)


def has_check_marker(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in CHECK_MARKERS)


def classify_node_script(name: str, command: str) -> tuple[str, str] | None:
    """Returns (decision, reason) where decision is 'include' or 'skip', or None
    if this script isn't one we look at at all (not in either allowlist).
    """
    if name in SAFE_NODE_SCRIPT_NAMES:
        if is_mutating(command):
            return ("skip", f"script name '{name}' looks safe but command contains a mutating flag")
        return ("include", "")
    if name in AMBIGUOUS_NODE_SCRIPT_NAMES:
        if is_mutating(command):
            return ("skip", f"'{name}' contains a mutating flag ({command!r})")
        if has_check_marker(command):
            return ("include", "")
        return ("skip", f"'{name}' has no --check/--list-different flag, would likely mutate files")
    return None


def find_files(root: Path, max_depth: int) -> list[Path]:
    found: list[Path] = []

    def walk(dir_path: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(dir_path.iterdir())
        except (PermissionError, FileNotFoundError):
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                walk(entry, depth + 1)
            elif entry.is_file():
                found.append(entry)

    walk(root, 0)
    return found


def discover_node_commands(root: Path, files: list[Path]) -> tuple[list[dict], list[dict]]:
    commands: list[dict] = []
    skipped: list[dict] = []
    for f in files:
        if f.name != "package.json":
            continue
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        scripts = data.get("scripts") or {}
        # Prefer a CI-oriented variant over its plain counterpart when both exist,
        # to avoid running the same check twice and to prefer the non-watch,
        # non-interactive form (test:ci over test, lint:check over lint if both
        # somehow exist).
        preferred_pairs = [("test:ci", "test"), ("lint:check", "lint")]
        names_to_skip_in_favor_of_preferred = set()
        for preferred, fallback in preferred_pairs:
            if preferred in scripts and fallback in scripts:
                names_to_skip_in_favor_of_preferred.add(fallback)

        for name, command in scripts.items():
            if name in names_to_skip_in_favor_of_preferred:
                continue
            decision = classify_node_script(name, command)
            if decision is None:
                continue
            verdict, reason = decision
            entry = {
                "tool": name,
                "command": command,
                "source": str(f.relative_to(root)),
                "ecosystem": "node",
            }
            if verdict == "include":
                commands.append(entry)
            else:
                skipped.append({**entry, "reason": reason})
    return commands, skipped


def discover_python_commands(root: Path, files: list[Path]) -> list[dict]:
    commands: list[dict] = []
    for f in files:
        if f.name != "pyproject.toml":
            continue
        try:
            text = f.read_text()
        except OSError:
            continue
        for section, (tool, command) in PYPROJECT_TOOL_SECTIONS.items():
            if section in text:
                commands.append(
                    {
                        "tool": tool,
                        "command": command,
                        "source": str(f.relative_to(root)),
                        "ecosystem": "python",
                    }
                )
    return commands


def discover_config_based_commands(root: Path, files: list[Path]) -> list[dict]:
    commands: list[dict] = []
    for f in files:
        rel = str(f.relative_to(root))
        if f.name in CONFIG_FILE_COMMANDS:
            for tool, command in CONFIG_FILE_COMMANDS[f.name]:
                commands.append({"tool": tool, "command": command, "source": rel, "ecosystem": None})
        elif f.name.endswith(DOTNET_SUFFIXES):
            commands.append(
                {
                    "tool": "dotnet format",
                    "command": "dotnet format --verify-no-changes",
                    "source": rel,
                    "ecosystem": "dotnet",
                }
            )
    return commands


def dedupe_commands(commands: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for c in commands:
        key = (c["command"], c["source"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def collect_ci_evidence(root: Path) -> list[dict]:
    """Informational only: lines in .github/workflows/*.yml that mention a
    lint/typecheck/test-style keyword. Not turned into executable commands --
    workflow steps often depend on env/setup we can't reproduce inline -- but
    surfaced so a human (or Claude) can sanity-check the discovered commands
    against what CI actually runs, per DESIGN.md's point that CI config is
    often the most reliable source of truth for a repo's real quality gate.
    """
    evidence: list[dict] = []
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return evidence
    for wf in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        try:
            lines = wf.read_text().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("run:") or stripped.startswith("- run:"):
                if CI_EVIDENCE_KEYWORDS.search(stripped):
                    evidence.append(
                        {
                            "file": str(wf.relative_to(root)),
                            "line": i + 1,
                            "text": stripped,
                        }
                    )
    return evidence


def discover(root: Path, max_depth: int = 3) -> dict:
    files = find_files(root, max_depth)
    node_commands, node_skipped = discover_node_commands(root, files)
    python_commands = discover_python_commands(root, files)
    config_commands = discover_config_based_commands(root, files)

    all_commands = dedupe_commands(node_commands + python_commands + config_commands)
    ci_evidence = collect_ci_evidence(root)

    return {
        "commands": all_commands,
        "skipped_mutating": node_skipped,
        "ci_evidence": ci_evidence,
    }


def run_self_test() -> int:
    tests_dir = Path(__file__).parent / "tests"
    sys.path.insert(0, str(tests_dir))
    import test_discover_lint_commands  # type: ignore

    return test_discover_lint_commands.run_all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    report = discover(Path(args.root).resolve(), args.max_depth)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
