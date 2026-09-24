# Native control protocol v1

This Camoufox build provides an opt-in local control component. It uses native
Firefox browser services and window actors. It does not start a BiDi,
Marionette, or Juggler session, attach a JavaScript `Debugger`, or install a
WebExtension. All state described here is internal to the authorized connection;
the component does not add a control object to web pages.

This is a Camoufox protocol, not an implementation of WebDriver BiDi. Its object,
coordinate, keyboard, and action names follow existing browser terminology.
Business workflows, profile generation, action timing policy, VNC, and desktop
input are the caller's responsibility.

Windows x64 implementation, build and validation are complete; see
[the verification report](native-control-verification.md) for the delivered
artifact and tested scope. Continuation records are in
[the work checklist](native-control-plan.md). Other platforms have not been
runtime-validated.

## Launch configuration

Use the existing `CAMOU_CONFIG` JSON or `CAMOU_CONFIG_<n>` transport.

| Property | Type | Default / meaning |
| --- | --- | --- |
| `control:enabled` | boolean | `false`; no service or content actors are initialized |
| `control:port` | integer, 0–65535 | `0`, ask the OS for an available loopback port |
| `control:token` | string | Required when enabled; 32–256 base64url characters, generated randomly by the caller |
| `control:endpoint` | absolute filename | Required when enabled; a **new** discovery file in a caller-controlled directory |

The endpoint file contains `protocolVersion`, `transport`, `host`, `port`,
`processId`, and `instance`. It never contains the token. Creation is exclusive:
an existing file is an error, not something to overwrite. A normally stopped
instance removes its own file; after a crash the caller should use a fresh
filename or remove a stale file after checking the old process has exited.
File permissions are restricted to the creating user where supported by the OS.

The socket binds to loopback only, including when a fixed port is requested.
Connections from other local programs still require the token. WebSocket and
HTTP requests are not accepted. The caller passes the token out of band and
should not put it in command-line arguments or logs.

Native control and explicit `--juggler-pipe`, `--marionette`, or remote-debugging
startup are mutually exclusive. Invalid configuration logs an error and leaves
the native service unavailable; it does not silently start another protocol.
The ordinary explicit Playwright/Juggler launch path remains available when
native control is disabled.

Example using only the Python standard library:

```python
import json, os, secrets, subprocess
from pathlib import Path

token = secrets.token_urlsafe(32)
endpoint = Path("work/endpoint.json").resolve()  # parent directory already exists
config = {
    "control:enabled": True,
    "control:token": token,
    "control:endpoint": str(endpoint),
    "control:port": 0,
}
env = {**os.environ, "CAMOU_CONFIG": json.dumps(config)}
process = subprocess.Popen([
    r"path\to\camoufox.exe", "-no-remote", "-wait-for-browser",
    "-profile", r"path\to\owned-profile"
], env=env)
# Wait for endpoint to contain valid JSON, checking process.poll() and a timeout.
```

The connection does not own the browser process: disconnecting releases its
input and interceptions, but leaves the browser and profile open.

## Transport and request lifecycle

Send UTF-8 JSON objects terminated by LF, one per line, over TCP. The first
message must authorize the connection:

```json
{"id":1,"method":"control.connect","params":{"protocolVersion":1,"token":"<out-of-band-token>"}}
```

Success returns `{ "id": 1, "result": { "protocolVersion": 1, "session": "...",
"instance": "...", "capabilities": {...} } }`. Compare `instance` to the discovery
file. Failure returns `{ "id": 1, "error": { "code": "...", "message": "..." } }`
and closes the connection. Unauthenticated connections expire after five seconds.

Subsequent messages have `{id, method, params, timeout?}`. `id` is a nonnegative
safe integer or a nonempty string of at most 128 characters; it cannot be reused
while pending. `params` defaults to `{}`. `timeout` is in milliseconds, defaults
to 30000, and accepts 1–120000. Replies can arrive out of order. Events have
`{method, params}` without an `id`.

