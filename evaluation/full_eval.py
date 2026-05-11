#!/usr/bin/env python3
"""
PDKind Full Evaluation Suite
============================
Runs pono --engine pdkind (and gold-standard engines) on every .btor2/.btor
file found recursively under pono-src/samples/.

Checks:
  1. Batch execution    — pdkind on every benchmark.
  2. Correctness        — compare verdict against ic3ia (SAFE) and bmc (UNSAFE).
  3. Edge-case analysis — CTI extraction, lemma stability, timeouts.
  4. Summary table      — filename, result (Pass/Fail), time.

Output:  printed to stdout + written to evaluation/full_eval_results.log
         CSV also written to evaluation/full_eval_results.csv
"""

import subprocess, time, re, os, sys, csv, glob, textwrap
from pathlib import Path
from typing import Optional

# ── configuration ───────────────────────────────────────────────────────────
PONO_ROOT = Path(__file__).resolve().parent.parent / "pono-src"
PONO      = str(PONO_ROOT / "build" / "pono")
SAMPLES   = PONO_ROOT / "samples"
EVAL_DIR  = Path(__file__).resolve().parent

BOUND     = 30      # unrolling depth for all engines
TIMEOUT   = 45      # per-run wall-clock seconds
VERBOSITY = 2       # verbosity level (enables PDKind lemma lines)

LOG_PATH  = EVAL_DIR / "full_eval_results.log"
CSV_PATH  = EVAL_DIR / "full_eval_results.csv"

# ── verdict parsing ──────────────────────────────────────────────────────────
def parse_verdict(stdout: str, stderr: str, returncode: int) -> str:
    """Return 'SAFE', 'UNSAFE', 'UNKNOWN', or 'ERROR'."""
    combined = (stdout + stderr).lower()
    if returncode == 0 and "sat" in stdout.lower():
        return "UNSAFE"
    if returncode == 1 and "unsat" in stdout.lower():
        return "SAFE"
    if "unknown" in combined or returncode == 255:
        return "UNKNOWN"
    if returncode not in (0, 1, 255):
        return "ERROR"
    return "UNKNOWN"

# ── single engine run ────────────────────────────────────────────────────────
def run_engine(engine: str, bench_rel: str, extra_args: list = []) -> dict:
    """
    Run pono with *engine* on *bench_rel* (relative to PONO_ROOT).
    Returns a dict with keys: verdict, elapsed, lemma_total, lemma_useful,
    lemma_trivial, cti_count, proof_depth, stdout, stderr, timed_out.
    """
    cmd = [PONO, "-e", engine, "-k", str(BOUND), "-v", str(VERBOSITY),
           bench_rel] + extra_args
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=TIMEOUT, cwd=str(PONO_ROOT)
        )
        elapsed = time.perf_counter() - t0
        stdout, stderr = proc.stdout, proc.stderr
        timed_out = False
        verdict = parse_verdict(stdout, stderr, proc.returncode)
    except subprocess.TimeoutExpired:
        elapsed = TIMEOUT
        stdout = stderr = ""
        timed_out = True
        verdict = "TIMEOUT"

    # PDKind-specific diagnostics from stderr
      # PDKind-specific diagnostics from stderr
    cti_count      = len(re.findall(r"extracting CTI", stderr))
    lemma_useful   = len(re.findall(r"PDKind: new lemma at k=", stderr))
    lemma_trivial  = len(re.findall(r"discarding trivially-true lemma", stderr))
    lemma_total    = lemma_useful + lemma_trivial

    proof_depth_m = re.search(r"PDKind: property proved (\d+)-inductive", stderr)
    proof_depth = int(proof_depth_m.group(1)) if proof_depth_m else None

    return dict(
        verdict=verdict,
        elapsed=elapsed,
        lemma_total=lemma_total,
        lemma_useful=lemma_useful,
        lemma_trivial=lemma_trivial,
        cti_count=cti_count,
        proof_depth=proof_depth,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
    )

# ── benchmark discovery ──────────────────────────────────────────────────────
def discover() -> list[tuple[str, str]]:
    """Return list of (display_name, path_relative_to_PONO_ROOT) pairs."""
    results = []
    for ext in ("**/*.btor2", "**/*.btor"):
        for p in sorted(SAMPLES.glob(ext)):
            rel = str(p.relative_to(PONO_ROOT))
            name = p.stem
            # Prefix sub-directory for disambiguation
            parts = p.relative_to(SAMPLES).parts
            if len(parts) > 1:
                name = f"{parts[-2]}/{p.stem}"
            results.append((name, rel))
    return results

