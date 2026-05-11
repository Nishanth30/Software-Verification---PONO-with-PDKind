Property-Directed K-Induction (PDKInd) Engine for Pono

This repository contains a high-performance implementation of the PDKInd engine, integrated into the Pono SMT-based model checker. PDKInd leverages the strengths of K-Induction combined with property-directed lemma generation to enhance the formal verification of large-scale hardware transition systems.

Core Features

• CTI Extraction: Advanced extraction of Counter-Examples to Inducement (CTI) from the SMT solver during the inductive step to guide refinement and lemma generation.

• Lemma Sharing & Stamping: Automatically generates and generalizes inductive lemmas, stamping them across timed indices to accelerate convergence and eliminate untimed-lemma bugs.

• Incremental SMT Optimization: High-efficiency background context management utilizing incremental solving to minimize solver overhead during transition relation assertions.

• BTOR2 Compatibility: Optimized specifically for hardware model checking benchmarks in the BTOR2 format (HWMCC).

Technical Implementation

The engine architecture is integrated into the Pono framework across several core components:

• pono-src/engines/pdk_ind.cpp: Core algorithmic logic for the PDKInd induction loop and property-directed refinement.

• pono-src/engines/pdk_ind.h: Engine state management and architecture definitions.

• pono-src/utils/make_provers.cpp: Factory integration to enable the --engine pdkind command-line flag.

• pono-src/options/options.cpp: Configuration and tuning flags for the PDKInd solver.

Building and Usage

1. Prerequisites

Ensure the standard Pono dependencies are configured:

• smt-switch (Bitwuzla or Z3 backend recommended)

• Btor2Tools

2. Build

[bash]
mkdir build && cd build
cmake ..
make -j$(nproc)


3. Running the Engine

To execute formal verification on a benchmark using the PDKInd engine:

[bash]
./pono --engine pdkind <path_to_benchmark>.btor2



