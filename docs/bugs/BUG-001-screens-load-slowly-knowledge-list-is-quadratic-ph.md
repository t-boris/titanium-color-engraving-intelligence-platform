---
type: bug
id: BUG-001
title: "Screens load slowly: knowledge list is quadratic, photographs are re-rendered from RAW on every request"
status: fixed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-19
updated: 2026-10-24
provenance: Created by an AI agent through MarkView
---

# Screens load slowly: knowledge list is quadratic, photographs are re-rendered from RAW on every request

## Summary

On the local application (0.5.1, real data: 343 knowledge entries, 17 experiments) the Knowledge screen takes 6.8 s, the experiments list loads 17 thumbnails of 0.6-1.0 s and about 2 MB each (34 MB per visit), and every photograph or overlay of an experiment takes 3.3 s. Causes: knowledge.list_for_setup calls get() per entry and every get() recomputes model.knowledge_summaries for the whole setup (O(N^2)); ingest.photo_preview_png and overlay_png decode the RAW (and for a corrected picture the 16-bit linear RAW plus the chart correction) on every request, with no cache, and the list asks for full-size previews.

## Steps to reproduce

1. Open the Knowledge screen for laser 1 with lens 2: GET /api/knowledge?device_id=1&lens_id=2 takes 6.8 s
2. Open Experiments: each GET /api/pairs/{id}/photo.png?visibility=lifted takes 0.6-1.0 s and returns about 2 MB
3. Open an experiment: GET /api/pairs/59/overlay.png?corrected=true takes 3.3 s, every time

## Expected

A local screen opens in well under a second: the knowledge list in under 0.5 s, the experiments list in under 1 s once its pictures were rendered, and a picture already rendered in under 50 ms.

## Actual

6.8 s for the knowledge list, 10-17 s and 34 MB for the experiments list, 3.3 s per photograph on an experiment page, on every visit.

## Environment

titanium-platform 0.5.1 installed wheel, port 8765, macOS, data dir ~/.titanium-platform (measured 2026-10-19 with curl, GET only)

## Resolution

Fixed in 0.5.2 (PR #29): the knowledge list reads the summaries and events of a setup once (c9d9235); drawn photographs and
overlays are cached on disk with an ETag, and the lists ask for small sizes (a6ddfe3); `titanium-platform warm-cache` draws the screens'
default pictures ahead (8424062). Tests: `tests/test_knowledge.py`, `tests/test_render_cache.py`.

Verified 2026-10-24 on 0.28.0: the tests named pass (70 passed), and the full suite passes (2015 passed, none skipped). Measured on the live app (GET only): the knowledge list 0.16 s (was 6.8 s), the experiments list 0.30 s with
thumbnails of about 290 KB in 2-3 ms each (were 2 MB in 0.6-1.0 s), an overlay already drawn 5-7 ms (was 3.3 s every time). A picture
never drawn before still takes 3.7-4.6 s once, while its RAW is decoded; afterwards it comes from the cache.
