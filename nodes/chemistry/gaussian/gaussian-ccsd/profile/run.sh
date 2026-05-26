#!/usr/bin/env bash
# gaussian-ccsd/profile/run.sh — CCSD/CCSD(T) 单点能量
set -euo pipefail
# MF2 init

mf_banner "gaussian-ccsd" "CCSD/CCSD(T) single-point energy calculation"

# ── 方法变体 ───────────────────────────────────────────────────────────────
METHOD="${method_variant:-CCSD}"

echo "[gaussian-ccsd] ${METHOD}/${basis_set} FC=${frozen_core} Pop=${population} Cores=${n_cores} Mem=${mem_gb}GB"

XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-ccsd][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
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

# Frozen core: CCSD(full) to unfreeze core orbitals, empty for default frozen core
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

print(f"[gaussian-ccsd] Generated input.gjf for {method} ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[gaussian-ccsd] Generated input.gjf:"
cat "${WORKDIR}/input.gjf"

cd "$WORKDIR"
echo "[gaussian-ccsd] Running Gaussian..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-ccsd][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-ccsd] Gaussian finished (${METHOD}). Parsing output..."

# Energy extraction:
#   Unlike MP2 (which prints "EUMP2=..." / "E(MP2)=..."), Gaussian 16's CCSD output
#   does NOT contain an "E(CCSD)=..." line. The energy appears in two places:
#     1. Archive entry:  CCSD=-75.0122086  (and CCSD(T)=-xxx for triples)
#     2. Correlation summary:  E(Corr)= -75.012208612  /  E(CORR)= -75.012210765
#   The original grep for "E(CCSD)" matched nothing, causing the script to exit
#   before writing output files — Argo then reported "cannot save parameter" errors.
#   Fix: extract from the archive entry ("CCSD=..." / "CCSD(T)=...") first,
#   fallback to "E(Corr)" line if archive entry is missing.
if [[ "${METHOD}" == "CCSD(T)" ]]; then
    ENERGY=$(grep -oP 'CCSD\(T\)=\K-?[0-9]+\.[0-9]+' output.log | tail -1 || echo "")
    if [[ -z "$ENERGY" ]]; then
        ENERGY=$(grep -oP 'CCSD=\K-?[0-9]+\.[0-9]+' output.log | tail -1 || echo "")
    fi
    if [[ -z "$ENERGY" ]]; then
        ENERGY=$(grep "E(Corr)" output.log | tail -1 | awk -F'=' '{print $2}' | awk '{print $1}' || echo "")
    fi
else
    ENERGY=$(grep -oP 'CCSD=\K-?[0-9]+\.[0-9]+' output.log | tail -1 || echo "")
    if [[ -z "$ENERGY" ]]; then
        ENERGY=$(grep "E(Corr)" output.log | tail -1 | awk -F'=' '{print $2}' | awk '{print $1}' || echo "")
    fi
fi
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-ccsd][ERROR] Could not extract ${METHOD} energy from output!" >&2
    cat output.log >&2
    exit 1
fi
# Convert Fortran D-format (e.g. -0.353D+02) to E-format for downstream consumers
ENERGY=$(echo "$ENERGY" | sed 's/D/E/g' | python3 -c "import sys; print(f'{float(sys.stdin.read().strip()):.10f}')")

CONVERGED="true"
if grep -q "Convergence criterion not met" output.log; then
    CONVERGED="false"
    echo "[gaussian-ccsd][WARN] SCF DID NOT CONVERGE!"
fi

echo "[gaussian-ccsd] Energy=${ENERGY} Ha  Converged=${CONVERGED}"

if [[ -f input.chk ]]; then
    echo "[gaussian-ccsd] Converting .chk to .fchk..."
    formchk input.chk input.fchk > /dev/null 2>&1
    cp input.fchk "${OUTPUT_DIR}/fchk_file"
else
    echo "[gaussian-ccsd][WARN] .chk file not found!" >&2
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

echo "${ENERGY}"    > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}" > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"    > "${OUTPUT_DIR}/scf_energy"

echo "[gaussian-ccsd] Done."
