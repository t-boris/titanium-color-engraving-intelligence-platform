/* Update checks (DEC-048, REQ-080): off by default; when the user switches them on, the shell asks GitHub Releases for the latest
   release of the owner's repository and shows a banner with a link when it is newer. Nothing is downloaded or applied by the shell in
   this version: the apply step waits for signed builds (DEC-044). No Electron here. */
'use strict';
const https = require('node:https');

const REPO = 't-boris/titanium-color-engraving-intelligence-platform';
const LATEST = `https://api.github.com/repos/${REPO}/releases/latest`;
const RELEASES = `https://github.com/${REPO}/releases`;

/** SemVer-ish comparison of `a` and `b` (a leading v is ignored, pre-release parts are lower than none): -1, 0, 1. */
function compareVersions(a, b) {
  const parse = (v) => {
    const [core, pre] = String(v).replace(/^v/i, '').split('-');
    return {nums: core.split('.').map((n) => parseInt(n, 10) || 0), pre: pre || null};
  };
  const x = parse(a), y = parse(b);
  for (let i = 0; i < Math.max(x.nums.length, y.nums.length); i++) {
    const d = (x.nums[i] || 0) - (y.nums[i] || 0);
    if (d) return d < 0 ? -1 : 1;
  }
  if (x.pre === y.pre) return 0;
  if (x.pre === null) return 1;
  if (y.pre === null) return -1;
  return x.pre < y.pre ? -1 : 1;
}

/** What a GitHub release answer says: the version, whether it is newer than `current`, its page and its assets' names. */
function parseLatest(data, current) {
  if (!data || typeof data.tag_name !== 'string') return null;
  const version = data.tag_name.replace(/^v/i, '');
  return {version, newer: compareVersions(version, current) > 0, prerelease: !!data.prerelease, url: data.html_url || RELEASES,
    assets: (data.assets || []).map((a) => a.name), publishedAt: data.published_at || null};
}

/** Ask GitHub for the latest release; resolves with parseLatest's result or null when the network is not reachable (never throws). */
function fetchLatest(current, {get = https.get, timeoutMs = 15000} = {}) {
  return new Promise((resolve) => {
    const request = get(LATEST, {headers: {'User-Agent': 'titanium-workshop', Accept: 'application/vnd.github+json'}}, (response) => {
      let body = '';
      response.on('data', (c) => { body += c; });
      response.on('end', () => {
        try { resolve(response.statusCode === 200 ? parseLatest(JSON.parse(body), current) : null); } catch (e) { resolve(null); }
      });
    });
    request.on('error', () => resolve(null));
    request.setTimeout(timeoutMs, () => { request.destroy(); resolve(null); });
  });
}

module.exports = {compareVersions, parseLatest, fetchLatest, LATEST, RELEASES};
