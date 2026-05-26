# Gaussian 16 NMR

## Overview

The `NMR` keyword predicts NMR shielding tensors and magnetic susceptibilities using HF, DFT, or MP2 methods.

## Methods for NMR Shielding

### GIAO (Default)

Gauge-Independent Atomic Orbital method. Uses atomic orbitals that depend on the magnetic field, making results independent of gauge origin.

```
\# B3LYP/6-31G(d) NMR
```

This is the recommended method and the default.

### CSGT

Continuous Set of Gauge Transformations. Uses a continuous set of gauge origins. Requires large basis sets for accurate results.

```
\# B3LYP/6-31G(d) NMR=CSGT
```

### IGAIM

Individual Gauges for Atoms In Molecules. Uses atomic centers as gauge origins. Slight variation on CSGT.

```
\# B3LYP/6-31G(d) NMR=IGAIM
```

### SingleOrigin

Uses a single gauge origin. Not generally recommended, provided for comparison only.

```
\# B3LYP/6-31G(d) NMR=SingleOrigin
```

### All Methods

Compute properties with all three methods (SingleOrigin, IGAIM, CSGT):

```
\# B3LYP/6-31G(d) NMR=All
```

## Output Format

### Shielding Tensors

```
Magnetic properties (GIAO method)

Magnetic shielding (ppm):
  1  C    Isotropic =    57.7345   Anisotropy =   194.4092
   XX=    48.4143   YX=      .0000   ZX=      .0000
   XY=      .0000   YY=   -62.5514   ZY=      .0000
   XZ=      .0000   YZ=      .0000   ZZ=   187.3406
  2  H    Isotropic =    23.9397   Anisotropy =     5.2745
   XX=    27.3287   YX=      .0000   ZX=      .0000
   XY=      .0000   YY=    24.0670   ZY=      .0000
   XZ=      .0000   YZ=      .0000   ZZ=    20.4233
```

**Key quantities:**
- **Isotropic shielding**: Average of diagonal elements (XX+YY+ZZ)/3
- **Anisotropy**: Measures deviation from spherical symmetry

### Chemical Shifts

Chemical shifts are computed relative to a reference:
δ = σ_ref - σ_calc

Common references (TMS for ¹H and ¹³C):
- ¹H TMS: ~31.0 ppm (calculated)
- ¹³C TMS: ~184.0 ppm (calculated)

## Spin-Spin Coupling Constants

### SpinSpin Option

Compute spin-spin coupling constants in addition to shielding:

```
\# B3LYP/6-31G(d) NMR=SpinSpin
```

**Cost**: About twice that of computing vibrational frequencies alone. Available only for HF and DFT.

### Mixed Option

Two-step calculation for improved accuracy:

```
\# B3LYP/6-311+G(d,p) NMR=(SpinSpin,Mixed)
```

Step 1: Modified basis for Fermi Contact term (uncontracted + tight polarization)
Step 2: Standard basis for other three terms

This significantly improves accuracy, especially with valence-oriented basis sets.

### Coupling Constant Output

```
 Total nuclear spin-spin coupling K (Hz):
                1             2
      1  0.000000D+00
      2  0.147308D+02  0.000000D+00
 Total nuclear spin-spin coupling J (Hz):
                1             2
      1  0.000000D+00
      2  0.432614D+03  0.000000D+00
```

- **K matrix**: Isotope-independent coupling constants
- **J matrix**: Isotope-specific coupling constants

### Coupling Components

The four contributions to spin-spin coupling:
1. **Fermi Contact (FC)**: Through-bond contact interaction
2. **Spin-Dipolar (SD)**: Dipolar interaction between nuclear spins
3. **Paramagnetic Spin-Orbit (PSO)**: Spin-orbit coupling contribution
4. **Diamagnetic Spin-Orbit (DSO)**: Diamagnetic contribution

## ReadAtoms Option

Calculate spin-spin coupling only for selected atoms:

```
\# B3LYP/6-31G(d) NMR=(SpinSpin,ReadAtoms)
```

Input section format:
```
atoms=list [notatoms=list]
```

Examples:
```
atoms=3-6,17 notatoms=5      # Atoms 3,4,6,17 except 5
atoms=3 C 18-30 notatoms=H   # All C and non-H among 3,18-30
atoms=C N notatoms=5          # All C and N except atom 5
```

Bare integers without keyword are interpreted as atom numbers:
```
1,3,5 7                       # Atoms 1, 3, 5, 7
```

## Other NMR Options

### PrintEigenvectors

Display eigenvectors of the shielding tensor for each atom:

```
\# B3LYP/6-31G(d) NMR=PrintEigenvectors
```

### FCOnly

Compute only Fermi contact spin-spin terms:

```
\# B3LYP/6-31G(d) NMR=(SpinSpin,FCOnly)
```

### ReadFC

Read Fermi contact terms from checkpoint, compute other terms:

```
\# B3LYP/6-31G(d) NMR=(SpinSpin,ReadFC)
```

### Susceptibility

Compute magnetic susceptibility in addition to shielding:

```
\# B3LYP/6-31G(d) NMR=Susceptibility
```

## Availability

- **Methods**: SCF, DFT, and MP2
- **Can combine with**: SCRF (solvation)
- **Can combine with**: Freq (for HF and DFT on same route)

## Practical Recommendations

### Basis Set Choice

- **GIAO**: Moderate basis sets adequate (6-311+G(d,p) or cc-pVTZ)
- **CSGT**: Requires large basis sets for accuracy
- **Spin-spin coupling**: aug-cc-pVTZ or aug-cc-pVQZ recommended

### Method Choice

- **Shielding**: B3LYP/6-311+G(d,p) GIAO is a good default
- **Coupling constants**: Use `Mixed` option for better accuracy
- **High accuracy**: MP2/GIAO or CCSD/GIAO

### Workflow

```
\# Step 1: Optimize geometry
\# B3LYP/6-311+G(d,p) Opt Freq

Title

0 1
[molecule]

--Link1--
\# Step 2: NMR calculation
%OldChk=step1.chk
\# B3LYP/6-311+G(d,p) NMR Geom=Check Guess=Read

NMR shielding

0 1

--Link1--
\# Step 3: Coupling constants
%OldChk=step1.chk
\# B3LYP/6-311+G(d,p) NMR=(SpinSpin,Mixed) Geom=Check Guess=Read

NMR coupling constants

0 1
```

### Tips

1. Always optimize geometry before NMR calculation
2. Use GIAO (default) for most applications
3. Use `Mixed` option for coupling constants
4. Report calculated shifts relative to TMS or other standard
5. Consider solvent effects with `SCRF` for solution NMR
6. For ¹⁹F or ³¹P, use larger basis sets (aug-cc-pVTZ)
