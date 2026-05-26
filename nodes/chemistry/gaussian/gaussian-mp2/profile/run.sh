#!/usr/bin/env bash
# gaussian-mp2/profile/run.sh — MP2/MP3/MP4 单点能量
set -euo pipefail
# MF2 init

mf_banner "gaussian-mp2" "MP2/MP3/MP4 single-point energy calculation"

# ── 方法变体 ───────────────────────────────────────────────────────────────
METHOD="${method_variant:-MP2}"

echo "[gaussian-mp2] ${METHOD}/${basis_set} FC=${frozen_core} Pop=${population} Cores=${n_cores} Mem=${mem_gb}GB"

XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-mp2][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"

python3 << PYEOF
from string import Template

method = '${METHOD}'
basis_set = '${basis_set}'
population = '${population}'
frozen_core = '${frozen_core}'
charge = '${charge}'
multiplicity = '${multiplicity}'
n_cores = '${n_cores}'
mem_gb = '${mem_gb}'

mem_mb = str(int(float(mem_gb) * 1024))

# Frozen core: MP2(full) to unfreeze core orbitals, empty for default frozen core
fc_kw = '' if frozen_core.lower() == 'true' else '(full)'

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.gjf.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    method=method,
    basis_set=basis_set,
    population=population,
    fc_kw=fc_kw,
    n_cores=n_cores,
    mem_mb=mem_mb,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
)

with open('${WORKDIR}/input.gjf', 'w') as f:
    f.write(result)

print(f"[gaussian-mp2] Generated input.gjf for {method} ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[gaussian-mp2] Generated input.gjf:"
cat "${WORKDIR}/input.gjf"

cd "$WORKDIR"
echo "[gaussian-mp2] Running Gaussian..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-mp2][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-mp2] Gaussian finished (${METHOD}). Parsing output..."

# Energy extraction:
#   Gaussian 16 prints MPn total energy in two forms:
#     1. Archive entry:  MP2=-74.9983209\  (backslash-separated, single long line)
#        The value is the TOTAL energy (HF + correlation).
#     2. EUMP2 line:     EUMP2 = -0.74998320875307D+02
#   The old grep chain (grep -E "RMP2|UMP2|LMP2" | grep "EUMP2") was fragile —
#   "UMP2" matches as a substring in "EUMP2" and "T2", and the awk extraction
#   could pick up the correlation energy (E2) instead of the total energy.
#   Fix: extract from archive entry first (MP2=...), then EUMPn line, then E(Corr).
if [[ "${METHOD}" == "MP4" ]]; then
    ENERGY=$(grep -oP 'MP4=\K-?[0-9]+\.[0-9]+' output.log | tail -1 || echo "")
    [[ -z "$ENERGY" ]] && ENERGY=$(grep -oP 'EUMP4\s*=\s*\K-?[0-9]+\.[0-9]+D[+-][0-9]+' output.log | tail -1 || echo "")
    [[ -z "$ENERGY" ]] && ENERGY=$(grep "E(Corr)" output.log | tail -1 | awk -F'=' '{print $2}' | awk '{print $1}' || echo "")
elif [[ "${METHOD}" == "MP3" ]]; then
    ENERGY=$(grep -oP 'MP3=\K-?[0-9]+\.[0-9]+' output.log | tail -1 || echo "")
    [[ -z "$ENERGY" ]] && ENERGY=$(grep -oP 'EUMP3\s*=\s*\K-?[0-9]+\.[0-9]+D[+-][0-9]+' output.log | tail -1 || echo "")
    [[ -z "$ENERGY" ]] && ENERGY=$(grep "E(Corr)" output.log | tail -1 | awk -F'=' '{print $2}' | awk '{print $1}' || echo "")
else
    ENERGY=$(grep -oP 'MP2=\K-?[0-9]+\.[0-9]+' output.log | tail -1 || echo "")
    [[ -z "$ENERGY" ]] && ENERGY=$(grep -oP 'EUMP2\s*=\s*\K-?[0-9]+\.[0-9]+D[+-][0-9]+' output.log | tail -1 || echo "")
    [[ -z "$ENERGY" ]] && ENERGY=$(grep "E(Corr)" output.log | tail -1 | awk -F'=' '{print $2}' | awk '{print $1}' || echo "")
fi
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-mp2][ERROR] Could not extract ${METHOD} energy from output!" >&2
    cat output.log >&2
    exit 1
fi
# Convert Fortran D-format (e.g. -0.353D+02) to E-format for downstream consumers
ENERGY=$(echo "$ENERGY" | sed 's/D/E/g' | python3 -c "import sys; print(f'{float(sys.stdin.read().strip()):.10f}')")

CONVERGED="true"
if grep -q "Convergence criterion not met" output.log; then
    CONVERGED="false"
    echo "[gaussian-mp2][WARN] SCF DID NOT CONVERGE!"
fi

echo "[gaussian-mp2] Energy=${ENERGY} Ha  Converged=${CONVERGED}"

if [[ -f input.chk ]]; then
    echo "[gaussian-mp2] Converting .chk to .fchk..."
    formchk input.chk input.fchk > /dev/null 2>&1
    cp input.fchk "${OUTPUT_DIR}/fchk_file"
else
    echo "[gaussian-mp2][WARN] .chk file not found!" >&2
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

echo "${ENERGY}"    > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}" > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"    > "${OUTPUT_DIR}/scf_energy"

echo "[gaussian-mp2] Done."