Limits: eight connections, 32 pending requests per connection, 8 MiB per incoming
frame, 64 MiB queued outgoing data per connection. Slow clients that exhaust the
output queue are disconnected and their blocked requests are released.

`control.cancel` takes `{request: id}` and cancels a pending request on the same
connection. Cancellation/timeout ends the wait and stops future queued input.
Already delivered input, navigation, downloads, or JavaScript side effects are
not rolled back. A synchronous page script cannot be preempted by this API;
scripts with infinite loops can block that content process just as normal page
scripts can. Async script waits are cancellable without loading a debugger.

Errors include `invalid argument`, `unknown method`, `authentication failed`,
`unsupported version`, `no such context`, `no such document`, `stale element`,
`element not interactable`, `move target out of bounds`, `input busy`,
`input timeout`, `cancelled`, `timeout`, `resource limit`, and
`unsupported operation`. Errors do not trigger a fallback to another control path.

## Subscriptions and objects

`control.subscribe` takes `{events: [...], contexts?: [...]}` and returns a
`subscription` ID. Event names, domain wildcards such as `"network.*"`, and `"*"`
are accepted. A context filter includes descendant frames.
`control.unsubscribe` takes `{subscriptions: [...]}`.
An intercepted request and its timeout event are always delivered to the
connection responsible for releasing it, even without a matching subscription.

Context IDs identify live Firefox `BrowsingContext` objects. A frame can retain
its ID through navigation. Node IDs are connection- and document-scoped weak
references; detached nodes, navigation, explicit release, and disconnect make
them unusable. Reconnect obtains a new session and new node references; it does
not restore input button state or old interceptions.
Disconnect also releases connection-owned state in documents kept in BFCache.
Frame creation/destruction events carry `parent` and `ancestors`, so a
subscription scoped to a parent receives the destruction event after the frame
has left the live tree.

## Browser and browsing contexts

| Method | Parameters / result |
| --- | --- |
| `browser.getInfo` | Browser version, build ID, process ID, protocol version. Optional `diagnostics: true` reports internal modules, existing actors and focus/BFCache override state; it does not attach a debugger |
| `browser.close` | Requests a normal browser shutdown; native unload/dialog rules still apply |
| `browsingContext.getTree` | `root?`, `maxDepth?` (0–100); returns `contexts` with context, parent, URL, userContextId, originalOpener, children |
| `browsingContext.getFrame` | Parent `context` and exactly one of `selector` (CSS, one iframe/frame) or `child` (context ID). Returns `{context, visible}`; `context: null` if absent. Ambiguous/non-frame selectors are errors |
| `browsingContext.create` | `type: "tab" | "window"` (tab), `referenceContext?`, `background?`, `userContextId?` for a tab, `private?` for a window; returns `context` |
| `browsingContext.close` | Requests normal closure of `context`, a top-level tab; native unload dialogs can defer it |
| `browsingContext.activate` | `context`; selects its tab, raises the browser window and focuses content as an explicit action |
| `browsingContext.navigate` | `context`, absolute `url`, `wait?: "none" | "interactive" | "complete"` |
| `browsingContext.reload` | `context`, `ignoreCache?`, `wait?` |
| `browsingContext.traverseHistory` | `context`, signed integer `delta`, `wait?`; zero does nothing |

`originalOpener` records Firefox's cross-group creation source, including
`noopener` tabs, independently of the page's `window.opener`. It remains the
source context ID if that source closes while the control component is active.
It is null when Firefox has no known source; unrelated new tabs are not inferred
from selection, ordering, or URL.

Frame lookup uses the native embedder element and browsing context association.
It emits no page messages and does not modify frame names, attributes or globals.
Visibility uses the real parent viewport, independently of profile dimensions.

Navigation waits observe a new navigation before accepting document readiness,
including same-document commits whose URL is unchanged.
They follow native redirects and navigation security rules. A wait is bounded
by the request timeout and can be cancelled.

