# Gaussian 16 Basis Sets

## Overview

Most methods require a basis set specification. If no basis set keyword is included, STO-3G is used by default. Exceptions include:

- All semi-empirical methods (including ZIndo)
- All molecular mechanics methods
- Compound model chemistries: all Gn, CBS and W1 methods

Basis sets can also be input using `ExtraBasis` and `Gen` keywords. `ChkBasis` reads the basis set from the checkpoint file.

## Built-in Basis Sets

### Pople Basis Sets

| Keyword | Elements | Notes |
|---------|----------|-------|
| STO-3G | H-Kr | Minimal basis |
| 3-21G | H-Xe | Split valence, accepts * suffix (no actual polarization) |
| 6-21G | H-Cl | Split valence |
| 4-31G | H-Ne | Split valence |
| 6-31G | H-Kr | Split valence, most widely used |
| 6-311G | H-Kr | Triple-split valence |

#### Polarization and Diffuse Functions

- **`*` or `**`**: Single polarization. `*` adds d to heavy atoms; `**` adds d to heavy and p to H. `6-31G**` = `6-31G(d,p)`
- **`(d,p)`**: Explicit polarization specification
- **`(3df,2p)`**: Multiple polarization sets
- **`+`**: Diffuse functions on heavy atoms
- **`++`**: Diffuse functions on heavy atoms and hydrogen
- **`6-31+G(3df,2p)`**: 6-31G + diffuse + 3d + 1f on heavy, 2p on H

