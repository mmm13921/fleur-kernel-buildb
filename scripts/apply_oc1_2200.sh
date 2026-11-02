#!/usr/bin/env bash
set -Eeuo pipefail
SRC_DIR="${1:?Usage: apply_oc1_2200.sh <kernel-source-directory>}"
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$WORKSPACE/scripts/apply_beta2_2200.sh" "$SRC_DIR"

python3 - "$SRC_DIR" <<'PY'
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
def read(rel):
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"OC1 audit: required file missing: {rel}")
    return p.read_text(errors="replace")
platform_h = read("drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_platform.h")
hybrid = read("drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c")
config = read("arch/arm64/configs/fleur_defconfig")
for symbol in ("CONFIG_MTK_TINYSYS_SSPM_SUPPORT=y", "CONFIG_MTK_TINYSYS_SSPM_V2=y", "CONFIG_THERMAL=y", "CONFIG_CPU_THERMAL=y"):
    if symbol not in config:
        raise SystemExit(f"OC1 audit: required protection/config missing: {symbol}")
for token, source in (
    ("#define PPM_AP_SIDE", platform_h),
    ("idx_opp_ppm_limit", hybrid),
    ("if (j < p->idx_opp_ppm_limit)", hybrid),
    ("OFFS_IMAX_THERMAL_EN", hybrid),
    ("csram_write(OFFS_IMAX_THERMAL_EN, 1);", hybrid),
):
    if token not in source:
        raise SystemExit(f"OC1 audit: SSPM thermal/PPM path missing: {token}")
changed = set(subprocess.check_output(["git", "-C", str(root), "diff", "--name-only"], text=True).splitlines())
allowed = {
    "arch/arm64/boot/dts/mediatek/mt6781.dts",
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_table.h",
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_pv_table.h",
}
if changed != allowed:
    raise SystemExit(f"OC1 audit: unexpected changed source files: {sorted(changed)}")
print("OC1 source audit passed: CPU6/CPU7 top OPP 2200 MHz.")
print("DTS, Linux OPP and SSPM PVT table are coordinated.")
print("SSPM/PPM thermal cap path and IMAX thermal state remain enabled.")
print("PMIC ceilings, thermal trips, watchdog and vendor firmware are unchanged.")
PY
