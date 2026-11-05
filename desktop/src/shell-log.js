/* The shell's log (feature electron): what the shell and the window did, one line per event, in a file that outlives the run, because
   the shell's stdout is read by nobody and the core writes no file of its own. The file is in the operating system's log folder, not in
   the workshop: the workshop is scanned by backups and diagnostics, and a log is needed before a workshop is chosen. The session
   address and the launch secret never reach it. No Electron here, so `node --test` covers it. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const MAX_BYTES = 1024 * 1024;
const MAX_LINE = 2000;
const SESSION_ADDRESS = /\/session\/[A-Za-z0-9_-]+/g;

/** `text` without any session address (`/session/<secret>`) and without the given secrets. */
function redact(text, secrets = []) {
  let out = String(text).replace(SESSION_ADDRESS, '/session/…');
  for (const secret of secrets) if (secret) out = out.split(secret).join('…');
  return out;
}

class ShellLog {
  /** @param {string} file  the log file; its folder is created. A second file `<file>.1` keeps the previous run's lines once `maxBytes` is passed. */
  constructor({file, fileSystem = fs, now = () => new Date(), maxBytes = MAX_BYTES}) {
    Object.assign(this, {file, fileSystem, now, maxBytes});
    this.secrets = [];
    this.size = 0;
    this.lastError = null;
    try {
      this.fileSystem.mkdirSync(path.dirname(file), {recursive: true});
      this.size = this.fileSystem.statSync(file).size;
    } catch (error) { if (error.code !== 'ENOENT') this.lastError = error; }
  }

  /** A secret of this run (the launch secret): redacted from every line written after this. */
  addSecret(secret) { if (secret) this.secrets.push(secret); }

  /** One event: a UTC time, the scope (`shell`, `core`, `window`, `net`, `page`) and the message; later lines of a long message are indented. */
  line(scope, message) {
    let text = redact(message, this.secrets);
    if (text.length > MAX_LINE) text = `${text.slice(0, MAX_LINE)}… (${text.length - MAX_LINE} more characters)`;
    const [first, ...rest] = text.split(/\r?\n/);
    const entry = [`${this.now().toISOString()} [${scope}] ${first}`, ...rest.map((l) => `    ${l}`)].join('\n') + '\n';
    try {
      if (this.size + Buffer.byteLength(entry) > this.maxBytes) this.rotate();
      this.fileSystem.appendFileSync(this.file, entry);
      this.size += Buffer.byteLength(entry);
    } catch (error) { this.lastError = error; }              // a log that cannot be written must never stop the application
  }

  rotate() {
    this.fileSystem.rmSync(`${this.file}.1`, {force: true});
    this.fileSystem.renameSync(this.file, `${this.file}.1`);
    this.size = 0;
  }
}

module.exports = {ShellLog, redact, MAX_BYTES, MAX_LINE};
