/* Переводы сообщений о времени гравировки и о цветах векторной работы (REQ-034, REQ-035, DEC-073..DEC-075, DEC-034):
   почему время рецепта не оценить, фильтр по времени и допуск ΔE карты цветов, палитра лазера, линзы и заготовки и
   перекраска исходных цветов. Загружается после остальных таблиц, но до i18n-gaps.js. Числа приходят как есть. */
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
  ]);
})();
