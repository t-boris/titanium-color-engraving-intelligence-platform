---
type: feature
id: desktop-macos-windows
title: "Публичная desktop-бета: выпуск и проверка macOS и Windows"
status: draft
owner: Boris Tsekinovsky
created: 2026-11-05
provenance: Created by an AI agent through MarkView from Выделено из electron / REQ-080, REQ-082, REQ-086; tasks/todo.md, Review 2026-10-24; решение пользователя 2026-11-05.
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: known
  Permissions: known
  Failure Scenarios: known
  Data Model: known
  Notifications: known
  Security: partial
  Analytics: n/a
  Dependencies: partial
  Acceptance Criteria: known
---

# Публичная desktop-бета: выпуск и проверка macOS и Windows

## Idea

Довести выпущенное внутреннее приложение Electron и облачный обмен лабораториями до публичной беты для macOS Apple Silicon и Windows x64. Остаток: подпись Windows и notarization macOS, проверяемые обновления, минимальные версии ОС и проверки установщиков на чистых машинах, LAN и вход через системный браузер на обеих платформах, восстановление аккаунта и подтверждение условий использования на карточках выпусков. Подписанные обновления устанавливаются только на безопасной границе операций и сохраняют мастерскую. Реализация и повторная проверка отсутствующего остаются открытыми; эта фича не объявляет публичную бету выпущенной. Исходная фича electron закрывает реализованный внутренний выпуск 0.29.0–0.31.1 и последующие исправления.

## Problem

## Scope
