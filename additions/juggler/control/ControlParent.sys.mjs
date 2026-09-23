/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Includes documents kept alive in BFCache. Disconnect must release their
// connection-owned sandboxes and handles as well as the current document's.
export const controlActors = new Set();

export class CamoufoxControlParent extends JSWindowActorParent {
  actorCreated() { controlActors.add(this); }
  didDestroy() { controlActors.delete(this); }

  receiveMessage({name, data}) {
    if (name === "Control:event") {
      Services.obs.notifyObservers(null, "camoufox-control-event",
        JSON.stringify({...data, context: String(this.browsingContext.id)}));
    }
  }
}