Lifecycle events include `browsingContext.created`, `.destroyed`, `.activated`,
`.navigationStarted`, `.navigationCommitted`, `.navigationFailed`,
`page.DOMContentLoaded`, `page.load`, `page.pageshow`, and `page.pagehide`.

## DOM and script

All these methods take `context`.

| Method | Parameters / result |
| --- | --- |
| `page.info` | URL, title, readiness, real viewport, document dimensions, scroll and focus |
| `dom.query` | `selector?` (CSS), `text?`, `exact?`, `root?` (node ID), `pierce?` (open shadow roots), `visible?`, `limit?` (1–1000). Returns node descriptions |
| `dom.get` | `node`, `html?`; description, value and optional outer HTML |
| `dom.release` | `nodes: [...]`; release handles no longer needed |
| `dom.focus` | `node`, `preventScroll?`; normal DOM focus, not a click |
| `dom.scrollIntoView` | `node`; instant scrolling to center |
| `dom.setFiles` | File input `node`, absolute `files: [...]`; empty clears, input multiplicity is respected |
| `script.evaluate` | `expression`, `world?: "isolated" | "main"` (isolated), `awaitPromise?` (true); JSON result by value |

Descriptions include tag name, text, attributes, real bounding rect, visibility,
enabled state, and whether the center is hit-testable. There is a 4096-handle
limit per connection/document and a 50000-element query scan bound. Closed
shadow roots are not pierced.

Isolated evaluation uses a privileged-created, content-principal sandbox with
Xrays. Main-world evaluation calls a Chrome-only C++ embedder method which
compiles in the target content realm; it does not call a page-replaceable
`window.eval` or attach `Debugger`. Results are `{type, value}`; undefined and nonfinite numbers have
explicit representations, bigint values are decimal strings. Cyclic objects,
functions and other non-JSON values are not remote object handles.
Browser-privileged documents do not allow page DOM/script commands.
Authorized control execution also works on pages whose CSP prohibits page
script evaluation. It does not modify their CSP: the page's own `eval()`,
dynamic script loading, same-origin checks and permissions still follow normal
Firefox rules. The client can address another frame explicitly.

## Input and geometry

Input commands select the tab as an explicit operation. All coordinates are
**real viewport CSS pixels** of `context`, not the reported values of
`window:profile`, `screen.*`, or spoofed DPR. Child-frame coordinates are mapped
through the frame's actual content quad, then through native full-page zoom.
This conversion is centralized with the existing parent input boundary guards.
It uses measured dimensions because Gecko's app-unit rounding can make the
effective pixel scale differ slightly from the requested zoom percentage.
Element commands take a `node` handle.
`input.click` scrolls a node into view, then checks its center.

| Method | Main parameters |
| --- | --- |
| `input.dispatchPointer` | `context`, `type: "pointerMove" | "pointerDown" | "pointerUp"`, `x/y?` or `node?`, `button?`, `clickCount?`, `modifiers?` |
| `input.click` | `context`, `x/y` or `node`, `button?`, `count?` (1–3), `modifiers?` |
| `input.dispatchKey` | `context`, `type: "keydown" | "keyup"`, `key`, `code?`, `keyCode?`, `location?`, `repeat?` |
| `input.insertText` | `context`, `text`; native text-input composition/commit, supports Unicode |
| `input.dispatchWheel` | `context`, `x`, `y`, `deltaX?`, `deltaY?`, `deltaMode?` (0 pixels, 1 lines, 2 pages), `modifiers?` |
| `input.performActions` | `context`, `actions: [...]` |
| `input.releaseActions` | `context`; release pressed keys/buttons and an active drag |

