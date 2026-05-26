# Gaussian 16 ONIOM

## Overview

The `ONIOM` keyword requests a two- or three-layer ONIOM calculation. The molecular system is divided into layers treated with different model chemistries, and results are automatically combined.

**Layers**: Conventionally called Low, Medium, and High. By default, atoms are placed in the High layer.

## Model Chemistry Specification

Layers are specified in the route section as options to the ONIOM keyword, separated by colons:

```
\# ONIOM(High:Low)                  # 2-layer
\# ONIOM(High:Medium:Low)           # 3-layer
```

### Examples

```
\# ONIOM(B3LYP/6-31G(d,p):UFF)         # DFT high, UFF low
\# ONIOM(HF/6-31G(d):PM6:UFF)          # HF high, PM6 medium, UFF low
\# ONIOM(MP2/6-31G(d):HF/STO-3G)       # MP2 high, HF low
\# ONIOM(BLYP/6-31G(d)/Auto:UFF)       # With density fitting
```

## Molecule Specification

Layer assignment is done in the molecule specification via additional parameters:

```
atom [freeze-code] coordinate-spec layer [link-atom [bonded-to [scale-fac1 [scale-fac2 [scale-fac3]]]]]
```

### Layer Assignment

- `H` or `High`: High layer (most accurate method)
- `M` or `Medium`: Medium layer
- `L` or `Low`: Low layer (least accurate, fastest)

### Freeze Code

- `0` or omitted: Atom optimized normally
- `-1`: Atom frozen during optimization
- Other negative integer: Atom part of rigid fragment (same value = same block)

### Link Atoms

Link atoms saturate dangling bonds at layer boundaries when covalent bonds span different layers.

```
C     0.0  0.0  0.0  M  H  4
```

This places C in Medium layer, with a hydrogen link atom bonded to atom 4.

**Important**: All link atoms must be specified by the user. Gaussian does not define them automatically.

### Bonded-to Parameter

Specifies which atom the current atom is bonded to during the higher-level calculation. If omitted, Gaussian attempts to identify it automatically.

### Scale Factors

Link atom bond distances are scaled from the original bond distance. For a 2-layer calculation:
- Scale factor 1: Link atom distance at low level
- Scale factor 2: Link atom distance at high level

For a 3-layer calculation, up to three scale factors (low, medium, high). Setting 0.0 lets the program determine the factor automatically.

## Example Molecule Specifications

### Simple 2-Layer ONIOM

```
\# ONIOM(B3LYP/6-31G(d,p):UFF) Opt

2-layer ONIOM optimization

0 1 0 1 0 1
  F     -1.041506214819     0.000000000000    -2.126109488809 M
  F     -2.033681935634    -1.142892069126    -0.412218766901 M
  F     -2.033681935634     1.142892069126    -0.412218766901 M
  C     -1.299038105677     0.000000000000    -0.750000000000 M H 4
  C      0.000000000000     0.000000000000     0.000000000000 H
  H      0.000000000000     0.000000000000     1.100000000000 H
  O      1.125833024920     0.000000000000    -0.650000000000 H

```

### With Amber Force Field

```
\# ONIOM(B3LYP/6-31G(d):Amber) Geom=Connectivity

2 layer ONIOM job

0 1 0 1 0 1
 C-CA--0.25   0   -4.703834   -1.841116   -0.779093 L
 C-CA--0.25   0   -3.331033   -1.841116   -0.779093 L H-HA-0.1  3
 C-CA--0.25   0   -2.609095   -0.615995   -0.779093 H
 C-CA--0.25   0   -3.326965    0.607871   -0.778723 H
 C-CA--0.25   0   -4.748381    0.578498   -0.778569 H
 C-CA--0.25   0   -5.419886   -0.619477   -0.778859 L H-HC-0.1  5
 H-HA-0.1     0   -0.640022   -1.540960   -0.779336 L
 H-HA-0.1     0   -5.264565   -2.787462   -0.779173 L
```

## Per-Layer Charge and Spin Multiplicity

Multiple charge/spin pairs can be specified for different layers.

### 2-Layer Format

```
chrgreal-low spinreal-low [chrgmodel-high spinmodel-high [chrgmodel-low spinmodel-low]]
```

