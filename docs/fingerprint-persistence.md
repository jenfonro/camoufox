# Fixed fingerprint inputs

Implemented on codex/fingerprint-persistence, based on WebGPU commit 7d2e264.
The branch includes the existing window modes and WebGPU configuration API.
Windows x64 verification is recorded in [the acceptance report](fingerprint-persistence-validation.md).

## Configuration contract

Use the existing Camoufox configuration keys. The kernel consumes fixed inputs;
the caller stores and replays the complete resolved profile and Firefox preferences.

| Input | Nonzero value | Omitted | Explicit zero |
| --- | --- | --- | --- |
| canvas:seed | Stable root for Firefox's enabled Canvas/WebGL randomization paths | Native session randomization | Native session randomization |
| audio:seed | Existing deterministic audio transformation | Native audio unless a context override exists | No custom audio transformation |
| fonts:spacing_seed | Existing deterministic glyph-advance adjustment | Native spacing unless a context override exists | No custom spacing adjustment |

All three launch inputs are JSON integers from 0 through 4294967295, inclusive.
Booleans, strings, null, fractional-number JSON values including 1.0, negatives,
and overflow are configuration errors. The Python launch API checks them before
resolving the binary; direct kernel launches print the offending key and exit 1
before browser/profile initialization.

These are independent seeds. There is no new manager-specific profile format or
Python master-seed API. A minimal seed fragment to merge into a complete profile is:

    {
      "canvas:seed": 123456789,
      "audio:seed": 234567891,
      "fonts:spacing_seed": 345678912
    }

Pass it through the existing config argument or CAMOU_CONFIG / CAMOU_CONFIG_n
transport. Canvas seed configuration is process-wide. The existing font/audio
context setters remain supported; a supplied context seed, including zero, takes
precedence over its process-wide value. Setters retain their existing init-script
window and are sealed before ordinary page script runs.

This change does not add a window.setCanvasSeed method. Multi-context callers
must observe the scope of the process-wide Canvas input and Firefox's native
OriginAttributes isolation. A persistent browser process per stored profile can
replay all three launch inputs directly.

## Native Canvas path

With a nonzero canvas:seed, nsRFPService derives stable session-key material from
the seed and OriginAttributes. Version 1 uses four big-endian seed bytes as the
HMAC-SHA256 key, the domain camoufox:canvas-seed:v1 followed by a NUL byte, and
the native OriginAttributes suffix. The first 16 digest bytes form the nsID
consumed by Firefox's existing per-site key derivation.

Permissions, site/container/private-origin partitioning, CookieJarSettings IPC,
ServiceWorker key generation, and encoder/extraction decisions remain native.
No clock, PID, profile-directory path, or freshly generated UUID enters the
configured root. Clearing the in-memory key cache reproduces the same key for
the same fixed inputs. Changing the seed deliberately changes that identity.

The seed preserves the selected protection mode. It does not enable a disabled
privacy feature. Under Firefox's default efficient mode, the PNG deBG metadata
becomes stable while source pixels remain native. In the full Canvas/WebGL
randomization mode, the existing pixel perturbation derives from the same stable
material. JPEG/WebP and unperturbed pixel reads follow their native extraction
rules; a seed does not require every format to produce different pixels.

Coverage includes HTMLCanvasElement, toDataURL, toBlob, getImageData,
OffscreenCanvas.convertToBlob, WebGL exports/readback, and supported Worker paths.
There is no page-side replacement of drawing methods or preset website hash.

## Audio, font and context corrections

- Audio copyFromChannel offsets advance the existing LCG to the corresponding
  sample index. A slice agrees with the same range from getChannelData.
- Acquiring JS audio channels for playback and restoring them no longer applies
  the transformation again. Caller-written channel samples also survive this
  lifecycle without additional perturbation.
- AnalyserNode applies frequency perturbation to returned values, preserving
  the native FFT smoothing history. Time-dependent live audio remains live audio.
- Word-cache keys include the resolved font seed. Shaped spaces carry the text
  run's context ID, and HTML/main-thread OffscreenCanvas/Worker text shaping uses
  the appropriate native window or Worker origin attributes.
- When a configured font allowlist requires global fallback, the search loads
  an eligible family's character map instead of skipping it while async loading
  is pending. This fixes cold/warm ClientRects drift without adding a rect seed.
- Roverfox per-context configuration uses runtime default preferences for IPC
  and ignores stale user-branch values. Temporary context IDs and setter flags
  are not newly persisted into prefs.js as profile identity.

## Complete profile replay

A stable seed is one part of the effective input. The caller also preserves:

| Surface | Existing configuration to replay |
| --- | --- |
| Fonts and audio | fonts, fonts:spacing_seed, audio:seed, AudioContext parameters |
| Canvas and WebGL | canvas:seed; webGl/webGl2 identity, parameters, extensions and precision values |
| WebGPU | gfx:hardwareAcceleration, webgpu:enabled, the complete webgpu:profile object including adapterOverrides |
| Geometry | window:mode and window:profile, or the explicit legacy global geometry |
| Other identity | navigator fields, language/timezone, voices and media-device configuration |
| Behavior | Explicit Firefox preferences, permissions and relevant launch options |

The Python wrapper still generates omitted fingerprint fields as before. Saving
only the three seeds while regenerating the rest of a profile does not preserve
its complete identity. User-directory reuse continues to preserve Firefox's
ordinary cookies, storage and window state; it is not a replacement for input replay.

The guarantee is for unchanged inputs and comparable browser, resources,
rendering environment, page content and permission state. Browser/driver/font
upgrades are separate compatibility events. Current time, actual network exits,
live signal measurements and site session state retain their native meanings.

## Build and tests

The Firefox source edits are exported in patches/zzz-fingerprint-persistence.patch,
which is applied after the inherited window/WebGPU patches. New shared C++
helpers live in additions/camoucfg. GNU patch applied to the saved preceding
source state on Linux reproduces all 16 compiled source files byte for byte.
The Windows git-apply check also succeeds, with Git's local line-ending conversion.

The focused tests are:

- tests/native/fingerprint-seeds.cpp: JSON/uint32 contract and indexed audio sequences.
- pythonlib/tests/test_fingerprint_seed_config.py: Python input contract and early public-API rejection.
- tests/patches/fingerprint-persistence-windows.py plus its JS probe: complete
  BrowserScan reports, native bytes, three restarts, Worker/iframe paths,
  input changes, native defaults, lifecycle and direct-startup errors.
- tests/patches/fingerprint-seed-contexts.py: existing setters, explicit zero,
  launch/context precedence, repeated pages and all three Worker types.

The build-tester Canvas/emoji checks now hash the entire exported data URL,
including trailing PNG metadata. Font-list hashes also retain the complete list.
