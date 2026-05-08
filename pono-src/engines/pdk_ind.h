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
 ** strengthening check (checking whether P is k-inductive).  The engine
 ** is complete: if neither check fires within the given bound it reports
 ** UNKNOWN.
 **
 ** CTI extraction contract:
 **   inductive_check() pops the solver context only on UNSAT (proved).
 **   On SAT the context remains pushed so that extract_cti() can query
 **   model values; the caller (check_until) must call solver_->pop()
 **   before invoking literal_drop().
 **
 **/

#pragma once

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
  /** Check base case at step k: SAT( I ^ T^k ^ ~P_k ).
   *  Returns TRUE iff a counterexample was found (SAT). */
  bool base_check(int k);

  /** Check k-inductive step: SAT( P_0 ^ ... ^ P_{k-1} ^ T^k ^ ~P_k ).
   *
   *  Contract:
   *    Returns TRUE  (UNSAT) — property is k-inductive; solver popped.
   *    Returns FALSE (SAT)   — not yet k-inductive; solver context remains
   *                            pushed so that extract_cti() can read the
   *                            model.  Caller must call solver_->pop() before
   *                            calling literal_drop().
   */
  bool inductive_check(int k);

  /** Extract a Counterexample To Induction (CTI) from the current SAT model.
   *
   *  Must be called while the solver is still in the SAT state left by
   *  inductive_check() returning FALSE (before the pop).
   *
   *  For each state variable v, reads its value at time k-1 from the model
   *  and builds a literal over the *untimed* variable v:
   *    Bool sort : v (if true) or ¬v (if false)
   *    Other sort: v == model_value
   *
   *  Returns the literals as a TermVec (one entry per state variable).
   *  The caller receives the raw list for use in literal_drop().
   *
   *  @param k  depth of the preceding inductive_check call  (k >= 1)
   */
  smt::TermVec extract_cti(int k);

  /** Generalise a CTI cube by greedily dropping inessential literals.
   *
   *  For each literal cti[i] we test whether the remaining literals still
   *  reach the bad state in one step (at time indices k-1 → k):
   *
   *    SAT( kept ∪ {cti[i+1], …} @ (k-1)  ∧  T(k-1)  ∧  bad(k) )
   *
   *  If SAT  → cti[i] is not needed; drop it.
   *  If UNSAT → cti[i] is essential; keep it.
   *
   *  Returns ¬(∧ kept_literals) — a generalised clause over untimed state
   *  variables that can be asserted as a permanent lemma.
   *
   *  This method uses its own push/pop scopes and is safe to call after
   *  the inductive check context has been popped.
   *
   *  @param cti  untimed literal vector from extract_cti()
   *  @param k    depth of the inductive check that produced the CTI (k >= 1)
   */
  smt::Term literal_drop(const smt::TermVec & cti, int k);

  smt::Term false_;

  /** Accumulated lemmas (negated CTI cubes) asserted permanently. */
  smt::TermVec lemmas_;
};

}  // namespace pono
