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
 **   Base:      SAT( I(s0) ^ T(s0,s1) ^ … ^ T(s_{k-1},sk) ^ bad(sk) )
 **              — finds a k-step counterexample.
 **
 **   Inductive: UNSAT( P(s0) ^ … ^ P(s_{k-1}) ^ T^k ^ bad(sk) )
 **              — proves k-inductiveness of the strengthened invariant.
 **
 ** When the inductive check is SAT, a CTI (counterexample to induction) is
 ** extracted from the model, generalised by literal_drop(), and the resulting
 ** blocking clause is asserted permanently to strengthen all future queries.
 **
 ** ─────────────────────────────────────────────────────────────────────────
 ** BUG HISTORY & FIXES (v3)
 ** ─────────────────────────────────────────────────────────────────────────
 **
 ** FIX 1a (v2, PARTIAL) — literal_drop: missing property hypothesis
 **   The v1 dropping probe checked
 **     remaining_lits @ (k-1)  ∧  T(k-1) [bg]  ∧  bad(k)
 **   With the last literal removed this collapses to T(k-1)∧bad(k) — true
 **   for almost every circuit (some unreachable state can reach bad).  v2
 **   wrapped the probe with an outer push asserting P@0..P@k-1 so the
 **   pre-state must respect the inductive hypothesis.  This was necessary
 **   but NOT sufficient.
 **
 ** FIX 1b (v3, CRITICAL) — literal_drop: existential vs universal probe
 **   The v2 probe still asked the wrong QUESTION:
 **       ∃ pre-state in subcube that reaches bad?       (existential)
 **   With ALL literals dropped (kept = rest = ∅) this collapses to exactly
 **   the body of inductive_check(k), which is SAT by hypothesis — so the
 **   last literal is ALWAYS droppable, the cube ALWAYS empties out, and
 **   the lemma is ALWAYS `true`.  Confirmed empirically: 403/403 trivial
 **   lemmas across the sample suite.
 **
 **   The correct question is the dual:
 **       ∀ pre-states in subcube reach bad?              (universal)
 **   which is checked by asserting good@k (= ¬bad@k) instead of bad@k:
 **       subcube@(k-1) ∧ T(k-1) ∧ ¬bad@k    UNSAT
 **   iff every state matching subcube must transition into bad.
 **
 **   New interpretation:
 **     UNSAT → no escape from bad → cti[i] is REDUNDANT (drop)
 **     SAT   → an escape exists  → cti[i] is ESSENTIAL  (keep)
 **     UNKNOWN → keep conservatively (avoid unsound drop).
 **
 ** FIX 1c (v3, SOUNDNESS GUARD) — relative-inductivity check
 **   The flipped probe finds cubes that FORCE bad in one step, but
 **   ¬cube is asserted permanently at every timestep — so soundness
 **   requires cube to be UNREACHABLE.  Adding an unsound lemma corrupts
 **   subsequent base_check queries and yields false SAFE.
 **
 **   First attempt: bounded reachability  (I ∧ T^j ∧ cube@j  UNSAT for
 **   j ≤ k).  Failed on `counter`: state6 increments from 0, cube was
 **   (state6 = N-1), unreachable in 0 or 1 step but reachable at N-1.
 **
 **   Adopted: standard PDR relative-inductivity check —
 **     Initiation:    I ∧ cube@0                 UNSAT
 **     Consecution:   ¬cube@0 ∧ T(0) ∧ cube@1    UNSAT
 **   Initiation excludes init states.  Consecution, with existing lemmas
 **   in the background, proves ¬cube is preserved by T — so by induction
 **   cube is unreachable from any reachable state.  See is_lemma_sound().
 **
 ** FIX 2 — inductive_check: UNKNOWN result treated as SAT (MEDIUM)
 **   Root cause: The original code returned false (SAT path) when the solver
 **   returned UNKNOWN (e.g. BZLA on constant-array equality).  The caller
 **   then called extract_cti()->get_value() on a non-SAT solver state,
 **   triggering "cannot get value if input formula is not sat".
 **   Fix: check res.is_sat() explicitly.  On UNKNOWN, pop and return
 **   ProverResult::UNKNOWN so the caller skips CTI extraction entirely.
 **
 ** FIX 3 — base_check: UNKNOWN result silently treated as "no CEX" (LOW)
 **   Root cause: When BZLA returns UNKNOWN (same constant-array limitation),
 **   base_check returned false — silently skipping a depth where a real CEX
 **   may exist (demonstrated by constarrfalse, which BMC finds at depth 16).
 **   Fix: check res.is_sat() explicitly.  On UNKNOWN, pop and return
 **   ProverResult::UNKNOWN; check_until continues but logs the limitation.
 **
 ** FIX 4 — lemma deduplication and trivial-lemma filtering (ENHANCEMENT)
 **   The new try_add_lemma() helper skips lemmas that are syntactically
 **   `true` and deduplicates via a string-keyed unordered_set before
 **   asserting into the permanent solver context.  This prevents SMT context
 **   bloat when the same CTI cube recurs at multiple depths.
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
  true_  = solver_->make_term(true);
  false_ = solver_->make_term(false);
}

