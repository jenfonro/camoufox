/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

const {ControlBrowser, METHODS} =
  ChromeUtils.importESModule("chrome://juggler/content/control/ControlBrowser.sys.mjs");
const {fail, object, string, number, bounded, errorObject, id, setTimeout, clearTimeout} =
  ChromeUtils.importESModule("chrome://juggler/content/control/ControlUtils.sys.mjs");

const VERSION = 1;
const MAX_FRAME = 8 * 1024 * 1024;
const MAX_OUTPUT = 64 * 1024 * 1024;
const MAX_PENDING = 32;
const MAX_CONNECTIONS = 8;
const AUTH_TIMEOUT = 5000;
const EVENTS = [
  "browsingContext.created", "browsingContext.destroyed", "browsingContext.activated",
  "browsingContext.navigationStarted", "browsingContext.navigationCommitted",
  "browsingContext.navigationFailed",
  "page.DOMContentLoaded", "page.load", "page.pageshow", "page.pagehide",
  "page.DOMWillOpenModalDialog", "page.DOMModalDialogClosed",
  "downloads.created", "downloads.changed", "downloads.removed",
  "network.beforeRequestSent", "network.responseStarted", "network.responseCompleted",
  "network.requestFailed", "network.interceptExpired",
];
const CONTROL_METHODS = ["control.connect", "control.subscribe", "control.unsubscribe", "control.cancel"];

// These limits describe this implementation, not all operations of Firefox.
// No remote debugger is started to implement a missing operation.
export const CAPABILITIES = {
  methods: [...CONTROL_METHODS, ...METHODS],
  events: EVENTS,
  scriptWorlds: ["main", "isolated"],
  pointerTypes: ["mouse"],
  interceptionPhases: ["beforeRequestSent"],
  screenshotFormats: ["png", "jpeg", "webp"],
  coordinates: "real viewport CSS pixels",
  workers: false,
  recording: false,
  transport: "loopback-tcp-ndjson",
  limits: {maxFrameBytes: MAX_FRAME, maxQueuedOutputBytes: MAX_OUTPUT,
    maxPendingRequests: MAX_PENDING, maxConnections: MAX_CONNECTIONS},
};

function tokenMatches(actual, expected) {
  if (typeof actual !== "string") return false;
  let difference = actual.length ^ expected.length;
  for (let i = 0; i < expected.length; i++)
    difference |= (actual.charCodeAt(i) || 0) ^ expected.charCodeAt(i);
  return difference === 0;
}

function bytes(value) {
  const encoded = new TextEncoder().encode(value);
  const chunks = [];
  for (let i = 0; i < encoded.length; i += 16384)
    chunks.push(String.fromCharCode(...encoded.subarray(i, i + 16384)));
  return chunks.join("");
}

class Connection {
  constructor(service, transport) {
    this.service = service;
    this.transport = transport;
    this.id = id();
    this.authenticated = false;
    this.closed = false;
    this.closing = false;
    this.subscriptions = new Map();
    this.pending = new Map();
    this.inputBytes = 0;
    this.text = "";
    this.decoder = new TextDecoder("utf-8", {fatal: true});
    this.outputQueue = [];
    this.outputOffset = 0;
    this.outputBytes = 0;
    this.input = transport.openInputStream(0, 0, 0);
    this.output = transport.openOutputStream(0, 0, 0).QueryInterface(Ci.nsIAsyncOutputStream);
    this.pump = Cc["@mozilla.org/network/input-stream-pump;1"].createInstance(Ci.nsIInputStreamPump);
    this.pump.init(this.input, 0, 0, true);
    this.pump.asyncRead(this);
    this.authTimer = setTimeout(() => this.close(), AUTH_TIMEOUT);
  }

  QueryInterface = ChromeUtils.generateQI(["nsIStreamListener", "nsIRequestObserver",
    "nsIOutputStreamCallback"]);
  onStartRequest() {}
  onStopRequest() { this.close(); }

