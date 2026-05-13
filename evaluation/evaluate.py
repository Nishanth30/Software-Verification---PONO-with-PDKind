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
    width = 135
    print(f"\n{'='*width}")
    print(f"  Pono Engine Comparison   (K-Ind/PDKind Bound={KIND_BOUND}, IC3 Bound={IC3_BOUND}, Timeout={TIMEOUT}s)")
    print(f"{'='*width}\n")

    col = [30, 14, 14, 10, 14, 10, 10, 10, 10]
    hdr = ["Benchmark", "Expected(IC3)", "IC3 Time", "K-Ind Verdict", "K-Ind Time", "PDK Verdict", "PDK Time", "PDK Lemmas", "PDK Useful"]
    print("  " + "  ".join(h.ljust(col[i]) for i, h in enumerate(hdr)))
    print("  " + "-"*(width-4))

    # 3. Execution
    pdkind_solved = 0
    kind_solved = 0

    for name, path in benchmarks:
        # Run IC3 (Gold Standard)
        ic_v, ic_t, _, _, _ = run_engine("mbic3", path, IC3_BOUND)
        expected = ic_v

        # Run K-Induction
        ki_v, ki_t, _, _, _ = run_engine("ind", path, KIND_BOUND)
        
        # Run PDKind
        pk_v, pk_t, pk_tot, pk_use, _ = run_engine("pdkind", path, KIND_BOUND)

        # Track "PASS/MISS/FAIL" internally
        # PASS: matches IC3
        # MISS: timeout/unknown
        # FAIL: soundness bug (disagrees with IC3)
        
        row = [
            name[:30], 
            expected, 
            ki_v, 
            f"{ki_t:.2f}s", 
            pk_v, 
            f"{pk_t:.2f}s", 
            str(pk_tot), 
            str(pk_use), 
            f"{ic_t:.2f}s"
        ]
        
        # Statistics
        if pk_v in ("SAFE", "UNSAFE"):
            pdkind_solved += 1
        if ki_v in ("SAFE", "UNSAFE"):
            kind_solved += 1

        # Visual Markers
        marker = ""
        # PDKind win: PDKind solved, K-Induction didn't
        if ki_v not in ("SAFE", "UNSAFE") and pk_v in ("SAFE", "UNSAFE"):
            marker = "  ← PDKind win!"
        
        # Soundness check: Disagrees with ground truth
        if expected in ("SAFE", "UNSAFE") and pk_v in ("SAFE", "UNSAFE") and pk_v != expected:
            marker = "  ← FAIL (Soundness Bug!)"

        print("  " + "  ".join(str(row[i]).ljust(col[i]) for i in range(len(row))) + marker)

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
