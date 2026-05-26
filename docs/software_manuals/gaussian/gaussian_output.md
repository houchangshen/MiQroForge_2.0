# Gaussian 16 Output

## Overview

The `Output` keyword creates input files for external programs or writes Fortran unformatted files containing calculation results. Its options control the contents of the created file.

## Wavefunction File Output

### WFN (PSI)

Write a PROAIMS wavefunction (.wfn) file. The filename is read from the input stream on a separate line.

```
\# B3LYP/6-31G(d) Output=WFN

Title

0 1
[molecule]

output.wfn
```

### WFX (WfnX)

Write a wavefunction file for newer versions of AIMPAC (.wfx files). Filename read from input stream.

```
\# B3LYP/6-31G(d) Output=WFX

Title

0 1
[molecule]

output.wfx
```

### GIAOCx / CSGTCx

Include GIAO Cx or CSGT Cx in .wfn or .wfx file.

## Pickett File Output

Write g tensors and other tensors for hyperfine spectra in Pickett's program format.

### Tensors Computed

- Nuclear electric quadrupole constants: all jobs
- Rotational constants: `Freq=(VibRot[,Anharmonic])`
- Quartic centrifugal distortion: `Freq=(VCD,Anharmonic)`
- Electronic spin rotation: NMR
- Nuclear spin rotation: NMR
- Dipolar hyperfine terms: all jobs
- Fermi contact terms: all jobs

### Related Options

| Option | Equivalent to |
|--------|---------------|
| SpinRotation | NMR Output=Pickett |
| RotationalConstants | Freq=VibRot Output=Pickett |
| QuarticCentrifugal | Freq=(VibRot,Anharm) Output=Pickett |

For HF and DFT, combine options:
```
Output=(RotationalConstants,SpinRotation)
```
This includes all tensors computable with no more than second derivatives.

### ReadAtoms

Read a list of atoms for Pickett's program input (max 8 nuclei). Atoms specified in free format, blank-terminated.

## Matrix Element File Output

### MatrixElement

Generate a text data file for interfacing to other programs. `RawMatrixElement` generates a binary file.

### Matrix Element Options

| Option | Description |
|--------|-------------|
| I4Labels / I8Labels | Use Integer*4 or Integer*8 values |
| MO2ElectronIntegrals | Include two-electron integrals over MOs |
| DerivativeDensities | Include derivative densities from CPHF |
| GIAOInts | Include GIAO integral derivatives |
| AO2ElectronIntegrals | Perform conventional SCF for AO integrals |
| Derivatives | Include derivatives of overlap, Core Hamiltonian |
| AO2ElDerivatives | Store AO 2-electron integral derivatives |
| Files | Include contents of specified internal Gaussian files |

### Files Option Detail

```
Output=(Matrix,Files=(123,(456,offset=1,integer=27)))
```

Includes:
- Contents of internal file 123 (real values)
- 27 integers from internal file 456 starting after first word

## Gaussian Output File Structure

A standard Gaussian output file contains these key sections:

### Header Information
- Gaussian version and citation
- Input file echo
- Route section
- Title section

### Initial Setup
- Basis set information
- Molecular geometry
- Symmetry information
- Initial guess

### SCF Iterations
- Energy convergence
- Density convergence
- Final SCF energy

### Post-SCF Results (if applicable)
- MP2, CCSD, etc. correlation energies
- Excited state information

### Properties
- Population analysis
- Dipole moment
- Electrostatic potential

### Optimization (if applicable)
- Geometry steps
- Energy at each step
- Forces and displacements
- Optimized geometry

### Frequency (if applicable)
- Vibrational frequencies
- Zero-point energy
- Thermal corrections
- Thermochemistry

### Summary
- Final energy
- Wall clock time
- Job completion status

## Key Output Patterns for Parsing

### Energy Extraction

```
SCF Done:  E(RB3LYP) =  -76.4089614     A.U. after    5 cycles
```

For MP2:
```
E2 =    -0.20456789D+00  EUMP2 =    -7.661345678901D+01
```

### Geometry (Optimized)

```
                         Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
```

### Frequencies

```
 Frequencies --   1234.5678  2345.6789  3456.7890
 Red. masses --     1.0078     1.0078     1.0078
 Frc consts  --     0.1234     0.2345     0.3456
 IR Inten    --    12.3456    23.4567    34.5678
```

### Thermochemistry

```
 Sum of electronic and zero-point Energies=          -76.38523456
 Sum of electronic and thermal Energies=             -76.38412345
 Sum of electronic and thermal Enthalpies=           -76.38345678
 Sum of electronic and thermal Free Energies=        -76.40123456
```

### Population Analysis

```
 Mulliken atomic charges:
            1
 1  C    -0.123456
 2  H     0.041152
```

### Dipole Moment

```
 Dipole moment (field-independent basis, Debye):
    X=     0.0000  Y=     0.0000  Z=     1.2345  Tot=     1.2345
```

## Error Diagnosis

Common error patterns in Gaussian output:

### SCF Convergence Failure

```
SCF Done:  E(RB3LYP) =  NaN     A.U. after  128 cycles
Convergence failure.
```

**Solution**: Try `SCF=QC`, `SCF=XQC`, or different initial guess.

### Optimization Not Converged

```
 Optimization stopped.
    -- Number of steps exceeded, NMax=100.
```

**Solution**: Increase `Opt=(MaxCycle=200)` or use `Opt=CalcFC`.

### Negative Frequency

```
 Frequencies --  -234.5678
```

Indicates not a true minimum. For TS optimization, should have exactly one imaginary frequency.

### Memory Error

```
Insufficient memory.
```

**Solution**: Increase `%Mem` or reduce `%NProc`.

### Disk Space Error

```
Write error in NtrExt1.
```

**Solution**: Increase `%RWF` space or clean scratch directory.

## Related Keywords

- `Punch`: Write punch file
- `Pop=MK(Antechamber)`: Generate charges for Antechamber
- `NMR=CSGT IOp(10/93=1)`: ACID data file
- `SCRF=COSMORS`: COSMO/RS data file
