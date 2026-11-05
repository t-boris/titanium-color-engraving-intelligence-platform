/* The four words of the workshop that the screens use without saying what they are (feature ux-save-feedback-p0, REQ-003): «пара»,
   «знание», «стадия», «основание». Each is explained through what the person is doing; the technical number stays available beside it
   («пара № 12»), in the details of the explanation, so it can be quoted and found. The explanations repeat what the screens of the
   product already say about these things (knowledge.js, findings.js, ingest*.js); a screen that wants the word explained asks ``Terms``
   instead of writing its own sentence. */
'use strict';
const Terms = (() => {
  const {h} = App;
  const TERMS = {
    pair: {name: 'пара', task: 'фото и гравировка',
      about: 'Пара — одна выгравированная пластина и её фотография, которые проверяются вместе. По принятой паре программа измеряет цвета; пока пара не принята, её измерения не попадают ни в знания, ни в прогнозы.'},
    knowledge: {name: 'знание', task: 'запись о проверенных настройках',
      about: 'Знание — запись о том, какие настройки лазера дают какой цвет на титане, вместе с измерениями, на которых она держится. Из таких записей строятся прогнозы и выводы.'},
    stage: {name: 'стадия', task: 'насколько запись проверена',
      about: 'Стадия показывает, насколько проверена запись знания: измерено, кандидат, повторено, валидировано, производственное. В производство запись переводит только человек, явным действием; автоматически стадия не понижается.'},
    basis: {name: 'основание', task: 'на чём это держится',
      about: 'Основание — фотографии, измерения и записи знания, на которых держится число или вывод. Их можно открыть и проверить самому.'}};

  const known = (key) => { const t = TERMS[key]; if (!t) throw new Error(`unknown term ${key}`); return t; };
  /** The words for the task: «фото и гравировка (пара)». */
  const say = (key) => { const t = known(key); return `${t.task} (${t.name})`; };
  /** What the word means, in a sentence. */
  const about = (key) => known(key).about;
  /** A fold that explains the word; the technical number (``id``) is in it, not in the text around it. */
  function note(key, id) {
    const t = known(key);
    return h('details', {class: 'small terms-note'}, h('summary', {}, `Что такое «${t.name}»?`), h('p', {}, t.about),
      id == null || id === '' ? null : h('p', {class: 'muted'}, `Технический номер: ${t.name} № ${id}`));
  }
  return {TERMS, say, about, note};
})();
