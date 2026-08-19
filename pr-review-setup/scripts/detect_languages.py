#!/usr/bin/env python3
"""Phase 2 helper for the pr-review-setup skill: detect which language ecosystems
a repo uses, so that when the installer has no coding-standards source of their
own, we can suggest well-known community standards instead of leaving them
empty-handed (see DESIGN.md, Phase 2, step 2).

This is the deterministic half of Phase 2 -- finding manifest files and mapping
them to ecosystems is a plain filesystem walk, no judgment required. Turning
whatever standards *are* found (an in-repo markdown file, a wiki export, a style
guide URL) into coding-standards.md is Claude's job, guided by
references/coding-standards-ingestion.md -- same division of labor as Phase 1's
mining script vs. clustering step.

Usage:
    python3 detect_languages.py [--root .] [--max-depth 3]
    python3 detect_languages.py --self-test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Directories that are never worth descending into when looking for manifest
# files -- either vendored/generated code or so deep they'd blow up scan time.
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

# manifest filename -> ecosystem. Order doesn't matter; a repo can and often
# does match several (navigator.business.nj.gov matches node + python).
MANIFEST_TO_ECOSYSTEM = {
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "Pipfile": "python",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "Cargo.toml": "rust",
    "composer.json": "php",
}

# .csproj/.sln are matched by suffix, not exact name.
DOTNET_SUFFIXES = (".csproj", ".sln")

# Well-known, stable community standards to suggest when an ecosystem is
# detected but the installer has no standards doc of their own. Deliberately a
# short list of the most widely-recognized guide per ecosystem rather than an
# exhaustive one -- more than one or two options per language is choice overload
# for someone who explicitly said they don't have a preference yet.
SUGGESTED_STANDARDS = {
    "node": [
        {
            "name": "Airbnb JavaScript Style Guide",
            "url": "https://github.com/airbnb/javascript",
            "note": "The most widely-adopted community JS style guide; has an ESLint config you can install directly.",
        },
        {
            "name": "typescript-eslint recommended rules",
            "url": "https://typescript-eslint.io/rules/",
            "note": "If the repo is TypeScript rather than plain JS, start here instead of/alongside Airbnb.",
        },
    ],
    "python": [
        {
            "name": "PEP 8",
            "url": "https://peps.python.org/pep-0008/",
            "note": "The baseline every other Python style guide builds on.",
        },
        {
            "name": "Google Python Style Guide",
            "url": "https://google.github.io/styleguide/pyguide.html",
            "note": "More opinionated than PEP 8 alone -- covers things like docstring format and typing conventions.",
        },
    ],
    "go": [
        {
            "name": "Effective Go",
            "url": "https://go.dev/doc/effective_go",
            "note": "The canonical starting point from the Go team itself.",
        },
        {
            "name": "Google Go Style Guide",
            "url": "https://google.github.io/styleguide/go/",
            "note": "More prescriptive than Effective Go; good if the team wants firmer rules.",
        },
    ],
    "ruby": [
        {
            "name": "The Ruby Style Guide",
            "url": "https://rubystyle.guide/",
            "note": "Community standard; also the basis for RuboCop's default rules.",
        },
    ],
    "java": [
        {
            "name": "Google Java Style Guide",
            "url": "https://google.github.io/styleguide/javaguide.html",
            "note": "Widely adopted outside Google too; pairs well with Checkstyle/Spotless.",
        },
    ],
    "rust": [
        {
            "name": "Rust API Guidelines",
            "url": "https://rust-lang.github.io/api-guidelines/",
            "note": "Focused on public API design; pair with `rustfmt`'s default style for formatting.",
        },
    ],
    "php": [
        {
            "name": "PSR-12: Extended Coding Style",
            "url": "https://www.php-fig.org/psr/psr-12/",
            "note": "The de facto standard most PHP tooling (PHP-CS-Fixer, etc.) defaults to.",
        },
    ],
    "dotnet": [
        {
            "name": "Microsoft C# Coding Conventions",
            "url": "https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/coding-style/coding-conventions",
            "note": "Official Microsoft guidance; `dotnet format` enforces much of it automatically.",
        },
    ],
}


def classify_manifest(filename: str) -> str | None:
    if filename in MANIFEST_TO_ECOSYSTEM:
        return MANIFEST_TO_ECOSYSTEM[filename]
    if filename.endswith(DOTNET_SUFFIXES):
        return "dotnet"
    return None


def scan_repo(root: Path, max_depth: int = 3) -> dict[str, list[str]]:
    """Walk the repo (bounded depth, skipping vendored/generated dirs) and return
    {ecosystem: [manifest paths relative to root]}. Pure filesystem logic, no
    network or subprocess calls, so it's easy to point at any directory tree
    (including a fixture tree) for testing.
    """
    found: dict[str, list[str]] = {}

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
                ecosystem = classify_manifest(entry.name)
                if ecosystem:
                    found.setdefault(ecosystem, []).append(str(entry.relative_to(root)))

    walk(root, 0)
    return found


def build_report(detections: dict[str, list[str]]) -> dict:
    ecosystems = []
    for name, manifests in sorted(detections.items()):
        ecosystems.append(
            {
                "name": name,
                "manifest_files": sorted(manifests),
                "suggested_standards": SUGGESTED_STANDARDS.get(name, []),
            }
        )
    return {
        "ecosystems": ecosystems,
        "is_polyglot": len(ecosystems) > 1,
    }


def run_self_test() -> int:
    tests_dir = Path(__file__).parent / "tests"
    sys.path.insert(0, str(tests_dir))
    import test_detect_languages  # type: ignore

    return test_detect_languages.run_all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repo root to scan (default: cwd).")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    root = Path(args.root).resolve()
    detections = scan_repo(root, args.max_depth)
    print(json.dumps(build_report(detections), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
