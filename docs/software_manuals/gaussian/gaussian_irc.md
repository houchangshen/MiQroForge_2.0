# Gaussian 16 IRC (Intrinsic Reaction Coordinate)

## Overview

The `IRC` keyword requests that a reaction path be followed by integrating the intrinsic reaction coordinate. The initial geometry is the transition state, and the path can be followed in one or both directions.

**Forward direction**: Defined as the direction the transition vector points when its largest component is positive.

## Requirements

IRC calculations require initial force constants, provided by one of:
- `RCFC` — Read force constants from checkpoint file (from preceding frequency calculation)
- `CalcFC` — Compute force constants at the first point
- `CalcAll` — Compute force constants at every point

One of RCFC or CalcFC must be specified.

## Basic Usage

```
\# HF/6-31G(d) IRC RCFC
```

Typical workflow:
1. Optimize transition state geometry
2. Run frequency calculation to verify TS (one imaginary frequency)
3. Run IRC from the TS checkpoint

## Path Specification Options

### Phase=(N1, N2 [,N3 [,N4]])

Defines the phase for the transition vector. Two atoms: bond stretch. Three atoms: angle bend. Four atoms: dihedral angle.

### Forward / Reverse

Follow the path only in the forward or reverse direction. Default: both directions.

### Downhill

Proceed downhill from the input geometry.

### MaxPoints=N

Number of points along the reaction path in each direction. Default: 10.

### StepSize=N

Step size in units of 0.01 Bohr. If N<0, units are 0.01 amu^(1/2)-Bohr. Default: 10.

## Algorithm Selection Options

### HPC (Default)

Hessian-based Predictor-Corrector integrator. Very accurate algorithm using Hessian-based local quadratic approximation as predictor and modified Bulrisch-Stoer integrator for corrector. Default for most calculations. Not practical for extremely large systems.

### EulerPC

First-order Euler integration for predictor with HPC corrector. Default for:
- IRC=GradientOnly calculations
- ONIOM(MO:MM) calculations
- Practical for large molecules

### LQA

Local quadratic approximation for the predictor step.

### DVV

Damped velocity verlet integrator.

### Euler

First-order Euler integration only. Not recommended for production.

### GradientOnly

Use algorithm without second derivatives. Must be specified explicitly for methods without analytic second derivatives. Can combine with EulerPC (default), HPC, Euler, or DVV.

## Coordinate System Options

### MassWeighted (MW) — Default

Follow the path in mass-weighted Cartesian coordinates.

### Cartesian

Follow the path in Cartesian coordinates without mass-weighting.

## Force Constant Options

### RCFC (ReadCartesianFC)

Read force constants from checkpoint file. This is the usual approach — run a frequency calculation first, then read its force constants.

```
\# HF/6-31G(d) IRC=RCFC
```

### CalcFC

Compute force constants at the first point.

### CalcAll

Compute force constants at every point. More expensive but can improve accuracy.

### ReCalc=N (Update)

Compute Hessian analytically every N predictor steps (or every |N| corrector steps if N<0). Requires a method with analytic second derivatives.

```
IRC=(CalcFC,RecalcFC=(Predictor=3,Corrector=2))
```

## Procedure Options

### Restart

Restart an incomplete IRC calculation, or add more points to a completed one.

### Report[=item]

Controls which geometric parameters are reported:
- `Report` (no parameter): All generated internal coordinates
- `Report=Read`: Read list of coordinates to report (1-4 atom numbers)
- `Report=Bonds`: Report bonds
- `Report=Angles`: Report angles
- `Report=Dihedrals`: Report dihedrals
- `Report=Cartesians`: Report all Cartesian coordinates

### ReCorrect[=when]

Controls correction step testing for HPC and EulerPC:
- `ReCorrect=Yes` (default for HPC/EulerPC): Repeat correction if threshold exceeded
- `ReCorrect=Never`: Suppress threshold test
- `ReCorrect=Always`: Always recompute corrector at least once
- `ReCorrect=Test`: Test quality but don't take additional step

### MaxCycle=N

Maximum number of steps. Default: 20.

### Tight / VeryTight (VTight)

Tighten cutoffs on forces and step size for convergence. For DFT, also specify `Int=UltraFine`.

## Gaussian 03 Compatibility

### GS2

Use the IRC algorithm from Gaussian 03 and earlier. Geometry is optimized at each point such that path segments are described by circular arcs.

Default: 6 points in each direction, steps of 0.1 amu^(1/2) Bohr.

```
\# HF/6-31G(d) IRC=GS2
```

## Availability

The default HPC algorithm is available for:
- HF and all DFT methods
- CIS, TD
- MP2, MP3, MP4(SDQ)
- CID, CISD, CCD, CCSD, QCISD, BD
- CASSCF
- All semi-empirical methods

## IRCMax

`IRCMax` computes the maximum energy along an IRC path. Related keyword for finding the highest point on a reaction path.

## Output Example

When the IRC completes, a summary table is printed:

```
Reaction path calculation complete.

Energies reported relative to the TS energy of    -91.564851
----------------------------------------------------------------------
   Summary of reaction path following
----------------------------------------------------------------------
                       Energy   Rx Coord
  1                   -0.00880  -0.54062
  2                   -0.00567  -0.43250
  3                   -0.00320  -0.32438
  4                   -0.00142  -0.21626
  5                   -0.00035  -0.10815
  6                    0.00000   0.00000      transition state
  7                   -0.00034   0.10815
  8                   -0.00131   0.21627
  9                   -0.00285   0.32439
 10                   -0.00487   0.43252
 11                   -0.00725   0.54065
----------------------------------------------------------------------
```

The transition state appears at the midpoint with energy and reaction coordinate values of 0.00000.

## Practical Workflow

### Complete IRC Procedure

```
\# Step 1: Optimize TS
%chk=ts.chk
\# B3LYP/6-31G(d) Opt=(CalcFC,TS,NoEigenTest)

TS optimization

0 1
[molecule]

--Link1--
\# Step 2: Frequency calculation (verify TS)
%chk=ts.chk
\# B3LYP/6-31G(d) Freq

Frequency check

0 1

--Link1--
\# Step 3: IRC calculation
%chk=ts.chk
\# B3LYP/6-31G(d) IRC=RCFC

IRC from TS

0 1
```

### Tips

1. Always verify the TS with a frequency calculation before IRC
2. Use `RCFC` to read force constants from the frequency calculation checkpoint
3. For DFT calculations, use `Int=UltraFine` grid
4. For large systems, use `EulerPC` algorithm
5. Use `MaxPoints=N` if more path points are needed
6. Use `Report=Read` to track specific geometric parameters along the path
