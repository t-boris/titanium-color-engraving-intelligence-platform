"""Generate hardware-linked titanium test plates from a laser passport.

The operator chooses the physical laser, titanium stock and a plate type. The profile row used by the
existing learning pipeline is created or reused internally as the identity of that laser/lens pair;
no process settings are saved on it.
"""
from __future__ import annotations

import json
import math
from typing import Any

from . import devices, lenses, plans, profiles as pf
from .db import Store, now

PLATE_TYPES = [
    {"id": "small_patches", "name": "Малые квадраты · 1–4 пробы",
     "purpose": "Быстро проверить один режим или сравнить до четырёх режимов заливки, расходуя минимум площади материала.",
     "action": "Один–четыре квадрата размером 3–5 мм с зазором 0,8 мм. Каждый квадрат имеет собственный слой и полный набор параметров. Можно добавить QR и четыре регистрационные метки для автоматического совмещения фото. Первым слоем локально очищаются квадраты и, если есть, метки.",
     "finds": "Отклик, равномерность и различия между выбранными режимами заливки на этой заготовке. Для надписей, линий и глубины нужны отдельные образцы."},
    {"id": "compact_capability", "name": "Компактная комплексная проверка",
     "purpose": "За один небольшой опыт проверить базовый отклик линий и заливок, минимальный разнос линий, wobble и отклик надписей разного размера.",
     "action": "28 выходных слоёв теста: 16 сочетаний мощности и скорости, 4 реперные частоты, десять групп зазора линий в одном слое, 3 уровня wobble, 3 интервала заливки и 5 размеров текста в одном слое. Вместе с очисткой и регистрацией файл занимает ровно 30 обычных выходных слоёв LightBurn.",
     "finds": "Компактный обзор видимости линий, частотного диапазона, слияния дорожек, влияния wobble, интервала Scan и отклика пяти размеров текста. Читаемость отдельных символов этим измерением пока не подтверждается. Частота проверяется на CW, если оно есть в паспорте. Это предварительный отбор; полные сетки частоты и wobble запускаются отдельными компактными платами."},
    {"id": "calibration", "name": "Калибровочная матрица",
     "purpose": "Получить базовую картину отклика именно этой заготовки титана и найти диапазоны, где лазер оставляет заметный след.",
     "action": "24 заливочные ячейки: 4 реперных уровня мощности × 6 частот вокруг выбранной частоты. Скорость, Q-Pulse и шаг заливки остаются заданными; очистка и метки занимают ещё два слоя.",
     "finds": "Порог появления следа, влияние мощности и частоты, а также зоны слабой или чрезмерной обработки. Это матрица отклика, не карта готовых цветов."},
    {"id": "material_matrix", "name": "Матрица двух параметров (Material Test)",
     "purpose": "Сравнить контролируемую сетку сочетаний двух выбранных параметров лазера на одной заготовке титана.",
     "action": "Матрица до 28 ячеек: две оси выбираются из мощности, скорости, частоты, Q-Pulse, интервала линий, проходов и диаметра wobble (0 = выключен). Геометрия: линия, заливка, заполненные буквы либо однолинейные векторные буквы A8M B012 высотой 2 и 4 мм с повторением. Для wobble задаётся постоянный шаг. Очистка, метки и ячейки входят в один LightBurn-файл до 30 выходных слоёв.",
     "finds": "Влияние выбранной пары параметров на одинаковую геометрию; при wobble — сравнение с контролем OFF. Фото даёт предварительный отклик, а читаемость, кромку и глубину проверяют на изделии."},
    {"id": "text_readability", "name": "Компактный тест надписей",
     "purpose": "Сравнить режимы именно на буквах и цифрах, а не переносить результат одиночной линии на текст.",
     "action": "9 групп: 3 мощности × 3 скорости. В каждой группе три одинаковых образца A8M высотой 1 / 1,5 / 2 мм. Остальные параметры фиксированы; чистка идёт первой. Размер платы около 52 × 49 мм с метками.",
     "finds": "Отклик мелких и крупных символов при смене мощности и скорости. Контраст на RAW — предварительный сигнал; окончательную читаемость и качество кромок нужно оценить по фото и самому изделию."},
    {"id": "power_speed", "name": "Предел мощности и скорости",
     "purpose": "Понять, при каких сочетаниях мощности и скорости линия становится видимой и сохраняет непрерывность.",
     "action": "28 длинных одиночных векторных линий: 4 уровня мощности × 7 скоростей; частота и длительность импульса фиксированы. Это максимальная сетка, которая помещается в 30 выходных слоёв вместе с очисткой и метками.",
     "finds": "Нижний порог следа и примерный рабочий диапазон галво по скорости. Это практический тест на выбранной длине линии, не измерение паспортного максимума скорости."},
    {"id": "frequency", "name": "Частотный диапазон",
     "purpose": "Проверить, как повторение импульсов влияет на результат при одной мощности, скорости и длительности импульса.",
     "action": "Отдельная линия для каждой тестовой частоты из диапазона лазера; если паспорт содержит CW, выбирается эта ступень, чтобы пройти частоты выше среза.",
     "finds": "Частоты, на которых след устойчивый, слабый или меняется; помогает проверить заявленный диапазон повторения на титане."},
    {"id": "pulse_cutoff", "name": "Длительность импульса и частота среза",
     "purpose": "Проверить, как длительность импульса и паспортная частота среза связаны с фактическим следом.",
     "action": "До 9 равномерно выбранных импульсных ступеней проверяются на 0,8×, 1× и 1,2× частоты среза; если есть CW, добавляется контрольная линия. Подвыборка нужна, чтобы файл вместе с очисткой и метками не превысил 30 выходных слоёв LightBurn.",
     "finds": "Где меняется выраженность следа около среза и насколько поведение выбранного лазера соответствует его таблице частот."},
    {"id": "line_resolution", "name": "Ширина дорожки и разрешение",
     "purpose": "Оценить минимальный разнос, при котором соседние следы на этой заготовке остаются различимыми.",
     "action": "10 групп по 5 параллельных векторных линий с заданным промежутком от 20 до 300 мкм.",
     "finds": "При каком промежутке линии начинают сливаться и какова наблюдаемая ширина дорожки. По этому тесту нельзя напрямую объявить оптический диаметр пятна."},
    {"id": "hatch_interval", "name": "Шаг заливки",
     "purpose": "Выбрать подходящий интервал штриховки для заполненных участков.",
     "action": "5 небольших квадратов в режиме обычной заливки Scan с интервалами 0,01 / 0,025 / 0,05 / 0,1 / 0,2 мм.",
     "finds": "Насколько равномерно покрывается поверхность, видны ли пропуски или чрезмерное перекрытие и как меняется след при уплотнении штрихов."},
    {"id": "offset_fill", "name": "Контурная заливка (Offset Fill)",
     "purpose": "Оценить отдельный режим заполнения, в котором траектории идут по контуру фигуры, и сравнить его с обычной заливкой.",
     "action": "12 квадратов в режиме Offset Fill: 3 скорости × 4 интервала заливки. Скорости сравниваются при одинаковой мощности, частоте и Q-Pulse.",
     "finds": "Как скорость и плотность контурных траекторий влияют на непрерывность и равномерность следа; результат применим к фигурам с заливкой по контуру."},
    {"id": "wobble", "name": "Wobble: шаг и размер окружности",
     "purpose": "Понять, как wobble меняет ширину и выраженность следа на выбранной марке титана.",
     "action": "9 небольших заполненных образцов: 3 значения Step × 3 значения Size; LightBurn Wobble включён только на этих слоях.",
     "finds": "Как шаг между центрами окружностей и их диаметр влияют на видимый след. Это наблюдаемая ширина гравировки, а не оптический диаметр пятна."},
]
for item in PLATE_TYPES:
    item["description"] = f"Зачем: {item['purpose']} Что делает плата: {item['action']} Что выясняет результат: {item['finds']}"
TYPE_BY_ID = {item["id"]: item for item in PLATE_TYPES}

# The user's established clean-first recipe. Values are adapted only when a selected laser passport
# does not support the exact frequency or pulse step.
CLEAN_DEFAULTS = {"power": 20.0, "frequency": 48.0, "speed": 2000.0, "pulse_width": 200.0,
                  "line_interval": 0.05, "passes": 1}
LABEL_DEFAULTS = {"power": 25.0, "frequency": 60.0, "speed": 150.0, "pulse_width": 200.0,
                  "line_interval": 0.01, "passes": 1}
DEFAULT_TEST = {"power": 20.0, "frequency": 48.0, "speed": 900.0, "pulse_width": 200.0,
                "line_interval": 0.025, "passes": 1, "global_passes": 1}
