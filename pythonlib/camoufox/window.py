"""Resolution policy for the native window/portrait configuration API."""

import math
from typing import Any, Dict, Mapping

GEOMETRY_KEYS = (
    'screen.width', 'screen.height',
    'screen.availWidth', 'screen.availHeight',
    'screen.availLeft', 'screen.availTop',
    'window.outerWidth', 'window.outerHeight',
    'window.innerWidth', 'window.innerHeight',
    'window.screenX', 'window.screenY', 'window.devicePixelRatio',
    'document.body.clientWidth', 'document.body.clientHeight',
    'document.body.clientLeft', 'document.body.clientTop',
)

_POSITIVE = {
    'screen.width', 'screen.height', 'window.outerWidth', 'window.outerHeight',
    'window.innerWidth', 'window.innerHeight', 'window.devicePixelRatio',
}
_NONNEGATIVE = {
    'screen.availWidth', 'screen.availHeight',
    'document.body.clientWidth', 'document.body.clientHeight',
}
_PAIRS = (
    ('screen.width', 'screen.height'),
    ('screen.availWidth', 'screen.availHeight'),
    ('window.outerWidth', 'window.outerHeight'),
    ('window.innerWidth', 'window.innerHeight'),
    ('document.body.clientWidth', 'document.body.clientHeight'),
)


def validate_window_options(config: Mapping[str, Any]) -> None:
    mode = config.get('window:mode', 'auto')
    if mode not in ('auto', 'native'):
        raise ValueError("window:mode must be 'auto' or 'native'")
    if 'window:profile' not in config:
        return
    profile = config['window:profile']
    if not isinstance(profile, dict):
        raise ValueError('window:profile must be a mapping of geometry properties')
    for key, value in profile.items():
        if key not in GEOMETRY_KEYS:
            raise ValueError(f'Unknown window:profile property: {key}')
        floating = key in ('window.devicePixelRatio', 'window.innerWidth', 'window.innerHeight')
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'window:profile {key} must be numeric')
        if not floating and not isinstance(value, int):
            raise ValueError(f'window:profile {key} must be an integer')
        if not -(2**31) <= value <= 2**31 - 1 or not math.isfinite(value):
            raise ValueError(f'window:profile {key} is out of range')
        if (key in _POSITIVE and value <= 0) or (key in _NONNEGATIVE and value < 0):
            raise ValueError(f'window:profile {key} is out of range')
    for width, height in _PAIRS:
        if (width in profile) != (height in profile):
            raise ValueError(f'window:profile requires both {width} and {height}')


def finish_window_options(config: Dict[str, Any], *, explicit_global: bool) -> None:
    """Keep generated legacy dimensions from defeating an explicit new mode.

    User-supplied legacy dimensions still select global mode as before. Native
    mode is an explicit opt-out; in auto mode a portrait only takes effect when
    the caller did not also request global geometry.
    """
    native = config.get('window:mode') == 'native'
    profile_only = 'window:profile' in config and not explicit_global
    if native or profile_only:
        for key in GEOMETRY_KEYS:
            config.pop(key, None)


def effective_geometry(config: Mapping[str, Any]) -> Mapping[str, Any]:
    if config.get('window:mode') == 'native':
        return {}
    if any(key in config for key in GEOMETRY_KEYS):
        return config
    profile = config.get('window:profile')
    return profile if isinstance(profile, dict) else {}
