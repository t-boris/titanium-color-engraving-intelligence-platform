# .tcelab benchmark, 2026-10-24

Hardware: Mac14,14, Apple M2 Ultra, 128 GB; macOS-27.0.1-arm64-arm-64bit; Python 3.12.2; app 0.28.0. Policy: unlimited.

| measurements | file MB | export s / peak MB | read s / peak MB | snapshot s / peak MB / MB | connect s / peak MB / outcome | progress gap s | temp disk MB |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 500000 | 289.6 | 88.53 / None | 55.35 / None | 96.41 / None / 424.5 | 576.91 / None / done | 0.06 | 1797 |

Seconds are wall clock without tracing; peak memory is what Python's allocator traced in a second run of the step (tracemalloc), the SQLite page cache outside it; None when the run was timed only.
Reading and building a snapshot do not grow with the release; writing one keeps its indices (identity, role, label per measurement).
