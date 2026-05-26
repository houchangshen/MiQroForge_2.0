#!/usr/bin/env bash
# psi4-casci/profile/run.sh — CASCI 单点能量
set -euo pipefail
# MF2 init

mf_banner "psi4-casci" "CASCI single-point energy calculation"

echo "[psi4-casci] CASSCF/${basis_set} AE=${active_electrons} AO=${active_orbitals} Ref=${reference} SCF=${scf_type} Charge=${charge} Mult=${multiplicity} Cores=${n_cores}"

# ── 读取 stream input: xyz_geometry ──────────────────────────────────────────
XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[psi4-casci][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"
echo "[psi4-casci] Loaded input geometry: $(wc -l < "${WORKDIR}/input.xyz") lines"

# ── 生成 Psi4 输入脚本（string.Template 渲染）─────────────────────────────────
python3 << PYEOF
from string import Template

basis_set = '${basis_set}'
reference = '${reference}'
scf_type = '${scf_type}'
n_cores = '${n_cores}'
charge = '${charge}'
multiplicity = '${multiplicity}'
mem_gb = '${mem_gb}'
active_electrons = '${active_electrons}'
active_orbitals = '${active_orbitals}'

mem_mb = str(int(float(mem_gb) * 1024))

# Compute frozen_docc: Psi4 does not auto-freeze like ORCA/Gaussian.
# frozen_docc = (total_electrons - active_electrons) // 2
# total_electrons from atomic numbers - charge
ATOMIC_NUM = {'H':1,'He':2,'Li':3,'Be':4,'B':5,'C':6,'N':7,'O':8,'F':9,'Ne':10,
              'Na':11,'Mg':12,'Al':13,'Si':14,'P':15,'S':16,'Cl':17,'Ar':18}
with open('${WORKDIR}/input.xyz') as f:
    xyz_lines = f.readlines()
n_atoms = int(xyz_lines[0].strip())
total_electrons = sum(ATOMIC_NUM.get(line.split()[0], 0) for line in xyz_lines[2:2+n_atoms]) - int(charge)
frozen_docc = max(0, (total_electrons - int(active_electrons)) // 2)

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.py.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    basis_set=basis_set,
    reference=reference,
    scf_type=scf_type,
    n_cores=n_cores,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
    mem_mb=mem_mb,
    active_orbitals=active_orbitals,
    frozen_docc=str(frozen_docc),
    output_dir='${OUTPUT_DIR}',
)

with open('${WORKDIR}/input.py', 'w') as f:
    f.write(result)

print(f"[psi4-casci] Generated input.py ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[psi4-casci] Generated input.py:"
cat "${WORKDIR}/input.py"

# ── 运行 Psi4 ─────────────────────────────────────────────────────────────────
cd "$WORKDIR"
echo "[psi4-casci] Running Psi4..."
psi4 input.py > output.log 2>&1 || {
    ec=$?
    echo "[psi4-casci][ERROR] psi4 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[psi4-casci] Psi4 finished. Parsing output..."

# ── 解析输出 ──────────────────────────────────────────────────────────────────
ENERGY=$(grep "FINAL ENERGY:" output.log | tail -1 | awk '{print $NF}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[psi4-casci][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "SCF did not converge" output.log; then
    CONVERGED="false"
    echo "[psi4-casci][WARN] SCF DID NOT CONVERGE!"
fi

SCF_ITER=$(grep -oP "Guess energy.*?after \K[0-9]+" output.log || echo "0")
echo "[psi4-casci] Energy=${ENERGY} Ha  Converged=${CONVERGED}  SCF_iter=${SCF_ITER}"

# ── 写入输出 ──────────────────────────────────────────────────────────────────
echo "${ENERGY}"      > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}"   > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"      > "${OUTPUT_DIR}/scf_energy"
echo "${SCF_ITER:-0}" > "${OUTPUT_DIR}/scf_iterations"

if [[ -f "${OUTPUT_DIR}/wavefunction.json" ]]; then
    cp "${OUTPUT_DIR}/wavefunction.json" "${OUTPUT_DIR}/wavefunction_data"
    echo "[psi4-casci] Wavefunction data saved."
else
    echo "[psi4-casci][WARN] Wavefunction file not found."
    echo "{}" > "${OUTPUT_DIR}/wavefunction_data"
fi

echo "[psi4-casci] Done."