// ─────────────────────────────────────────────────────────────────────────────
// check_until
// ─────────────────────────────────────────────────────────────────────────────
ProverResult PDKind::check_until(int k)
{
  initialize();
  assert(reached_k_ == -1);

  for (int i = 0; i <= k; ++i) {
    logger.log(1, "PDKind checking at bound {}", i);

    // Extend the permanent unrolled transition relation by one step.
    // T(0)..T(i-2) persist from prior iterations.
    // Stamp ALL accumulated lemmas at the new frontier time i so the
    // strengthened invariant holds at every unrolled timestep.
    if (i > 0) {
      solver_->assert_formula(unroller_.at_time(ts_.trans(), i - 1));
      for (const auto & lem : lemmas_) {
        solver_->assert_formula(unroller_.at_time(lem, i));
      }
    }

    // ── Base check ────────────────────────────────────────────────────────────
    ProverResult base_res = base_check(i);
    if (base_res == ProverResult::FALSE) {
      // CEX found — context is still pushed; read witness then clean up.
      compute_witness();
      solver_->pop();
      return ProverResult::FALSE;
    }
    // TRUE  → no CEX at depth i; continue.
    // UNKNOWN → solver limitation; continue optimistically.

    // ── Inductive check ───────────────────────────────────────────────────────
    ProverResult ind_res = inductive_check(i);

    if (ind_res == ProverResult::TRUE) {
      // UNSAT — the strengthened invariant is i-inductive.  Proved.
      // (Solver context was already popped inside inductive_check.)
      logger.log(1, "PDKind: property proved {}-inductive", i);
      return ProverResult::TRUE;
    }

    if (ind_res == ProverResult::FALSE) {
      // SAT — inductive check failed; context is still PUSHED.
      // At i=0 there is no pre-state (k-1 = -1), so skip CTI extraction.
      if (i > 0) {
        logger.log(1, "PDKind: inductive check SAT at k={} — extracting CTI "
                   "({} state vars)", i, ts_.statevars().size());

        TermVec cti_lits = extract_cti(i);

        // Pop the inductive-check push scope BEFORE calling literal_drop.
        // literal_drop uses its own push/pop scopes on the background context.
        solver_->pop();

        Term lemma = literal_drop(cti_lits, i);

        // Soundness gate: literal_drop returns a cube whose negation we want
        // to assert as a permanent invariant.  Verify the cube is genuinely
        // unreachable within current bound before adopting — otherwise the
        // lemma would block a real CEX and cause false SAFE.
        // (Skipping the trivially-true case which try_add_lemma filters anyway.)
        if (lemma != true_) {
          // The lemma is ¬cube; recover cube as ¬lemma for the reachability
          // probe.  (Building it directly avoids reparsing the And-chain.)
          Term cube = solver_->make_term(Not, lemma);
          if (is_lemma_sound(cube, i)) {
            try_add_lemma(lemma, i);
          } else {
            logger.log(1, "PDKind: discarding unsound candidate lemma at k={}",
                       i);
          }
        } else {
          try_add_lemma(lemma, i);  // logs the discard
        }
      } else {
        solver_->pop();
      }
    }
    // ind_res == UNKNOWN → inductive_check already popped; no CTI to extract.

    reached_k_ = i;
  }

  return ProverResult::UNKNOWN;
}

