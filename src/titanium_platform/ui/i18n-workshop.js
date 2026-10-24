/* Сообщения о самой мастерской (electron REQ-080, REQ-081): резервные копии и восстановление. Загружается перед i18n-gaps.js. */
'use strict';
(() => {
  I18N.add([
    [/^choose the folder the backup is written to$/i, 'Выберите папку, куда записать резервную копию'],
    [/^a backup cannot be written inside the workshop it copies: choose another folder$/i,
      'Резервную копию нельзя записать внутрь той мастерской, которую она копирует: выберите другую папку'],
    [/^not enough free space for the backup: (\d+) MB are needed and (\d+) MB are free$/i,
      (m) => `Недостаточно места для резервной копии: нужно ${m[1]} МБ, свободно ${m[2]} МБ`],
    [/^the copy of the database did not pass the integrity check \((.*)\): the backup was not made$/is,
      (m) => `Копия базы не прошла проверку целостности (${m[1]}): резервная копия не записана`],
    [/^the copy of (.+?) does not match the original: the backup was not made$/i,
      (m) => `Копия файла ${m[1]} не совпадает с оригиналом: резервная копия не записана`],
    [/^this is a laboratory release, not a backup of a workshop: a release is connected on the laboratories screen$/i,
      'Это выпуск лаборатории, а не резервная копия мастерской: выпуск подключается на экране «Лаборатории»'],
    [/^this backup was not finished$/i, 'Эта резервная копия не была завершена'],
    [/^this folder holds no backup of a workshop \(no manifest\)$/i, 'В этой папке нет резервной копии мастерской (нет описания)'],
    [/^the manifest of this backup cannot be read$/i, 'Описание этой резервной копии не читается'],
    [/^the file (.+?) is missing from the backup$/i, (m) => `В резервной копии нет файла ${m[1]}`],
    [/^the file (.+?) has another size than the backup recorded$/i, (m) => `Размер файла ${m[1]} не совпадает с записанным в резервной копии`],
    [/^the file (.+?) does not match the hash the backup recorded$/i, (m) => `Файл ${m[1]} не совпадает с хешем, записанным в резервной копии`],
    [/^choose the folder the workshop is restored into$/i, 'Выберите папку, в которую восстановить мастерскую'],
    [/^a workshop cannot be restored into its own backup: choose another folder$/i,
      'Мастерскую нельзя восстановить в её собственную резервную копию: выберите другую папку'],
    [/^this folder is the open workshop: restoring into it replaces it, which must be chosen explicitly$/i,
      'Эта папка — открытая мастерская: восстановление в неё заменит её, это нужно выбрать явно'],
    [/^the folder is not empty: choose an empty folder, or ask explicitly to replace what is there$/i,
      'Папка не пуста: выберите пустую папку или явно попросите заменить то, что в ней'],
    [/^choose the backup folder$/i, 'Выберите папку резервной копии'],
    // диагностика (diagnostics.py)
    [/^choose the folder the diagnostics file is written to$/i, 'Выберите папку, куда записать файл диагностики'],
    [/^a diagnostics file cannot be written inside the workshop: choose another folder$/i,
      'Файл диагностики нельзя записать внутрь мастерской: выберите другую папку'],
    [/^there is no diagnostics file (.+)$/i, (m) => `Файла диагностики ${m[1]} нет`],
  ]);
})();
