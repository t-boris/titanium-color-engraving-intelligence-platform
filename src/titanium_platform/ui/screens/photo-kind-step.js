/* «Какая гравировка?» as the last step of «Новая работа» of a photograph (BUG-003, REQ-071; shared with feature ux-work-creation-p0).
   The work is made first, on its scale, so that its own picture can be shown in every kind (the tiles of PhotoPanels.kindTiles). The question is
   answered in one dialog, and the work exists only if the person confirms it: «Создать в «…»» keeps the work in the chosen kind; «← Назад», ×,
   Escape or a click outside delete the work the caller made, so no half-made work is left. ``open`` only runs this dialog: what comes before
   it (the picture, the name, the width) and after it (opening the work) belongs to the caller — the dialog of photo engraving and the
   creation screen both call it, so the question and its rules are the same in both. */
'use strict';
const PhotoKindStep = (() => {
  const {h, post, del, modal, fail} = App;
  const {kindTiles, kindName, GRAYSCALE, KINDS_ABOUT} = PhotoPanels;

  const TITLE = 'Новая работа · шаг 2 из 2: какая гравировка?';

  /** The dialog for the work ``id`` (made and not yet kept). Options, all optional:
      ``title``    the dialog's title; ``initial`` the kind marked at the start (grayscale);
      ``onChoose`` called with the kind at every click on a tile;
      ``before``   async, called when «Создать в…» is pressed and before the kind is saved; if it throws, the work is not kept and the dialog stays;
      ``failed``   async, called when saving the kind failed (the dialog stays, the work is not kept);
      ``onKept``   called with the chosen kind after the dialog is closed, the work being kept in it;
      ``onLeft``   called as ``{back}`` after the dialog is closed without keeping the work (it is being deleted); ``back`` is true for «← Назад». */
  function open(id, {title = TITLE, initial = GRAYSCALE, onChoose = null, before = null, failed = null, onKept = null, onLeft = null} = {}) {
    let chosen = initial, kept = false, back = false;
    const label = () => `Создать в «${kindName(chosen)}»`;
    const tiles = kindTiles(`/photo-works/${id}`, chosen, (key) => {
      chosen = key; tiles.mark(key); create.textContent = label();
      if (onChoose) onChoose(key);
    }, 'выбрано');
    const dialog = modal(title, h('div', {class: 'stack'},
      h('p', {class: 'small'}, 'Под каждым видом — ваша картинка, какой она выйдет на титане на шкале работы; щелчок выбирает вид. ' + KINDS_ABOUT), tiles.el), [
      {label: '← Назад', run: (m) => { back = true; m.close(); }},
      {label: label(), cls: 'primary', run: async (m) => {
        kept = true;                                      // from here the work stays, even if the dialog is closed while it is saved
        try {
          if (before) await before();
        } catch (e) { kept = false; throw e; }
        try {
          if (chosen !== GRAYSCALE) await post(`/photo-works/${id}/settings`, {kind: chosen});
        } catch (e) {
          kept = false;
          if (failed) await failed();
          throw e;
        }
        m.close();
        if (onKept) onKept(chosen);
      }}], () => {
      if (kept) return;
      del('/plans/' + id).catch(fail);
      if (onLeft) onLeft({back});
    });
    const buttons = dialog.el.querySelectorAll('button');
    const create = buttons[buttons.length - 1];
    return dialog;
  }

  return {open, TITLE};
})();
