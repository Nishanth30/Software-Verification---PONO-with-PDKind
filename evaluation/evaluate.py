"""
PDKind vs K-Induction Evaluation Script
Compares pono's built-in k-induction (-e ind) against our PDKind engine (-e pdkind)
across a suite of BTOR2 benchmarks.

Usage:
    # Run against the built-in sample files (default):
    python3 evaluation/evaluate.py

    # Run against a directory of .btor2 / .btor files (bulk mode):
    python3 evaluation/evaluate.py path/to/hwmcc/benchmarks/

Output:
    - Markdown table printed to stdout
    - results.csv written to the evaluation/ directory (for scatter/cactus plots)
"""

import subprocess
import time
import re
import os
import sys
import csv
import glob

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

PONO    = "../build/pono"          # path to binary (run from pono-src/)
BOUND   = 20                      # max unrolling depth for both engines
TIMEOUT = 60                      # seconds per run

# Default sample benchmarks used when no directory is supplied on the CLI.
# Tuple: (display_name, btor2_path_relative_to_pono-src/, expected_verdict)
DEFAULT_BENCHMARKS = [
    ("uv_example",    "samples/uv_example.btor2",    "SAFE"),
    ("uvw_example",   "samples/uvw_example.btor2",   "SAFE"),
    ("xp2",           "samples/xp2.btor2",           "SAFE"),
    ("counter_true",  "samples/counter-true.btor",   "SAFE"),
    ("counter_false", "samples/counter.btor",         "UNSAFE"),
    ("neg_rst_test",  "samples/neg_rst_test.btor2",  "UNSAFE"),
    ("state2input",   "samples/state2input.btor",     "UNSAFE"),
]

EVAL_DIR  = os.path.dirname(os.path.abspath(__file__))   # evaluation/
CSV_PATH  = os.path.join(EVAL_DIR, "results.csv")
PONO_ROOT = os.path.join(EVAL_DIR, "..", "pono-src")     # pono-src/

# --------------------------------------------------------------------------- #
# Benchmark discovery
# --------------------------------------------------------------------------- #

def discover_benchmarks(bench_dir):
    """Return a list of (name, rel_path, 'UNKNOWN') for every .btor2/.btor file
    found recursively under bench_dir (absolute path).
    Expected verdict is 'UNKNOWN' since ground-truth is not available for
    arbitrary suites; the correctness section is skipped in bulk mode."""
    patterns = ["**/*.btor2", "**/*.btor"]
    found = []
    for pat in patterns:
        for path in sorted(glob.glob(os.path.join(bench_dir, pat), recursive=True)):
            rel = os.path.relpath(path, PONO_ROOT)
            name = os.path.splitext(os.path.basename(path))[0]
            found.append((name, rel, "UNKNOWN"))
    return found

# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

