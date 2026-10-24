# Cloud smoke test — 2026-10-24 17:25 UTC

Target: `https://titanium-labs-api.vercel.app` (deployment). Tool: `tools/cloud_smoke.py`. Result: **passed**.

| Step | Result | Detail | ms |
|---|---|---|---:|
| build a workshop | ok | 60 measurements, origin c4f6edde… | 3 |
| GET /health | ok | 0.1.0 | 251 |
| POST /labs | ok | c9197ac4-ce2b-405f-aa43-fff73c1bcc02 | 521 |
| POST /labs/{id}/publications | ok | release 9f86aff5… number 1, chunks of 1048576 bytes | 234 |
| export the release with the reserved identity | ok | 35999 bytes | 16 |
| PUT /publications/{id}/chunks/{n} | ok | 1 chunks | 275 |
| POST /publications/{id}/finalize | ok | release 9f86aff5… number 1, 60 measurements | 301 |
| GET /labs/{id} and /releases/{id}/manifest without a token | ok | latest release and manifest agree | 430 |
| GET /releases/{id}/chunks/{n} with urllib | ok | 1 chunks, 35999 bytes, hash agrees | 219 |
| lab_import.stage/start into a second workshop | ok | connected as source «Smoke laboratory» | 29 |
| release_palette equals the author's vector_palette | ok | 60 colours agree | 19 |
| POST /releases/{id}/withdraw and GET /withdrawals | ok | measurement e0201c05… withdrawn and listed | 481 |

Laboratory `c9197ac4-ce2b-405f-aa43-fff73c1bcc02`, release `9f86aff5-ecea-4bd1-9037-62b442febdce` number 1, 35999 bytes in 1 chunks, counts {"captures": 6, "equipment": 1, "materials": 1, "provenance": 0, "measurements": 60, "tone_profiles": 0}.

The author's workshop and the reader's were temporary folders; nothing of this run is kept but this note and the rows on the service.
