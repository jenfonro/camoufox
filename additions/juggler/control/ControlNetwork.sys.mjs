/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// This module reuses the native HTTP channel plumbing, not a Juggler session,
// TargetRegistry, page agent, or JavaScript debugger.
const {NetworkObserver, PageNetwork} =
  ChromeUtils.importESModule("chrome://juggler/content/NetworkObserver.js");
const {fail, string, number, choice, id, setTimeout, clearTimeout} =
  ChromeUtils.importESModule("chrome://juggler/content/control/ControlUtils.sys.mjs");

function channelContext(channel) {
  const info = channel.loadInfo;
  return info?.frameBrowsingContext || info?.workerAssociatedBrowsingContext || info?.browsingContext;
}

export class ControlNetwork {
  constructor(controller, emit) {
    this.controller = controller;
    this.emit = emit;
    this.enabled = new Map();
    this.intercepts = new Map();
    this.pending = new Map();
    this.requests = new Map();
    this.targets = new Map();
    this.observer = null;
  }

  contexts(values) {
    if (values === undefined) return null;
    if (!Array.isArray(values) || !values.length) fail("invalid argument", "contexts must be a nonempty array");
    return new Set(values.map(value => String(this.controller.context(string(value, "context")).id)));
  }

  matches(contexts, bc) {
    if (!bc) return false;
    if (!contexts) return true;
    for (let current = bc; current; current = current.parent)
      if (contexts.has(String(current.id))) return true;
    return false;
  }

  intercept(channel) {
    const bc = channelContext(channel);
    return [...this.intercepts.values()].find(rule =>
      this.matches(rule.contexts, bc) && rule.patterns.some(pattern => pattern.test(channel.URI.spec)));
  }

  start() {
    if (this.observer) return;
    this.observer = new NetworkObserver({
      preserveNativeAuth: true,
      getProxyInfo: () => null,
      shouldBustHTTPAuthCacheForProxy: () => false,
      shouldObserve: channel => [...this.enabled.values()].some(contexts => this.matches(contexts, channelContext(channel))) ||
        !!this.intercept(channel),
      shouldIntercept: channel => !!this.intercept(channel),
      targetForBrowserId: browserId => this.target(browserId),
    });
  }

  target(browserId) {
    const root = this.controller.roots().find(bc => bc.browserId === browserId);
    const inScope = (bc, contexts) => this.matches(contexts, bc) ||
      bc.children.some(child => inScope(child, contexts));
    if (!root || ![...this.enabled.values(), ...[...this.intercepts.values()].map(r => r.contexts)]
      .some(contexts => inScope(root, contexts))) return null;
    if (this.targets.has(browserId)) return this.targets.get(browserId);
    const target = {context: String(root.id),
      browserContext: () => ({extraHTTPHeaders: [], requestInterceptionEnabled: false})};
    const page = PageNetwork.forPageTarget(target);
    const events = new Map([
      [PageNetwork.Events.Request, "network.beforeRequestSent"],
      [PageNetwork.Events.Response, "network.responseStarted"],
      [PageNetwork.Events.RequestFinished, "network.responseCompleted"],
      [PageNetwork.Events.RequestFailed, "network.requestFailed"],
    ]);
    for (const [event, method] of events) {
      page.on(event, (_, data, frameId) => this.event(method, data, frameId, root, page));
    }
    target.page = page;
    this.targets.set(browserId, target);
    return target;
  }

  event(method, data, frameId, root, page) {
    let context = String(frameId || "").replace(/^frame-/, "");
    let bc;
    try { bc = this.controller.context(context); }
    catch (_) { context = String(root.id); bc = root; }
    const requestId = data.requestId;
    const previous = this.requests.get(requestId);
    const record = previous || {context, page, url: data.url, method: data.method};
    this.requests.set(requestId, record);
    if (this.requests.size > 5000) {
      for (const key of this.requests.keys()) {
        if (!this.pending.has(key)) { this.requests.delete(key); break; }
      }
    }
    let owner;
    if (["network.responseCompleted", "network.requestFailed"].includes(method)) {
      const pending = this.pending.get(requestId);
      if (pending) clearTimeout(pending.timer);
      this.pending.delete(requestId);
    }
    if (data.isIntercepted) {
      // PageNetwork inserts the native intercepted channel after synchronous
      // Request listeners return. Client commands arrive on a later event turn.
      const rule = [...this.intercepts.values()].find(r =>
        this.matches(r.contexts, bc) && r.patterns.some(pattern => pattern.test(data.url)));
      if (rule) {
        owner = rule.session;
        const timer = setTimeout(() => {
          if (!this.pending.has(requestId)) return;
          try { page.resumeInterceptedRequest(requestId); } catch (_) {}
          this.pending.delete(requestId);
          this.emit("network.interceptExpired", {request: requestId, context}, owner);
        }, rule.timeout);
        this.pending.set(requestId, {page, session: owner, intercept: rule.id, timer});
      } else {
        setTimeout(() => { try { page.resumeInterceptedRequest(requestId); } catch (_) {} }, 0);
      }
    }
    const params = {...data, context, request: requestId, url: data.url || record.url,
      blocked: !!owner, intercept: this.pending.get(requestId)?.intercept};
    delete params.frameId;
    delete params.requestId;
    for (const [session, contexts] of this.enabled)
      if (session === owner || this.matches(contexts, bc))
        this.emit(method, params, session);
  }

