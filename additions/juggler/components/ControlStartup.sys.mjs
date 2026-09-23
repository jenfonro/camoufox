/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// A profile observer, not a remote-debugging command-line handler. No controller
// or content actor is loaded by the normal (disabled) startup path.
export class ControlStartup {
  QueryInterface = ChromeUtils.generateQI(["nsIObserver"]);

  observe(subject, topic) {
    if (topic === "profile-after-change") {
      if (!ChromeUtils.camouGetBool("control:enabled", false)) return;
      Services.obs.addObserver(this, "command-line-startup");
      Services.obs.addObserver(this, "final-ui-startup");
      Services.obs.addObserver(this, "quit-application");
    } else if (topic === "command-line-startup") {
      Services.obs.removeObserver(this, topic);
      this.conflict = ["juggler-pipe", "marionette", "remote-debugging-port", "remote-debugging-pipe"]
        .some(flag => subject.findFlag(flag, false) >= 0) ||
        Services.env.exists("MOZ_MARIONETTE") ||
        Services.prefs.getBoolPref("marionette.enabled", false);
    } else if (topic === "final-ui-startup") {
      Services.obs.removeObserver(this, topic);
      if (this.conflict) {
        console.error("Camoufox control: native control and remote-debugging startup are mutually exclusive.");
        return;
      }
      this.starting = this.start().catch(error => {
        console.error(`Camoufox control: ${error.message}`);
      });
    } else if (topic === "quit-application") {
      Services.obs.removeObserver(this, topic);
      this.service?.stop(true);
    }
  }

  async start() {
    const {ControlService} =
      ChromeUtils.importESModule("chrome://juggler/content/control/ControlService.sys.mjs");
    this.service = new ControlService();
    await this.service.start();
  }
}

const instance = new ControlStartup();
export function ControlStartupFactory() {
  return instance;
}
