# Window resolution and native window state

Camoufox separates content-facing geometry from the geometry used by browser
chrome, layout management, and Firefox's window-state restoration. Configuration
is read at process startup; changing a portrait requires restarting the process.

## Inputs and precedence

The existing top-level `screen.*`, window dimension/position/DPR, and
`document.body.client*` properties retain their global-override role. Existing
callers do not need to change their property names.

`window:profile` is a new object containing the same geometry property names.
It supplies reported geometry without resizing the desktop window or pinning
the browser's content stack. In the default `window:mode = "auto"` policy:

| Inputs | Actual browser window | Content-facing geometry |
| --- | --- | --- |
| Any legacy/global geometry property | Apply the legacy global window sizing rules | Use global properties |
| Only `window:profile` | Firefox manages and restores the window | Use the portrait properties |
| Neither | Firefox's native startup and restoration | Firefox's native APIs |

Global input wins **as a whole**, including when a portrait is also present.
Unspecified fields are not borrowed from the lower-priority portrait. Other
fingerprint properties, such as `window.history.length`, do not select global
geometry.

`window:mode = "native"` is an explicit opt-out. It ignores both geometry
inputs and per-context screen-dimension overrides. This is useful with callers
that otherwise generate resolution properties automatically. Other fingerprint
surfaces are unaffected.

## Examples

Legacy global sizing, using the existing API:

```json
{
  "screen.width": 1920,
  "screen.height": 1080,
  "screen.availWidth": 1920,
  "screen.availHeight": 1040,
  "window.outerWidth": 1200,
  "window.outerHeight": 900
}
```

An independent portrait, with a freely movable and resizable desktop window:

```json
{
  "window:profile": {
    "screen.width": 1920,
    "screen.height": 1080,
    "screen.availWidth": 1920,
    "screen.availHeight": 1040,
    "window.devicePixelRatio": 1.0
  }
}
```

Explicit native geometry:

```json
{ "window:mode": "native" }
```

Pass these objects through `CAMOU_CONFIG` / `CAMOU_CONFIG_<n>`, or through the
Python package's existing `config=` argument. In profile-only and native modes,
the Python wrapper removes automatically generated legacy geometry. Explicitly
supplied legacy geometry, `window=`, `screen=`, or a custom BrowserForge
fingerprint retains global precedence in auto mode. An explicit Playwright
viewport request remains a real viewport request; the wrapper suppresses only
Playwright's implicit default viewport in profile/native modes.

## Portrait properties

Supported fields are `screen.width/height`, `screen.availWidth/availHeight`,
`screen.availLeft/availTop`, `window.outerWidth/outerHeight`,
`window.innerWidth/innerHeight`, `window.screenX/screenY`,
`window.devicePixelRatio`, and `document.body.clientWidth/clientHeight/clientLeft/
clientTop`. Width/height pairs should be supplied together. Screen dimensions
are CSS pixels; positions may be signed and DPR may be fractional.

When a portrait supplies a screen size without an available size, the available
size defaults to that portrait screen size. An explicit available rectangle
can reserve space for a taskbar. The portrait does not copy these values from
the machine's display.

Portraits override the configured reporting APIs. They do not create a virtual
display, scale rendered content, or freeze the actual layout viewport. When
viewport fields are omitted, they continue to describe the actual viewport.
When explicitly overriding viewport fields, element/layout measurements still
describe actual layout.

## Window-state behavior

In profile and native modes, the browser performs no Camoufox startup resize
and does not force the window into normal mode. Firefox's existing `screenX`,
`screenY`, `width`, `height`, and `sizemode` persistence remains responsible for
restoration, including maximized windows and display/DPI handling. No separate
window-state database is introduced.

In global mode, the explicit override takes precedence over the restored
geometry. Its legacy default size and optional fixed content dimensions are
confined to that mode. Browser chrome always reads real geometry; only the
startup sizing code consumes the global resize request. Juggler likewise waits
for actual docshell viewport dimensions, not portrait getter values.

## Verification

The native policy regression test can run on the Linux build host:

```sh
g++ -std=c++17 -I additions/camoucfg tests/native/window-resolution.cpp -o /tmp/window-resolution-test
/tmp/window-resolution-test
python -m pytest pythonlib/tests/test_window_resolution.py pythonlib/tests/test_viewport_default.py pythonlib/tests/test_config_schema.py
```

The Windows runtime check launches a supplied binary with isolated persistent
profiles, reads a local page's own geometry report, and compares it with Win32
window bounds. It moves/resizes only its own test windows and injects no desktop
mouse or keyboard input:

```powershell
python tests/patches/window-resolution-windows.py --executable path/to/camoufox.exe --report-dir path/to/test-results
```

Runtime verification on 2026-09-10 passed the three modes, global precedence,
move/resize restoration, maximized-state restoration, CSS screen/DPR queries,
legacy fixed inner/outer dimensions, and legacy inner-only sizing. In the
portrait case, content reported an outer size of 1680×980 while the real window
was 1120×780; resizing the real window to 1040×740 left the portrait unchanged
and the new real bounds survived a restart. Reports and test profiles are
retained under the supplied results directory.

## Incremental Windows x64 builds

Use a persistent Linux build tree and keep its object directory and compiler
cache. On a minimal Ubuntu 24.04 host, the bootstrapped Wine/MIDL tools also
need `libc6-i386`, `lib32gcc-s1`, and `lib32stdc++6`, even for the x64 target.

After the initial source/toolchain setup, build from the prepared Firefox tree:

```sh
CARGO_BUILD_JOBS=1 CCACHE_MAXSIZE=10G ./mach build -j 4
```

Then run `make package-windows arch=x86_64` from the Camoufox repository root.
Normal iterations should preserve the prepared source and object directory;
`make setup` and `make clean` recreate or discard that state.
