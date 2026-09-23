/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

const {MouseDispatch} = ChromeUtils.importESModule("chrome://juggler/content/input/MouseDispatch.js");
const {fail, number, choice, string, delay, bounded, checkAbort, setTimeout, clearTimeout} =
  ChromeUtils.importESModule("chrome://juggler/content/control/ControlUtils.sys.mjs");

const BUTTON_BITS = [1, 4, 2, 8, 16];

export class ControlInput {
  constructor(controller) {
    this.controller = controller;
    this.states = new Map();
    this.queue = Promise.resolve();
    this.owner = null;
    this.lastEvent = null;
    this.processors = new WeakMap();
  }

  state(session, context) {
    const key = session.id;
    if (!this.states.has(key))
      this.states.set(key, {session: session.id, context, x: 0, y: 0,
        buttons: 0, keys: new Map(), sources: new Map(), positions: new Map(), dragging: false});
    const state = this.states.get(key);
    if (state.context !== context) {
      state.positions.set(state.context, {x: state.x, y: state.y});
      Object.assign(state, state.positions.get(context) || {x: 0, y: 0});
      state.context = context;
    }
    state.topContext = String(this.controller.context(context).top.id);
    return state;
  }

  async toTop(context, x, y, options) {
    let bc = this.controller.context(context);
    while (bc.parent) {
      const geometry = await this.controller.query(String(bc.parent.id), "page.frameGeometry",
        {child: String(bc.id)}, options);
      if (!geometry.width || !geometry.height)
        fail("element not interactable", "Frame has no visible viewport");
      const page = await this.controller.query(String(bc.id), "page.info", {}, options);
      const px = x / page.viewport.width;
      const py = y / page.viewport.height;
      x = geometry.p1.x + (geometry.p2.x - geometry.p1.x) * px + (geometry.p4.x - geometry.p1.x) * py;
      y = geometry.p1.y + (geometry.p2.y - geometry.p1.y) * px + (geometry.p4.y - geometry.p1.y) * py;
      bc = bc.parent;
    }
    const {viewport} = await this.controller.query(String(bc.id), "page.info", {}, options);
    return {x, y, viewport};
  }

  modifiers(win, params, state) {
    const names = params.modifiers ?? [...state.keys.keys()].filter(k => ["Shift", "Control", "Alt", "Meta"].includes(k));
    if (!Array.isArray(names)) fail("invalid argument", "modifiers must be an array");
    const constants = {
      Shift: win.windowUtils.MODIFIER_SHIFT, Control: win.windowUtils.MODIFIER_CONTROL,
      Alt: win.windowUtils.MODIFIER_ALT, Meta: win.windowUtils.MODIFIER_META,
    };
    let value = 0;
    for (const name of names) {
      if (!Object.hasOwn(constants, name)) fail("invalid argument", `Unknown modifier ${name}`);
      value |= constants[name];
    }
    return value;
  }

