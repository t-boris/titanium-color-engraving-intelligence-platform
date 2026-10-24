---
type: feature
id: vector-detail-and-colour-control
title: Vector Detail and Colour Control
status: implementing
owner: Boris Tsekinovsky
created: 2026-10-19
provenance: Created from the quick feature intake
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: known
  Permissions: n/a
  Failure Scenarios: known
  Data Model: known
  Notifications: known
  Security: n/a
  Analytics: n/a
  Dependencies: partial
  Acceptance Criteria: known
intake: quick
questions_left: 0
issue: "#32"
understanding_notes:
  Problem: "Запрос определяет проблемы: слишком много областей, угловатые границы, недостаточный контроль глаз и раскраски."
  Target Users: Оператор лазерной мастерской, готовящий фотографии для цветной гравировки титана.
  Primary Workflow: Решениями закреплены выбор алгоритма, единое пространство с центральным изображением и сохранение порядка светлоты в Artistic. Повторно спрашивать об объединении экранов не требуется.
  Permissions: Новые роли и права доступа в рамках функции не заявлены.
  Failure Scenarios: Документы определяют ограничения палитры, сохранение ручных назначений, пропущенные глаза, исключённые области и сброс при пересоздании. Остальные граничные случаи решаются при реализации и проверке.
  Data Model: Код уже хранит версии геометрии, назначения цветов и историю; план требует сохранять исходную информацию после автоматического объединения. Технические расширения определяет исполнитель.
  Notifications: Предусмотрено предупреждение о сбросе раскраски и вариантов перед явным пересозданием.
  Security: Новых требований безопасности не заявлено; обязательное подключение внешнего AI-сервиса не предусмотрено.
  Analytics: Отдельная продуктовая аналитика для этой функции не требуется.
  Dependencies: Код подтверждает SLIC, измеренную палитру, ручную раскраску и объединение областей. Дополнительные алгоритмы ещё предстоит выбрать и проверить; ответа владельца продукта для этого не нужно.
  Acceptance Criteria: Спецификацию можно завершить без новых ответов. Критерии уже описывают плотность, глаза, гладкость, раскраску, объединение, историю и экспорт; выбор алгоритмов и компоновка дополнительно закреплены решениями и планом.
---

# Vector Detail and Colour Control

## Idea

Extend photo Vector Work with adjustable region density, smoother shared contours, independent eye detail, measured-palette colouring and automatic removal of redundant same-recipe boundaries.

## Problem

The operator reports excessive regions, angular transitions and insufficient control over eyes and colour composition. Existing controls and manual merging only partially address this workflow.

## Scope

Photo-to-colour-region vector work in Laser Workshop: segmentation controls, eye-area editing, shared-border smoothing, palette interaction, Contrast and Artistic recolouring, automatic adjacent-region merging, preview/history/export integration, and navigation placement.

## Analysis

Existing implementation: `src/titanium_platform/ui/screens/vector-split.js` exposes colour count, three detail presets, smoothing in millimetres and removable/addable important areas. `src/titanium_platform/vector_job.py` maps detail to superpixel density and minimum region area; rebuilding resets colouring, variants and undo history. `src/titanium_platform/segment.py` already smooths shared borders using Gaussian filtering, Douglas–Peucker simplification and Chaikin rounding; eyes, lips and manual areas share a fixed finer-detail level. It does not expose independent eye overrides. `src/titanium_platform/ui/screens/vector-editor.js` already provides measured-colour painting, selection, manual region/colour merges and undo/redo. `src/titanium_platform/palette.py` implements Closest, Tonality, Random and Fewer Layers, without Contrast or Artistic modes. Automatic same-recipe geometry merging was not found. `src/titanium_platform/ui/router.js` currently places Vector Work sixth. Documentation: `docs/features/vector-work-colour-editor/requirements/REQ-044.md`–`REQ-049.md` define the existing editor; its overview explicitly excludes split changes, so this proposal extends that scope. Its `decisions/DEC-001.md` supersedes the older REQ-042 acceptance gate for out-of-tolerance photo colours.

## Assumptions

Made by the AI where the request left a choice open; correct them in the discussion.

- «Насыщенность векторов» трактуется как плотность геометрических областей, независимо от количества цветов и цветовой насыщенности.
- Настройка глаз применяется к каждому глазу отдельно; редактирование означает изменение границы важной области, детализации и цвета, без полноценного редактора узлов.
- AI-перекраска означает интеллектуальный подбор вариантов; внешний генеративный сервис не обязателен. Contrast оптимизирует различимость соседей.
- Автоматические режимы действуют на всю работу и сохраняют ручной выбор, согласно существующему DEC-075.
- Объединение определяется совпадением рецепта и настроек, а не только похожим экранным цветом; после слияния внутренняя граница восстанавливается отменой операции.
- Новые настройки разбиения сохраняют существующий сценарий явного пересоздания с предупреждением о сбросе раскраски.

## Acceptance Criteria

- [x] Navigation starts with Experiments, Color Map, Vector Work; existing vector-work URLs remain valid.
- [x] Global density can be decreased or increased independently of the source-colour count. Preview shows the resulting region count; a detailed reference image produces fewer regions at low density than at high density with other settings unchanged.
- [x] Each detected or manually marked eye has its own detail override and editable boundary. Changing an eye override preserves geometry outside that boundary; missing detections can be added manually.
- [x] Smoothing produces continuous tangents along curved boundaries except at intentional corners and multi-region junctions. Shared borders remain identical, holes survive, and rasterized uncovered and doubly covered areas each remain below 0.5%. Export preserves the previewed geometry.
- [x] Selecting a region exposes every eligible measured palette colour for the selected laser, lens and titanium. Applying a colour updates that region, its recipe, layer count and time estimate.
- [x] Contrast and Artistic modes produce previewable, reproducible whole-work variants using eligible recipes and existing filters, preserving manual choices. Contrast improves the shared-border-length-weighted mean ΔE between neighbouring regions over Closest on a reference fixture; Artistic offers distinct seeded hue arrangements within a chosen measured palette subset while preserving the source image's lightness order for automatically assigned colours.
- [x] After colouring, each connected component of included regions sharing a border and the same recipe becomes one region without internal seams. Holes remain; corner-touching, disconnected, excluded or differently configured regions stay separate.
- [x] Recolouring and its automatic merges form one undoable operation. Density and eye changes require an explicit rebuild with a notice that colouring and variants reset; the smoothness of borders is a live slider that redraws the picture without resetting anything (REQ-052). Reload and LightBurn export retain the accepted result and existing layer limits.
