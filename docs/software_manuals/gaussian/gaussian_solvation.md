# Gaussian 16 SCRF (Solvation)

## Overview

The `SCRF` keyword requests a calculation in the presence of a solvent by placing the solute in a cavity within the solvent reaction field.

**Default method**: PCM using the Integral Equation Formalism variant (IEFPCM), which creates the solute cavity via overlapping spheres.

## SCRF Methods

### PCM (IEFPCM) — Default

The Polarizable Continuum Model using IEFPCM. Uses continuous surface charge formalism for smooth, robust reaction fields with continuous derivatives.

```
\# B3LYP/6-31G(d) SCRF=(PCM,Solvent=Water)
```

### CPCM

PCM using the polarizable conductor calculation model. Simpler than IEFPCM, often adequate.

```
\# B3LYP/6-31G(d) SCRF=(CPCM,Solvent=Water)
```

### SMD

Truhlar's SMD solvation model — **recommended for computing ΔG of solvation**. Performs IEFPCM calculation with special radii and non-electrostatic terms.

```
\# B3LYP/6-31G(d) SCRF=(SMD,Solvent=Water)
```

### Onsager (Dipole)

Places solute in a spherical cavity. Requires solute radius and dielectric constant.

```
\# B3LYP/6-31G(d) SCRF=(Dipole,Solvent=Water)
```

### IPCM (Isodensity)

Uses static isodensity surface for cavity.

### SCIPCM

Self-Consistent Isodensity PCM — cavity determined self-consistently from isodensity surface.

## Solvent Specification

### Named Solvents

```
SCRF=(Solvent=Water)
SCRF=(Solvent=Ethanol)
SCRF=(Solvent=Dichloromethane)
SCRF=(Solvent=DiMethylSulfoxide)
```

**Common solvents with dielectric constants (ε):**

| Solvent | ε |
|---------|---|
| Water | 78.3553 |
| DiMethylSulfoxide | 46.826 |
| Acetonitrile | 35.688 |
| Methanol | 32.613 |
| Ethanol | 24.852 |
| Acetone | 20.493 |
| 1-Propanol | 20.524 |
| 2-Propanol | 19.264 |
| 1-Butanol | 17.332 |
| Dichloromethane | 8.93 |
| TetraHydroFuran | 7.4257 |
| Chloroform | 4.7113 |
| DiethylEther | 4.2400 |
| Toluene | 2.3741 |
| Benzene | 2.2706 |
| CarbonTetraChloride | 2.2280 |
| CycloHexane | 2.0165 |
| n-Hexane | 1.8819 |

### Custom Solvent (Generic)

For SMD, define a new solvent via PCM input section with SCRF=Read:

```
\# B3LYP/6-31G(d) 5D SCRF(SMD,Solvent=Generic,Read)

SMD with custom solvent

0 1
O
H,1,0.94
H,1,0.94,2,104.5

Eps=24.852
EpsInf=1.852593
HbondAcidity=0.37
HbondBasicity=0.48
SurfaceTensionAtInterface=31.62
CarbonAromaticity=0.
ElectronegativeHalogenicity=0.

```

All 7 parameters are required for SMD custom solvents.

## PCM Non-Equilibrium Solvation

The solvent responds in two ways:
1. **Electronic polarization** (fast) — electron distribution adjusts
2. **Molecular reorientation** (slow) — solvent molecules rotate

- **Equilibrium**: Solvent fully responds (geometry optimization)
- **Non-equilibrium**: Only fast response (vertical excitation)

### NonEquilibrium Options

```
SCRF=(Solvent=Water,NonEquilibrium=Save)   # Save slow charges
SCRF=(Solvent=Water,NonEquilibrium=Read)   # Read slow charges
```

### Workflow for Non-Equilibrium Excitation

**Step 1**: Ground state optimization with `NonEquilibrium=Save`
```
\# B3LYP/6-31+G(d,p) Opt Freq SCRF=(Solvent=Ethanol,NonEquilibrium=Save)
```

**Step 2**: Vertical excitation reading saved data
```
\# B3LYP/6-31+G(d,p) TD=(NStates=6,Root=1) SCRF=(Solvent=Ethanol,NonEquilibrium=Read)
```

## External Iteration PCM

