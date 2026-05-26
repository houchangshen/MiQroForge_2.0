# Gaussian 16 Geometry Optimization

   Hartree-Fock, CIS, MP2, MP3, MP4(SDQ), CID, CISD, CCD, CCSD, QCISD, BD,
   CASSCF, and all DFT and semi-empirical methods, the default algorithm
   for both minimizations (optimizations to a local minimum) and
   optimizations to transition states and higher-order saddle points is
   the Berny algorithm using GEDIIS [Li06] in redundant internal
   coordinates [Pulay79, Fogarasi92, Pulay92, Baker93, Peng93, Peng96]
   (corresponding to the Redundant option). An brief overview of the Berny
   algorithm is provided in the final subsection of this discussion. The
   default algorithm for all methods lacking analytic gradients is the
   eigenvalue-following algorithm (Opt=EF).
   Gaussian includes the STQN method for locating transition structures.
   This method, implemented by H. B. Schlegel and coworkers [Peng93,
   Peng96], uses a quadratic synchronous transit approach to get closer to
   the quadratic region of the transition state and then uses a
   quasi-Newton or eigenvector-following algorithm to complete the
   optimization. Like the default algorithm for minimizations, it performs
   optimizations by default in redundant internal coordinates. This method
   will converge efficiently when provided with an empirical estimate of
   the Hessian and suitable starting structures.
   This method is requested with the QST2 and QST3 options. QST2 requires
   two molecule specifications, for the reactants and products, as its
   input, while QST3 requires three molecule specifications: the
   reactants, the products, and an initial structure for the transition
   state, in that order. The order of the atoms must be identical within
   all molecule specifications. See the examples for sample input for and
   output from this method.
   Basic information as well as techniques and pitfalls related to
   geometry optimizations are discussed in detail in chapter 3 of
   Exploring Chemistry with Electronic Structure Methods [Foresman15]. For
   a review article on optimization and related subjects, see
   [Hratchian05a].
   Gaussian 16 supports generalized internal coordinates (GIC), a facility
   which allows arbitrary redundant internal coordinates to be defined and
   used for optimization constraints and other purposes [Marenich25].
   There are several GIC-related options to Opt, and the GIC Info
   subsection describes using GICs as well as their limitations in the
   present implementation.
The Berny Optimization Algorithm
   The Berny geometry optimization algorithm in Gaussian is based on an
   earlier program written by H. B. Schlegel which implemented his
   published algorithm [Schlegel82]. The program has been considerably
   enhanced since this earlier version using techniques either taken from
   other algorithms or never published, and consequently it is appropriate
   to summarize the current status of the Berny algorithm here.
   At each step of a Berny optimization the following actions are taken:
     * The Hessian is updated unless an analytic Hessian has been computed
       or it is the first step, in which case an estimate of the Hessian
       is made. Normally the update is done using an iterated BFGS for
       minima and an iterated Bofill for transition states in redundant
       internal coordinates, and using a modification of the original
       Schlegel update procedure for optimizations in internal
       coordinates. By default, this is derived from a valence force field
       [Schlegel84a], but upon request either a unit matrix or a diagonal
       Hessian can also be generated as estimates.
     * The trust radius (maximum allowed Newton-Raphson step) is updated
       if a minimum is sought, using the method of Fletcher [Fletcher80,
       Bofill94, Bofill95].
     * Any components of the gradient vector corresponding to frozen
       variables are set to zero or projected out, thereby eliminating
       their direct contribution to the next optimization step.
       If a minimum is sought, perform a linear search between the latest
       point and the best previous point (the previous point having lowest
       energy). If second derivatives are available at both points and a
       minimum is sought, a quintic polynomial fit is attempted first; if
       it does not have a minimum in the acceptable range (see below) or
       if second derivatives are not available, a constrained quartic fit
       is attempted. This fits a quartic polynomial to the energy and
       first derivative (along the connecting line) at the two points with
       the constraint that the second derivative of the polynomial just
       reach zero at its minimum, thereby ensuring that the polynomial
       itself has exactly one minimum. If this fit fails or if the
       resulting step is unacceptable, a simple cubic is fit is done.
       Any quintic or quartic step is considered acceptable if the latest
       point is the best so far but if the newest point is not the best,
       the linear search must return a point in between the most recent
       and the best step to be acceptable. Cubic steps are never accepted
       unless they are in between the two points or no larger than the
       previous step. Finally, if all fits fail and the most recent step
       is the best so far, no linear step is taken. If all fits fail and
       the most recent step is not the best, the linear step is taken to
       the midpoint of the line connecting the most recent and the best
       previous points.
     * If the latest point is the best so far or if a transition state is
       sought, a quadratic step is determined using the current (possibly
       approximate) second derivatives. If a linear search was done, the
       quadratic step is taken from the point extrapolated using the
       linear search and uses forces at that point estimated by
       interpolating between the forces at the two points used in the
       linear search. By default, this step uses the Rational Function
       Optimization (RFO) approach [Simons83, Banerjee85, Baker86,
       Baker87]. The RFO step behaves better than the Newton-Raphson
       method used in earlier versions of Gaussian when the curvature at
       the current point is not that desired. The old Newton-Raphson step
       is available as an option.
     * Any components of the step vector resulting from the quadratic step
       corresponding to frozen variables are set to zero or projected out.
     * If the quadratic step exceeds the trust radius and a minimum is
       sought, the step is reduced in length to the trust radius by
       searching for a minimum of the quadratic function on the sphere
       having the trust radius, as discussed by Jørgensen [Golab83]. If a
       transition state is sought or if NRScale was requested, the
       quadratic step is simply scaled down to the trust radius.
     * Finally, convergence is tested against criteria for the maximum
       force component, root-mean square force, maximum step component,
       and root-mean-square step. The step is the change between the most
       recent point and the next to be computed (the sum of the linear and
       quadratic steps).
   Selecting the Optimization Goal
   By default, optimizations search for a local minimum.
QST2
   Search for a transition structure using the STQN method. This option
   requires the reactant and product structures as input, specified in two
   consecutive groups of title and molecule specification sections. Note
   that the atoms must be specified in the same order in the two
   structures. The TS option should not be combined with QST2.
QST3
   Search for a transition structure using the STQN method. This option
   requires the reactant, product, and initial TS structures as input,
   specified in three consecutive groups of title and molecule
   specification sections. Note that the atoms must be specified in the
   same order within the three structures. The TS option should not be
   combined with QST3.
TS
   Requests optimization to a transition state rather than a local
   minimum, using the Berny algorithm.
Saddle=N
   Requests optimization to a saddle point of order N using the Berny
   algorithm.
Conical
   Search for a conical intersection or avoided crossing using the
   state-averaged CASSCF method. Avoided is a synonym for Conical. Note
   that CASSCF=SlaterDet is needed in order to locate a conical
   intersection between a singlet state and a triplet state.
   Options
Options to Modify the Initial Geometry
ModRedundant
   Except for any case when it is combined with the GIC option (see
   below), the ModRedundant option will add, delete, or modify redundant
   internal coordinate definitions (including scan and constraint
   information) before performing the calculation. This option requires a
   separate input section following the geometry specification; when used
   in conjunction with QST2 or QST3, a ModRedundant input section must
   follow each geometry specification. AddRedundant is synonymous with
   ModRedundant.
   Lines in a ModRedundant input section use the following syntax:
[Type] N1 [N2 [N3 [N4]]] [A | F]
[Type] N1 [N2 [N3 [N4]]] B
[Type] N1 [N2 [N3 [N4]]] K | R
[Type] N1 [N2 [N3 [N4]]] D
[Type] N1 [N2 [N3 [N4]]] H diag-elem
[Type] N1 [N2 [N3 [N4]]] S nsteps stepsize
   N1, N2, N3, and N4 are atom numbers or wildcards (discussed below).
   Atom numbering begins at 1, and any dummy atoms are not counted.
   The atom numbers are followed by a one-character code letter indicating
   the coordinate modification to be performed; the action code is
   sometimes followed by additional required parameters as indicated
   above. If no action code is included, the default action is to add the
   specified coordinate. These are the available action codes:
   A Activate the coordinate for optimization if it has been frozen.
   F Freeze the coordinate in the optimization.
   B Add the coordinate and build all related coordinates.
   K Remove the coordinate and kill all related coordinates containing
   this coordinate.
   R Remove the coordinate from the definition list (but not the related
   coordinates).
   D Calculate numerical second derivatives for the row and column of the
   initial Hessian for this coordinate.
   H Change the diagonal element for this coordinate in the initial
   Hessian to diag-elem.
   S Perform a relaxed potential energy surface scan. Increment the
   coordinate by stepsize a total of nsteps times, performing an
   optimization from each resulting starting geometry.
   An asterisk (*) in the place of an atom number indicates a wildcard.
   Here are some examples of wildcard use:
   * All atoms specified by Cartesian coordinates.
   * * All defined bonds.
   3 * All defined bonds with atom 3.
   * * * All defined valence angles.
   * 4 * All defined valence angles around atom 4.
   * * * * All defined dihedral angles.
   * 3 4 * All defined dihedral angles around the bond connecting atoms 3
   and 4.
   By default, the coordinate type is determined from the number of atoms
   specified: Cartesian coordinates for 1 atom, bond stretch for 2 atoms,
   valence angle for 3 atoms, and dihedral angle for 4 atoms. Optionally,
   type can be used to designate these and additional coordinate types:
   X Cartesian coordinates.
   B Bond length.
   A Valence angle.
   D Dihedral angle.
   L Linear bend specified by three atoms (if N4 is -1) or by four atoms,
   where the fourth atom is used to determine the 2 orthogonal directions
   of the linear bend.
   See the examples for illustrations of the use of ModRedundant.
ReadOptimize
   Read an input section modifying which atoms are to be optimized. The
   atom list is specified in a separate input section (terminated by a
   blank line). By default, the atom list contains all atoms in the
   molecule, unless any atoms are designated as frozen within the molecule
   specification, in which case the initial atom list excludes them. If
   the structure is being read in from the checkpoint file, then the list
   of atoms to be optimized matches that in the checkpoint file. ReadOpt
   and RdOpt are synonyms for this option. ReadFreeze and RdFreeze are
   deprecated synonyms.
   The input section uses the following format:
atoms=list [notatoms=list]
   where each list is a comma or space-separated list of atom numbers,
   atom number ranges and/or atom types. Keywords are applied in
   succession. Here are some examples:
   atoms=3-6,17 notatoms=5   Adds atoms 3,4,6,17 to atom list. Removes 5
   if present.
   atoms=3 C 18-30 notatoms=H   Adds all C & non-H among atoms 3, 18-30.
   atoms=C N notatoms=5   Adds all C and N atoms except atom 5.
   atoms=1-5 notatoms=H atoms=8-10   Adds atoms 8-10 and non-hydrogens
   among atoms 1-5,
   Bare integers without a keyword are interpreted as atom numbers:
1,3,5 7        Adds atoms 1, 3, 5 and 7.
   You can start from an empty atom list by placing noatoms as the first
   item in the input section. For example, the following input optimizes
   all non-hydrogen atoms within atoms 1-100 and freezes all other atoms
   in the molecule:
noatoms atoms=1-100 notatoms=H
   For ONIOM optimizations only, block and notblock can be similarly used
   to include/not include rigid blocks defined in ONIOM molecule
   specifications. If there are contradictions between atoms specified as
   atoms and within blocks—e.g., an atom is included within a block but
   excluded by atom type—Gaussian 16 generates an error.
   Atoms can also be specified by ONIOM layer via the [not]layer keywords,
   which accept these values: real for the real system, model for the
   model system in a 2-layer ONIOM, middle for the middle layer in a
   3-layer ONIOM, and small for the model layer of a 3-layer ONIOM. Atoms
   may be similarly included/excluded by residue with residue and
   notresidue, which accept lists of residue names. Both keyword pairs
   function as shorthand forms for atom lists.
   Separate sections are read for each geometry for transition state
   optimizations using QST2 or QST3. Be aware that providing contradictory
   input—e.g., different frozen atoms for the reactants and products—will
   produce unpredictable results.
NoFreeze
   Activates (unfreezes) all variables, in other words freeze nothing and
   optimize all atoms. This option is useful when reading in a structure
   from a checkpoint file that contains frozen atoms (i.e. with
   Geom=Check). This option should not be used with GICs; use UnFreezeAll
   in the GIC input section instead.
General Procedural Options
MaxCycles=N
   Sets the maximum number of optimization steps to N. The default is the
   maximum of 20 and twice the number of redundant internal coordinates in
   use (for the default procedure) or twice the number of variables to be
   optimized (for other procedures).
MaxStep=N
   Sets the maximum size for an optimization step (the initial trust
   radius) to 0.01N Bohr or radians. The default value for N is 30.
Restart
   Restarts a geometry optimization from the checkpoint file. In this
   case, the entire route section will consist of the Opt keyword and the
   same options to it as specified for the original job (along with
   Restart). No other input is needed (see the examples).
InitialHarmonic=N
   Add harmonic constraints to the initial structure with force constant
   N/1000000 Hartree/Bohr^2. IHarmonic is a synonym for this option.
ChkHarmonic=N
   Add harmonic constraints to the initial structure saved on the chk file
   with force constant N/1000000 Hartree/Bohr^2. CHarmonic is a synonym
   for this option.
ReadHarmonic=N
   Add harmonic constraints to a structure read in the input stream (in
   the input orientation), with force constant N/1000000 Hartree/Bohr^2.
   RHarmonic is a synonym for this option.
MaxMicroiterations=N
   Allow up to N microiterations. The default is based on NAtoms but is at
   least 5000. MaxMicro is a synonym for this option.