  headers(value) {
    if (value === undefined) return undefined;
    if (!Array.isArray(value) || value.length > 1000) fail("invalid argument", "headers must be an array");
    return value.map(header => {
      const name = string(header.name, "header.name"), value = string(header.value, "header.value", {empty: true});
      if (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name) || /[\r\n]/.test(value))
        fail("invalid argument", "Invalid header characters");
      return {name, value};
    });
  }

  command(method, p, session) {
    if (method === "network.enable") {
      this.enabled.set(session.id, this.contexts(p.contexts));
      this.start();
      return {};
    }
    if (method === "network.disable") { this.releaseSession(session.id); return {}; }
    if (method === "network.addIntercept") {
      if ([...this.intercepts.values()].filter(rule => rule.session === session.id).length >= 128)
        fail("resource limit", "Too many intercept rules on this connection");
      const contexts = this.contexts(p.contexts);
      const phases = p.phases ?? ["beforeRequestSent"];
      if (!Array.isArray(phases) || phases.length !== 1 || phases[0] !== "beforeRequestSent")
        fail("unsupported operation", "Interception currently supports beforeRequestSent");
      const patterns = p.urlPatterns ?? ["*"];
      if (!Array.isArray(patterns) || !patterns.length || patterns.length > 100)
        fail("invalid argument", "urlPatterns must contain 1 to 100 wildcard patterns");
      const compiled = patterns.map(value => {
        string(value, "urlPattern");
        if (value.length > 2048) fail("invalid argument", "URL pattern is too long");
        return new RegExp("^" + value.split("*").map(s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*") + "$");
      });
      const rule = {id: id(), session: session.id, contexts, patterns: compiled,
        timeout: number(p.timeout ?? 30000, "timeout", 100, 120000, true)};
      this.intercepts.set(rule.id, rule);
      if (!this.enabled.has(session.id)) this.enabled.set(session.id, contexts);
      this.start();
      return {intercept: rule.id};
    }
    if (method === "network.removeIntercept") {
      const rule = this.intercepts.get(p.intercept);
      if (!rule || rule.session !== session.id) fail("no such intercept", "Intercept is not owned by this connection");
      this.intercepts.delete(rule.id);
      this.resumeWhere(item => item.intercept === rule.id);
      return {};
    }
    if (method === "network.getResponseBody") {
      const record = this.requests.get(p.request);
      if (!record || !this.enabled.has(session.id)) fail("no such request", "Response is not available");
      const bc = this.controller.context(record.context);
      if (!this.matches(this.enabled.get(session.id), bc)) fail("no such request", "Request is outside this connection's scope");
      const body = record.page.getResponseBody(p.request);
      if (body.evicted) fail("resource limit", "Response body was evicted from the bounded cache");
      return {data: body.base64body, base64Encoded: true};
    }
    const pending = this.pending.get(p.request);
    if (!pending || pending.session !== session.id)
      fail("no such request", "Blocked request is not owned by this connection");
    const headers = this.headers(p.headers);
    if (method === "network.continueRequest") {
      if (p.url !== undefined) Services.io.newURI(string(p.url, "url"));
      if (p.method !== undefined && !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(string(p.method, "method")))
        fail("invalid argument", "Invalid HTTP method");
      if (p.body !== undefined) { string(p.body, "body", {empty: true}); atob(p.body); }
      pending.page.resumeInterceptedRequest(p.request, p.url, p.method, headers, p.body);
    } else if (method === "network.failRequest") {
      pending.page.abortInterceptedRequest(p.request, "NS_ERROR_ABORT");
    } else if (method === "network.provideResponse") {
      const status = number(p.status ?? 200, "status", 100, 599, true);
      const statusText = p.statusText ?? "";
      string(statusText, "statusText", {empty: true});
      if (/[\r\n]/.test(statusText)) fail("invalid argument", "Invalid HTTP status text");
      const body = p.body ?? "";
      string(body, "body", {empty: true});
      atob(body);
      pending.page.fulfillInterceptedRequest(p.request, status, statusText, headers || [], body);
    } else {
      fail("unknown method", `Unknown network method: ${method}`);
    }
    clearTimeout(pending.timer);
    this.pending.delete(p.request);
    return {};
  }

  resumeWhere(predicate) {
    for (const [request, item] of this.pending) {
      if (!predicate(item)) continue;
      clearTimeout(item.timer);
      try { item.page.resumeInterceptedRequest(request); } catch (_) {}
      this.pending.delete(request);
    }
  }

  releaseSession(session) {
    this.resumeWhere(item => item.session === session);
    this.enabled.delete(session);
    for (const [id, rule] of this.intercepts)
      if (rule.session === session) this.intercepts.delete(id);
    if (!this.enabled.size) this.dispose();
  }

  forgetContext(context) {
    for (const [browserId, target] of this.targets) {
      if (target.context !== context) continue;
      this.resumeWhere(item => item.page === target.page);
      for (const [request, record] of this.requests)
        if (record.page === target.page) this.requests.delete(request);
      this.targets.delete(browserId);
    }
  }

  dispose() {
    this.resumeWhere(() => true);
    this.observer?.dispose();
    this.observer = null;
    this.targets.clear();
    this.requests.clear();
  }
}
