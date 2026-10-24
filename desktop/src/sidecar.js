/* The Python core as a child of the shell (DEC-046, REQ-080): started on a free loopback port with a per-launch session secret, its
   JSON ready line read from stdout, restarted once when it dies, never in a loop, and terminated on quit so that its port and the
   workshop lock are released. No Electron here: the process functions are injected, so `node --test` covers the logic. */
'use strict';
const crypto = require('node:crypto');
const path = require('node:path');
const fs = require('node:fs');

const READY_TIMEOUT_MS = 120000;
const LOG_TAIL_LINES = 60;
const STOP_GRACE_MS = 8000;

/** The ready line of the core: `{"ready": true, "port": N, "pid": P}`; null for any other line. */
function parseReadyLine(line) {
  const text = String(line || '').trim();
  if (!text.startsWith('{')) return null;
  try {
    const data = JSON.parse(text);
    if (data && data.ready === true && Number.isInteger(data.port) && data.port > 0) return {port: data.port, pid: data.pid, version: data.version};
  } catch (e) { /* not the ready line */ }
  return null;
}

/** What to run: the packaged core next to the app (resources/titanium-core), else the development core: the Python of
 *  TCE_CORE_PYTHON or the repository's venv, running the repository's sources. */
function coreCommand({resourcesPath, repoRoot, platform = process.platform, exists = fs.existsSync, env = process.env}) {
  const exe = platform === 'win32' ? 'titanium-core.exe' : 'titanium-core';
  const packaged = resourcesPath ? path.join(resourcesPath, 'titanium-core', exe) : null;
  if (packaged && exists(packaged)) return {command: packaged, args: [], packaged: true};
  const venv = platform === 'win32' ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe') : path.join(repoRoot, '.venv', 'bin', 'python');
  return {command: env.TCE_CORE_PYTHON || venv, args: ['-m', 'titanium_platform'], packaged: false, env: {PYTHONPATH: path.join(repoRoot, 'src')}};
}

/** The arguments the core is started with for a workshop folder. */
function coreArgs(dataDir, parentPid) {
  return ['--desktop', '--port', '0', '--parent-pid', String(parentPid), '--data-dir', dataDir];
}

/** The restart policy: the core is started again once after an unexpected death; the second death is an error for the user. */
function restartDecision(deaths, {stopping = false} = {}) {
  if (stopping) return 'stopped';
  return deaths <= 1 ? 'restart' : 'give-up';
}

function tail(lines, n = LOG_TAIL_LINES) {
  return lines.slice(-n).join('\n');
}

class Sidecar {
  /**
   * @param {object} io  spawn(command, args, options) -> child with stdout/stderr streams, on('exit'), kill(); plus the command.
   */
  constructor({spawn, command, args = [], env = {}, dataDir, parentPid, onLog = () => {}, timeoutMs = READY_TIMEOUT_MS}) {
    Object.assign(this, {spawn, command, baseArgs: args, baseEnv: env, dataDir, parentPid, onLog, timeoutMs});
    this.child = null;
    this.secret = null;
    this.port = null;
    this.deaths = 0;
    this.stopping = false;
    this.log = [];
    this.onDeath = null;
  }

  /** Start the core and resolve with {port, secret, url} once it says it is ready; reject with the log tail on failure or timeout. */
  start() {
    this.secret = crypto.randomBytes(24).toString('base64url');
    const env = {...process.env, ...this.baseEnv, TCE_SESSION_SECRET: this.secret, TCE_DESKTOP: '1', PYTHONUNBUFFERED: '1'};
    const child = this.spawn(this.command, [...this.baseArgs, ...coreArgs(this.dataDir, this.parentPid)], {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
    this.child = child;
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => finish(new Error('the core did not report ready in time')), this.timeoutMs);
      const finish = (error, ready) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (error) { error.logTail = tail(this.log); reject(error); } else resolve(ready);
      };
      let buffer = '';
      child.stdout.on('data', (chunk) => {
        buffer += chunk.toString();
        let at;
        while ((at = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, at);
          buffer = buffer.slice(at + 1);
          this.remember(line);
          const ready = parseReadyLine(line);
          if (ready) {
            this.port = ready.port;
            finish(null, {...ready, secret: this.secret, url: this.url()});
          }
        }
      });
      child.stderr.on('data', (chunk) => String(chunk).split('\n').filter(Boolean).forEach((l) => this.remember(l)));
      child.on('error', (error) => { this.child = null; finish(error); });
      child.on('exit', (code, signal) => {
        this.child = null;
        if (!settled) finish(new Error(`the core stopped before it was ready (code ${code}, signal ${signal})`));
        else if (!this.stopping) { this.deaths += 1; if (this.onDeath) this.onDeath(restartDecision(this.deaths), {code, signal, logTail: tail(this.log)}); }
      });
    });
  }

  url() { return `http://127.0.0.1:${this.port}`; }
  bootstrapUrl() { return `${this.url()}/session/${this.secret}`; }

  remember(line) {
    this.log.push(line);
    if (this.log.length > 500) this.log.splice(0, this.log.length - 500);
    this.onLog(line);
  }

  /** Terminate the core and wait for it to exit, so that the port and the workshop lock are free when the shell quits. */
  stop() {
    this.stopping = true;
    const child = this.child;
    if (!child) return Promise.resolve();
    return new Promise((resolve) => {
      const killer = setTimeout(() => { try { child.kill('SIGKILL'); } catch (e) { /* gone */ } setTimeout(resolve, 1000); }, STOP_GRACE_MS);
      child.on('exit', () => { clearTimeout(killer); resolve(); });
      if (child.exitCode !== null && child.exitCode !== undefined) { clearTimeout(killer); resolve(); return; }
      try { child.kill('SIGTERM'); } catch (e) { clearTimeout(killer); resolve(); }
    });
  }
}

module.exports = {Sidecar, parseReadyLine, coreCommand, coreArgs, restartDecision, tail, READY_TIMEOUT_MS};