NGoUp=N
   Opt=NGoUp=N allows the energy to increase N times before the algorithm
   switches to doing only linear searches. The default is 1, meaning that
   only linear searches are performed after the second time in row that
   the energy increases. N=-1 forces only linear searches whenever the
   energy rises.
NGoDown=N
   When near a saddle point, mix at most N eigenvectors of the Hessian
   with negative eigenvalues to form a step away from the saddle point.
   The default is 3. N=-1 turns this feature off, and the algorithm takes
   only the regular RFO step. NoDownHill is equivalent to NGoDown=-1.
MaxEStep=N
   Take a step of length N/1000 (Bohr or radians) when moving away from a
   saddle point. The default is N=600 (0.6) for regular optimizations and
   N=100 (0.1) for ONIOM Opt=Quadmac calculations.
Options Related to Initial Force Constants
   Unless you specify otherwise, a Berny geometry optimization starts with
   an initial guess for the second derivative matrix—also known as the
   Hessian—which is determined using connectivity derived from atomic
   radii and a simple valence force field [Schlegel84a, Peng96]. The
   approximate matrix is improved at each point using the computed first
   derivatives. This scheme usually works fine, but for some cases the
   initial guess may be so poor that the optimization fails to start off
   properly or spends many early steps improving the Hessian without
   nearing the optimized structure. In addition, for optimizations to
   transition states, some knowledge of the curvature around the saddle
   point is essential, and the default approximate Hessian must always be
   improved.
   There are a variety of options which retrieve or compute improved force
   constants for a geometry optimization. They are listed following this
   preliminary discussion.
   There are two other approaches to providing the initial Hessian which
   are sometimes useful:
     * Input new guesses: The default approximate matrix can be used, but
       with new guesses read in for some or all of the diagonal elements
       of the Hessian. This is specified in the ModRedundant input or on
       the variable definition lines in the Z-matrix. For example:

\## 1 2 H 0.55

       The letter H indicates that a diagonal force constant is being
       specified for this coordinate and that its value is 0.55
       Hartree/au^2.
     * Compute some or all of the Hessian numerically: You can ask the
       optimization program to compute part of the second derivative
       matrix numerically. In this case each specified variable will be
       stepped in only one direction, not both up and down as would be
       required for an accurate determination of force constants. The
       resulting second-derivatives are not as good as those determined by
       a frequency calculation but are fine for starting an optimization.
       Of course, this requires that the program do an extra gradient
       calculation for each specified variable. This procedure is
       requested by a flag (D) on the variable definition lines:
1 2 D

\## 1 2 3 D

       This input tells the program to do three points before taking the
       first optimization step: the usual first point, a geometry with the
       bond between atoms 1 and 2 incremented slightly, and a geometry
       with the angle between atoms 1, 2 and 3 incremented slightly. The
       program will estimate all force constants (on and off diagonal) for
       bond(1,2) and angle(1,2,3) from the three points. This option is
       only available with the Berny and EF algorithms.
   The following options select methods for providing improved force
   constants:
ReadFC
   Extract force constants from a checkpoint file. These will typically be
   the final approximate force constants from an optimization at a lower
   level, or (much better) the force constants computed correctly by a
   lower-level frequency calculation (the latter are greatly preferable to
   the former).
CalcFC
   Specifies that the force constants be computed at the first point using
   the current method (available for the HF, CIS, MP2, CASSCF, DFT, and
   semi-empirical methods only).
RCFC
   Specifies that the computed force constants in Cartesian coordinates
   (as opposed to internal) from a frequency calculation are to be read
   from the checkpoint file. Normally it is preferable to pick up the
   force constants already converted to internal coordinates as described
   above (ReadFC). However, a frequency calculation occasionally reveals
   that a molecule needs to distort to lower symmetry. In this case, the
   computed force constants in terms of the old internal coordinates
   cannot be used, and instead Opt=RCFC is used to read the Cartesian
   force constants and transform them. Note that Cartesian force constants
   are only available on the checkpoint file after a frequency
   calculation. You cannot use this option after an optimization dies
   because of a wrong number of negative eigenvalues in the approximate
   second derivative matrix. In the latter case, you may want to start
   from the most recent geometry and compute some derivatives numerically
   (see below). ReadCartesianFC is a synonym for RCFC.
CalcHFFC
   Specifies that the analytic HF force constants are to be computed at
   the first point. CalcHFFC is used with MP2 optimizations, and it is
   equivalent to CalcFC for DFT methods, AM1, PM3, PM3MM, PM6 and PDDG.
CalcAll
   Specifies that the force constants are to be computed at every point
   using the current method (available for the HF,CIS, MP2, CASSCF, DFT,
   and semi-empirical methods only). Note that vibrational frequency
   analysis is automatically done at the converged structure and the
   results of the calculation are archived as a frequency job.
RecalcFC=N
   Do analytic second derivatives at step 1 and every N^th step thereafter
   during an optimization.
VCD
   Calculate VCD intensities at each point of a Hartree-Fock or DFT
   Opt=CalcAll optimization.
NoRaman
   Specifies that Raman intensities are not to be calculated at each point
   of a Hartree-Fock Opt=CalcAll job (since it includes a frequency
   analysis using the results of the final point of the optimization). The
   Raman intensities add 10-20% to the cost of each intermediate second
   derivative point. NoRaman is the default for methods other than
   Hartree-Fock.
StarOnly
   Specifies that the specified force constants are to be estimated
   numerically but that no optimization is to be done. Note that this has
   nothing to do with computation of vibrational frequencies.
NewEstmFC
   Estimate the force constants using a valence force field. This is the
   default.
EstmFC
   Estimate the force constants using the old diagonal guesses. Only
   available for the Berny algorithm.
FCCards
   Requests that read the energy (although value is not used), cartesian
   forces and force constants from the input stream, as written out by
   Punch=Derivatives. The format for this input is:
   Energy                  Format (D24.16)
   Cartesian forces        Lines of format (6F12.8)
   Force constants
   Lines of format (6F12.8)
   The force constants are in lower triangular form:
   ((F(J,I),J=1,I),I=1,3N[atoms]), where 3N[atoms] is the number of
   Cartesian coordinates.
Convergence-Related Options
   These options are available for the Berny algorithm only.
Tight
   This option tightens the cutoffs on forces and step size that are used
   to determine convergence. An optimization with Opt=Tight will take
   several more steps than with the default cutoffs. For molecular systems
   with very small force constants (low frequency vibrational modes), this
   may be necessary to ensure adequate convergence and reliability of
   frequencies computed in a subsequent job step. This option can only be
   used with Berny optimizations. For DFT calculations, Int=UltraFine
   should be specified as well.
VeryTight
   Extremely tight optimization convergence criteria. VTight is a synonym
   for VeryTight. For DFT calculations, Int=UltraFine should be specified
   as well.
EigenTest
   EigenTest requests and NoEigenTest suppresses testing the curvature in
   Berny optimizations. The test is on by default only for transition
   states in internal (Z-matrix) or Cartesian coordinates, for which it is
   recommended. Occasionally, transition state optimizations converge even
   if the test is not passed, but NoEigenTest is only recommended for
   those with large computing budgets.
Expert
   Relaxes various limits on maximum and minimum force constants and step
   sizes enforced by the Berny program. This option can lead to faster
   convergence but is quite dangerous. It is used by experts in cases
   where the forces and force constants are very different from typical
   molecules and Z-matrices, and sometimes in conjunction with Opt=CalcFC
   or Opt=CalcAll. NoExpert enforces the default limits and is the
   default.
Loose
   Sets the optimization convergence criteria to a maximum step size of
   0.01 au and an RMS force of 0.0017 au. These values are consistent with
   the Int(Grid=SG1) keyword, and may be appropriate for initial
   optimizations of large molecules using DFT methods which are intended
   to be followed by a full convergence optimization using the default
   (Fine) grid. It is not recommended for use by itself.
Algorithm-Related Options

## GEDIIS

   Use GEDIIS optimization algorithm. This is the default for
   minimizations when gradients are available.
RFO
   Requests the Rational Function Optimization [Simons83] step during
   Berny optimizations. It is the default for transition state
   optimizations (Opt=TS). This was also the default algorithm for
   minimizations using gradients in Gaussian 03.
EF
   Requests an eigenvalue-following algorithm [Simons83, Cerjan81,
   Banerjee85], which is useful only for methods without derivatives (for
   which it is the default). Available for both minima and transition
   states. and EigenvalueFollow are all synonyms for EF. When used with
   Opt=Z-Matrix, a maximum of 50 variables may be optimized.
ONIOM-Related Options
Micro
   Use microiterations in ONIOM(MO:MM) optimizations. This is the default,
   with selection of L120 or L103 for the microiterations depending on
   whether electronic embedding is on or off. NoMicro forbids
   microiterations during ONIOM(MO:MM) optimizations. Mic120 says to use
   microiterations in L120 for ONIOM(MO:MM), even for mechanical
   embedding. This is the default for electronic embedding. Mic103 says to
   perform microiterations in L103 for ONIOM(MO:MM). It is the default for
   mechanical embedding, and it cannot be used with electronic embedding.
QuadMacro
   Controls whether the coupled, quadratic macro step is used during
   ONIOM(MO:MM) geometry optimizations [Vreven06a]. NoQuadMacro is the
   default.
Coordinate System Selection Options
Redundant
   Build an automatic set of redundant internal coordinates such as bonds,
   angles, and dihedrals from the current Cartesian coordinates or
   Z-Matrix values, using the old algorithm available in Gaussian 16.
   Perform the optimization using the Berny algorithm in these redundant
   internal coordinates. This is the default for methods for which
   analytic gradients are available.
Z-matrix
   Perform the optimization with the Berny algorithm using internal
   coordinates [Schlegel82, Schlegel89, Schlegel95]. In this case, the
   keyword FOpt rather than Opt requests that the program verify that a
   full optimization is being done (i.e., that the variables including
   inactive variables are linearly independent and span the degrees of
   freedom allowed by the molecular symmetry). The POpt form requests a
   partial optimization in internal coordinates. It also suppresses the
   frequency analysis at the end of optimizations which include second
   derivatives at every point (via the CalcAll option). See Appendix C for
   details and examples of Z-matrix molecule specifications.
Cartesian
   Requests that the optimization be performed in Cartesian coordinates,
   using the Berny algorithm. Note that the initial structure may be input
   using any coordinate system. No partial optimization or freezing of
   variables can be done with purely Cartesian optimizations; the mixed
   optimization format with all atoms specified via Cartesian lines in the
   Z-matrix can be used along with Opt=Z-matrix if these features are
   needed. When a Z-matrix without any variables is used for the molecule
   specification, and Opt=Z-matrix is specified, then the optimization
   will actually be performed in Cartesian coordinates. Note that a
   variety of other coordinate systems, such as distance matrix
   coordinates, can be constructed using the ModRedundant option.
Generalized Internal Coordinate (GIC) Options
GIC
   Build an automatic set of redundant internal coordinates using the new
   GIC algorithm. Perform the optimization using the Berny algorithm in
   the GIC-type internal coordinates. Note that the coordinates generated
   with this option can be the same bonds, angles, and dihedrals generated
   by the default algorithm. However, these coordinates are internally
   stored and manipulated as the generalized ones (e.g., relevant
   analytical derivatives with respect to Cartesian coordinates
   displacements can be calculated automatically via an auto
   differentiation engine). The GICs are more flexible and, in principle,
   can be any combination of standard mathematical functions. Note that
   Geom=Checkpoint Opt=GIC option is equivalent to Geom=(Checkpoint,GIC).
AddGIC
   Add, delete, or modify GIC-type internal coordinate definitions
   (including scan and constraint information) before performing the
   calculation using the new GIC algorithm. This option requires a
   separate input section following the geometry specification. When used
   in conjunction with QST2 or QST3, a GIC input section must follow each
   geometry specification. The syntax of the GIC input section is
   described in GIC Info. Note that Opt=(ModRedundant,GIC) is equivalent
   to Opt=AddGIC. Note that Geom=Checkpoint Opt=ReadAllGIC is equivalent
   to Geom=(Checkpoint, ReadAllGIC).
GICOld
   Build an automatic set of redundant internal coordinates using the
   current default algorithm (as with the option Redundant) and then
   convert the coordinates into the GICs and treat them as such. Perform
   the optimization using the Berny algorithm in the GIC-type internal
   coordinates.
ReadAllGIC
   Do not build any redundant internal coordinates by default. Instead,
   read the input stream for user-provided GIC definitions and create the
   coordinates. Perform the optimization using the Berny algorithm in the
   GIC-type internal coordinates. This option requires a separate GIC
   input section following the geometry specification. When used in
   conjunction with QST2 or QST3, a GIC input section must follow each
   geometry specification. The syntax of the GIC input section is
   described in the GIC Info tab.
Rarely Used Options
Path=M
   In combination with either the QST2 or the QST3 option, requests the
   simultaneous optimization of a transition state and an M-point reaction
   path in redundant internal coordinates [Ayala97]. No coordinate may be
   frozen during this type of calculation.
   If QST2 is specified, the title and molecule specification sections for
   both reactant and product structures are required as input as usual.
   The remaining M-2 points on the path are then generated by linear
   interpolation between the reactant and product input structures. The
   highest energy structure becomes the initial guess for the transition
   structure. Each point is optimized to lie in the reaction path and the
   highest point is optimized toward the transition structure.
   If QST3 is specified, a third set of title and molecule specification
   sections must be included in the input as a guess for the transition
   state as usual. The remaining M-3 points on the path are generated by
   two successive linear interpolations, first between the reactant and
   transition structure and then between the transition structure and
   product. By default, the central point is optimized to the transition
   structure, regardless of the ordering of the energies. In this case, M
   must be an odd number so that the points on the path may be distributed
   evenly between the two sides of the transition structure.
   In the output for a simultaneous optimization calculation, the
   predicted geometry for the optimized transition structure is followed
   by a list of all M converged reaction path structures.
   The treatment of the input reactant and product structures is
   controlled by other options: OptReactant, OptProduct, BiMolecular.
   Note that the SCF wavefunction for structures in the reactant valley
   may be quite different from that of structures in the product valley.
   Guess=Always can be used to prevent the wavefunction of a reactant-like
   structure from being used as a guess for the wavefunction of a
   product-like structure.