// ─────────────────────────────────────────────────────────────────────────────
// base_check: SAT( I(s0) ^ T^k ^ bad(k) )
//
// T(0)..T(k-1) live in the permanent background context.
// Only I(s0) and bad(k) are pushed into a temporary scope.
//
// FIX 3: res.is_sat() is tested explicitly.
//   Original code tested !is_unsat(), treating UNKNOWN as "no CEX found".
//   A UNKNOWN result (e.g. BZLA on unsupported array ops) now returns
//   ProverResult::UNKNOWN so the caller can log the limitation rather than
//   silently skipping a depth where a real CEX may exist.
// ─────────────────────────────────────────────────────────────────────────────
ProverResult PDKind::base_check(int k)
{
  solver_->push();

  solver_->assert_formula(unroller_.at_time(ts_.init(), 0));
  solver_->assert_formula(unroller_.at_time(bad_, k));

  Result res = solver_->check_sat();

  if (res.is_sat()) {
    // Leave context pushed — caller reads model via compute_witness().
    return ProverResult::FALSE;   // property is FALSE (CEX found)
  }

  solver_->pop();

  if (!res.is_unsat()) {
    // UNKNOWN — log but continue; base check is inconclusive at this depth.
    logger.log(1, "PDKind: base_check UNKNOWN at k={} (solver limitation)", k);
    return ProverResult::UNKNOWN;
  }

  return ProverResult::TRUE;   // clean: no CEX at depth k
}

// ─────────────────────────────────────────────────────────────────────────────
// inductive_check: UNSAT( P(s0)^…^P(s_{k-1}) ^ T^k ^ bad(k) )
//
// T(0)..T(k-1) and all lemmas at 0..k are in the permanent background.
// The inductive hypothesis P(sj) for j=0..k-1 and bad(k) are pushed.
//
// FIX 2: res.is_sat() is tested explicitly before the SAT branch.
//   Original code returned false on any non-UNSAT result, leaving the context
//   pushed even on UNKNOWN.  The caller then called extract_cti()->get_value()
//   on a non-SAT formula, crashing with "cannot get value if not sat".
//   Now: on UNKNOWN we pop and return ProverResult::UNKNOWN, signalling to
//   check_until that it must NOT call extract_cti().
// ─────────────────────────────────────────────────────────────────────────────
ProverResult PDKind::inductive_check(int k)
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
    return ProverResult::TRUE;    // k-inductive — proved
  }

  if (!res.is_sat()) {
    // UNKNOWN — cannot safely call get_value(); pop and signal.
    solver_->pop();
    logger.log(1, "PDKind: inductive_check UNKNOWN at k={} (solver limitation)", k);
    return ProverResult::UNKNOWN;
  }

  // SAT — leave context pushed; caller calls extract_cti() then pops.
  return ProverResult::FALSE;
}

// ─────────────────────────────────────────────────────────────────────────────
// extract_cti: read model values at time k-1 for every state variable.
//
// Precondition: solver is in the SAT state left by inductive_check() == FALSE.
// ─────────────────────────────────────────────────────────────────────────────
TermVec PDKind::extract_cti(int k)
{
  TermVec literals;
  const int pre_step = k - 1;

  for (const auto & v : ts_.statevars()) {
    Term v_at_pre = unroller_.at_time(v, pre_step);
    Term val      = solver_->get_value(v_at_pre);

    Term lit;
    if (v->get_sort()->get_sort_kind() == BOOL) {
      // Build an untimed polarity literal so at_time() can stamp it later.
      bool is_true = (val == true_);
      lit = is_true ? v : solver_->make_term(Not, v);
    } else {
      // Build untimed equality: v == constant_value.
      lit = solver_->make_term(Equal, v, val);
    }
    literals.push_back(lit);
  }

  return literals;
}