Self-consistent PCM calculation making the solvent reaction field self-consistent with the solute electrostatic potential. Important for excited states and post-SCF methods.

```
SCRF=(Solvent=Water,ExternalIteration)
```

- `1stVac`: Do first iteration in vacuum
- `1stPCM`: Do first iteration in solution
- `Restart`: Restart from checkpoint file

## Corrected Linear Response

State-specific correction for CIS/RPA/TD-DFT excited states:

```
SCRF=(Solvent=Water,CorrectedLR)
```

## PCM Cavity Options

### Atomic Radii

| Model | Description |
|-------|-------------|
| UFF | UFF force field radii (default). Explicit H spheres. |
| UA0 | United Atom Topological Model on UFF radii. H enclosed in heavy atom sphere. |
| UAHF | UA model with HF/6-31G(d) optimized radii |
| UAKS | UA model with PBE1PBE/6-31G(d) optimized radii |
| Pauling | Merz-Kollman atomic radii (explicit H) |
| Bondi | Bondi atomic radii (explicit H) |

### Surface Types

| Type | Description |
|------|-------------|
| VDW | Van der Waals surface (default) |
| SES | Solvent Excluding Surface (default in G03) |
| SAS | Solvent Accessible Surface |

### Cavity Parameters

- `Alpha=scale`: Electrostatic scaling factor for sphere radii (default: 1.1)
- `PDens=x`: Integration point density (default: 5.0 Å⁻²)
- `OFac=x`: Overlap index for SES added spheres (default: 0.89)
- `RMin=x`: Minimum radius for SES added spheres (default: 0.2 Å)

## PCM Input Section Keywords

Additional PCM parameters go in a separate input section with `SCRF=Read`:

```
\# B3LYP/6-31G(d) 5D SCRF(Solvent=Ethanol,Read)

Title

0 1
molecule specification

QConv=10
Alpha=1.1

```

### Key Parameters

- `Eps=x`: Static dielectric constant
- `EpsInf=x`: Dynamic dielectric constant
- `RSolv=x`: Solvent radius
- `NonEq=item`: Non-equilibrium solvation
- `Dis/Rep/Cav`: Include dispersion/repulsion/cavitation energies
- `CavityFieldEffects`: Include cavity-field interaction
- `QConv=type|N`: Convergence threshold (VeryTight=10⁻¹², Tight=10⁻⁹, Sleazy=10⁻⁶)
- `MxIter=N`: Max iterations for PCM charges (default: 400)
- `Iterative`: Use iterative method for PCM charges

### Save/Retrieve PCM Charges

- `SaveQ` (WriteQ): Write PCM charges to checkpoint
- `LoadQ` (ReadQ): Read PCM charges from checkpoint

\## ONIOM+PCM

```
SCRF=ONIOMPCM=A  # Self-consistent with integrated ONIOM density (energy only)
SCRF=ONIOMPCM=B  # Real-system low-level reaction field (energy only)
SCRF=ONIOMPCM=C  # Real-system low-level only, gas phase sub-calcs
SCRF=ONIOMPCM=X  # Separate reaction field per sub-calc (default)
```

## Availability

| Method | Energy (Ext.Iter.) | Energy | Opt | Freq | NMR |
|--------|-------------------|--------|-----|------|-----|
| MM | no | yes | yes | yes | no |
| AM1, PM3, PM6 | no | yes | yes | yes | no |
| HF, DFT | yes | yes | yes | yes | yes |
| MP2 | yes | yes* | yes* | yes* | yes* |
| MP3, CCSD, QCISD | yes | yes* | no | no | no |
| CASSCF | yes | yes | yes | numerical | no |
| CIS | yes | yes** | yes** | yes** | no |
| TD | yes | yes** | yes** | yes** | no |

*Computed via SCF MO polarization
**Using linear response approach

## Practical Recommendations

1. **For ΔG of solvation**: Use `SCRF=(SMD,Solvent=X)` — compute gas phase and solution energies, take difference
2. **For excited states**: Use linear response for quick estimates; use `ExternalIteration` or `CorrectedLR` for state-specific
3. **For geometry optimization**: Use default equilibrium solvation
4. **For vertical excitation**: Use non-equilibrium solvation (default for TD energies)
5. **For MP2 and higher**: Use `ExternalIteration` for proper correlation with solvent
