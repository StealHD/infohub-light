"""Bundled Skill drift detection for local OpenClaw setup."""

from __future__ import annotations

from pathlib import Path


def skill_tree_matches(source: Path, installed: Path) -> bool:
    """Compare managed Skill content while ignoring OpenClaw install metadata."""

    def managed_files(root: Path) -> dict[Path, bytes] | None:
        if not root.is_dir():
            return None
        files: dict[Path, bytes] = {}
        try:
            for path in root.rglob("*"):
                relative = path.relative_to(root)
                if any(part.startswith(".") for part in relative.parts):
                    continue
                if path.is_symlink():
                    return None
                if path.is_file():
                    files[relative] = path.read_bytes()
        except OSError:
            return None
        return files

    source_files = managed_files(source)
    installed_files = managed_files(installed)
    return source_files is not None and source_files == installed_files
