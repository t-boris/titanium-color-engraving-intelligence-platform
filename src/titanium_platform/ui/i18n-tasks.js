/* Задачи гравировки (REQ-020): названия задач, основания и способы измерения метрик, чего не хватает в контексте,
   и перевод сообщений сервера об этом (DEC-034). Сервер присылает ключи (text, chart, lens_unknown…) и английские сообщения;
   подписи к ключам — здесь, сообщения переводит I18N. */
'use strict';
const TaskText = (() => {
  const KIND = {text: 'Надписи', line: 'Линии', fill: 'Заливка', tonal_image: 'Тоновое изображение', color_image: 'Цветное изображение',
    mark: 'Маркировка', cleaning: 'Очистка', deep: 'Глубокая гравировка', relief: '3D-рельеф', cutting: 'Резка'};
  // откуда у слоя задача: выбрана оператором или следует из самого слоя
  const SOURCE = {operator: 'выбрана для слоя', work: 'задача всей работы', plan: 'по плану или плате', layer: 'по слою LightBurn',
    role: 'по роли слоя'};
  const BASIS = {chart: 'по эталонной карте', clean: 'относительно чистого титана этого снимка', as_shot: 'как снято, относительно камеры',
    registration_scale: 'масштаб снимка по совмещению'};
  const METHOD = {layer_mask_median: 'медиана пикселей слоя внутри его маски', grey_to_lightness_bins: 'L* по уровням серого картинки',
    line_profile_peak: 'пик профиля поперёк линии относительно поверхности рядом', line_profile_stations: 'доля точек вдоль линии, где след виден',
    line_profile_threshold: 'ширина профиля поперёк линии выше четверти его контраста', clean_witness_difference: 'разница L* с чистым титаном этого снимка'};
  const METRIC = {lab: 'Цвет', lightness: 'Светлота L*', chroma: 'Насыщенность C*', tonal_profile: 'Тональный профиль', contrast: 'Контраст',
    line_continuity: 'Непрерывность линии', line_visibility: 'Видимые линии', apparent_trace_width: 'Видимая ширина следа',
    line_width_um: 'Ширина линии, мкм', text_legibility: 'Читаемость текста', dimensional_accuracy: 'Точность размеров', depth: 'Глубина',
    relief_height: 'Высота рельефа', cut_through: 'Сквозной рез', kerf_width: 'Ширина пропила'};
  const MISSING = {lens_unknown: 'линза неизвестна', batch_unknown: 'партия титана неизвестна', focus_unknown: 'фокус не записан',
    camera_relative: 'без эталонной карты', unreferenced: 'без привязки к чистому титану', provisional: 'проверка ещё не принята',
    settings_incomplete: 'в файле нет части настроек'};
  const GOAL = {target_lab: 'Целевой цвет (L, a, b)', tonal_note: 'Тональное поведение', line_width_mm: 'Ширина линии, мм',
    text_height_mm: 'Высота букв, мм', legibility_note: 'Требования к читаемости', note: 'Примечание к задаче'};
  return {KIND, SOURCE, BASIS, METHOD, METRIC, MISSING, GOAL};
})();

I18N.add([
  [/^unknown engraving task: /i, 'Неизвестная задача гравировки: '],
  [/^this layer is not in the LightBurn file of the pair$/i, 'Этого слоя нет в файле LightBurn пары'],
  [/^the target colour must be three numbers L, a, b$/i, 'Целевой цвет — три числа L, a, b (L от 0 до 100)'],
  [/^the line width and the text height must be positive numbers of millimetres$/i, 'Ширина линии и высота букв — положительные числа в миллиметрах'],
  [/^a task note must not exceed 500 characters$/i, 'Примечание к задаче — не длиннее 500 символов'],
  [/^the task goals must be a JSON object$/i, 'Цели задачи записаны неверно'],
  // чего фотография не измеряет (REQ-020): метрика показана недоступной с причиной
  [/^line width in micrometres needs a calibrated image scale or an independent measurement/i,
    'Ширина линии в микрометрах требует калиброванного масштаба снимка или независимого измерения; видимая ширина следа — только след на фото в масштабе совмещения'],
  [/^text legibility is not measured from a photograph/i, 'Читаемость текста по фотографии не измеряется: нужна проверка чтения выгравированных символов'],
  [/^dimensional accuracy needs a calibrated image scale or an independent measurement/i,
    'Точность размеров требует калиброванного масштаба снимка или независимого измерения: совмещение само подгоняет геометрию файла к фото'],
  [/^depth needs a physical measurement/i, 'Глубину нужно измерить физически — глубиномером или профилометром; фото поверхности её не показывает'],
  [/^relief height needs a height map or profilometry/i, 'Для высоты рельефа нужна карта высот или профилометрия; фото поверхности её не показывает'],
  [/^a cut through the part needs a physical check of the part/i, 'Сквозной рез проверяется на самой детали; фото поверхности его не показывает'],
  [/^kerf width needs a calibrated image scale or an independent measurement$/i, 'Ширина пропила требует калиброванного масштаба снимка или независимого измерения'],
]);
