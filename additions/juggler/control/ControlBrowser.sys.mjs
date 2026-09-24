/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

const {fail, object, string, number, choice, bounded, delay, checkAbort, id, setTimeout} =
  ChromeUtils.importESModule("chrome://juggler/content/control/ControlUtils.sys.mjs");
const {ControlInput} = ChromeUtils.importESModule("chrome://juggler/content/control/ControlInput.sys.mjs");
const {controlActors} = ChromeUtils.importESModule("chrome://juggler/content/control/ControlParent.sys.mjs");
const {MouseDispatch} = ChromeUtils.importESModule("chrome://juggler/content/input/MouseDispatch.js");

export const METHODS = [
  "browser.getInfo", "browser.close",
  "browsingContext.getTree", "browsingContext.getFrame", "browsingContext.create", "browsingContext.close",
  "browsingContext.activate", "browsingContext.navigate", "browsingContext.reload",
  "browsingContext.traverseHistory", "browsingContext.captureScreenshot",
  "page.info", "page.getDialogs", "page.handleDialog",
  "dom.query", "dom.get", "dom.release", "dom.focus", "dom.scrollIntoView", "dom.setFiles",
  "script.evaluate", "input.dispatchPointer", "input.dispatchKey", "input.insertText",
  "input.dispatchWheel", "input.click", "input.performActions", "input.releaseActions",
  "storage.get", "storage.set", "storage.remove", "storage.clear",
  "storage.getCookies", "storage.setCookie", "storage.deleteCookies",
  "permissions.set", "permissions.get", "permissions.reset",
  "downloads.get", "downloads.cancel",
  "network.enable", "network.disable", "network.addIntercept", "network.removeIntercept",
  "network.continueRequest", "network.failRequest", "network.provideResponse", "network.getResponseBody",
];

export class ControlBrowser {
  constructor(emit) {
    this.emit = emit;
    this.input = new ControlInput(this);
    this.network = null;
    this.windows = new Map();
    this.contexts = new Map();
    this.dialogIds = new WeakMap();
    this.downloadIds = new WeakMap();
    this.navigationSequence = new Map();
    this.eventObserver = {observe: (subject, topic, data) => {
      const event = JSON.parse(data);
      this.emit(event.type, event);
    }};
    Services.obs.addObserver(this.eventObserver, "camoufox-control-event");
    this.windowObserver = {observe: win => this.watchWindow(win)};
    Services.obs.addObserver(this.windowObserver, "browser-delayed-startup-finished");
    this.contextObserver = {observe: (bc, topic) => {
      if (topic === "browsing-context-discarded") this.forgetContext(String(bc.id));
      else this.trackContext(bc);
    }};
    for (const topic of ["browsing-context-attached", "browsing-context-did-set-embedder",
      "browsing-context-discarded"])
      Services.obs.addObserver(this.contextObserver, topic);
    for (const win of Services.wm.getEnumerator("navigator:browser"))
      this.watchWindow(win);
    this.watchDownloads().catch(error => console.error(error));
  }

  watchWindow(win) {
    if (!win.gBrowser || this.windows.has(win)) return;
    const events = {TabOpen: "browsingContext.created", TabClose: "browsingContext.destroyed",
      TabSelect: "browsingContext.activated"};
    const listener = event => {
      const bc = event.target.linkedBrowser?.browsingContext;
      if (!bc) return;
      if (event.type === "TabOpen") this.trackContext(bc);
      else if (event.type === "TabClose") this.forgetContext(String(bc.id));
      else this.emit(events[event.type], {context: String(bc.id)});
    };
    for (const type of Object.keys(events)) win.gBrowser.tabContainer.addEventListener(type, listener);
    const progress = {
      onStateChange: (browser, webProgress, request, flags, status) => {
        if (!(flags & Ci.nsIWebProgressListener.STATE_IS_DOCUMENT)) return;
        const context = String(webProgress.browsingContext?.id || browser.browsingContext.id);
        if (flags & Ci.nsIWebProgressListener.STATE_START) {
          let url = "";
          try { url = request?.name || ""; } catch (_) {}
          this.emit("browsingContext.navigationStarted", {context, url});
        }
        if ((flags & Ci.nsIWebProgressListener.STATE_STOP) && !Components.isSuccessCode(status))
          this.emit("browsingContext.navigationFailed", {context, status});
      },
      onLocationChange: (browser, webProgress, request, location, flags) => {
        const context = String(webProgress.browsingContext?.id || browser.browsingContext.id);
        this.navigationSequence.set(context, (this.navigationSequence.get(context) || 0) + 1);
        this.emit("browsingContext.navigationCommitted", {context, url: location.spec,
          sameDocument: !!(flags & Ci.nsIWebProgressListener.LOCATION_CHANGE_SAME_DOCUMENT)});
      },
    };
    win.gBrowser.addTabsProgressListener(progress);
    const close = () => {
      for (const type of Object.keys(events))
        win.gBrowser?.tabContainer.removeEventListener(type, listener);
      this.windows.delete(win);
      win.gBrowser?.removeTabsProgressListener(progress);
      win.removeEventListener("unload", close);
    };
    win.addEventListener("unload", close, {once: true});
    this.windows.set(win, close);
    for (const browser of win.gBrowser.browsers)
      if (browser.browsingContext) this.trackContext(browser.browsingContext);
  }

