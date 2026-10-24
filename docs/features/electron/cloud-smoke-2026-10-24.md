# Cloud smoke test — 2026-10-24 17:14 UTC

Target: `http://127.0.0.1:56177` (local uvicorn, in-memory catalogue). Tool: `tools/cloud_smoke.py`. Result: **passed**.

| Step | Result | Detail | ms |
|---|---|---|---:|
| build a workshop | ok | 60 measurements, origin 6a7a9a5d… | 3 |
| GET /health | ok | 0.1.0 | 2 |
| POST /labs | ok | 3c083663-95cc-47c6-bdbf-e1d9472227d7 | 3 |
| POST /labs/{id}/publications | ok | release 62c0f7c5… number 1, chunks of 1048576 bytes | 2 |
| export the release with the reserved identity | ok | 35998 bytes | 17 |
| PUT /publications/{id}/chunks/{n} | ok | 1 chunks | 2 |
| POST /publications/{id}/finalize | ok | release 62c0f7c5… number 1, 60 measurements | 11 |
| GET /labs/{id} and /releases/{id}/manifest without a token | ok | latest release and manifest agree | 4 |
| GET /releases/{id}/chunks/{n} with urllib | ok | 1 chunks, 35998 bytes, hash agrees | 2 |
| lab_import.stage/start into a second workshop | ok | connected as source «Smoke laboratory» | 29 |
| release_palette equals the author's vector_palette | ok | 60 colours agree | 20 |
| POST /releases/{id}/withdraw and GET /withdrawals | ok | measurement c113b1cd… withdrawn and listed | 6 |

Laboratory `3c083663-95cc-47c6-bdbf-e1d9472227d7`, release `62c0f7c5-b82e-4b64-8879-6f0ce1cb350d` number 1, 35998 bytes in 1 chunks, counts {"captures": 6, "equipment": 1, "materials": 1, "measurements": 60, "provenance": 0, "tone_profiles": 0}.

The author's workshop and the reader's were temporary folders; nothing of this run is kept but this note and the rows on the service.
