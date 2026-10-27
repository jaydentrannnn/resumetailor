// The pending fills ("Fill this page" waiting on Prepare), kept in session storage under
// one key and keyed by application id. Every change goes through `changePending`, one at a
// time: two read-modify-writes that overlap would write back an older copy and lose an
// application that started waiting meanwhile.

export const PENDING_KEY = "pendingFills";

let queue = Promise.resolve();

export async function readPending() {
  const { [PENDING_KEY]: pending } = await chrome.storage.session.get(PENDING_KEY);
  return pending && typeof pending === "object" ? pending : {};
}

/**
 * Run `change(pending)` on the current pending fills and save what it leaves, after every
 * earlier change finished. Resolves to its result; a throw saves nothing. `change` must
 * not wait on the network: the next change waits for it.
 */
export function changePending(change) {
  const run = queue.then(async () => {
    const pending = await readPending();
    const result = await change(pending);
    await chrome.storage.session.set({ [PENDING_KEY]: pending });
    return result;
  });
  queue = run.catch(() => {});
  return run;
}