  trackContext(bc) {
    if (!bc.isContent) return;
    const browser = bc.top.embedderElement;
    const win = browser?.ownerDocument?.defaultView;
    if (!win?.gBrowser?.getTabForBrowser(browser)) return;
    const context = String(bc.id);
    const originalOpener = bc.crossGroupOpener;
    if (!this.contexts.has(context)) {
      const ancestors = [];
      for (let parent = bc.parent; parent; parent = parent.parent)
        ancestors.push(String(parent.id));
      const description = {context, parent: ancestors[0] || null, ancestors,
        url: bc.currentURI?.spec || "about:blank",
        userContextId: bc.originAttributes?.userContextId || 0,
        originalOpener: originalOpener ? String(originalOpener.id) : null};
      this.contexts.set(context, description);
      this.emit("browsingContext.created", description);
    }
    // Firefox can attach the browser before assigning its cross-group opener.
    // Preserve the native creation relation even after the source tab closes.
    if (originalOpener)
      this.contexts.get(context).originalOpener = String(originalOpener.id);
    for (const child of bc.children) this.trackContext(child);
  }

  forgetContext(context) {
    const descendants = [...this.contexts.values()]
      .filter(item => item.context === context || item.ancestors.includes(context))
      .sort((a, b) => b.ancestors.length - a.ancestors.length);
    for (const item of descendants) {
      this.contexts.delete(item.context);
      this.navigationSequence.delete(item.context);
      this.input.forgetContext(item.context);
      this.emit("browsingContext.destroyed", item);
    }
    this.network?.forgetContext(context);
  }

  roots() {
    const result = [];
    for (const win of Services.wm.getEnumerator("navigator:browser")) {
      for (const browser of win.gBrowser?.browsers || []) {
        if (browser.browsingContext) result.push(browser.browsingContext);
      }
    }
    return result;
  }

  context(value) {
    const key = string(value, "context");
    const walk = bc => String(bc.id) === key ? bc : bc.children.map(walk).find(Boolean);
    for (const root of this.roots()) {
      const result = walk(root);
      if (result) return result;
    }
    fail("no such context", "Browsing context no longer exists");
  }

  browser(context) {
    const browser = this.context(context).top.embedderElement;
    if (!browser) fail("no such context", "Context is not attached to a browser");
    return browser;
  }

  async query(context, method, params, {signal, timeout = 30000, sessionId = ""} = {}) {
    checkAbort(signal);
    const bc = this.context(context);
    if (!bc.currentWindowGlobal)
      fail("no such document", "Context has no current document");
    const actor = bc.currentWindowGlobal.getActor("CamoufoxControl");
    const request = id();
    const cancel = () => {
      try { actor.sendAsyncMessage("Control:cancel", {request}); } catch (_) {}
    };
    signal?.addEventListener("abort", cancel, {once: true});
    try {
      const result = await bounded(actor.sendQuery("Control:request", {method, params,
        session: sessionId, request, timeout}), timeout, signal);
      if (result?.error) fail(result.error.code, result.error.message);
      return result?.result;
    } finally {
      signal?.removeEventListener("abort", cancel);
      cancel();
    }
  }

  async activate(context, options = {}) {
    const browser = this.browser(context);
    const win = browser.ownerDocument.defaultView;
    const tab = win.gBrowser.getTabForBrowser(browser);
    win.focus();
    if (win.gBrowser.selectedTab !== tab) {
      let listener;
      const switched = new Promise(resolve => {
        listener = () => resolve();
        win.addEventListener("TabSwitchDone", listener);
      });
      try {
        win.gBrowser.selectedTab = tab;
        await bounded(switched, 10000, options.signal);
      } finally { win.removeEventListener("TabSwitchDone", listener); }
    }
    browser.focus();
  }

