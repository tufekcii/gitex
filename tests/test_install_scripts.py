"""Kurulum betiklerinin dosya biçimi: kodlama hataları sözdizimi denetiminden kaçabiliyor."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"


def test_install_ps1_has_exactly_one_bom_and_crlf() -> None:
    # Windows PowerShell 5.1 Türkçe karakterleri yalnızca BOM'lu UTF-8'de doğru okur;
    # ikinci bir BOM ise ilk satırı bozar ve parametreler sessizce yok sayılır.
    data = (ROOT / "install.ps1").read_bytes()
    assert data.startswith(BOM)
    assert not data[len(BOM) :].startswith(BOM)
    assert b"\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_install_cmd_is_crlf() -> None:
    data = (ROOT / "install.cmd").read_bytes()
    assert not data.startswith(BOM)
    assert b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh yok")
def test_install_sh_syntax_and_language_validation() -> None:
    script = str(ROOT / "install.sh")
    assert subprocess.run(["sh", "-n", script], check=False).returncode == 0
    bad = subprocess.run(
        ["sh", script, "--lang", "de"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert bad.returncode == 2
    assert "tr | en" in bad.stderr


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell yok")
def test_install_ps1_parses() -> None:
    cmd = (
        "$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{ROOT / 'install.ps1'}', [ref]$null, [ref]$e) | Out-Null; $e.Count"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, check=False
    )
    assert out.stdout.strip() == "0"
