/* Shared explanations of workshop terminology, including optional technical identifiers (REQ-003). */
'use strict';
const Terms = (() => {
  const {h} = App;
  const TERMS = {
    pair: {name: 'pair', question: 'What is a pair?', task: 'photo and engraving',
      about: 'A pair is an engraved plate and its photograph reviewed together. The application measures colors from an accepted pair; until acceptance, its measurements are excluded from knowledge and predictions.'},
    knowledge: {name: 'knowledge', question: 'What is a knowledge record?', task: 'record of tested settings',
      about: 'A knowledge record links laser settings to the color they produce on titanium and the measurements supporting them. Predictions and findings use these records.'},
    stage: {name: 'stage', question: 'What is a stage?', task: 'how thoroughly the record has been checked',
      about: 'A stage describes how thoroughly a knowledge record has been checked: measured, candidate, repeated, validated or production. A person must explicitly promote a record to production; its stage is not lowered automatically.'},
    basis: {name: 'evidence', question: 'What is evidence?', task: 'what supports the result',
      about: 'Evidence is the photographs, measurements and knowledge records supporting a number or finding. You can open and inspect them.'}};

  const known = (key) => { const t = TERMS[key]; if (!t) throw new Error(`unknown term ${key}`); return t; };
  /** A task-oriented phrase followed by the technical term. */
  const say = (key) => { const t = known(key); return `${t.task} (${t.name})`; };
  /** What the word means, in a sentence. */
  const about = (key) => known(key).about;
  /** A fold that explains the word; the technical number (``id``) is in it, not in the text around it. */
  function note(key, id) {
    const t = known(key);
    return h('details', {class: 'small terms-note'}, h('summary', {}, t.question), h('p', {}, t.about),
      id == null || id === '' ? null : h('p', {class: 'muted'}, `Technical identifier: ${t.name} #${id}`));
  }
  return {TERMS, say, about, note};
})();
