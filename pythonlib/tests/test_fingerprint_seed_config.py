import copy
import json
from pathlib import Path

import pytest

from camoufox.seeds import SEED_KEYS, validate_seed_options


@pytest.mark.parametrize('key', SEED_KEYS)
@pytest.mark.parametrize('value', [0, 1, 4294967295])
def test_explicit_seed_is_preserved(key, value):
    config = {key: value}
    original = copy.deepcopy(config)
    validate_seed_options(config)
    assert config == original


@pytest.mark.parametrize('key', SEED_KEYS)
@pytest.mark.parametrize('value', [True, False, None, -1, 4294967296, 1.0, '1', [], {}])
def test_invalid_seed_is_rejected_before_launch(key, value):
    with pytest.raises(ValueError, match=key):
        validate_seed_options({key: value})


def test_absent_seed_remains_absent():
    config = {'navigator.platform': 'Win32'}
    validate_seed_options(config)
    assert config == {'navigator.platform': 'Win32'}


@pytest.mark.parametrize('key', SEED_KEYS)
def test_public_launch_rejects_seed_before_resolving_binary(key, monkeypatch):
    from camoufox import utils

    def unexpected_binary_lookup(*args, **kwargs):
        pytest.fail('An invalid seed reached binary resolution')

    monkeypatch.setattr(utils, 'get_path', unexpected_binary_lookup)
    with pytest.raises(ValueError, match=key):
        utils.launch_options(config={key: True})


def test_schema_covers_uint32_seed_range():
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / 'settings/camoucfg.jvv').read_text(encoding='utf-8'))
    for key in SEED_KEYS:
        assert schema[key] == 'int[0-4294967295]'
