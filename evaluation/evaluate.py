#!/usr/bin/env python3
"""
Pono Engine Comparison Evaluation Script (Refactored)
=====================================================
Dynamically discovers all .btor/.btor2 benchmarks and compares:
  - K-Induction (-e ind, -k 20)
  - PDKind      (-e pdkind, -k 20)
  - IC3/PDR      (-e mbic3, -k 500) [Gold Standard]

Usage:
    python3 evaluation/evaluate.py
"""

import subprocess
import time
import re
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

EVAL_DIR  = Path(__file__).resolve().parent
PONO_ROOT = EVAL_DIR.parent / "pono-src"
PONO      = str(PONO_ROOT / "build" / "pono")
SAMPLES   = PONO_ROOT / "samples"

KIND_BOUND = 20
IC3_BOUND  = 500
TIMEOUT    = 60

ENGINE_RUNS = {
    "ic3": ("mbic3", IC3_BOUND),
    "kind": ("ind", KIND_BOUND),
    "pdkind": ("pdkind", KIND_BOUND),
}

SOLVED_VERDICTS = ("SAFE", "UNSAFE")

TABLE_COLUMNS = [
    ("Benchmark", 30),
    ("Expected(IC3)", 14),
    ("IC3 Time", 10),
    ("K-Ind Verdict", 13),
    ("K-Ind Time", 10),
    ("PDK Verdict", 11),
    ("PDK Time", 10),
    ("PDK Lemmas", 10),
    ("PDK Useful", 10),
]
TABLE_GAP = "  "

# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

def run_engine(engine, benchmark_path, bound, verbosity=2):
    """Run pono with the given engine and bound."""
    cmd = [PONO, "-e", engine, "-k", str(bound), "-v", str(verbosity),
           benchmark_path]
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT,
            cwd=str(PONO_ROOT)
        )
        elapsed = time.perf_counter() - start
        # Combine stdout and stderr for parsing
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT", TIMEOUT, 0, 0, ""

    # Parse verdict
    out_lower = out.lower()
    if "unsat" in out_lower:
        verdict = "SAFE"
    elif "sat" in out_lower and "unsat" not in out_lower:
        verdict = "UNSAFE"
    elif "unknown" in out_lower:
        verdict = "UNKNOWN"
    else:
        verdict = "ERROR"

    # Count lemmas (PDKind-specific diagnostics usually in stderr with -v 2)
    lemma_useful   = len(re.findall(r"PDKind: new lemma at k=", out))
    lemma_trivial  = len(re.findall(r"discarding trivially-true lemma", out))
    lemma_total    = lemma_useful + lemma_trivial

    return verdict, elapsed, lemma_total, lemma_useful, out


