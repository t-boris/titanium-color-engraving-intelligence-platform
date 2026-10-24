"""Measure the laboratory exchange on this machine (electron REQ-083, REQ-084): a workshop of N area-fill measurements is written as a
``.tcelab`` release, read whole, built into a snapshot and connected by another workshop; each step reports its time, its peak traced
memory and the sizes it produces. The results go into ``docs/features/electron/benchmarks/`` as evidence of the resource policy.

    .venv/bin/python tools/bench_tcelab.py --sizes 10000 50000 500000 --out docs/features/electron/benchmarks/

Sizes above the default policy's limits are measured with a policy that allows them (``--unlimited``), so that the limits can be set
from what was measured rather than the other way round.
"""
from __future__ import annotations

import argparse
import gc
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import labworld  # noqa: E402
from titanium_platform import __version__, lab_export, lab_format as lf, lab_import, lab_snapshot  # noqa: E402
from titanium_platform.db import Store  # noqa: E402

UNLIMITED = lf.ResourcePolicy(max_bytes=1 << 40, max_records={s: 1 << 31 for s in lf.SECTIONS})


MEMORY = True                  # --no-memory: time only (tracing the allocator slows a step two to three times)


def measured(run, again=None) -> dict:
    """What a step took: seconds of wall clock without tracing, then (unless ``--no-memory``) the peak bytes Python's allocator traced in
    a second run of ``again`` (``run`` itself when not given), since tracing slows the step."""
    gc.collect()
    started = time.perf_counter()
    result = run()
    seconds = time.perf_counter() - started
    peak = None
    if MEMORY:
        gc.collect()
        tracemalloc.start()
        tracemalloc.reset_peak()
        try:
            (again or run)()
        finally:
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
    return {"seconds": round(seconds, 2), "peak_mb": None if peak is None else round(peak / 1e6, 1), "result": result}


def folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def hardware() -> dict:
    out = {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(), "app": __version__}
    if sys.platform == "darwin":
        for key, name in (("hw.model", "model"), ("machdep.cpu.brand_string", "cpu"), ("hw.memsize", "memory_bytes")):
            try:
                out[name] = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
    return out


def bench(size: int, policy: lf.ResourcePolicy, keep_dir: Path | None) -> dict:
    base = Path(tempfile.mkdtemp(prefix=f"tcelab-bench-{size}-"))
    try:
        author = Store(base / "author")
        prepared = measured(lambda: labworld.bulk(author, base / "author" / "files", size), lambda: None)   # once: it fills the workshop
        lab_export.set_public_info(author, {"name": "Benchmark laboratory", "author": "bench_tcelab.py"})
        path = base / "release.tcelab"
        again = base / "release-again.tcelab"
        export = measured(lambda: lab_export.export(author, path, None, "CC-BY-4.0", policy=policy),
                          lambda: lab_export.export(author, again, None, "CC-BY-4.0", policy=policy))
        author.close()
        again.unlink(missing_ok=True)
        temp_before = folder_bytes(base)

        def read_whole() -> int:
            n = 0
            with open(path, "rb") as fh:
                for _ in lf.read(fh, policy=policy):
                    n += 1
            return n
        read = measured(read_whole)

        def build(folder: Path = base / "snapshot") -> dict:
            with open(path, "rb") as fh:
                return lab_snapshot.build(folder, fh, policy=policy)
        built = measured(build, lambda: build(base / "snapshot-again"))
        shutil.rmtree(base / "snapshot-again", ignore_errors=True)
        snapshot_bytes = folder_bytes(base / "snapshot")
        progress: list[tuple[float, int]] = []

        def connect(folder: Path = base / "reader") -> dict:
            reader = Store(folder)
            try:
                token = lab_import.stage(reader, _chunks(path), policy)
                job = lab_import.start(reader, token, wait=False, policy=policy)
                started = time.perf_counter()
                while not job["done"]:
                    time.sleep(0.05)
                    job = lab_import.status(job["id"])
                    progress.append((time.perf_counter() - started, job["read"]))
                return job
            finally:
                reader.close()
        connected = measured(connect, lambda: connect(base / "reader-again"))
        shutil.rmtree(base / "reader-again", ignore_errors=True)
        gaps = [b[0] - a[0] for a, b in zip(progress, progress[1:]) if b[1] != a[1]]
        out = {"measurements": size, "captures": prepared["result"]["pairs"], "file_bytes": path.stat().st_size,
               "prepare": _step(prepared), "export": _step(export), "read": _step(read), "build_snapshot": {**_step(built), "snapshot_bytes": snapshot_bytes},
               "connect": {**_step(connected), "phase": connected["result"]["phase"], "error": connected["result"].get("error"),
                           "progress_updates": len(progress), "longest_gap_between_progress_s": round(max(gaps), 2) if gaps else None},
               "temporary_disk_bytes": temp_before + snapshot_bytes + folder_bytes(base / "reader")}
        if keep_dir is not None:
            shutil.copyfile(path, keep_dir / f"release-{size}.tcelab")
        return out
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _chunks(path: Path):
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(lab_import.CHUNK)
            if not chunk:
                return
            yield chunk


