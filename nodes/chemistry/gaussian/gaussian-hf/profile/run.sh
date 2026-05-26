#!/usr/bin/env bash
# gaussian-hf/profile/run.sh — Hartree-Fock 单点能量
set -euo pipefail
# MF2 init

mf_banner "gaussian-hf" "Hartree-Fock single-point energy calculation"

echo "[gaussian-hf] HF/${basis_set} Pop=${population} Cores=${n_cores} Mem=${mem_gb}GB"

XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-hf][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"

python3 << PYEOF
from string import Template

basis_set = '${basis_set}'
population = '${population}'
charge = '${charge}'
multiplicity = '${multiplicity}'
n_cores = '${n_cores}'
mem_gb = '${mem_gb}'

mem_mb = str(int(float(mem_gb) * 1024))

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.gjf.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    basis_set=basis_set,
    population=population,
    n_cores=n_cores,
    mem_mb=mem_mb,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
)

with open('${WORKDIR}/input.gjf', 'w') as f:
    f.write(result)

print(f"[gaussian-hf] Generated input.gjf ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[gaussian-hf] Generated input.gjf:"
cat "${WORKDIR}/input.gjf"

cd "$WORKDIR"
echo "[gaussian-hf] Running Gaussian..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-hf][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-hf] Gaussian finished. Parsing output..."

ENERGY=$(grep "SCF Done" output.log | tail -1 | awk '{print $5}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-hf][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "Convergence criterion not met" output.log; then
    CONVERGED="false"
    echo "[gaussian-hf][WARN] SCF DID NOT CONVERGE!"
fi

echo "[gaussian-hf] Energy=${ENERGY} Ha  Converged=${CONVERGED}"

if [[ -f input.chk ]]; then
    echo "[gaussian-hf] Converting .chk to .fchk..."
    formchk input.chk input.fchk > /dev/null 2>&1
    cp input.fchk "${OUTPUT_DIR}/fchk_file"
else
    echo "[gaussian-hf][WARN] .chk file not found!" >&2
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

echo "${ENERGY}"    > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}" > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"    > "${OUTPUT_DIR}/scf_energy"

echo "[gaussian-hf] Done."