  tree(bc, depth = 20) {
    return {
      context: String(bc.id), parent: bc.parent ? String(bc.parent.id) : null,
      url: bc.currentURI?.spec || bc.currentWindowGlobal?.documentURI?.spec || "about:blank",
      userContextId: bc.originAttributes?.userContextId || 0,
      originalOpener: this.contexts.get(String(bc.id))?.originalOpener || null,
      children: depth > 0 ? bc.children.map(c => this.tree(c, depth - 1)) : [],
    };
  }

  async waitReady(context, wait, signal, previous) {
    if (wait === "none") return;
    const accepted = wait === "interactive" ? ["interactive", "complete"] : ["complete"];
    for (;;) {
      checkAbort(signal);
      const bc = this.context(context);
      try {
        const info = await this.query(context, "page.info", {}, {signal, timeout: 3000});
        const committed = !previous || (
          (this.navigationSequence.get(context) || 0) !== previous.sequence &&
          !(info.url === "about:blank" && previous.target !== "about:blank"));
        if (committed && info.url === bc.currentURI?.spec && accepted.includes(info.readyState) &&
            (wait === "interactive" || !bc.top.embedderElement?.webProgress?.isLoadingDocument))
          return;
      } catch (error) {
        if (signal?.aborted) throw error;
        if (error.code === "no such context") throw error;
        // Documents and actors are replaced during ordinary navigation.
      }
      await delay(50, signal);
    }
  }

  async navigate(method, p, options) {
    const context = string(p.context, "context");
    const bc = this.context(context);
    const wait = choice(p.wait ?? "complete", "wait", ["none", "interactive", "complete"]);
    const previous = {target: p.url || bc.currentURI?.spec,
      sequence: this.navigationSequence.get(context) || 0};
    if (method === "browsingContext.navigate") {
      let uri;
      try { uri = Services.io.newURI(string(p.url, "url")); }
      catch (_) { fail("invalid argument", "url is invalid"); }
      bc.loadURI(uri, {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});
    } else if (method === "browsingContext.reload") {
      bc.reload(p.ignoreCache ? Ci.nsIWebNavigation.LOAD_FLAGS_BYPASS_CACHE : Ci.nsIWebNavigation.LOAD_FLAGS_NONE);
    } else {
      const delta = number(p.delta, "delta", -1000000, 1000000, true);
      if (!delta) return {url: bc.currentURI?.spec, traversed: false};
      const history = bc.sessionHistory;
      const index = history?.index + delta;
      if (!history || index < 0 || index >= history.count)
        fail("no such history entry", "History has no entry at that offset");
      bc.goToIndex(index);
    }
    await this.waitReady(context, wait, options.signal, previous);
    return {context, url: this.context(context).currentURI?.spec || null};
  }

  attrs(p) {
    if (p.context) {
      const bc = this.context(p.context);
      return {...(bc.currentWindowGlobal?.documentPrincipal.originAttributes || bc.originAttributes || {})};
    }
    const attrs = p.originAttributes ? object(p.originAttributes, "originAttributes") : {};
    return {...Services.scriptSecurityManager.createContentPrincipal(
      Services.io.newURI("https://camoufox.invalid"), attrs).originAttributes};
  }

