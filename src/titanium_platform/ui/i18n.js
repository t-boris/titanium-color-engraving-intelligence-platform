/* Server messages and names are already in English; retain operator-supplied text verbatim. */
'use strict';
const I18N = (() => {
  const tr = (message) => String(message || '') || 'Unknown error';
  const name = (value) => String(value ?? '');
  // Kept for callers that previously distinguished translated server messages from operator text.
  const known = () => null;
  const add = () => {};
  return {tr, name, known, add, count: () => 0};
})();
