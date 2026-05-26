# Gaussian 16 Input

## Overview

Gaussian 16 input consists of a series of lines in an ASCII text file. The basic structure includes several sections:

- **Link 0 Commands**: Locate and name scratch files (not blank line terminated)
- **Route section** (`#` lines): Specify calculation type, model chemistry, and other options (blank line terminated)
- **Title section**: Brief description of the calculation (blank line terminated). Required but not interpreted by Gaussian. Cannot exceed five lines.
- **Molecule specification**: Specify molecular system (blank line terminated)
- **Optional additional sections**: Additional input for specific job types (usually blank line terminated)

## Basic Input Example

A simple single point energy calculation on water:

```
\# HF/6-31G(d)

water energy

0   1
O  -0.464   0.177   0.0
H  -0.464   1.137   0.0
H   0.441  -0.143   0.0
```

The route and title sections each consist of a single line. The molecule specification begins with charge and spin multiplicity (0 charge, singlet), followed by Cartesian coordinates.

## Input with Link 0 and Additional Sections

```
%Chk=heavy
\# HF/6-31G(d) Opt=ModRedun

Opt job

0   1
atomic coordinates ...

3 8
2 1 3
```

This job requests a geometry optimization with a named checkpoint file. The section after molecule specification adds an additional bond and angle to internal coordinates.

## Syntax Rules

- Input is **free-format and case-insensitive**
- Spaces, tabs, commas, or forward slashes can separate items within a line. Multiple spaces treated as single delimiter.
- Options may be specified as:
  - `keyword = option`
  - `keyword(option)`
  - `keyword=(option1, option2, ...)`
  - `keyword(option1, option2, ...)`
- Multiple options enclosed in parentheses, separated by commas. Equals sign before parenthesis may be omitted.
- **Abbreviations**: All keywords and options may be shortened to their shortest unique abbreviation. For example, `Conventional` can be `Conven` but not `Conv` (ambiguous with `Convergence`).
- **File inclusion**: `@filename` includes contents of an external file. Appending `/N` prevents echoing in output.
- **Comments**: Begin with `!`, may appear anywhere on a line.

## Link 0 Commands

Link 0 commands specify scratch file locations and resource allocation. They appear at the very beginning of the input file and are **not** blank-line terminated.

### %Chk=filename

Specifies the checkpoint file name. The checkpoint file stores molecular geometry, basis set, wavefunction, and other calculation data for later use.

```
%Chk=water_hf
```

### %OldChk=filename

Specifies a previous checkpoint file to read data from (used with `Geom=Check`, `Guess=Read`, etc.).

```
%OldChk=previous_calc
```

### %NProc=N

Specifies the number of processors to use for the job.

```
%NProc=8
```

### %NProcShared=N

Specifies the number of shared-memory processors. Differs from `%NProc` in how memory is managed for parallel calculations.

```
%NProcShared=4
```

### %Mem=N

Specifies the total memory allocation. Can use KB, MB, GB, or MW (megawords, where 1 MW = 8 MB).

```
%Mem=1GB
%Mem=500MW
%Mem=1024MB
```

### %RWF=path

Specifies the read-write file location and size limits.

```
%RWF=/scratch/rwf,8GB
```

### %NoSave

Prevents saving the checkpoint file at the end of the job.

### %Save

Forces saving all scratch files at the end of the job.

## Route Section

The route section begins with `#` (or `#p` for verbose, `#t` for terse) and specifies the calculation type and model chemistry.

### Route Section Prefixes

- `#` — Normal output
- `#p` — Verbose output (recommended for debugging)
- `#t` — Terse output (minimal output)

### Route Section Format

```
\# [prefix] Method/BasisSet [Keywords...]
```

Examples:
```
\# HF/6-31G(d) Opt Freq
#p B3LYP/6-311+G(d,p) SCRF=(Solvent=Water) Pop=Full
#t MP2/cc-pVTZ SP
```

## Multistep Jobs

Multiple Gaussian jobs can be combined in a single input file, separated by `--Link1--`:

```
%Chk=freq
\# HF/6-31G(d) Freq

Frequencies at STP

Molecule specification

--Link1--
%Chk=freq
%NoSave
\# HF/6-31G(d) Geom=Check Guess=Read Freq=(ReadFC,ReadIsotopes)

Frequencies at 300 K

charge and spin

300.0  2.0
Isotope specifications
```

