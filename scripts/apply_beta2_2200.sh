#!/usr/bin/env bash
set -Eeuo pipefail

SRC_DIR="${1:?Usage: apply_beta2_2200.sh <kernel-source-directory>}"
python3 - "$SRC_DIR" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])

def read(rel):
    path = root / rel
    if not path.is_file():
        raise SystemExit(f"Required source file missing: {rel}")
    return path.read_text()

def write(rel, content):
    (root / rel).write_text(content)

def replace_exact(text, old, new, expected, label):
    found = text.count(old)
    if found != expected:
        raise SystemExit(
            f"{label}: expected {expected} occurrence(s), found {found}: {old!r}"
        )
    return text.replace(old, new)

def braced_region(text, marker, label):
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"{label}: marker not found: {marker}")
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"{label}: opening brace not found")
    depth = 0
    for pos in range(brace, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return brace, pos + 1
    raise SystemExit(f"{label}: unterminated block")

# The build must use the SKU table path inspected below.
config = read("arch/arm64/configs/fleur_defconfig")
for symbol in (
    "CONFIG_MTK_TINYSYS_SSPM_SUPPORT=y",
    "CONFIG_MTK_TINYSYS_SSPM_V2=y",
):
    if symbol not in config:
        raise SystemExit(f"Required SSPM V2 configuration is absent: {symbol}")

platform_c = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_platform.c"
)
start = platform_c.find("unsigned int _mt_cpufreq_get_cpu_level(void)")
end = platform_c.find("\n}", start)
selector = platform_c[start:end + 2] if start >= 0 and end >= 0 else ""
if "unsigned int lv = CPU_LEVEL_0;" not in selector or "return lv;" not in selector:
    raise SystemExit("CPU_LEVEL_0 segment selector changed; refusing to patch")

# Verify PMIC voltage-code mapping: 50000 + 105 * 625 = 115625 (10-uV units).
platform_h = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_platform.h"
)
if "#define VPROC_BASE 50000" not in platform_h:
    raise SystemExit("Unexpected VPROC_BASE")
if "#define VPROC_STEP 625" not in platform_h:
    raise SystemExit("Unexpected VPROC_STEP")
if 50000 + 105 * 625 != 115625:
    raise SystemExit("Internal PMIC code calculation failed")

# Confirm that the requested VPROC and coupled VSRAM remain inside the
# source-declared regulator ceilings. Do not raise these ceilings.
pmic = read("arch/arm64/boot/dts/mediatek/mt6359p.dtsi")
vproc_start, vproc_end = braced_region(
    pmic, "mt_pmic_vproc2_buck_reg:", "VPROC2 regulator"
)
vproc_node = pmic[vproc_start:vproc_end]
if "regulator-max-microvolt = <1193750>;" not in vproc_node:
    raise SystemExit("VPROC2 regulator ceiling differs from audited source")
vsram_start, vsram_end = braced_region(
    pmic, "mt_pmic_vsram_proc2_ldo_reg:", "VSRAM2 regulator"
)
vsram_node = pmic[vsram_start:vsram_end]
if "regulator-max-microvolt = <1293750>;" not in vsram_node:
    raise SystemExit("VSRAM2 regulator ceiling differs from audited source")
if 1156250 > 1193750 or 1156250 + 100000 > 1293750:
    raise SystemExit("Requested top OPP exceeds PMIC regulator ceilings")

# 1. Linux Device Tree: cluster1 OPP, CPU6/CPU7 declarations, DOE B-table.
dts_path = "arch/arm64/boot/dts/mediatek/mt6781.dts"
dts = read(dts_path)
block_start, block_end = braced_region(
    dts, "cluster1_opp: opp_table1", "cluster1 OPP table"
)
cluster = dts[block_start:block_end]
cluster = replace_exact(
    cluster,
    "opp-hz = /bits/ 64 <2050000000>;",
    "opp-hz = /bits/ 64 <2200000000>;",
    1,
    "cluster1 top OPP frequency",
)
cluster = replace_exact(
    cluster,
    "opp-microvolt = <1118750>;",
    "opp-microvolt = <1156250>;",
    1,
    "cluster1 top OPP voltage",
)
dts = dts[:block_start] + cluster + dts[block_end:]
dts = replace_exact(
    dts,
    "clock-frequency = <2050000000>;",
    "clock-frequency = <2200000000>;",
    2,
    "CPU6/CPU7 clock-frequency declarations",
)
dts = replace_exact(
    dts,
    "B-table = <2050 99 1 1",
    "B-table = <2200 105 1 1",
    1,
    "DOE B-table top row",
)
write(dts_path, dts)

# 2. Linux CPU_LEVEL_0 OPP macros for the selected MT6781T SKU.
opp_path = (
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_opp_table.h"
)
opp = read(opp_path)
opp = replace_exact(
    opp,
    "#define CPU_DVFS_FREQ0_L_6781T 2050000",
    "#define CPU_DVFS_FREQ0_L_6781T 2200000",
    1,
    "CPU_LEVEL_0 big-cluster frequency macro",
)
opp = replace_exact(
    opp,
    "#define CPU_DVFS_VOLT0_VPROC2_6781T 111875",
    "#define CPU_DVFS_VOLT0_VPROC2_6781T 115625",
    1,
    "CPU_LEVEL_0 big-cluster VPROC macro",
)
write(opp_path, opp)

# 3. PVT table copied by the hybrid DVFS path into SSPM shared memory.
pv_path = (
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_opp_pv_table.h"
)
pv = read(pv_path)
pv = replace_exact(
    pv,
    "{ 2050, 99, 1, 1 },",
    "{ 2200, 105, 1, 1 },",
    1,
    "MT6781T PVT big-cluster top row",
)
write(pv_path, pv)

# Fail closed: verify the new settings and ensure the old top settings are gone.
for rel, old_values in (
    (
        dts_path,
        (
            "opp-hz = /bits/ 64 <2050000000>;",
            "clock-frequency = <2050000000>;",
            "B-table = <2050 99 1 1",
        ),
    ),
    (
        opp_path,
        (
            "#define CPU_DVFS_FREQ0_L_6781T 2050000",
            "#define CPU_DVFS_VOLT0_VPROC2_6781T 111875",
        ),
    ),
    (pv_path, ("{ 2050, 99, 1, 1 },",)),
):
    value = read(rel)
    for old in old_values:
        if old in value:
            raise SystemExit(f"Unpatched old top OPP remains in {rel}: {old}")

for rel, expected_values in (
    (
        dts_path,
        (
            "<2200000000>",
            "<1156250>",
            "B-table = <2200 105 1 1",
        ),
    ),
    (
        opp_path,
        (
            "CPU_DVFS_FREQ0_L_6781T 2200000",
            "CPU_DVFS_VOLT0_VPROC2_6781T 115625",
        ),
    ),
    (pv_path, ("{ 2200, 105, 1, 1 },",)),
):
    value = read(rel)
    for expected in expected_values:
        if expected not in value:
            raise SystemExit(f"Beta 2 value missing from {rel}: {expected}")

print("Beta 2 coordinated OPP patch applied; source assertions passed.")
print("CPU6/CPU7 top OPP: 2200 MHz")
print("Top big-cluster VPROC: 1,156,250 uV (+37,500 uV vs stock)")
print("PMIC code: 105; thermal and watchdog protections unchanged")
PY
