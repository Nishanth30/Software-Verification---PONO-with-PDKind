/*********************                                                        */
/*! \file pdk_ind.h
 ** \verbatim
 ** Top contributors (to current version):
 **   Nishanth Dikkala
 ** This file is part of the pono project.
 ** Copyright (c) 2024 by the authors listed in the file AUTHORS
 ** in the top-level source directory) and their institutional affiliations.
 ** All rights reserved.  See the file LICENSE in the top-level source
 ** directory for licensing information.\endverbatim
 **
 ** \brief Property-Directed K-Induction (PDKind) engine.
 **
 ** Implements the PDKind algorithm: interleaves a BMC-style base check
 ** (searching for a counterexample of length k) with a k-inductive
 ** strengthening check (checking whether P is k-inductive).  When the
 ** inductive check fails, a CTI is extracted, generalised via literal_drop(),
 ** and the resulting lemma is asserted permanently to strengthen future checks.
 **
 ** === CTI extraction contract ===
 **   inductive_check() returns:
 **     TRUE    — UNSAT (proved k-inductive); solver context popped.
 **     FALSE   — SAT (CTI exists); context left PUSHED so extract_cti() can
 **               read get_value(); caller must pop before calling literal_drop().
 **     UNKNOWN — solver returned indeterminate; context alreåady popped;
 **               do NOT call extract_cti().
 **
 ** === literal_drop correctness requirement ===
 **   The drop probe MUST assert P@0..P@k-1 (¬bad at every pre-step).
 **   Without this the unconstrained pre-state allows the solver to satisfy
 **   T(k-1)∧bad(k) from an unreachable state, making every literal appear
 **   droppable and the resulting lemma trivially true.
 **
 **/

#pragma once

#include <chrono>
#include <string>
#include <unordered_set>

#include "engines/prover.h"
#include "options/options.h"

namespace pono {

class PDKind : public SafetyProver
{
 public:
  PDKind(const SafetyProperty & p,
         const TransitionSystem & ts,
         const smt::SmtSolver & solver,
         PonoOptions opt = {});

  typedef SafetyProver super;

  void initialize() override;

  ProverResult check_until(int k) override;

 protected:
  /**
   * base_check — SAT( I(s0) ^ T^k ^ bad(k) ).
   *
   * Returns FALSE   — CEX found (SAT); context left PUSHED for compute_witness().
   * Returns TRUE    — no CEX at depth k (UNSAT); context popped.
   * Returns UNKNOWN — solver returned indeterminate; context popped.
   */
  ProverResult base_check(int k);

  /**
   * inductive_check — UNSAT( P(s0)^…^P(s_{k-1}) ^ T^k ^ bad(k) ).
   *
   * Returns TRUE    — k-inductive (UNSAT); solver context popped.
   * Returns FALSE   — not k-inductive (SAT); context left PUSHED so that
   *                   extract_cti() can call get_value(); caller pops.
   * Returns UNKNOWN — solver returned indeterminate; context popped.
   *                   Caller must NOT call extract_cti() in this case.
   */
  ProverResult inductive_check(int k);

  /**
   * extract_cti — read model values for all state variables at time k-1.
   *
   * Precondition: solver is in the SAT state left by inductive_check()
   * returning FALSE (i.e. the push scope has NOT been popped yet).
   */
  smt::TermVec extract_cti(int k);

  /**
   * literal_drop — generalise a CTI cube under the k-step inductive hypothesis.
   *
   * For each literal cti[i], probes whether the REMAINING literals still allow
   * reaching bad(k) when the pre-state is constrained to satisfy P:
   *
   *   [background: T@0..T@k-1, existing lemmas]
   *   [outer push: P@0 ^ … ^ P@k-1]            ← THE CRITICAL CONSTRAINT
   *   [inner push: kept∪rest\{cti[i]} @ (k-1), bad(k)]
   *
   * UNSAT → cti[i] is essential (keep).
   * SAT   → cti[i] is droppable.
   * UNKNOWN → treated conservatively as essential (keep).
   *
   * P@0..P@k-1 is asserted once per call in an outer push/pop scope,
   * amortising the cost across all n literal probes (O(k) not O(k·n) asserts).
   *
   * Execution budget: the loop aborts when either kMaxDropProbes SAT/UNSAT
   * queries have been issued or kDropTimeBudget wall-clock seconds have
   * elapsed since the call started.  On abort all unprocessed literals are
   * kept conservatively, guaranteeing a non-trivial (if less generalised)
   * blocking clause.
   *
   * Returns ¬(∧ kept_literals) — a generalised blocking clause over untimed
   * state variables, ready for permanent assertion at all time steps.
   */
  smt::Term literal_drop(const smt::TermVec & cti, int k);

  // ── Generalisation budget ─────────────────────────────────────────────────
  // kMaxDropProbes: maximum number of SAT/UNSAT queries issued per CTI before
  //   aborting and keeping remaining literals conservatively.
  //   50 covers any benchmark with ≤50 state variables in a single pass.
  //   Increase if working with very wide state spaces and a fast solver.
  //
  // kDropTimeBudget: hard wall-clock ceiling in seconds per CTI.
  //   Prevents the growing background context (T@0..T@k-1) from making
  //   individual probes too expensive at large k.
  //   5 s is generous for the sample suite; lower to 1–2 s for production
  //   runs with a strict global timeout.
  static constexpr std::size_t kMaxDropProbes  = 50;
  static constexpr double      kDropTimeBudget = 5.0;

  /**
   * try_add_lemma — add lemma to the permanent background if it is
   * non-trivial and has not been seen before.
   *
   * Stamps lemma@t for t = 0 .. up_to_time and appends to lemmas_.
   * Returns true iff the lemma was actually added.
   */
  bool try_add_lemma(const smt::Term & lemma, int up_to_time);

  /**
   * is_lemma_sound — standard PDR relative-inductivity check.
   *
   * The candidate lemma is ¬cube, asserted at every timestep.  For this to
   * be a sound invariant, ¬cube must be inductive relative to the current
   * background (existing lemmas + T):
   *
   *   (1) Initiation:    I(s0) ∧ cube@0                  is UNSAT
   *   (2) Consecution:   ¬cube@0 ∧ T(0) ∧ cube@1         is UNSAT
   *
   * If both hold, ¬cube is preserved by T from any state already satisfying
   * existing lemmas (which are in the background) — so by induction it
   * holds at every reachable state.
   *
   * Bounded reachability (I ∧ T^j ∧ cube@j  UNSAT for j ≤ k) is NOT enough:
   * the lemma is asserted forever, so a state reachable beyond the current
   * bound would still be incorrectly blocked.  See `counter` benchmark
   * counter-example: state6 increments from 0; cube = (state6 = bad-1) is
   * unreachable in 0 or 1 step but reachable in bad-1 steps.
   *
   * Returns false on UNKNOWN at either check (conservative refuse).
   */
  bool is_lemma_sound(const smt::Term & cube, int k_current);

  smt::Term true_;
  smt::Term false_;

  /** Accumulated non-trivial lemmas asserted permanently at all timesteps. */
  smt::TermVec lemmas_;

  /**
   * Syntactic deduplication set: to_string() keys of every lemma in lemmas_.
   * Prevents re-asserting the same blocking clause when the same CTI is
   * encountered at different depths.
   */
  std::unordered_set<std::string> lemma_set_;
};

}  // namespace pono