SPEEDS_MM_S = (500, 1000, 1500, 2000, 3000, 5000, 7500, 10000)
FREQUENCIES_KHZ = (1, 5, 10, 20, 30, 40, 48, 60, 80, 100, 150, 200, 300, 500, 800, 1200, 1600, 1950, 2000, 3000, 4000)
CALIBRATION_POWERS = (5, 20, 50, 100)
CALIBRATION_FREQUENCY_FACTORS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
HATCH_INTERVALS_MM = (0.01, 0.025, 0.05, 0.1, 0.2)
OFFSET_FILL_INTERVALS_MM = (0.025, 0.05, 0.1, 0.2)
LINE_SPACINGS_UM = (20, 30, 40, 50, 60, 80, 100, 150, 200, 300)
COMPACT_POWERS = (5, 20, 50, 100)
COMPACT_SPEEDS = (500, 1500, 5000, 10000)
COMPACT_FREQUENCY_POINTS = 4
COMPACT_WOBBLE_POINTS = ((0.025, 0.05), (0.05, 0.1), (0.1, 0.2))
COMPACT_HATCH_INTERVALS_MM = (0.025, 0.05, 0.2)
COMPACT_TEXT_HEIGHTS_MM = (0.8, 1.1, 1.5, 2.0, 2.5)
WOBBLE_STEPS_MM = (0.025, 0.05, 0.1)
WOBBLE_SIZES_MM = (0.05, 0.1, 0.2)
COMPACT_MARKER_SIZE = {"aruco_mm": 4.0, "qr_module_mm": 0.25, "margin_mm": 0.5,
                       "qr_position": "top-right"}
MATRIX_AXES = {
    "power": {"label": "Power", "short": "P", "unit": "%", "default_min": 5, "default_max": 100},
    "speed": {"label": "Speed", "short": "V", "unit": "mm/s", "default_min": 500, "default_max": 10000},
    "frequency": {"label": "Frequency", "short": "F", "unit": "kHz", "default_min": 24, "default_max": 96},
    "pulse_width": {"label": "Q-Pulse", "short": "PW", "unit": "ns", "default_min": 2, "default_max": 500},
    "line_interval": {"label": "Line interval", "short": "I", "unit": "mm", "default_min": 0.01, "default_max": 0.2},
    "passes": {"label": "Passes", "short": "N", "unit": "", "default_min": 1, "default_max": 5},
    "wobble_size": {"label": "Wobble diameter", "short": "W", "unit": "mm", "default_min": 0, "default_max": 0.08},
}

# Each glyph is a set of open, single-stroke polylines in a 2.5 × 5 unit box.
# Keeping them as paths (rather than filling pixel rectangles) lets LightBurn apply wobble to
# the same centreline at every matrix setting.
VECTOR_GLYPHS = {
    "A": (((0, 5), (1.25, 0), (2.5, 5)), ((0.5, 3), (2, 3))),
    "8": (((0.4, 0), (2.1, 0), (2.5, 0.6), (2.5, 1.8), (1.25, 2.5), (0, 1.8), (0, 0.6), (0.4, 0)),
          ((1.25, 2.5), (2.5, 3.2), (2.5, 4.4), (2.1, 5), (0.4, 5), (0, 4.4), (0, 3.2), (1.25, 2.5))),
    "M": (((0, 5), (0, 0), (1.25, 2.5), (2.5, 0), (2.5, 5)),),
    "B": (((0, 5), (0, 0), (1.8, 0), (2.5, 0.7), (2.5, 1.7), (1.8, 2.5), (0, 2.5)),
          ((1.8, 2.5), (2.5, 3.3), (2.5, 4.3), (1.8, 5), (0, 5))),
    "0": (((0.5, 0), (2, 0), (2.5, 0.7), (2.5, 4.3), (2, 5), (0.5, 5), (0, 4.3), (0, 0.7), (0.5, 0)),),
    "1": (((0.3, 1), (1.25, 0), (1.25, 5)), ((0.3, 5), (2.3, 5))),
    "2": (((0, 0.8), (0.6, 0), (1.9, 0), (2.5, 0.8), (2.5, 1.8), (0, 5), (2.5, 5)),),
}

FONT = {
    "A": "010/101/111/101/101", "B": "110/101/110/101/110", "C": "011/100/100/100/011",
    "D": "110/101/101/101/110", "E": "111/100/110/100/111", "F": "111/100/110/100/100",
    "G": "011/100/101/101/011", "H": "101/101/111/101/101", "I": "111/010/010/010/111",
    "J": "001/001/001/101/010", "K": "101/101/110/101/101", "L": "100/100/100/100/111",
    "M": "101/111/111/101/101", "N": "101/111/111/111/101", "O": "010/101/101/101/010",
    "P": "110/101/110/100/100", "Q": "010/101/101/111/011", "R": "110/101/110/101/101",
    "S": "011/100/010/001/110", "T": "111/010/010/010/010", "U": "101/101/101/101/111",
    "V": "101/101/101/101/010", "W": "101/111/111/111/101", "X": "101/101/010/101/101",
    "Y": "101/101/010/010/010", "Z": "111/001/010/100/111",
    "0": "111/101/101/101/111", "1": "010/110/010/010/111", "2": "110/001/010/100/111",
    "3": "110/001/010/001/110", "4": "101/101/111/001/001", "5": "111/100/110/001/110",
    "6": "011/100/110/101/010", "7": "111/001/010/010/010", "8": "010/101/010/101/010",
    "9": "010/101/011/001/110", "-": "000/000/111/000/000", ".": "000/000/000/000/010",
    "/": "001/001/010/100/100", "%": "101/001/010/100/101", "+": "000/010/111/010/000",
}


def _text(text: str, x: float, y: float, pixel: float = 0.22) -> list[dict]:
    pixel *= 1.45
    pitch = pixel * 1.35
    out = []
    for ci, ch in enumerate(text.upper()):
        glyph = FONT.get(ch)
        if not glyph:
            continue
        for ry, row in enumerate(glyph.split("/")):
            for rx, on in enumerate(row):
                if on == "1":
                    out.append({"kind": "rect", "x": x + ci * pitch + rx * pixel, "y": y + ry * pixel,
                                "width": pixel, "height": pixel})
    return out