OptReactant
   Specifies that the input structure for the reactant in a path
   optimization calculation (Opt=Path) should be optimized to a local
   minimum. This is the default. NoOptReactant retains the input structure
   as a point that is already on the reaction path (which generally means
   that it should have been previously optimized to a minimum).
   OptReactant may not be combined with BiMolecular.
BiMolecular
   Specifies that the reactants or products are bimolecular and that the
   input structure will be used as an anchor point in an Opt=Path
   optimization. This anchor point will not appear as one of the M points
   on the path. Instead, it will be used to control how far the reactant
   side spreads out from the transition state. By default, this option is
   off.
OptProduct
   Specifies that the input structure for the product in a path
   optimization calculation (Opt=Path) should be optimized to a local
   minimum. This is the default. NoOptProduct retains the input structure
   as a point that is already on the reaction path (which generally means
   that it should have been previously optimized to a minimum). OptProduct
   may not be combined with BiMolecular.
Linear
   Linear requests and NoLinear suppresses the linear search in Berny
   optimizations. The default is to use the linear search whenever
   possible.
TrustUpdate
   TrustUpdate requests and NoTrustUpdate suppresses dynamic update of the
   trust radius in Berny optimizations. The default is to update for
   minima.
Newton
   Use the Newton-Raphson step rather than the RFO step during Berny
   optimizations.
NRScale
   NRScale requests that if the step size in the Newton-Raphson step in
   Berny optimizations exceeds the maximum, then it is to be scaled back.
   NoNRScale causes a minimization on the surface of the sphere of maximum
   step size [Golab83]. Scaling is the default for transition state
   optimizations and minimizing on the sphere is the default for
   minimizations.
Steep
   Requests steepest descent instead of Newton-Raphson steps during Berny
   optimizations. This is only compatible with Berny local minimum
   optimizations. It may be useful when starting far from the minimum, but
   is unlikely to reach full convergence.
UpdateMethod=keyword
   Specifies the Hessian update method. Keyword is one of: Powell, BFGS,
   PDBFGS, ND2Corr, OD2Corr, D2CorrBFGS, Bofill, D2CMix and None.
HFError
   Assume that numerical errors in the energy and forces are those
   appropriate for HF and post-SCF calculations (1.0D-07 and 1.0D-07,
   respectively). This is the default for optimizations using those
   methods and also for semi-empirical methods.
FineGridError
   Assume that numerical errors in the energy and forces are those
   appropriate for DFT calculations using the default grid (1.0D-07 and
   1.0D-06, respectively). This is the default for optimizations using a
   DFT method and specifying Int=FineGrid.
SG1Error
   Assume that numerical errors in the energy and forces are those
   appropriate for DFT calculations using the SG-1 grid (1.0D-07 and
   1.0D-05, respectively). This is the default for optimizations using a
   DFT method and Int(Grid=SG1Grid).
   Availability
   Analytic gradients are available for the HF, all DFT methods, CIS, MP2,
   MP3, MP4(SDQ), CID, CISD, CCD, CCSD, QCISD, CASSCF, and all
   semi-empirical methods.
   The Tight, VeryTight, Expert, Eigentest and EstmFC options are
   available for the Berny algorithm only.
   Optimizations of large molecules which have many very low frequency
   vibrational modes with DFT will often proceed more reliably when a
   larger DFT integration grid is requested (Int=UltraFine).
   Related Keywords
   IRC, IRCMax, Scan, Force, Frequency, Geom
   Examples
   Output from Optimization Jobs. The string GradGradGrad… delimits the
   output from the Berny optimization procedures. On the first,
   initialization pass, the program prints a table giving the initial
   values of the variables to be optimized. For optimizations in redundant
   internal coordinates, all coordinates in use are displayed in the table
   (not merely those present in the molecule specification section):
 GradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGrad
 Berny optimization.    The opt. algorithm is identified by the header format &
this line.
 Initialization pass.
                   ----------------------------
                   !    Initial Parameters    !
                   ! (Angstroms and Degrees)  !
--------------------                          ----------------------
! Name  Definition              Value          Derivative Info.    !
--------------------------------------------------------------------
! R1    R(2,1)                  1.             estimate D2E/DX2   !
! R2    R(3,1)                  1.             estimate D2E/DX2   !
! A1    A(2,1,3)              104.5            estimate D2E/DX2   !
--------------------------------------------------------------------
   The manner in which the initial second derivative are provided is
   indicated under the heading Derivative Info. In this case the second
   derivatives will be estimated.
   Each subsequent step of the optimization is delimited by lines like
   these:
GradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGrad
Berny optimization.
Search for a local minimum.
Step number   4 out of a maximum of  20
   Once the optimization completes, the final structure is displayed:
Optimization completed.
   -- Stationary point found.
                    ----------------------------
                    !   Optimized Parameters   !
                    ! (Angstroms and Degrees)  !
--------------------                            --------------------
! Name  Definition              Value          Derivative Info.    !
--------------------------------------------------------------------

\## ! R1    R(2,1)                  0.9892         -DE/DX =    0.0002 !


\## ! R2    R(3,1)                  0.9892         -DE/DX =    0.0002 !


\## ! A1    A(2,1,3)              100.004          -DE/DX =    0.0001 !

--------------------------------------------------------------------
   The redundant internal coordinate definitions are given in the second
   column of the table. The numbers in parentheses refer to the atoms
   within the molecule specification. For example, the variable R1,
   defined as R(2,1), specifies the bond length between atoms 1 and 2. The
   energy for the optimized structure will be found in the output from the
   final optimization step, which precedes this table in the output file.
   Compound Jobs. Optimizations are commonly followed by frequency
   calculations at the optimized structure. To facilitate this procedure,
   the Opt keyword may be combined with Freq in the route section of an
   input file, and this combination will automatically generate a two-step
   job.
   It is also common to follow an optimization with a single point energy
   calculation at a higher level of theory. The following route section
   automatically performs an HF/6-31G(d,p) optimization followed by an
   MP4/6-31G(d,p) single point energy calculation :
\# MP4/6-31G(d,p)//HF/6-31G(d,p) Test
   Note that the Opt keyword is not required in this case. However, it may
   be included if setting any of its options is desired.
   Modifying Redundant Internal Coordinates. The following input file
   illustrates the method for modifying redundant internal coordinates
   within an input file:
\   # HF/6-31G(d) Opt=ModRedun Test
   Opt job
   0,1

\##    C1  0.000   0.000   0.000


\##    C2  0.000   0.000   1.505


\##    O3  1.047   0.000  -0.651


\##    H4 -1.000  -0.006  -0.484


\##    H5 -0.735   0.755   1.898


\##    H6 -0.295  -1.024   1.866


\##    O7  1.242   0.364   2.065


\##    H8  1.938  -0.001   1.499

   3  8 Adds hydrogen bond (but not angles or dihedrals).
   2  1  3 Adds C-C-O angle.
   This structure is acetaldehyde with an OH substituted for one of the
   hydrogens in the methyl group; the first input line for ModRedundant
   creates a hydrogen bond between that hydrogen atom and the oxygen atom
   in the carbonyl group. Note that this adds only the bond between these
   two atoms The associated angles and dihedral angles could be added as
   well using the B action code:

\## 3  8  B

   Displaying the Value of a Desired Coordinate. The second input line for
   ModRedundant specifies the C-C=O bond angle, ensuring that its value
   will be displayed in the summary structure table for each optimization
   step.
   Using Wildcards in Redundant Internal Coordinates. A distance matrix
   coordinate system can be activated using the following input:
   * * B   Define all bonds between pairs of atoms
   * * * K Remove all other redundant internal coordinates
   The following input defines partial distance matrix coordinates to
   connect only the closest layers of atoms:
   * * B 1.1 Define all bonds between atoms within 1.1 Å
   * * * K   Remove all other redundant internal coordinates
   The following input sets up an optimization in redundant internal
   coordinates in which atoms N1 through Nn are frozen (such jobs may
   require the NoSymm keyword). Note that the lines containing the B
   action code will generate Cartesian coordinates for all of the
   coordinates involving the specified atom since only one atom number is
   specified:
   N1 B Generate Cartesian coordinates involving atom N1
   …
   Nn B Generate Cartesian coordinates involving atom Nn
   * F  Freeze all Cartesian coordinates
   The following input defines special “spherical” internal coordinates
   appropriate for molecules like C[60] by removing all dihedral angles
   from the redundant internal coordinates:
   * * * * R Remove all dihedral angles
   Additional examples are found in the section on relaxed PES scans
   below.
   Performing Partial Optimizations. The following job illustrates the
   method for freezing variables during an optimization:
\   # B3LYP/6-31G(d) Opt=ReadOpt
   Partial optimization of Fe2S2
   cluster with phenylthiolates.
   -2,1
   Fe 15.2630 -1.0091  7.0068

\##    S  14.8495  1.1490  7.0431

   Fe 17.0430  1.0091  7.0068

\##    S  17.4565 -1.1490  7.0431


\##    S  14.3762 -2.1581  8.7983


\##    C  12.5993 -2.1848  8.6878

   …

\##    C  14.8285 -3.8823  3.3884


\##    H  14.3660 -3.3149  2.7071

   noatoms atoms=1-4             ReadOpt input.
   The central cluster (the first four atoms) will be optimized while the
   phenylthiolates are frozen.
   Restarting an Optimization. A failed optimization may be restarted from
   its checkpoint file by simply repeating the route section of the
   original job, adding the Restart option to the Opt keyword. For
   example, this route section restarts a B3LYP/6-31G(d) Berny
   optimization to a second-order saddle point:
%Chk=saddle2
\# Opt=(TS,Restart,MaxCyc=50) Test
   The model chemistry and starting geometry are retrieved from the
   checkpoint file. Options specifying the optimization type and procedure
   are required in the route section for the restart job (e.g., TS in the
   preceding example). Some parameter-setting options can be omitted to
   use the same values are for the original job, or they can be modified
   for the restarted job, such as MaxCycle in the example. Note that you
   must include CalcFC to compute the Hessian at the first point of the
   restarted job. Second derivatives are computed only when this option is
   present in the route section of the restarted job, regardless of
   whether it was specified for the original job.
   Reading a Structure from the Checkpoint File. Redundant internal
   coordinate structures may be retrieved from the checkpoint file with
   Geom=Checkpoint as usual. The read-in structure may be altered by
   specifying Geom=ModRedundant as well; modifications have a form
   identical to the input for Opt=ModRedundant:
   [Type] N1 [N2 [N3 [N4]]] [Action [Params]] [[Min] Max]]
   Locating a Transition Structure with the STQN Method. The QST2 option
   initiates a search for a transition structure connecting specific
   reactants and products. The input for this option has this general
   structure (blank lines are omitted):
\   # HF/6-31G(d) Opt=QST2 # HF/6-31G(d) (Opt=QST2,ModRedun)
   First title section First title section
   Molecule specification for the reactants Molecule specification for the
   reactants
   Second title section ModRedundant input for the reactants
   Molecule specification for the products Second title section
     Molecule specification for the products
     ModRedundant input for the products (optional)
   Note that each molecule specification is preceded by its own title
   section (and separating blank line). If the ModRedundant option is
   specified, then each molecule specification is followed by any desired
   modifications to the redundant internal coordinates.
   Gaussian will automatically generate a starting structure for the
   transition structure midway between the reactant and product
   structures, and then perform an optimization to a first-order saddle
   point.
   The QST3 option allows you to specify a better initial structure for
   the transition state. It requires the two title and molecule
   specification sections for the reactants and products as for QST2 and
   also additional, third title and molecule specification sections for
   the initial transition state geometry (along with the usual blank line
   separators), as well as three corresponding modifications to the
   redundant internal coordinates if the ModRedundant option is specified.
   The program will then locate the transition structure connecting the
   reactants and products closest to the specified initial geometry.
   The optimized structure found by QST2 or QST3 appears in the output in
   a format similar to that for other types of geometry optimizations:
                    ----------------------------
                    !   Optimized Parameters   !
                    ! (Angstroms and Degrees)  !
---------------------                          ----------------------
! Name  Definition    Value    Reactant  Product  Derivative Info.  !
-------------------------------------------------------------------

\## ! R1    R(2,1)        1.0836    1.083     1.084    -DE/DX =    0.  !


\## ! R2    R(3,1)        1.4233    1.4047    1.4426   -DE/DX =   -0.   !


\## ! R3    R(4,1)        1.4154    1.4347    1.3952   -DE/DX =   -0.   !


\## ! R4    R(5,3)        1.3989    1.3989    1.3984   -DE/DX =    0.   !


\## ! R5    R(6,3)        1.1009    1.0985    1.0995   -DE/DX =    0.   !