A blank line must precede the `--Link1--` line.

## Section Ordering

The following table lists the order of sections in a Gaussian input file:

| Section | Keywords | Final blank line? |
|---------|----------|-------------------|
| Link 0 commands | % commands | no |
| Route Section (# lines) | all | yes |
| Extra Overlays | ExtraOverlays | yes |
| Title section | all except Geom=AllCheck | yes |
| Molecule specification | all except Geom=AllCheck | yes |
| Connectivity specifications | Geom=Connect or ModConnect | yes |
| Alterations to frozen atoms | Geom=ReadOpt | yes |
| Modifications to coordinates | Opt=ModRedundant | yes |
| 2nd title and molecule specification | Opt=QST2 or QST3 | yes for both |
| Connectivity specs for 2nd set | Geom=Connect + Opt=QST2/QST3 | yes |
| 2nd alterations to frozen atoms | Geom=ReadOpt | yes |
| Modifications to 2nd set of coordinates | Opt=QST2 or QST3 | yes |
| 3rd title and initial TS structure | Opt=QST3 | yes for both |
| Connectivity specs for 3rd set | Geom=Connect + Opt=(ModRedun,QST3) | yes |
| 3rd alterations to frozen atoms | Geom=ReadOpt | yes |
| Modifications to 3rd set of coordinates | Opt=(ModRedun,QST3) | yes |
| PDB secondary structure information | automatic if residue info | yes |
| Atomic masses | ReadIsotopes option | yes |
| External | External=(...,ReadInput) | yes |
| Molecular Mechanics parameters | HardFirst, SoftFirst, SoftOnly, Modify | yes |
| Frequency of interest | CPHF=RdFreq or Freq=ROA | yes |
| Background charge distribution | Charge | yes |
| BOMD/ADMP input | ADMP/BOMD + ReadVelocity | yes |
| PCM input | SCRF=(ExternalIteration,Read) | yes |
| Coordinates for IRC table | IRC(Report=Read) | yes |
| Harmonic constraints | Geom=ReadHarmonic | yes |
| Semi-empirical parameters | Input option | yes |
| Basis set specification | Gen, GenECP, ExtraBasis | yes |
| Basis set alterations | Massage | yes |
| Finite field coefficients | Field=Read | yes |
| ECP specification | Pseudo=Cards, GenECP | yes |
| Density fitting basis set | ExtraDensityBasis | yes |
| PCM solvation model input | SCRF=Read | yes |
| DFTB parameters | DFTB | yes |
| Source for initial guess | Guess=Input | yes |
| Symmetry types to combine | Guess=LowSymm | no |
| Orbital specifications | Guess=Cards | yes |
| Orbital alterations | Guess=Alter | yes |
| Orbital reordering | Guess=Permute | yes |
| # Orbitals/GVB pair | GVB | no |
| Weights for CAS state averaging | CAS=StateAverage | yes |
| States of interest for SOC | CASSCF=SpinOrbit | no |
| Orbital freezing information | ReadWindow options | yes |
| EPT orbitals to refine | EPT=ReadAnharmonic | yes |
| Atoms for spin-spin coupling | NMR=ReadAtoms | yes |
| Alternate atomic radii | Pop=ReadRadii | yes |
| Data for electrostatic properties | Prop=Read | yes |
| NBO input | Pop=NBORead | no |
| Harmonic Normal Mode selection | Freq=SelectNormalModes | yes |
| Hindered Rotor input | Freq=ReadHindered | yes |
| Anharmonic Normal Mode selection | Freq=SelectAnharmonicModes | yes |
| Input for Anharmonic | Freq=ReadAnharmonic | yes |
| Input for FCHT | Freq=ReadFCHT | yes |
| Atom list for Pickett file | Output=Pickett | no |
| ACID output filename | NMR=CGST IOp(10/93=1) | yes |
| PROAIMS output filename | Output=WFN | no |
| Matrix element filename | Output=MatrixElement | yes |

## Title Section Notes

- Required in input but not interpreted by Gaussian
- Appears in output for identification
- Cannot exceed five lines
- Avoid these characters: `@  #  !  -  _  \  control characters (especially Ctrl-G)`
- Typical content: compound name, symmetry, electronic state
