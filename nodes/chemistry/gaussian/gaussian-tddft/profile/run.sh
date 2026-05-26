#!/usr/bin/env bash
# gaussian-tddft/profile/run.sh — TD-DFT 激发态计算
set -euo pipefail
# MF2 init

mf_banner "gaussian-tddft" "TD-DFT excited-state calculation"

echo "[gaussian-tddft] TD(NStates=${n_states}) ${functional}/${basis_set} Disp=${dispersion} Pop=${population} Cores=${n_cores}"

XYZ_INPUT="${INPUT_DIR}/xyz_geometry"
if [[ ! -f "$XYZ_INPUT" ]]; then
    echo "[gaussian-tddft][ERROR] Required stream input 'xyz_geometry' not found at ${XYZ_INPUT}" >&2
    exit 1
fi
cp "$XYZ_INPUT" "${WORKDIR}/input.xyz"

python3 << PYEOF
from string import Template

functional = '${functional}'
basis_set = '${basis_set}'
dispersion = '${dispersion}'
population = '${population}'
n_states = '${n_states}'
charge = '${charge}'
multiplicity = '${multiplicity}'
n_cores = '${n_cores}'
mem_gb = '${mem_gb}'

mem_mb = str(int(float(mem_gb) * 1024))

# Gaussian dispersion keyword mapping (same as gaussian-dft)
disp_kw_map = {
    'none': '',
    'D3': 'EmpiricalGD=GD3 ',
    'D3BJ': 'EmpiricalGD=GD3BJ ',
    'D4': '',  # Gaussian 16 doesn't natively support D4
}
disp_kw = disp_kw_map.get(dispersion, '')

# Functional is used directly as method keyword
method_kw = functional

with open('${WORKDIR}/input.xyz') as f:
    lines = f.readlines()
geometry_lines = "".join(lines[2:])

with open('/mf/profile/input.gjf.template') as f:
    tmpl = Template(f.read())

result = tmpl.substitute(
    method_kw=method_kw,
    basis_set=basis_set,
    disp_kw=disp_kw,
    population=population,
    n_states=n_states,
    n_cores=n_cores,
    mem_mb=mem_mb,
    charge=charge,
    multiplicity=multiplicity,
    geometry_lines=geometry_lines,
)

with open('${WORKDIR}/input.gjf', 'w') as f:
    f.write(result)

print(f"[gaussian-tddft] Generated input.gjf ({mem_mb}MB, {n_cores} cores)")
PYEOF

echo "[gaussian-tddft] Generated input.gjf:"
cat "${WORKDIR}/input.gjf"

cd "$WORKDIR"
echo "[gaussian-tddft] Running Gaussian..."
g16 < input.gjf > output.log 2>&1 || {
    ec=$?
    echo "[gaussian-tddft][ERROR] g16 exited with ${ec}; dumping output.log tail:" >&2
    tail -n 200 output.log >&2 || true
    exit "${ec}"
}
echo "[gaussian-tddft] Gaussian finished. Parsing output..."

ENERGY=$(grep "SCF Done" output.log | tail -1 | awk '{print $5}' || echo "")
if [[ -z "$ENERGY" ]]; then
    echo "[gaussian-tddft][ERROR] Could not extract energy from output!" >&2
    cat output.log >&2
    exit 1
fi

CONVERGED="true"
if grep -q "Convergence criterion not met" output.log; then
    CONVERGED="false"
    echo "[gaussian-tddft][WARN] SCF DID NOT CONVERGE!"
fi

echo "[gaussian-tddft] Energy=${ENERGY} Ha  Converged=${CONVERGED}"

# Parse excitation energies from output (Gaussian prints them in eV)
python3 << PARSE_EOF
import re, json

excitations = []
with open('output.log') as f:
    text = f.read()

# Gaussian prints: "Excited State   1:   Singlet-A     4.1234 eV ..."
for m in re.finditer(r'Excited State\s+(\d+):\s+\S+\s+([\d.]+)\s+eV', text):
    excitations.append(float(m.group(2)))

with open('${OUTPUT_DIR}/excitation_energies', 'w') as f:
    json.dump(excitations, f)

print(f"[gaussian-tddft] Parsed {len(excitations)} excitation energies: {excitations}")
PARSE_EOF

if [[ -f input.chk ]]; then
    echo "[gaussian-tddft] Converting .chk to .fchk..."
    formchk input.chk input.fchk > /dev/null 2>&1
    cp input.fchk "${OUTPUT_DIR}/fchk_file"
else
    echo "[gaussian-tddft][WARN] .chk file not found!" >&2
    echo "NO_FCHK" > "${OUTPUT_DIR}/fchk_file"
fi

echo "${ENERGY}"    > "${OUTPUT_DIR}/total_energy"
echo "${CONVERGED}" > "${OUTPUT_DIR}/scf_converged"
echo "${ENERGY}"    > "${OUTPUT_DIR}/scf_energy"

echo "[gaussian-tddft] Done."
