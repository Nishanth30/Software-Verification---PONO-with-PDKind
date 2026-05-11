# PDKind Engine Evaluation Report

**Engine:** `pono --engine pdkind`  
**Benchmarks:** 36 (all `.btor2` / `.btor` files under `pono-src/samples/`)  
**Gold standard:** IC3IA (safety) + BMC (unsafety)  
**Bound:** k = 30 | **Timeout:** 45 s per engine per benchmark  
**Date:** 2026-05-11

---

## 1. Full Results Table

| Benchmark | BMC | IC3IA | PDKind | Gold | Pass/Fail | Proof k | CTIs | PDK(s) |
|-----------|-----|-------|--------|------|-----------|---------|------|--------|
| anderson.2.prop1-func-interl | TIMEOUT | TIMEOUT | TIMEOUT | UNKNOWN | N/A | — | 0 | 45.00 |
| array_lt200 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | N/A | — | 30 | 0.82 |
| bmc-interval-search/count2-large-interval-… | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 0 | 0.01 |
| bmc-interval-search/count2-single-bad-… | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 0 | 0.01 |
| bmc-interval-search/count2-stall-bad-state | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 2 | 0.01 |
| cone-of-influence-reduction/count2-redundancy-constraint-bad-unreachable | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 3 | 2 | 0.01 |
| cone-of-influence-reduction/count2-redundancy-constraint-connection | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 1 | 0 | 0.01 |
| cone-of-influence-reduction/count2-redundancy | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 2 | 0.01 |
| cone-of-influence-reduction/count9-10-combined-redundancy | UNKNOWN | TIMEOUT | UNKNOWN | UNKNOWN | N/A | — | 30 | 0.77 |
| cone-of-influence-reduction/unconstrained-input | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 0 | 0.01 |
| constarrfalse | UNSAFE | UNKNOWN | UNKNOWN | UNSAFE | **MISS** | — | 30 | 0.03 |
| constarrtest | UNKNOWN | UNKNOWN | ERROR | UNKNOWN | N/A | — | 1 | 0.01 |
| int_win | UNKNOWN | SAFE | UNKNOWN | SAFE | **MISS** | — | 30 | 0.06 |
| k-induction/adder-cfg-safe | UNKNOWN | SAFE | UNKNOWN | SAFE | **MISS** | — | 30 | 0.03 |
| k-induction/cnt-3bits-wrap-safe-kind-bound0 | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 1 | 0 | 0.00 |
| k-induction/cnt-3bits-wrap-safe-kind-bound1 | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 2 | 1 | 0.01 |
| k-induction/pono-test-case-simple-alu-… | UNKNOWN | SAFE | UNKNOWN | SAFE | **MISS** | — | 30 | 0.04 |
| neg_rst_test | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 0 | 0.01 |
| sygus-pdr/bvadd-cond | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | N/A | — | 30 | 0.30 |
| sygus-pdr/bvadd-simple | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | N/A | — | 30 | 0.09 |
| sygus-pdr/bvadd | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | N/A | — | 30 | 0.10 |
| sygus-pdr/cal39 | UNKNOWN | SAFE | UNKNOWN | SAFE | **MISS** | — | 30 | 34.59 |
| sygus-pdr/mul4 | TIMEOUT | TIMEOUT | TIMEOUT | UNKNOWN | N/A | — | 0 | 45.00 |
| sygus-pdr/trans | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 1 | 0 | 0.01 |
| sygus-pdr/two-cnt-false | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 13 | 0.01 |
| sygus-pdr/two-cnt-true-2 | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 12 | 11 | 0.01 |
| sygus-pdr/two-cnt-true | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 16 | 15 | 0.01 |
| uv_example | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 2 | 1 | 0.01 |
| uvw_example | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 17 | 16 | 0.03 |
| xp2 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | N/A | — | 30 | 0.03 |
| counter-true | UNKNOWN | SAFE | SAFE | SAFE | **PASS** | 1 | 0 | 0.01 |
| counter | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 9 | 0.01 |
| dspfilters_fastfir_second-p09 | UNKNOWN | TIMEOUT | TIMEOUT | UNKNOWN | N/A | — | 0 | 45.00 |
| mem | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 0 | 0.01 |
| ridecore | TIMEOUT | TIMEOUT | TIMEOUT | UNKNOWN | N/A | — | 0 | 45.00 |
| state2input | UNSAFE | UNSAFE | UNSAFE | UNSAFE | **PASS** | — | 0 | 0.01 |

**PASS** = PDKind agreed with gold standard &nbsp;|&nbsp; **MISS** = PDKind couldn't decide within bound/timeout &nbsp;|&nbsp; **N/A** = no ground truth

---

## 2. Correctness Check

| Metric | Count |
|--------|-------|
| Benchmarks with ground truth | 25 |
| PDKind gave definitive answer | 20 |
| PASS (correct) | **20 / 20** |
| FAIL (soundness violations) | **0** |
| MISS (timed out / stayed UNKNOWN) | 5 |
| No ground truth | 11 |