def worker_count():
    """Return the number of concurrent engine processes to run."""
    configured = os.environ.get("PONO_EVAL_WORKERS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            print(f"WARNING: Ignoring invalid PONO_EVAL_WORKERS={configured!r}")

    return max(1, min(32, os.cpu_count() or 1))


def truncate_cell(value, width):
    """Keep table cells inside their fixed-width column."""
    text = str(value)
    if len(text) <= width:
        return text
    return text[:width - 3] + "..."


def format_cell(value, width):
    """Format a fixed-width table cell after clean truncation."""
    text = truncate_cell(value, width)
    return f"{text:<{width}}"


def format_table_row(values):
    """Format one output row with stable column widths."""
    return "  " + TABLE_GAP.join(
        format_cell(value, width)
        for value, (_, width) in zip(values, TABLE_COLUMNS)
    )


def format_elapsed(seconds):
    """Format engine runtime for table output."""
    return f"{seconds:.2f}s"


def build_result_row(name, results):
    """Build display fields and marker for one completed benchmark."""
    ic_v, ic_t, _, _, _ = results["ic3"]
    ki_v, ki_t, _, _, _ = results["kind"]
    pk_v, pk_t, pk_tot, pk_use, _ = results["pdkind"]

    row = [
        name,
        ic_v,
        format_elapsed(ic_t),
        ki_v,
        format_elapsed(ki_t),
        pk_v,
        format_elapsed(pk_t),
        str(pk_tot),
        str(pk_use),
    ]

    marker = ""
    # PDKind win: PDKind solved, K-Induction didn't
    if ki_v not in SOLVED_VERDICTS and pk_v in SOLVED_VERDICTS:
        marker = "  ← PDKind win!"

    # Soundness check: Disagrees with ground truth
    if ic_v in SOLVED_VERDICTS and pk_v in SOLVED_VERDICTS and pk_v != ic_v:
        marker = "  ← FAIL (Soundness Bug!)"

    return row, marker


def run_parallel_benchmarks(benchmarks):
    """Run all engine/benchmark jobs concurrently and print rows as they finish."""
    results_by_benchmark = {
        index: {"name": name, "results": {}}
        for index, (name, _) in enumerate(benchmarks)
    }
    pdkind_solved = 0
    kind_solved = 0

    with ThreadPoolExecutor(max_workers=worker_count()) as executor:
        future_to_job = {}
        for index, (_, path) in enumerate(benchmarks):
            for engine_key, (engine, bound) in ENGINE_RUNS.items():
                future = executor.submit(run_engine, engine, path, bound)
                future_to_job[future] = (index, engine_key)

        for future in as_completed(future_to_job):
            index, engine_key = future_to_job[future]
            benchmark = results_by_benchmark[index]

            try:
                benchmark["results"][engine_key] = future.result()
            except Exception as exc:
                benchmark["results"][engine_key] = ("ERROR", 0.0, 0, 0, str(exc))

            if len(benchmark["results"]) != len(ENGINE_RUNS):
                continue

            row, marker = build_result_row(benchmark["name"], benchmark["results"])
            print(format_table_row(row) + marker, flush=True)

            ki_v = benchmark["results"]["kind"][0]
            pk_v = benchmark["results"]["pdkind"][0]
            if pk_v in SOLVED_VERDICTS:
                pdkind_solved += 1
            if ki_v in SOLVED_VERDICTS:
                kind_solved += 1

    return kind_solved, pdkind_solved

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    # 1. Dynamic Discovery
    benchmarks = []
    for ext in ("**/*.btor2", "**/*.btor"):
        for p in sorted(SAMPLES.glob(ext)):
            rel = str(p.relative_to(PONO_ROOT))
            name = p.stem
            # Include parent directory if it's a sub-folder of samples
            parts = p.relative_to(SAMPLES).parts
            if len(parts) > 1:
                name = f"{parts[-2]}/{p.stem}"
            benchmarks.append((name, rel))

    if not benchmarks:
        print(f"ERROR: No .btor2/.btor files found in {SAMPLES}")
        sys.exit(1)

    # 2. Header
    table_width = (
        2
        + sum(width for _, width in TABLE_COLUMNS)
        + len(TABLE_GAP) * (len(TABLE_COLUMNS) - 1)
    )
    width = max(135, table_width + 24)
    print(f"\n{'='*width}")
    print(f"  Pono Engine Comparison   (K-Ind/PDKind Bound={KIND_BOUND}, IC3 Bound={IC3_BOUND}, Timeout={TIMEOUT}s)")
    print(f"{'='*width}\n")

    hdr = [header for header, _ in TABLE_COLUMNS]
    print(format_table_row(hdr))
    print("  " + "-"*(width-4))

    # 3. Execution
    kind_solved, pdkind_solved = run_parallel_benchmarks(benchmarks)

    # 4. Metrics Summary
    total = len(benchmarks)
    print(f"\n{'='*width}")
    print("  METRICS SUMMARY")
    print(f"{'='*width}")
    print(f"  K-Induction solved : {kind_solved}/{total} ({100*kind_solved//total if total > 0 else 0}%)")
    print(f"  PDKind solved      : {pdkind_solved}/{total} ({100*pdkind_solved//total if total > 0 else 0}%)")
    print()

    # 5. Theoretical Capability Table
    print("""=================================================================================
  THEORETICAL CAPABILITY SUMMARY (Algorithm vs. Features)
=================================================================================
Algorithm       | Proves Safe | Handles CTI | Learns Lemmas | Generalizes | Agnostic
---------------------------------------------------------------------------------
BMC             |      X      |      X      |       X       |      X      |   ✓
K-Induction     |     ✓*      |      X      |       X       |      X      |   ✓
PDKind (Ours)   |      ✓      |      ✓      |       ✓       |   Partial   |   ✓
IC3 / PDR       |      ✓      |      ✓      |       ✓       |     Full    |   ✓
---------------------------------------------------------------------------------
* K-Induction fails to prove safety when CTIs exist in the inductive region.""")

if __name__ == "__main__":
    main()
