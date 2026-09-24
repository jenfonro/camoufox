/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

const {fail, object, string, number, choice, errorObject, id, setTimeout, clearTimeout} =
  ChromeUtils.importESModule("chrome://juggler/content/control/ControlUtils.sys.mjs");
const {MouseDispatch} = ChromeUtils.importESModule("chrome://juggler/content/input/MouseDispatch.js");

export class CamoufoxControlChild extends JSWindowActorChild {
  actorCreated() {
    this._sessions = new Map();
    this._pending = new Map();
  }

  didDestroy() {
    for (const session of this._sessions.keys()) this.release(session);
    for (const cancel of this._pending.values()) cancel();
    this._pending.clear();
  }

  handleEvent(event) {
    if (event.type === "dragstart") return;
    if (["DOMWindowCreated", "DOMDocElementInserted"].includes(event.type)) return;
    if (["DOMWillOpenModalDialog", "DOMModalDialogClosed"].includes(event.type)) {
      this.sendAsyncMessage("Control:event", {type: `page.${event.type}`, url: this.document.documentURI});
      return;
    }
    if (event.target !== this.document)
      return;
    this.sendAsyncMessage("Control:event", {
      type: `page.${event.type}`, url: this.document.documentURI,
      persisted: !!event.persisted,
    });
  }

  async receiveMessage({name, data}) {
    if (name === "Control:release") { this.release(data.session); return undefined; }
    if (name === "Control:cancel") { this._pending.get(data.request)?.(); return undefined; }
    if (name !== "Control:request")
      return undefined;
    let timer;
    try {
      const cancelled = new Promise((_, reject) => {
        const cancel = () => reject(Object.assign(new Error("Page operation cancelled"), {code: "cancelled"}));
        this._pending.set(data.request, cancel);
        timer = setTimeout(() => reject(Object.assign(new Error("Page operation timed out"),
          {code: "timeout"})), data.timeout || 30000);
      });
      return {result: await Promise.race([
        this.command(string(data.method, "method"), object(data.params), this.state(data.session || "")),
        cancelled,
      ])};
    } catch (error) {
      return {error: errorObject(error)};
    } finally {
      clearTimeout(timer);
      this._pending.delete(data.request);
    }
  }

  state(session) {
    if (!this._sessions.has(session))
      this._sessions.set(session, {nodes: new Map(), nodeIds: new WeakMap(), sandbox: null});
    return this._sessions.get(session);
  }

  release(session) {
    const state = this._sessions.get(session);
    if (!state) return;
    if (state.sandbox) Cu.nukeSandbox(state.sandbox);
    state.nodes.clear();
    this._sessions.delete(session);
  }

  node(params, state) {
    const key = string(params.node, "node");
    const node = state.nodes.get(key)?.deref();
    if (!node || !node.isConnected || node.ownerDocument !== this.document)
      fail("stale element", "The node no longer belongs to the current document");
    return node;
  }

  remember(node, state) {
    let key = state.nodeIds.get(node);
    if (!key || !state.nodes.has(key)) {
      if (state.nodes.size >= 4096) {
        for (const [old, ref] of state.nodes) {
          if (!ref.deref()?.isConnected)
            state.nodes.delete(old);
        }
        if (state.nodes.size >= 4096)
          fail("resource limit", "Release node references before querying more elements");
      }
      key = id();
      state.nodeIds.set(node, key);
      state.nodes.set(key, new WeakRef(node));
    }
    return key;
  }

  describe(node, state) {
    const rect = node.getBoundingClientRect();
    const style = this.contentWindow.getComputedStyle(node);
    const x = rect.x + rect.width / 2;
    const y = rect.y + rect.height / 2;
    let hit = this.document.elementFromPoint(x, y);
    while (hit?.shadowRoot) {
      const next = hit.shadowRoot.elementFromPoint(x, y);
      if (!next || next === hit) break;
      hit = next;
    }
    let covered = hit;
    while (covered && covered !== node) {
      covered = covered.parentNode || covered.getRootNode()?.host;
    }
    return {
      node: this.remember(node, state), tagName: node.localName,
      text: (node.innerText ?? node.textContent ?? "").slice(0, 65536),
      attributes: Object.fromEntries(Array.from(node.attributes || [], a => [a.name, a.value])),
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
      visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none",
      enabled: !node.matches(":disabled") && node.getAttribute("aria-disabled") !== "true",
      hit: covered === node, point: {x, y},
    };
  }

