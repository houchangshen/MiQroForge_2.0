#!/usr/bin/env bash
# psi4-ccsd/profile/run.sh — CCSD/CCSD(T) 单点能量
set -euo pipefail
# MF2 init

mf_banner "psi4-ccsd" "CCSD/CCSD(T) single-point energy calculation"

# ── 方法变体 ───────────────────────────────────────────────────────────────
METHOD="${method_variant:-CCSD}"

echo "[psi4-ccsd] ${METHOD}/${basis_set} FC=${frozen_core} Ref=${reference} SCF=${scf_type} Charge=${charge} Mult=${multiplicity} Cores=${n_cores}"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[psi4-ccsd][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"
echo "[psi4-ccsd] Loaded input geometry: $(wc -l < "${WORKDIR}/input.xyz") lines"

# ── 生成 Psi4 输入脚本（string.Template 渲染）─────────────────────────────────
python3 << PYEOF
from string import Template

method = '${METHOD}'.lower()  # Psi4 uses lowercase: 'ccsd', 'ccsd(t)'
basis_set = '${basis_set}'
reference = '${reference}'
scf_type = '${scf_type}'
n_cores = '${n_cores}'
charge = '${charge}'
multiplicity = '${multiplicity}'
mem_gb = '${mem_gb}'
frozen_core = '${frozen_core}'

mem_mb = str(int(float(mem_gb) * 1024))

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.py.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    method=method,
    basis_set=basis_set,
    reference=reference,
    scf_type=scf_type,
    n_cores=n_cores,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
    mem_mb=mem_mb,
    frozen_core=frozen_core,
    output_dir='${OUTPUT_DIR}',
)

with open('${WORKDIR}/input.py', 'w') as f:
    f.write(result)

print(f"[psi4-ccsd] Generated input.py for {method} ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[psi4-ccsd] Generated input.py:"
cat "${WORKDIR}/input.py"

# ── 运行 Psi4 ─────────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[psi4-ccsd] Running Psi4..."
psi4 input.py > output.log 2>&1 || {
    ec=$?
    echo "[psi4-ccsd][ERROR] psi4 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[psi4-ccsd] Psi4 finished (${METHOD}). Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "FINAL ENERGY:" output.log | tail -1 | awk '{print $NF}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[psi4-ccsd][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "SCF did not converge" output.log; then
    CONVERGED="false"
    echo "[psi4-ccsd][WARN] SCF DID NOT CONVERGE!"
fi

SCF_ITER=$(grep -oP "Guess energy.*?after \K[0-9]+" output.log || echo "0")
echo "[psi4-ccsd] Energy=${ENERGY} Ha  Converged=${CONVERGED}  SCF_iter=${SCF_ITER}"

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ENERGY}"      > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}"   > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"      > "${OUTPUT_DIR}/scf_energy"
echo "${SCF_ITER:-0}" > "${OUTPUT_DIR}/scf_iterations"

if [[ -f "${OUTPUT_DIR}/wavefunction.json" ]]; then
    cp "${OUTPUT_DIR}/wavefunction.json" "${OUTPUT_DIR}/wavefunction_data"
    echo "[psi4-ccsd] Wavefunction data saved."
else
    echo "[psi4-ccsd][WARN] Wavefunction file not found."
    echo "{}" > "${OUTPUT_DIR}/wavefunction_data"
fi

echo "[psi4-ccsd] Done."