  async pointer(context, params, state, options) {
    checkAbort(options.signal);
    const type = choice(params.type, "type", ["pointerMove", "pointerDown", "pointerUp"]);
    const element = params.node ? await this.controller.query(context, "dom.get", {node: params.node}, options) : null;
    if (element && (!element.visible || !element.enabled || !element.hit))
      fail("element not interactable", "Node is hidden, disabled, or covered at its center");
    let x = element ? element.point.x : number(params.x ?? state.x, "x");
    let y = element ? element.point.y : number(params.y ?? state.y, "y");
    const page = await this.controller.query(context, "page.info", {}, options);
    if (x < 0 || y < 0 || x >= page.viewport.width || y >= page.viewport.height)
      fail("move target out of bounds", "Point is outside the real frame viewport");
    const top = await this.toTop(context, x, y, options);
    const browser = this.controller.browser(context);
    const win = browser.ownerDocument.defaultView;
    let button = params.button ?? 0;
    number(button, "button", 0, 4, true);
    let buttons = state.buttons;
    if (type === "pointerDown") {
      if (buttons & BUTTON_BITS[button]) fail("invalid state", "Pointer button is already pressed");
      buttons |= BUTTON_BITS[button];
    }
    if (type === "pointerUp") {
      if (!(buttons & BUTTON_BITS[button])) fail("invalid state", "Pointer button is not pressed");
      buttons &= ~BUTTON_BITS[button];
    }
    const dispatch = MouseDispatch.forNativeBrowser(win, browser, {
      button, buttons, clickCount: type === "pointerMove" ? 0 : params.clickCount ?? 1,
      modifiers: this.modifiers(win, params, state),
    }, top.viewport);
    if (!dispatch.isInViewport(top.x, top.y))
      fail("move target out of bounds", "Point is outside the real top-level viewport");
    const drag = await this.controller.query(context, "input.dragStatus", {}, options);
    state.dragging = drag.active;
    if (state.dragging && type !== "pointerDown") {
      await this.controller.query(context, "input.drag", {type: "dragover", x, y,
        modifiers: this.modifiers(win, params, state)}, options);
      if (type === "pointerUp") {
        await this.controller.query(context, "input.drag", {type: "drop", x, y,
          modifiers: this.modifiers(win, params, state)}, options);
        await this.controller.query(context, "input.drag", {type: "dragend"}, options);
        state.dragging = false;
      }
      Object.assign(state, {x, y, buttons});
      return {};
    }
    let observer;
    const flushed = new Promise(resolve => {
      observer = {observe: resolve};
      Services.obs.addObserver(observer, "apz-repaints-flushed");
    });
    try {
      if (win.windowUtils.flushApzRepaints()) await bounded(flushed, 3000, options.signal);
    } finally { Services.obs.removeObserver(observer, "apz-repaints-flushed"); }
    const eventType = {pointerMove: "mousemove", pointerDown: "mousedown", pointerUp: "mouseup"}[type];
    // Input may have reached the widget even if content did not acknowledge it.
    // Retain pressed state so disconnect/cancellation can release it.
    state.x = x;
    state.y = y;
    state.buttons = buttons;
    const ack = await dispatch.sendNativeAcked(eventType, top.x, top.y);
    this.lastEvent = {type: eventType, context, completed: ack, point: top,
      parentPoint: dispatch.toAbsolute(top.x, top.y), fullZoom: browser.browsingContext.fullZoom};
    if (!ack) fail("input timeout", "The renderer did not acknowledge input");
    if (type === "pointerDown" && button === 2)
      await dispatch.sendNativeAcked("contextmenu", top.x, top.y);
    await this.controller.query(context, "input.barrier", {}, options);
    return {};
  }

  async key(context, params, state, options) {
    choice(params.type, "type", ["keydown", "keyup"]);
    string(params.key, "key");
    if (params.code !== undefined) string(params.code, "code", {empty: true});
    if (params.keyCode !== undefined) number(params.keyCode, "keyCode", 0, 255, true);
    if (params.location !== undefined) number(params.location, "location", 0, 3, true);
    if (params.repeat !== undefined && typeof params.repeat !== "boolean")
      fail("invalid argument", "repeat must be a boolean");
    if (params.type === "keydown" && !state.keys.has(params.key) && state.keys.size >= 256)
      fail("resource limit", "Too many pressed keys");
    if (params.key === "Escape" && params.type === "keydown" &&
        (await this.controller.query(context, "input.dragStatus", {}, options)).active) {
      await this.controller.query(context, "input.drag", {type: "dragend"}, options);
      state.dragging = false;
      state.buttons = 0;
    }
    if (params.type === "keydown") state.keys.set(params.key, {...params});
    else state.keys.delete(params.key);
    await this.controller.query(context, "input.focus", {}, options);
    const win = this.controller.browser(context).ownerDocument.defaultView;
    const key = params.key;
    const keyCodes = {Backspace: 8, Tab: 9, Enter: 13, Shift: 16, Control: 17,
      Alt: 18, Pause: 19, CapsLock: 20, Escape: 27, " ": 32, PageUp: 33,
      PageDown: 34, End: 35, Home: 36, ArrowLeft: 37, ArrowUp: 38,
      ArrowRight: 39, ArrowDown: 40, Insert: 45, Delete: 46, Meta: 91};
    const code = params.code ?? (/^[a-z]$/i.test(key) ? `Key${key.toUpperCase()}` :
      /^[0-9]$/.test(key) ? `Digit${key}` : key === " " ? "Space" :
      ["Control", "Shift", "Alt", "Meta"].includes(key) ? `${key}Left` : key.length > 1 ? key : "");
    const keyCode = params.keyCode ?? keyCodes[key] ??
      (/^[a-z0-9]$/i.test(key) ? key.toUpperCase().charCodeAt(0) :
        /^F([1-9]|1[0-9]|2[0-4])$/.test(key) ? 111 + Number(key.slice(1)) : 0);
    this.processor(win)[params.type](new win.KeyboardEvent("", {key, code, keyCode,
      location: params.location || 0, repeat: !!params.repeat}), 0);
    await this.controller.query(context, "input.barrier", {}, options);
    return {};
  }

