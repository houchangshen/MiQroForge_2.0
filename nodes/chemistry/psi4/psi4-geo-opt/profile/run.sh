#!/usr/bin/env bash
# psi4-geo-opt/profile/run.sh — 几何优化
set -euo pipefail
# MF2 init

mf_banner "psi4-geo-opt" "Geometry optimization"

echo "[psi4-geo-opt] Method=${method}/${basis_set} Ref=${reference} Cores=${n_cores} MaxIter=${max_iter}"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[psi4-geo-opt][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"
echo "[psi4-geo-opt] Loaded input geometry: $(wc -l < "${WORKDIR}/input.xyz") lines"

# ── 生成 Psi4 输入脚本 ───────────────────────────────────────────────────────
python3 << PYEOF
from string import Template

method = '${method}'
basis_set = '${basis_set}'
reference = '${reference}'
scf_type = '${scf_type}'
n_cores = '${n_cores}'
charge = '${charge}'
multiplicity = '${multiplicity}'
max_iter = '${max_iter}'
geom_max_force = '${geom_max_force}'
mem_gb = '${mem_gb}'

mem_mb = str(int(float(mem_gb) * 1024))

# Psi4 不支持直接设置单个力收敛阈值，需映射到 g_convergence 预设级别。
# 官方 Max Force 阈值：
#   GAU_VERYTIGHT  1.0e-6
#   GAU_TIGHT      1.5e-5
#   QCHEM          3.0e-4  (Psi4 默认)
#   GAU            3.0e-4
#   GAU_LOOSE      1.7e-3
#   NWCHEM_LOOSE   3.0e-3
force_thresh = float(geom_max_force)
if force_thresh <= 1.0e-6:
    g_convergence = 'gau_verytight'
elif force_thresh <= 1.5e-5:
    g_convergence = 'gau_tight'
elif force_thresh <= 3.0e-4:
    g_convergence = 'qchem'   # Psi4 默认，与 nodespec default 一致
elif force_thresh <= 1.7e-3:
    g_convergence = 'gau_loose'
else:
    g_convergence = 'nwchem_loose'

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.psi4.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    method=method,
    basis_set=basis_set,
    reference=reference,
    scf_type=scf_type,
    n_cores=n_cores,
    charge=charge,
    multiplicity=multiplicity,
    max_iter=max_iter,
    g_convergence=g_convergence,
    geometry_lines=geometry_lines,
    mem_mb=mem_mb,
    output_dir='${OUTPUT_DIR}',
)

with open('${WORKDIR}/input.py', 'w') as f:
    f.write(result)

print(f"[psi4-geo-opt] Generated input.py ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[psi4-geo-opt] Generated input.py"

# ── 运行 Psi4 ─────────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[psi4-geo-opt] Running Psi4 geometry optimization..."
psi4 input.py > output.log 2>&1 || {
    ec=$?
    echo "[psi4-geo-opt][ERROR] psi4 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[psi4-geo-opt] Psi4 finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "FINAL ENERGY:" output.log | tail -1 | awk '{print $NF}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[psi4-geo-opt][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "Did not converge\|Optimization failed" output.log; then
    CONVERGED="false"
    echo "[psi4-geo-opt][WARN] Optimization DID NOT CONVERGE!"
fi

OPT_CYCLES=$(grep -oP "Optimization converged in \K[0-9]+" output.log || echo "0")
echo "[psi4-geo-opt] Energy=${ENERGY} Ha  Converged=${CONVERGED}  Cycles=${OPT_CYCLES}"

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ENERGY}"        > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}"     > "${OUTPUT_DIR}/opt_converged"
echo "${ENERGY}"        > "${OUTPUT_DIR}/final_energy"
echo "${OPT_CYCLES:-0}" > "${OUTPUT_DIR}/opt_cycles"

if [[ -f "${OUTPUT_DIR}/optimized_xyz" ]]; then
    echo "[psi4-geo-opt] Optimized geometry saved."
else
    echo "[psi4-geo-opt][WARN] Optimized XYZ not found, copying input as fallback."
    cp "${WORKDIR}/input.xyz" "${OUTPUT_DIR}/optimized_xyz"
fi

echo "[psi4-geo-opt] Done."
