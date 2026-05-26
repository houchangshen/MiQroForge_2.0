# Gaussian 16 SCF Keyword

## Overview

The `SCF` keyword controls the Self-Consistent Field procedure behavior. In Gaussian 16, `SCF=Tight` is the default.

The default SCF procedure uses a combination of EDIIS and CDIIS, with no damping or Fermi broadening. The `SCF=QC` option is often helpful for difficult convergence cases.

## Algorithm Selection Options

### DIIS / NoDIIS

DIIS calls for Pulay's Direct Inversion in the Iterative Subspace extrapolation method. NoDIIS prohibits it.

### CDIIS

Use only CDIIS. Implies Damp as well.

### Fermi / NoFermi

Requests temperature broadening during early iterations, combined with CDIIS and damping. NoFermi is the default. Fermi also implies Damp and level shifting.

### Damp / NoDamp

Turn on dynamic damping of early SCF iterations. NoDamp is the default. Damping is enabled if `SCF=Fermi` or `SCF=CDIIS` is requested. Note: damping and EDIIS do not work well together.

### NDamp=N

Allow dynamic damping for up to N SCF iterations (default: 10).

### QC

Quadratically convergent SCF procedure. Slower than regular SCF with DIIS but more reliable. Not available for restricted open shell (RO) calculations.

### XQC

Add extra SCF=QC step if first-order SCF has not converged. Defaults to `MaxConventional=32`.

### YQC

New algorithm for difficult SCF convergence in very large molecules. Does steepest descent then scaled steepest descent, then switches to regular SCF; uses quadratic algorithm only if regular SCF fails. Defaults to `MaxConventional=32`.

### MaxConventionalCycles=N

Sets limit on conventional SCF cycles during SCF=XQC and SCF=YQC.

### PseudoDiagonalization=N (PDiag)

Use pseudo-diagonalization in Link 502, with full diagonalization only at early cycles, end, and every Nth cycle. Default for semi-empirical methods (N=30 default).

### FullDiagonalization (FDiag)

Forces full diagonalization in Link 502. Default for HF and DFT.

### SD / SSD

Steepest descent / scaled steepest descent SCF.

### DM

Direct minimization SCF. Usually inferior to SCF=QC. Available only for RHF closed shell and UHF open shell.

### VShift[=N]

Shift orbital energies by N*0.001 Hartrees (N defaults to 100). Disables automatic archiving. N=-1 disables level shifting.

### MaxCycle=N

Maximum number of SCF cycles (default: 64, or 512 for SCF=DM and SCF=QC).

### FullLinear

L508 (SCF=QC, SD, SSD) does full linear searches at each iteration.

### FinalIteration / NoFinalIteration

FinalIteration performs a final non-extrapolated, non-incremental iteration after DIIS/direct SCF convergence. Default: NoFinalIteration.

### IncFock / NoIncFock

Forces/prevents incremental Fock matrix formation. Default for direct SCF: IncFock. Default for conventional: NoIncFock.

### Pass / NoPass

For in-core calculations, saves integrals on disk to avoid recomputation. Only useful for frequency jobs with SCF=InCore.

### TightLinEq / VeryTightLinEq (VTL)

Tighter convergence in linear equation solution during SCF=QC. VeryTightLinEq for nearly linearly-dependent cases.

## Integral Storage Options

### Direct (default)

Two-electron integrals are recomputed as needed. Default for Gaussian 16.

### InCore / NoInCore

SCF performed storing full integral list in memory. Automatically done if sufficient memory available. Aborts if not enough memory.

### Conventional (NoDirect)

Two-electron integrals stored on disk and read each SCF iteration.

## Convergence and Cutoff Options

### Conver=N

Sets SCF convergence criterion to 10^(-N). Requires both:
- RMS change in density matrix < 10^(-N)
- Maximum change in density matrix < 10^(-(N-2))

Energy change is not used to test convergence.

### VarAcc / NoVarAcc (VarInt / NoVarInt)

Use modest integral accuracy early in direct SCF, switching to full accuracy later. Default for direct SCF.

### Tight

Normal, tight convergence. This is the default.

### Big

Turns off optional O(N³) steps to speed up very large calculations (>5000 basis functions).

### MaxNR=N

Maximum rotation gradient for Newton-Raphson step in SCF=QC and SCF=YQC to 10^(-N). Default N=2.

### PtDensity=N

Points per Angstrom² (N>0) or -N tesserae (N<0). Default: 5.

## Symmetry-Related Options

### IDSymm / NoIDSymm

Symmetrize density matrix at first iteration. Default: NoIDSymm.

### DSymm / NoDSymm

Symmetrize density matrix at every iteration. Default: NoDSymm. DSymm implies IDSymm.

### NoSymm

Lifts all orbital symmetry constraints. Synonymous with `Guess=NoSymm` and `Symm=NoSCF`.

### Symm

Retain all symmetry constraints: match number of occupied orbitals per symmetry type to initial guess. Default only for GVB.

### IntRep

Account for integral symmetry by replicating integrals. Default for L502 (RHF, ROHF, UHF) and L508 (SCF=QC).

### FockSymm (FSymm)

Account for integral symmetry by symmetrizing Fock matrices. This is the default.

## Restart-Related Options

### Save / NoSave

Save wavefunction on checkpoint file every iteration. Default for direct SCF.

### Restart

Restart SCF from checkpoint file. Cannot restart SCF=DM. SCF=Restart skips unnecessary steps when restarting.

## Practical Usage

### Convergence Problems

For difficult convergence cases, try in order:
1. `SCF=QC` — quadratically convergent, most reliable
2. `SCF=XQC` — falls back to QC if regular SCF fails
3. `SCF=YQC` — for very large molecules
4. `SCF=DM` — direct minimization, last resort
5. `SCF=(QC,MaxCycle=512)` — increase max cycles
6. `Guess=Mix` — break symmetry for open-shell systems
7. `Stable=Opt` — check and optimize for stability

### Initial Guess Methods

While not part of the SCF keyword, initial guess options affect convergence:
- `Guess=HCore` — diagonalize core Hamiltonian
- `Guess=Read` — read from checkpoint file
- `Guess=Mix` — mix HOMO and LUMO for open-shell singlets
- `Guess=Alter` — modify orbital assignments
- `Guess=Fragment` — use fragment wavefunctions

### Typical SCF Options

```
\# B3LYP/6-31G(d) SCF=Tight           # Default, tight convergence
\# B3LYP/6-31G(d) SCF=QC              # Quadratically convergent
\# B3LYP/6-31G(d) SCF=(QC,MaxCycle=256)  # QC with more cycles
\# B3LYP/6-31G(d) SCF=Conventional    # Store integrals on disk
\# B3LYP/6-31G(d) SCF=InCore          # All integrals in memory
\# B3LYP/6-31G(d) SCF=NoVarAcc        # Full accuracy from start
```
