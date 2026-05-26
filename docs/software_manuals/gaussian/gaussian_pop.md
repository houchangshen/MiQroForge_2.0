# Gaussian 16 Population Analysis (Pop)

## Overview

Population analysis methods partition the electron density among atoms to determine atomic charges, bond orders, and orbital character. The `Pop` keyword controls which population analysis is performed.

## Pop Keyword Options

### Pop=Minimal (Default)

Default population analysis — only Mulliken charges and orbital populations are printed.

### Pop=Regular

Prints the full population analysis including Mulliken charges, overlap populations, and orbital contributions.

### Pop=Full

Prints all available population analysis data including full orbital population breakdown.

### Pop=NBO

Requests Natural Bond Orbital analysis (requires NBO program).

### Pop=CHF

Requests Complete Hirshfeld population analysis.

## Mulliken Population Analysis

The oldest and simplest method. Divides overlap population equally between atoms.

### Usage

```
\# HF/6-31G(d) Pop=Full
```

### Output Format

```
 Mulliken atomic charges:
            1
 1  C    -0.123456
 2  H     0.041152
 3  H     0.041152
 4  O    -0.301234
 5  H     0.342383
 Sum of Mulliken charges =   0.00000
```

### Limitations

- Basis set dependent (charges change significantly with basis set)
- Can give unphysical charges (e.g., negative charge on electropositive atoms)
- Not recommended for quantitative charge analysis

## Natural Population Analysis (NPA)

Based on Natural Atomic Orbitals (NAOs). More stable with respect to basis set changes than Mulliken.

### Usage

Requires NBO program interface:
```
\# B3LYP/6-31G(d) Pop=NBO
```

### Key Features

- More basis set independent than Mulliken
- Preserves chemical intuition about electronegativity
- Includes Natural Electron Configuration
- Provides Wiberg bond indices

## Atoms in Molecules (AIM)

Bader's Quantum Theory of Atoms in Molecules. Partitions space based on gradient paths of electron density.

### Usage

```
\# B3LYP/6-31G(d) Pop=AIM
```

### Key Features

- Partition based on zero-flux surfaces in electron density
- Provides atomic charges, volumes, and energies
- Topological analysis of bond critical points
- Basis set independent (based on density, not orbitals)

## ChelpG Charges

ChElPG (Charges from Electrostatic Potential Grid) fits atomic charges to reproduce the molecular electrostatic potential on a grid outside the van der Waals surface.

### Usage

```
\# B3LYP/6-31G(d) Pop=ChElPG
```

### Key Features

- Charges reproduce electrostatic potential
- Suitable for molecular dynamics force fields
- Grid-based fitting (not unique, depends on grid)
- Similar to MK but different grid definition

## MK (Merz-Kollman-Singh) Charges

Fits atomic charges to the electrostatic potential on concentric surfaces around the molecule.

### Usage

```
\# B3LYP/6-31G(d) Pop=MK
```

### Key Features

- Most widely used ESP-fitted charges
- Multiple concentric surfaces (typically 4 layers)
- Radii: 1.4, 1.6, 1.8, 2.0 times van der Waals radii
- Reproduces far-field electrostatic potential well

### Custom Radii

```
\# B3LYP/6-31G(d) Pop=MK(ReadRadii)
```

Custom radii specified in additional input section.

## Hirshfeld Charges

Partitions electron density based on promolecular (atomic) densities.

### Usage

```
\# B3LYP/6-31G(d) Pop=Hirshfeld
```

### Key Features

- Weight function: ρ_atom / ρ_promolecule
- More basis set independent than Mulliken
- Tends to give smaller charges than other methods
- Chemically reasonable

## HLYGAt (Hu-Lu-Yang with Gaussian Atoms)

Uses Gaussian's standard atomic densities instead of HLY's densities.

### Usage

```
\# B3LYP/6-31G(d) Pop=HLYGAt
```

## CM5 (Charge Model 5)

Truhlar's charge model based on Hirshfeld charges with parameterized corrections.

### Usage

```
\# B3LYP/6-31G(d) Pop=CM5
```

### Key Features

- Based on Hirshfeld with empirical corrections
- Better reproduces dipole moments
- Less basis set dependent than Mulliken

## Natural Orbitals

Natural orbitals are the eigenfunctions of the one-particle density matrix.

### Usage

```
\# B3LYP/6-31G(d) Pop=CNDO
```

Natural orbitals are automatically computed for correlated methods (MP2, CCSD, etc.) and printed in the output.

## Bond Order Analysis

### Wiberg Bond Indices

Available through NBO analysis or as part of population analysis:

```
\# B3LYP/6-31G(d) Pop=NBO
```

### Mayer Bond Order

Available with certain population analysis options.

## Comparison of Methods

| Method | Basis Set Dependence | Speed | Physical Basis |
|--------|---------------------|-------|----------------|
| Mulliken | Very high | Fast | Orbital partitioning |
| NPA (NBO) | Low | Moderate | Natural orbitals |
| AIM (Bader) | Low | Slow | Density topology |
| ChElPG | Moderate | Moderate | ESP fitting |
| MK | Moderate | Moderate | ESP fitting |
| Hirshfeld | Low | Fast | Promolecular density |
| CM5 | Low | Fast | Parameterized Hirshfeld |

## Practical Recommendations

- **For qualitative analysis**: Mulliken (quick, but basis set dependent)
- **For quantitative charges**: MK or ChElPG (reproduce ESP)
- **For basis set independence**: Hirshfeld, CM5, or NPA
- **For force field parameterization**: MK or ChElPG
- **For bond analysis**: NBO (Wiberg indices)
- **For topological analysis**: AIM (Bader)
- **For publication**: Report multiple methods for comparison

## Combining with Other Keywords

Population analysis can be combined with most calculation types:

```
\# B3LYP/6-31G(d) Opt Freq Pop=Full      # Opt + freq + population
\# MP2/cc-pVTZ Pop=NBO                    # MP2 + NBO analysis
\# HF/6-31G(d) SCRF=(Water) Pop=MK       # Solvated ESP charges
\# CASSCF/6-31G(d) Pop=Full              # CASSCF populations
```

## Reading Additional Input

For custom radii or other modifications:

```
\# B3LYP/6-31G(d) Pop=MK(ReadRadii)

Title

0 1
[molecule]

1.5 1.7 1.9 2.1
```

The additional section specifies radii multipliers for each atom type.
