"""A rebuilt file with unchanged size/time must replace old archive contents."""
import importlib.util
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which('7z') is None, reason='Requires the packaging host 7z')
def test_same_timestamp_and_size_replaces_binary_and_removes_stale_entries(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('camoufox_package_script', ROOT / 'scripts/package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = tmp_path / 'output.zip'
    incoming = tmp_path / 'incoming.zip'
    stamp = (2025, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(old, 'w') as archive:
        archive.writestr(zipfile.ZipInfo('xul.dll', stamp), b'old!')
        archive.writestr(zipfile.ZipInfo('stale-only.dll', stamp), b'stale')
    with zipfile.ZipFile(incoming, 'w') as archive:
        archive.writestr(zipfile.ZipInfo('camoufox/xul.dll', stamp), b'new!')
    module.add_includes_to_package(str(incoming), [], [], str(old), 'windows')
    with zipfile.ZipFile(old) as archive:
        assert archive.read('xul.dll') == b'new!'
        assert 'stale-only.dll' not in archive.namelist()