# ── gold-standard verdict ────────────────────────────────────────────────────
def gold_verdict(ic3ia_v: str, bmc_v: str) -> str:
    """
    Return the best known ground-truth verdict.
    UNSAFE from bmc is definitive.
    SAFE from ic3ia is definitive.
    UNKNOWN if neither gave a definitive answer.
    """
    if bmc_v == "UNSAFE":
        return "UNSAFE"
    if ic3ia_v == "SAFE":
        return "SAFE"
    return "UNKNOWN"

# ── pass/fail determination ──────────────────────────────────────────────────
def pass_fail(pdkind_v: str, gold: str) -> str:
    if gold == "UNKNOWN":
        return "N/A"          # no ground truth to compare against
    if pdkind_v in ("TIMEOUT", "ERROR", "UNKNOWN"):
        return "MISS"         # timed out or missed — not a soundness bug
    if pdkind_v == gold:
        return "PASS"
    return "FAIL"             # soundness violation

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    benchmarks = discover()
    if not benchmarks:
        print(f"ERROR: no .btor2/.btor files found under {SAMPLES}", file=sys.stderr)
        sys.exit(1)

    lines = []          # accumulated output lines
    csv_rows = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 100)
    emit(f"  PDKind Full Evaluation Report")
    emit(f"  Pono binary : {PONO}")
    emit(f"  Samples dir : {SAMPLES}")
    emit(f"  Bound       : {BOUND}")
    emit(f"  Timeout     : {TIMEOUT}s / engine / benchmark")
    emit(f"  Benchmarks  : {len(benchmarks)}")
    emit("=" * 100)
    emit()

    # ── per-benchmark run ────────────────────────────────────────────────────
    col_w = [38, 8, 8, 7, 9, 6, 8, 8, 7, 9]
    header = ["Benchmark", "BMC", "IC3IA", "PDKind", "Gold", "PF",
              "Depth", "CTIs", "Lemmas", "PDK(s)"]
    emit("  " + "  ".join(h.ljust(col_w[i]) for i, h in enumerate(header)))
    emit("  " + "-" * 100)

    all_results = []

    for name, rel_path in benchmarks:
        abs_path = PONO_ROOT / rel_path
        if not abs_path.exists():
            emit(f"  {'FILE NOT FOUND':<38} (skipped)")
            continue

        # Run gold-standard engines first
        bmc_r   = run_engine("bmc",   rel_path)
        ic3ia_r = run_engine("ic3ia", rel_path)
        gold    = gold_verdict(ic3ia_r["verdict"], bmc_r["verdict"])

        # Run PDKind
        pk_r = run_engine("pdkind", rel_path)

        pf = pass_fail(pk_r["verdict"], gold)

        depth_str = str(pk_r["proof_depth"]) if pk_r["proof_depth"] is not None else "-"

        row_vals = [
            name[:38],
            bmc_r["verdict"][:8],
            ic3ia_r["verdict"][:8],
            pk_r["verdict"][:7],
            gold[:9],
            pf[:6],
            depth_str,
            str(pk_r["cti_count"]),
            str(pk_r["lemma_useful"]),
            f"{pk_r['elapsed']:.2f}s",
        ]
        marker = ""
        if pf == "FAIL":
            marker = "  ← SOUNDNESS BUG"
        elif pf == "PASS" and ic3ia_r["verdict"] in ("UNKNOWN","TIMEOUT") and pk_r["verdict"] == "SAFE":
            marker = "  ← PDKind stronger"

        emit("  " + "  ".join(str(row_vals[i]).ljust(col_w[i]) for i in range(len(row_vals))) + marker)

        all_results.append(dict(
            name=name, rel=rel_path, gold=gold, pf=pf,
            bmc=bmc_r, ic3ia=ic3ia_r, pdkind=pk_r,
        ))

        csv_rows.append([
            name, rel_path, gold,
            bmc_r["verdict"], f"{bmc_r['elapsed']:.4f}",
            ic3ia_r["verdict"], f"{ic3ia_r['elapsed']:.4f}",
            pk_r["verdict"], f"{pk_r['elapsed']:.4f}",
            pf,
            pk_r["cti_count"], pk_r["lemma_total"],
            pk_r["lemma_useful"], pk_r["lemma_trivial"],
            pk_r["proof_depth"] if pk_r["proof_depth"] is not None else "",
        ])

    emit()
    emit("  PF key:  PASS=correct  MISS=timeout/unknown  FAIL=soundness bug  N/A=no ground truth")

    # ── correctness summary ──────────────────────────────────────────────────
    emit()
    emit("=" * 100)
    emit("  CORRECTNESS CHECK")
    emit("=" * 100)
    definitive = [r for r in all_results
                  if r["gold"] != "UNKNOWN"
                  and r["pdkind"]["verdict"] not in ("UNKNOWN","TIMEOUT","ERROR","MISS")]
    passes   = [r for r in definitive if r["pf"] == "PASS"]
    fails    = [r for r in definitive if r["pf"] == "FAIL"]
    misses   = [r for r in all_results
                if r["gold"] != "UNKNOWN" and r["pdkind"]["verdict"] in ("UNKNOWN","TIMEOUT","ERROR")]
    no_gt    = [r for r in all_results if r["gold"] == "UNKNOWN"]

    emit(f"  Benchmarks with ground truth   : {len(all_results) - len(no_gt)}")
    emit(f"  PDKind gave definitive answer  : {len(definitive)}")
    emit(f"    PASS (correct)               : {len(passes)}")
    emit(f"    FAIL (soundness bug)         : {len(fails)}")
    emit(f"  Missed (timeout/unknown)       : {len(misses)}")
    emit(f"  No ground truth available      : {len(no_gt)}")
    if fails:
        emit()
        emit("  *** SOUNDNESS VIOLATIONS DETECTED ***")
        for r in fails:
            emit(f"    {r['name']}: gold={r['gold']} pdkind={r['pdkind']['verdict']}")
    else:
        emit()
        emit("  No soundness violations found — PDKind is sound on all checked benchmarks.")

    # ── CTI / lemma analysis ─────────────────────────────────────────────────
    emit()
    emit("=" * 100)
    emit("  CTI & LEMMA ANALYSIS")
    emit("=" * 100)
    cti_benchmarks = [r for r in all_results if r["pdkind"]["cti_count"] > 0]
    trivial_only   = [r for r in cti_benchmarks
                      if r["pdkind"]["lemma_useful"] == 0 and r["pdkind"]["cti_count"] > 0]
    all_trivial    = sum(r["pdkind"]["lemma_trivial"] for r in all_results)
    all_useful     = sum(r["pdkind"]["lemma_useful"]  for r in all_results)

    emit(f"  Benchmarks that generated CTIs : {len(cti_benchmarks)}")
    emit(f"  Total CTIs extracted           : {sum(r['pdkind']['cti_count'] for r in all_results)}")
    emit(f"  Useful lemmas (non-trivial)    : {all_useful}")
    emit(f"  Trivial lemmas ('true')        : {all_trivial}")
    emit()
    if trivial_only:
        emit("  Benchmarks where ALL lemmas were trivially 'true'")
        emit("  (literal_drop found no essential literals — bad reachable from any state):")
        for r in trivial_only:
            emit(f"    {r['name']:40s}  gold={r['gold']}  CTIs={r['pdkind']['cti_count']}")
        emit()
        emit("  NOTE: trivially-true lemmas add no information to the inductive frame.")
        emit("  This typically means the property is UNSAFE and every CTI state can")
        emit("  reach the bad state — so no generalised blocking clause can be formed.")
    else:
        emit("  No benchmarks produced exclusively trivial lemmas.")

    emit()
    emit("  Per-benchmark lemma details (benchmarks with CTIs):")
    emit(f"  {'Benchmark':<40}  {'Gold':<8}  {'Verdict':<8}  {'CTIs':>5}  {'Useful':>6}  {'Trivial':>7}")
    emit("  " + "-" * 80)
    for r in cti_benchmarks:
        pk = r["pdkind"]
        emit(f"  {r['name']:<40}  {r['gold']:<8}  {pk['verdict']:<8}  "
             f"{pk['cti_count']:>5}  {pk['lemma_useful']:>6}  {pk['lemma_trivial']:>7}")

    # ── lemma stability check ────────────────────────────────────────────────
    emit()
    emit("=" * 100)
    emit("  LEMMA STABILITY CHECK")
    emit("=" * 100)
    emit("  A 'false negative' (SAFE when gold=UNSAFE) indicates a lemma that")
    emit("  incorrectly blocked all counterexample paths — a stability bug.")
    false_negatives = [r for r in all_results
                       if r["gold"] == "UNSAFE"
                       and r["pdkind"]["verdict"] == "SAFE"]
    if false_negatives:
        emit()
        emit("  *** FALSE NEGATIVES DETECTED (LEMMA STABILITY BUG) ***")
        for r in false_negatives:
            emit(f"    {r['name']}: reported SAFE but gold=UNSAFE")
    else:
        emit()
        emit("  No false negatives — lemmas do not cause spurious SAFE results.")

    # ── timeout analysis ─────────────────────────────────────────────────────
    emit()
    emit("=" * 100)
    emit("  TIMEOUT ANALYSIS")
    emit("=" * 100)
    timeouts_pdkind = [r for r in all_results if r["pdkind"]["timed_out"]]
    timeouts_bmc    = [r for r in all_results if r["bmc"]["timed_out"]]
    timeouts_ic3ia  = [r for r in all_results if r["ic3ia"]["timed_out"]]

    emit(f"  Timeouts — BMC    : {len(timeouts_bmc)}")
    emit(f"  Timeouts — IC3IA  : {len(timeouts_ic3ia)}")
    emit(f"  Timeouts — PDKind : {len(timeouts_pdkind)}")
    if timeouts_pdkind:
        emit()
        emit("  Benchmarks that timed out PDKind:")
        for r in timeouts_pdkind:
            emit(f"    {r['name']:<45}  gold={r['gold']:<8}  bmc={r['bmc']['verdict']:<8}  ic3ia={r['ic3ia']['verdict']}")
        emit()
        emit("  These circuits are hard for PDKind at this bound/timeout.")
        emit("  Possible causes: large state space, deep counterexamples, or")
        emit("  slow CTI generalisation loop in literal_drop().")

    # ── proof-depth distribution ─────────────────────────────────────────────
    emit()
    emit("=" * 100)
    emit("  PROOF DEPTH DISTRIBUTION (PDKind proved-k-inductive)")
    emit("=" * 100)
    proved = [(r["name"], r["pdkind"]["proof_depth"])
              for r in all_results
              if r["pdkind"]["proof_depth"] is not None]
    if proved:
        emit(f"  {'Benchmark':<45}  Proved k-inductive")
        emit("  " + "-" * 60)
        for nm, depth in sorted(proved, key=lambda x: x[1]):
            emit(f"  {nm:<45}  k={depth}")
    else:
        emit("  No benchmarks proved within the bound by PDKind.")

    # ── summary table ────────────────────────────────────────────────────────
    emit()
    emit("=" * 100)
    emit("  FINAL SUMMARY TABLE")
    emit("=" * 100)
    total      = len(all_results)
    pk_safe    = sum(1 for r in all_results if r["pdkind"]["verdict"] == "SAFE")
    pk_unsafe  = sum(1 for r in all_results if r["pdkind"]["verdict"] == "UNSAFE")
    pk_unknown = sum(1 for r in all_results if r["pdkind"]["verdict"] == "UNKNOWN")
    pk_timeout = len(timeouts_pdkind)
    pk_error   = sum(1 for r in all_results if r["pdkind"]["verdict"] == "ERROR")
    pk_pass    = len(passes)
    pk_fail    = len(fails)
    avg_time   = sum(r["pdkind"]["elapsed"] for r in all_results) / max(total, 1)
    max_time_r = max(all_results, key=lambda r: r["pdkind"]["elapsed"])

    emit(f"  Total benchmarks             : {total}")
    emit(f"  PDKind SAFE                  : {pk_safe}")
    emit(f"  PDKind UNSAFE                : {pk_unsafe}")
    emit(f"  PDKind UNKNOWN               : {pk_unknown}")
    emit(f"  PDKind TIMEOUT               : {pk_timeout}")
    emit(f"  PDKind ERROR                 : {pk_error}")
    emit(f"  PASS (vs gold)               : {pk_pass}")
    emit(f"  FAIL (soundness violations)  : {pk_fail}")
    emit(f"  Avg PDKind time              : {avg_time:.3f}s")
    emit(f"  Slowest benchmark            : {max_time_r['name']} ({max_time_r['pdkind']['elapsed']:.2f}s)")
    emit()

    # ── CSV output ───────────────────────────────────────────────────────────
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "benchmark", "rel_path", "gold",
            "bmc_verdict", "bmc_time_s",
            "ic3ia_verdict", "ic3ia_time_s",
            "pdkind_verdict", "pdkind_time_s",
            "pass_fail",
            "cti_count", "lemma_total", "lemma_useful", "lemma_trivial",
            "proof_depth_k",
        ])
        w.writerows(csv_rows)
    emit(f"  CSV written  → {CSV_PATH}")

    # ── log file ─────────────────────────────────────────────────────────────
    with open(LOG_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    emit(f"  Log written  → {LOG_PATH}")
    emit()

if __name__ == "__main__":
    main()