  cookies(method, p) {
    const attrs = this.attrs(p);
    const sameSite = {None: Ci.nsICookie.SAMESITE_NONE, Lax: Ci.nsICookie.SAMESITE_LAX, Strict: Ci.nsICookie.SAMESITE_STRICT};
    if (method === "storage.setCookie") {
      const c = object(p.cookie, "cookie");
      const uri = c.url ? Services.io.newURI(string(c.url, "cookie.url")) : null;
      const host = c.domain ?? uri?.host;
      string(host, "cookie.domain");
      string(c.name, "cookie.name", {empty: true});
      string(c.value, "cookie.value", {empty: true});
      const path = c.path ?? "/";
      if (!string(path, "cookie.path").startsWith("/"))
        fail("invalid argument", "Cookie path must start with /");
      const expiry = c.expires === undefined ? Date.now() + 31536000000 :
        number(c.expires, "cookie.expires", 0) * 1000;
      Services.cookies.add(host, path, c.name, c.value,
        c.secure ?? uri?.scheme === "https", !!c.httpOnly, c.expires === undefined,
        expiry, attrs, sameSite[choice(c.sameSite ?? "None", "sameSite", Object.keys(sameSite))],
        Ci.nsICookie.SCHEME_UNSET);
      return {};
    }
    const result = [];
    for (const cookie of Services.cookies.cookies) {
      if (Object.entries(attrs).some(([key, value]) => cookie.originAttributes[key] !== value)) continue;
      if (p.name !== undefined && cookie.name !== p.name) continue;
      if (p.domain !== undefined && cookie.host !== p.domain) continue;
      if (p.path !== undefined && cookie.path !== p.path) continue;
      if (method === "storage.deleteCookies") {
        Services.cookies.remove(cookie.host, cookie.name, cookie.path, cookie.originAttributes);
      } else {
        result.push({name: cookie.name, value: cookie.value, domain: cookie.host, path: cookie.path,
          secure: cookie.isSecure, httpOnly: cookie.isHttpOnly, session: cookie.isSession,
          expires: cookie.isSession ? null : cookie.expiry / 1000,
          sameSite: Object.keys(sameSite).find(k => sameSite[k] === cookie.sameSite) || "None",
          originAttributes: {...cookie.originAttributes}});
      }
    }
    return method === "storage.getCookies" ? {cookies: result} : {};
  }

  dialogs(context) {
    const dialogs = this.browser(context).tabDialogBox?.getContentDialogManager().dialogs || [];
    return dialogs.map(dialog => dialog.frameContentWindow?.Dialog).filter(Boolean);
  }

  async screenshot(p, options) {
    const bc = this.context(p.context);
    const info = await this.query(p.context, "page.info", {}, options);
    const clip = p.clip || {x: p.fullPage ? 0 : info.scroll.x, y: p.fullPage ? 0 : info.scroll.y,
      ...(p.fullPage ? info.document : info.viewport)};
    for (const key of ["x", "y", "width", "height"])
      number(clip[key], `clip.${key}`, key === "width" || key === "height" ? 0.01 : 0);
    const win = this.browser(p.context).ownerDocument.defaultView;
    const topInfo = bc.parent ? await this.query(String(bc.top.id), "page.info", {}, options) : info;
    const nativeScale = MouseDispatch.forNativeBrowser(win, this.browser(p.context), {}, topInfo.viewport).contentScale;
    const scale = number(p.scale ?? (bc.overrideDPPX || win.devicePixelRatio * nativeScale), "scale", 0.1, 8);
    const width = Math.ceil(clip.width * scale), height = Math.ceil(clip.height * scale);
    if (width > 32767 || height > 32767 || width * height > 100000000)
      fail("resource limit", "Screenshot exceeds the supported pixel dimensions");
    const format = choice(p.format ?? "png", "format", ["png", "jpeg", "webp"]);
    const bitmap = await bounded(bc.currentWindowGlobal.drawSnapshot(
      new DOMRect(clip.x, clip.y, clip.width, clip.height), scale, "rgb(255,255,255)", !!p.fullPage), 15000, options.signal);
    try {
      const canvas = win.document.createElementNS("http://www.w3.org/1999/xhtml", "canvas");
      canvas.width = width; canvas.height = height;
      canvas.getContext("2d").drawImage(bitmap, 0, 0);
      const value = canvas.toDataURL(`image/${format}`, number(p.quality ?? 0.9, "quality", 0, 1));
      return {mimeType: `image/${format}`, data: value.slice(value.indexOf(",") + 1), width, height};
    } finally { bitmap.close(); }
  }

  async setFiles(p, options) {
    if (!Array.isArray(p.files) || p.files.length > 100)
      fail("invalid argument", "files must be an array with at most 100 paths");
    const win = this.browser(p.context).ownerDocument.defaultView;
    const files = [];
    for (const path of p.files) {
      const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
      file.initWithPath(string(path, "file path"));
      if (!file.exists() || !file.isFile()) fail("invalid argument", "File does not exist");
      files.push(await win.File.createFromNsIFile(file));
    }
    // Like the native picker: the parent authorizes the file and sends File
    // objects through IPC. A sandboxed content process must not open OS paths.
    return this.query(p.context, "dom.setFiles", {node: p.node, files}, options);
  }