! …                                                              !
-------------------------------------------------------------------
   In addition to listing the optimized values, the table includes those
   for the reactants and products.
   Performing a Relaxed Potential Energy Surface Scan. The
   Opt=ModRedundant option may also be used to perform a relaxed potential
   energy surface (PES) scan. Like the facility provided by Scan, a
   relaxed PES scan steps over a rectangular grid on the PES involving
   selected internal coordinates. It differs from Scan in that a
   constrained geometry optimization is performed at each point.
   Relaxed PES scans are available only for the Berny algorithm. If any
   scanning variable breaks symmetry during the calculation, then you must
   include NoSymm in the route section of the job, since it may fail with
   an error.
   Redundant internal coordinates specified with the Opt=ModRedundant
   option may be scanned using the S code letter: N1 N2 [N3 [N4]] S steps
   step-size. For example, this input adds a bond between atoms 2 and 3,
   specifying three scan steps of 0.05 Å each:

\## 2 3 S 3 0.05

   Wildcards in the ModRedundant input may also be useful in setting up
   relaxed PES scans. For example, the following input is appropriate for
   a potential energy surface scan involving the N1-N2-N3-N4 dihedral
   angle:
   N1 N2 N3 N4 S 20 2.0 Specify a relaxed PES scan of 20 steps in 2°
   increments

## Examples of Using GICs

   Basic GIC input. Here is an example of using the generalized internal
   coordinates defined by the user from scratch for the geometry
   optimization of the water molecule.
\# HF opt=readallgic
Title
 0 1

\## O    0.0000    0.0000    0.0000


\## H    0.0000    0.0000    1.3112


\## H    1.0354    0.0000   -0.6225


\## R(1,2)


\## R(1,3)


\## HOH=A(2,1,3)

   The atomic indexes 1, 2, and 3 refer to the oxygen atom, the first and
   the second hydrogen atom, respectively. The first and the second
   expression define the O-H bonds, and the third one defines the H-O-H
   valence angle (with the user-provided label “HOH”). An excerpt of the
   output with a table containing the initial values of the GICs is shown
   below.
                           ----------------------------
                           !    Initial Parameters    !
                           ! (Angstroms and Degrees)  !
 --------------------------                            -------------------------
-
 ! Name  Definition              Value          Derivative Info.
!
 -------------------------------------------------------------------------------
-
 ! R1    R(1,2)                  1.3112         estimate D2E/DX2
!
 ! R2    R(1,3)                  1.2081         estimate D2E/DX2
!
 ! HOH   A(2,1,3)              121.015          estimate D2E/DX2
!
 -------------------------------------------------------------------------------
-
   Note that the labels “R1” and “R2” above were assigned by default. The
   coordinates R1=R(1,2) and R2=R(1,3) are parsed as pure distances and
   given here in Angstroms, and the HOH=A(2,1,3) is a pure valence angle
   in degrees.
\# HF opt=readallgic
Title
 0 1

\## O    0.0000    0.0000    0.0000


\## H    0.0000    0.0000    1.3112


\## H    1.0354    0.0000   -0.6225

OHSym1=(R(1,2)+R(1,3))/sqrt(2)
OHSym2=(R(1,2)-R(1,3))/sqrt(2)

\## HOH=A(2,1,3)

   The first and the second expression in the example above define the
   symmetrized O-H bonds, and the third one is the H-O-H valence angle.
                           ----------------------------
                           !    Initial Parameters    !
                           ! (Angstroms and Degrees)  !
 --------------------------                            -------------------------
-
 ! Name   Definition             Value          Derivative Info.
!
 -------------------------------------------------------------------------------
-
 ! OHSym1 GIC-1                  3.3664         estimate D2E/DX2
!
 ! OHSym2 GIC-2                  0.1377         estimate D2E/DX2
!
 ! HOH    A(2,1,3)             121.015          estimate D2E/DX2
!
 -------------------------------------------------------------------------------
-
 NOTE: GIC-type coordinates are in arbitrary units.
   The coordinates OHSym1 and OHSym2 are parsed as generic GICs and
   therefore given here in arbitrary units. The units are actually Bohrs
   in this case because the 2^-1/2 factor is taken as dimensionless and
   the values of R(1,2) and R(1,3) are taken in Bohrs.
\# HF opt=readallgic
Title
 0 1
O

\## H  1  1.3


\## H  1  1.2  2  120.


\## R12=SQRT[{X(2)-X(1)}^2+{Y(2)-Y(1)}^2+{Z(2)-Z(1)}^2]


\## R13=SQRT[{X(3)-X(1)}^2+{Y(3)-Y(1)}^2+{Z(3)-Z(1)}^2]

A0(Inactive)=DotDiff(2,1,3,1)/{R12*R13}
A213=ArcCos(A0)
   The GIC input section above defines two bond distances and one valence
   angle expressed via Cartesian coordinates. The coordinate A0 is defined
   as the dot-product (DotDiff) of the vectors R→[12] and R→[13] divided
   by the product of their lengths, and it is selected as “inactive”
   (i.e., excluded from the geometry optimization). An excerpt of the
   output with a table containing the initial values of the GICs is shown
   below.
                           ----------------------------
                           !    Initial Parameters    !
                           ! (Angstroms and Degrees)  !
 --------------------------                            -------------------------
-
 ! Name  Definition              Value          Derivative Info.
!
 -------------------------------------------------------------------------------
-
 ! R12   GIC-1                   2.4566         estimate D2E/DX2
!
 ! R13   GIC-2                   2.2677         estimate D2E/DX2
!
 ! A213  GIC-3                   2.0944         estimate D2E/DX2
!
 -------------------------------------------------------------------------------
-
 NOTE: GIC-type coordinates are in arbitrary units.
   The values of R12, R13, and the dot-product are calculated using the
   Cartesian coordinates given in Bohrs. The GIC arbitrary units are Bohrs
   (for R12 and R13) and radians (for A213).
   GIC considerations
   The options that do not mention GIC and can be used with the Opt
   keyword should work as described—except for NoFreeze, which should not
   be combined with any GIC-related option. In the latter case, use the
   UnFreezeAll flag in the GIC input section.
   This section discusses specifying generalized internal coordinates
   (GICs) in Gaussian input files. GICs have many potential uses: defining
   additional coordinates whose values are reported during geometry
   optimizations, freezing various structural parameters during the
   optimization of a molecular system, specifying parameters over which to
   perform a scan, defining constraints for geometry optimizations based
   on structural parameters or complex relationships between them,
   requesting calculation of parts of the Hessian, and other purposes.
   The GIC input section is separated from the earlier input by a blank
   line. It has one or more lines containing coordinate definitions,
   expressions or standalone options. Here is a simple GIC input section
   for water illustrating some of the possible features:
R(1,2)                 Define a bond length coordinate for atoms 1 and 2
Bond2=R[1,3]           Define another bond length coordinate named Bond2
HOH(freeze)=A(2,1,3)   Define an optimization constraint: a bond angle coordinat
e named HOH (∠2-1-3)
   For an optimization, these coordinates will result in the bond angle
   remaining fixed at its initial value and the two bond distances being
   optimized.
   The basic form of a coordinate is the following:
label(options)=expression
   All of the components are optional. In the preceding examples, all
   components were present only in the third line. The first line
   contained only a coordinate expression, while the second line also
   contained a label without options. Note that options may also be placed
   following the expression:
HOH=A(2,1,3) Freeze
   Labels are user-assigned identifiers for the coordinate. They are not
   case sensitive. Labels many contain letters and number, but must begin
   with a letter. If no label is specified, a generic one will be assigned
   by the program (e.g., R1, R2, A1, etc.). A parenthesized,
   comma-separated list of options can be included following the label if
   desired. Note that square brackets or braces may be substituted for
   parentheses anywhere in a coordinate definition.
Structural Parameters
   Coordinates are defined by expressions. The simplest expressions simply
   identify a specific structural parameter within the molecule, using the
   following constructs. Note that an asterisk may be used as a wildcard
   for any atom number (see the examples).
   R(i,j)
   Define a bond coordinate between atoms i and j. B, Bond and Stretch are
   synonyms for R.
   A(i,j,k)
   Define a non-linear angle coordinate involving atoms i, j and k where
   the angle vertex is at atom j. Angle and Bend are synonyms for A.
   D(i,j,k,l)
   Define a dihedral angle between the plane containing atoms i, j and k
   and the plane containing atoms j, k and l. Dihedral and Torsion are
   synonyms for D.
   L(i,j,k,l,M)
   Define the linear bend coordinate involving atoms i, j and k where the
   angle vertex is at atom j. Linear and LinearBend are synonyms for L.
   A linear bend definition has two components, indicated by M values of
   -1 and -2 for the first and second components, respectively (no other
   values are permitted). A linear bend is specified by defining its two
   orthogonal directions. These can be indicated in two ways:
     * For a nonlinear molecule with more than 3 atoms, a fourth atom
       which does not form a linear angle with i, j and k in any
       combination can be used. In this case, l can be set to its atom
       number. For example, the following may be used to specify a linear
       bend involving atoms 1, 2 and 3 using atom 6 to determine the two
       orthogonal directions:

\## L(1,2,3,6,-1)


\## L(1,2,3,6,-2)

       If l is set to -4, then the fourth atom will be determined
       automatically based on the molecular geometry.
     * The other method is to project the linear bend onto one of the
       coordinate system’s axial planes: the values of -1, -2 and -3 for l
       specify the YZ, XZ and XY planes (respectively). The value 0 may
       also be used to request that the appropriate plane be determined
       automatically:

\## L(1,2,3,0,-1)


\## L(1,2,3,0,-2)

   X(i)
   Define the x Cartesian coordinate for atom i. Cartesian(i,-1) and
   Cartesian(i,X) are synonyms, and Cartesian may be abbreviated as Cart.
   Y(i)
   Define the y Cartesian coordinate for atom i. Cartesian(i,-2) and
   Cartesian(i,Y) are synonyms, and Cartesian may be abbreviated as Cart.
   Z(i)
   Define the z Cartesian coordinate for atom i. Cartesian(i,-3) and
   Cartesian(i,Z) are synonyms, and Cartesian may be abbreviated as Cart.
   XCntr(atom-list)
   YCntr(atom-list)
   ZCntr(atom-list)
   Define x, y or z Cartesian coordinate for the geometric center
   (centroid) of a molecular fragment that contains specified atoms. The
   atom list is a comma-separated list of atom numbers and/or ranges. For
   example, XCntr(1,12-15,27) defines the x coordinate of the fragment
   containing atoms 1, 12, 13, 14, 15 and 27. If the atom list is omitted,
   it defaults to the entire molecule.
   DotDiff(i,j,k,l)
   Define the dot product (a·b) of the two Cartesian coordinate difference
   vectors a and b for atoms i, j, k and l determined as a = (X[i]–X[j],
   Y[i]–Y[j], Z[i]–Z[j]) and b = (X[k]–X[l], Y[k]–Y[l], Z[k]–Z[l]).
Compound Expressions
   Complex expressions may be constructed by combining multiple items
   using one or more mathematical operations. The argument(s) A and B can
   be the labels of a previously defined coordinate, a valid GIC
   expression or even constants (integer or floating-point). The operation
   names are not case sensitive. The following operations are available:
     * Square root: SQRT(A).
     * Power of e: EXP(A) for e^A.
     * Trigonometric functions: SIN(A), COS(A), TAN(A).
     * Inverse cosine: ARCCOS(A).
     * Addition: A+B
     * Subtraction: A–B
     * Multiplication: A*B
     * Division: A/B
     * Exponentiation: A**n for A^n (n is an integer). The form A^n is
       also accepted.
   Here are some simple examples which define symmetrized OH bonds in
   water:
R12(inactive)=B(1,2)
R13(inactive)=B(1,3)
RSym  = (R12 + R13)/SQRT(2)
RASym = [Bond(1,2) - Bond(1,3)]/SQRT(2)
   The first two coordinates are set as inactive since they are
   intermediates not intended to be used in the optimization. Line 3
   illustrates an expression using previously defined labels, while line 4
   shows the use of literal expressions with operators. Note that the
   argument to the square root function is the constant 2.