### 3-Layer Format

```
cRealL sRealL [cIntM sIntM [cIntL sIntL [cModH sModH [cModM sModM [cModL sModL]]]]]
```

When fewer pairs are specified, defaults are taken from the next higher level.

## Embedding Options

### Mechanical Embedding (Default)

MM region treated as point charges. No polarization of QM region by MM.

### Electronic Embedding

```
ONIOM=EmbedCharge
```

Incorporates MM partial charges into QM Hamiltonian. Provides:
- Better electrostatic interaction between QM and MM regions
- QM wavefunction polarization by MM environment

### Charge Models for Embedding

| Option | Description |
|--------|-------------|
| MKUFF | Merz-Kollman-Singh with UFF radii (default) |
| MK | Merz-Kollman-Singh charges |
| Mulliken | Mulliken charges |
| HLYGAt | Hu-Lu-Yang with Gaussian atomic densities |

### ScaleCharge=ijklmn

Scales MM charges during electronic embedding. Integers multiplied by 0.2 for actual scale factors. Default: 500 (i.e., 555500 — charges within 2 bonds of QM region turned off).

```
ONIOM=(EmbedCharge,ScaleCharge=555500)
```

## Optimization Options

### Microiterations (Default for MO:MM)

Uses RFO algorithm for model system atoms and linear microiterations for real system atoms.

### QuadMacro

Quadratic coupled algorithm for more accurate steps:

```
Opt=QuadMacro
```

Takes into account coupling between model system atoms and MM-only atoms.

### Recommendations

- For minima: Default algorithm usually best
- For convergence problems: `Opt=QuadMac`
- For transition structures: `Opt=(QuadMac,TS,CalcFC)`
- Start with mechanical embedding, then refine with electronic embedding

## ONIOM Options

### SValue

Produces substituent values (S-values) for testing:

```
ONIOM=SValue
```

### Compress / NoCompress

Compress operations and storage to active atoms during MO:MM mechanical embedding second derivative calculations. Default: Compress.

### InputFiles / OnlyInputFiles

Print input files for each intermediate calculation:

```
ONIOM=InputFiles       # Print and run
ONIOM=OnlyInputFiles   # Print only, don't run
```

## Availability

- Energies, gradients, and frequencies
- If any model requires numerical frequencies, all models use numerical
- CIS and TD calculations for one or more layers
- Gen, GenECP, ChkBasis keywords for relevant models
- Density fitting sets when applicable
- NMR calculations

## Practical Workflow

### Basic ONIOM Optimization

```
%Chk=oniom.chk
\# ONIOM(B3LYP/6-31G(d):UFF) Opt

2-layer ONIOM optimization

0 1 0 1
[coordinates with layer assignments]
```

### Handling SCF Convergence Issues

1. Run with `ONIOM=OnlyInputFiles` to get individual input files
2. Converge the problematic layer separately
3. Run ONIOM with `Guess=Input` reading the converged checkpoint

```
%Chk=mychk
\# ONIOM(BLYP/3-21G:UFF) Opt Freq Guess=Input

ONIOM Opt Freq

molecule specification

highmod.chk    Checkpoint file for Guess=Input

```

### Complete ONIOM Workflow

```
\# Step 1: Mechanical embedding optimization
%Chk=step1.chk
\# ONIOM(B3LYP/6-31G(d):UFF) Opt

Title

0 1 0 1
[coordinates]

--Link1--
\# Step 2: Electronic embedding optimization
%OldChk=step1.chk
%Chk=step2.chk
\# ONIOM(B3LYP/6-31G(d):UFF) Opt=(QuadMac,TS,CalcFC) EmbedCharge

Title

0 1 0 1
[coordinates]

--Link1--
\# Step 3: Frequency at final geometry
%OldChk=step2.chk
\# ONIOM(B3LYP/6-31G(d):UFF) Freq EmbedCharge Geom=Check Guess=Read

Title

0 1 0 1
```

## Related Keywords

- `Geom=Connect`: Connectivity specification
- `Molecular Mechanics Methods`: UFF, Amber, Dreiding
- `Opt=QuadMacro`: Quadratic macroiteration
- `External`: External program for one or more levels
