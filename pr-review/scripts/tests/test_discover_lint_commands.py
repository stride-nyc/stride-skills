"""Fixture-based self-test for discover_lint_commands.py. The Node fixtures below
use the *actual* scripts blocks from navigator.business.nj.gov's root and
web/package.json (verified by reading the real repo), so this isn't testing
against invented data for the trickiest part -- distinguishing mutating from
check-mode commands when both live under similar-looking script names.

Run via:
    python3 discover_lint_commands.py --self-test
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import discover_lint_commands as l  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# Real scripts block from navigator.business.nj.gov's web/package.json (trimmed
# to the fields relevant here).
REAL_WEB_SCRIPTS = {
    "build": "yarn copy-vendor-assets && yarn next build && yarn run sitemap",
    "clean": "rimraf .next public/vendor",
    "eslint": "eslint",
    "lint": "eslint . --max-warnings 0",
    "lint:fix": "eslint . --max-warnings 0 --fix",
    "prettier": "prettier --write . --ignore-path=./.eslintignore",
    "prettier:check": "prettier . --check --ignore-path=./.eslintignore",
    "test": "cross-env-shell DEBUG_PRINT_LIMIT=50000 jest",
    "typecheck": "tsc --noemit",
    "start": "next start",
}

# Real (trimmed) scripts block from the repo root's package.json.
REAL_ROOT_SCRIPTS = {
    "build": "yarn verify:node && yarn decap:build-config && yarn workspaces foreach --all -ptvi run build",
    "lint": "yarn workspaces foreach --all run lint",
    "lint:fix": "yarn workspaces foreach --all run lint:fix",
    "lint:staged": "lint-staged",
    "prettier": "prettier --write . --ignore-path=./.eslintignore",
    "prettier:check": "prettier --check . --ignore-path=./.eslintignore",
    "test": "jest",
    "test:ci": "jest --colors --runInBand --ci",
    "typecheck": "yarn workspaces foreach --all -v run typecheck",
}


def test_real_web_package_scripts() -> None:
    print("test_real_web_package_scripts")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "web" / "package.json", {"scripts": REAL_WEB_SCRIPTS})

        report = l.discover(root)
        included_tools = {c["tool"] for c in report["commands"]}

        check("includes 'lint' (no --fix)", "lint" in included_tools)
        check("includes 'typecheck' (tsc --noemit is inherently read-only)", "typecheck" in included_tools)
        check("includes 'prettier:check' (has --check)", "prettier:check" in included_tools)
        check("includes 'test' (no test:ci alternative at this level)", "test" in included_tools)
        check("does NOT include 'lint:fix'", "lint:fix" not in included_tools)
        check("does NOT include bare 'prettier' (mutates, no --check)", "prettier" not in included_tools)
        check("does NOT include 'eslint' (not in either allowlist)", "eslint" not in included_tools)
        check("does NOT include 'build'/'clean'/'start'", not ({"build", "clean", "start"} & included_tools))

        skipped_tools = {s["tool"] for s in report["skipped_mutating"]}
        check("bare 'prettier' shows up in skipped_mutating with a reason", "prettier" in skipped_tools)


def test_real_root_scripts_prefers_test_ci_over_test() -> None:
    print("test_real_root_scripts_prefers_test_ci_over_test")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "package.json", {"scripts": REAL_ROOT_SCRIPTS})

        report = l.discover(root)
        included_tools = {c["tool"] for c in report["commands"]}

        check("includes 'test:ci'", "test:ci" in included_tools)
        check("does not also include plain 'test' when test:ci exists", "test" not in included_tools)
        check("includes 'lint'", "lint" in included_tools)
        check("includes 'typecheck'", "typecheck" in included_tools)
        check("includes 'prettier:check'", "prettier:check" in included_tools)
        check("excludes 'lint:staged' (not in either allowlist)", "lint:staged" not in included_tools)


def test_python_pyproject_sections() -> None:
    print("test_python_pyproject_sections")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Matches the real navigator.business.nj.gov pyproject.toml shape: a
        # [project] block listing "black" as a dependency, but -- importantly --
        # no [tool.black]/[tool.ruff]/[tool.mypy] section. Should yield zero
        # python commands, not a false positive from seeing "black" as a string.
        write_text(
            root / "pyproject.toml",
            '[project]\nname = "example"\ndependencies = ["black", "mypy-extensions"]\n',
        )
        report = l.discover(root)
        check(
            "no python commands inferred just from 'black' appearing as a dependency name",
            not any(c["ecosystem"] == "python" for c in report["commands"]),
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_text(
            root / "pyproject.toml",
            "[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n",
        )
        report = l.discover(root)
        tools = {c["tool"] for c in report["commands"]}
        check("[tool.ruff] section yields a ruff command", "ruff" in tools)
        check("[tool.mypy] section yields a mypy command", "mypy" in tools)
        check("[tool.black] absent, so no black command", "black --check" not in tools)


def test_config_file_based_ecosystems() -> None:
    print("test_config_file_based_ecosystems")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_text(root / "go.mod", "module example.com/x\n")
        write_text(root / ".golangci.yml", "linters:\n  enable:\n    - govet\n")
        write_text(root / "Cargo.toml", "[package]\nname = \"x\"\n")
        write_text(root / "src" / "Thing.csproj", "<Project />")

        report = l.discover(root)
        tools = {c["tool"] for c in report["commands"]}
        check("go vet discovered from go.mod", "go vet" in tools)
        check("golangci-lint discovered from .golangci.yml", "golangci-lint" in tools)
        check("cargo fmt --check discovered from Cargo.toml", "cargo fmt --check" in tools)
        check("cargo clippy discovered from Cargo.toml", "cargo clippy" in tools)
        check("dotnet format discovered from .csproj", "dotnet format" in tools)


def test_ci_evidence_collection() -> None:
    print("test_ci_evidence_collection")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_text(
            root / ".github" / "workflows" / "build-and-test.yml",
            "jobs:\n  test:\n    steps:\n      - run: yarn lint\n      - run: yarn build\n",
        )
        report = l.discover(root)
        check("lint-related run: line captured as ci_evidence", len(report["ci_evidence"]) == 1)
        check("build-only run: line not captured (no keyword match)", "yarn build" not in str(report["ci_evidence"]))


def test_skips_vendored_dirs() -> None:
    print("test_skips_vendored_dirs")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_json(root / "package.json", {"scripts": {"lint": "eslint ."}})
        write_json(root / "node_modules" / "some-dep" / "package.json", {"scripts": {"lint": "eslint ."}})

        report = l.discover(root)
        sources = {c["source"] for c in report["commands"]}
        check("only the real root package.json is used as a source", sources == {"package.json"})


def run_all() -> int:
    test_real_web_package_scripts()
    test_real_root_scripts_prefers_test_ci_over_test()
    test_python_pyproject_sections()
    test_config_file_based_ecosystems()
    test_ci_evidence_collection()
    test_skips_vendored_dirs()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