Options
   A comma separated list of options can follow the coordinate label,
   enclosed in parentheses. Alternatively, options may follow the
   expression, separated from it and from one another by spaces. All
   options are case insensitive.
   For the purposes of geometry optimizations, a coordinate can be
   designated as:
     * Active: The coordinate is part of the list of internal coordinates
       used in the geometry optimzation. In contrast, Inactive coordinates
       are not included in the set used for the geometry optimization. By
       default, active coordinates are unfrozen: allowed to change value
       (see the next bullet).
     * Frozen: A coordinate whose value is held constant during the course
       of a geometry optimization. The values of active, unfrozen
       coordinates change during a geometry optimization. The frozen or
       unfrozen status of inactive coordinates is irrelevant during an
       optimization.
   In the descriptions that follow, coordinates that “already exist”
   refers to previously-defined coordinates with the same label or the
   same value expression. Such coordinates may have been defined earlier
   in the input stream or retrieved from the checkpoint file from a
   previous job.
   Active
   If the specified coordinate does not already exist, build a new
   coordinate defined by the given expression, and flag it as active and
   unfrozen. If the coordinate was previously defined, then flag it as
   active and unfrozen (whatever its previous status). It is the default.
   Activate, Add and Build are synonyms for Active. May be abbreviated to
   A when specified following the expression.
   Frozen
   Build a coordinate defined by the expression if it does not exist, and
   flag the coordinate as active for geometry optimizations and freeze it
   at the current value.
   Freeze is a synonym for Frozen. May be abbreviated to F when specified
   following the expression.
   Inactive
   If the coordiante does not already exist, build a new coordinate
   defined by the expression and flag it inactive. If the coordinate with
   the given label or for the given expression has been already built and
   flagged as active (frozen or unfrozen), then remove it from the
   geometry optimization by flagging it as inactive. Remove is a synonym
   for Inactive. May be abbreviated to R when specified following the
   expression.
   Kill
   Remove the coordinate from the list of internal coordinates used in
   geometry optimization along with any dependent coordinates by flagging
   all of them as inactive. The dependent coordinates include any
   coordinate that depends on the same atoms as the given coordinate. For
   example, R(1,5) Kill will result in removing the coordinate R(1,5)—the
   internuclear distance between atoms 1 and 5—as well as the valence
   angles, dihedral angles and any other coordinate that depends on the
   Cartesian coordinates of atoms 1 and 5 in combination with other atoms
   in the molecule. RemoveAll is a synonym for Kill. May be abbreviated to
   K when specified following the expression.
   PrintOnly
   Include the initial value of the coordinate in the starting geometry in
   the Gaussian output file, and then flag it as inactive.
   Modify
   A label must be included in the coordinate specification for this
   option. It replaces the old coordinate with the specified label with
   the new expression, and flags the newly modified coordinate as active
   and unfrozen.
   Diff
   Calculate numerical second derivatives for the row and column of the
   initial Hessian corresponding to this coordinate. May be abbreviated to
   D when specified following the expression.
   FC=x
   Change the diagonal element for the given coordinate in the initial
   Hessian to x, a floating-point number in atomic units. ForceConstant is
   a synonym for FC.
   Value=x
   Set the initial value for the given internal coordinate to x, a
   floating point value. The units for the value are those of the Gaussian
   program, as defined by the Units keyword (Angstroms or degrees by
   default). The current Cartesian coordinates will be adjusted to match
   this value as closely as possible. This option should be used
   cautiously and sparingly. It is far easier and more reliable to set the
   initial molecular structure as desired in a graphical environment like
   GaussView.
   StepSize=x,NSteps=n
   These options are used to specify a relaxed potential energy surface
   scan in which the coordinate is incremented by x a total of n times,
   and a constrained optimization is perfromed from each resulting
   starting geometry. x should be a positive floating-point number in
   atomic units, N should be an integer >1. When these options follow the
   expression, the comma separating them should be replaced by a space.
   Min=min,Max=max
   This option is used in combination with Active, Freeze or Inactive. It
   adds, freezes or makes inactive the coordinate when its value satisfies
   the condition min≤value≤max. min and max are floating-point numbers in
   the units defined by the Units (Angstroms or degrees by default). If
   Min or Max is omitted, the condition becomes value≤max or min≥min
   respectively. When these options follow the expression, the comma
   should be replaced by a space.
   action OnlyIf condition
   action IfNot condition
   These options provide conditional coordinate operations. They can only
   be placed following the expression defining the current coordinate.
   Action is one of Active, Freeze or Inactive. The condition is a label
   or expression for another coordinate. The specified action will be
   performed for the current coordinate if the coordinate referred to in
   condition is active for OnlyIf or inactive for IfNot. Note that the
   conditional test applies only to the action specified preceding the
   option and not to other options that may be present in the coordinate
   specification.
Standalone Options
   The following options are independent of coordinate definitions and
   apply globally. They should be specified alone on their input line.
   FreezeAll
   Freeze all internal coordinate previously added as active.
   UnFreezeAll
   Unfreeze all internal coordinates previously added as active frozen.
   RemoveAll
   Remove/inactivate all internal coordinate previously added as active
   (frozen or unfrozen).
   Atom i action
   Apply the specified action to the Cartesian coordinates of atom i. If i
   is an asterisk, then the action applies to all atoms. Action is one of
   Active, Freeze, UnFreeze, Remove (make inactive), RemoveAll and
   XYZOnly. These options are as defined above; XYZOnly says to remove any
   internal coordinates that depend on atom i but to add/retain the
   coordinates of that atom. The default action is Active.

## Examples

   The following example manipulates some automatically-generated
   coordinates, defines some new ones, and then uses wildcards to remove
   coordinates related to specific atoms:
R(5,9) freeze                           Freeze bond distance R(5,9).
R(8,9)                                  Add a new active coordinate R(8,9) with
a default label.
Ang189 = A(1,8,9)                       Add a new active coordinate A(1,8,9) lab
eled Ang189.
R10(remove)                             Remove a coordinate labeled R10.
Dih6123(remove) = D(6,1,2,3)            If D(6,1,2,3) exists, then remove the co
ordinate.
Dis79(freeze) = R(7,9)                  Freeze the coordinate R(7,9): if it is n
ew, then label it Dis79; if it already exists, retain the old label.
G1 = (R16+R19)*0.529177                 Add a new coordinate labeled G1.
Ang189a(modify)=cos(g2)*57.29577951     Change the definition of coordinate Ang1
89a.
R(11,*) remove                          Remove distances between atom 11 and any
 other atom.
D(*,1,17,*) remove                      Remove any dihedral built around the 1-1
7 bond.
   Note that if a specified coordinate already exists, then an entry
   adding it will result in an error (e.g., lines 1-3 above).
   The following example first defines the centroids of two fragments.
   Then, it defines the interfragment distance as an optimization
   coordinate:
Define the center of Fragment 1, but don't include it in the optimization.
XC1(Inactive)=XCntr(1-10)
YC1(Inactive)=YCntr(1-10)
ZC1(Inactive)=ZCntr(1-10)
Define the center of Fragment 2, but don't include it in the optimization.
XC2(Inactive)=XCntr(11-21)
YC2(Inactive)=YCntr(11-21)
ZC2(Inactive)=ZCntr(11-21)
Define the distance F1-F2 and include it in the optimization. Its value will be
reported in Å:
F1F2=sqrt[(XC1-XC2)^2+(YC1-YC2)^2+(ZC1-ZC2)^2]*0.529177
   The following example requests a relaxed PES scan over the same
   coordinate:
F1F2(NSteps=10,StepSize=0.2)
   The following example removes an angle coordinate generated by default
   if ≥179.9°, substituting a linear bend:
A(1,2,3) Remove Min=179.9           Remove angle coordinate if too large.
L(1,2,3,0,-1) Add IfNot A(1,2,3)    Add linear bend only if the angle coordinate
 not active.
L(1,2,3,0,-2) Add IfNot A(1,2,3)
   The following example removes an angle coordinate if it is ≤ the
   specified value, setting the corresponding force constant is set to 0.2
   au. The latter applies whenever it is needed: as the initial force
   constant and the force constant to use should be variable be
   reactivated. The second line specifies the force constant for a bond
   coordinate:
A(1,2,3) Remove Min=3.139847 ForceConstant=0.2

\## R(1,2) FC=0.5

   The following example sets the force constants for various coordinates.
   It also inactivates bond angle coordinates ≥ 179.8°:

\## R(1,*) FC=0.8


\## D(*,4,5,*) FC=0.4


\## A(*,1,*) FC=0.5

A(*,*,*) R Min=179.8
Limitations of GICs in the Current Implementation
   In the current implementation, GICs can be successfully used for many
   purposes including optimization constraints and PES scans. However,
   there are potential problems with active composite coordinates
   including multiple dihedral angles. In general, coordinates comprised
   of combinations of bond distances and bond angles should behave well.
   Simple dihedral angles are also welll supported. Complex expressions
   involving multiple dihedral angles are acceptable for frozen
   coordinates and for PES scans. However, they should be avoided as
   active optimization coordinates.
   In a non-GIC optimization, or one using GICs with only regular
   dihedrals, then the program is careful about the periodicity of these
   coordinates. For example, in deciding whether a step in the geometry is
   too big and needs to be scaled back, it recognizes that a change in
   value from 1 degree to 359 degrees is really a change of -2 degrees
   rather than 358 degrees. Similarly, in numerically differentiating the
   forces in order to update the Hessian, displacements between geometries
   in internal coordinates are needed, and the periodicity is accounted
   for. A problem can arise when a GIC is a combination of parts for which
   such periodicity is important, typically, combinations of multiple
   dihedral angles. For example, consider these GICs:

\## D1 = D(1,2,3,4)


\## D2 = D(5,6,7,8)


\## V1 = D1 + 2*D2

   D1 and D2 are dihedral angles, but they are intermediates and are not
   used as variables in the optimization. Their periodicity is not
   currently recognized in the composite coordinate V1. Suppose they have
   values of 1 and 2 degrees at one geometry and 1 and 359 degress at the
   next. The change in the optimization variable V1 should be 0 + 2*(-3) =
   -6 degrees, but it is actually 0 + 2*(357) = 714 degrees, which looks
   like an enormous change. This will result in the optimization algorithm
   performing very poorly. V1 isn’t a simple periodic function; it is
   necessary to apply periodicity to its component parts as it is
   computed, which is not done in the current GIC implementation.
GIC Units in Gaussian Output
   The values of the GICs defined as pure distances and angles (including
   valence angles, linear bends and dihedral angles/torsions) are computed
   from the Cartesian coordinates in atomic units (Bohrs) and stored
   internally in Bohrs and radians. However, for the user’s convenience,
   they are expressed as usual in Angstroms and degrees in the Gaussian
   output. In the case of a generic GIC (i.e., when the GIC is not a pure
   Cartesian coordinate, bond distance or angle), the GIC value is
   computed as a function of Cartesian coordinates and bond distances in
   Bohrs and angles in radians, combined with optional constants in
   user-defined units. Such generic GIC values (labeled as GIC) are
   computed, stored and output in these same units: i.e., if the GIC is a
   combination of bonds or a combination of valence angles, then the
   arbitrary units become Bohrs for the bonds and radians for the angles.
Use of ModRedundant Format Input
   Modifications to the GICs can be read in using the ModRedundant format
   from the current internal coordinate algorithm. However, the old format
   is only available with the GICs that include only pure bond distances,
   bond angles or torsion angles. In addition, the old format and the new
   GIC format described above cannot be mixed together in the same input
   section.
   Last updated on: 23 April 2020. [G16 Rev. C.01]
   See General Internal Coordinates for more information on GICs.
     * Description
     * Selecting the Optimization Goal
     * Options
     * Availability
     * Related Keywords
     * Examples
     * GIC considerations
   This keyword requests that a geometry optimization be performed. The
   geometry will be adjusted until a stationary point on the potential
   surface is found. Analytic gradients will be used if available. For the
   Hartree-Fock, CIS, MP2, MP3, MP4(SDQ), CID, CISD, CCD, CCSD, QCISD, BD,
   CASSCF, and all DFT and semi-empirical methods, the default algorithm
   for both minimizations (optimizations to a local minimum) and
   optimizations to transition states and higher-order saddle points is
   the Berny algorithm using GEDIIS [Li06] in redundant internal
   coordinates [Pulay79, Fogarasi92, Pulay92, Baker93, Peng93, Peng96]
   (corresponding to the Redundant option). An brief overview of the Berny
   algorithm is provided in the final subsection of this discussion. The
   default algorithm for all methods lacking analytic gradients is the
   eigenvalue-following algorithm (Opt=EF).
   Gaussian includes the STQN method for locating transition structures.
   This method, implemented by H. B. Schlegel and coworkers [Peng93,
   Peng96], uses a quadratic synchronous transit approach to get closer to
   the quadratic region of the transition state and then uses a
   quasi-Newton or eigenvector-following algorithm to complete the
   optimization. Like the default algorithm for minimizations, it performs
   optimizations by default in redundant internal coordinates. This method
   will converge efficiently when provided with an empirical estimate of
   the Hessian and suitable starting structures.
   This method is requested with the QST2 and QST3 options. QST2 requires
   two molecule specifications, for the reactants and products, as its
   input, while QST3 requires three molecule specifications: the
   reactants, the products, and an initial structure for the transition
   state, in that order. The order of the atoms must be identical within
   all molecule specifications. See the examples for sample input for and
   output from this method.
   Basic information as well as techniques and pitfalls related to
   geometry optimizations are discussed in detail in chapter 3 of
   Exploring Chemistry with Electronic Structure Methods [Foresman15]. For
   a review article on optimization and related subjects, see
   [Hratchian05a].
   Gaussian 16 supports generalized internal coordinates (GIC), a facility
   which allows arbitrary redundant internal coordinates to be defined and
   used for optimization constraints and other purposes [Marenich25].
   There are several GIC-related options to Opt, and the GIC Info
   subsection describes using GICs as well as their limitations in the
   present implementation.
