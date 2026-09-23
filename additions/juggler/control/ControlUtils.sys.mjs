/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

export const {setTimeout, clearTimeout} =
  ChromeUtils.importESModule("resource://gre/modules/Timer.sys.mjs");

export function fail(code, message) {
  throw Object.assign(new Error(message), {code});
}

export function object(value, name = "params") {
  if (!value || typeof value !== "object" || Array.isArray(value))
    fail("invalid argument", `${name} must be an object`);
  return value;
}

export function string(value, name, {empty = false} = {}) {
  if (typeof value !== "string" || (!empty && !value.length))
    fail("invalid argument", `${name} must be a string${empty ? "" : " with a value"}`);
  return value;
}

export function number(value, name, min = -Infinity, max = Infinity, integer = false) {
  if (typeof value !== "number" || !Number.isFinite(value) ||
      value < min || value > max || (integer && !Number.isInteger(value)))
    fail("invalid argument", `${name} is outside its numeric range`);
  return value;
}

export function choice(value, name, values) {
  if (!values.includes(value))
    fail("invalid argument", `${name} must be one of ${values.join(", ")}`);
  return value;
}

export function checkAbort(signal) {
  if (signal?.aborted) {
    if (signal.reason?.code) throw signal.reason;
    fail("cancelled", "Request was cancelled");
  }
}

export function delay(ms, signal) {
  checkAbort(signal);
  return new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      error ? reject(error) : resolve();
    };
    const abort = () => finish(Object.assign(new Error("Request was cancelled"), {code: "cancelled"}));
    const timer = setTimeout(() => finish(), ms);
    signal?.addEventListener("abort", abort, {once: true});
  });
}

export async function bounded(promise, timeout, signal) {
  checkAbort(signal);
  let timer;
  let abort;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(Object.assign(new Error("Operation timed out"), {code: "timeout"})), timeout);
        abort = () => reject(Object.assign(new Error("Request was cancelled"), {code: "cancelled"}));
        signal?.addEventListener("abort", abort, {once: true});
      }),
    ]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function errorObject(error) {
  return {code: typeof error?.code === "string" ? error.code :
    error?.name === "AbortError" ? "no such document" : "unknown error",
    message: String(error?.message || error)};
}

export function id() {
  return Services.uuid.generateUUID().toString().slice(1, -1);
}
