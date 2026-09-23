// Ordinary profile startup must not import the Juggler execution environment.
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const imported = [], observers = [], scripts = [];
let enabled = false;
const context = vm.createContext({
  ChromeUtils: {
    importESModule(uri) { imported.push(uri); throw new Error(`Unexpected import ${uri}`); },
    camouGetBool() { return enabled; },
    generateQI() { return () => {}; },
  },
  Services: {
    scriptloader: {loadSubScript(uri) { scripts.push(uri); }},
    obs: {addObserver(_, topic) { observers.push(topic); }, removeObserver() {}},
  },
  Components: {classes: {}, interfaces: {}, ID() {}},
});
const source = fs.readFileSync(new URL("../../additions/juggler/components/Juggler.js", import.meta.url), "utf8");
vm.runInContext(source.replace(/\bexport\s+(?=class|var|const|function)/g, "") +
  "\nglobalThis.component = JugglerFactory();", context);
assert.equal(imported.length, 0);
assert.equal(scripts.length, 0);
context.component.observe(null, "profile-after-change");
await context.component.observe({handleFlag() { return false; }}, "command-line-startup");
assert.equal(imported.length, 0);
assert.equal(scripts.length, 0);
enabled = true;
await context.component.observe({handleFlag() { throw new Error("Native mode consumed a Juggler flag"); }}, "command-line-startup");
assert.equal(imported.length, 0);
assert.equal(scripts.length, 0);
console.log("startup: disabled and native modes leave Juggler execution modules unloaded");