def _line(x1: float, y1: float, x2: float, y2: float) -> dict:
    return {"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "x": min(x1, x2), "y": min(y1, y2), "width": abs(x2 - x1), "height": abs(y2 - y1)}


def _vector_text(text: str, x: float, y: float, height: float) -> list[dict]:
    """Draw genuinely open vector centrelines, scaled to an exact glyph height in mm."""
    unit = height / 5
    regions = []
    cursor = x
    for char in text.upper():
        if char == " ":
            cursor += 2.1 * unit
            continue
        for stroke in VECTOR_GLYPHS.get(char, ()):
            for start, end in zip(stroke, stroke[1:]):
                regions.append(_line(cursor + start[0] * unit, y + start[1] * unit,
                                     cursor + end[0] * unit, y + end[1] * unit))
        cursor += 3.1 * unit
    return regions


def _rect(x: float, y: float, width: float, height: float) -> dict:
    return {"kind": "rect", "x": x, "y": y, "width": width, "height": height}


def _nearest(steps: list[dict], preferred: float) -> float:
    values = [float(step["pulse_width_ns"]) for step in steps]
    return min(values, key=lambda v: (abs(v - preferred), v))


def _evenly_spaced(items: list[dict], limit: int) -> list[dict]:
    """Choose deterministic, endpoint-preserving passport samples for a layer-limited plate."""
    if len(items) <= limit:
        return items
    if limit <= 1:
        return [items[len(items) // 2]]
    indexes = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
    return [items[i] for i in indexes]


def _clamp(value: float, bounds: dict) -> float:
    return min(max(float(value), float(bounds["min"])), float(bounds["max"]))


def _process(values: dict, profile_id: int) -> dict:
    p = {k: values[k] for k in ("power", "frequency", "speed", "pulse_width", "line_interval", "passes")}
    p["profile_id"] = profile_id
    return p


def _layer(index: int, name: str, p: dict, regions: list[dict], *, mode: str = "Cut",
           cross_hatch: bool = False, bidirectional: bool = True, line_interval: float | None = None,
           global_passes: int = 1, wobble_enabled: bool = False, wobble_step: float = 0.05,
           wobble_size: float = 0.1) -> dict:
    params = dict(p)
    if line_interval is not None:
        params["line_interval"] = line_interval
    return {"index": index, "name": name, "parameters": params, "regions": regions,
            "cell_id": name, "cut_type": mode,
            "lightburn_settings": {"global_passes": global_passes, "bidirectional": bidirectional,
                                   "cross_hatch": cross_hatch, "scan_angle": 0.0, "angle_increment": 0.0,
                                   "wobble_enabled": wobble_enabled, "wobble_step": wobble_step,
                                   "wobble_size": wobble_size},
            "prediction": None, "knowledge_id": None, "stage": None, "questioned": False}


def _passport_defaults(passport: dict, supplied: dict) -> tuple[dict, dict, dict]:
    repetition = passport["repetition_rate_khz"]
    steps = passport["pulse_steps"]
    selectable = [float(s["pulse_width_ns"]) for s in steps]
    values = {**DEFAULT_TEST, **supplied}
    values["power"] = pf._finite(values["power"], "мощность")
    if not 0 < values["power"] <= 100:
        raise pf.ValidationError("мощность должна быть больше 0 и не выше 100%")
    values["frequency"] = pf._finite(values["frequency"], "частота", True)
    if not repetition["min"] <= values["frequency"] <= repetition["max"]:
        raise pf.ValidationError(f"частота должна быть в диапазоне {repetition['min']:g}–{repetition['max']:g} кГц для выбранного лазера")
    values["speed"] = pf._finite(values["speed"], "скорость", True)
    if values["speed"] > 10000:
        raise pf.ValidationError("скорость теста не должна превышать 10000 мм/с")
    values["pulse_width"] = pf._finite(values["pulse_width"], "длительность импульса", True)
    if values["pulse_width"] not in selectable:
        raise pf.ValidationError("выбранной длительности импульса нет в паспорте лазера")
    values["line_interval"] = pf._finite(values["line_interval"], "шаг линий", True)
    if values["line_interval"] > 1:
        raise pf.ValidationError("шаг линий должен быть не больше 1 мм")
    for key in ("passes", "global_passes"):
        n = values[key]
        if isinstance(n, bool) or int(n) != n or not 1 <= n <= 20:
            raise pf.ValidationError(f"{key}: укажите целое число от 1 до 20")
        values[key] = int(n)
    clean = dict(CLEAN_DEFAULTS)
    clean["frequency"] = _clamp(clean["frequency"], repetition)
    clean["pulse_width"] = _nearest(steps, clean["pulse_width"])
    label = dict(LABEL_DEFAULTS)
    label["frequency"] = _clamp(label["frequency"], repetition)
    label["pulse_width"] = _nearest(steps, label["pulse_width"])
    return values, clean, label


def _calibration(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    powers = CALIBRATION_POWERS
    rate = passport["repetition_rate_khz"]
    lo, hi = max(rate["min"], values["frequency"] * 0.5), min(rate["max"], values["frequency"] * 2)
    freqs = sorted({round(max(lo, min(hi, values["frequency"] * factor)), 2)
                    for factor in CALIBRATION_FREQUENCY_FACTORS})
    cell, gap, x0, y0 = 5.0, 0.6, 13.0, 12.0
    labels = _text("CALIBRATION POWER X FREQUENCY", 4, 2, 0.22)
    layers = []
    cells = []
    idx = 1
    for row, frequency in enumerate(freqs):
        labels += _text(f"F{frequency:g}", 2.0, y0 + row * (cell + gap) + 2.0, 0.12)
        for col, power in enumerate(powers):
            x, y = x0 + col * (cell + gap), y0 + row * (cell + gap)
            name = f"P{power}-F{frequency:g}"
            layers.append(_layer(idx, name, _process(values | {"power": power, "frequency": frequency}, profile_id),
                                 [_rect(x, y, cell, cell)], mode="Scan", cross_hatch=False,
                                 bidirectional=True, line_interval=values["line_interval"], global_passes=values["global_passes"]))
            labels += _text(f"{power}", x + 1.3, y + 2.1, 0.13)
            cells.append({"name": name, "power": power, "frequency": frequency, "speed": values["speed"], "x": x, "y": y, "width": cell, "height": cell})
            idx += 1
    width = x0 + len(powers) * cell + (len(powers) - 1) * gap + 4
    height = y0 + len(freqs) * cell + (len(freqs) - 1) * gap + 3
    return layers, labels, {"width": width, "height": height, "columns": len(powers), "rows": len(freqs), "cells": cells}


def _power_speed(values: dict, profile_id: int) -> tuple[list[dict], list[dict], dict]:
    powers = COMPACT_POWERS
    speeds = (500, 1000, 1500, 3000, 5000, 7500, 10000)
    x1, x2, y0, row_pitch, gap = 18.0, 72.0, 12.0, 0.55, 0.8
    labels = _text("POWER X SPEED LINE TEST", 4, 1, 0.24)
    layers, cells = [], []
    for pi, power in enumerate(powers):
        top = y0 + pi * (len(speeds) * row_pitch + gap)
        labels += _text(f"P{power}", 3.5, top + 1.3, 0.14)
        for si, speed in enumerate(speeds):
            y = top + si * row_pitch
            labels += _text(f"{speed}", 10.5, y - 0.18, 0.075)
            name = f"P{power}-V{speed}"
            layers.append(_layer(len(layers) + 1, name, _process(values | {"power": power, "speed": speed}, profile_id),
                                 [_line(x1, y, x2, y)], mode="Cut", global_passes=values["global_passes"]))
            cells.append({"name": name, "power": power, "speed": speed, "frequency": values["frequency"], "y": y})
    return layers, labels, {"width": 76.0, "height": y0 + len(powers) * (len(speeds) * row_pitch + gap), "columns": len(speeds), "rows": len(powers), "cells": cells}


def _frequency(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    rate = passport["repetition_rate_khz"]
    freqs = [f for f in FREQUENCIES_KHZ if rate["min"] <= f <= rate["max"]]
    if values["frequency"] not in freqs:
        freqs.append(values["frequency"])
    freqs = sorted(set(freqs))
    x1, x2, y0, row_pitch = 15.0, 71.0, 11.0, 2.15
    labels = _text("FREQUENCY RANGE LINE RESPONSE", 4, 1, 0.21)
    layers, cells = [], []
    for row, frequency in enumerate(freqs):
        y = y0 + row * row_pitch
        labels += _text(f"F{frequency:g}", 4, y - 0.3, 0.1)
        name = f"F{frequency:g}KHZ"
        layers.append(_layer(len(layers) + 1, name, _process(values | {"frequency": frequency}, profile_id),
                             [_line(x1, y, x2, y)], mode="Cut", global_passes=values["global_passes"]))
        cells.append({"name": name, "frequency": frequency, "power": values["power"], "speed": values["speed"], "y": y})
    return layers, labels, {"width": 76.0, "height": y0 + len(freqs) * row_pitch + 2, "columns": 1, "rows": len(freqs), "cells": cells}


def _pulse_cutoff(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    rate = passport["repetition_rate_khz"]
    steps = [s for s in passport["pulse_steps"] if s["cutoff_khz"] is not None]
    if not steps:
        raise pf.ValidationError("в паспорте лазера нет таблицы частоты среза импульсов")
    steps = _evenly_spaced(steps, 9)
    factors = (0.8, 1.0, 1.2)
    labels = _text("Q-PULSE / FREQUENCY CUTOFF", 4, 1, 0.24)
    layers, cells = [], []
    x_positions, x2, y0, pitch = (21.0, 39.0, 57.0), 68.0, 11.0, 2.6
    for row, step in enumerate(steps):
        pulse, cutoff = float(step["pulse_width_ns"]), float(step["cutoff_khz"])
        y = y0 + row * pitch
        labels += _text(f"PW{pulse:g}", 3, y + 0.4, 0.11)
        for col, factor in enumerate(factors):
            frequency = round(max(rate["min"], min(rate["max"], cutoff * factor)), 1)
            name = f"PW{pulse:g}-F{frequency:g}"
            labels += _text(f"{frequency:g}", x_positions[col] + 1, y - 0.35, 0.09)
            params = _process(values | {"frequency": frequency, "pulse_width": pulse}, profile_id)
            layers.append(_layer(len(layers) + 1, name, params, [_line(x_positions[col], y + 1, x2 + col * 0, y + 1)],
                                 mode="Cut", global_passes=values["global_passes"]))
            cells.append({"name": name, "pulse_width": pulse, "cutoff_khz": cutoff, "frequency": frequency, "factor": factor})
    # A CW step has no pulse-width cutoff and makes a useful reference line.
    cw = next((float(s["pulse_width_ns"]) for s in passport["pulse_steps"] if s["cutoff_khz"] is None), None)
    if cw is not None:
        y = y0 + len(steps) * pitch
        labels += _text(f"CW PW{cw:g}", 3, y + 0.4, 0.11)
        layers.append(_layer(len(layers) + 1, f"CW-PW{cw:g}-REFERENCE", _process(values | {"pulse_width": cw}, profile_id),
                             [_line(21, y + 1, 31, y + 1)], mode="Cut", global_passes=values["global_passes"]))
        cells.append({"name": f"CW-PW{cw:g}-REFERENCE", "pulse_width": cw, "frequency": values["frequency"], "reference": True})
    return layers, labels, {"width": 76.0, "height": y0 + (len(steps) + int(cw is not None)) * pitch + 2,
                            "columns": 3, "rows": len(steps), "cells": cells}


def _line_resolution(values: dict, profile_id: int) -> tuple[list[dict], list[dict], dict]:
    x1, x2, y0, group_pitch = 20.0, 47.0, 12.0, 3.8
    labels = _text("LINE SEPARATION / RESOLUTION", 4, 1, 0.22)
    layers, cells = [], []
    for row, spacing_um in enumerate(LINE_SPACINGS_UM):
        center_y = y0 + row * group_pitch
        spacing = spacing_um / 1000.0
        regions = [_line(x1, center_y + (i - 2) * spacing, x2, center_y + (i - 2) * spacing) for i in range(5)]
        labels += _text(f"{spacing_um}UM", 4, center_y - 0.35, 0.11)
        name = f"GAP-{spacing_um}UM"
        layers.append(_layer(len(layers) + 1, name, _process(values, profile_id), regions, mode="Cut",
                             global_passes=values["global_passes"]))
        cells.append({"name": name, "spacing_um": spacing_um, "lines": 5})
    return layers, labels, {"width": 52.0, "height": y0 + len(LINE_SPACINGS_UM) * group_pitch, "columns": 1,
                           "rows": len(LINE_SPACINGS_UM), "cells": cells}


def _hatch_interval(values: dict, profile_id: int) -> tuple[list[dict], list[dict], dict]:
    side, gap, x0, y0 = 8.0, 3.0, 5.0, 12.0
    labels = _text("HATCH INTERVAL TEST", 4, 1, 0.22)
    layers, cells = [], []
    for col, interval in enumerate(HATCH_INTERVALS_MM):
        x = x0 + col * (side + gap)
        name = f"HATCH-I{interval:g}"
        labels += _text(f"{interval:g}MM", x, y0 - 2, 0.10)
        layers.append(_layer(len(layers) + 1, name, _process(values | {"line_interval": interval}, profile_id),
                             [_rect(x, y0, side, side)], mode="Scan", line_interval=interval,
                             bidirectional=True, global_passes=values["global_passes"]))
        cells.append({"name": name, "line_interval": interval, "x": x, "y": y0, "width": side, "height": side})
    return layers, labels, {"width": x0 + len(HATCH_INTERVALS_MM) * side + (len(HATCH_INTERVALS_MM) - 1) * gap + 4,
                            "height": y0 + side + 3, "columns": len(HATCH_INTERVALS_MM), "rows": 1, "cells": cells}


def _offset_fill(values: dict, profile_id: int) -> tuple[list[dict], list[dict], dict]:
    """Compare LightBurn's contour-following fill mode across speed and line-interval axes."""
    speeds = sorted({round(min(10000.0, max(100.0, values["speed"] * factor)), 1) for factor in (0.5, 1.0, 2.0)})
    side, x0, y0, pitch_x, pitch_y = 6.0, 13.0, 14.0, 8.0, 8.0
    labels = _text("OFFSET FILL SPEED X INTERVAL", 3, 1, 0.22)
    layers, cells = [], []
    for col, interval in enumerate(OFFSET_FILL_INTERVALS_MM):
        x = x0 + col * pitch_x
        labels += _text(f"I{interval:g}", x + 0.6, y0 - 2.2, 0.10)
    for row, speed in enumerate(speeds):
        y = y0 + row * pitch_y
        labels += _text(f"V{speed:g}", 3, y + 2.0, 0.11)
        for col, interval in enumerate(OFFSET_FILL_INTERVALS_MM):
            x = x0 + col * pitch_x
            name = f"OFFSET-V{speed:g}-I{interval:g}"
            params = _process(values | {"speed": speed, "line_interval": interval}, profile_id)
            layers.append(_layer(len(layers) + 1, name, params, [_rect(x, y, side, side)], mode="OffsetFill",
                                 cross_hatch=False, bidirectional=False, line_interval=interval,
                                 global_passes=values["global_passes"]))
            cells.append({"name": name, "speed": speed, "line_interval": interval, "power": values["power"],
                          "x": x, "y": y, "width": side, "height": side})
    width = x0 + (len(OFFSET_FILL_INTERVALS_MM) - 1) * pitch_x + side + 3
    height = y0 + (len(speeds) - 1) * pitch_y + side + 3
    return layers, labels, {"width": width, "height": height, "columns": len(OFFSET_FILL_INTERVALS_MM),
                            "rows": len(speeds), "cells": cells}


def _compact_capability(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """Use no more than 28 test settings so clean + registration stay inside colors 00..29."""
    layers: list[dict] = []
    labels = _text("COMPACT LASER CAPABILITY", 2.0, 0.8, 0.14)
    cells: list[dict] = []
    index = 1

    # Sixteen short vector strokes span four powers and four speeds. Broader detailed sweeps have
    # their own plate types; this coupon preserves the full speed span without consuming 56 slots.
    x0, y0, x_pitch, y_pitch, line_length = 7.0, 5.0, 3.6, 1.8, 2.6
    for col, speed in enumerate(COMPACT_SPEEDS):
        labels += _text(f"{speed}", x0 + col * x_pitch - 0.1, 2.6, 0.065)
    for row, power in enumerate(COMPACT_POWERS):
        y = y0 + row * y_pitch
        labels += _text(f"P{power}", 1.2, y - 0.22, 0.07)
        for col, speed in enumerate(COMPACT_SPEEDS):
            x = x0 + col * x_pitch
            name = f"LINE-P{power}-V{speed}"
            params = _process(values | {"power": power, "speed": speed}, profile_id)
            layer = _layer(index, name, params, [_line(x, y, x + line_length, y)], mode="Cut", global_passes=values["global_passes"])
            layers.append(layer)
            cells.append({"name": name, "parameters": params, "x": x, "y": y - 0.02, "width": line_length, "height": 0.04})
            index += 1

    # Ten five-line groups share the same laser settings and therefore one LightBurn output layer.
    line_y0, line_group_pitch, line_x1, line_x2 = 19.5, 1.43, 7.0, 31.0
    gap_regions, gap_groups = [], []
    for row, spacing_um in enumerate(LINE_SPACINGS_UM):
        center = line_y0 + row * line_group_pitch
        spacing = spacing_um / 1000.0
        start = len(gap_regions)
        gap_regions.extend(_line(line_x1, center + (i - 2) * spacing, line_x2, center + (i - 2) * spacing) for i in range(5))
        name = f"LINE-GAP-{spacing_um}UM"
        labels += _text(f"{spacing_um}UM", 1.0, center - 0.22, 0.06)
        gap_groups.append({"name": name, "region_start": start, "region_count": 5, "spacing_um": spacing_um})
    gap_name = "LINE-GAP-20-300UM"
    gap_params = _process(values, profile_id)
    gap_layer = _layer(index, gap_name, gap_params, gap_regions, mode="Cut", global_passes=values["global_passes"])
    gap_layer["measurement_groups"] = gap_groups
    layers.append(gap_layer)
    cells.append({"name": gap_name, "parameters": gap_params, "x": line_x1, "y": line_y0 - 0.16,
                  "width": line_x2 - line_x1, "height": (len(LINE_SPACINGS_UM) - 1) * line_group_pitch + 0.32,
                  "features": gap_groups})
    index += 1

    # A compact diagonal of small / medium / large Step and Size settings. The dedicated wobble plate
    # retains the full 3 x 3 factorial when a first pass shows that wobble needs investigation.
    wobble_x, wobble_y, wobble_side, wobble_pitch = 39.0, 5.0, 3.0, 4.6
    for col, (step, size) in enumerate(COMPACT_WOBBLE_POINTS):
        x, y = wobble_x + col * wobble_pitch, wobble_y + col * wobble_pitch
        name = f"WOBBLE-S{step:g}-D{size:g}"
        labels += _text(f"S{step:g}D{size:g}", x, y - 1.15, 0.075)
        params = _process(values, profile_id)
        layers.append(_layer(index, name, params, [_rect(x, y, wobble_side, wobble_side)], mode="Scan",
                             line_interval=values["line_interval"], global_passes=values["global_passes"],
                             wobble_enabled=True, wobble_step=step, wobble_size=size))
        cells.append({"name": name, "parameters": params, "wobble_step": step, "wobble_size": size,
                      "x": x, "y": y, "width": wobble_side, "height": wobble_side})
        index += 1

    # Three representative hatch intervals: tighter than baseline, baseline-adjacent and coarse.
    hatch_side, hatch_y, hatch_x, hatch_pitch = 3.0, 23.0, 38.0, 3.8
    for col, interval in enumerate(COMPACT_HATCH_INTERVALS_MM):
        x = hatch_x + col * hatch_pitch
        name = f"HATCH-I{interval:g}"
        labels += _text(f"I{interval:g}", x, hatch_y - 1.15, 0.075)
        params = _process(values | {"line_interval": interval}, profile_id)
        layers.append(_layer(index, name, params, [_rect(x, hatch_y, hatch_side, hatch_side)], mode="Scan",
                             line_interval=interval, global_passes=values["global_passes"]))
        cells.append({"name": name, "parameters": params, "x": x, "y": hatch_y, "width": hatch_side, "height": hatch_side})
        index += 1

    # Four logarithmically distributed rates include the requested baseline. CW isolates repetition
    # rate from pulse-width cutoff; the complete frequency plate contains every supported test value.
    rate = passport["repetition_rate_khz"]
    lo, hi = float(rate["min"]), float(rate["max"])
    if hi > lo:
        mid = math.sqrt(lo * hi)
        candidates = [lo, float(values["frequency"]), mid, hi]
        frequencies = sorted({round(max(lo, min(hi, f)), 2) for f in candidates})
        if len(frequencies) < COMPACT_FREQUENCY_POINTS:
            for fraction in (1 / 3, 2 / 3):
                frequencies.append(round(math.exp(math.log(lo) + fraction * (math.log(hi) - math.log(lo))), 2))
                frequencies = sorted(set(frequencies))
                if len(frequencies) >= COMPACT_FREQUENCY_POINTS:
                    break
        if len(frequencies) > COMPACT_FREQUENCY_POINTS:
            inner = sorted(frequencies[1:-1], key=lambda f: abs(math.log(f) - math.log(values["frequency"])))
            keep = {frequencies[0], frequencies[-1], values["frequency"]}
            for f in inner:
                if len(keep) >= COMPACT_FREQUENCY_POINTS:
                    break
                keep.add(f)
            frequencies = sorted(keep)
    else:
        frequencies = [lo]
    cw = next((float(step["pulse_width_ns"]) for step in passport["pulse_steps"] if step["cutoff_khz"] is None), values["pulse_width"])
    frequency_x1, frequency_x2, frequency_y0, frequency_pitch = 40.0, 55.0, 27.5, 3.9
    for row, frequency in enumerate(frequencies):
        y = frequency_y0 + row * frequency_pitch
        name = f"FREQUENCY-F{frequency:g}-CW{cw:g}"
        labels += _text(f"F{frequency:g}", 34.0, y - 0.2, 0.055)
        params = _process(values | {"frequency": frequency, "pulse_width": cw}, profile_id)
        layers.append(_layer(index, name, params, [_line(frequency_x1, y, frequency_x2, y)], mode="Cut",
                             global_passes=values["global_passes"]))
        cells.append({"name": name, "parameters": params, "x": frequency_x1, "y": y - 0.02,
                      "width": frequency_x2 - frequency_x1, "height": 0.04})
        index += 1

    # All five glyph heights share one parameter set, so they belong to one real output layer.
    text_y, text_pitch = 37.5, 5.0
    text_params = _process({**values, **LABEL_DEFAULTS}, profile_id)
    text_regions, text_groups = [], []
    for col, glyph_height in enumerate(COMPACT_TEXT_HEIGHTS_MM):
        x = 3.0 + col * text_pitch
        start = len(text_regions)
        pixel = glyph_height / (5 * 1.45)
        text_regions.extend(_text("A8", x, text_y, pixel))
        text_groups.append({"name": f"TEXT-H{glyph_height:g}MM", "region_start": start,
                            "region_count": len(text_regions) - start, "glyph_height_mm": glyph_height})
        labels += _text(f"H{glyph_height:g}", x, text_y + glyph_height + 0.35, 0.07)
    text_name = "TEXT-H0.8-2.5MM"
    text_layer = _layer(index, text_name, text_params, text_regions, mode="Scan",
                        line_interval=LABEL_DEFAULTS["line_interval"], global_passes=1)
    text_layer["measurement_groups"] = text_groups
    layers.append(text_layer)
    cells.append({"name": text_name, "parameters": text_params, "x": 3.0, "y": text_y,
                  "width": 22.5, "height": 5.85, "features": text_groups})

    feature_count = 16 + len(gap_groups) + len(COMPACT_WOBBLE_POINTS) + len(COMPACT_HATCH_INTERVALS_MM) + len(frequencies) + len(text_groups)
    return layers, labels, {"width": 58.0, "height": 42.0, "columns": 4, "rows": 4,
                            "cells": cells, "feature_count": feature_count}


def _text_readability(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """A small, repeatable text coupon centered on an observed or user-selected setting."""
    power = float(values["power"])
    speed = float(values["speed"])
    spread = float(values.get("text_spread", 0.2))
    if not math.isfinite(spread) or not 0.04 <= spread <= 0.4:
        raise pf.ValidationError("разброс теста надписей должен быть от 4% до 40%")
    powers = sorted({round(max(1.0, min(100.0, power * factor)), 2) for factor in (1 - spread, 1, 1 + spread)})
    speeds = sorted({round(max(1.0, min(10000.0, speed * factor)), 1) for factor in (1 - spread * 1.25, 1, 1 + spread * 1.25)})
    if len(powers) < 3 or len(speeds) < 3:
        raise pf.ValidationError("для трёхточечного теста надписей задайте мощность 2–83% и скорость 2–8000 мм/с")
    labels = _text("TEXT POWER X SPEED", 2.0, 1.0, 0.14)
    layers, cells = [], []
    x0, y0, pitch_x, pitch_y = 5.0, 10.0, 16.0, 12.0
    heights = (1.0, 1.5, 2.0)
    for col, setting_power in enumerate(powers):
        labels += _text(f"P{setting_power:g}", x0 + col * pitch_x, 7.0, 0.08)
    for row, setting_speed in enumerate(speeds):
        y = y0 + row * pitch_y
        labels += _text(f"V{setting_speed:g}", 0.5, y + 4.0, 0.055)
        for col, setting_power in enumerate(powers):
            x = x0 + col * pitch_x
            params = _process(values | {"power": setting_power, "speed": setting_speed}, profile_id)
            regions, groups = [], []
            for height_index, height in enumerate(heights):
                first = len(regions)
                glyphs = _text("A8M", x + 1.0, y + 0.5 + height_index * 3.4, height / (5 * 1.45))
                regions.extend(glyphs)
                groups.append({"name": f"TEXT-H{height:g}MM", "region_start": first,
                               "region_count": len(glyphs), "glyph_height_mm": height})
            name = f"TEXT-P{setting_power:g}-V{setting_speed:g}"
            layer = _layer(len(layers) + 1, name, params, regions, mode="Scan",
                           line_interval=values["line_interval"], global_passes=values["global_passes"])
            layer["measurement_groups"] = groups
            layers.append(layer)
            cells.append({"name": name, "parameters": params, "x": x, "y": y,
                          "width": 13.0, "height": 10.0, "features": groups})
    return layers, labels, {"width": 54.0, "height": 47.0, "columns": 3, "rows": 3,
                            "cells": cells, "feature_count": len(cells) * len(heights)}


def _wobble(values: dict, profile_id: int) -> tuple[list[dict], list[dict], dict]:
    side, x0, y0, pitch = 5.0, 5.0, 12.0, 8.0
    labels = _text("WOBBLE STEP X CIRCLE DIAMETER", 3.0, 1.0, 0.18)
    layers, cells = [], []
    for row, step in enumerate(WOBBLE_STEPS_MM):
        for col, size in enumerate(WOBBLE_SIZES_MM):
            x, y = x0 + col * pitch, y0 + row * pitch
            name = f"WOBBLE-S{step:g}-D{size:g}"
            labels += _text(f"S{step:g}D{size:g}", x, y - 1.8, 0.09)
            params = _process(values, profile_id)
            layers.append(_layer(len(layers) + 1, name, params, [_rect(x, y, side, side)], mode="Scan",
                                 line_interval=values["line_interval"], global_passes=values["global_passes"],
                                 wobble_enabled=True, wobble_step=step, wobble_size=size))
            cells.append({"name": name, "wobble_step": step, "wobble_size": size,
                          "power": values["power"], "frequency": values["frequency"], "speed": values["speed"],
                          "x": x, "y": y, "width": side, "height": side})
    return layers, labels, {"width": 5 + 2 * pitch + side + 3, "height": y0 + 2 * pitch + side + 3,
                            "columns": 3, "rows": 3, "cells": cells}


def _small_patches(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """A true content-sized coupon; marker/QR overhead is included by preview()."""
    try:
        side = float(values.get("patch_size_mm", 3.0))
    except (TypeError, ValueError):
        raise pf.ValidationError("размер квадрата должен быть числом от 3 до 5 мм") from None
    if not math.isfinite(side) or not 3 <= side <= 5:
        raise pf.ValidationError("размер квадрата должен быть от 3 до 5 мм")
    registration = values.get("registration", "full")
    if registration not in {"full", "none"}:
        raise pf.ValidationError("регистрация малой платы должна быть full или none")
    patch_specs = values.get("patches")
    if patch_specs is None:
        patch_specs = [{}]
    if not isinstance(patch_specs, list) or not 1 <= len(patch_specs) <= 4 or any(not isinstance(p, dict) for p in patch_specs):
        raise pf.ValidationError("задайте от одного до четырёх квадратов с параметрами")
    allowed = {"power", "frequency", "speed", "pulse_width", "line_interval", "passes", "global_passes"}
    gap, pad = 0.8, 1.5
    max_width = float(values.get("max_width_mm", 100))
    max_height = float(values.get("max_height_mm", 100))
    minimum_canvas = 10.0 if registration == "full" else 0.0
    marker_overhead = 9.0 if registration == "full" else 0.0
    layouts = []
    for candidate_columns in range(1, len(patch_specs) + 1):
        candidate_rows = math.ceil(len(patch_specs) / candidate_columns)
        cw = max(minimum_canvas, candidate_columns * side + (candidate_columns - 1) * gap + 2 * pad) + marker_overhead
        ch = max(minimum_canvas, candidate_rows * side + (candidate_rows - 1) * gap + 2 * pad) + marker_overhead
        fits = cw <= max_width + 1e-6 and ch <= max_height + 1e-6
        layouts.append((not fits, cw * ch, abs(cw - ch), candidate_columns, candidate_rows))
    _, _, _, columns, rows = min(layouts)
    content_w = columns * side + (columns - 1) * gap
    content_h = rows * side + (rows - 1) * gap
    width, height = max(minimum_canvas, content_w + 2 * pad), max(minimum_canvas, content_h + 2 * pad)
    x0, y0 = (width - content_w) / 2, (height - content_h) / 2
    layers, cells = [], []
    for i, spec in enumerate(patch_specs):
        unknown = set(spec) - allowed
        if unknown:
            raise pf.ValidationError(f"квадрат {i + 1}: неизвестные параметры: {', '.join(sorted(unknown))}")
        selected, _, _ = _passport_defaults(passport, {**values, **spec})
        x = x0 + (i % columns) * (side + gap)
        y = y0 + (i // columns) * (side + gap)
        name = f"PATCH-{i + 1:02d}-P{selected['power']:g}-V{selected['speed']:g}"
        params = _process(selected, profile_id)
        layers.append(_layer(i + 1, name, params, [_rect(x, y, side, side)], mode="Scan",
                             line_interval=selected["line_interval"], global_passes=selected["global_passes"]))
        cells.append({"name": name, "parameters": params, "x": x, "y": y,
                      "width": side, "height": side, "patch_index": i + 1})
    return layers, [], {"width": width, "height": height, "columns": columns, "rows": rows,
                        "cells": cells, "sample_area_mm2": round(len(cells) * side * side, 2)}


def _matrix_axis_values(axis: str, lower: float, upper: float, count: int, passport: dict) -> list[float]:
    """Return a bounded, unique sweep. Pulse and pass axes use supported discrete values."""
    if axis == "pulse_width":
        domain = sorted({float(step["pulse_width_ns"]) for step in passport["pulse_steps"]
                        if lower <= float(step["pulse_width_ns"]) <= upper})
        if len(domain) < count:
            raise pf.ValidationError(f"для оси Q-Pulse в выбранном диапазоне доступно только {len(domain)} ступеней; уменьшите число точек или расширьте диапазон")
        return [float(item["value"]) for item in _evenly_spaced([{"value": v} for v in domain], count)]
    if axis == "passes":
        low, high = int(lower), int(upper)
        if lower != low or upper != high or high - low + 1 < count:
            raise pf.ValidationError("ось проходов должна использовать целые границы и содержать достаточно разных значений")
        return [float(round(low + i * (high - low) / (count - 1))) for i in range(count)]
    return [round(lower + i * (upper - lower) / (count - 1), 4) for i in range(count)]


def _material_matrix(values: dict, profile_id: int, passport: dict) -> tuple[list[dict], list[dict], dict]:
    """A Material-Test-style 5x5 response matrix. Every cell owns one real output layer."""
    settings = _matrix_settings(values, passport)
    x_axis, y_axis = settings["x_axis"], settings["y_axis"]
    x_meta, y_meta = MATRIX_AXES[x_axis], MATRIX_AXES[y_axis]
    x_values = _matrix_axis_values(x_axis, settings["x_min"], settings["x_max"], settings["x_count"], passport)
    y_values = _matrix_axis_values(y_axis, settings["y_min"], settings["y_max"], settings["y_count"], passport)
    mark = settings["geometry"]
    columns, rows = len(x_values), len(y_values)
    gap, x0, y0 = 0.5, 5.0, 10.0
    # Compact cells and place the QR in the top registration band. Four small corner marks still
    # give the photo enough points for perspective alignment without stacking a QR footer below it.
    cell_w, cell_h = ((21.0, 15.5) if mark == "vector_text" else
                      (13.0, 10.5) if mark == "text" else (8.5, 7.5))
    if min(cell_w, cell_h) < 4.0:
        raise pf.ValidationError("выберите меньше точек по каждой оси, чтобы подписи и образцы оставались различимыми")
    labels = _text(f"{x_meta['short']} X {y_meta['short']} MATERIAL TEST", 2.0, 1.0, 0.18)
    layers, cells = [], []
    for col, x_value in enumerate(x_values):
        x = x0 + col * (cell_w + gap)
        labels += _text(f"{x_value:g}", x + 2.5, 9.0, 0.10)
    for row, y_value in enumerate(y_values):
        y = y0 + row * (cell_h + gap)
        labels += _text(f"{y_value:g}", 1.0, y + 3.0, 0.10)
        for col, x_value in enumerate(x_values):
            x = x0 + col * (cell_w + gap)
            params = {**values, x_axis: x_value, y_axis: y_value}
            params.pop("matrix", None)
            params = _process(params, profile_id)
            name = f"MATRIX-{x_meta['short']}{x_value:g}-{y_meta['short']}{y_value:g}"
            groups = []
            if mark == "vector_text":
                region = []
                baseline = y + 0.7
                for height, repeat in ((2.0, 1), (2.0, 2), (4.0, 1), (4.0, 2)):
                    first = len(region)
                    glyphs = _vector_text("A8M B012", x + 0.8, baseline, height)
                    region.extend(glyphs)
                    groups.append({"name": f"TEXT-H{height:g}MM-R{repeat}", "region_start": first,
                                   "region_count": len(glyphs), "glyph_height_mm": height, "repeat": repeat})
                    baseline += height + 0.65
                mode, interval = "Cut", params["line_interval"]
            elif mark == "text":
                region = []
                for height_index, glyph_height in enumerate((0.9, 1.3, 1.7)):
                    first = len(region)
                    glyphs = _text("A8M", x + 0.9, y + 0.5 + height_index * 3.1,
                                   glyph_height / (5 * 1.45))
                    region.extend(glyphs)
                    groups.append({"name": f"TEXT-H{glyph_height:g}MM", "region_start": first,
                                   "region_count": len(glyphs), "glyph_height_mm": glyph_height})
                mode, interval = "Scan", params["line_interval"]
            elif mark == "fill":
                side = min(5.6, cell_w * 0.68, cell_h * 0.68)
                region = [_rect(x + (cell_w - side) / 2, y + (cell_h - side) / 2, side, side)]
                mode, interval = "Scan", params["line_interval"]
            else:
                line_length = min(7.4, cell_w * 0.82, cell_h * 0.78)
                region = [_line(x + (cell_w - line_length) / 2, y + cell_h / 2,
                                x + (cell_w + line_length) / 2, y + cell_h / 2)]
                mode, interval = "Cut", params["line_interval"]
            if mark in ("text", "vector_text"):
                name = f"TEXT-MATRIX-{x_meta['short']}{x_value:g}-{y_meta['short']}{y_value:g}"
            wobble_size = (float(x_value) if x_axis == "wobble_size" else
                           float(y_value) if y_axis == "wobble_size" else 0.0)
            layer = _layer(len(layers) + 1, name, params, region, mode=mode,
                           line_interval=interval, global_passes=values["global_passes"],
                           wobble_enabled=wobble_size > 0, wobble_step=settings["wobble_step"],
                           wobble_size=wobble_size)
            if groups:
                layer["measurement_groups"] = groups
            layers.append(layer)
            cells.append({"name": name, "parameters": params,
                          "x": x if mark in ("text", "vector_text") else region[0]["x"],
                          "y": y if mark in ("text", "vector_text") else region[0]["y"],
                          "width": cell_w if mark in ("text", "vector_text") else region[0]["width"],
                          "height": cell_h if mark in ("text", "vector_text") else region[0]["height"],
                          "x_axis": x_axis, "y_axis": y_axis, "x_value": x_value, "y_value": y_value,
                          "geometry_type": mark, "wobble_enabled": wobble_size > 0,
                          "wobble_step": settings["wobble_step"] if wobble_size > 0 else None,
                          "wobble_size": wobble_size, "features": groups})
    width = x0 + columns * cell_w + (columns - 1) * gap + 2.0
    height = y0 + rows * cell_h + (rows - 1) * gap + 2.0
    return layers, labels, {"width": width, "height": height, "columns": columns, "rows": rows,
                            "feature_count": len(cells) * (4 if mark == "vector_text" else 3 if mark == "text" else 1),
                            "cells": cells, "matrix": {**settings, "x_values": x_values, "y_values": y_values}}


def _matrix_settings(values: dict, passport: dict) -> dict:
    supplied = values.get("matrix") or {}
    x_axis = supplied.get("x_axis", "power")
    y_axis = supplied.get("y_axis", "speed")
    if x_axis not in MATRIX_AXES or y_axis not in MATRIX_AXES or x_axis == y_axis:
        raise pf.ValidationError("выберите две разные оси из мощности, скорости, частоты, Q-Pulse, интервала линий, проходов и wobble")
    geometry = supplied.get("geometry", "line")
    if geometry not in ("line", "fill", "text", "vector_text"):
        raise pf.ValidationError("образец матрицы должен быть линией, заливкой, заполненным или векторным текстом")
    if "line_interval" in (x_axis, y_axis) and geometry in ("line", "vector_text"):
        raise pf.ValidationError("интервал линий проверяется только на залитых участках; выберите заливку или другую ось")
    if "wobble_size" in (x_axis, y_axis) and geometry not in ("line", "vector_text"):
        raise pf.ValidationError("wobble проверяется на векторной линии или однолинейном векторном тексте")
    repetition = passport["repetition_rate_khz"]
    pulse_values = [float(step["pulse_width_ns"]) for step in passport["pulse_steps"]]
    domain = {"power": (1.0, 100.0), "frequency": (float(repetition["min"]), float(repetition["max"])),
              "speed": (1.0, 10000.0), "pulse_width": (min(pulse_values), max(pulse_values)),
              "line_interval": (0.001, 1.0), "passes": (1.0, 20.0), "wobble_size": (0.0, 1.0)}
    defaults = {key: (float(MATRIX_AXES[key]["default_min"]), float(MATRIX_AXES[key]["default_max"])) for key in MATRIX_AXES}
    defaults["frequency"] = (max(domain["frequency"][0], defaults["frequency"][0]),
                              min(domain["frequency"][1], defaults["frequency"][1]))
    defaults["pulse_width"] = (min(pulse_values), max(pulse_values))
    try:
        wobble_step = float(supplied.get("wobble_step", 0.02))
    except (TypeError, ValueError):
        raise pf.ValidationError("шаг wobble должен быть числом") from None
    if not math.isfinite(wobble_step) or not 0.001 <= wobble_step <= 1:
        raise pf.ValidationError("шаг wobble должен быть от 0,001 до 1 мм")
    out = {"x_axis": x_axis, "y_axis": y_axis, "geometry": geometry, "wobble_step": wobble_step}
    for prefix, axis in (("x", x_axis), ("y", y_axis)):
        low_default, high_default = defaults[axis]
        try:
            low = float(supplied.get(f"{prefix}_min", low_default))
            high = float(supplied.get(f"{prefix}_max", high_default))
            count = int(supplied.get(f"{prefix}_count", 5))
        except (TypeError, ValueError):
            raise pf.ValidationError("границы и число точек матрицы должны быть числами") from None
        if not math.isfinite(low) or not math.isfinite(high) or low >= high:
            raise pf.ValidationError("нижняя граница каждой оси должна быть строго ниже верхней")
        if low < domain[axis][0] or high > domain[axis][1]:
            raise pf.ValidationError(f"ось {MATRIX_AXES[axis]['label']} выходит за поддерживаемый диапазон лазера: {domain[axis][0]:g}–{domain[axis][1]:g} {MATRIX_AXES[axis]['unit']}")
        if not 2 <= count <= 7:
            raise pf.ValidationError("для каждой оси задайте от 2 до 7 точек")
        if axis == "passes" and (low != round(low) or high != round(high)):
            raise pf.ValidationError("границы оси проходов должны быть целыми числами")
        out.update({f"{prefix}_min": low, f"{prefix}_max": high, f"{prefix}_count": count})
    if out["x_count"] * out["y_count"] > 28:
        raise pf.ValidationError("в сетке не более 28 ячеек: ещё два выходных слоя нужны для чистки и регистрации")
    return out


BUILDERS = {"small_patches": _small_patches, "compact_capability": _compact_capability, "text_readability": _text_readability, "calibration": _calibration, "power_speed": _power_speed, "frequency": _frequency,
            "pulse_cutoff": _pulse_cutoff, "line_resolution": _line_resolution, "hatch_interval": _hatch_interval,
            "offset_fill": _offset_fill, "wobble": _wobble, "material_matrix": _material_matrix}


def _identity_profile(store: Store, device: dict, lens: dict) -> dict:
    row = store.one("SELECT id FROM laser_profile WHERE device_id=? AND lens_id=? ORDER BY id LIMIT 1", (device["id"], lens["id"]))
    if row:
        return pf.get_profile(store, row["id"])
    label = f"{device['name']} · {lens['name']}"
    return pf.create_profile(store, label, device_id=device["id"], lens_id=lens["id"])


def preview(store: Store, device_id: int, material_id: int, test_type: str, settings: dict | None = None) -> dict:
    """Build a test plate without saving a plate or plan (the laser/lens identity may be initialized)."""
    if test_type not in BUILDERS:
        raise pf.ValidationError("выберите тип экспериментальной платы")
    device = devices.get_device(store, device_id)
    lens = device.get("lens")
    if not lens:
        raise pf.ValidationError("сначала укажите линзу, установленную на этом лазере")
    material_row = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if material_row is None:
        raise pf.ValidationError("выберите материал с фактической маркой или партией")
    if material_row["family"] != "Titanium":
        raise pf.ValidationError("для этого материала пока не задан рецепт очистки; титановую очистку применять нельзя")
    profile = _identity_profile(store, device, lens)
    values, clean, labels = _passport_defaults(device["passport"], settings or {})
    limits = {}
    for axis in ("width", "height"):
        try:
            limit = float((settings or {}).get(f"max_{axis}_mm", 100))
        except (TypeError, ValueError):
            raise pf.ValidationError("максимальные размеры платы должны быть числами от 1 до 100 мм") from None
        if not math.isfinite(limit) or not 1 <= limit <= 100:
            raise pf.ValidationError("максимальные размеры платы должны быть от 1 до 100 мм")
        limits[axis] = limit
        values[f"max_{axis}_mm"] = limit
    if test_type == "frequency":
        # The CW step lets the sweep reach the full repetition-rate range without crossing a pulse cutoff.
        cw = next((s for s in device["passport"]["pulse_steps"] if s["cutoff_khz"] is None), None)
        if cw:
            values["pulse_width"] = float(cw["pulse_width_ns"])
    if test_type in ("small_patches", "frequency", "pulse_cutoff", "calibration", "compact_capability", "material_matrix", "text_readability"):
        layers, label_regions, geometry = BUILDERS[test_type](values, profile["id"], device["passport"])
    else:
        layers, label_regions, geometry = BUILDERS[test_type](values, profile["id"])
    if test_type == "material_matrix":
        values["matrix"] = geometry["matrix"]
    ident = plans.new_identifier("TCE")
    marked = test_type != "small_patches" or values.get("registration", "full") == "full"
    markers = plans.marker_geometry(ident, geometry["width"], geometry["height"], COMPACT_MARKER_SIZE) if marked else None
    total_w = markers["extent"]["max_x"] - markers["extent"]["min_x"] if markers else geometry["width"]
    total_h = markers["extent"]["max_y"] - markers["extent"]["min_y"] if markers else geometry["height"]
    clean_regions = None
    if test_type == "small_patches":
        # Cleaning is still first, but the laser need not raster over the empty space
        # separating tiny samples and registration marks.
        apron = 0.3
        clean_regions = [_rect(c["x"] - apron, c["y"] - apron,
                               c["width"] + 2 * apron, c["height"] + 2 * apron)
                         for c in geometry["cells"]]
        if markers:
            clean_regions += [_rect(m["x"], m["y"], m["size"], m["size"])
                              for m in markers["aruco"]]
            qr = markers["qr"]
            clean_regions.append(_rect(qr["x"], qr["y"], qr["size"], qr["size"]))
    if total_w > limits["width"] + 1e-6 or total_h > limits["height"] + 1e-6:
        raise pf.ValidationError(f"эта плата с метками занимает {total_w:.1f} × {total_h:.1f} мм; заданный предел — {limits['width']:g} × {limits['height']:g} мм")
    field = lens.get("field_mm")
    if field and max(total_w, total_h) > float(field):
        raise pf.ValidationError(f"плата {total_w:.1f} × {total_h:.1f} мм не помещается в поле линзы {field:g} мм")
    if len(layers) + 1 + int(marked) > plans.MAX_LAYERS:
        raise pf.ValidationError("для этого теста слишком много слоёв LightBurn")
    # The user's C01 black-on-titanium recipe, kept separate from the laser/lens identity.
    marker_layer = labels | {"name": "Markers and labels", "interval": labels["line_interval"], "global_passes": 1,
                            "bidirectional": False, "cross_hatch": False, "angle": 0.0, "angle_increment": 0.0}
    series = ({"identifier": values.get("series_identifier"), "part_index": values.get("part_index"),
               "part_count": values.get("part_count")}) if values.get("series_identifier") else None
    title = TYPE_BY_ID[test_type]["name"]
    if series:
        title += f" · часть {series['part_index']}/{series['part_count']}"
    experiment = {"test_type": test_type, "test_name": title, "test_description": TYPE_BY_ID[test_type]["description"],
                  "device": {k: device.get(k) for k in ("id", "name", "manufacturer", "model", "serial", "title")},
                  "lens": {k: lens.get(k) for k in ("id", "name", "focal_length_mm", "field_mm", "expansion")},
                  "material": {k: material_row[k] for k in ("id", "name", "family", "grade", "batch", "thickness_mm", "surface")},
                  "test_settings": values, "cleanup_settings": clean, "label_settings": labels, "series": series,
                  "research_goal": values.get("research_goal"), "source_pair_id": values.get("source_pair_id"),
                  "summary": {"layers": len(layers), "test_features": len(geometry["cells"]),
                              "visual_features": geometry.get("feature_count", len(geometry["cells"])),
                              "size_mm": {"width": round(total_w, 2), "height": round(total_h, 2)},
                              "limit_mm": limits, "registration": "full" if marked else "none",
                              "sample_area_mm2": geometry.get("sample_area_mm2"),
                              "clean_area_mm2": round(sum(r["width"] * r["height"] for r in clean_regions), 2)
                              if clean_regions is not None else round(total_w * total_h, 2)}}
    return {"profile": profile, "device": device, "lens": lens, "material": dict(material_row), "identifier": ident,
            "layers": layers, "label_regions": label_regions, "geometry": geometry, "markers": markers,
            "clean_layer": clean | {"interval": clean["line_interval"], "global_passes": 1, "bidirectional": True,
                                    "cross_hatch": True, "angle": 0.0, "angle_increment": 0.0},
            "marker_layer": marker_layer, "clean_regions": clean_regions, "experiment": experiment,
            "values": values, "label_regions_count": len(label_regions)}


def _persist_prepared(store: Store, result: dict, device_id: int, material_id: int, test_type: str,
                      research_session_id: int | None = None, supersede_plan_id: int | None = None) -> dict:
    """Persist a prevalidated plate inside the caller's transaction."""
    profile, device, lens = result["profile"], result["device"], result["lens"]
    ident, geometry, layers = result["identifier"], result["geometry"], result["layers"]
    title = result["experiment"]["test_name"]
    lens_snapshot = lenses.snapshot(lens, device.get("passport", {}).get("spot_diameter_um"))
    cells = geometry["cells"]
    if supersede_plan_id is not None:
        if research_session_id is None:
            raise pf.ValidationError("для замены платы требуется исследование")
        changed = store.execute(
            "UPDATE plan SET status='Superseded' WHERE id=? AND research_session_id=? "
            "AND status IN ('Ready to export','Exported') "
            "AND NOT EXISTS (SELECT 1 FROM pair WHERE plan_id=? AND status!='Deleted')",
            (supersede_plan_id, research_session_id, supersede_plan_id))
        if changed.rowcount != 1:
            raise pf.ProtectedError("плата уже изменилась или к ней привязана фотография; замена отменена")
    plate_id = store.execute(
        "INSERT INTO plate(experiment_id,profile_id,speed,geometry_json,cells_json,proposal_id,lens_json,material_id,test_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ident, profile["id"], result["values"]["speed"], json.dumps(geometry), json.dumps(cells), None,
         json.dumps(lens_snapshot) if lens_snapshot else None, material_id, test_type, now())).lastrowid
    plan_data = {"layers": layers, "markers": result["markers"], "marker_labels": result["label_regions"],
                 "clean_regions": result["clean_regions"],
                 "marker_layer": result["marker_layer"], "clean_layer": result["clean_layer"],
                 "export_mirror_y": True,
                 "experiment": result["experiment"], "test_type": test_type,
                 "process_settings": {k: result["values"][k] for k in ("pulse_width", "line_interval", "passes")},
                 "lightburn_settings": {"global_passes": result["values"]["global_passes"], "bidirectional": True,
                                        "cross_hatch": False, "scan_angle": 0.0, "angle_increment": 0.0}}
    plan_id = store.execute(
        "INSERT INTO plan(name,mode,status,profile_id,plate_id,markers,plan_identifier,band_count,data_json,created_at,research_session_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (f"{title} · {ident}", plans.MODE_CAPABILITY, "Ready to export", profile["id"], plate_id,
         int(bool(result["markers"])), ident, len(layers), json.dumps(plan_data), now(), research_session_id)).lastrowid
    if supersede_plan_id is not None:
        store.audit("research_plate_superseded", session_id=research_session_id,
                    old_plan_id=supersede_plan_id, new_plan_id=plan_id)
    store.audit("capability_plate_created", plan_id=plan_id, plate_id=plate_id, device_id=device_id, lens_id=lens["id"],
                material_id=material_id, test_type=test_type, identifier=ident)
    return {"plan_id": plan_id, "plate_id": plate_id, "identifier": ident, "name": f"{title} · {ident}",
            "test_type": test_type, "summary": result["experiment"]["summary"], "experiment": result["experiment"]}


def create(store: Store, device_id: int, material_id: int, test_type: str, settings: dict | None = None,
           *, research_session_id: int | None = None, supersede_plan_id: int | None = None) -> dict:
    result = preview(store, device_id, material_id, test_type, settings)
    with store.transaction():
        return _persist_prepared(store, result, device_id, material_id, test_type,
                                 research_session_id, supersede_plan_id)


def preview_small_patch_parts(store: Store, device_id: int, material_id: int, settings: dict) -> list[dict]:
    """Partition 1–4 samples into the fewest independent marked files that fit the limits."""
    patches = settings.get("patches")
    if patches is None:
        patches = [{}]
    if not isinstance(patches, list) or not 1 <= len(patches) <= 4:
        raise pf.ValidationError("задайте от одного до четырёх квадратов с параметрами")
    prepared = []
    cursor = 0
    while cursor < len(patches):
        last_size_error = None
        for end in range(len(patches), cursor, -1):
            candidate = {**settings, "patches": patches[cursor:end]}
            try:
                part = preview(store, device_id, material_id, "small_patches", candidate)
            except pf.ValidationError as exc:
                if str(exc).startswith("эта плата с метками занимает"):
                    last_size_error = exc
                    continue
                raise
            prepared.append((cursor, end, part))
            cursor = end
            break
        else:
            raise last_size_error or pf.ValidationError("даже один квадрат не помещается в заданный размер")
    return [{"sample_indexes": list(range(start + 1, end + 1)), "prepared": part,
             "settings": {**settings, "patches": patches[start:end]}}
            for start, end, part in prepared]


def create_small_patch_parts(store: Store, device_id: int, material_id: int, settings: dict) -> dict:
    parts = preview_small_patch_parts(store, device_id, material_id, settings)
    series_identifier = plans.new_identifier("TCE") if len(parts) > 1 else None
    prepared = []
    for index, part in enumerate(parts, 1):
        part_settings = {**part["settings"], "series_identifier": series_identifier,
                         "part_index": index, "part_count": len(parts)}
        prepared.append((part, preview(store, device_id, material_id, "small_patches", part_settings)))
    with store.transaction():
        created = [(_persist_prepared(store, plate, device_id, material_id, "small_patches"),
                    part["sample_indexes"]) for part, plate in prepared]
    return {"series_identifier": series_identifier,
            "parts": [{**record, "sample_indexes": indexes,
                       "download_url": f"/api/plans/{record['plan_id']}/export.lbrn2"}
                      for record, indexes in created]}