  onDataAvailable(request, stream, offset, count) {
    if (this.closed || this.closing) return;
    try {
      const input = Cc["@mozilla.org/binaryinputstream;1"].createInstance(Ci.nsIBinaryInputStream);
      input.setInputStream(stream);
      const chunk = input.readByteArray(count);
      this.inputBytes += count;
      if (this.inputBytes > MAX_FRAME && !chunk.includes(10))
        fail("resource limit", "Request frame is too large");
      this.text += this.decoder.decode(new Uint8Array(chunk), {stream: true});
      let end;
      while ((end = this.text.indexOf("\n")) !== -1) {
        const line = this.text.slice(0, end);
        this.text = this.text.slice(end + 1);
        if (new TextEncoder().encode(line).length > MAX_FRAME)
          fail("resource limit", "Request frame is too large");
        if (!line.trim()) fail("invalid message", "Empty request frame");
        this.receive(JSON.parse(line));
        if (this.closed || this.closing) return;
      }
      this.inputBytes = new TextEncoder().encode(this.text).length;
      if (this.inputBytes > MAX_FRAME) fail("resource limit", "Request frame is too large");
    } catch (error) {
      this.send({id: null, error: {code: error.code || "invalid message",
        message: error.code ? error.message : "Expected one UTF-8 JSON object per line"}});
      this.closeAfterFlush();
    }
  }

  receive(message) {
    let requestId = null;
    try {
      object(message, "request");
      requestId = message.id;
      if (!((typeof requestId === "string" && requestId.length > 0 && requestId.length <= 128) ||
          (Number.isSafeInteger(requestId) && requestId >= 0)))
        fail("invalid argument", "id must be a nonnegative safe integer or a short nonempty string");
      const method = string(message.method, "method");
      const params = object(message.params ?? {});
      if (!this.authenticated) {
        if (method !== "control.connect" || !tokenMatches(params.token, this.service.token))
          fail("authentication failed", "Connection authorization failed");
        if (params.protocolVersion !== VERSION)
          fail("unsupported version", `Expected protocolVersion ${VERSION}`);
        this.authenticated = true;
        clearTimeout(this.authTimer);
        this.send({id: requestId, result: {protocolVersion: VERSION, session: this.id,
          instance: this.service.instance, capabilities: CAPABILITIES}});
        return;
      }
      if (method === "control.connect") fail("invalid state", "Connection is already authorized");
      const key = JSON.stringify(requestId);
      if (this.pending.has(key)) fail("invalid argument", "Request id is already pending");
      if (method.startsWith("control.")) {
        this.send({id: requestId, result: this.control(method, params)});
        return;
      }
      if (this.pending.size >= MAX_PENDING) fail("resource limit", "Too many pending requests");
      const timeout = number(message.timeout ?? 30000, "timeout", 1, 120000, true);
      const abort = new AbortController();
      this.pending.set(key, abort);
      // Dispatch is asynchronous so a blocked page operation never blocks
      // authentication, cancellation, or another tab's control messages.
      this.run(requestId, key, method, params, abort, timeout);
    } catch (error) {
      this.send({id: requestId, error: errorObject(error)});
      if (!this.authenticated) this.closeAfterFlush();
    }
  }

  control(method, params) {
    if (method === "control.cancel") {
      const pending = this.pending.get(JSON.stringify(params.request));
      if (!pending) fail("no such request", "Request is no longer pending on this connection");
      pending.abort(Object.assign(new Error("Request was cancelled"), {code: "cancelled"}));
      return {};
    }
    if (method === "control.subscribe") {
      if (!Array.isArray(params.events) || !params.events.length || params.events.length > 64)
        fail("invalid argument", "events must contain 1 to 64 event names");
      const events = new Set();
      for (const pattern of params.events) {
        string(pattern, "event");
        const matches = EVENTS.filter(event => pattern === "*" || pattern === event ||
          (pattern.endsWith(".*") && event.startsWith(pattern.slice(0, -1))));
        if (!matches.length) fail("invalid argument", `Unknown event: ${pattern}`);
        for (const event of matches) events.add(event);
      }
      if (this.subscriptions.size >= 64) fail("resource limit", "Too many subscriptions");
      let contexts = null;
      if (params.contexts !== undefined) {
        if (!Array.isArray(params.contexts) || !params.contexts.length)
          fail("invalid argument", "contexts must be a nonempty array");
        contexts = new Set(params.contexts.map(context => String(this.service.browser.context(context).id)));
      }
      const subscription = id();
      this.subscriptions.set(subscription, {events, contexts});
      return {subscription};
    }
    if (method === "control.unsubscribe") {
      if (!Array.isArray(params.subscriptions)) fail("invalid argument", "subscriptions must be an array");
      for (const subscription of params.subscriptions) {
        if (!this.subscriptions.has(subscription)) fail("invalid argument", "Unknown subscription");
      }
      for (const subscription of params.subscriptions) this.subscriptions.delete(subscription);
      return {};
    }
    fail("unknown method", `Unknown method: ${method}`);
  }