  async command(method, p, session, options) {
    options = {...options, sessionId: session.id};
    if (!METHODS.includes(method)) fail("unknown method", `Unknown method: ${method}`);
    for (const key of ["fullPage", "ignoreCache", "background", "private", "exact", "pierce", "visible",
      "html", "preventScroll", "awaitPromise", "accept", "persistent", "repeat", "diagnostics"]) {
      if (p[key] !== undefined && typeof p[key] !== "boolean")
        fail("invalid argument", `${key} must be a boolean`);
    }
    if (method.startsWith("input.")) return this.input.command(method, p, session, options);
    if (method.startsWith("network.")) {
      if (!this.network) {
        const {ControlNetwork} = ChromeUtils.importESModule("chrome://juggler/content/control/ControlNetwork.sys.mjs");
        this.network = new ControlNetwork(this, this.emit);
      }
      return this.network.command(method, p, session);
    }
    if (method === "dom.setFiles") return this.setFiles(p, options);
    if (method === "page.info" || method === "browsingContext.getFrame" ||
        method.startsWith("dom.") || method === "script.evaluate" ||
        ["storage.get", "storage.set", "storage.remove", "storage.clear"].includes(method))
      return this.query(string(p.context, "context"), method, p, options);
    if (method.startsWith("storage.")) return this.cookies(method, p);
    if (["browsingContext.navigate", "browsingContext.reload", "browsingContext.traverseHistory"].includes(method))
      return this.navigate(method, p, options);
    switch (method) {
      case "browser.getInfo": {
        const result = {name: "Camoufox", version: Services.appinfo.version, buildId: Services.appinfo.appBuildID,
          processId: Services.appinfo.processID, protocolVersion: 1};
        if (p.diagnostics) {
          result.modules = Cu.loadedESModules.filter(uri => uri.startsWith("chrome://juggler/"));
          result.lifecycleContexts = [...this.contexts.keys()];
          result.documentActors = controlActors.size;
          result.input = {lastEvent: this.input.lastEvent};
          result.contexts = [];
          const inspect = async bc => {
            try {
              result.contexts.push({context: String(bc.id),
                ...await this.query(String(bc.id), "control.diagnostics", {}, options)});
            } catch (error) {
              result.contexts.push({context: String(bc.id), error: String(error)});
            }
            for (const child of bc.children) await inspect(child);
          };
          for (const root of this.roots()) await inspect(root);
        }
        return result;
      }
      case "browser.close":
        setTimeout(() => Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit), 100);
        return {};
      case "browsingContext.getTree": {
        const depth = number(p.maxDepth ?? 20, "maxDepth", 0, 100, true);
        const roots = p.root ? [this.context(p.root)] : this.roots();
        for (const bc of roots) this.trackContext(bc);
        return {contexts: roots.map(bc => this.tree(bc, depth))};
      }
      case "browsingContext.create": {
        const type = choice(p.type ?? "tab", "type", ["tab", "window"]);
        let win = p.referenceContext ? this.browser(p.referenceContext).ownerDocument.defaultView :
          Services.wm.getMostRecentWindow("navigator:browser");
        if (!win) fail("no such window", "No browser window exists");
        if (type === "window") {
          win = win.OpenBrowserWindow({private: !!p.private});
          await bounded(new Promise(resolve => win.addEventListener("load", resolve, {once: true})), 20000, options.signal);
          if (win.delayedStartupPromise) await bounded(win.delayedStartupPromise, 20000, options.signal);
          const bc = win.gBrowser.selectedBrowser.browsingContext;
          return {context: String(bc.id)};
        }
        const tab = win.gBrowser.addTab("about:blank", {
          triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
          userContextId: number(p.userContextId ?? 0, "userContextId", 0, 0xffffffff, true),
        });
        if (!p.background) win.gBrowser.selectedTab = tab;
        return {context: String(tab.linkedBrowser.browsingContext.id)};
      }
      case "browsingContext.close": {
        if (this.context(p.context).parent)
          fail("invalid argument", "Only a top-level browsing context can be closed");
        const browser = this.browser(p.context);
        const win = browser.ownerDocument.defaultView;
        win.gBrowser.removeTab(win.gBrowser.getTabForBrowser(browser));
        return {};
      }
      case "browsingContext.activate": await this.activate(p.context, options); return {};
      case "browsingContext.captureScreenshot": return this.screenshot(p, options);
      case "page.getDialogs":
        return {dialogs: this.dialogs(p.context).map(prompt => {
          if (!this.dialogIds.has(prompt)) this.dialogIds.set(prompt, id());
          return {dialog: this.dialogIds.get(prompt), type: prompt.args.promptType,
            message: prompt.ui.infoBody.textContent, defaultValue: prompt.ui.loginTextbox?.value || ""};
        })};
      case "page.handleDialog": {
        const prompt = this.dialogs(p.context).find(d => this.dialogIds.get(d) === p.dialog);
        if (!prompt) fail("no such dialog", "Dialog is no longer open");
        if (p.accept) {
          if (p.text !== undefined) prompt.ui.loginTextbox.value = string(p.text, "text", {empty: true});
          prompt.ui.button0.click();
        } else {
          (prompt.ui.button1 || prompt.ui.button0).click();
        }
        return {};
      }
      case "permissions.set":
      case "permissions.get":
      case "permissions.reset": {
        const principal = Services.scriptSecurityManager.createContentPrincipal(
          Services.io.newURI(string(p.origin, "origin")), this.attrs(p));
        const requestedName = string(p.name, "name");
        const name = ({geolocation: "geo", notifications: "desktop-notification"})[requestedName] || requestedName;
        const states = {granted: Ci.nsIPermissionManager.ALLOW_ACTION,
          denied: Ci.nsIPermissionManager.DENY_ACTION, prompt: Ci.nsIPermissionManager.PROMPT_ACTION};
        if (method === "permissions.reset") Services.perms.removeFromPrincipal(principal, name);
        if (method === "permissions.set")
          Services.perms.addFromPrincipal(principal, name, states[choice(p.state, "state", Object.keys(states))],
            p.persistent ? Ci.nsIPermissionManager.EXPIRE_NEVER : Ci.nsIPermissionManager.EXPIRE_SESSION, 0);
        const action = Services.perms.testPermissionFromPrincipal(principal, name);
        return {state: Object.keys(states).find(k => states[k] === action) || "default"};
      }
      case "downloads.get":
      case "downloads.cancel": {
        const {Downloads} = ChromeUtils.importESModule("resource://gre/modules/Downloads.sys.mjs");
        const list = await Downloads.getList(Downloads.ALL);
        const downloads = await list.getAll();
        for (const item of downloads)
          if (!this.downloadIds.has(item)) this.downloadIds.set(item, id());
        if (method === "downloads.cancel") {
          const item = downloads.find(d => this.downloadIds.get(d) === p.download);
          if (!item) fail("no such download", "Download does not exist");
          await item.cancel();
          return {};
        }
        return {downloads: downloads.map(d => ({download: this.downloadIds.get(d), url: d.source.url,
          path: d.target.path, currentBytes: d.currentBytes, totalBytes: d.totalBytes,
          succeeded: d.succeeded, stopped: d.stopped, canceled: d.canceled,
          error: d.error ? String(d.error.message) : null}))};
      }
      default: fail("unknown method", `Unknown method: ${method}`);
    }
  }

  async release(session) {
    this.network?.releaseSession(session.id);
    await this.input.releaseSession(session.id);
    for (const actor of controlActors) {
      try { actor.sendAsyncMessage("Control:release", {session: session.id}); } catch (_) {}
    }
  }

  describeDownload(item) {
    if (!this.downloadIds.has(item)) this.downloadIds.set(item, id());
    return {download: this.downloadIds.get(item), url: item.source.url,
      path: item.target.path, currentBytes: item.currentBytes, totalBytes: item.totalBytes,
      succeeded: item.succeeded, stopped: item.stopped, canceled: item.canceled,
      error: item.error ? String(item.error.message) : null};
  }

  async watchDownloads() {
    const {Downloads} = ChromeUtils.importESModule("resource://gre/modules/Downloads.sys.mjs");
    const list = await Downloads.getList(Downloads.ALL);
    if (this.disposed) return;
    this.downloadList = list;
    this.downloadView = {
      onDownloadAdded: item => this.emit("downloads.created", this.describeDownload(item)),
      onDownloadChanged: item => this.emit("downloads.changed", this.describeDownload(item)),
      onDownloadRemoved: item => this.emit("downloads.removed", this.describeDownload(item)),
    };
    await list.addView(this.downloadView);
  }

  dispose() {
    this.disposed = true;
    Services.obs.removeObserver(this.eventObserver, "camoufox-control-event");
    Services.obs.removeObserver(this.windowObserver, "browser-delayed-startup-finished");
    for (const topic of ["browsing-context-attached", "browsing-context-did-set-embedder",
      "browsing-context-discarded"])
      Services.obs.removeObserver(this.contextObserver, topic);
    this.contexts.clear();
    this.navigationSequence.clear();
    for (const close of this.windows.values()) close();
    this.network?.dispose();
    if (this.downloadView) this.downloadList.removeView(this.downloadView);
  }
}
