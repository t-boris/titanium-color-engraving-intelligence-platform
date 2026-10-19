"""Task-first experiment suggestions for one laser, installed lens and physical stock.

Suggestions are deterministic and auditable. They narrow measured ranges but never promote a
photographic contrast proxy to a production recipe or infer cutting depth from a surface photo.
A suggestion names its engraving task (REQ-020, ``tasks``) and the observed evidence it builds on.
"""
from __future__ import annotations

import json

from . import capability_results, devices, setup as su, tasks
from .db import Store


GOALS = {
    "text": ("Надписи", "Разборчивые буквы и цифры выбранного размера"),
    "line": ("Линии и чертежи", "Непрерывный тонкий штрих и различимые соседние линии"),
    "black_mark": ("Чёрная маркировка", "Тёмный контрастный след с повторяемым видом"),
    "white_mark": ("Светлая маркировка", "Светлый контрастный след с повторяемым видом"),
    "color": ("Цвет на металле", "Воспроизводимый цвет с эталонной картой"),
    "cleaning": ("Очистка", "Удаление поверхностного загрязнения без нежелательного следа"),
    "image": ("Рисунок и изображение", "Детали, полутона и равномерные области"),
    "deep": ("Глубокая гравировка", "Глубина в миллиметрах и качество стенок после циклов гравировки/очистки"),
    "relief_3d": ("3D-рельеф и монеты", "Послойный рельеф, геометрия и фактура"),
    "cutting": ("Резка", "Сквозной рез, ширина пропила и состояние кромки"),
}


def list_goals() -> list[dict]:
    return [{"id": key, "name": value[0], "objective": value[1]} for key, value in GOALS.items()]


