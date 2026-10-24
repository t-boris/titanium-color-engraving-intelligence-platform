/* Сообщения переносимых лабораторий (electron REQ-083..085): публикация своих результатов, подключение чужих выпусков, перенос
   рецепта. Загружается перед i18n-gaps.js, который идёт последним. */
'use strict';
(() => {
  const FIELD = {name: 'название лаборатории', description: 'описание', url: 'ссылка лаборатории', author: 'автор', organization: 'организация',
    author_url: 'ссылка автора', public_name: 'публичное название лазера', manufacturer: 'производитель', model: 'модель'};
  const f = (s) => FIELD[s] || s;
  I18N.add([
    [/^the public text (\S+) is longer than (\d+) characters$/i, (m) => `Публичный текст «${f(m[1])}» длиннее ${m[2]} символов`],
    [/^the public text (\S+) may hold only plain text: no links, scripts or file paths$/i,
      (m) => `Публичный текст «${f(m[1])}» — только простой текст: без ссылок, скриптов и путей к файлам`],
    [/^the link (\S+) must be an https address of a named site$/i, (m) => `Поле «${f(m[1])}»: нужен адрес https на сайт с именем`],
    [/^choose usage terms from the approved list$/i, 'Выберите условия использования из утверждённого списка'],
    [/^enter the laboratory's public name and the author before publishing$/i, 'Перед публикацией укажите публичное название лаборатории и автора'],
    [/^nothing is chosen: choose a laser, a titanium or an experiment with accepted photographs$/i,
      'Ничего не выбрано: выберите лазер, титан или эксперимент с принятыми фотографиями'],
    [/^the release cannot be written: (.*)$/is, (m) => `Выпуск не записан: ${m[1]}`],
  ]);
})();
