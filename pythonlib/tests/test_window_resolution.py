import copy

import pytest

from camoufox.window import effective_geometry, finish_window_options, validate_window_options


def test_profile_survives_generated_global_dimensions():
    config = {
        'window:profile': {'screen.width': 1920, 'screen.height': 1080},
        'screen.width': 1366, 'screen.height': 768,
        'window.outerWidth': 1200, 'window.innerWidth': 1180,
        'window.devicePixelRatio': 1, 'navigator.platform': 'Win32',
    }
    profile = copy.deepcopy(config['window:profile'])
    finish_window_options(config, explicit_global=False)
    assert 'window.outerWidth' not in config
    assert 'screen.width' not in config
    assert 'window.devicePixelRatio' not in config
    assert config['navigator.platform'] == 'Win32'
    assert config['window:profile'] == profile
    assert effective_geometry(config)['screen.width'] == 1920


def test_explicit_legacy_dimensions_take_priority():
    config = {'window.outerWidth': 1100, 'window:profile': {'screen.width': 1920, 'screen.height': 1080}}
    finish_window_options(config, explicit_global=True)
    assert effective_geometry(config)['window.outerWidth'] == 1100
    assert 'screen.width' not in effective_geometry(config)


def test_native_mode_cannot_be_overridden_by_generation():
    config = {'window:mode': 'native', 'screen.width': 1920, 'window.innerWidth': 1000,
              'navigator.platform': 'Win32'}
    finish_window_options(config, explicit_global=True)
    assert config == {'window:mode': 'native', 'navigator.platform': 'Win32'}
    assert effective_geometry(config) == {}


@pytest.mark.parametrize('profile', [
    None, [], {'unknown': 1}, {'screen.width': 1000},
    {'screen.width': True, 'screen.height': 1080},
    {'screen.width': -1, 'screen.height': 1080},
    {'screen.width': 2**32, 'screen.height': 1080},
    {'window.devicePixelRatio': float('nan')},
    {'window.devicePixelRatio': 0},
])
def test_invalid_profile_is_rejected(profile):
    with pytest.raises(ValueError):
        validate_window_options({'window:profile': profile})


def test_profile_accepts_signed_positions_and_positive_scale():
    validate_window_options({'window:profile': {'screen.width': 1920, 'screen.height': 1080,
                                              'window.screenX': -100, 'window.devicePixelRatio': 1.5}})


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        validate_window_options({'window:mode': 'portrait'})