  query(params, state) {
    const limit = number(params.limit ?? 100, "limit", 1, 1000, true);
    if (params.selector !== undefined) string(params.selector, "selector");
    if (params.text !== undefined) string(params.text, "text", {empty: true});
    if (params.selector === undefined && params.text === undefined)
      fail("invalid argument", "selector or text is required");
    const root = params.root ? this.node({node: params.root}, state) : this.document;
    const roots = [root];
    const result = [];
    let scanned = 0;
    while (roots.length && result.length < limit) {
      const current = roots.shift();
      let elements;
      try {
        elements = current.querySelectorAll(params.selector || "*");
      } catch (_) {
        fail("invalid selector", "CSS selector could not be parsed");
      }
      for (const element of elements) {
        if (++scanned > 50000)
          fail("resource limit", "Query scans more than 50000 elements; narrow the selector");
        if (params.text !== undefined) {
          const text = (element.innerText ?? element.textContent ?? "").trim();
          if (params.exact ? text !== params.text : !text.includes(params.text))
            continue;
        }
        const description = this.describe(element, state);
        if (params.visible && !description.visible) continue;
        result.push(description);
        if (result.length >= limit) break;
      }
      if (params.pierce && result.length < limit) {
        if (current.shadowRoot) roots.push(current.shadowRoot);
        for (const element of current.querySelectorAll("*")) {
          if (++scanned > 50000)
            fail("resource limit", "Shadow query scans more than 50000 elements; narrow its root");
          if (element.shadowRoot) roots.push(element.shadowRoot);
        }
      }
    }
    return {nodes: result};
  }

  async evaluate(params, state) {
    const expression = string(params.expression, "expression", {empty: true});
    const world = choice(params.world ?? "isolated", "world", ["main", "isolated"]);
    let value;
    if (world === "main") {
      value = ChromeUtils.camouEvaluateInPage(this.contentWindow, expression);
    } else {
      if (!state.sandbox) {
        state.sandbox = Cu.Sandbox(this.contentWindow, {
          sandboxPrototype: this.contentWindow, wantXrays: true,
          sameZoneAs: this.contentWindow, sandboxName: "Camoufox control isolated world",
        });
      }
      value = Cu.evalInSandbox(expression, state.sandbox, "latest");
    }
    if (params.awaitPromise !== false)
      value = await value;
    if (value === undefined) return {type: "undefined"};
    if (typeof value === "number" && !Number.isFinite(value))
      return {type: "number", unserializableValue: String(value)};
    if (typeof value === "bigint") return {type: "bigint", value: String(value)};
    let serialized;
    try {
      serialized = JSON.parse(JSON.stringify(Cu.waiveXrays(value)));
    } catch (_) {
      fail("serialization error", "Result must be serializable by value");
    }
    return {type: value === null ? "null" : typeof value, value: serialized};
  }

