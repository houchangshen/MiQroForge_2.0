#!/usr/bin/env bash
# gaussian-geo-opt/profile/run.sh — 几何优化
set -euo pipefail
# MF2 init

mf_banner "gaussian-geo-opt" "Geometry optimization"

echo "[gaussian-geo-opt] Method=${method}/${basis_set} Pop=${population} MaxIter=${max_iter} Cores=${n_cores}"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-geo-opt][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"

# ── 生成 Gaussian 输入文件 ────────────────────────────────────────────────────
python3 << PYEOF
from string import Template

method = '${method}'
basis_set = '${basis_set}'
population = '${population}'
charge = '${charge}'
multiplicity = '${multiplicity}'
n_cores = '${n_cores}'
mem_gb = '${mem_gb}'
max_iter = '${max_iter}'

mem_mb = str(int(float(mem_gb) * 1024))

# Opt 参数：MaxCycle 控制最大迭代步数
opt_params = f"MaxCycle={max_iter}"

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.gjf.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    method=method,
    basis_set=basis_set,
    population=population,
    opt_params=opt_params,
    n_cores=n_cores,
    mem_mb=mem_mb,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
)

with open('${WORKDIR}/input.gjf', 'w') as f:
    f.write(result)

print(f"[gaussian-geo-opt] Generated input.gjf (MaxCycle={max_iter})")
PYEOF

echo "[gaussian-geo-opt] Generated input.gjf"

# ── 运行 Gaussian ─────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[gaussian-geo-opt] Running Gaussian optimization..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-geo-opt][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-geo-opt] Gaussian finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "SCF Done" output.log | tail -1 | awk '{print $5}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-geo-opt][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "Optimization completed\." output.log; then
    CONVERGED="true"
elif grep -q "Maximum number of optimization cycles reached" output.log; then
    CONVERGED="false"
    echo "[gaussian-geo-opt][WARN] Max optimization cycles reached!"
fi

OPT_CYCLES=$(grep -c "Step number" output.log || echo "0")
echo "[gaussian-geo-opt] Energy=${ENERGY} Ha  Converged=${CONVERGED}  Cycles=${OPT_CYCLES}"

# ── 提取优化后几何 ───────────────────────────────────────────────────────────
python3 /mf/profile/postprocess.py

# ── 转换 .chk → .fchk ───────────────────────────────────────────────────────
if [[ -f input.chk ]]; then
    formchk input.chk input.fchk > /dev/null 2>&1
    cp input.fchk "${OUTPUT_DIR}/fchk_file"
else
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ENERGY}"        > "${OUTPUT_DIR}/total_energy"
echo "${ENERGY}"        > "${OUTPUT_DIR}/final_energy"
echo "${CONVERGED}"     > "${OUTPUT_DIR}/opt_converged"
echo "${OPT_CYCLES:-0}" > "${OUTPUT_DIR}/opt_cycles"

echo "[gaussian-geo-opt] Done."
