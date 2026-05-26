#!/usr/bin/env bash
# gaussian-freq/profile/run.sh — 振动频率分析
set -euo pipefail
# MF2 init

mf_banner "gaussian-freq" "Vibrational frequency analysis"

echo "[gaussian-freq] Method=${method}/${basis_set} Pop=${population} T=${temperature}K P=${pressure}atm"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-freq][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
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
temperature = '${temperature}'
pressure = '${pressure}'

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
    temperature=temperature,
    pressure=pressure,
    geometry_lines=geometry_lines,
)

with open('${WORKDIR}/input.gjf', 'w') as f:
    f.write(result)

print(f"[gaussian-freq] Generated input.gjf")
PYEOF

echo "[gaussian-freq] Generated input.gjf"

# ── 运行 Gaussian ─────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[gaussian-freq] Running Gaussian frequency analysis..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-freq][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-freq] Gaussian finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "SCF Done" output.log | tail -1 | awk '{print $5}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-freq][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

# 提取热化学量（Gaussian 输出格式：Thermochemistry 部分）
ZPE=$(grep "Zero-point correction=" output.log | tail -1 | awk '{print $3}' || echo "")
ENTHALPY=$(grep "Sum of electronic and thermal Enthalpies=" output.log | tail -1 | awk '{print $NF}' || echo "")
GIBBS=$(grep "Sum of electronic and thermal Free Energies=" output.log | tail -1 | awk '{print $NF}' || echo "")

# 统计虚频数量 — Gaussian 在 "Frequencies --" 行输出负频率值
N_IMAG=$(grep "Frequencies --" output.log | grep -oP '[-]\d+\.\d+' | wc -l || echo "0")

IS_MINIMUM="true"
if [[ "$N_IMAG" -gt 0 ]]; then
    IS_MINIMUM="false"
    echo "[gaussian-freq][WARN] Found ${N_IMAG} imaginary frequency(ies)!"
fi

echo "[gaussian-freq] Energy=${ENERGY} Ha  N_imag=${N_IMAG}  ZPE=${ZPE}  G=${GIBBS}"

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ZPE}"        > "${OUTPUT_DIR}/zpe"
echo "${GIBBS}"      > "${OUTPUT_DIR}/gibbs_free_energy"
echo "${ENTHALPY}"   > "${OUTPUT_DIR}/enthalpy"
echo "${N_IMAG:-0}"  > "${OUTPUT_DIR}/n_imaginary"
echo "${IS_MINIMUM}" > "${OUTPUT_DIR}/is_true_minimum"

# ── 生成 thermo report JSON ──────────────────────────────────────────────────
python3 << PYEOF
import os
import json

output_dir = '${OUTPUT_DIR}'
temperature = '${temperature}'
pressure = '${pressure}'

def _read_output(name):
    path = os.path.join(output_dir, name)
    try:
        return float(open(path).read().strip())
    except (ValueError, FileNotFoundError):
        return 0.0

n_imag_path = os.path.join(output_dir, "n_imaginary")
try:
    n_imag = int(open(n_imag_path).read().strip())
except (ValueError, FileNotFoundError):
    n_imag = 0

report = {
    "zpe_ha": _read_output("zpe"),
    "enthalpy_ha": _read_output("enthalpy"),
    "gibbs_free_energy_ha": _read_output("gibbs_free_energy"),
    "temperature_K": float(temperature),
    "pressure_atm": float(pressure),
    "n_imaginary": n_imag,
}

with open(os.path.join(output_dir, "thermo_report"), "w") as f:
    json.dump(report, f, indent=2)

print("[gaussian-freq] Generated thermo_report JSON")
PYEOF

echo "[gaussian-freq] Done."