Buttons use DOM numbering: 0 primary, 1 auxiliary, 2 secondary, 3 back, 4 forward.
Modifiers are `Shift`, `Control`, `Alt`, `Meta`. `key` uses UI Events names or a
Unicode character, not WebDriver's private-use escape codes. `code` describes
physical position; provide it explicitly when keyboard layout matters.
When omitted, physical codes are derived only for known keys. Arbitrary Unicode,
including supplementary characters, uses an unspecified physical code.

Action sources have `id`, `type` (`pointer`, `key`, `wheel`, `none`), and
`actions`. Pointer sources support `parameters: {pointerType: "mouse"}`.
One source of each physical type is supported. Actions include `pointerMove`,
`pointerDown`, `pointerUp`, `keyDown`, `keyUp`, `scroll`, and `pause`.
Move `origin` is `"viewport"`, `"pointer"`, or `{node: id}`. Durations are in
milliseconds. A source ID keeps its type until release. Ticks keep the
longest action duration; instantaneous key/button transitions are applied before
duration-based pointer movement.
A source accepts at most 1000 actions per request. Text callers can submit
successive batches ending at key-up boundaries on the same source, with one
overall deadline. `scroll` spreads its signed deltas over its duration; zero
duration dispatches immediately. `pointerDown` and `pointerUp` accept matching
`clickCount` values for successive clicks, including double-clicks.

Mouse movement while a button is held can initiate native drag-and-drop.
Subsequent moves and release use the native drag session; Escape/release/disconnect
ends it. The endpoint does not inject a second humanized trajectory over supplied
actions, regardless of the legacy Juggler `humanize` option.
Mouse and wheel completion uses Firefox's native callbacks through APZ and
out-of-process frames, with a five-second delivery bound. Keys and text use the
native text-input processor on the browser widget, including browser shortcuts.
An acknowledged mouse action remains successful when its event handler destroys
the source document. A later action targeting that missing context still fails.
`input.releaseActions` releases the connection's state even if the context has
closed; it does not activate a replacement document.

Commands are serialized for the shared physical input state. Another connection
cannot take over while a connection has pressed keys/buttons. Errors, cancellation,
and disconnect attempt bounded release of that connection's input state.
OS-level input from another application is outside this connection's state model.

## Screenshots

`browsingContext.captureScreenshot` takes `context`, optional `fullPage`, optional
`clip: {x,y,width,height}`, `scale?`, `format?: "png" | "jpeg" | "webp"`,
`quality?` (0–1). A clip is in real **document** CSS pixels. With no clip, the
visible viewport is captured, or the full document when `fullPage` is true.
Scale defaults to native browser DPR including full-page zoom. Returned `{mimeType,data,width,height}`
contains base64 image bytes. Encoding occurs in browser chrome and does not run
the page's Canvas fingerprint readout.

The compositor snapshot supports cross-process frames. Maximum dimensions are
32767 per axis and 100 million pixels; the connection's output limit also applies.
Continuous recording is not provided.

## Storage, permissions and browser interactions

Local/session storage: `storage.get`, `.set`, `.remove`, `.clear` take `context`,
`area?: "local" | "session"` (local), optional expected `origin`.
Set uses string-valued `entries`; remove uses `key`. Get returns `{origin,entries}`.
The current document's native security, container, private and partition rules apply.

Cookies: `storage.getCookies`, `.setCookie`, `.deleteCookies` accept `context` or
explicit Firefox `originAttributes`. Get/delete filters are `name?`, `domain?`,
`path?`. Set takes `cookie: {name,value,url? or domain,path?,secure?,httpOnly?,
sameSite?: "None" | "Lax" | "Strict",expires?}`. Public expiry is Unix seconds;
omitting it creates a session cookie. Native prefixes, partition attributes and
cookie policy still apply. No implicit cross-container enumeration is performed.

Permissions: `permissions.get`, `.set`, `.reset` use `origin`, `name`,
`context?`/`originAttributes?`. Set uses `state: "granted" | "denied" | "prompt"`,
`persistent?` (false). `geolocation` and `notifications` map to Firefox's
`geo` and `desktop-notification`; other names use Firefox's permission types.

