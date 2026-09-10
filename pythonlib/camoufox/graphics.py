"""Validation for the kernel's optional graphics policy and WebGPU profiles."""

import math
from typing import Any, Dict, Iterable

FEATURES = frozenset({
    'core-features-and-limits', 'depth-clip-control', 'depth32float-stencil8',
    'texture-compression-bc', 'texture-compression-bc-sliced-3d',
    'texture-compression-etc2', 'texture-compression-astc',
    'texture-compression-astc-sliced-3d', 'timestamp-query',
    'indirect-first-instance', 'shader-f16', 'rg11b10ufloat-renderable',
    'bgra8unorm-storage', 'float32-filterable', 'float32-blendable',
    'clip-distances', 'dual-source-blending', 'subgroups', 'primitive-index',
})
WGSL_FEATURES = frozenset({
    'packed_4x8_integer_dot_product', 'pointer_composite_access',
    'readonly_and_readwrite_storage_textures',
})
LIMITS = frozenset({
    'maxTextureDimension1D', 'maxTextureDimension2D', 'maxTextureDimension3D',
    'maxTextureArrayLayers', 'maxBindGroups', 'maxBindGroupsPlusVertexBuffers',
    'maxBindingsPerBindGroup', 'maxDynamicUniformBuffersPerPipelineLayout',
    'maxDynamicStorageBuffersPerPipelineLayout', 'maxSampledTexturesPerShaderStage',
    'maxSamplersPerShaderStage', 'maxStorageBuffersInVertexStage',
    'maxStorageBuffersInFragmentStage', 'maxStorageBuffersPerShaderStage',
    'maxStorageTexturesInVertexStage', 'maxStorageTexturesInFragmentStage',
    'maxStorageTexturesPerShaderStage', 'maxUniformBuffersPerShaderStage',
    'maxUniformBufferBindingSize', 'maxStorageBufferBindingSize',
    'minUniformBufferOffsetAlignment', 'minStorageBufferOffsetAlignment',
    'maxVertexBuffers', 'maxBufferSize', 'maxVertexAttributes',
    'maxVertexBufferArrayStride', 'maxInterStageShaderVariables',
    'maxColorAttachments', 'maxColorAttachmentBytesPerSample',
    'maxComputeWorkgroupStorageSize', 'maxComputeInvocationsPerWorkgroup',
    'maxComputeWorkgroupSizeX', 'maxComputeWorkgroupSizeY',
    'maxComputeWorkgroupSizeZ', 'maxComputeWorkgroupsPerDimension',
})
WIDE_LIMITS = frozenset({
    'maxBufferSize', 'maxUniformBufferBindingSize', 'maxStorageBufferBindingSize',
})
INFO_STRINGS = frozenset({'vendor', 'architecture', 'device', 'description'})
INFO_INTS = frozenset({'subgroupMinSize', 'subgroupMaxSize'})
REQUEST_FIELDS = frozenset({
    'powerPreference', 'forceFallbackAdapter', 'featureLevel', 'xrCompatible',
})


def _error(path: str, message: str) -> None:
    raise ValueError(f'{path}: {message}')


def _object(value: Any, path: str, allowed: Iterable[str]) -> None:
    if not isinstance(value, dict):
        _error(path, 'must be an object')
    for key in value:
        if key not in allowed:
            _error(f'{path}.{key}', 'unknown field')


def _uint(value: Any, path: str, maximum: int) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0 or value > maximum
            or (isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()))):
        _error(path, f'must be an unsigned integer <= {maximum}')


def _string_set(value: Any, path: str, allowed: Iterable[str]) -> None:
    if not isinstance(value, list):
        _error(path, 'must be an array')
    for index, name in enumerate(value):
        if not isinstance(name, str) or name not in allowed:
            _error(f'{path}[{index}]', 'unknown or unimplemented feature')


def _adapter(value: Any, path: str) -> None:
    _object(value, path, {'info', 'features', 'limits'})
    if 'info' in value:
        info = value['info']
        _object(info, f'{path}.info', INFO_STRINGS | INFO_INTS | {'isFallbackAdapter'})
        for key, item in info.items():
            at = f'{path}.info.{key}'
            if key in INFO_STRINGS and not isinstance(item, str):
                _error(at, 'must be a string')
            if key in INFO_INTS:
                _uint(item, at, 2**32 - 1)
            if key == 'isFallbackAdapter' and not isinstance(item, bool):
                _error(at, 'must be boolean')
    if 'features' in value:
        _string_set(value['features'], f'{path}.features', FEATURES)
    if 'limits' in value:
        _object(value['limits'], f'{path}.limits', LIMITS)
        for key, item in value['limits'].items():
            _uint(item, f'{path}.limits.{key}', 2**53 - 1 if key in WIDE_LIMITS else 2**32 - 1)


def validate_graphics_options(config: Dict[str, Any]) -> None:
    """Check shape and ambiguity without generating or mutating any profile.

    Backend capability checks remain in the kernel after adapter selection.
    Absent fields are native; empty/false/zero values are explicit inputs.
    """
    for key in ('gfx:hardwareAcceleration', 'webgpu:enabled'):
        if key in config and not isinstance(config[key], bool):
            _error(key, 'must be boolean')
    if 'webgpu:profile' not in config:
        return
    profile = config['webgpu:profile']
    path = 'webgpu:profile'
    _object(profile, path, {'gpu', 'adapter', 'adapterOverrides'})
    if 'gpu' in profile:
        gpu = profile['gpu']
        _object(gpu, f'{path}.gpu', {'wgslLanguageFeatures', 'preferredCanvasFormat'})
        if 'wgslLanguageFeatures' in gpu:
            _string_set(gpu['wgslLanguageFeatures'], f'{path}.gpu.wgslLanguageFeatures', WGSL_FEATURES)
        if 'preferredCanvasFormat' in gpu and gpu['preferredCanvasFormat'] not in ('rgba8unorm', 'bgra8unorm'):
            _error(f'{path}.gpu.preferredCanvasFormat', 'must be rgba8unorm or bgra8unorm')
    if 'adapter' in profile:
        _adapter(profile['adapter'], f'{path}.adapter')
    if 'adapterOverrides' not in profile:
        return
    overrides = profile['adapterOverrides']
    if not isinstance(overrides, list):
        _error(f'{path}.adapterOverrides', 'must be an array')
    seen = []
    for index, entry in enumerate(overrides):
        at = f'{path}.adapterOverrides[{index}]'
        _object(entry, at, {'request', 'adapter'})
        if 'request' not in entry or 'adapter' not in entry:
            _error(at, 'requires request and adapter')
        _adapter(entry['adapter'], f'{at}.adapter')
        request = entry['request']
        _object(request, f'{at}.request', REQUEST_FIELDS)
        if not request:
            _error(f'{at}.request', 'must not be empty')
        for key in ('forceFallbackAdapter', 'xrCompatible'):
            if key in request and not isinstance(request[key], bool):
                _error(f'{at}.request.{key}', 'must be boolean')
        if 'powerPreference' in request and request['powerPreference'] not in ('low-power', 'high-performance'):
            _error(f'{at}.request.powerPreference', 'must be low-power or high-performance')
        if 'featureLevel' in request and request['featureLevel'] not in ('core', 'compatibility'):
            _error(f'{at}.request.featureLevel', 'must be core or compatibility')
        for other_index, other in enumerate(seen):
            if len(request) == len(other) and all(other[key] == request[key] for key in other.keys() & request.keys()):
                _error(f'{at}.request', f'ambiguous with adapterOverrides[{other_index}]')
        seen.append(request)