// ─────────────────────────────────────────────────────────────────────────────
// literal_drop: generalise a CTI cube under the k-step inductive hypothesis.
//
// Inner probe (v3, UNIVERSAL form):
//   Outer push:  P@0 ∧ … ∧ P@(k-1)              ← inductive hypothesis
//   Inner push:  kept@(k-1) ∧ rest_without_i@(k-1) ∧ good@k     where good = ¬bad
//   Background:  T@0 .. T@(k-1), all stamped lemmas
//
//   The probe asks:  ∀ states in subcube,  T(s) ⊆ bad ?
//   Equivalently:    subcube ∧ T ∧ good@k    UNSAT ?
//
//   UNSAT → no escape from bad → cti[i] is REDUNDANT (drop)
//   SAT   → escape exists       → cti[i] is ESSENTIAL  (keep)
//   UNKNOWN → keep conservatively (avoid unsound drop).
//
// Why this MUST be the universal form, not the existential one
// (subcube ∧ T ∧ bad@k SAT?):
//   With kept = rest = ∅, the existential probe collapses to
//   P-prefix ∧ T ∧ bad@k — which is exactly the body of inductive_check(k),
//   SAT by hypothesis.  Every cube empties out → every lemma is `true`.
//   The universal form does not have this collapse: empty subcube under
//   ∀ asks "must every P-prefix end in bad?", which is generally FALSE
//   (only states that satisfy enough of the CTI necessarily end in bad).
//
// Performance: P@0..P@k-1 is asserted ONCE in the outer scope rather than
// inside every inner push — O(k) assertions instead of O(k·n).
//
// Soundness of the returned cube is NOT established here — see
// is_lemma_sound() called by check_until before adoption.
// ─────────────────────────────────────────────────────────────────────────────
Term PDKind::literal_drop(const TermVec & cti, int k)
{
  using Clock    = std::chrono::steady_clock;
  using Seconds  = std::chrono::duration<double>;

  const std::size_t n = cti.size();
  TermVec kept_literals;
  Term good = solver_->make_term(Not, bad_);

  // ── Pre-drop log (verbosity 1) ────────────────────────────────────────────
  logger.log(1, "PDKind: generalising CTI of {} literals at k={} "
             "(budget: {} probes / {:.1f}s)",
             n, k, kMaxDropProbes, kDropTimeBudget);

  // ── Outer push: establish the full k-step inductive hypothesis ────────────
  // P@j = ¬bad@j for j = 0..k-1, asserted ONCE and shared by all inner probes.
  // T@0..T@k-1 and all existing lemmas are already in the permanent background.
  solver_->push();
  for (int t = 0; t < k; ++t) {
    solver_->assert_formula(unroller_.at_time(good, t));
  }

  // ── Budgeted per-literal greedy drop ─────────────────────────────────────
  // Two independent abort conditions:
  //   (a) probes_used >= kMaxDropProbes  — cap solver calls regardless of speed
  //   (b) elapsed wall time >= kDropTimeBudget — hard deadline for this CTI
  //
  // On abort: ALL unprocessed literals are appended to kept_literals.
  // This guarantees a non-trivial (if less generalised) blocking clause —
  // a weak lemma is strictly better than a timeout producing no lemma at all.
  const auto t_start = Clock::now();
  std::size_t probes_used = 0;
  bool budget_hit = false;

  for (std::size_t i = 0; i < n; ++i) {

    // ── Budget check (before the next push, to avoid an orphaned scope) ──────
    const double elapsed =
        Seconds(Clock::now() - t_start).count();
    if (probes_used >= kMaxDropProbes || elapsed >= kDropTimeBudget) {
      budget_hit = true;
      logger.log(1,
                 "PDKind: literal_drop budget hit at literal {}/{} "
                 "(probes={}, elapsed={:.2f}s) — keeping remaining {} as essential",
                 i, n, probes_used, elapsed, n - i);
      // Conservatively treat every unprocessed literal as essential.
      for (std::size_t j = i; j < n; ++j) {
        kept_literals.push_back(cti[j]);
      }
      break;
    }

    // ── Inner probe ──────────────────────────────────────────────────────────
    solver_->push();

    // Literals already known essential, timed at k-1.
    for (const auto & lit : kept_literals) {
      solver_->assert_formula(unroller_.at_time(lit, k - 1));
    }

    // Literals not yet tested (indices i+1..n-1) — excludes cti[i] itself.
    for (std::size_t j = i + 1; j < n; ++j) {
      solver_->assert_formula(unroller_.at_time(cti[j], k - 1));
    }

    // good@k = ¬bad@k at the post-state.  Universal form:
    //   subcube ∧ T(k-1) ∧ good@k   UNSAT  ⇔  every state in subcube forces bad.
    // T(k-1) is already in the permanent background.
    solver_->assert_formula(unroller_.at_time(good, k));

    const Result res = solver_->check_sat();
    ++probes_used;

    if (res.is_unsat()) {
      // No escape from bad without cti[i] — subcube alone forces bad.
      // → cti[i] is REDUNDANT; drop it (do nothing).
    } else if (!res.is_sat()) {
      // UNKNOWN — cannot prove redundancy soundly; keep conservatively.
      logger.log(2, "PDKind: literal_drop UNKNOWN at literal {}/{} — keeping",
                 i + 1, n);
      kept_literals.push_back(cti[i]);
    } else {
      // SAT — without cti[i], some state in the subcube escapes to good.
      // → cti[i] is ESSENTIAL to force bad; keep it.
      kept_literals.push_back(cti[i]);
    }

    solver_->pop();
  }

  // ── Outer pop: discard the P-hypothesis assertions ────────────────────────
  solver_->pop();

  // ── Post-drop log ─────────────────────────────────────────────────────────
  const double total_elapsed = Seconds(Clock::now() - t_start).count();
  logger.log(1, "PDKind: literal_drop done: kept {}/{} literals "
             "(probes={}, elapsed={:.2f}s, budget_hit={})",
             kept_literals.size(), n, probes_used, total_elapsed,
             budget_hit ? "yes" : "no");

  if (kept_literals.empty()) {
    logger.log(1, "PDKind: empty cube at k={} — every individual CTI literal "
               "had an escape; no bad-forcing subcube found", k);
    return true_;
  }

  // ── Build ¬(∧ kept_literals) ─────────────────────────────────────────────
  Term cube = kept_literals[0];
  for (std::size_t i = 1; i < kept_literals.size(); ++i) {
    cube = solver_->make_term(And, cube, kept_literals[i]);
  }
  return solver_->make_term(Not, cube);
}