Dialogs: `page.getDialogs` takes `context`, returns IDs, types, messages and
default values. `page.handleDialog` takes `context`, `dialog`, `accept` and
optional prompt `text`. Events are `page.DOMWillOpenModalDialog` and
`page.DOMModalDialogClosed`. Native browser/OS file dialogs are not a desktop API;
use `dom.setFiles` for a file input.

Downloads: `downloads.get` returns live native download records; `downloads.cancel`
takes `download`. Events are `downloads.created`, `.changed`, `.removed`.
Destination and save prompts follow the profile's normal Firefox download
preferences; connecting does not rewrite those preferences.

## HTTP observation and interception

`network.enable` takes optional `contexts` (all browser tabs by default).
`network.disable` releases that connection's observation and interception.
Events are `network.beforeRequestSent`, `.responseStarted`, `.responseCompleted`,
`.requestFailed`, and `.interceptExpired`.

`network.addIntercept` takes `contexts?`, `urlPatterns?: ["*"]` (simple `*`
wildcards), `phases?: ["beforeRequestSent"]`, `timeout?` (100–120000 ms).
It returns `intercept`. Adding a rule enables observation for its owner.
Overlapping rules use registration order. A blocked request's ID is `request`;
only the owning connection can complete it.

| Method | Parameters |
| --- | --- |
| `network.removeIntercept` | `intercept`; resumes its pending requests |
| `network.continueRequest` | `request`, optional `url`, `method`, `headers`, base64 `body` |
| `network.failRequest` | `request`; aborts it |
| `network.provideResponse` | `request`, `status?` (200), `statusText?`, `headers?`, base64 `body?` |
| `network.getResponseBody` | `request`; returns base64 `data` and `base64Encoded: true` |

Headers are arrays of `{name,value}`. Binary bodies always use base64. The native
response cache is bounded (100 MiB per tracked tab, 10 MiB per response); evicted
bodies produce a resource error. Request metadata is also bounded.
Timeout, rule removal or disconnect resumes paused requests instead of leaving
the browser wedged. Normal proxy configuration and HTTP authentication prompts
are preserved.

The reused native channel implementation supports interception before the
initial request, not response-stage interception or pausing a redirect hop.
Redirects are observed. Service-worker/cache behavior follows Firefox's channel
semantics. WebSocket frame interception and worker execution are not v1 commands.

## Client and verification

[`scripts/native_control_client.py`](../scripts/native_control_client.py) is a
small reusable Python client and CLI with no third-party dependencies. The CLI
reads its token from `CAMOUFOX_CONTROL_TOKEN` by default:

```text
python scripts/native_control_client.py --endpoint <file> browser.getInfo
```

The direct runtime guard is
[`tests/native-control/verify.py`](../tests/native-control/verify.py). It launches
an explicitly named executable into owned profiles and connects through this
transport. The patch-guard wrapper makes it part of the existing CI guard suite.
Old-protocol compatibility tests are separate evidence; they do not prove the
native path is independent of debugging.
[`tests/native-control/lifecycle.py`](../tests/native-control/lifecycle.py)
additionally launches a page before any client connects, compares its reported
state through connect/disconnect/reconnect, and checks simultaneous instances.

The guard exercises deliberately different real viewport and reported profile
geometry. `--mode persistence --config <fixed.json>` compares complete native
fingerprint data across three normal restarts. The separate
[`tests/native-control/website.py`](../tests/native-control/website.py) compares
all eight full BrowserScan identity hashes, identity cells and Canvas/WebGPU
detail data. Its optional `--settled` mode preserves initial reports and uses
the site's visible Check again once after its own UI has loaded, matching the
previously documented BrowserScan named-element race. It never exempts a hash.

Local IPC, OS handles, process environment and deliberate script/input activity
can be observable to sufficiently privileged software. No guarantee of universal
undetectability is made.