The Berny Optimization Algorithm
   The Berny geometry optimization algorithm in Gaussian is based on an
   earlier program written by H. B. Schlegel which implemented his
   published algorithm [Schlegel82]. The program has been considerably
   enhanced since this earlier version using techniques either taken from
   other algorithms or never published, and consequently it is appropriate
   to summarize the current status of the Berny algorithm here.
   At each step of a Berny optimization the following actions are taken:
     * The Hessian is updated unless an analytic Hessian has been computed
       or it is the first step, in which case an estimate of the Hessian
       is made. Normally the update is done using an iterated BFGS for
       minima and an iterated Bofill for transition states in redundant
       internal coordinates, and using a modification of the original
       Schlegel update procedure for optimizations in internal
       coordinates. By default, this is derived from a valence force field
       [Schlegel84a], but upon request either a unit matrix or a diagonal
       Hessian can also be generated as estimates.
     * The trust radius (maximum allowed Newton-Raphson step) is updated
       if a minimum is sought, using the method of Fletcher [Fletcher80,
       Bofill94, Bofill95].
     * Any components of the gradient vector corresponding to frozen
       variables are set to zero or projected out, thereby eliminating
       their direct contribution to the next optimization step. If a
       minimum is sought, perform a linear search between the latest point
       and the best previous point (the previous point having lowest
       energy). If second derivatives are available at both points and a
       minimum is sought, a quintic polynomial fit is attempted first; if
       it does not have a minimum in the acceptable range (see below) or
       if second derivatives are not available, a constrained quartic fit
       is attempted. This fits a quartic polynomial to the energy and
       first derivative (along the connecting line) at the two points with
       the constraint that the second derivative of the polynomial just
       reach zero at its minimum, thereby ensuring that the polynomial
       itself has exactly one minimum. If this fit fails or if the
       resulting step is unacceptable, a simple cubic is fit is done. Any
       quintic or quartic step is considered acceptable if the latest
       point is the best so far but if the newest point is not the best,
       the linear search must return a point in between the most recent
       and the best step to be acceptable. Cubic steps are never accepted
       unless they are in between the two points or no larger than the
       previous step. Finally, if all fits fail and the most recent step
       is the best so far, no linear step is taken. If all fits fail and
       the most recent step is not the best, the linear step is taken to
       the midpoint of the line connecting the most recent and the best
       previous points.
     * If the latest point is the best so far or if a transition state is
       sought, a quadratic step is determined using the current (possibly
       approximate) second derivatives. If a linear search was done, the
       quadratic step is taken from the point extrapolated using the
       linear search and uses forces at that point estimated by
       interpolating between the forces at the two points used in the
       linear search. By default, this step uses the Rational Function
       Optimization (RFO) approach [Simons83, Banerjee85, Baker86,
       Baker87]. The RFO step behaves better than the Newton-Raphson
       method used in earlier versions of Gaussian when the curvature at
       the current point is not that desired. The old Newton-Raphson step
       is available as an option.
     * Any components of the step vector resulting from the quadratic step
       corresponding to frozen variables are set to zero or projected out.
     * If the quadratic step exceeds the trust radius and a minimum is
       sought, the step is reduced in length to the trust radius by
       searching for a minimum of the quadratic function on the sphere
       having the trust radius, as discussed by Jørgensen [Golab83]. If a
       transition state is sought or if NRScale was requested, the
       quadratic step is simply scaled down to the trust radius.
     * Finally, convergence is tested against criteria for the maximum
       force component, root-mean square force, maximum step component,
       and root-mean-square step. The step is the change between the most
       recent point and the next to be computed (the sum of the linear and
       quadratic steps).
   By default, optimizations search for a local minimum.
QST2
   Search for a transition structure using the STQN method. This option
   requires the reactant and product structures as input, specified in two
   consecutive groups of title and molecule specification sections. Note
   that the atoms must be specified in the same order in the two
   structures. The TS option should not be combined with QST2.
QST3
   Search for a transition structure using the STQN method. This option
   requires the reactant, product, and initial TS structures as input,
   specified in three consecutive groups of title and molecule
   specification sections. Note that the atoms must be specified in the
   same order within the three structures. The TS option should not be
   combined with QST3.
TS
   Requests optimization to a transition state rather than a local
   minimum, using the Berny algorithm.
Saddle=N
   Requests optimization to a saddle point of order N using the Berny
   algorithm.
Conical
   Search for a conical intersection or avoided crossing using the
   state-averaged CASSCF method. Avoided is a synonym for Conical. Note
   that CASSCF=SlaterDet is needed in order to locate a conical
   intersection between a singlet state and a triplet state.
Options to Modify the Initial Geometry
ModRedundant
   Except for any case when it is combined with the GIC option (see
   below), the ModRedundant option will add, delete, or modify redundant
   internal coordinate definitions (including scan and constraint
   information) before performing the calculation. This option requires a
   separate input section following the geometry specification; when used
   in conjunction with QST2 or QST3, a ModRedundant input section must
   follow each geometry specification. AddRedundant is synonymous with
   ModRedundant.
   [include-page id="/modred"]
   See the examples for illustrations of the use of ModRedundant.
ReadOptimize
   Read an input section modifying which atoms are to be optimized. The
   atom list is specified in a separate input section (terminated by a
   blank line). By default, the atom list contains all atoms in the
   molecule, unless any atoms are designated as frozen within the molecule
   specification, in which case the initial atom list excludes them. If
   the structure is being read in from the checkpoint file, then the list
   of atoms to be optimized matches that in the checkpoint file. ReadOpt
   and RdOpt are synonyms for this option. ReadFreeze and RdFreeze are
   deprecated synonyms.
   The input section uses the following format:
atoms=list [notatoms=list]
   where each list is a comma or space-separated list of atom numbers,
   atom number ranges and/or atom types. Keywords are applied in
   succession. Here are some examples:
   atoms=3-6,17 notatoms=5   Adds atoms 3,4,6,17 to atom list. Removes 5
   if present.
   atoms=3 C 18-30 notatoms=H   Adds all C & non-H among atoms 3, 18-30.
   atoms=C N notatoms=5   Adds all C and N atoms except atom 5.
   atoms=1-5 notatoms=H atoms=8-10   Adds atoms 8-10 and non-hydrogens
   among atoms 1-5,
   Bare integers without a keyword are interpreted as atom numbers:
1,3,5 7        Adds atoms 1, 3, 5 and 7.
   For ONIOM optimizations only, block and notblock can be similarly used
   to include/not include rigid blocks defined in ONIOM molecule
   specifications. If there are contradictions between atoms specified as
   atoms and within blocks—e.g., an atom is included within a block but
   excluded by atom type—Gaussian 16 generates an error.
   You can start from an empty atom list by placing noatoms as the first
   item in the input section. For example, the following input optimizes
   all non-hydrogen atoms within atoms 1-100 and freezes all other atoms
   in the molecule:
noatoms atoms=1-100 notatoms=H
   Atoms can also be specified by ONIOM layer via the [not]layer keywords,
   which accept these values: real for the real system, model for the
   model system in a 2-layer ONIOM, middle for the middle layer in a
   3-layer ONIOM, and small for the model layer of a 3-layer ONIOM. Atoms
   may be similarly included/excluded by residue with residue and
   notresidue, which accept lists of residue names. Both keyword pairs
   function as shorthand forms for atom lists.
   Separate sections are read for each geometry for transition state
   optimizations using QST2 or QST3. Be aware that providing contradictory
   input—e.g., different frozen atoms for the reactants and products—will
   produce unpredictable results.
NoFreeze
   Activates (unfreezes) all variables, in other words freeze nothing and
   optimize all atoms. This option is useful when reading in a structure
   from a checkpoint file that contains frozen atoms (i.e. with
   Geom=Check). This option should not be used with GICs; use UnFreezeAll
   in the GIC input section instead.
General Procedural Options
MaxCycles=N
   Sets the maximum number of optimization steps to N. The default is the
   maximum of 20 and twice the number of redundant internal coordinates in
   use (for the default procedure) or twice the number of variables to be
   optimized (for other procedures).
MaxStep=N
   Sets the maximum size for an optimization step (the initial trust
   radius) to 0.01N Bohr or radians. The default value for N is 30.
Restart
   Restarts a geometry optimization from the checkpoint file. In this
   case, the entire route section will consist of the Opt keyword and the
   same options to it as specified for the original job (along with
   Restart). No other input is needed (see the examples).
InitialHarmonic=N
   Add harmonic constraints to the initial structure with force constant
   N/1000000 Hartree/Bohr^2. IHarmonic is a synonym for this option.
ChkHarmonic=N
   Add harmonic constraints to the initial structure saved on the chk file
   with force constant N/1000000 Hartree/Bohr^2. CHarmonic is a synonym
   for this option.
ReadHarmonic=N
   Add harmonic constraints to a structure read in the input stream (in
   the input orientation), with force constant N/1000000 Hartree/Bohr^2.
   RHarmonic is a synonym for this option.
MaxMicroiterations=N
   Allow up to N microiterations. The default is based on NAtoms but is at
   least 5000. MaxMicro is a synonym for this option.
NGoUp=N
   Opt=NGoUp=N allows the energy to increase N times before the algorithm
   switches to doing only linear searches. The default is 1, meaning that
   only linear searches are performed after the second time in row that
   the energy increases. N=-1 forces only linear searches whenever the
   energy rises.
NGoDown=N
   When near a saddle point, mix at most N eigenvectors of the Hessian
   with negative eigenvalues to form a step away from the saddle point.
   The default is 3. N=-1 turns this feature off, and the algorithm takes
   only the regular RFO step. NoDownHill is equivalent to NGoDown=-1.
MaxEStep=N
   Take a step of length N/1000 (Bohr or radians) when moving away from a
   saddle point. The default is N=600 (0.6) for regular optimizations and
   N=100 (0.1) for ONIOM Opt=Quadmac calculations.
Options Related to Initial Force Constants
   Unless you specify otherwise, a Berny geometry optimization starts with
   an initial guess for the second derivative matrix—also known as the
   Hessian—which is determined using connectivity derived from atomic
   radii and a simple valence force field [Schlegel84a, Peng96]. The
   approximate matrix is improved at each point using the computed first
   derivatives. This scheme usually works fine, but for some cases the
   initial guess may be so poor that the optimization fails to start off
   properly or spends many early steps improving the Hessian without
   nearing the optimized structure. In addition, for optimizations to
   transition states, some knowledge of the curvature around the saddle
   point is essential, and the default approximate Hessian must always be
   improved.
   There are a variety of options which retrieve or compute improved force
   constants for a geometry optimization. They are listed following this
   preliminary discussion.
   There are two other approaches to providing the initial Hessian which
   are sometimes useful:
     * Input new guesses: The default approximate matrix can be used, but
       with new guesses read in for some or all of the diagonal elements
       of the Hessian. This is specified in the ModRedundant input or on
       the variable definition lines in the Z-matrix. For example:

\## 1 2 H 0.55

       The letter H indicates that a diagonal force constant is being
       specified for this coordinate and that its value is 0.55
       Hartree/au^2.
     * Compute some or all of the Hessian numerically: You can ask the
       optimization program to compute part of the second derivative
       matrix numerically. In this case each specified variable will be
       stepped in only one direction, not both up and down as would be
       required for an accurate determination of force constants. The
       resulting second-derivatives are not as good as those determined by
       a frequency calculation but are fine for starting an optimization.
       Of course, this requires that the program do an extra gradient
       calculation for each specified variable. This procedure is
       requested by a flag (D) on the variable definition lines:
1 2 D

\## 1 2 3 D

       This input tells the program to do three points before taking the
       first optimization step: the usual first point, a geometry with the
       bond between atoms 1 and 2 incremented slightly, and a geometry
       with the angle between atoms 1, 2 and 3 incremented slightly. The
       program will estimate all force constants (on and off diagonal) for
       bond(1,2) and angle(1,2,3) from the three points. This option is
       only available with the Berny and EF algorithms.
   The following options select methods for providing improved force
   constants:
ReadFC
   Extract force constants from a checkpoint file. These will typically be
   the final approximate force constants from an optimization at a lower
   level, or (much better) the force constants computed correctly by a
   lower-level frequency calculation (the latter are greatly preferable to
   the former).
CalcFC
   Specifies that the force constants be computed at the first point using
   the current method (available for the HF, CIS, MP2, CASSCF, DFT, and
   semi-empirical methods only).
RCFC
   Specifies that the computed force constants in Cartesian coordinates
   (as opposed to internal) from a frequency calculation are to be read
   from the checkpoint file. Normally it is preferable to pick up the
   force constants already converted to internal coordinates as described
   above (ReadFC). However, a frequency calculation occasionally reveals
   that a molecule needs to distort to lower symmetry. In this case, the
   computed force constants in terms of the old internal coordinates
   cannot be used, and instead Opt=RCFC is used to read the Cartesian
   force constants and transform them. Note that Cartesian force constants
   are only available on the checkpoint file after a frequency
   calculation. You cannot use this option after an optimization dies
   because of a wrong number of negative eigenvalues in the approximate
   second derivative matrix. In the latter case, you may want to start
   from the most recent geometry and compute some derivatives numerically
   (see below). ReadCartesianFC is a synonym for RCFC.
CalcHFFC
   Specifies that the analytic HF force constants are to be computed at
   the first point. CalcHFFC is used with MP2 optimizations, and it is
   equivalent to CalcFC for DFT methods, AM1, PM3, PM3MM, PM6 and PDDG.
CalcAll
   Specifies that the force constants are to be computed at every point
   using the current method (available for the HF,CIS, MP2, CASSCF, DFT,
   and semi-empirical methods only). Note that vibrational frequency
   analysis is automatically done at the converged structure and the
   results of the calculation are archived as a frequency job.
RecalcFC=N
   Do analytic second derivatives at step 1 and every N^th step thereafter
   during an optimization.
VCD
   Calculate VCD intensities at each point of a Hartree-Fock or DFT
   Opt=CalcAll optimization.
NoRaman
   Specifies that Raman intensities are not to be calculated at each point
   of a Hartree-Fock Opt=CalcAll job (since it includes a frequency
   analysis using the results of the final point of the optimization). The
   Raman intensities add 10-20% to the cost of each intermediate second
   derivative point. NoRaman is the default for methods other than
   Hartree-Fock.
StarOnly
   Specifies that the specified force constants are to be estimated
   numerically but that no optimization is to be done. Note that this has
   nothing to do with computation of vibrational frequencies.
NewEstmFC
   Estimate the force constants using a valence force field. This is the
   default.
EstmFC
   Estimate the force constants using the old diagonal guesses. Only
   available for the Berny algorithm.
FCCards
   Requests that read the energy (although value is not used), cartesian
   forces and force constants from the input stream, as written out by
   Punch=Derivatives. The format for this input is:
   Energy             Format (D24.16)
   Cartesian forces   Lines of format (6F12.8)
   Force constants    Lines of format (6F12.8)
   The force constants are in lower triangular form:
   ((F(J,I),J=1,I),I=1,3N[atoms]), where 3N[atoms] is the number of
   Cartesian coordinates.