def _step(step: dict) -> dict:
    return {"seconds": step["seconds"], "peak_mb": step["peak_mb"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10000, 50000])
    parser.add_argument("--out", type=Path, help="folder for the JSON and Markdown results")
    parser.add_argument("--unlimited", action="store_true", help="measure with a policy that allows any size")
    parser.add_argument("--keep-files", type=Path, help="folder to keep the written releases in")
    parser.add_argument("--no-memory", action="store_true", help="time only: do not trace the allocator in a second run of each step")
    args = parser.parse_args()
    global MEMORY
    MEMORY = not args.no_memory
    policy = UNLIMITED if args.unlimited else lf.DEFAULT_POLICY
    report = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hardware": hardware(),
              "policy": "unlimited" if args.unlimited else "default", "runs": []}
    for size in args.sizes:
        run = bench(size, policy, args.keep_files)
        report["runs"].append(run)
        print(json.dumps(run), flush=True)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = report["measured_at"][:10] + ("" if MEMORY else "-time")
        (args.out / f"tcelab-{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (args.out / f"tcelab-{stamp}.md").write_text(markdown(report), encoding="utf-8")
    return 0


def markdown(report: dict) -> str:
    hw = report["hardware"]
    lines = [f"# .tcelab benchmark, {report['measured_at'][:10]}", "",
             f"Hardware: {hw.get('model', hw['machine'])}, {hw.get('cpu', '')}, {int(hw.get('memory_bytes', 0) or 0) // 2**30} GB; "
             f"{hw['platform']}; Python {hw['python']}; app {hw['app']}. Policy: {report['policy']}.", "",
             "| measurements | file MB | export s / peak MB | read s / peak MB | snapshot s / peak MB / MB | connect s / peak MB / outcome | progress gap s | temp disk MB |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in report["runs"]:
        outcome = r["connect"]["phase"] + (f" ({r['connect']['error']['code']})" if r["connect"].get("error") else "")
        lines.append(f"| {r['measurements']} | {r['file_bytes'] / 1e6:.1f} | {r['export']['seconds']} / {r['export']['peak_mb']} | "
                     f"{r['read']['seconds']} / {r['read']['peak_mb']} | {r['build_snapshot']['seconds']} / {r['build_snapshot']['peak_mb']} / "
                     f"{r['build_snapshot']['snapshot_bytes'] / 1e6:.1f} | {r['connect']['seconds']} / {r['connect']['peak_mb']} / {outcome} | "
                     f"{r['connect']['longest_gap_between_progress_s']} | {r['temporary_disk_bytes'] / 1e6:.0f} |")
    lines += ["", "Seconds are wall clock without tracing; peak memory is what Python's allocator traced in a second run of the step (tracemalloc), "
              "the SQLite page cache outside it; None when the run was timed only.",
              "Reading and building a snapshot do not grow with the release; writing one keeps its indices (identity, role, label per measurement)."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
