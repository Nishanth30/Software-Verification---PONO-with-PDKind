"""
Pono Engine Comparison Evaluation Script
Compares:
  - k-induction (-e ind)
  - PDKind engine (-e pdkind)
  - IC3 (mbic3)
across a suite of BTOR2 benchmarks.

Hierarchy expectation: K-Induction < PDKind <= IC3

Usage:
    python3 evaluation/evaluate.py
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

PONO       = "../build/pono"       # path to binary (run from pono-src/)
KIND_BOUND = 20                   # bound for K-Induction and PDKind
IC3_BOUND  = 500                  # IC3 is complete, so we give it more depth
TIMEOUT    = 60                   # seconds per run

# Default sample benchmarks used when no directory is supplied on the CLI.
DEFAULT_BENCHMARKS = [
    ("uv_example",    "samples/uv_example.btor2",    "SAFE"),
    ("uvw_example",   "samples/uvw_example.btor2",   "SAFE"),
    ("xp2",           "samples/xp2.btor2",           "SAFE"),
    ("counter_true",  "samples/counter-true.btor",   "SAFE"),
    ("counter_false", "samples/counter.btor",         "UNSAFE"),
    ("neg_rst_test",  "samples/neg_rst_test.btor2",  "UNSAFE"),
    ("state2input",   "samples/state2input.btor",     "UNSAFE"),
]

EVAL_DIR  = os.path.dirname(os.path.abspath(__file__))
CSV_PATH  = os.path.join(EVAL_DIR, "results.csv")
PONO_ROOT = os.path.join(EVAL_DIR, "..", "pono-src")

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
            cwd=PONO_ROOT
        )
        elapsed = time.perf_counter() - start
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

    # Count lemmas (PDKind-specific)
    lemma_lines   = re.findall(r"new lemma at k=(\d+): (.+)", out)
    useful_lemmas = [(k, l) for k, l in lemma_lines if l.strip() != "true"]

    return verdict, elapsed, len(lemma_lines), len(useful_lemmas), out

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    benchmarks = DEFAULT_BENCHMARKS
    if len(sys.argv) > 1:
        # Simple discovery if dir provided
        bench_dir = os.path.abspath(sys.argv[1])
        if os.path.isdir(bench_dir):
            patterns = ["**/*.btor2", "**/*.btor"]
            benchmarks = []
            for pat in patterns:
                for path in sorted(glob.glob(os.path.join(bench_dir, pat), recursive=True)):
                    rel = os.path.relpath(path, PONO_ROOT)
                    name = os.path.splitext(os.path.basename(path))[0]
                    benchmarks.append((name, rel, "UNKNOWN"))

    print(f"\n{'='*110}")
    print(f"  Pono Engine Comparison   (K-Ind Bound={KIND_BOUND}, IC3 Bound={IC3_BOUND}, "
          f"Timeout={TIMEOUT}s)")
    print(f"{'='*110}\n")

    col = [22, 9, 8, 8, 8, 8, 8, 8, 6, 8]
    hdr = ["Benchmark", "Expected", "KInd", "KInd(s)", "PDK", "PDK(s)",
           "IC3", "IC3(s)", "Lem", "Useful"]
    print("  " + "  ".join(h.ljust(col[i]) for i, h in enumerate(hdr)))
    print("  " + "-"*106)

    results = []
    for name, path, expected in benchmarks:
        abs_path = os.path.join(PONO_ROOT, path)
        if not os.path.exists(abs_path):
            print(f"  {name:<22} FILE NOT FOUND")
            continue

        ki_v, ki_t, _, _, _ = run_engine("ind", path, KIND_BOUND)
        pk_v, pk_t, pk_tot, pk_use, pk_out = run_engine("pdkind", path, KIND_BOUND)
        ic_v, ic_t, _, _, _ = run_engine("mbic3", path, IC3_BOUND)

        row = [name[:22], expected, ki_v, f"{ki_t:.2f}s", pk_v, f"{pk_t:.2f}s",
               ic_v, f"{ic_t:.2f}s", str(pk_tot), str(pk_use)]
        
        # Highlight PDKind wins over K-Induction
        marker = ""
        if ki_v == "UNKNOWN" and pk_v in ("SAFE", "UNSAFE"):
            marker = "  ← PDKind win!"
        elif pk_v == "UNKNOWN" and ic_v in ("SAFE", "UNSAFE"):
            marker = "  ← IC3 win!"

        print("  " + "  ".join(str(row[i]).ljust(col[i]) for i in range(len(row))) + marker)

        results.append({
            "name": name, "expected": expected,
            "kind": (ki_v, ki_t), "pdkind": (pk_v, pk_t, pk_tot, pk_use), "ic3": (ic_v, ic_t)
        })

    # Summary
    print(f"\n{'='*110}")
    print("  SUMMARY")
    print(f"{'='*110}")
    total = len(results)
    ki_s = sum(1 for r in results if r["kind"][0] in ("SAFE", "UNSAFE"))
    pk_s = sum(1 for r in results if r["pdkind"][0] in ("SAFE", "UNSAFE"))
    ic_s = sum(1 for r in results if r["ic3"][0] in ("SAFE", "UNSAFE"))

    print(f"  K-Induction solved : {ki_s}/{total} ({100*ki_s//max(total,1)}%)")
    print(f"  PDKind solved      : {pk_s}/{total} ({100*pk_s//max(total,1)}%)")
    print(f"  IC3 solved         : {ic_s}/{total} ({100*ic_s//max(total,1)}%)")
    print()

    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["benchmark", "expected", "kind_v", "kind_t", "pk_v", "pk_t", "ic3_v", "ic3_t"])
        for r in results:
            writer.writerow([r["name"], r["expected"], r["kind"][0], r["kind"][1], 
                             r["pdkind"][0], r["pdkind"][1], r["ic3"][0], r["ic3"][1]])

if __name__ == "__main__":
    os.chdir(os.path.join(EVAL_DIR, ".."))
    main()
