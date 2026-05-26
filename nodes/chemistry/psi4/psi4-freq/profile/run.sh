#!/usr/bin/env bash
# psi4-freq/profile/run.sh — 振动频率分析
set -euo pipefail
# MF2 init

mf_banner "psi4-freq" "Vibrational frequency analysis"

echo "[psi4-freq] Method=${method}/${basis_set} Ref=${reference} T=${temperature}K P=${pressure}atm Cores=${n_cores}"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[psi4-freq][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"
echo "[psi4-freq] Loaded input geometry: $(wc -l < "${WORKDIR}/input.xyz") lines"

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
temperature = '${temperature}'
pressure = '${pressure}'
mem_gb = '${mem_gb}'

mem_mb = str(int(float(mem_gb) * 1024))

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
    temperature=temperature,
    pressure=pressure,
    geometry_lines=geometry_lines,
    mem_mb=mem_mb,
    output_dir='${OUTPUT_DIR}',
)

with open('${WORKDIR}/input.py', 'w') as f:
    f.write(result)

print(f"[psi4-freq] Generated input.py ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[psi4-freq] Generated input.py"

# ── 运行 Psi4 ─────────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[psi4-freq] Running Psi4 frequency analysis..."
psi4 input.py > output.log 2>&1 || {
    ec=$?
    echo "[psi4-freq][ERROR] psi4 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[psi4-freq] Psi4 finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
# 从 input.py 中的 print() 输出提取数据
ENERGY=$(grep "FINAL ENERGY:" output.log | tail -1 | awk '{print $NF}' || echo "")
N_IMAG=$(grep "N_IMAGINARY:" output.log | tail -1 | awk '{print $NF}' || echo "-1")
ZPE=$(grep "^ZPE:" output.log | tail -1 | awk '{print $NF}' || echo "")
ENTHALPY=$(grep "^ENTHALPY:" output.log | tail -1 | awk '{print $NF}' || echo "")
GIBBS=$(grep "^GIBBS:" output.log | tail -1 | awk '{print $NF}' || echo "")

if [[ -z "$ENERGY" ]]; then
    echo "[psi4-freq][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

IS_MINIMUM="true"
if [[ "$N_IMAG" -gt 0 ]]; then
    IS_MINIMUM="false"
    echo "[psi4-freq][WARN] Found ${N_IMAG} imaginary frequency(ies)!"
fi

echo "[psi4-freq] Energy=${ENERGY} Ha  N_imag=${N_IMAG}  ZPE=${ZPE}  H=${ENTHALPY}  G=${GIBBS}"

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
workdir = '${WORKDIR}'
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

# 读取频率列表
freqs = []
log_path = os.path.join(workdir, "output.log")
if os.path.exists(log_path):
    for line in open(log_path):
        if line.startswith("FREQS:"):
            try:
                freqs = json.loads(line.split(":", 1)[1].strip())
            except Exception:
                pass
            break

report = {
    "energy_ha": _read_output("total_energy") if os.path.exists(os.path.join(output_dir, "total_energy")) else 0.0,
    "zpe_ha": _read_output("zpe"),
    "enthalpy_ha": _read_output("enthalpy"),
    "gibbs_free_energy_ha": _read_output("gibbs_free_energy"),
    "temperature_K": float(temperature),
    "pressure_atm": float(pressure),
    "n_imaginary": n_imag,
    "frequencies": freqs,
}

with open(os.path.join(output_dir, "thermo_report"), "w") as f:
    json.dump(report, f, indent=2)

print("[psi4-freq] Generated thermo_report JSON")
PYEOF

echo "[psi4-freq] Done."