  async command(method, params, state) {
    const win = this.contentWindow;
    const doc = this.document;
    if (!["page.info", "control.diagnostics"].includes(method) && doc.nodePrincipal.isSystemPrincipal)
      fail("unsupported operation", "Page commands do not execute in browser-privileged documents");
    switch (method) {
      case "control.diagnostics": {
        let oldActor = false;
        try { oldActor = !!this.manager.getExistingActor("JugglerFrame"); } catch (_) {}
        return {processId: Services.appinfo.processID,
          modules: Cu.loadedESModules.filter(uri => uri.startsWith("chrome://juggler/")),
          jugglerActor: oldActor, overrideHasFocus: this.docShell.overrideHasFocus,
          forceActiveState: this.docShell.forceActiveState, disallowBFCache: this.docShell.disallowBFCache};
      }
      case "page.info": {
        const [width, height] = ChromeUtils.camouGetNativeViewportSize(win);
        const root = doc.scrollingElement || doc.documentElement;
        return {
          url: doc.documentURI, title: doc.title, readyState: doc.readyState,
          viewport: {width, height}, scroll: {x: win.scrollX, y: win.scrollY},
          document: {width: Math.max(width, root?.scrollWidth || 0), height: Math.max(height, root?.scrollHeight || 0)},
          focused: doc.hasFocus(), activeElement: doc.activeElement?.localName || null,
        };
      }
      case "page.frameGeometry": {
        const child = this.browsingContext.children.find(c => String(c.id) === String(params.child));
        const frame = child?.embedderElement;
        if (!frame) fail("no such context", "Frame is no longer attached");
        const quad = frame.getBoxQuads({box: "content"})[0];
        if (!quad) fail("element not interactable", "Frame has no content rectangle");
        return {p1: {x: quad.p1.x, y: quad.p1.y}, p2: {x: quad.p2.x, y: quad.p2.y},
          p4: {x: quad.p4.x, y: quad.p4.y}, width: frame.clientWidth, height: frame.clientHeight};
      }
      case "browsingContext.getFrame": {
        if ((params.selector === undefined) === (params.child === undefined))
          fail("invalid argument", "Provide exactly one of selector or child");
        let child;
        if (params.selector !== undefined) {
          const selector = string(params.selector, "selector");
          let matches;
          try { matches = doc.querySelectorAll(selector); }
          catch (_) { fail("invalid selector", "CSS selector could not be parsed"); }
          if (!matches.length) return {context: null, visible: false};
          if (matches.length !== 1 || !["iframe", "frame"].includes(matches[0].localName))
            fail("invalid argument", "selector must resolve exactly one frame element");
          child = this.browsingContext.children.find(c => c.embedderElement === matches[0]);
        } else {
          const context = string(params.child, "child");
          child = this.browsingContext.children.find(c => String(c.id) === context);
        }
        const frame = child?.embedderElement;
        if (!frame || child.isDiscarded) return {context: null, visible: false};
        const rect = frame.getBoundingClientRect();
        const [width, height] = ChromeUtils.camouGetNativeViewportSize(win);
        return {context: String(child.id),
          visible: frame.checkVisibility({opacityProperty: true, visibilityProperty: true}) &&
            rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
            rect.x < width && rect.y < height};
      }
      case "input.barrier":
        await new Promise(resolve => setTimeout(resolve, 0));
        return {};
      case "input.focus":
        win.focus();
        return {};
      case "dom.query": return this.query(params, state);
      case "dom.get": {
        const node = this.node(params, state);
        return {...this.describe(node, state), value: "value" in node ? node.value : undefined,
          html: params.html ? node.outerHTML : undefined};
      }
      case "dom.release":
        if (!Array.isArray(params.nodes)) fail("invalid argument", "nodes must be an array");
        for (const key of params.nodes) state.nodes.delete(string(key, "node"));
        return {};
      case "dom.focus": this.node(params, state).focus({preventScroll: !!params.preventScroll}); return {};
      case "dom.scrollIntoView":
        this.node(params, state).scrollIntoView({block: "center", inline: "center", behavior: "instant"});
        return {};
      case "dom.setFiles": {
        const element = this.node(params, state);
        if (element.localName !== "input" || element.type !== "file")
          fail("invalid argument", "Node must be an input of type file");
        if (!Array.isArray(params.files) || params.files.length > 100)
          fail("invalid argument", "files must be an array with at most 100 paths");
        if (!element.multiple && params.files.length > 1)
          fail("invalid argument", "Input does not accept multiple files");
        element.mozSetFileArray(params.files);
        for (const event of [new win.Event("input", {bubbles: true, composed: true}),
          new win.Event("change", {bubbles: true})])
          win.windowUtils.dispatchDOMEventViaPresShellForTesting(element, event);
        return {};
      }
      case "script.evaluate": return this.evaluate(params, state);
      case "input.dragStatus":
        return {active: !!Cc["@mozilla.org/widget/dragservice;1"].getService(Ci.nsIDragService).getCurrentSession(win)};
      case "input.drag": {
        const session = Cc["@mozilla.org/widget/dragservice;1"].getService(Ci.nsIDragService).getCurrentSession(win);
        if (!session) return {active: false};
        const type = choice(params.type, "type", ["dragover", "drop", "dragend"]);
        if (type === "dragend") session.endDragSession(true);
        else if (type === "dragover" || session.dataTransfer.dropEffect !== "none")
          MouseDispatch.sendContentDrag(win, type, params.x, params.y, params.modifiers || 0);
        return {active: type !== "dragend"};
      }
      case "storage.get":
      case "storage.set":
      case "storage.remove":
      case "storage.clear": {
        if (params.origin !== undefined && params.origin !== win.location.origin)
          fail("invalid argument", "Storage origin does not match the selected document");
        const area = choice(params.area ?? "local", "area", ["local", "session"]);
        const storage = area === "local" ? win.localStorage : win.sessionStorage;
        if (method === "storage.get") {
          const entries = Object.create(null);
          for (let i = 0; i < storage.length; i++) {
            const key = storage.key(i);
            entries[key] = storage.getItem(key);
          }
          return {origin: win.location.origin, entries};
        }
        if (method === "storage.set") {
          for (const [key, value] of Object.entries(object(params.entries, "entries")))
            string(value, `entries.${key}`, {empty: true});
          for (const [key, value] of Object.entries(params.entries))
            storage.setItem(key, value);
        } else if (method === "storage.remove") {
          storage.removeItem(string(params.key, "key", {empty: true}));
        } else {
          storage.clear();
        }
        return {};
      }
      default: fail("unknown method", `Unknown page method: ${method}`);
    }
  }
}
