#!/usr/bin/env bash
# gaussian-single-point/profile/run.sh — 单点能量计算
set -euo pipefail
# MF2 init

mf_banner "gaussian-single-point" "Single-point electronic energy calculation"

echo "[gaussian-single-point] Method=${method}/${basis_set} Pop=${population} Cores=${n_cores} Mem=${mem_gb}GB"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-single-point][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
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

mem_mb = str(int(float(mem_gb) * 1024))

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.gjf.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    method=method,
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

print(f"[gaussian-single-point] Generated input.gjf ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[gaussian-single-point] Generated input.gjf:"
cat "${WORKDIR}/input.gjf"

# ── 运行 Gaussian ─────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[gaussian-single-point] Running Gaussian..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-single-point][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-single-point] Gaussian finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "SCF Done" output.log | tail -1 | awk '{print $5}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-single-point][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "Convergence criterion not met" output.log; then
    CONVERGED="false"
    echo "[gaussian-single-point][WARN] SCF DID NOT CONVERGE!"
fi

echo "[gaussian-single-point] Energy=${ENERGY} Ha  Converged=${CONVERGED}"

# ── 转换 .chk → .fchk ───────────────────────────────────────────────────────
if [[ -f input.chk ]]; then
    echo "[gaussian-single-point] Converting .chk to .fchk..."
    formchk input.chk input.fchk > /dev/null 2>&1
    cp input.fchk "${OUTPUT_DIR}/fchk_file"
else
    echo "[gaussian-single-point][WARN] .chk file not found!" >&2
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ENERGY}"    > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}" > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"    > "${OUTPUT_DIR}/scf_energy"

echo "[gaussian-single-point] Done."