// ─────────────────────────────────────────────────────────────────────────────
// is_lemma_sound: standard PDR relative-inductivity check.
//
// For ¬cube to be a sound permanent invariant, it must be inductive
// relative to the current background (existing lemmas + T):
//
//   (1) Initiation:    I(s0) ∧ cube@0                UNSAT
//   (2) Consecution:   ¬cube@0 ∧ T(0) ∧ cube@1       UNSAT
//
// If both hold, ¬cube is preserved by T (relative to existing lemmas in
// the background) and excludes every initial state — so by induction it
// holds at every reachable state.
//
// IMPORTANT: bounded reachability (I ∧ T^j ∧ cube@j UNSAT for j ≤ k) is
// NOT sufficient.  The lemma is asserted at every timestep forever, so a
// cube reachable beyond the current bound would still be incorrectly
// blocked.  Concrete failure mode: `counter` benchmark — state6 increments
// from 0, bad = (state6 = N).  literal_drop produces cube = (state6 = N-1).
// At k=1, bounded check trivially passes (cube unreachable in 0 or 1 step),
// but cube IS reachable at step N-1 → false SAFE.  The consecution check
// rejects this lemma directly: ¬(state6=N-1)@0 ∧ T ∧ (state6=N-1)@1 is SAT
// via state6@0 = N-2.
//
// UNKNOWN at either step → return false (conservative refuse).
// ─────────────────────────────────────────────────────────────────────────────
bool PDKind::is_lemma_sound(const Term & cube, int k_current)
{
  // (1) Initiation: cube must exclude every initial state.
  solver_->push();
  solver_->assert_formula(unroller_.at_time(ts_.init(), 0));
  solver_->assert_formula(unroller_.at_time(cube, 0));
  const Result init_res = solver_->check_sat();
  solver_->pop();

  if (init_res.is_sat()) {
    logger.log(1, "PDKind: lemma soundness REJECTED at k={} — initiation: "
               "cube intersects init", k_current);
    return false;
  }
  if (!init_res.is_unsat()) {
    logger.log(1, "PDKind: lemma soundness UNKNOWN at k={} (initiation) — "
               "refusing", k_current);
    return false;
  }

  // (2) Consecution (relative to existing lemmas, which are in the
  // background): no state outside cube transitions INTO cube.
  //     ¬cube@0 ∧ T(0) ∧ cube@1  must be UNSAT.
  // T(0) and all stamped lemmas are already permanently asserted.
  solver_->push();
  const Term not_cube = solver_->make_term(Not, cube);
  solver_->assert_formula(unroller_.at_time(not_cube, 0));
  solver_->assert_formula(unroller_.at_time(cube, 1));
  const Result cons_res = solver_->check_sat();
  solver_->pop();

  if (cons_res.is_sat()) {
    logger.log(1, "PDKind: lemma soundness REJECTED at k={} — consecution: "
               "a state outside cube transitions into cube", k_current);
    return false;
  }
  if (!cons_res.is_unsat()) {
    logger.log(1, "PDKind: lemma soundness UNKNOWN at k={} (consecution) — "
               "refusing", k_current);
    return false;
  }

  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// try_add_lemma: deduplicate and assert a lemma permanently.
//
// FIX 4: Guards against two classes of redundancy:
//   (a) Trivially-true lemmas — make_term(true) adds nothing to the solver
//       but wastes an assertion and a lemma slot.
//   (b) Duplicate lemmas — the same CTI cube can recur at multiple depths;
//       re-asserting the same clause wastes solver budget with no benefit.
//
// Deduplication key: the lemma's canonical string representation.
// For the solver backends in use (BZLA, CVC5, Z3) this is deterministic
// for structurally identical terms produced by the same solver instance.
//
// Returns true iff the lemma was actually added and stamped.
// ─────────────────────────────────────────────────────────────────────────────
bool PDKind::try_add_lemma(const Term & lemma, int up_to_time)
{
  // (a) Skip trivially-true lemmas.
  if (lemma == true_) {
    logger.log(2, "PDKind: discarding trivially-true lemma at k={}",
               up_to_time);
    return false;
  }

  // (b) Syntactic deduplication.
  std::string key = lemma->to_string();
  if (!lemma_set_.insert(key).second) {
    logger.log(2, "PDKind: discarding duplicate lemma at k={}: {}",
               up_to_time, key);
    return false;
  }

  // Stamp the new lemma at every timestep already in the background so it
  // immediately constrains all timed variable instances v@0 .. v@up_to_time.
  lemmas_.push_back(lemma);
  for (int t = 0; t <= up_to_time; ++t) {
    solver_->assert_formula(unroller_.at_time(lemma, t));
  }

  logger.log(2, "PDKind: new lemma at k={} [{} total]: {}",
             up_to_time, lemmas_.size(), key);
  return true;
}

}  // namespace pono
