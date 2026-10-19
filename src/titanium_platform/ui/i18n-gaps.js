/* Переводы сообщений, добавленных при закрытии пробелов I-15 (DEC-034): настройки, которых нет в файле LightBurn и которые
   вводит оператор; измеренное пятно линзы; границы контроллера; поле линзы; рамка по сторонам; расчёт настроек по
   закону толщины. Загружается после остальных таблиц. Здесь же — перевод названий, которые сервер хранит по-английски
   и показывает как данные (заголовок матрицы «Material test: …», слои «Power 20.0 x Speed 900»): хранимый текст не
   меняется, переводится только показ (I18N.name). */
'use strict';
(() => {
  // -- названия, которые сервер хранит по-английски (REQ-031): переводится показ, хранимый текст не меняется -------------
  const PARAM = {power: 'Мощность', speed: 'Скорость', frequency: 'Частота', 'q-pulse': 'Q-Pulse', interval: 'Шаг строк', passes: 'Проходы'};
  const UNIT = {kHz: 'кГц', ns: 'нс', 'mm/s': 'мм/с', mm: 'мм'};
  const param = (s) => PARAM[s.toLowerCase()] || s;
  const MODE = {'Calibration plate': 'Калибровочная матрица', 'Laser capability test': 'Тест возможностей лазера',
    'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла', 'Vector job': 'Векторная работа'};
  const units = (s) => s.replace(/(\d)\s+(kHz|ns|mm\/s|mm)(?![\w/])/g, (_, d, u) => `${d} ${UNIT[u]}`);
  const NAMES = [
    // «Material test: Power x Speed · 330 kHz 4 ns · IMG_1234» — заголовок матрицы, прочитанной с фотографии
    [/^Material test: (.+?)( · \d[^·]*)? · ([^·]*)$/, (m) => `Тест материала: ${m[1].split(' x ').map((p) => (p === 'matrix' ? 'матрица' : param(p))).join(' × ')}`
      + `${m[2] ? units(m[2]) : ''} · ${m[3]}`],
    // «Power 20.0 x Speed 900» — слой одной ячейки матрицы; «Cell 2,3» — ячейка без известных осей
    [/^([A-Za-z-]+) (-?[\d.]+)(?: x ([A-Za-z-]+) (-?[\d.]+))?$/, (m) => (PARAM[m[1].toLowerCase()] && (!m[3] || PARAM[m[3].toLowerCase()])
      ? `${param(m[1])} ${m[2]}${m[3] ? ` × ${param(m[3])} ${m[4]}` : ''}` : null)],
    [/^Cell (\d+),(\d+)$/, (m) => `Ячейка ${m[1]},${m[2]}`],
    // вид плана и название платы, которые сервер хранит по-английски: «Calibration plate», «Plate TCE-… (speed 900)»
    [/^(Calibration plate|Laser capability test|Discrete color engraving|Tonal photo engraving|Color-path photo engraving|Restored from file|Vector job)$/,
      (m) => MODE[m[1]]],
    [/^Plate (\S+) \(speed (-?[\d.]+)\)$/, (m) => `Плата ${m[1]} (скорость ${m[2]} мм/с)`],
    [/^waveform$/, () => 'Форма импульса'],                       // осциллограмма, которой не дали названия
    [/^Photo capture \(no rig\)$/, () => 'Съёмка без установки (ранние фотографии)'],   // setup.LEGACY_SETUP_NAME
  ];
  /** Название-данные по-русски, если оно сложено сервером по известному образцу; иначе — как есть, без пометки «без перевода»:
      название работы, которое дал оператор, не переводится. */
  I18N.name = (text) => {
    const s = String(text ?? '');
    for (const [re, to] of NAMES) {
      const m = s.match(re);
      const out = m ? to(m) : null;
      if (out) return out;
    }
    return s;
  };

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
    // край рамки по сторонам (REQ-024, REQ-027)
    [/^The edge of the frame was not found on the (left|right|top|bottom) side: a margin of (\S+)% \((\S+) mm\) is assumed there\.$/i,
      (m) => `Край рамки ${{left: 'слева', right: 'справа', top: 'сверху', bottom: 'снизу'}[m[1].toLowerCase()]} не найден: там принят скрытый край ${m[2]} % (${m[3]} мм)`],
    // настройка по закону толщины от дозы — только с тремя оценками и в пределах измеренных доз (REQ-002)
    [/^the law of this pulse regime has no r2: the confidence of a computed setting is not known$/i,
      'У закона этого режима импульса нет r²: уверенность рассчитанной настройки неизвестна'],
    [/^fewer than two measured cells near this dose: the stability of the colour there is not known$/i,
      'Рядом с этой дозой меньше двух измеренных ячеек: стабильность цвета там неизвестна'],
    [/^no power up to 100 % reaches this dose at the speed and line interval of the nearest measured cell$/i,
      'Ни одна мощность до 100 % не даёт этой дозы при скорости и шаге ближайшей измеренной ячейки'],
    // поле линзы неизвестно: размещение не проверено, а не «помещается» (REQ-018)
    [/^the work field of the lens is unknown: the placement was not checked$/i, 'Поле линзы неизвестно — размещение не проверено'],
  ]);
})();