def _bounded_center(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


STARTING_PULSE_NS = 200.0       # an editable starting value, only when the laser offers it (DEC-043)


def _settings(device: dict, params: dict | None = None) -> dict:
    """Settings of a suggested plate: measured ones when a finding gives them, else starting values. The pulse width
    starts at 200 ns only on a laser that offers that step; otherwise it is None and the operator chooses it."""
    passport = device["passport"]
    steps = [float(s["pulse_width_ns"]) for s in passport["pulse_steps"]]
    rate = passport["repetition_rate_khz"]
    values = {"power": 20.0, "speed": 900.0, "frequency": 48.0, "pulse_width": STARTING_PULSE_NS if STARTING_PULSE_NS in steps else None,
              "line_interval": 0.025, "passes": 1, "global_passes": 1}
    for key in ("power", "speed", "frequency", "pulse_width", "line_interval", "passes"):
        if params and params.get(key) is not None:
            values[key] = params[key]
    values["power"] = _bounded_center(float(values["power"]), 1.0, 100.0)
    values["speed"] = _bounded_center(float(values["speed"]), 1.0, 10000.0)
    values["frequency"] = _bounded_center(float(values["frequency"]), float(rate["min"]), float(rate["max"]))
    if values["pulse_width"] is not None:
        values["pulse_width"] = min(steps, key=lambda item: abs(item - float(values["pulse_width"])))
    return values


def _accepted_runs(store: Store, device_id: int, material_id: int, lens_id: int, test_type: str) -> int:
    return store.one(
        "SELECT COUNT(DISTINCT p.engraving_id) AS n FROM pair p "
        "JOIN plate t ON t.id=p.plate_id WHERE p.status='Accepted' AND p.device_id=? AND p.lens_id=? "
        "AND p.material_id=? AND t.test_type=?",
        (device_id, lens_id, material_id, test_type))["n"]


def _pending_plan(store: Store, device_id: int, material_id: int, lens_id: int, goal: str) -> int | None:
    rows = store.query(
        "SELECT p.id,p.data_json FROM plan p JOIN plate t ON t.id=p.plate_id "
        "LEFT JOIN research_session s ON s.id=p.research_session_id "
        "WHERE p.status IN ('Ready to export','Exported') "
        "AND (s.id IS NULL OR s.status!='Deleted') AND t.material_id=? "
        "AND p.device_id=? AND p.lens_id=? ORDER BY p.id DESC",
        (material_id, device_id, lens_id))
    for row in rows:
        experiment = json.loads(row["data_json"]).get("experiment") or {}
        if experiment.get("research_goal") != goal:
            continue
        accepted = store.one("SELECT COUNT(*) AS n FROM pair WHERE plan_id=? AND status='Accepted'", (row["id"],))["n"]
        if not accepted:
            return row["id"]
    return None


def _support(store: Store, finding: dict | None) -> dict | None:
    """The evidence behind a finding the suggestion builds on (REQ-020): its observations and the photographs of its
    engraving, how many independent engravings it has (one: its repeatability is not assessed) and the context it lacks."""
    if finding is None:
        return None
    pair = store.one("SELECT engraving_id, lens_id, context_json FROM pair WHERE id=?", (finding["pair_id"],))
    layer = (finding.get("evidence") or {}).get("layer_index")
    rows = [r for r in store.query("SELECT id, layer_index, parameters_json, evidence_json FROM observation WHERE pair_id=? ORDER BY id",
                                   (finding["pair_id"],)) if layer is None or r["layer_index"] == layer]
    photographs = store.one("SELECT COUNT(*) AS n FROM pair WHERE engraving_id=? AND status='Accepted'", (pair["engraving_id"],))["n"]
    missing = []
    if pair["lens_id"] is None:
        missing.append("lens_unknown")
    if json.loads(pair["context_json"] or "{}").get("batch") is None:
        missing.append("batch_unknown")
    if any((json.loads(r["evidence_json"] or "{}").get("color_measurement") or {}).get("mode") == "raw_camera_relative" for r in rows):
        missing.append("camera_relative")
    if any(json.loads(r["parameters_json"]).get(k) is None for r in rows for k in ("power", "frequency", "speed", "pulse_width", "passes")):
        missing.append("settings_incomplete")
    return {"evidence": "observed", "pair_id": finding["pair_id"], "observation_ids": [r["id"] for r in rows],
            "engravings": 1, "photographs": photographs, "repeatability": {"assessed": False, "engravings": 1},
            "missing_context": missing}


def suggest(store: Store, device_id: int, material_id: int, goal: str | None = None, task: str | None = None) -> dict:
    """The next step for an engraving task on one laser, its installed lens and one titanium stock. The task is either a goal
    of this guide or a task kind of REQ-020 (``task``), which names the goal that serves it."""
    if goal is None and task is not None:
        goal = tasks.TASKS[tasks.require(task)]["guide_goal"]
    if goal not in GOALS:
        raise su.ValidationError("неизвестная задача гравировки")
    kind = tasks.require(task) if task is not None else tasks.GOAL_TASK[goal]
    device = devices.get_device(store, device_id)
    if not device.get("lens"):
        raise su.ValidationError("сначала установите линзу на выбранный лазер")
    material = store.one("SELECT * FROM material_profile WHERE id=?", (material_id,))
    if material is None:
        raise su.ValidationError("выберите материал и конкретную заготовку")
    lens_id = device["lens"]["id"]
    findings = [finding for finding in capability_results.findings_for_device(store, device_id)
                if finding["material_id"] == material_id and finding["lens_id"] == lens_id]
    latest = {}
    for finding in findings:
        latest.setdefault(finding["purpose"], finding)
    source = latest.get(goal)
    line = latest.get("line")
    text = latest.get("text")
    title, objective = GOALS[goal]
    base = {"goal": goal, "goal_name": title, "objective": objective, "task": {"kind": kind, "name": tasks.TASKS[kind]["name"]},
            "support": _support(store, source),
            "device": {"id": device_id, "name": device["name"]},
            "lens": {"id": lens_id, "name": device["lens"]["name"]},
            "material": {key: material[key] for key in ("id", "name", "family", "grade", "batch")},
            "finding": source, "plate": None, "status": "needs_test"}
    pending = _pending_plan(store, device_id, material_id, lens_id, goal)
    if pending:
        return base | {"status": "awaiting_photo", "pending_plan_id": pending,
                       "message": "Следующая плата для этой задачи уже создана. Продолжите её вместо повторного создания.",
                       "next_step": "Откройте LightBurn-файл платы, выгравируйте её и добавьте RAW-фото."}
    if goal in {"deep", "relief_3d", "cutting"}:
        details = {
            "deep": "Для глубины нужна измеренная глубина после каждого цикла гравировки и очистки; фото поверхности её не определяет.",
            "relief_3d": "Для рельефа нужна высотная карта/профилометрия, а не только верхняя фотография.",
            "cutting": "Для резки нужны толщина, подтверждение сквозного прохода и оценка кромки; текущие платы измеряют поверхность.",
        }
        return base | {"status": "measurement_needed", "message": details[goal],
                       "next_step": "Добавить измерение глубины/кромки и специальную плату для этой задачи; готовых параметров пока нет."}
    if material["family"] != "Titanium":
        return base | {"status": "cleaning_recipe_needed",
                       "message": "Для этого материала ещё нет проверенного рецепта предварительной очистки. Титановую очистку автоматически применять нельзя.",
                       "next_step": "Сначала сохранить и проверить рецепт очистки для этого материала."}
    if goal == "text":
        if _accepted_runs(store, device_id, material_id, lens_id, "text_readability") >= 3:
            return base | {"status": "manual_review_needed",
                           "message": "Три фототеста надписей уже сделаны. Дальнейшее сужение только по контрасту может ухудшить читаемость.",
                           "next_step": "Сравните реальные буквы и кромки на изделии; отметьте лучший вариант перед следующим тестом."}
        if text and text["status"] == "contrast_candidate":
            candidate = text["evidence"].get("parameters")
            rounds = sum(f["purpose"] == "text" and f["status"] == "contrast_candidate" for f in findings)
            settings = _settings(device, candidate)
            settings["text_spread"] = max(0.06, round(0.20 * (0.7 ** rounds), 3))
            message = ("Следующий маленький тест сужает мощность и скорость вокруг самого контрастного образца. "
                       "Это поиск по контрасту: перед выбором рабочего режима проверьте читаемость букв и края на изделии.")
            basis = text
        else:
            seed = (line["parameters"] if line and line["parameters"] else
                    text["evidence"].get("parameters") if text else None)
            settings = _settings(device, seed)
            message = ("Сравнить надписи при трёх мощностях и трёх скоростях; в каждом режиме три размера шрифта. "
                       "Основа взята из подтверждённой линии." if line and line["parameters"] else
                       "За основу взята различимая линия; отсутствующий в исходном файле Q-Pulse задан по паспорту и должен быть проверен." if seed else
                       "Сравнить надписи при трёх мощностях и трёх скоростях. Используются паспортные базовые значения.")
            basis = text or line
        settings["power"] = min(settings["power"], 83.0)
        settings["speed"] = min(settings["speed"], 8000.0)
        return base | {"status": "candidate_to_test", "message": message,
                       "next_step": "Выгравировать, добавить RAW-фото, проверить совмещение и сравнить буквы A8M.",
                       "plate": {"test_type": "text_readability", "settings": settings,
                                 "source_pair_id": basis["pair_id"] if basis else None}}
    if goal == "line":
        seed = line["parameters"] or line["evidence"].get("parameters") if line else None
        if seed:
            settings = _settings(device, seed)
            power, speed = settings["power"], settings["speed"]
            rounds = _accepted_runs(store, device_id, material_id, lens_id, "material_matrix")
            if rounds >= 3:
                return base | {"status": "manual_review_needed", "message": "Три уточняющие матрицы линий уже измерены.",
                               "next_step": "Сравните следы на металле и повторяемость выбранного режима перед применением."}
            spread = 0.25 * (0.7 ** rounds)
            settings["matrix"] = {"x_axis": "power", "y_axis": "speed", "geometry": "line",
                                  "x_min": round(max(1.0, power * (1 - spread)), 2), "x_max": round(min(100.0, power * (1 + spread)), 2), "x_count": 3,
                                  "y_min": round(max(1.0, speed * (1 - spread * 1.2)), 1),
                                  "y_max": round(min(10000.0, speed * (1 + spread * 1.2)), 1), "y_count": 3}
            return base | {"status": "candidate_to_test", "message": "Уточнить 3 × 3 соседних режима вокруг наблюдаемой линии; недостающий Q-Pulse задан по паспорту и проверяется заново.",
                           "next_step": "Повторить лучшие линии и проверить их различимость на новом RAW-фото.",
                           "plate": {"test_type": "material_matrix", "settings": settings, "source_pair_id": line["pair_id"]}}
        return base | {"message": "Сначала найти область видимых линий на компактной обзорной плате.",
                       "next_step": "Сделать обзорную плату, затем сузить мощность и скорость.",
                       "plate": {"test_type": "compact_capability", "settings": _settings(device), "source_pair_id": None}}
    mapping = {
        "black_mark": ("calibration", "Сравнить яркость участков. Чёрный режим можно выбрать только после проверки на изделии и повторном фото."),
        "white_mark": ("calibration", "Сравнить яркость участков. Светлый режим можно выбрать только после проверки на изделии и повторном фото."),
        "color": ("calibration", "Для выбора цвета нужны RAW-фото с эталонной картой и повторные образцы."),
        "cleaning": ("compact_capability", "Оценить очищенный фон отдельно от тестовых участков; далее нужен отдельный сравнительный тест очистки."),
        "image": ("hatch_interval", "Проверить шаг заливки; позднее нужен образец с деталями и полутонами."),
    }
    test_type, message = mapping[goal]
    if _accepted_runs(store, device_id, material_id, lens_id, test_type):
        return base | {"status": "manual_review_needed",
                       "message": "Базовая плата для этой цели уже измерена. Без отдельной оценки качества повторять её не имеет смысла.",
                       "next_step": "Сравните результат на изделии и уточните критерий: яркость, цвет, равномерность, тонкие детали или степень очистки."}
    return base | {"message": message, "next_step": "Выгравировать небольшую плату и добавить RAW-фото того же изделия.",
                   "plate": {"test_type": test_type, "settings": _settings(device),
                             "source_pair_id": source["pair_id"] if source else None}}
