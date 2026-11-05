---
type: feature
id: feature
title: Обрезать фотоработу под пластину
status: draft
owner: Boris Tsekinovsky
created: 2026-11-05
provenance: Created by an AI agent through MarkView from Выделено из work-size-and-splitting-a-region-again / REQ-003 по решению пользователя 2026-11-05 («так и сделай»).
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: known
  Permissions: unknown
  Failure Scenarios: partial
  Data Model: partial
  Notifications: unknown
  Security: unknown
  Analytics: unknown
  Dependencies: known
  Acceptance Criteria: known
---

# Обрезать фотоработу под пластину

## Idea

Оператор задаёт ширину и высоту пластины и перемещает рамку соответствующих пропорций по изображению сохранённой фотоработы. Работа обрезается по рамке с сохранением оставшихся областей, надписей и фотозон; действие отменяется через историю. Это оставшийся этап исходной фичи work-size-and-splitting-a-region-again: изменение размера «Вписать» и повторное разбиение области уже выпущены в 0.36.0 и 0.37.0. Кадрирование ещё не реализовано.

## Problem

## Scope
