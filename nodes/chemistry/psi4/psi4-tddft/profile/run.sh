#!/usr/bin/env bash
# psi4-tddft/profile/run.sh — TD-DFT 激发态计算
set -euo pipefail
# MF2 init

mf_banner "psi4-tddft" "TD-DFT excited-state calculation"

echo "[psi4-tddft] TD-${functional}/${basis_set} States=${n_states} Disp=${dispersion} Ref=${reference} SCF=${scf_type} Charge=${charge} Mult=${multiplicity} Cores=${n_cores}"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[psi4-tddft][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"
echo "[psi4-tddft] Loaded input geometry: $(wc -l < "${WORKDIR}/input.xyz") lines"

# ── 生成 Psi4 输入脚本（string.Template 渲染）─────────────────────────────────
python3 << PYEOF
from string import Template

functional = '${functional}'
basis_set = '${basis_set}'
dispersion = '${dispersion}'
reference = '${reference}'
scf_type = '${scf_type}'
n_cores = '${n_cores}'
charge = '${charge}'
multiplicity = '${multiplicity}'
mem_gb = '${mem_gb}'
n_states = '${n_states}'

mem_mb = str(int(float(mem_gb) * 1024))

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.py.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    functional=functional,
    basis_set=basis_set,
    dispersion=dispersion,
    reference=reference,
    scf_type=scf_type,
    n_cores=n_cores,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
    mem_mb=mem_mb,
    n_states=n_states,
    output_dir='${OUTPUT_DIR}',
)

with open('${WORKDIR}/input.py', 'w') as f:
    f.write(result)

print(f"[psi4-tddft] Generated input.py ({mem_mb}MB, {n_states} states, {n_cores} cores)")
PYEOF

echo "[psi4-tddft] Generated input.py:"
cat "${WORKDIR}/input.py"

# ── 运行 Psi4 ─────────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[psi4-tddft] Running Psi4..."
psi4 input.py > output.log 2>&1 || {
    ec=$?
    echo "[psi4-tddft][ERROR] psi4 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[psi4-tddft] Psi4 finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "FINAL ENERGY:" output.log | tail -1 | awk '{print $NF}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[psi4-tddft][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "SCF did not converge" output.log; then
    CONVERGED="false"
    echo "[psi4-tddft][WARN] SCF DID NOT CONVERGE!"
fi

SCF_ITER=$(grep -oP "Guess energy.*?after \K[0-9]+" output.log || echo "0")
echo "[psi4-tddft] Ground-state Energy=${ENERGY} Ha  Converged=${CONVERGED}  SCF_iter=${SCF_ITER}"

# ── 提取激发能 ───────────────────────────────────────────────────────────────
python3 << PARSEEOF
import json, re

exc_energies = []
with open('output.log') as f:
    content = f.read()

# Parse TD-DFT excitation energies from Psi4 output
# Pattern: "Excitation energy (eV): X.XXXX" or "Excitation energy: X.XXXX (Hartree)"
for m in re.finditer(r'Excitation energy.*?:\s*([0-9]+\.?[0-9]*)', content):
    val = float(m.group(1))
    # Convert eV to Hartree if the value looks like eV (> 0.5 typically)
    if val > 0.5:
        val = val / 27.211386  # eV to Ha
    exc_energies.append(val)

# Fallback: look for "Root" lines with energies
if not exc_energies:
    for m in re.finditer(r'Root\s+\d+.*?energy.*?=\s*([-0-9.]+)', content):
        exc_energies.append(float(m.group(1)))

print(f"[psi4-tddft] Found {len(exc_energies)} excitation energies: {exc_energies}")

with open('${OUTPUT_DIR}/excitation_energies', 'w') as f:
    json.dump(exc_energies, f)
PARSEEOF

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ENERGY}"      > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}"   > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"      > "${OUTPUT_DIR}/scf_energy"
echo "${SCF_ITER:-0}" > "${OUTPUT_DIR}/scf_iterations"

if [[ -f "${OUTPUT_DIR}/wavefunction.json" ]]; then
    cp "${OUTPUT_DIR}/wavefunction.json" "${OUTPUT_DIR}/wavefunction_data"
    echo "[psi4-tddft] Wavefunction data saved."
else
    echo "[psi4-tddft][WARN] Wavefunction file not found."
    echo "{}" > "${OUTPUT_DIR}/wavefunction_data"
fi

echo "[psi4-tddft] Done."
