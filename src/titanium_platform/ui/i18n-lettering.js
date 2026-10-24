/* Переводы сообщений надписей в работах (feature inscriptions-in-works, DEC-034): шрифты этого компьютера, свои и Google Fonts,
   поля надписи, её операции и причины, по которым надпись не выгравировать. Загружается после остальных таблиц. */
'use strict';
(() => {
  // поля надписи так, как их называет сервер (lettering.FIELD_NAMES)
  const FIELD = {
    'the letter height (mm)': 'Высота букв (мм)', 'the width (%)': 'Ширина (%)', 'the letter spacing (mm)': 'Межбуквенный интервал (мм)',
    'the line spacing (%)': 'Межстрочный интервал (%)', 'the rotation (degrees)': 'Поворот (градусы)', 'the bend (%)': 'Изгиб (%)',
    'the radius (mm)': 'Радиус (мм)', 'the start angle (degrees)': 'Начальный угол (градусы)', 'the place along the path (%)': 'Место на пути (%)',
    'the gap (mm)': 'Зазор (мм)', "the backing's margin (mm)": 'Поле подложки (мм)', "the backing's corner radius (mm)": 'Скругление углов подложки (мм)',
    'the position x (mm)': 'Положение x (мм)', 'the position y (mm)': 'Положение y (мм)', 'the alignment': 'Выравнивание',
    'the layout': 'Расположение', 'the letters on a curve': 'Буквы на кривой', 'the backing': 'Подложка',
    'the switch «inside the circle»': 'Переключатель «внутри круга»', 'the switch «reverse the path»': 'Переключатель «путь в обратную сторону»',
  };
  const field = (s) => FIELD[s] || s;
  const FIELDS = Object.keys(FIELD).map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');

  I18N.add([
    // шрифты (fonts.py)
    [/^there is no font (.+)$/i, (m) => `Шрифта ${m[1]} нет`],
    [/^choose the font of the inscription$/i, 'Выберите шрифт надписи'],
    [/^the font (.+) is not on this computer any more: choose another font$/i, (m) => `Шрифта ${m[1]} больше нет на этом компьютере: выберите другой шрифт`],
    [/^a font file must be TTF, OTF or TTC$/i, 'Файл шрифта должен быть TTF, OTF или TTC'],
    [/^the font file is larger than (\S+) MB$/i, (m) => `Файл шрифта больше ${m[1]} МБ`],
    [/^this file is not a font that can be engraved: it has no outlines or cannot be read$/i,
      'Этот файл — не шрифт, которым можно гравировать: в нём нет контуров букв или его не прочитать'],
    [/^only a font you added can be removed here$/i, 'Удалить здесь можно только шрифт, который вы добавили сами'],
    [/^Google Fonts could not be reached: (.+)$/i, (m) => `Не удалось связаться с Google Fonts: ${m[1]}. Проверьте подключение к интернету`],
    [/^Google Fonts has no family (.+)$/i, (m) => `В Google Fonts нет семейства ${m[1]}`],
    [/^the font (.+) could not be downloaded from Google Fonts: (.+)$/i,
      (m) => `Шрифт ${m[1]} не удалось скачать из Google Fonts: ${m[2]}. Проверьте подключение к интернету`],
    [/^say which Google family to download$/i, 'Укажите, какое семейство Google скачать'],
    [/^say which Google families to download$/i, 'Укажите, какие семейства Google скачать'],
    [/^unknown script (.+)$/i, (m) => `Неизвестная письменность ${m[1]}`],
    [/^unknown kind of font (.+)$/i, (m) => `Неизвестный вид шрифта ${m[1]}`],
    [/^Google fonts are being downloaded already: wait until it ends$/i, 'Шрифты Google уже скачиваются: дождитесь окончания'],
    [/^the font file of (.+) cannot be read any more: choose another font$/i, (m) => `Файл шрифта ${m[1]} больше не читается: выберите другой шрифт`],
    [/^no font is found on this computer: add a font file$/i, 'На этом компьютере не найдено ни одного шрифта: добавьте файл шрифта'],
    // поля надписи (lettering.checked)
    [new RegExp(`^(${FIELDS}) of an inscription must be a number from (\\S+) to (\\S+)$`, 'i'),
      (m) => `${field(m[1])} надписи — число от ${m[2]} до ${m[3]}`],
    [new RegExp(`^(${FIELDS}) of an inscription must be one of (.+)$`, 'i'), (m) => `${field(m[1])} надписи — одно из: ${m[2]}`],
    [new RegExp(`^(${FIELDS}) of an inscription must be true or false$`, 'i'), (m) => `${field(m[1])} надписи — да или нет`],
    [/^the path of an inscription must be a list of at most (\d+) points$/i, (m) => `Путь надписи — список не больше чем из ${m[1]} точек`],
    [/^every point of the path of an inscription must be two numbers \(mm\)$/i, 'Каждая точка пути надписи — два числа (мм)'],
    [/^an inscription must be an object$/i, 'Надпись должна быть объектом'],
    [/^an inscription has no field (.+)$/i, (m) => `У надписи нет поля ${m[1]}`],
    [/^the text of an inscription must be text$/i, 'Текст надписи должен быть текстом'],
    [/^the text of an inscription may have at most (\d+) characters in (\d+) lines$/i,
      (m) => `В тексте надписи — не больше ${m[1]} знаков в ${m[2]} строках`],
    [/^draw the path of the inscription: two points or more$/i, 'Нарисуйте путь надписи: две точки или больше'],
    [/^the colour of an inscription must be a measured colour$/i, 'Цвет надписи должен быть измеренным цветом'],
    [/^the colour of an inscription must be a measured colour of this laser, lens and titanium stock$/i,
      'Цвет надписи должен быть измеренным цветом этого лазера, линзы и партии титана'],
    [/^an inscription is named t1, t2 \.\.\.$/i, 'Надписи называются t1, t2 …'],
    // операции (lettering.operate)
    [/^there is no inscription (.+)$/i, (m) => `Надписи ${m[1]} нет`],
    [/^say what to change in the inscription$/i, 'Укажите, что изменить в надписи'],
    [/^an inscription keeps its name$/i, 'Имя надписи не меняется'],
    [/^unknown inscription operation (.+)$/i, (m) => `Неизвестная операция с надписью ${m[1]}`],
    // почему надпись не выгравировать (lettering._why_not_engraved, text_blocker)
    [/^its font has no letters «(.+)»: choose a font that has them$/i, (m) => `В её шрифте нет букв «${m[1]}»: выберите шрифт, в котором они есть`],
    [/^choose the titanium colour of its letters$/i, 'Выберите цвет титана для её букв'],
    [/^its titanium colour is no longer measured on this laser, lens and titanium stock: choose another$/i,
      'Её цвет титана больше не измерен на этом лазере, линзе и партии титана: выберите другой'],
  ]);
})();