  async run(requestId, key, method, params, abort, timeout) {
    const timer = setTimeout(() => abort.abort(Object.assign(new Error("Operation timed out"), {code: "timeout"})), timeout);
    try {
      const result = await bounded(this.service.browser.command(method, params, this,
        {signal: abort.signal, timeout}), timeout + 100, abort.signal);
      if (!this.closed) this.send({id: requestId, result: result ?? {}});
    } catch (error) {
      if (!this.closed) this.send({id: requestId, error: errorObject(abort.signal.reason || error)});
    } finally {
      clearTimeout(timer);
      this.pending.delete(key);
    }
  }

  event(method, params, forced = false) {
    if (!this.authenticated || this.closed || this.closing) return;
    const matches = forced || [...this.subscriptions.values()].some(subscription => {
      if (!subscription.events.has(method)) return false;
      if (!subscription.contexts) return true;
      if (subscription.contexts.has(params.context)) return true;
      if (params.ancestors?.some(context => subscription.contexts.has(context))) return true;
      try {
        for (let bc = this.service.browser.context(params.context).parent; bc; bc = bc.parent)
          if (subscription.contexts.has(String(bc.id))) return true;
      } catch (_) {}
      return false;
    });
    if (matches) this.send({method, params});
  }

  send(message) {
    if (this.closed) return;
    let data;
    try { data = bytes(JSON.stringify(message) + "\n"); }
    catch (_) { this.close(); return; }
    if (this.outputBytes + data.length > MAX_OUTPUT) {
      this.close();
      return;
    }
    this.outputBytes += data.length;
    this.outputQueue.push(data);
    this.output.asyncWait(this, 0, 0, Services.tm.currentThread);
  }

  onOutputStreamReady(stream) {
    if (this.closed) return;
    try {
      let budget = 1024 * 1024;
      while (this.outputQueue.length && budget > 0) {
        const data = this.outputQueue[0].slice(this.outputOffset, this.outputOffset + Math.min(budget, 65536));
        const written = stream.write(data, data.length);
        if (!written) break;
        this.outputOffset += written;
        this.outputBytes -= written;
        budget -= written;
        if (this.outputOffset === this.outputQueue[0].length) {
          this.outputQueue.shift();
          this.outputOffset = 0;
        }
      }
    } catch (error) {
      if (error.result !== Cr.NS_BASE_STREAM_WOULD_BLOCK) { this.close(); return; }
    }
    if (this.outputQueue.length) stream.asyncWait(this, 0, 0, Services.tm.currentThread);
    else if (this.closing) this.close();
  }

  closeAfterFlush() {
    this.closing = true;
    clearTimeout(this.authTimer);
    this.authTimer = setTimeout(() => this.close(), 1000);
    if (!this.outputQueue.length) this.close();
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.authTimer);
    for (const abort of this.pending.values()) abort.abort();
    this.pending.clear();
    this.subscriptions.clear();
    this.outputQueue.length = 0;
    try { this.pump.cancel(Cr.NS_BINDING_ABORTED); } catch (_) {}
    try { this.output.close(); } catch (_) {}
    try { this.transport.close(Cr.NS_OK); } catch (_) {}
    this.service.connections.delete(this.id);
    this.service.browser.release(this).catch(error => console.error(error));
  }
}

export class ControlService {
  constructor() {
    this.instance = id();
    this.connections = new Map();
    this.stopped = false;
  }

  QueryInterface = ChromeUtils.generateQI(["nsIServerSocketListener"]);

