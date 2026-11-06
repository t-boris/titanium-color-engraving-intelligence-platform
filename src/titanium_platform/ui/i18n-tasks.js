/* Labels for engraving tasks, measurements and missing context (REQ-020). */
'use strict';
const TaskText = (() => {
  const KIND = {text: 'Lettering', line: 'Lines', fill: 'Fill', tonal_image: 'Tonal image', color_image: 'Color image',
    mark: 'Marking', cleaning: 'Cleaning', deep: 'Deep engraving', relief: '3D relief', cutting: 'Cutting'};
  const SOURCE = {operator: 'selected for the layer', work: 'whole work', plan: 'from the plan or plate',
    layer: 'from the LightBurn layer', role: 'from the layer role'};
  const BASIS = {chart: 'reference chart corrected', clean: 'relative to clean titanium in this photo',
    as_shot: 'as photographed, relative to the camera', registration_scale: 'image scale from alignment'};
  const METHOD = {layer_mask_median: 'median layer pixels within the mask', grey_to_lightness_bins: 'L* by image gray level',
    line_profile_peak: 'cross-line profile peak relative to nearby surface', line_profile_stations: 'fraction of positions with a visible line',
    line_profile_threshold: 'cross-line profile width above one-quarter contrast',
    clean_witness_difference: 'L* difference from clean titanium in this photo'};
  const METRIC = {lab: 'Color', lightness: 'Lightness L*', chroma: 'Chroma C*', tonal_profile: 'Tonal profile', contrast: 'Contrast',
    line_continuity: 'Line continuity', line_visibility: 'Visible lines', apparent_trace_width: 'Apparent trace width',
    line_width_um: 'Line width, µm', text_legibility: 'Text legibility', dimensional_accuracy: 'Dimensional accuracy', depth: 'Depth',
    relief_height: 'Relief height', cut_through: 'Cut-through', kerf_width: 'Kerf width'};
  const MISSING = {lens_unknown: 'lens unknown', batch_unknown: 'titanium batch unknown', focus_unknown: 'focus not recorded',
    camera_relative: 'no reference chart', unreferenced: 'no clean titanium reference', provisional: 'review not yet accepted',
    settings_incomplete: 'some settings are missing from the file'};
  const GOAL = {target_lab: 'Target color (L, a, b)', tonal_note: 'Tonal behavior', line_width_mm: 'Line width, mm',
    text_height_mm: 'Letter height, mm', legibility_note: 'Legibility requirements', note: 'Task note'};
  return {KIND, SOURCE, BASIS, METHOD, METRIC, MISSING, GOAL};
})();
