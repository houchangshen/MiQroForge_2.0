#!/usr/bin/env bash
# gaussian-casscf/profile/run.sh — CASSCF 单点能量
set -euo pipefail
# MF2 init

mf_banner "gaussian-casscf" "CASSCF single-point energy calculation"

echo "[gaussian-casscf] CASSCF(${active_electrons},${active_orbitals})/${basis_set} Ref=${reference} Pop=${population} Cores=${n_cores} Mem=${mem_gb}GB"
echo "[gaussian-casscf] OUTPUT_DIR=${OUTPUT_DIR} WORKDIR=${WORKDIR}"

XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-casscf][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"

echo "[gaussian-casscf] Starting Python input generation..."
python3 << PYEOF
from string import Template

basis_set = '${basis_set}'
population = '${population}'
active_electrons = '${active_electrons}'
active_orbitals = '${active_orbitals}'
reference = '${reference}'
charge = '${charge}'
multiplicity = '${multiplicity}'
n_cores = '${n_cores}'
mem_gb = '${mem_gb}'

print(f"[gaussian-casscf] Python got: basis_set={basis_set} mem_gb={mem_gb} n_cores={n_cores}")

mem_mb = str(int(float(mem_gb) * 1024))

# Reference keyword mapping
ref_kw_map = {
    'rhf': '',
    'uhf': 'UHF',
    'rohf': 'ROHF',
}
ref_kw = ref_kw_map.get(reference, '')

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.gjf.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    basis_set=basis_set,
    population=population,
    active_electrons=active_electrons,
    active_orbitals=active_orbitals,
    ref_kw=ref_kw,
    n_cores=n_cores,
    mem_mb=mem_mb,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
)

with open('${WORKDIR}/input.gjf', 'w') as f:
    f.write(result)

print(f"[gaussian-casscf] Generated input.gjf ({mem_mb}MB, {n_cores} cores)")
PYEOF
echo "[gaussian-casscf] Python input generation done (exit=$?)"

echo "[gaussian-casscf] Generated input.gjf:"
cat "${WORKDIR}/input.gjf"

cd "$WORKDIR"
echo "[gaussian-casscf] Running Gaussian..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-casscf][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-casscf] Gaussian finished. Parsing output..."

# CASSCF energy extraction
# Gaussian 16 CASSCF outputs "EIGENVALUE   -74.96418185" in CI matrix section,
# and "HF=-74.9641818" in the archive entry. Neither uses "E(CASSCF)=" format.
ENERGY=$(grep -E "EIGENVALUE\s+-?[0-9]" output.log | head -1 | awk '{print $NF}' || echo "")
if [[ -z "$ENERGY" ]]; then
    # Fallback: extract from archive entry "HF=<energy>"
    ENERGY=$(grep "HF=" output.log | tail -1 | sed 's/.*HF=//' | sed 's/\\.*//' | awk '{print $1}' || echo "")
fi
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-casscf][ERROR] Could not extract CASSCF energy from output!" >&2
    cat output.log >&2
    exit 1
fi
echo "[gaussian-casscf] Raw ENERGY=${ENERGY}"
# Convert Fortran D-format (e.g. -0.353D+02) to decimal
ENERGY=$(echo "$ENERGY" | sed 's/D/E/g' | python3 -c "
import sys
val = sys.stdin.read().strip()
try:
    print(f'{float(val):.10f}')
except ValueError:
    print(f'CONVERSION_ERROR:{val}', file=sys.stderr)
    sys.exit(1)
")

CONVERGED="true"
if grep -q "MCSCF converged" output.log; then
    CONVERGED="true"
elif grep -q "Convergence criterion not met" output.log; then
    CONVERGED="false"
    echo "[gaussian-casscf][WARN] SCF DID NOT CONVERGE!"
else
    CONVERGED="false"
    echo "[gaussian-casscf][WARN] Could not determine convergence status"
fi

echo "[gaussian-casscf] Energy=${ENERGY} Ha  Converged=${CONVERGED}"
echo "[gaussian-casscf] Writing output files to ${OUTPUT_DIR}..."

if [[ -f input.chk ]]; then
    echo "[gaussian-casscf] Converting .chk to .fchk..."
    formchk input.chk input.fchk > /dev/null 2>&1 || echo "[gaussian-casscf][WARN] formchk failed (non-fatal)" >&2
    if [[ -f input.fchk ]]; then
        cp input.fchk "${OUTPUT_DIR}/fchk_file"
    else
        echo "[gaussian-casscf][WARN] input.fchk not produced by formchk" >&2
        echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
    fi
else
    echo "[gaussian-casscf][WARN] .chk file not found!" >&2
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

echo "${ENERGY}"    > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}" > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"    > "${OUTPUT_DIR}/scf_energy"

echo "[gaussian-casscf] Done. Output files:"
ls -la "${OUTPUT_DIR}/"