Convergence-Related Options
   These options are available for the Berny algorithm only.
Tight
   This option tightens the cutoffs on forces and step size that are used
   to determine convergence. An optimization with Opt=Tight will take
   several more steps than with the default cutoffs. For molecular systems
   with very small force constants (low frequency vibrational modes), this
   may be necessary to ensure adequate convergence and reliability of
   frequencies computed in a subsequent job step. This option can only be
   used with Berny optimizations. For DFT calculations, Int=UltraFine
   should be specified as well.
VeryTight
   Extremely tight optimization convergence criteria. VTight is a synonym
   for VeryTight. For DFT calculations, Int=UltraFine should be specified
   as well.
EigenTest
   EigenTest requests and NoEigenTest suppresses testing the curvature in
   Berny optimizations. The test is on by default only for transition
   states in internal (Z-matrix) or Cartesian coordinates, for which it is
   recommended. Occasionally, transition state optimizations converge even
   if the test is not passed, but NoEigenTest is only recommended for
   those with large computing budgets.
Expert
   Relaxes various limits on maximum and minimum force constants and step
   sizes enforced by the Berny program. This option can lead to faster
   convergence but is quite dangerous. It is used by experts in cases
   where the forces and force constants are very different from typical
   molecules and Z-matrices, and sometimes in conjunction with Opt=CalcFC
   or Opt=CalcAll. NoExpert enforces the default limits and is the
   default.
Loose
   Sets the optimization convergence criteria to a maximum step size of
   0.01 au and an RMS force of 0.0017 au. These values are consistent with
   the Int(Grid=SG1) keyword, and may be appropriate for initial
   optimizations of large molecules using DFT methods which are intended
   to be followed by a full convergence optimization using the default
   (Fine) grid. It is not recommended for use by itself.
Algorithm-Related Options

## GEDIIS

   Use GEDIIS optimization algorithm. This is the default for
   minimizations when gradients are available.
RFO
   Requests the Rational Function Optimization [Simons83] step during
   Berny optimizations. It is the default for transition state
   optimizations (Opt=TS). This was also the default algorithm for
   minimizations using gradients in Gaussian 03.
EF
   Requests an eigenvalue-following algorithm [Simons83, Cerjan81,
   Banerjee85], which is useful only for methods without derivatives (for
   which it is the default). Available for both minima and transition
   states. and EigenvalueFollow are all synonyms for EF. When used with
   Opt=Z-Matrix, a maximum of 50 variables may be optimized.
ONIOM-Related Options
Micro
   Use microiterations in ONIOM(MO:MM) optimizations. This is the default,
   with selection of L120 or L103 for the microiterations depending on
   whether electronic embedding is on or off. NoMicro forbids
   microiterations during ONIOM(MO:MM) optimizations. Mic120 says to use
   microiterations in L120 for ONIOM(MO:MM), even for mechanical
   embedding. This is the default for electronic embedding. Mic103 says to
   perform microiterations in L103 for ONIOM(MO:MM). It is the default for
   mechanical embedding, and it cannot be used with electronic embedding.
QuadMacro
   Controls whether the coupled, quadratic macro step is used during
   ONIOM(MO:MM) geometry optimizations [Vreven06a]. NoQuadMacro is the
   default.
Coordinate System Selection Options
Redundant
   Build an automatic set of redundant internal coordinates such as bonds,
   angles, and dihedrals from the current Cartesian coordinates or
   Z-Matrix values, using the old algorithm available in Gaussian 16.
   Perform the optimization using the Berny algorithm in these redundant
   internal coordinates. This is the default for methods for which
   analytic gradients are available.
Z-matrix
   Perform the optimization with the Berny algorithm using internal
   coordinates [Schlegel82, Schlegel89, Schlegel95]. In this case, the
   keyword FOpt rather than Opt requests that the program verify that a
   full optimization is being done (i.e., that the variables including
   inactive variables are linearly independent and span the degrees of
   freedom allowed by the molecular symmetry). The POpt form requests a
   partial optimization in internal coordinates. It also suppresses the
   frequency analysis at the end of optimizations which include second
   derivatives at every point (via the CalcAll option). See Appendix C for
   details and examples of Z-matrix molecule specifications.
Cartesian
   Requests that the optimization be performed in Cartesian coordinates,
   using the Berny algorithm. Note that the initial structure may be input
   using any coordinate system. No partial optimization or freezing of
   variables can be done with purely Cartesian optimizations; the mixed
   optimization format with all atoms specified via Cartesian lines in the
   Z-matrix can be used along with Opt=Z-matrix if these features are
   needed. When a Z-matrix without any variables is used for the molecule
   specification, and Opt=Z-matrix is specified, then the optimization
   will actually be performed in Cartesian coordinates. Note that a
   variety of other coordinate systems, such as distance matrix
   coordinates, can be constructed using the ModRedundant option.
Generalized Internal Coordinate (GIC) Options
GIC
   Build an automatic set of redundant internal coordinates using the new
   GIC algorithm. Perform the optimization using the Berny algorithm in
   the GIC-type internal coordinates. Note that the coordinates generated
   with this option can be the same bonds, angles, and dihedrals generated
   by the default algorithm. However, these coordinates are internally
   stored and manipulated as the generalized ones (e.g., relevant
   analytical derivatives with respect to Cartesian coordinates
   displacements can be calculated automatically via an auto
   differentiation engine). The GICs are more flexible and, in principle,
   can be any combination of standard mathematical functions. Note that
   Geom=Checkpoint Opt=GIC option is equivalent to Geom=(Checkpoint,GIC).
AddGIC
   Add, delete, or modify GIC-type internal coordinate definitions
   (including scan and constraint information) before performing the
   calculation using the new GIC algorithm. This option requires a
   separate input section following the geometry specification. When used
   in conjunction with QST2 or QST3, a GIC input section must follow each
   geometry specification. The syntax of the GIC input section is
   described in GIC Info. Note that Opt=(ModRedundant,GIC) is equivalent
   to Opt=AddGIC. Note that Geom=Checkpoint Opt=ReadAllGIC is equivalent
   to Geom=(Checkpoint, ReadAllGIC).
GICOld
   Build an automatic set of redundant internal coordinates using the
   current default algorithm (as with the option Redundant) and then
   convert the coordinates into the GICs and treat them as such. Perform
   the optimization using the Berny algorithm in the GIC-type internal
   coordinates.
ReadAllGIC
   Do not build any redundant internal coordinates by default. Instead,
   read the input stream for user-provided GIC definitions and create the
   coordinates. Perform the optimization using the Berny algorithm in the
   GIC-type internal coordinates. This option requires a separate GIC
   input section following the geometry specification. When used in
   conjunction with QST2 or QST3, a GIC input section must follow each
   geometry specification. The syntax of the GIC input section is
   described in the GIC Considerations tab.
Rarely Used Options
Path=M
   In combination with either the QST2 or the QST3 option, requests the
   simultaneous optimization of a transition state and an M-point reaction
   path in redundant internal coordinates [Ayala97]. No coordinate may be
   frozen during this type of calculation.
   If QST2 is specified, the title and molecule specification sections for
   both reactant and product structures are required as input as usual.
   The remaining M-2 points on the path are then generated by linear
   interpolation between the reactant and product input structures. The
   highest energy structure becomes the initial guess for the transition
   structure. Each point is optimized to lie in the reaction path and the
   highest point is optimized toward the transition structure.
   If QST3 is specified, a third set of title and molecule specification
   sections must be included in the input as a guess for the transition
   state as usual. The remaining M-3 points on the path are generated by
   two successive linear interpolations, first between the reactant and
   transition structure and then between the transition structure and
   product. By default, the central point is optimized to the transition
   structure, regardless of the ordering of the energies. In this case, M
   must be an odd number so that the points on the path may be distributed
   evenly between the two sides of the transition structure.
   In the output for a simultaneous optimization calculation, the
   predicted geometry for the optimized transition structure is followed
   by a list of all M converged reaction path structures.
   The treatment of the input reactant and product structures is
   controlled by other options: OptReactant, OptProduct, BiMolecular.
   Note that the SCF wavefunction for structures in the reactant valley
   may be quite different from that of structures in the product valley.
   Guess=Always can be used to prevent the wavefunction of a reactant-like
   structure from being used as a guess for the wavefunction of a
   product-like structure.
OptReactant
   Specifies that the input structure for the reactant in a path
   optimization calculation (Opt=Path) should be optimized to a local
   minimum. This is the default. NoOptReactant retains the input structure
   as a point that is already on the reaction path (which generally means
   that it should have been previously optimized to a minimum).
   OptReactant may not be combined with BiMolecular.
BiMolecular
   Specifies that the reactants or products are bimolecular and that the
   input structure will be used as an anchor point in an Opt=Path
   optimization. This anchor point will not appear as one of the M points
   on the path. Instead, it will be used to control how far the reactant
   side spreads out from the transition state. By default, this option is
   off.
OptProduct
   Specifies that the input structure for the product in a path
   optimization calculation (Opt=Path) should be optimized to a local
   minimum. This is the default. NoOptProduct retains the input structure
   as a point that is already on the reaction path (which generally means
   that it should have been previously optimized to a minimum). OptProduct
   may not be combined with BiMolecular.
Linear
   Linear requests and NoLinear suppresses the linear search in Berny
   optimizations. The default is to use the linear search whenever
   possible.
TrustUpdate
   TrustUpdate requests and NoTrustUpdate suppresses dynamic update of the
   trust radius in Berny optimizations. The default is to update for
   minima.
Newton
   Use the Newton-Raphson step rather than the RFO step during Berny
   optimizations.
NRScale
   NRScale requests that if the step size in the Newton-Raphson step in
   Berny optimizations exceeds the maximum, then it is to be scaled back.
   NoNRScale causes a minimization on the surface of the sphere of maximum
   step size [Golab83]. Scaling is the default for transition state
   optimizations and minimizing on the sphere is the default for
   minimizations.
Steep
   Requests steepest descent instead of Newton-Raphson steps during Berny
   optimizations. This is only compatible with Berny local minimum
   optimizations. It may be useful when starting far from the minimum, but
   is unlikely to reach full convergence.
UpdateMethod=keyword
   Specifies the Hessian update method. Keyword is one of: Powell, BFGS,
   PDBFGS, ND2Corr, OD2Corr, D2CorrBFGS, Bofill, D2CMix and None.
HFError
   Assume that numerical errors in the energy and forces are those
   appropriate for HF and post-SCF calculations (1.0D-07 and 1.0D-07,
   respectively). This is the default for optimizations using those
   methods and also for semi-empirical methods.
FineGridError
   Assume that numerical errors in the energy and forces are those
   appropriate for DFT calculations using the default grid (1.0D-07 and
   1.0D-06, respectively). This is the default for optimizations using a
   DFT method and using the default grid (or specifying Int=FineGrid).
SG1Error
   Assume that numerical errors in the energy and forces are those
   appropriate for DFT calculations using the SG-1 grid (1.0D-07 and
   1.0D-05, respectively). This is the default for optimizations using a
   DFT method and Int(Grid=SG1Grid).
   Analytic gradients are available for the HF, all DFT methods, CIS, MP2,
   MP3, MP4(SDQ), CID, CISD, CCD, CCSD, QCISD, CASSCF, and all
   semi-empirical methods.
   The Tight, VeryTight, Expert, Eigentest and EstmFC options are
   available for the Berny algorithm only.
   Optimizations of large molecules which have many very low frequency
   vibrational modes with DFT will often proceed more reliably when a
   larger DFT integration grid is requested (Int=UltraFine).
   IRC, IRCMax, Scan, Force, Frequency, Geom
   Output from Optimization Jobs. The string GradGradGrad… delimits the
   output from the Berny optimization procedures. On the first,
   initialization pass, the program prints a table giving the initial
   values of the variables to be optimized. For optimizations in redundant
   internal coordinates, all coordinates in use are displayed in the table
   (not merely those present in the molecule specification section):
 GradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGrad
 Berny optimization.    The opt. algorithm is identified by the header format &
this line.
 Initialization pass.
                   ----------------------------
                   !    Initial Parameters    !
                   ! (Angstroms and Degrees)  !
--------------------                          ----------------------
! Name  Definition              Value          Derivative Info.    !
--------------------------------------------------------------------
! R1    R(2,1)                  1.             estimate D2E/DX2   !
! R2    R(3,1)                  1.             estimate D2E/DX2   !
! A1    A(2,1,3)              104.5            estimate D2E/DX2   !
--------------------------------------------------------------------
   The manner in which the initial second derivative are provided is
   indicated under the heading Derivative Info. In this case the second
   derivatives will be estimated.
   Each subsequent step of the optimization is delimited by lines like
   these:
GradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGradGrad
Berny optimization.
Search for a local minimum.
Step number   4 out of a maximum of  20
   Once the optimization completes, the final structure is displayed:
Optimization completed.
   -- Stationary point found.
                    ----------------------------
                    !   Optimized Parameters   !
                    ! (Angstroms and Degrees)  !
--------------------                            --------------------
! Name  Definition              Value          Derivative Info.    !
--------------------------------------------------------------------

\## ! R1    R(2,1)                  0.9892         -DE/DX =    0.0002 !


\## ! R2    R(3,1)                  0.9892         -DE/DX =    0.0002 !


\## ! A1    A(2,1,3)              100.004          -DE/DX =    0.0001 !