  processor(win) {
    let tip = this.processors.get(win);
    if (!tip) {
      tip = Cc["@mozilla.org/text-input-processor;1"].createInstance(Ci.nsITextInputProcessor);
      this.processors.set(win, tip);
    }
    if (!tip.beginInputTransactionForTests(win))
      fail("input unavailable", "Another input transaction owns the target widget");
    return tip;
  }

  async insertText(context, params, options) {
    string(params.text, "text", {empty: true});
    await this.controller.query(context, "input.focus", {}, options);
    const win = this.controller.browser(context).ownerDocument.defaultView;
    this.processor(win).commitCompositionWith(params.text);
    await this.controller.query(context, "input.barrier", {}, options);
    return {};
  }

  async wheel(context, params, state, options) {
    const x = number(params.x, "x", 0);
    const y = number(params.y, "y", 0);
    const page = await this.controller.query(context, "page.info", {}, options);
    if (x >= page.viewport.width || y >= page.viewport.height)
      fail("move target out of bounds", "Wheel origin is outside the real frame viewport");
    const point = await this.toTop(context, x, y, options);
    const browser = this.controller.browser(context);
    const win = browser.ownerDocument.defaultView;
    const dispatch = MouseDispatch.forNativeBrowser(win, browser,
      {modifiers: this.modifiers(win, params, state)}, point.viewport);
    if (!dispatch.isInViewport(point.x, point.y))
      fail("move target out of bounds", "Wheel origin is outside the real viewport");
    const deltaX = number(params.deltaX ?? 0, "deltaX");
    const deltaY = number(params.deltaY ?? 0, "deltaY");
    const deltaMode = number(params.deltaMode ?? 0, "deltaMode", 0, 2, true);
    const delivered = await dispatch.sendNativeWheelAcked(point.x, point.y,
      {deltaX, deltaY, deltaZ: 0, deltaMode,
        lineOrPageDeltaX: Math.trunc(deltaX), lineOrPageDeltaY: Math.trunc(deltaY)});
    if (!delivered) fail("input timeout", "Wheel input was not acknowledged");
    return {};
  }

