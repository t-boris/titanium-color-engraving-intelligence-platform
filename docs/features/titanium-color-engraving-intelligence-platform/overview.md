---
type: feature
id: titanium-color-engraving-intelligence-platform
title: Titanium Color Engraving Intelligence Platform
status: implementing
owner: Boris Tsekinovsky
created: 2026-10-14
provenance: Created from the new-project intake
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: known
  Permissions: known
  Failure Scenarios: known
  Data Model: known
  Notifications: n/a
  Security: n/a
  Analytics: partial
  Dependencies: known
  Acceptance Criteria: known
understanding_notes:
  Problem: Плохая воспроизводимость цвета на титане; нужен замкнутый цикл обучения с измерениями как источником истины.
  Target Users: Один исследователь/мастер с одним лазером (DEC-001).
  Primary Workflow: Единая единица ввода — пара «LightBurn-файл + фото на стенде с эталоном» для плат и готовых работ; маркеры → автовыравнивание, иначе по углам.
  Permissions: Ролей нет, локальное однопользовательское приложение.
  Failure Scenarios: Фото без эталона отклоняется; недостижимые цвета → Designer; production-цвет «под вопросом» исключается из планов.
  Data Model: Наблюдение = параметры из файла + цвет из скорректированного фото + стадия зрелости + опциональный контекст. Отдельного legacy-уровня нет (DEC-012 заменено).
  Notifications: Не требуется для локального инструмента.
  Security: Локальные данные, один пользователь.
  Analytics: Стабильность/повторяемость и покрытие цветового пространства описаны; конкретные отчёты определит исполнитель.
  Dependencies: LightBurn (.lbrn/.lbrn2), фотостенд с эталонной картой, RAW-камера; опциональный LLM для пояснений.
  Acceptance Criteria: Критерии зафиксированы в REQ-001…REQ-016.
questions_left: 0
confirmed: 2026-10-14
---

# Titanium Color Engraving Intelligence Platform

## Idea

An experimental, data-driven platform that learns the relationship between laser parameters and the colors they produce on titanium from physical calibration experiments, and uses that learned model to generate engraving plans for artwork (discrete colors) and photographs (continuous luminance-driven parameters). It runs as a closed loop — experiment → engraving → photograph → measurement → comparison → model update → next experiment — with physical measurements as the source of truth, every prediction carrying confidence/error/stability, knowledge promoted to production only after repeated observations, and an AI Experiment Designer proposing the next calibration plates.

## Problem

Laser color marking on titanium is poorly reproducible: the same nominal parameters can yield different colors depending on material batch, laser, focus and environment, and colors are discovered by trial and error. Today there is no tool that systematically captures calibration results, aligns photographs of plates to the parameter grid without manual error, quantifies uncertainty and stability of each color, and turns that knowledge into engraving plans for real artwork and photos — nor one that tells the operator which experiment to run next.

## Scope

IN (first version, as stated by the user): material and laser profiles; calibration plate generation with registration markers and experiment identifier; photographing plates and CV-based alignment of cell ↔ parameter set; color measurement and experiment database; color-space model with confidence, expected color error and stability; parameter prediction; stability & reproducibility analysis; knowledge maturation pipeline (measured → candidate → repeated → validated → production); AI Experiment Designer; discrete-color artwork conversion; continuous photo engraving via calibrated transfer function; internal EngravingPlan format; LightBurn integration; post-engraving analysis and continuous learning. Deliverable of the first step is a full Product + System Specification in Markdown, not code.

OUT (not stated / assumed out until decided): direct laser control or firmware; automatic application of model updates to production profiles after a single observation; exact color reproduction guarantees; non-titanium materials; multi-tenant cloud service; hardware (camera, colorimeter) procurement.