--------------------------------------------------------------------
   The redundant internal coordinate definitions are given in the second
   column of the table. The numbers in parentheses refer to the atoms
   within the molecule specification. For example, the variable R1,
   defined as R(2,1), specifies the bond length between atoms 1 and 2. The
   energy for the optimized structure will be found in the output from the
   final optimization step, which precedes this table in the output file.
   Compound Jobs. Optimizations are commonly followed by frequency
   calculations at the optimized structure. To facilitate this procedure,
   the Opt keyword may be combined with Freq in the route section of an
   input file, and this combination will automatically generate a two-step
   job.
   It is also common to follow an optimization with a single point energy
   calculation at a higher level of theory. The following route section
   automatically performs an HF/6-31G(d,p) optimization followed by an
   MP4/6-31G(d,p) single point energy calculation :
\# MP4/6-31G(d,p)//HF/6-31G(d,p) Test
   Note that the Opt keyword is not required in this case. However, it may
   be included if setting any of its options is desired.
   Modifying Redundant Internal Coordinates. The following input file
   illustrates the method for modifying redundant internal coordinates
   within an input file:
\   # HF/6-31G(d) Opt=ModRedun Test
   Opt job
   0,1

\##    C1  0.000   0.000   0.000


\##    C2  0.000   0.000   1.505


\##    O3  1.047   0.000  -0.651


\##    H4 -1.000  -0.006  -0.484


\##    H5 -0.735   0.755   1.898


\##    H6 -0.295  -1.024   1.866


\##    O7  1.242   0.364   2.065


\##    H8  1.938  -0.001   1.499

   3  8 Adds hydrogen bond (but not angles or dihedrals).
   2  1  3 Adds C-C-O angle.
   This structure is acetaldehyde with an OH substituted for one of the
   hydrogens in the methyl group; the first input line for ModRedundant
   creates a hydrogen bond between that hydrogen atom and the oxygen atom
   in the carbonyl group. Note that this adds only the bond between these
   two atoms The associated angles and dihedral angles could be added as
   well using the B action code:

\## 3  8  B

   Displaying the Value of a Desired Coordinate. The second input line for
   ModRedundant specifies the C-C=O bond angle, ensuring that its value
   will be displayed in the summary structure table for each optimization
   step.
   Using Wildcards in Redundant Internal Coordinates. A distance matrix
   coordinate system can be activated using the following input:
   * * B   Define all bonds between pairs of atoms
   * * * K Remove all other redundant internal coordinates
   The following input defines partial distance matrix coordinates to
   connect only the closest layers of atoms:
   * * B 1.1 Define all bonds between atoms within 1.1 Å
   * * * K   Remove all other redundant internal coordinates
   The following input sets up an optimization in redundant internal
   coordinates in which atoms N1 through Nn are frozen (such jobs may
   require the NoSymm keyword). Note that the lines containing the B
   action code will generate Cartesian coordinates for all of the
   coordinates involving the specified atom since only one atom number is
   specified:
   N1 B Generate Cartesian coordinates involving atom N1
   …
   Nn B Generate Cartesian coordinates involving atom Nn
   * F  Freeze all Cartesian coordinates
   The following input defines special “spherical” internal coordinates
   appropriate for molecules like C[60] by removing all dihedral angles
   from the redundant internal coordinates:
   * * * * R Remove all dihedral angles
   Additional examples are found in the section on relaxed PES scans
   below.
   Performing Partial Optimizations. The following job illustrates the
   method for freezing variables during an optimization:
\   # B3LYP/6-31G(d) Opt=ReadOpt
   Partial optimization of Fe2S2
   cluster with phenylthiolates.
   -2,1
   Fe 15.2630 -1.0091  7.0068

\##    S  14.8495  1.1490  7.0431

   Fe 17.0430  1.0091  7.0068

\##    S  17.4565 -1.1490  7.0431


\##    S  14.3762 -2.1581  8.7983


\##    C  12.5993 -2.1848  8.6878

   …

\##    C  14.8285 -3.8823  3.3884


\##    H  14.3660 -3.3149  2.7071

   noatoms atoms=1-4             ReadOpt input.
   The central cluster (the first four atoms) will be optimized while the
   phenylthiolates are frozen.
   Restarting an Optimization. A failed optimization may be restarted from
   its checkpoint file by simply repeating the route section of the
   original job, adding the Restart option to the Opt keyword. For
   example, this route section restarts a B3LYP/6-31G(d) Berny
   optimization to a second-order saddle point:
%Chk=saddle2
\# Opt=(TS,Restart,MaxCyc=50) Test
   The model chemistry and starting geometry are retrieved from the
   checkpoint file. Options specifying the optimization type and procedure
   are required in the route section for the restart job (e.g., TS in the
   preceding example). Some parameter-setting options can be omitted to
   use the same values are for the original job, or they can be modified
   for the restarted job, such as MaxCycle in the example. Note that you
   must include CalcFC to compute the Hessian at the first point of the
   restarted job. Second derivatives are computed only when this option is
   present in the route section of the restarted job, regardless of
   whether it was specified for the original job.
   Reading a Structure from the Checkpoint File. Redundant internal
   coordinate structures may be retrieved from the checkpoint file with
   Geom=Checkpoint as usual. The read-in structure may be altered by
   specifying Geom=ModRedundant as well; modifications have a form
   identical to the input for Opt=ModRedundant:
   [Type] N1 [N2 [N3 [N4]]] [Action [Params]] [[Min] Max]]
   Locating a Transition Structure with the STQN Method. The QST2 option
   initiates a search for a transition structure connecting specific
   reactants and products. The input for this option has this general
   structure (blank lines are omitted):
\   # HF/6-31G(d) Opt=QST2 # HF/6-31G(d) (Opt=QST2,ModRedun)
   First title section First title section
   Molecule specification for the reactants Molecule specification for the
   reactants
   Second title section ModRedundant input for the reactants
   Molecule specification for the products Second title section
     Molecule specification for the products
     ModRedundant input for the products (optional)
   Note that each molecule specification is preceded by its own title
   section (and separating blank line). If the ModRedundant option is
   specified, then each molecule specification is followed by any desired
   modifications to the redundant internal coordinates.
   Gaussian will automatically generate a starting structure for the
   transition structure midway between the reactant and product
   structures, and then perform an optimization to a first-order saddle
   point.
   The QST3 option allows you to specify a better initial structure for
   the transition state. It requires the two title and molecule
   specification sections for the reactants and products as for QST2 and
   also additional, third title and molecule specification sections for
   the initial transition state geometry (along with the usual blank line
   separators), as well as three corresponding modifications to the
   redundant internal coordinates if the ModRedundant option is specified.
   The program will then locate the transition structure connecting the
   reactants and products closest to the specified initial geometry.
   The optimized structure found by QST2 or QST3 appears in the output in
   a format similar to that for other types of geometry optimizations:
                    ----------------------------
                    !   Optimized Parameters   !
                    ! (Angstroms and Degrees)  !
---------------------                          ----------------------
! Name  Definition    Value    Reactant  Product  Derivative Info.  !
-------------------------------------------------------------------

\## ! R1    R(2,1)        1.0836    1.083     1.084    -DE/DX =    0.  !


\## ! R2    R(3,1)        1.4233    1.4047    1.4426   -DE/DX =   -0.   !


\## ! R3    R(4,1)        1.4154    1.4347    1.3952   -DE/DX =   -0.   !


\## ! R4    R(5,3)        1.3989    1.3989    1.3984   -DE/DX =    0.   !


\## ! R5    R(6,3)        1.1009    1.0985    1.0995   -DE/DX =    0.   !

! …                                                              !
-------------------------------------------------------------------
   In addition to listing the optimized values, the table includes those
   for the reactants and products.
   Performing a Relaxed Potential Energy Surface Scan. The
   Opt=ModRedundant option may also be used to perform a relaxed potential
   energy surface (PES) scan. Like the facility provided by Scan, a
   relaxed PES scan steps over a rectangular grid on the PES involving
   selected internal coordinates. It differs from Scan in that a
   constrained geometry optimization is performed at each point.
   Relaxed PES scans are available only for the Berny algorithm. If any
   scanning variable breaks symmetry during the calculation, then you must
   include NoSymm in the route section of the job, since it may fail with
   an error.
   Redundant internal coordinates specified with the Opt=ModRedundant
   option may be scanned using the S code letter: N1 N2 [N3 [N4]] S steps
   step-size. For example, this input adds a bond between atoms 2 and 3,
   specifying three scan steps of 0.05 Å each:

\## 2 3 S 3 0.05

   Wildcards in the ModRedundant input may also be useful in setting up
   relaxed PES scans. For example, the following input is appropriate for
   a potential energy surface scan involving the N1-N2-N3-N4 dihedral
   angle:
   N1 N2 N3 N4 S 20 2.0 Specify a relaxed PES scan of 20 steps in 2°
   increments

## Examples of Using GICs

   Basic GIC input. Here is an example of using the generalized internal
   coordinates defined by the user from scratch for the geometry
   optimization of the water molecule.
\# HF opt=readallgic
Title
 0 1

\## O    0.0000    0.0000    0.0000


\## H    0.0000    0.0000    1.3112


\## H    1.0354    0.0000   -0.6225


\## R(1,2)


\## R(1,3)


\## HOH=A(2,1,3)

   The atomic indexes 1, 2, and 3 refer to the oxygen atom, the first and
   the second hydrogen atom, respectively. The first and the second
   expression define the O-H bonds, and the third one defines the H-O-H
   valence angle (with the user-provided label “HOH”). An excerpt of the
   output with a table containing the initial values of the GICs is shown
   below.
                           ----------------------------
                           !    Initial Parameters    !
                           ! (Angstroms and Degrees)  !
 --------------------------                            -------------------------
-
 ! Name  Definition              Value          Derivative Info.
!
 -------------------------------------------------------------------------------
-
 ! R1    R(1,2)                  1.3112         estimate D2E/DX2
!
 ! R2    R(1,3)                  1.2081         estimate D2E/DX2
!
 ! HOH   A(2,1,3)              121.015          estimate D2E/DX2
!
 -------------------------------------------------------------------------------
-
   Note that the labels “R1” and “R2” above were assigned by default. The
   coordinates R1=R(1,2) and R2=R(1,3) are parsed as pure distances and
   given here in Angstroms, and the HOH=A(2,1,3) is a pure valence angle
   in degrees.
\# HF opt=readallgic
Title
 0 1

\## O    0.0000    0.0000    0.0000


\## H    0.0000    0.0000    1.3112


\## H    1.0354    0.0000   -0.6225

OHSym1=(R(1,2)+R(1,3))/sqrt(2)
OHSym2=(R(1,2)-R(1,3))/sqrt(2)

\## HOH=A(2,1,3)

   The first and the second expression in the example above define the
   symmetrized O-H bonds, and the third one is the H-O-H valence angle.
                           ----------------------------
                           !    Initial Parameters    !
                           ! (Angstroms and Degrees)  !
 --------------------------                            -------------------------
-
 ! Name   Definition             Value          Derivative Info.
!
 -------------------------------------------------------------------------------
-
 ! OHSym1 GIC-1                  3.3664         estimate D2E/DX2
!
 ! OHSym2 GIC-2                  0.1377         estimate D2E/DX2
!
 ! HOH    A(2,1,3)             121.015          estimate D2E/DX2
!
 -------------------------------------------------------------------------------
-
 NOTE: GIC-type coordinates are in arbitrary units.
   The coordinates OHSym1 and OHSym2 are parsed as generic GICs and
   therefore given here in arbitrary units. The units are actually Bohrs
   in this case because the 2^-1/2 factor is taken as dimensionless and
   the values of R(1,2) and R(1,3) are taken in Bohrs.
\# HF opt=readallgic
Title
 0 1
O

\## H  1  1.3


\## H  1  1.2  2  120.


\## R12=SQRT[{X(2)-X(1)}^2+{Y(2)-Y(1)}^2+{Z(2)-Z(1)}^2]


\## R13=SQRT[{X(3)-X(1)}^2+{Y(3)-Y(1)}^2+{Z(3)-Z(1)}^2]

A0(Inactive)=DotDiff(2,1,3,1)/{R12*R13}
A213=ArcCos(A0)
   The GIC input section above defines two bond distances and one valence
   angle expressed via Cartesian coordinates. The coordinate A0 is defined
   as the dot-product (DotDiff) of the vectors R→[12] and R→[13] divided
   by the product of their lengths, and it is selected as “inactive”
   (i.e., excluded from the geometry optimization). An excerpt of the
   output with a table containing the initial values of the GICs is shown
   below.
                           ----------------------------
                           !    Initial Parameters    !
                           ! (Angstroms and Degrees)  !
 --------------------------                            -------------------------
-
 ! Name  Definition              Value          Derivative Info.
!
 -------------------------------------------------------------------------------
-
 ! R12   GIC-1                   2.4566         estimate D2E/DX2
!
 ! R13   GIC-2                   2.2677         estimate D2E/DX2
!
 ! A213  GIC-3                   2.0944         estimate D2E/DX2
!
 -------------------------------------------------------------------------------
-
 NOTE: GIC-type coordinates are in arbitrary units.
   The values of R12, R13, and the dot-product are calculated using the
   Cartesian coordinates given in Bohrs. The GIC arbitrary units are Bohrs
   (for R12 and R13) and radians (for A213).
   The options that do not mention GIC and can be used with the Opt
   keyword should work as described—except for NoFreeze, which should not
   be combined with any GIC-related option. In the latter case, use the
   UnFreezeAll flag in the GIC input section.
   [include-page id="/gic"]
   See General Internal Coordinates for more information on GICs.
   Last updated on: 14 January 2026. [G16 Rev. C.01]