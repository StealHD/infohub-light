from __future__ import annotations

from pathlib import Path

from scripts.check_e2e_contract import check_file


def _write(root: Path, content: str) -> Path:
    path = root / "frontend/e2e/example.spec.ts"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_rejects_hardcoded_preview_port(tmp_path: Path) -> None:
    path = _write(tmp_path, "await page.route('http://127.0.0.1:4174/api/items', handler)\n")

    assert any("baseURL" in error for error in check_file(tmp_path, path))


def test_rejects_count_before_transient_inert_assertion(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "const dialog = page.getByRole('dialog')\n"
        "expect(await dialog.count()).toBe(1)\n"
        "await expect(dialog).toHaveAttribute('aria-hidden', 'true')\n",
    )

    assert any("transient" in error for error in check_file(tmp_path, path))


def test_visual_contract_requires_deterministic_state(tmp_path: Path) -> None:
    path = _write(tmp_path, "await expect(page).toHaveScreenshot('page.png')\n")

    errors = check_file(tmp_path, path)
    assert len(errors) == 3


def test_deterministic_visual_contract_passes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "await page.emulateMedia({ reducedMotion: 'reduce' })\n"
        "await page.evaluate(() => localStorage.setItem('theme', 'dark'))\n"
        "await expect(page).toHaveScreenshot('page.png', { animations: 'disabled' })\n",
    )

    assert check_file(tmp_path, path) == []
