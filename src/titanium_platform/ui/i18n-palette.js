/* Переводы сообщений о времени гравировки и о цветах векторной работы (REQ-034, REQ-035, REQ-042, DEC-073..DEC-077, DEC-034):
   почему время рецепта не оценить, фильтр по времени и допуск ΔE карты цветов, палитра лазера, линзы и заготовки,
   перекраска исходных цветов, разбиение фотографии и файл LightBurn. Загружается после остальных таблиц, но до
   i18n-gaps.js. Числа приходят как есть. */
'use strict';
(() => {
  I18N.add([
    // оценка времени гравировки рецепта (REQ-035, DEC-075)
    [/^the speed of this recipe is not recorded: its engraving time is not known$/i, 'Скорость этого рецепта не записана — время гравировки не оценить'],
    [/^the line interval of this recipe is not recorded: its engraving time is not known$/i, 'Шаг строк этого рецепта не записан — время гравировки не оценить'],
    [/^the sub-layers of this recipe are not counted in its time$/i, 'Подслои этого рецепта во время не включены'],
    [/^how much this layer engraves is not given$/i, 'Не задано, сколько гравирует этот слой (площадь или длина линий)'],
    [/^the longest engraving time per square centimetre must be a positive number of seconds$/i,
      'Наибольшее время гравировки на см² — положительное число секунд'],
    [/^the delta E tolerance must be a non-negative number$/i, 'Допуск ΔE — неотрицательное число'],
    // палитра векторной работы и перекраска (REQ-034, DEC-073, DEC-074)
    [/^each source colour needs its index, a Lab colour and a pixel count$/i, 'У каждого исходного цвета должны быть номер, цвет Lab и число пикселей'],
    [/^a kept choice names a source colour that is not given$/i, 'Закреплённый выбор относится к исходному цвету, которого нет'],
    [/^a kept choice names a colour that is not in the palette of this laser, lens and titanium stock$/i,
      'Закреплённый выбор указывает цвет, которого нет в палитре этого лазера, линзы и заготовки титана'],
    [/^the recolouring mode must be closest, tonality, random or fewer_layers$/i,
      'Способ перекраски: ближайший, с сохранением тональности, случайный или меньше слоёв'],
    [/^give the source colours to recolour$/i, 'Укажите исходные цвета для перекраски'],
    [/^at most (\d+) colours: the cleaning layer comes first and LightBurn has 30 layers$/i,
      (m) => `Не больше ${m[1]} цветов: первым идёт слой очистки, а слоёв в LightBurn 30`],
    [/^two source colours have the same index$/i, 'У двух исходных цветов одинаковый номер'],
    [/^no measured colour of this laser, lens and titanium stock fills an area$/i,
      'У этого лазера, линзы и заготовки титана нет измеренного цвета заливки'],
    [/^no colour of the palette engraves within (\S+) s per square centimetre$/i,
      (m) => `Ни один цвет палитры не гравируется быстрее ${m[1]} с на см²`],
    [/^set the delta E tolerance: none is saved for this laser and lens$/i,
      'Задайте допуск ΔE: для этого лазера и линзы он не сохранён'],
    [/^every colour of the palette was measured as photographed: include such colours to colour automatically$/i,
      'Все цвета палитры сняты без привязки к эталону: чтобы раскрасить автоматически, включите цвета без привязки'],
    // фотография, разбитая на цветные области (REQ-042, DEC-073, DEC-076)
    [/^choose from (\d+) to (\d+) colours: the cleaning takes one LightBurn layer( and the markers another)?$/i,
      (m) => `Выберите от ${m[1]} до ${m[2]} цветов: один слой LightBurn занимает чистка` + (m[3] ? ', ещё один — маркеры' : '')],
    [/^the level of detail must be coarse, medium or fine$/i, 'Детальность: крупно, средне или детально'],
    [/^the smoothing must be a non-negative number of millimetres$/i, 'Сглаживание — неотрицательное число миллиметров'],
    [/^an important area must be an ellipse or a polygon of finite numbers in picture pixels$/i,
      'Важная область — эллипс или многоугольник в пикселях картинки'],
    [/^a removed area must be one of the areas found in the picture$/i, 'Убрать можно только область, найденную на картинке'],
    [/^the split settings must be an object$/i, 'Настройки разбиения переданы неверно'],
    [/^only a photograph split into colour regions is split and coloured this way$/i,
      'Так разбивается и раскрашивается только фотография, разбитая на цветные области'],
    [/^a photograph split into colour regions is changed by splitting it again and by its colouring$/i,
      'Фотографию, разбитую на цветные области, меняют новым разбиением и раскраской'],
    [/^there is no such source colour$/i, 'Такого исходного цвета нет'],
    [/^the titanium colour must be a measured colour of this laser, lens and titanium stock$/i,
      'Цвет титана — один из измеренных цветов этого лазера, линзы и заготовки титана'],
    [/^there is no earlier colouring to go back to$/i, 'Нет более ранней раскраски, к которой можно вернуться'],
    [/^there is no such variant of the colouring$/i, 'Такого варианта раскраски нет'],
    [/^there is no proposed titanium colour to accept$/i, 'Нет предложенного цвета титана, который можно принять'],
    [/^(\d+) colour\(s\) in (\d+) region\(s\) have no titanium colour within the delta E tolerance: accept the proposed colour, choose another or exclude it before export$/i,
      (m) => `Цветов без цвета титана в пределах допуска ΔE: ${m[1]} (областей: ${m[2]}). Примите предложенный цвет, выберите другой или исключите цвет — тогда экспорт станет доступен`],
    [/^(\d+) region\(s\) have a titanium colour that is no longer measured on this laser, lens and titanium stock: choose another before export$/i,
      (m) => `Областей с цветом титана, которого больше нет среди измерений этого лазера, линзы и заготовки: ${m[1]}. Выберите для них другой цвет перед экспортом`],
  ]);
})();