  async releaseState(state) {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), 5000);
    const options = {sessionId: state.session, timeout: 5000, signal: abort.signal};
    try {
      try { this.controller.context(state.context); }
      catch (_) { state.context = state.topContext; }
      for (const event of [...state.keys.values()].reverse()) {
        if (abort.signal.aborted) break;
        try { await this.key(state.context, {...event, type: "keyup"}, state, options); } catch (_) {}
      }
      state.keys.clear();
      try { await this.controller.query(state.context, "input.drag", {type: "dragend"}, options); } catch (_) {}
      state.dragging = false;
      for (let button = 0; button < BUTTON_BITS.length && !abort.signal.aborted; button++) {
        if (!(state.buttons & BUTTON_BITS[button])) continue;
        try {
          const page = await this.controller.query(state.context, "page.info", {}, options);
          await this.pointer(state.context, {type: "pointerUp", button,
            x: Math.max(0, Math.min(state.x, page.viewport.width - 1)),
            y: Math.max(0, Math.min(state.y, page.viewport.height - 1))}, state, options);
        } catch (_) {}
      }
    } finally {
      clearTimeout(timer);
      state.keys.clear();
      state.dragging = false;
      state.buttons = 0;
    }
  }

  forgetContext(context) {
    for (const state of this.states.values()) {
      state.positions.delete(context);
      if (state.context === context) this.releaseSession(state.session);
    }
  }

  releaseSession(sessionId) {
    const operation = this.queue.then(async () => {
      for (const [key, state] of this.states) {
        if (state.session !== sessionId) continue;
        await this.releaseState(state);
        this.states.delete(key);
      }
      if (this.owner === sessionId) this.owner = null;
    });
    this.queue = operation.catch(() => {});
    return operation;
  }

  command(method, params, session, options) {
    const operation = this.queue.then(async () => {
      checkAbort(options.signal);
      const context = string(params.context, "context");
      if (this.owner && this.owner !== session.id)
        fail("input busy", "Another connection has pressed input; release it before transferring control");
      await this.controller.activate(context, options);
      const state = this.state(session, context);
      try {
        if (method === "input.dispatchPointer") return await this.pointer(context, params, state, options);
        if (method === "input.dispatchKey") return await this.key(context, params, state, options);
        if (method === "input.insertText") return await this.insertText(context, params, options);
        if (method === "input.dispatchWheel") return await this.wheel(context, params, state, options);
        if (method === "input.releaseActions") {
          await this.releaseState(state);
          state.sources.clear();
          return {};
        }
        if (method === "input.click") {
          const count = number(params.count ?? 1, "count", 1, 3, true);
          if (params.node)
            await this.controller.query(context, "dom.scrollIntoView", {node: params.node}, options);
          await this.pointer(context, {...params, type: "pointerMove"}, state, options);
          for (let i = 1; i <= count; i++) {
            await this.pointer(context, {...params, type: "pointerDown", clickCount: i}, state, options);
            await this.pointer(context, {...params, type: "pointerUp", clickCount: i}, state, options);
          }
          return {};
        }
        if (method !== "input.performActions") fail("unknown method", `Unknown input method: ${method}`);
        if (!Array.isArray(params.actions) || !params.actions.length || params.actions.length > 16)
          fail("invalid argument", "actions must contain 1 to 16 sources");
        const sourceIds = new Set();
        const sourceTypes = new Set();
        for (const source of params.actions) {
          string(source.id, "source.id");
          if (sourceIds.has(source.id)) fail("invalid argument", "Input source ids must be unique");
          sourceIds.add(source.id);
          choice(source.type, "source.type", ["pointer", "key", "wheel", "none"]);
          if (source.type !== "none" && sourceTypes.has(source.type))
            fail("unsupported operation", "Only one source of each physical input type is supported");
          sourceTypes.add(source.type);
          if (state.sources.has(source.id) && state.sources.get(source.id) !== source.type)
            fail("invalid argument", "Input source type cannot change before releaseActions");
          if (!state.sources.has(source.id) && state.sources.size >= 64)
            fail("resource limit", "Release existing input sources before creating more");
          state.sources.set(source.id, source.type);
          if (source.type === "pointer" && (source.parameters?.pointerType ?? "mouse") !== "mouse")
            fail("unsupported operation", "This implementation supports mouse pointer sources");
          if (!Array.isArray(source.actions) || source.actions.length > 1000)
            fail("invalid argument", "Each source requires at most 1000 actions");
        }
        const ticks = Math.max(...params.actions.map(source => source.actions.length));
        for (let i = 0; i < ticks; i++) {
          const started = Date.now();
          let pause = 0;
          const sources = [...params.actions].sort((a, b) =>
            Number(a.actions[i]?.type === "pointerMove") - Number(b.actions[i]?.type === "pointerMove"));
          for (const source of sources) {
            checkAbort(options.signal);
            const action = source.actions[i];
            if (!action) continue;
            const duration = number(action.duration ?? 0, "duration", 0, 30000);
            pause = Math.max(pause, duration);
            if (action.type === "pause") continue;
            if (source.type === "pointer") {
              let {x, y} = action;
              if (action.type === "pointerMove") {
                const origin = action.origin ?? "viewport";
                if (origin === "pointer") { x += state.x ?? 0; y += state.y ?? 0; }
                else if (typeof origin === "object" && origin.node) {
                  const node = await this.controller.query(context, "dom.get", {node: origin.node}, options);
                  x += node.point.x; y += node.point.y;
                } else if (origin !== "viewport") fail("invalid argument", "Unknown pointer origin");
                number(x, "x"); number(y, "y");
                const start = {x: state.x, y: state.y};
                const steps = duration ? Math.max(1, Math.ceil(duration / 16)) : 1;
                for (let step = 1; step <= steps; step++) {
                  await this.pointer(context, {...action, x: start.x + (x - start.x) * step / steps,
                    y: start.y + (y - start.y) * step / steps}, state, options);
                  const remaining = started + duration * step / steps - Date.now();
                  if (remaining > 0) await delay(remaining, options.signal);
                }
              } else {
                await this.pointer(context, action, state, options);
              }
            } else if (source.type === "key") {
              await this.key(context, {...action, type: choice(action.type, "type", ["keyDown", "keyUp"]) === "keyDown" ? "keydown" : "keyup",
                key: action.key ?? action.value}, state, options);
            } else if (source.type === "wheel" && action.type === "scroll") {
              await this.wheel(context, action, state, options);
            } else {
              fail("invalid argument", "Action does not match its source");
            }
          }
          const remaining = started + pause - Date.now();
          if (remaining > 0) await delay(remaining, options.signal);
        }
        return {};
      } catch (error) {
        await this.releaseState(state);
        throw error;
      } finally {
        this.owner = [...this.states.values()].some(s => s.session === session.id &&
          (s.buttons || s.keys.size || s.dragging)) ? session.id : null;
      }
    });
    this.queue = operation.catch(() => {});
    return operation;
  }
}
