/*********************                                                        */
/*! \file pdk_ind.cpp
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
 ** At each depth k the engine performs two checks:
 **
 **   Base:      SAT( I(s0) ^ T(s0,s1) ^ ... ^ T(s_{k-1},sk) ^ ~P(sk) )
 **              — finds a k-step counterexample.
 **
 **   Inductive: SAT( P(s0) ^ ... ^ P(s_{k-1}) ^ T(s0,s1) ^ ... ^
 **                   T(s_{k-1},sk) ^ ~P(sk) )
 **              — proves k-inductiveness of P.
 **
 ** When the inductive check fails a CTI (counterexample to induction) is
 ** extracted, generalised via literal_drop(), and the resulting lemma is
 ** asserted permanently to strengthen future queries.
 **
 **/

#include "pdk_ind.h"

#include "utils/logger.h"

using namespace smt;

namespace pono {

PDKind::PDKind(const SafetyProperty & p,
               const TransitionSystem & ts,
               const SmtSolver & solver,
               PonoOptions opt)
    : super(p, ts, solver, opt, Engine::PDKIND)
{
}

void PDKind::initialize()
{
  if (initialized_) {
    return;
  }
  super::initialize();
  false_ = solver_->make_term(false);
}

// ---------------------------------------------------------------------------
// check_until
// ---------------------------------------------------------------------------
ProverResult PDKind::check_until(int k)
{
  initialize();
  // reached_k_ starts at -1 (set by SafetyProver); assert that invariant.
  assert(reached_k_ == -1);

  for (int i = 0; i <= k; ++i) {
    logger.log(1, "PDKind checking at bound {}", i);

    // Permanently extend the unrolled transition relation by one step.
    // T(0)...T(i-2) were asserted in previous iterations and persist.
    // Both base_check and inductive_check rely on this background context.
    if (i > 0) {
      solver_->assert_formula(unroller_.at_time(ts_.trans(), i - 1));
    }

    // ---- Base check --------------------------------------------------------
    // Check SAT( I ^ T^i ^ ~P_i ).  T(0)...T(i-1) are already in background.
    if (base_check(i)) {
      compute_witness();
      return ProverResult::FALSE;
    }

    // ---- Inductive check ---------------------------------------------------
    // Check UNSAT( P_0 ^ ... ^ P_{i-1} ^ T^i ^ ~P_i ).
    //
    // Contract: pops only on UNSAT; on SAT context remains pushed.
    if (inductive_check(i)) {
      // UNSAT — P is i-inductive.  Solver already popped inside the check.
      logger.log(1, "PDKind: property proved {}-inductive", i);
      return ProverResult::TRUE;
    }

    // SAT — inductive step failed.
    // Extract CTI while the solver context is still pushed, then pop.
    // (At i=0 there is no pre-state k-1 = -1, so skip CTI extraction.)
    if (i > 0) {
      TermVec cti_lits = extract_cti(i);

      // CRITICAL: pop the inductive hypothesis context before generalising.
      solver_->pop();

      smt::Term lemma = literal_drop(cti_lits, i);
      lemmas_.push_back(lemma);
      logger.log(2, "PDKind: new lemma at k={}: {}", i, lemma->to_string());

      // Assert the lemma permanently in the background solver context so it
      // strengthens every future base and inductive query.
      solver_->assert_formula(lemma);
    } else {
      solver_->pop();
    }

    reached_k_ = i;
  }

  return ProverResult::UNKNOWN;
}

// ---------------------------------------------------------------------------
// Base check: SAT( I(s0) ^ T(s0,s1) ^ ... ^ T(s_{k-1},sk) ^ ~P(sk) )
// T(0)...T(k-1) are already in the permanent background context.
// Only I(s0) and bad(k) are pushed into the temporary scope.
// ---------------------------------------------------------------------------
bool PDKind::base_check(int k)
{
  solver_->push();

  solver_->assert_formula(unroller_.at_time(ts_.init(), 0));
  solver_->assert_formula(unroller_.at_time(bad_, k));

  Result res = solver_->check_sat();
  bool cex_found = res.is_sat();

  solver_->pop();
  return cex_found;
}

// ---------------------------------------------------------------------------
// Inductive check: SAT( P_0 ^ ... ^ P_{k-1} ^ T^k ^ ~P_k )
// T(0)...T(k-1) are already in the permanent background context.
// Only the inductive hypothesis P(s0)...P(s_{k-1}) and bad(k) are pushed.
//
// Returns TRUE  (UNSAT) — k-inductive; solver is popped.
// Returns FALSE (SAT)   — not k-inductive; solver context left pushed so
//                         caller can call extract_cti() before popping.
// ---------------------------------------------------------------------------
bool PDKind::inductive_check(int k)
{
  solver_->push();

  Term good = solver_->make_term(Not, bad_);
  for (int j = 0; j < k; ++j) {
    solver_->assert_formula(unroller_.at_time(good, j));
  }
  solver_->assert_formula(unroller_.at_time(bad_, k));

  Result res = solver_->check_sat();

  if (res.is_unsat()) {
    solver_->pop();
    return true;
  }
  // SAT: leave context pushed; caller extracts CTI then pops.
  return false;
}

// ---------------------------------------------------------------------------
// extract_cti: read model values at time k-1 for every state variable.
//
// Must be called while the solver is still in the SAT state left by
// inductive_check() returning FALSE.
//
// Returns a TermVec of untimed literals (one per state variable):
//   Bool sort  →  v  (if true)  or  ¬v  (if false)
//   Other sort →  v == model_value
// ---------------------------------------------------------------------------
TermVec PDKind::extract_cti(int k)
{
  TermVec literals;
  const int pre_step = k - 1;  // pre-state of the failing inductive step

  for (const auto & v : ts_.statevars()) {
    Term v_at_pre = unroller_.at_time(v, pre_step);
    Term val = solver_->get_value(v_at_pre);

    Term lit;
    if (v->get_sort()->get_sort_kind() == BOOL) {
      bool is_true = (val == solver_->make_term(true));
      lit = is_true ? v : solver_->make_term(Not, v);
    } else {
      lit = solver_->make_term(Equal, v, val);
    }
    literals.push_back(lit);
  }

  return literals;
}

// ---------------------------------------------------------------------------
// literal_drop: greedily minimise the CTI cube and return a generalised lemma.
//
// T(k-1) is already in the permanent background context; each push scope
// only needs the subset of CTI literals and bad(k).
//
// For each literal cti[i]:
//   Push a scope with:  kept_literals @ (k-1)
//                     + {cti[i+1], ..., cti[n-1]} @ (k-1)
//                     + bad(k)          [T(k-1) comes from background]
//   If UNSAT → cti[i] is essential; keep it.
//   If SAT   → cti[i] is droppable; skip it.
//   Pop scope.
//
// Returns ¬( ∧ kept_literals ) — a clause over untimed state variables.
// ---------------------------------------------------------------------------
Term PDKind::literal_drop(const TermVec & cti, int k)
{
  TermVec kept_literals;

  for (size_t i = 0; i < cti.size(); ++i) {
    solver_->push();

    // Assert kept literals timed at k-1.
    for (const auto & lit : kept_literals) {
      solver_->assert_formula(unroller_.at_time(lit, k - 1));
    }

    // Assert remaining literals (excluding cti[i]) timed at k-1.
    for (size_t j = i + 1; j < cti.size(); ++j) {
      solver_->assert_formula(unroller_.at_time(cti[j], k - 1));
    }

    // T(k-1) is already in the permanent background; only assert bad(k).
    solver_->assert_formula(unroller_.at_time(bad_, k));

    if (solver_->check_sat().is_unsat()) {
      // Without cti[i] the cube cannot reach bad — this literal is essential.
      kept_literals.push_back(cti[i]);
    }
    // If SAT: still reaches bad without cti[i] — safely dropped.

    solver_->pop();
  }

  // Build the negated cube (lemma = ¬( ∧ kept_literals )).
  // If every literal was droppable (bad is reachable from any state),
  // return a trivially true lemma (no useful constraint to add).
  if (kept_literals.empty()) {
    logger.log(2, "PDKind: literal_drop: all literals droppable at k={}", k);
    return solver_->make_term(true);
  }

  Term cube = kept_literals[0];
  for (size_t i = 1; i < kept_literals.size(); ++i) {
    cube = solver_->make_term(And, cube, kept_literals[i]);
  }
  return solver_->make_term(Not, cube);
}

}  // namespace pono
