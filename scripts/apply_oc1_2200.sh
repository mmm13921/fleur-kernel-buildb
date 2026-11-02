#!/usr/bin/env bash
set -Eeuo pipefail
SRC_DIR="${1:?Usage: apply_oc1_2200.sh <kernel-source-directory>}"
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$WORKSPACE/scripts/apply_beta2_2200.sh" "$SRC_DIR"

python3 - "$SRC_DIR" <<'PY'
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1])

def read(rel):
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"OC1 audit: required file missing: {rel}")
    return p.read_text(errors="replace")

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

# The DTB's DOE parser returns immediately while change_flag is zero.
# Enable DOE ingestion so the edited B-table is copied into the active
# kernel/SSPM DVFS tables instead of leaving the DTB property unused.
dts_path = "arch/arm64/boot/dts/mediatek/mt6781.dts"
dts = read(dts_path)
node_start, node_end = braced_region(
    dts, "dvfsp: dvfsp@0011bc00", "MT6781 DVFSP node"
)
node = dts[node_start:node_end]
node = replace_exact(
    node,
    "change_flag = <0>;",
    "change_flag = <1>;",
    1,
    "DVFSP DOE change_flag",
)
b_table = re.search(r"\bB-table\s*=\s*<([^>]*)>", node, re.S)
if not b_table:
    raise SystemExit("OC1 audit: DVFSP B-table property is missing")
cells = [
    int(value, 0)
    for value in re.findall(r"0[xX][0-9a-fA-F]+|\d+", b_table.group(1))
]
if len(cells) != 64:
    raise SystemExit(
        f"OC1 audit: expected 16 B-table OPP rows (64 cells), found {len(cells)}"
    )
if tuple(cells[:4]) != (2200, 105, 1, 1):
    raise SystemExit(
        f"OC1 audit: active DOE B-table top row is {tuple(cells[:4])}, "
        "expected (2200, 105, 1, 1)"
    )
freqs = cells[0::4]
if any(a <= b for a, b in zip(freqs, freqs[1:])):
    raise SystemExit("OC1 audit: B-table frequencies are not strictly descending")
dts = dts[:node_start] + node + dts[node_end:]
write(dts_path, dts)

platform_h = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_platform.h"
)
platform_c = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_platform.c"
)
hybrid = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c"
)
config = read("arch/arm64/configs/fleur_defconfig")
opp = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_opp_table.h"
)
pv = read(
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_opp_pv_table.h"
)

for symbol in (
    "CONFIG_MTK_TINYSYS_SSPM_SUPPORT=y",
    "CONFIG_MTK_TINYSYS_SSPM_V2=y",
    "CONFIG_THERMAL=y",
    "CONFIG_CPU_THERMAL=y",
):
    if symbol not in config:
        raise SystemExit(
            f"OC1 audit: required protection/config missing: {symbol}"
        )

if not re.search(r"^\s*#define\s+ENABLE_DOE\s+1\b", platform_h, re.M):
    raise SystemExit("OC1 audit: MT6781 ENABLE_DOE is not enabled")

if "unsigned int lv = CPU_LEVEL_0;" not in platform_c or \
        "return lv;" not in platform_c[
            platform_c.find("unsigned int _mt_cpufreq_get_cpu_level(void)") :]:
    raise SystemExit("OC1 audit: active CPU segment selector is not CPU_LEVEL_0")

for token, source in (
    ("CPU_DVFS_FREQ0_L_6781T 2200000", opp),
    ("CPU_DVFS_VOLT0_VPROC2_6781T 115625", opp),
    ("{ 2200, 105, 1, 1 },", pv),
    ("if (d->change_flag)", hybrid),
    ("d->doe_flag |= BIT(i);", hybrid),
    ("update_pvt_tbl_by_doe();", hybrid),
    ("idx_opp_ppm_limit", hybrid),
    ("if (j < p->idx_opp_ppm_limit)", hybrid),
    ("OFFS_IMAX_THERMAL_EN", hybrid),
    ("csram_write(OFFS_IMAX_THERMAL_EN, 1);", hybrid),
):
    if token not in source:
        raise SystemExit(f"OC1 audit: required OPP/DOE/protection path missing: {token}")

# Confirm the edited node remains enabled after writing and that the complete
# 16-row DOE B-table is present in the final source DTS.
dts_check = read(dts_path)
check_start, check_end = braced_region(
    dts_check, "dvfsp: dvfsp@0011bc00", "MT6781 DVFSP node"
)
check_node = dts_check[check_start:check_end]
if "change_flag = <1>;" not in check_node:
    raise SystemExit("OC1 audit: DOE change_flag did not persist as 1")
if not re.search(r"\bB-table\s*=\s*<\s*2200\s+105\s+1\s+1\b", check_node):
    raise SystemExit("OC1 audit: enabled DOE node does not start at 2200/105")

changed = set(
    subprocess.check_output(
        ["git", "-C", str(root), "diff", "--name-only"], text=True
    ).splitlines()
)
allowed = {
    dts_path,
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_opp_table.h",
    "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/"
    "mtk_cpufreq_opp_pv_table.h",
}
if changed != allowed:
    raise SystemExit(
        f"OC1 audit: unexpected changed source files: {sorted(changed)}"
    )

print("OC1 source audit passed: CPU6/CPU7 top OPP 2200 MHz / 1.15625 V.")
print("DOE change_flag=1: the complete 16-row DTB B-table is now consumed.")
print("Linux OPP, SSPM PVT and DTB DOE top rows are coordinated.")
print("SSPM/PPM thermal cap path and IMAX thermal state remain enabled.")
print("PMIC ceilings, thermal trips, watchdog and vendor firmware are unchanged.")
PY
