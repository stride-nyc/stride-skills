"""Fixture-based self-test for detect_languages.py -- builds small fake repo
trees on disk (no real cloning needed) and checks the scan finds the right
ecosystems while skipping vendored/generated directories.

Run via:
    python3 detect_languages.py --self-test
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detect_languages as d  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        FAILURES.append(label)


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")


def test_single_ecosystem_repo() -> None:
    print("test_single_ecosystem_repo")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        touch(root / "package.json")
        touch(root / "src" / "index.ts")  # not a manifest, should be ignored

        detections = d.scan_repo(root)
        check("detects node", "node" in detections)
        check("only one ecosystem detected", len(detections) == 1)
        check("manifest path recorded correctly", detections["node"] == ["package.json"])


def test_polyglot_monorepo_like_navigator() -> None:
    print("test_polyglot_monorepo_like_navigator")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Root Yarn workspaces manifest, plus per-package manifests, plus a
        # Python component -- this is the real shape of navigator.business.nj.gov.
        touch(root / "package.json")
        touch(root / "pyproject.toml")
        touch(root / "web" / "package.json")
        touch(root / "api" / "package.json")
        touch(root / "shared" / "package.json")
        touch(root / "packages" / "static-site" / "package.json")

        detections = d.scan_repo(root, max_depth=3)
        report = d.build_report(detections)

        check("detects node", "node" in detections)
        check("detects python", "python" in detections)
        check("flagged as polyglot", report["is_polyglot"] is True)
        check(
            "finds all 5 package.json files across the workspace",
            len(detections["node"]) == 5,
        )
        node_entry = next(e for e in report["ecosystems"] if e["name"] == "node")
        check("node entry carries suggested standards", len(node_entry["suggested_standards"]) > 0)


def test_skips_vendored_and_generated_dirs() -> None:
    print("test_skips_vendored_and_generated_dirs")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        touch(root / "package.json")
        # A package.json buried inside node_modules should never be counted --
        # if it were, every single node repo would look enormous and the
        # manifest list would be useless signal.
        touch(root / "node_modules" / "some-dep" / "package.json")
        touch(root / "vendor" / "thing" / "go.mod")
        touch(root / ".git" / "package.json")  # pathological, but should still be skipped

        detections = d.scan_repo(root)
        check("only the real root package.json is found", detections["node"] == ["package.json"])
        check("go.mod under vendor/ is not counted", "go" not in detections)


def test_dotnet_matched_by_suffix() -> None:
    print("test_dotnet_matched_by_suffix")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        touch(root / "src" / "MyApp.csproj")

        detections = d.scan_repo(root)
        check("csproj detected as dotnet", "dotnet" in detections)


def test_max_depth_is_respected() -> None:
    print("test_max_depth_is_respected")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # 5 levels deep -- beyond a max_depth=2 scan.
        touch(root / "a" / "b" / "c" / "d" / "package.json")

        shallow = d.scan_repo(root, max_depth=2)
        deep = d.scan_repo(root, max_depth=6)
        check("deeply nested manifest missed at shallow depth", "node" not in shallow)
        check("same manifest found once depth is sufficient", "node" in deep)


def test_no_ecosystems_detected_is_not_an_error() -> None:
    print("test_no_ecosystems_detected_is_not_an_error")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        touch(root / "README.md")
        report = d.build_report(d.scan_repo(root))
        check("empty ecosystems list, not a crash", report["ecosystems"] == [])
        check("not flagged as polyglot", report["is_polyglot"] is False)


def run_all() -> int:
    test_single_ecosystem_repo()
    test_polyglot_monorepo_like_navigator()
    test_skips_vendored_and_generated_dirs()
    test_dotnet_matched_by_suffix()
    test_max_depth_is_respected()
    test_no_ecosystems_detected_is_not_an_error()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_all())
