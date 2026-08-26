#!/usr/bin/env python3
"""Fail when a requested release does not match versioned project artifacts."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _python_version(path: Path) -> str:
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', path.read_text(), re.M)
    if match is None:
        raise ValueError(f"missing __version__ in {path.relative_to(ROOT)}")
    return match.group(1)


def versioned_artifacts() -> dict[str, str]:
    """Return release versions embedded in canonical distributable artifacts."""

    manifest = json.loads(
        (ROOT / "custom_components/thessla_green/manifest.json").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    openapi = json.loads((ROOT / "docs/openapi-v1.json").read_text(encoding="utf-8"))
    return {
        "custom_components/thessla_green/manifest.json": manifest["version"],
        "pyproject.toml": pyproject["project"]["version"],
        "src/thessla_green/__init__.py": _python_version(
            ROOT / "src/thessla_green/__init__.py"
        ),
        "custom_components/thessla_green/_core/__init__.py": _python_version(
            ROOT / "custom_components/thessla_green/_core/__init__.py"
        ),
        "docs/openapi-v1.json": openapi["info"]["version"],
    }


def verify_release_version(requested: str) -> None:
    """Validate a strict SemVer release against every canonical artifact."""

    version = requested.removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("release version must use MAJOR.MINOR.PATCH, for example 0.3.1")
    mismatches = {
        path: actual for path, actual in versioned_artifacts().items() if actual != version
    }
    if mismatches:
        details = ", ".join(f"{path}={actual}" for path, actual in mismatches.items())
        raise ValueError(f"requested {version}, but versioned artifacts differ: {details}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="release version, with optional v prefix")
    args = parser.parse_args()
    verify_release_version(args.version)
    print(f"release version verified: {args.version.removeprefix('v')}")


if __name__ == "__main__":
    main()