def run_engine(engine, benchmark_path, verbosity=2):
    """Run pono with the given engine; return (verdict, elapsed_sec, total_lemmas,
    useful_lemmas, raw_output)."""
    cmd = [PONO, "-e", engine, "-k", str(BOUND), "-v", str(verbosity),
           benchmark_path]
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=TIMEOUT,
            cwd=PONO_ROOT
        )
        elapsed = time.perf_counter() - start
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT", TIMEOUT, 0, 0, ""

    elapsed = time.perf_counter() - start

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

    # Count lemmas (PDKind-specific)
    lemma_lines   = re.findall(r"new lemma at k=(\d+): (.+)", out)
    useful_lemmas = [(k, l) for k, l in lemma_lines if l.strip() != "true"]

    return verdict, elapsed, len(lemma_lines), len(useful_lemmas), out

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    # ---- Determine benchmark list ------------------------------------------ #
    bulk_mode = False
    if len(sys.argv) > 1:
        bench_dir = os.path.abspath(sys.argv[1])
        if not os.path.isdir(bench_dir):
            print(f"ERROR: '{bench_dir}' is not a directory.", file=sys.stderr)
            sys.exit(1)
        benchmarks = discover_benchmarks(bench_dir)
        if not benchmarks:
            print(f"ERROR: no .btor2 or .btor files found under '{bench_dir}'.",
                  file=sys.stderr)
            sys.exit(1)
        bulk_mode = True
        print(f"\nBulk mode: found {len(benchmarks)} benchmark(s) in '{bench_dir}'")
    else:
        benchmarks = DEFAULT_BENCHMARKS

    print(f"\n{'='*90}")
    print(f"  PDKind vs K-Induction Evaluation   (bound={BOUND}, timeout={TIMEOUT}s, "
          f"benchmarks={len(benchmarks)})")
    print(f"{'='*90}\n")

    # ---- Table header ------------------------------------------------------ #
    col = [28, 10, 9, 10, 9, 8, 8, 13]
    hdr = ["Benchmark", "Expected", "KInd", "KInd(s)", "PDKind", "PDK(s)",
           "Lemmas", "Useful Lemmas"]
    print("  " + "  ".join(h.ljust(col[i]) for i, h in enumerate(hdr)))
    print("  " + "-"*96)

    results = []

    for name, path, expected in benchmarks:
        abs_path = os.path.join(PONO_ROOT, path)
        if not os.path.exists(abs_path):
            print(f"  {name:<28} FILE NOT FOUND — skipping")
            continue

        ki_v, ki_t, _,        _,         _      = run_engine("ind",    path)
        pk_v, pk_t, pk_total, pk_useful, pk_out = run_engine("pdkind", path)

        pk_wins = ki_v == "UNKNOWN" and pk_v not in ("UNKNOWN", "TIMEOUT", "ERROR")

        row = [name[:28], expected, ki_v, f"{ki_t:.2f}s", pk_v, f"{pk_t:.2f}s",
               str(pk_total), str(pk_useful)]
        marker = "  ← PDKind wins!" if pk_wins else ""
        print("  " + "  ".join(str(row[i]).ljust(col[i]) for i in range(len(row))) + marker)

        results.append((name, expected, ki_v, ki_t, pk_v, pk_t,
                        pk_total, pk_useful, pk_out))

    print()
    print("  Lemmas = total lemmas generated by PDKind")
    print("  Useful = lemmas that are not trivially 'true' (actually constrain the search)")

    # ---- CSV export -------------------------------------------------------- #
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["benchmark", "expected", "kind_verdict", "kind_time_s",
                         "pdkind_verdict", "pdkind_time_s",
                         "pdkind_lemmas_total", "pdkind_lemmas_useful"])
        for name, expected, ki_v, ki_t, pk_v, pk_t, pk_total, pk_useful, _ in results:
            writer.writerow([name, expected, ki_v, f"{ki_t:.4f}", pk_v, f"{pk_t:.4f}",
                             pk_total, pk_useful])
    print(f"\n  CSV written → {CSV_PATH}")

    # ---- Correctness summary ----------------------------------------------- #
    if not bulk_mode:
        print(f"\n{'='*90}")
        print("  CORRECTNESS CHECK")
        print(f"{'='*90}")
        definitive = [(n, e, ki, pk) for n, e, ki, _, pk, *_ in results
                      if ki not in ("UNKNOWN", "TIMEOUT", "ERROR")
                      and pk not in ("UNKNOWN", "TIMEOUT", "ERROR")]
        agree_count   = sum(1 for _, _, ki, pk in definitive if ki == pk)
        disagree_list = [(n, ki, pk) for n, _, ki, pk in definitive if ki != pk]

        print(f"  Benchmarks with definitive answer from both: {len(definitive)}")
        print(f"  Agreement:                                   {agree_count}/{len(definitive)}")
        if disagree_list:
            print("  DISAGREEMENTS (bug — investigate):")
            for n, ki, pk in disagree_list:
                print(f"    {n}: ind={ki}, pdkind={pk}")
        else:
            print("  No disagreements — PDKind is sound on these benchmarks ✓")

    # ---- PDKind wins ------------------------------------------------------- #
    print(f"\n{'='*90}")
    print("  WHERE PDKIND HELPS")
    print(f"{'='*90}")
    wins = [(n, e, ki, pk, pt)
            for n, e, ki, _, pk, pt, *_ in results
            if ki == "UNKNOWN" and pk not in ("UNKNOWN", "TIMEOUT", "ERROR")]
    if wins:
        for n, e, ki, pk, pt in wins:
            print(f"  {n}: k-induction=UNKNOWN, PDKind={pk} in {pt:.2f}s — "
                  "lemmas broke the deadlock")
    else:
        print("  No benchmarks where PDKind resolved but k-induction could not "
              "(within this bound/suite).")

    # ---- Lemma deep-dive (sample mode only) -------------------------------- #
    if not bulk_mode:
        print(f"\n{'='*90}")
        print("  LEMMA ANALYSIS (PDKind verbose output)")
        print(f"{'='*90}")
        for name, _, _, _, _, _, total, useful, out in results:
            lemma_lines = re.findall(r"(PDKind: (?:new lemma|literal_drop).+)", out)
            proof_line  = re.findall(r"(PDKind: property proved.+)", out)
            if lemma_lines or proof_line:
                print(f"\n  [{name}]")
                for line in lemma_lines[:6]:
                    print(f"    {line}")
                for line in proof_line:
                    print(f"    {line}")
                if total > 0 and useful == 0:
                    print(f"    NOTE: All {total} lemma(s) were trivially 'true' — "
                          "literal_drop found no essential literals.")

    # ---- Summary stats ----------------------------------------------------- #
    print(f"\n{'='*90}")
    print("  SUMMARY")
    print(f"{'='*90}")
    total_run = len(results)
    ki_solved  = sum(1 for r in results
                     if r[2] not in ("UNKNOWN", "TIMEOUT", "ERROR"))
    pk_solved  = sum(1 for r in results
                     if r[4] not in ("UNKNOWN", "TIMEOUT", "ERROR"))
    timeouts   = sum(1 for r in results
                     if r[2] == "TIMEOUT" or r[4] == "TIMEOUT")
    print(f"  Total benchmarks run : {total_run}")
    print(f"  K-Induction solved   : {ki_solved}  ({100*ki_solved//max(total_run,1)}%)")
    print(f"  PDKind solved        : {pk_solved}  ({100*pk_solved//max(total_run,1)}%)")
    print(f"  PDKind wins          : {len(wins)}")
    print(f"  Timeouts (either)    : {timeouts}")
    print()

if __name__ == "__main__":
    # Always resolve paths relative to the repo root, not cwd.
    os.chdir(os.path.join(EVAL_DIR, ".."))
    main()
