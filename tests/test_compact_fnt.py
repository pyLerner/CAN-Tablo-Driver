from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from compact_fnt import font_path_for_index, load_fnt, render_text
from compact_fnt.catalog import FNT_INDEX_TO_FILE, FNT_INDEX_TO_HEIGHT, VALID_FNT_INDEXES


@pytest.mark.parametrize("index", VALID_FNT_INDEXES)
def test_load_all_catalog_fonts(index: int) -> None:
    path = font_path_for_index(index)
    font = load_fnt(path, expected_font_id=index)
    assert font.font_id == index
    assert font.height == FNT_INDEX_TO_HEIGHT[index]
    assert font.path.name == FNT_INDEX_TO_FILE[index]


@pytest.mark.parametrize("index", VALID_FNT_INDEXES)
def test_ascii_glyphs_present(index: int) -> None:
    font = load_fnt(font_path_for_index(index), expected_font_id=index)
    for ch in (" ", "A", "0"):
        assert font.has_codepoint(ord(ch))


def test_georgian_font_has_mkhedruli() -> None:
    font = load_fnt(font_path_for_index(62), expected_font_id=62)
    assert font.has_codepoint(0x10D0)


@pytest.mark.parametrize("index", (63, 65, 69))
def test_render_non_empty(index: int) -> None:
    font = load_fnt(font_path_for_index(index), expected_font_id=index)
    image = render_text(font, "ABC 123")
    assert image.width > 0
    assert image.height >= font.height
    assert image.getbbox() is not None


def test_fnt_demo_smoke(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for fnt-demo smoke test"

    output = tmp_path / "demo.jpg"
    proc = subprocess.run(
        [
            uv,
            "run",
            "fnt-demo",
            "--backend",
            "ttf",
            "--fnt-index",
            "63",
            "-o",
            str(output),
        ],
        input="Hello",
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert output.is_file()
    assert output.stat().st_size > 400


def test_fnt_demo_ttf_cyrillic(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for fnt-demo smoke test"

    output = tmp_path / "cyrillic.jpg"
    proc = subprocess.run(
        [
            uv,
            "run",
            "fnt-demo",
            "--backend",
            "ttf",
            "--fnt-index",
            "63",
            "-o",
            str(output),
        ],
        input="Шрифт 42",
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert output.is_file()
    assert output.stat().st_size > 400


def test_georgian_render_smoke() -> None:
    font = load_fnt(font_path_for_index(62), expected_font_id=62)
    image = render_text(font, "გამარჯობა")
    assert image.width > 0
    assert image.getbbox() is not None