  async start() {
    this.token = ChromeUtils.camouGetString("control:token");
    if (!/^[A-Za-z0-9_-]{32,256}$/.test(this.token))
      fail("invalid configuration", "control:token must contain 32 to 256 base64url characters");
    const port = number(ChromeUtils.camouGetInt("control:port"), "control:port", 0, 65535, true);
    const endpoint = ChromeUtils.camouGetString("control:endpoint");
    if (!endpoint) fail("invalid configuration", "control:endpoint must name a new absolute metadata file");
    const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
    file.initWithPath(endpoint);
    // Exclusive creation: never overwrite a previous instance's discovery file.
    file.create(Ci.nsIFile.NORMAL_FILE_TYPE, 0o600);
    this.endpoint = file;
    try {
      ChromeUtils.registerWindowActor("CamoufoxControl", {
        parent: {esModuleURI: "chrome://juggler/content/control/ControlParent.sys.mjs"},
        child: {
          esModuleURI: "chrome://juggler/content/control/ControlChild.sys.mjs",
          events: {
            DOMWindowCreated: {}, DOMDocElementInserted: {}, DOMContentLoaded: {},
            load: {capture: true}, pageshow: {capture: true}, pagehide: {capture: true},
            DOMWillOpenModalDialog: {}, DOMModalDialogClosed: {},
            dragstart: {capture: true, mozSystemGroup: true},
          },
        },
        allFrames: true,
      });
      this.actorRegistered = true;
      this.browser = new ControlBrowser((method, params, session) => {
        for (const connection of this.connections.values()) {
          if (session && session !== connection.id) continue;
          connection.event(method, params, !!session && (params.blocked || method === "network.interceptExpired"));
        }
      });
      if (![...Services.wm.getEnumerator("navigator:browser")]
        .some(win => win.gBrowserInit?.delayedStartupFinished)) {
        let observer;
        try {
          await bounded(new Promise(resolve => {
            observer = {observe: resolve};
            Services.obs.addObserver(observer, "browser-delayed-startup-finished");
          }), 30000);
        } finally {
          Services.obs.removeObserver(observer, "browser-delayed-startup-finished");
        }
      }
      if (this.stopped) return;
      this.server = Cc["@mozilla.org/network/server-socket;1"].createInstance(Ci.nsIServerSocket);
      this.server.init(port || -1, true, 8);
      this.server.asyncListen(this);
      await IOUtils.writeJSON(file.path, {
        protocolVersion: VERSION, transport: "loopback-tcp-ndjson",
        host: "127.0.0.1", port: this.server.port,
        processId: Services.appinfo.processID, instance: this.instance,
      });
    } catch (error) {
      this.stop();
      throw error;
    }
  }

  onSocketAccepted(server, transport) {
    if (this.stopped || this.connections.size >= MAX_CONNECTIONS) {
      transport.close(Cr.NS_ERROR_NOT_AVAILABLE);
      return;
    }
    try {
      const connection = new Connection(this, transport);
      this.connections.set(connection.id, connection);
    } catch (error) {
      transport.close(Cr.NS_ERROR_FAILURE);
      console.error("Camoufox control: could not accept local connection");
    }
  }
  onStopListening() {}

  stop(shuttingDown = false) {
    if (this.stopped) return;
    this.stopped = true;
    try { this.server?.close(); } catch (_) {}
    for (const connection of this.connections.values()) connection.close();
    this.browser?.dispose();
    if (this.actorRegistered && !shuttingDown) ChromeUtils.unregisterWindowActor("CamoufoxControl");
    // The file was created exclusively by this instance. Remove only if its
    // contents still identify this instance; a replacement belongs to its owner.
    if (this.endpoint) {
      const file = this.endpoint.clone();
      try {
        const input = Cc["@mozilla.org/network/file-input-stream;1"].createInstance(Ci.nsIFileInputStream);
        input.init(file, 0x01, 0, 0);
        const reader = Cc["@mozilla.org/scriptableinputstream;1"].createInstance(Ci.nsIScriptableInputStream);
        reader.init(input);
        const text = reader.read(Math.min(reader.available(), 4096));
        reader.close();
        if (!text || JSON.parse(text).instance === this.instance) file.remove(false);
      } catch (_) {}
    }
    this.token = "";
  }
}
