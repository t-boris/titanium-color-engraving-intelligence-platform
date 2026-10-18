/* Переводы сообщений, добавленных при закрытии пробелов I-15 (DEC-034): настройки, которых нет в файле LightBurn и которые
   вводит оператор; измеренное пятно линзы; границы контроллера; поле линзы; рамка по сторонам; расчёт настроек по
   закону толщины. Загружается после остальных таблиц. Здесь же — перевод названий, которые сервер хранит по-английски
   и показывает как данные (заголовок матрицы «Material test: …», слои «Power 20.0 x Speed 900»): хранимый текст не
   меняется, переводится только показ (I18N.name). */
'use strict';
(() => {
  const SETTING = {power: 'мощность', frequency: 'частота', speed: 'скорость', 'pulse width': 'длительность импульса',
    'line interval': 'шаг линий', passes: 'число проходов'};
  I18N.add([
    // настройки, которых нет в файле LightBurn (REQ-015, REQ-016)
    [/^the settings of a parameter matrix are corrected in the matrix itself$/i, 'Настройки матрицы параметров исправляются в самой матрице'],
    [/^only power, frequency, speed, pulse width, line interval and passes can be supplied$/i,
      'Ввести можно только мощность, частоту, скорость, длительность импульса, шаг линий и число проходов'],
    [/^the LightBurn file has no layer (-?\d+)$/i, (m) => `В файле LightBurn нет слоя ${m[1]}`],
    [/^the LightBurn layer holds this setting: a value read from the file is never replaced$/i,
      'Эта настройка есть в слое LightBurn: значение из файла никогда не заменяется'],
    // измеренное пятно принадлежит линзе (REQ-019)
    [/^a measured spot diameter belongs to the lens it was measured with: enter it on the lens$/i,
      'Измеренный диаметр пятна принадлежит линзе, с которой его мерили: введите его на вкладке «Линза»'],
    [/^the measured spot diameter must be between (\S+) and (\S+) µm$/i, (m) => `Измеренный диаметр пятна — от ${m[1]} до ${m[2]} мкм`],
    // границы контроллера: только напечатанные или подтверждённые и не оспоренные (REQ-018)
    [/^frequency (\S+) kHz is below Min PWM (\S+) kHz of the laser settings$/i,
      (m) => `Частота ${m[1]} кГц ниже Min PWM ${m[2]} кГц в настройках лазера: проверьте настройки LightBurn`],
    [/^frequency (\S+) kHz is above Max PWM (\S+) kHz of the laser settings$/i,
      (m) => `Частота ${m[1]} кГц выше Max PWM ${m[2]} кГц в настройках лазера: проверьте настройки LightBurn`],
    // поле линзы неизвестно: размещение не проверено, а не «помещается» (REQ-018)
    [/^the work field of the lens is unknown: the placement was not checked$/i, 'Поле линзы неизвестно — размещение не проверено'],
  ]);
})();
