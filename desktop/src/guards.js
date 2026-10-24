/* What the window may do (REQ-080 security): navigate only within the core's origin, open http(s) links in the system browser and
   nothing else, and a Content-Security-Policy for the core's pages. No Electron here, so `node --test` covers it. */
'use strict';

/** The CSP of the application pages: everything from the core's own origin, pictures also as data: and blob: (the editor draws them). */
function csp(origin) {
  return [`default-src 'self' ${origin}`, `script-src 'self' ${origin}`, `style-src 'self' ${origin} 'unsafe-inline'`,
    `img-src 'self' ${origin} data: blob:`, `connect-src 'self' ${origin}`, `font-src 'self' ${origin} data:`, "object-src 'none'",
    "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'"].join('; ');
}

/** The window may navigate within the core's origin only (the session address included). */
function navigationAllowed(url, origin) {
  try { return new URL(url).origin === origin; } catch (e) { return false; }
}

/** A link the page opens in a new window: http(s) goes to the system browser, anything else is denied. */
function windowOpenDecision(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? 'external' : 'deny';
  } catch (e) { return 'deny'; }
}

/** The permissions a page may ask for: none in v1 (the camera and the microphone are not used). */
function permissionAllowed(permission) {
  return ['clipboard-read', 'clipboard-sanitized-write', 'fullscreen'].includes(permission);
}

module.exports = {csp, navigationAllowed, windowOpenDecision, permissionAllowed};
