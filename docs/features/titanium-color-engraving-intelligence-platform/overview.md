---
type: feature
id: titanium-color-engraving-intelligence-platform
title: Titanium Color Engraving Intelligence Platform
status: implemented
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
  Dependencies: partial
  Acceptance Criteria: known
understanding_notes:
  Problem: "Цель и источник истины определены: воспроизводимость цвета оценивается по физическим наблюдениям."
  Target Users: Один оператор-исследователь, локальная лаборатория.
  Primary Workflow: Настройки задаются на плате или плане; отдельное создание профиля больше не требуется. Пара LightBurn + фото сохраняется.
  Permissions: Ролей нет; перевод в production остаётся явным действием оператора.
  Failure Scenarios: Неизвестные параметры, спорные значения контроллера, расхождения файла и платы и смена линзы имеют определённое поведение.
  Data Model: Устройство хранит факты оборудования, каждая работа — настройки LightBurn, намерение гравировки, материал/партию, линзу, изображение и измеренный результат. Рекомендации являются отдельными выводами со ссылками на подтверждающие наблюдения.
  Notifications: Достаточно предусмотренных предупреждений в интерфейсе; отдельные уведомления не требуются.
  Security: Ответы не меняют принятую локальную модель приложения без авторизации.
  Analytics: Правила разделения данных определены; оптимальность 200 нс и точность физических оценок ещё не подтверждены экспериментами.
  Dependencies: Стек и LightBurn определены. По README экспорт в LightBurn и измерение реального RAW-снимка стенда ещё требуют проверки.
  Acceptance Criteria: Спецификацию можно записать сейчас; неизвестные характеристики оборудования не требуют новых продуктовых вопросов.
questions_left: 0
confirmed: 2026-10-14
---

# Titanium Color Engraving Intelligence Platform

## Idea

An experimental, data-driven platform that learns how a specific laser, historical lens and titanium stock respond to LightBurn settings for different engraving tasks — text, vector lines, filled artwork, tonal images and color images. It maps job intent and geometry plus process parameters to measured results, then retrieves evidence-backed strategies for a new job. Its eventual workflow is image → interpretation and vector artwork → task-specific engraving plan → LightBurn file → physical engraving → photograph and measurement → comparison with the source and plan → updated knowledge → proposed next experiment. Physical observations remain the source of truth; recommendations carry their evidence, confidence and limits. The experiment designer identifies useful gaps and proposes targeted plates, while the operator decides what to engrave and what knowledge is ready for production.

## Problem

Laser color marking on titanium is poorly reproducible: the same nominal parameters can yield different colors depending on material batch, laser, focus and environment, and colors are discovered by trial and error. Today there is no tool that systematically captures calibration results, aligns photographs of plates to the parameter grid without manual error, quantifies uncertainty and stability of each color, and turns that knowledge into engraving plans for real artwork and photos — nor one that tells the operator which experiment to run next.

## Scope

IN: a laser- and lens-linked experiment database that stores the complete LightBurn job, task intent, titanium identity and batch, original image/files, and observed outcome; calibration plates with the required cleaning pass and registration markers; photo alignment and measurement; separate, evidence-backed mappings for color, text, lines, fills and image engraving; confidence, error and repeatability; a knowledge maturation pipeline; analysis of accumulated results; proposals for informative follow-up experiments; image-to-vector preparation; task-specific EngravingPlans; LightBurn integration; and a closed feedback loop from generated and imported work.

OUT (not stated / assumed out until decided): direct laser control or firmware; automatic application of model updates to production profiles after a single observation; exact color reproduction guarantees; non-titanium materials; multi-tenant cloud service; hardware (camera, colorimeter) procurement.
