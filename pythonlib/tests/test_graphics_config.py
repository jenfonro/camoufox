import copy
import json
import re
from pathlib import Path

import pytest

from camoufox.graphics import FEATURES, LIMITS, WGSL_FEATURES, validate_graphics_options

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('config', [
    {}, {'gfx:hardwareAcceleration': True}, {'webgpu:enabled': False},
    {'webgpu:profile': {}},
    {'webgpu:profile': {'adapter': {'info': {'vendor': '', 'isFallbackAdapter': False}, 'features': []}}},
    {'webgpu:profile': {'adapter': {'limits': {'maxBufferSize': 2**32, 'maxBindGroups': 4.0}}}},
    {'webgpu:profile': {'gpu': {'wgslLanguageFeatures': [], 'preferredCanvasFormat': 'rgba8unorm'}}},
])
def test_optional_native_and_explicit_values(config):
    previous = copy.deepcopy(config)
    validate_graphics_options(config)
    assert config == previous


@pytest.mark.parametrize('profile', [
    None, [], {'adapter': None}, {'adapter': {'unknown': 1}},
    {'adapter': {'info': {'vendor': 2}}},
    {'adapter': {'info': {'isFallbackAdapter': 0}}},
    {'adapter': {'limits': {'maxBindGroups': True}}},
    {'adapter': {'limits': {'maxBufferSize': 2**53}}},
    {'adapter': {'limits': {'maxBindGroups': -1}}},
    {'adapter': {'limits': {'maxBindGroups': 1.5}}},
    {'adapter': {'limits': {'maxBindGroups': float('nan')}}},
    {'adapter': {'features': ['not-a-feature']}},
    {'gpu': {'wgslLanguageFeatures': ['unrestricted_pointer_parameters']}},
    {'gpu': {'preferredCanvasFormat': 'rgba16float'}},
    {'adapterOverrides': [{'request': {}, 'adapter': {}}]},
    {'adapterOverrides': [{'request': {'powerPreference': 'automatic'}, 'adapter': {}}]},
    {'adapterOverrides': [{'request': {'forceFallbackAdapter': 'true'}, 'adapter': {}}]},
])
def test_invalid_profile_does_not_silently_become_native(profile):
    with pytest.raises(ValueError, match='webgpu:profile'):
        validate_graphics_options({'webgpu:profile': profile})


@pytest.mark.parametrize('key', ['gfx:hardwareAcceleration', 'webgpu:enabled'])
@pytest.mark.parametrize('value', [1, 0, 'true', None])
def test_booleans_are_not_numeric_modes(key, value):
    with pytest.raises(ValueError, match=re.escape(key)):
        validate_graphics_options({key: value})


def test_request_specificity_and_ambiguity():
    overrides = [
        {'request': {'forceFallbackAdapter': True}, 'adapter': {}},
        {'request': {'forceFallbackAdapter': True, 'powerPreference': 'high-performance'}, 'adapter': {}},
    ]
    validate_graphics_options({'webgpu:profile': {'adapterOverrides': overrides}})
    overrides[1]['request'] = {'powerPreference': 'high-performance'}
    with pytest.raises(ValueError, match='ambiguous'):
        validate_graphics_options({'webgpu:profile': {'adapterOverrides': overrides}})
    overrides[1]['request'] = {'forceFallbackAdapter': False}
    validate_graphics_options({'webgpu:profile': {'adapterOverrides': overrides}})


def test_schema_native_and_python_have_same_field_vocabulary():
    native = (ROOT / 'additions/camoucfg/GraphicsConfig.hpp').read_text(encoding='utf-8')
    for symbol, expected in [('FeatureNames', FEATURES), ('WgslFeatureNames', WGSL_FEATURES), ('LimitNames', LIMITS)]:
        body = native.split(symbol + '[] = {', 1)[1].split('};', 1)[0]
        assert set(re.findall(r'"([^"]+)"', body)) == expected
    schema = json.loads((ROOT / 'settings/camoucfg.jvv').read_text(encoding='utf-8'))
    assert set(schema['@WEBGPU_ADAPTER']['limits']) == LIMITS
    declared = {entry['property'] for entry in json.loads((ROOT / 'settings/properties.json').read_text())}
    assert {'gfx:hardwareAcceleration', 'webgpu:enabled', 'webgpu:profile'} <= declared
