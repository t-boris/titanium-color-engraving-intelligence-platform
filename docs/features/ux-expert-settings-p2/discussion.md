# Discussion — [P2] Плотность, технические справки и калибровка

### Answer to Q-001 · 2026-11-06

Нужен ли выпускаемый светлый вариант темы после проверки на рабочем освещении и планшете?

A. Сначала сравнить читаемость и действия на реальных условиях, затем решить о выпуске светлой темы.

### Implementation · 2026-11-06

Work in progress: REQ-003 technical data grouping already exists in 3641c79, with route coverage in tests/test_device_navigation_ui.py. REQ-002 grid and REQ-001 density controls are being implemented on feature/ux-expert-settings; criteria remain unticked pending verification. DEC-001 comparison under workshop lighting and on a tablet remains outstanding.

### Implementation · 2026-11-06

REQ-002 implemented: 24 Lab patches in row-major order, per-field validation, JSON exchange, source and white point, and published reset. Tests cover invalid input, payload round-trip and accepted observations surviving reference changes. REQ-003 was already implemented and its routes are covered. Density setting and persistence are implemented, but REQ-001 remains open: full real-interface and tablet checks, an experimental light variant and the DEC-001 workshop comparison have not been performed. Chrome access host was unavailable. No results for lighting, tablet, Electron or before/after performance are claimed.
