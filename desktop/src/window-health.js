/* Whether the window drew the interface (feature electron): the page of the core can load and still show nothing, no styles and no
   screens (the operator's window once showed only the skip link). After the main frame loads, the page is asked for the children of
   `#app` until there are some; when there are none in time, what the page looks like goes to the log and the window is reloaded
   once, ignoring the cache; a second failure is only logged. No Electron here: the page, the reload and the log are injected, so
   `node --test` covers it. */
'use strict';

const DRAW_TIMEOUT_MS = 15000;
const POLL_MS = 250;
const PROBE_TIMEOUT_MS = 5000;

/** The page's answer to "did the interface draw": run in the page, so it is a string. */
const PROBE_SCRIPT = "(() => { const app = document.getElementById('app'); return {children: app ? app.children.length : 0, " +
  "readyState: document.readyState, styleSheets: document.styleSheets.length, scripts: document.scripts.length, " +
  "text: (document.body ? document.body.innerText : '').trim().slice(0, 120)}; })()";

/** `promise`, or a rejection after `ms`: a page whose renderer is gone never answers. */
function withTimeout(promise, ms, message) {
  let timer;
  const late = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

/** What Electron reports as `error` for a request that went well (every completed request says `net::OK`) or that the page itself dropped. */
const HARMLESS_ERRORS = ['net::OK', 'net::ERR_ABORTED'];

/** A request worth a log line: a page or file of the core that was refused or missing, or any server error; null for the rest. An API
 *  answer of 4xx is the application talking to its user (a refused value, a missing item), not a failure of the window. */
function requestNote({method, url, statusCode, error}) {
  let pathname;
  try { pathname = new URL(url).pathname; } catch (e) { pathname = String(url); }
  if (error && !HARMLESS_ERRORS.includes(error)) return `${method} ${pathname} failed: ${error}`;
  if (statusCode >= 500 || (statusCode >= 400 && !pathname.startsWith('/api/'))) return `${method} ${pathname} answered ${statusCode}`;
  return null;
}

/** The path of an address: the log never needs a query, and the session address is not for it. */
function pathOf(url) { try { return new URL(url).pathname; } catch (e) { return String(url || ''); } }

/** The requests of the core's origin that failed go to the log: a style sheet that was refused is what a blank window would hide.
 *  `webRequest` is the session's. */
function watchRequests(webRequest, origin, note) {
  const filter = {urls: [origin + '/*']};
  const report = (details) => { const text = requestNote(details); if (text) note('net', text); };
  webRequest.onCompleted(filter, report);
  webRequest.onErrorOccurred(filter, report);
}

/** What the window reports goes to the log, and `check` runs every time its page loads or fails to. */
function watchWindow(contents, {note, check}) {
  contents.on('did-finish-load', () => { note('window', `page loaded: ${pathOf(contents.getURL())}`); check('loaded'); });
  contents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (code === -3) return;                                  // ERR_ABORTED: a navigation replaced by another one
    note('window', `${isMainFrame ? 'page' : 'frame'} failed to load: ${description} (${code}) ${pathOf(url)}`);
    if (isMainFrame) check('load-failed');
  });
  contents.on('render-process-gone', (_event, details) => note('window', `the page's process is gone: ${details.reason} (exit code ${details.exitCode})`));
  contents.on('unresponsive', () => note('window', 'the page stopped responding'));
  contents.on('responsive', () => note('window', 'the page responds again'));
  contents.on('console-message', (_event, level, message, line, source) => {
    if (level >= 2) note('page', `${level >= 3 ? 'error' : 'warning'}: ${message} (${pathOf(source)}:${line})`);
  });
}

class WindowHealth {
  constructor({probe, reload, log, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), now = Date.now,
    timeoutMs = DRAW_TIMEOUT_MS, pollMs = POLL_MS, maxReloads = 1}) {
    Object.assign(this, {probe, reload, log, sleep, now, timeoutMs, pollMs, maxReloads});
    this.reloads = 0;
    this.generation = 0;
    this.seen = null;
  }

  /** The window starts over (the core was restarted): the reload is available again, and a check in flight is dropped. */
  reset() { this.reloads = 0; this.generation += 1; }

  /** Check the window after `trigger` ('loaded' or 'load-failed'); resolves with 'drawn', 'reloaded', 'failed' or 'superseded'. */
  async check(trigger) {
    const mine = ++this.generation;
    const started = this.now();
    let seen = null;
    let problem = trigger === 'load-failed' ? 'the page did not load' : null;
    while (trigger !== 'load-failed') {
      try { seen = await this.probe(); problem = null; } catch (error) { seen = null; problem = `the page could not be asked: ${error.message}`; }
      if (mine !== this.generation) return 'superseded';
      if (seen && seen.children > 0) break;
      if (this.now() - started >= this.timeoutMs) break;
      await this.sleep(this.pollMs);
      if (mine !== this.generation) return 'superseded';
    }
    this.seen = seen;
    if (seen && seen.children > 0) {
      this.log('window', `interface drawn: ${seen.children} children of #app in ${this.now() - started} ms${this.reloads ? ` (after ${this.reloads} reload)` : ''}`);
      this.reloads = 0;
      return 'drawn';
    }
    this.log('window', `interface not drawn (${trigger}): ${problem || 'the page loaded but #app is empty'}${seen ? ` ${JSON.stringify(seen)}` : ''}`);
    if (this.reloads < this.maxReloads) {
      this.reloads += 1;
      this.log('window', 'reloading the window once, ignoring the cache');
      this.reload();
      return 'reloaded';
    }
    this.log('window', `interface still not drawn after ${this.reloads} reload: the window is left as it is`);
    return 'failed';
  }
}

module.exports = {WindowHealth, withTimeout, requestNote, watchRequests, watchWindow, pathOf, PROBE_SCRIPT, DRAW_TIMEOUT_MS, PROBE_TIMEOUT_MS};
