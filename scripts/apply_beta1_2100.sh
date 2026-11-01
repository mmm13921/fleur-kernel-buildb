#!/usr/bin/env bash
set -Eeuo pipefail

SRC_DIR="${1:?Usage: apply_beta1_2100.sh <kernel-source-directory>}"
python3 - "$SRC_DIR" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
def patch(rel, old, new, expected=1):
    path = root / rel
    if not path.is_file():
        raise SystemExit(f"Missing source file: {rel}")
    text = path.read_text()
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{rel}: expected {expected} occurrence(s) of {old!r}, found {count}")
    path.write_text(text.replace(old, new))
    print(f"PATCH {rel}: {old.strip()} -> {new.strip()}")

# This source ref currently selects CPU_LEVEL_0 for MT6781. Fail closed if that changes.
platform = (root / "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_platform.c").read_text()
start = platform.find("unsigned int _mt_cpufreq_get_cpu_level(void)")
if start < 0:
    raise SystemExit("CPU-level selector not found")
selector = platform[start:platform.find("\n}", start) + 2]
if "unsigned int lv = CPU_LEVEL_0;" not in selector or "return lv;" not in selector:
    raise SystemExit("CPU_LEVEL_0 selection changed; refusing to apply Beta 1 assumptions")

dts = "arch/arm64/boot/dts/mediatek/mt6781.dts"
patch(dts, "opp-hz = /bits/ 64 <2050000000>;", "opp-hz = /bits/ 64 <2100000000>;", 1)
patch(dts, "clock-frequency = <2050000000>;", "clock-frequency = <2100000000>;", 2)

opp = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_table.h"
patch(opp, "#define CPU_DVFS_FREQ0_L_6781T 2050000", "#define CPU_DVFS_FREQ0_L_6781T 2100000", 1)

pv = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_pv_table.h"
patch(pv, "{ 2050, 99, 1, 1 },", "{ 2100, 99, 1, 1 },", 1)

# Voltage remains at the existing CPU_LEVEL_0 stock maximum.
dts_text = (root / dts).read_text()
pv_text = (root / pv).read_text()
if "opp-microvolt = <1118750>;" not in dts_text:
    raise SystemExit("Stock DT voltage 1,118,750 uV is missing or was modified")
if "{ 2100, 99, 1, 1 }," not in pv_text:
    raise SystemExit("Beta 1 OPP row does not retain stock voltage code 99")
if "CPU_DVFS_VOLT0_VPROC2_6781T 111875" not in (root / opp).read_text():
    raise SystemExit("Stock VPROC voltage definition changed")

print("Beta 1 patch applied: big cluster 2100 MHz; CPU_LEVEL_0 VPROC unchanged.")
PY