The 6-31G(d') and 6-31G(d',p') keywords access Petersson's CBS basis sets.

### Dunning Correlation-Consistent Basis Sets

| Keyword | Type | Notes |
|---------|------|-------|
| cc-pVDZ | Double-zeta | Polarization included by definition |
| cc-pVTZ | Triple-zeta | |
| cc-pVQZ | Quadruple-zeta | |
| cc-pV5Z | Quintuple-zeta | |
| cc-pV6Z | Sextuple-zeta | |

**Polarization functions per atom:**

| Atoms | cc-pVDZ | cc-pVTZ | cc-pVQZ | cc-pV5Z |
|-------|---------|---------|---------|---------|
| H | 2s,1p | 3s,2p,1d | 4s,3p,2d,1f | 5s,4p,3d,2f,1g |
| B-Ne | 3s,2p,1d | 4s,3p,2d,1f | 5s,4p,3d,2f,1g | 6s,5p,4d,3f,2g,1h |
| Na-Ar | 4s,3p,1d | 5s,4p,2d,1f | 6s,5p,3d,2f,1g | 7s,6p,4d,3f,2g,1h |

**Diffuse augmentation:**

- `AUG-cc-pVnZ`: Add one diffuse function of each angular momentum
- `spAug-cc-pVnZ`: Augment with s and p only (including H/He)
- `dAug-cc-pVnZ`: Two shells of each angular momentum

**Truhlar "calendar" basis sets** (removing diffuse functions from AUG):
- `Jul-cc-pVnZ`: Remove diffuse from H/He
- `Jun-cc-pVnZ`: Also remove highest angular momentum diffuse from others
- `May-cc-pVnZ`: Remove two highest angular momentum functions
- `Apr-cc-pVnZ`: Remove three highest angular momentum functions

### Ahlrichs/def2 Basis Sets

| Keyword | Type | Notes |
|---------|------|-------|
| SV, SVP | Split valence | Older definitions |
| TZV, TZVP | Triple zeta | Older definitions |
| Def2SV, Def2SVP, Def2SVPP | Split valence | Newer redefinitions |
| Def2TZV, Def2TZVP, Def2TZVPP | Triple zeta | Newer redefinitions |
| Def2QZV, Def2QZVP, Def2QZVPP | Quadruple zeta | Newer redefinitions |
| QZVP | Quadruple zeta | |

Note: `Def2SVPP` corresponds to "def2-SV(P)" in the literature.

### Dunning/Huzinaga Basis Sets

| Keyword | Description |
|---------|-------------|
| D95V | Valence double-zeta |
| D95 | Full double-zeta |

### ECP (Effective Core Potential) Basis Sets

| Keyword | Description | Elements |
|---------|-------------|----------|
| LanL2MB | STO-3G on 1st row, Los Alamos ECP+MBS on Na-La, Hf-Bi | H-La, Hf-Bi |
| LanL2DZ | D95V on 1st row, Los Alamos ECP+DZ on Na-La, Hf-Bi | H, Li-La, Hf-Bi |
| SDD | D95 to Ar, Stuttgart/Dresden ECPs on remainder | All but Fr, Ra |
| SDDAll | Stuttgart potentials for Z > 2 | All |
| CEP-4G | Stevens/Basch/Krauss ECP minimal basis | H-Rn |
| CEP-31G | Stevens/Basch/Krauss ECP split valence | H-Rn |
| CEP-121G | Stevens/Basch/Krauss ECP triple-split | H-Rn |

### Specialized Basis Sets

| Keyword | Description |
|---------|-------------|
| EPR-II, EPR-III | Optimized for hyperfine coupling constants (DFT, especially B3LYP) |
| UGBS | Universal Gaussian basis set (H-Lr) |
| MTSmall | Part of W1 method |
| DGDZVP, DGDZVP2, DGTZVP | DGauss basis sets |
| CBSB7 | 6-311G(2d,d,p) for CBS-QB3 |
| MIDI! | Truhlar's MidiX basis set |

### Basis Set Applicability Table

| Basis Set | Elements | Polarization | Diffuse |
|-----------|----------|-------------|---------|
| 3-21G | H-Xe | * (2nd row only) | + |
| 6-21G | H-Cl | * or ** | - |
| 4-31G | H-Ne | * or ** | - |
| 6-31G | H-Kr | through (3df,3pd) | +,++ |
| 6-311G | H-Kr | through (3df,3pd) | +,++ |
| D95 | H-Cl (except Na,Mg) | through (3df,3pd) | +,++ |
| D95V | H-Ne | (d) or (d,p) | +,++ |
| LanL2MB | H-La, Hf-Bi | - | - |
| LanL2DZ | H, Li-La, Hf-Bi | - | - |
| SDD/SDDAll | All but Fr, Ra | - | - |
| cc-pVDZ-V5Z | H-Ar, Ca-Kr | included | AUG- prefix |
| SV-SVP | H-Kr | (SVP included) | - |
| Def2 series | H-La, Hf-Rn | included | - |
| EPR-II/III | H, B-F | included | - |

## Gen and GenECP Keywords

The `Gen` keyword allows specifying a custom basis set in an additional input section. `GenECP` allows specifying both basis set and ECP together.

```
\# HF/Gen

Title

0 1
C  0.0 0.0 0.0
H  0.0 0.0 1.09
...

C 0
6-31G(d)
****
H 0
3-21G
****
```

\## Pure vs. Cartesian Functions

- `5D`: Use 5 pure d functions (default for most basis sets)
- `6D`: Use 6 Cartesian d functions
- `7F`: Use 7 pure f functions (default for all built-in basis sets)
- `10F`: Use 10 Cartesian f functions

**Default behavior:**
- Most built-in basis sets use pure d functions
- Exceptions (use Cartesian d by default): 3-21G, 6-21G, 4-31G, 6-31G, CEP-31G, D95, D95V
- All basis sets use pure f functions

**Rules:**
- Within a job, all d functions must be 5D or 6D
- All f and higher functions must be pure or Cartesian
- `Gen` basis sets default to 5D and 7F
- Explicit `6D` in route section overrides defaults

## Density Fitting Basis Sets

Density fitting expands the density in atom-centered functions for Coulomb interaction computation. Provides significant speedup for pure DFT calculations.

### Syntax

```
\# BLYP/TZVP/TZVPFit
```

Slashes must separate method, basis set, and fitting set.

### Available Fitting Sets

| Keyword | Description |
|---------|-------------|
| DGA1 | Available H-Xe |
| DGA2 | Available H, He, B-Ne |
| SVPFit | For SVP basis set |
| TZVPFit | For TZVP basis set |
| W06 | For SVP, TZV, QZVP |
| Fit | Auto-select corresponding fitting set |
| NoFit | Disable density fitting |
| Auto | Generate fitting set automatically |

### Auto-generated Fitting Sets

The `Auto` keyword generates fitting sets from AO primitives. Default truncation: `Max(MaxTyp+1, 2*MaxVal)` where MaxTyp is highest angular momentum in AO basis and MaxVal is highest valence angular momentum.

- `Auto=All`: Use all generated functions
- `Auto=N`: Maximum angular momentum N
- `PAuto`: Products of AO functions on one center (usually more than needed)

### Usage Notes

- No fitting set used by default
- `ExtraDensityBasis` augments density fitting sets
- `Gen` keyword can define fitting sets
- Can be set as default in `Default.Route` via `DensityFit` keyword
- Faster than exact Coulomb for systems up to several hundred atoms
- Slower than exact Coulomb with linear scaling for very large systems