**Soundness verdict: PDKind is sound on all tested benchmarks.** No case was found where PDKind reported SAFE for a circuit that is UNSAFE, or vice versa.

---

## 3. Edge-Case Analysis

### 3.1 CTI Extraction & Lemma Stability — Critical Bug Found

**Observation:** Every single one of the 403 CTI lemmas generated across all benchmarks is trivially `true`. Not a single useful blocking clause was produced.

**Root cause — `literal_drop()` over-generalises:** The function's job is to minimise the CTI cube and return its negation as a lemma. For each literal it tests whether the **remaining** literals alone can still reach the bad state:

```
kept_lits @ (k-1)  ∧  remaining_lits @ (k-1)  ∧  T(k-1)  ∧  bad(k)
```

When testing the very last literal (so `kept = []`, no remaining), this collapses to:

```
T(k-1)  ∧  bad(k)
```

This asks: *"Does there exist ANY pre-state that transitions to bad?"* — not *"Does the CTI state reach bad?"*

For virtually every non-trivial circuit, the transition relation allows some (possibly unreachable) state to reach the bad set, so the check is `SAT`, the literal is dropped, and `literal_drop` ultimately returns `solver_->make_term(true)`.

**Impact:** The strengthening loop at the heart of PDKind is entirely ineffective. The engine degenerates to pure k-induction: it can only prove properties that are already k-inductive for some k within the bound, without any property-directed guidance.

**Fix:** The pre-state in the `literal_drop` check must be constrained to states satisfying the current property hypothesis `P`. Replace the inner loop body with:

```cpp
// Current (broken):
solver_->assert_formula(unroller_.at_time(bad_, k));

// Fixed: also assert P at the pre-state so we only test reachability
// from property-satisfying states, not from arbitrary states.
Term good = solver_->make_term(Not, bad_);
for (const auto & lit : kept_literals) {
    solver_->assert_formula(unroller_.at_time(lit, k - 1));
}
for (size_t j = i + 1; j < cti.size(); ++j) {
    solver_->assert_formula(unroller_.at_time(cti[j], k - 1));
}
// Add property constraint at pre-state:
solver_->assert_formula(unroller_.at_time(good, k - 1));
solver_->assert_formula(unroller_.at_time(bad_, k));
```

Without this fix, PDKind never produces the lemmas that distinguish it from standard k-induction.

### 3.2 Lemma Stability (False Negatives)

**Finding: No false negatives.** No benchmark was reported SAFE by PDKind when the ground truth is UNSAFE. The lemma accumulation mechanism (although producing only trivially-true lemmas) never over-constrained the base check enough to mask a real counterexample.

This is expected: a lemma of `true` is a tautology and adds no constraints, so it cannot block a valid counterexample trace.

### 3.3 constarrtest — Solver Exception Bug

**Symptom:** PDKind crashes with:
```
invalid call to 'Term bitwuzla::Bitwuzla::get_value(const Term &)',
cannot get value if input formula is not sat
```

**Trace:**
1. BZLA emits `"Equality over constant arrays not fully supported yet"` during `inductive_check(2)`.
2. BZLA returns `UNKNOWN` (not SAT, not UNSAT) due to the unsupported feature.
3. `inductive_check()` checks only `res.is_unsat()` — since it is not UNSAT, it returns `false` (the SAT branch), leaving the solver context pushed.
4. `extract_cti(2)` calls `solver_->get_value(v_at_1)`, but the formula is not in a SAT state — it is UNKNOWN — causing the exception.

**Fix in `inductive_check()`:**

```cpp
Result res = solver_->check_sat();
if (res.is_unsat()) {
    solver_->pop();
    return true;
}
if (!res.is_sat()) {
    // UNKNOWN from solver — treat as non-inductive but skip CTI extraction
    solver_->pop();
    return false;  // signal to caller with a distinguishable path, or throw
}
// SAT: leave context pushed for extract_cti
return false;
```

A cleaner approach is to return a `ProverResult` (TRUE/FALSE/UNKNOWN) rather than `bool`, so the caller can distinguish the SAT and UNKNOWN cases.

### 3.4 constarrfalse — Missed Counterexample

**Symptom:** BMC finds a counterexample at depth 16; PDKind reports UNKNOWN at k=30.

**Root cause:** BZLA's incomplete support for constant array equality causes `base_check()` at depth 16 to return UNKNOWN instead of SAT. The code in `base_check()` only checks `res.is_sat()`, so an UNKNOWN result silently becomes "no counterexample found," and the engine increments k and continues. By k=30 the unrolled context is large and BZLA's constant-array limitations affect the result consistently.

**Fix:** Surface the UNKNOWN result from `base_check()` and propagate it upward:

```cpp
bool PDKind::base_check(int k) {
    solver_->push();
    solver_->assert_formula(unroller_.at_time(ts_.init(), 0));
    solver_->assert_formula(unroller_.at_time(bad_, k));
    Result res = solver_->check_sat();
    if (res.is_sat()) {
        return true;   // leave pushed — caller handles witness
    }
    solver_->pop();
    if (res.is_unknown()) {
        logger.log(1, "PDKind: base_check UNKNOWN at k={} (solver limitation)", k);
        // Optionally: throw or set a flag to return UNKNOWN from check_until
    }
    return false;
}
```

### 3.5 Timeouts

| Benchmark | BMC | IC3IA | PDKind | Notes |
|-----------|-----|-------|--------|-------|
| anderson.2.prop1-func-interl | TIMEOUT | TIMEOUT | TIMEOUT | Concurrent protocol, large state space |
| sygus-pdr/mul4 | TIMEOUT | TIMEOUT | TIMEOUT | Multiplier circuit, hard for all engines |
| dspfilters_fastfir_second-p09 | UNKNOWN | TIMEOUT | TIMEOUT | DSP filter, IC3IA/PDKind time out |
| ridecore | TIMEOUT | TIMEOUT | TIMEOUT | RISC-V processor core, all engines timeout |

All 4 PDKind timeouts occur on benchmarks that also exceed the timeout for at least one other engine. PDKind is not uniquely worse on any of these; they are inherently hard problems.

**Primary performance concern:** `sygus-pdr/cal39` takes 34.59 s for PDKind (vs < 1 s for most others). This is due to the 30 trivially-true CTIs generated — each requires a push/pop in `literal_drop`, producing 30 × 30 = 900 incremental SMT calls against a growing background context. Fixing the `literal_drop` bug would reduce CTI count (fewer but more useful lemmas) and cut runtime.

---

## 4. Proof Depth Distribution

| Benchmark | k-inductive at |
|-----------|---------------|
| cone-of-influence-reduction/count2-redundancy-constraint-connection | k=1 |
| k-induction/cnt-3bits-wrap-safe-kind-bound0 | k=1 |
| counter-true | k=1 |
| sygus-pdr/trans | k=1 |
| k-induction/cnt-3bits-wrap-safe-kind-bound1 | k=2 |
| uv_example | k=2 |
| cone-of-influence-reduction/count2-redundancy-constraint-bad-unreachable | k=3 |
| sygus-pdr/two-cnt-true-2 | k=12 |
| sygus-pdr/two-cnt-true | k=16 |
| uvw_example | k=17 |

All proofs succeed through the direct inductive check, not through lemma-derived strengthening. This is consistent with the trivial-lemma bug: the engine is doing pure k-induction.

---

## 5. Summary

| Metric | Value |
|--------|-------|
| Total benchmarks | 36 |
| PDKind SAFE | 10 |
| PDKind UNSAFE | 10 |
| PDKind UNKNOWN | 11 |
| PDKind TIMEOUT | 4 |
| PDKind ERROR | 1 |
| PASS (correct vs gold) | **20 / 20** |
| FAIL (soundness violation) | **0** |
| MISS (ground truth missed) | 5 |
| Total CTIs extracted | 403 |
| Useful lemmas (non-trivial) | **0** |
| Trivial lemmas (`true`) | **403 (100%)** |
| Avg PDKind time | 6.03 s |
| Slowest benchmark | anderson (45.00 s, timeout) |

---

## 6. Bugs Ranked by Severity

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| 1 | **High** | `pdk_ind.cpp:literal_drop()` | No property-hypothesis constraint in CTI dropping — all lemmas are trivially `true`; PDKind degenerates to k-induction |
| 2 | **Medium** | `pdk_ind.cpp:inductive_check()` | UNKNOWN solver result treated as SAT; causes crash in `extract_cti()` on constant-array benchmarks |
| 3 | **Low** | `pdk_ind.cpp:base_check()` | UNKNOWN solver result silently treated as "no counterexample"; masks deep bugs on constant-array circuits (constarrfalse) |

---

## 7. Recommendations

1. **Fix `literal_drop`** (Bug #1): Add `P @ (k-1)` (i.e., `¬bad @ (k-1)`) to the dropping check. This is the most impactful change — it makes the CTI generalisation semantically correct and will unlock PDKind's advantage over plain k-induction on hard-to-prove SAFE benchmarks.

2. **Handle solver UNKNOWN in `inductive_check` and `base_check`** (Bugs #2 and #3): Check `res.is_sat()` explicitly before entering the CTI extraction path. Propagate UNKNOWN upward so the caller can decide whether to continue or report UNKNOWN.

3. **Extend the benchmark suite** with HWMCC benchmarks (hardware model checking competition) to stress-test the engine at scale once Bug #1 is fixed — the current samples are insufficient to distinguish PDKind from k-induction since all proofs succeed by direct inductiveness.
