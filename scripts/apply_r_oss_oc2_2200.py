#!/usr/bin/env python3
"""Apply CPU-only 2.2 GHz big-cluster OPP changes to Fleur Android R OSS 4.14.343.

The patch intentionally leaves little-cluster, CCI, GPU, PMIC hardware ceilings,
thermal policy, PPM, IMAX and SSPM firmware untouched.
"""
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1]).resolve()

DTS = "arch/arm64/boot/dts/mediatek/mt6781.dts"
PMIC = "arch/arm64/boot/dts/mediatek/mt6359p.dtsi"
OPP = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_table.h"
PVT = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_pv_table.h"
PLATFORM_H = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_platform.h"
PLATFORM_C = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_platform.c"
HYBRID = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c"
MAIN = "drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_main.c"
EEM = "drivers/misc/mediatek/base/power/eem_v2/mt6781/inc/mtk_eem_config.h"
DEFCONFIG = "arch/arm64/configs/fleur_defconfig"

def fail(message):
    raise SystemExit("R-OSS OC2 patch error: " + message)

def read(path):
    p = ROOT / path
    if not p.is_file():
        fail("required file missing: " + path)
    return p.read_text()

def write(path, text):
    (ROOT / path).write_text(text)

def replace_once(text, old, new, label):
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        fail(f"{label}: expected one old anchor, found {count}")
    return text.replace(old, new, 1)

def block_span(text, marker, label):
    start = text.find(marker)
    if start < 0:
        fail(label + " block not found")
    brace = text.find("{", start)
    if brace < 0:
        fail(label + " opening brace not found")
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
    fail(label + " block is unterminated")

def edit_block(text, marker, label, transform):
    start, end = block_span(text, marker, label)
    return text[:start] + transform(text[start:end]) + text[end:]

def set_macro(text, name, old, new, label):
    pattern = re.compile(
        r"(?m)^([ \t]*#define[ \t]+" + re.escape(name) +
        r"[ \t]+)(\S+)([^\n]*)$"
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        fail(label + f": expected exactly one macro, found {len(matches)}")
    m = matches[0]
    if m.group(2) == str(new):
        return text
    if m.group(2) != str(old):
        fail(label + f": found {m.group(2)}, expected {old}")
    return text[:m.start()] + m.group(1) + str(new) + m.group(3) + text[m.end():]

def set_cpu_clock(dts, marker, label):
    def transform(body):
        return replace_once(
            body,
            "clock-frequency = <2050000000>;",
            "clock-frequency = <2200000000>;",
            label + " clock-frequency",
        )
    return edit_block(dts, marker, label, transform)

def set_pvt_row(text, table_name, old, new):
    start, end = block_span(text, table_name, table_name)
    body = text[start:end]
    lmark = body.find("/* L */")
    cci = body.find("/* CCI */", lmark + 1)
    if lmark < 0 or cci < 0:
        fail(table_name + ": cannot isolate big-cluster PVT rows")
    head = body[:lmark + len("/* L */")]
    segment = body[lmark + len("/* L */"):cci]
    row = re.compile(
        r"(?m)^([ \t]*)\{\s*" +
        r"\s*,\s*".join(map(str, old)) +
        r"\s*\},"
    )
    m = row.search(segment)
    if m:
        replacement = m.group(1) + "{ " + ", ".join(map(str, new)) + " },"
        segment = segment[:m.start()] + replacement + segment[m.end():]
    elif not re.search(
        r"(?m)^[ \t]*\{\s*" + r"\s*,\s*".join(map(str, new)) + r"\s*\},",
        segment,
    ):
        fail(table_name + ": original big-cluster top PVT row not found")
    return text[:start] + head + segment + body[cci:] + text[end:]

# 1) Device tree: big CPUs 6/7 and the MediaTek DVFSP table.
dts = read(DTS)
dts = set_cpu_clock(dts, "cpu6: cpu@102", "CPU6")
dts = set_cpu_clock(dts, "cpu7: cpu@103", "CPU7")

def update_dvfsp(body):
    body = replace_once(
        body, "change_flag = <0>;", "change_flag = <1>;",
        "DVFSP DOE change_flag",
    )
    m = re.search(r"\bB-table\s*=\s*<([^>]*)>", body, re.S)
    if not m:
        fail("DVFSP B-table is missing")
    values = [int(v, 0) for v in re.findall(r"0[xX][0-9a-fA-F]+|\d+", m.group(1))]
    if len(values) != 64:
        fail(f"DVFSP B-table has {len(values)} cells, expected 64")
    rows = [tuple(values[i:i + 4]) for i in range(0, 64, 4)]
    if rows[0] == (2050, 99, 1, 1):
        first = re.compile(r"(?m)^([ \t]*)2050[ \t]+99[ \t]+1[ \t]+1\b")
        segment = body[m.start(1):m.end(1)]
        segment, count = first.subn(r"\g<1>2200 105 1 1", segment, count=1)
        if count != 1:
            fail("DVFSP big OPP row replacement failed")
        body = body[:m.start(1)] + segment + body[m.end(1):]
    elif rows[0] != (2200, 105, 1, 1):
        fail(f"DVFSP B-table top row is {rows[0]}, expected 2050/99 or already 2200/105")
    m = re.search(r"\bB-table\s*=\s*<([^>]*)>", body, re.S)
    values = [int(v, 0) for v in re.findall(r"0[xX][0-9a-fA-F]+|\d+", m.group(1))]
    rows = [tuple(values[i:i + 4]) for i in range(0, 64, 4)]
    if rows[0] != (2200, 105, 1, 1):
        fail("DVFSP B-table top row did not become 2200/105")
    if any(a[0] <= b[0] for a, b in zip(rows, rows[1:])):
        fail("DVFSP B-table frequencies are not strictly descending")
    return body

dts = edit_block(dts, "dvfsp: dvfsp@0011bc00", "DVFSP", update_dvfsp)

# 2) Linux CPU OPP macros. Keep little-cluster and CCI OPPs stock.
opp = read(OPP)
opp = set_macro(opp, "CPU_DVFS_FREQ0_L_6781T", "2050000", "2200000", "active big-cluster frequency")
opp = set_macro(opp, "CPU_DVFS_VOLT0_VPROC2_6781T", "111875", "115625", "active big-cluster VPROC")
opp = set_macro(opp, "CPU_DVFS_FREQ0_L_6781", "2002000", "2200000", "fallback big-cluster frequency")
opp = set_macro(opp, "CPU_DVFS_VOLT0_VPROC2_6781", "110000", "115625", "fallback big-cluster VPROC")

# 3) SSPM PVT tables, both silicon/project variants.
pvt = read(PVT)
pvt = set_pvt_row(pvt, "OPP_6781T_Tbl", (2050, 99, 1, 1), (2200, 105, 1, 1))
pvt = set_pvt_row(pvt, "OPP_6781_Tbl", (2002, 96, 1, 1), (2200, 105, 1, 1))
if pvt.count("{ 2200, 105, 1, 1 },") < 2:
    fail("both SSPM PVT big-cluster tables must contain 2200/105")

# 4) Voltage software ceilings and EEM big-cluster calibration.
platform_h = read(PLATFORM_H)
platform_h = set_macro(platform_h, "MAX_VPROC_VOLT", "100000", "115625", "VPROC software ceiling")
platform_h = set_macro(platform_h, "MAX_VSRAM_VOLT", "100000", "125625", "VSRAM software ceiling")

eem = read(EEM)
eem = set_macro(eem, "B_FREQ_BASE", "2050000", "2200000", "EEM big-cluster base frequency")
eem = set_macro(eem, "VMAX_VAL_B", "(0x73)", "(0x79)", "EEM B maximum voltage code")
eem = set_macro(eem, "VMAX_VAL_BH", "(0x73)", "(0x79)", "EEM B_HI maximum voltage code")

# 5) Verify that the runtime DVFS, PPM/IMAX and thermal safety paths remain.
pmic = read(PMIC)
def regulator_max(name):
    match = re.search(
        r'regulator-name\s*=\s*"' + re.escape(name) +
        r'";[\s\S]*?regulator-max-microvolt\s*=\s*<(\d+)>;',
        pmic,
    )
    if not match:
        fail("PMIC regulator declaration missing: " + name)
    return int(match.group(1))

if regulator_max("vproc2") < 1156250:
    fail("PMIC VPROC2 ceiling is below 1.15625 V")
if regulator_max("vsram_proc2") < 1256250:
    fail("PMIC VSRAM_PROC2 ceiling is below 1.25625 V")

platform_c = read(PLATFORM_C)
if "unsigned int lv = CPU_LEVEL_0;" not in platform_c:
    fail("active CPU DVFS level is not CPU_LEVEL_0")

hybrid = read(HYBRID)
for token in (
    "if (d->change_flag)",
    "d->doe_flag |= BIT(i);",
    "update_pvt_tbl_by_doe();",
    "idx_opp_ppm_limit",
    "OFFS_IMAX_THERMAL_EN",
    "csram_write(OFFS_IMAX_THERMAL_EN, 1);",
):
    if token not in hybrid:
        fail("vendor DVFS/thermal protection path missing: " + token)

main = read(MAIN)
if "volt = MIN(volt, MAX_VPROC_VOLT);" not in main:
    fail("VPROC software voltage clamp is missing")

config = read(DEFCONFIG)
for token in (
    "CONFIG_MTK_TINYSYS_SSPM_SUPPORT=y",
    "CONFIG_THERMAL=y",
    "CONFIG_CPU_THERMAL=y",
):
    if token not in config:
        fail("required vendor thermal/SSPM config missing: " + token)

# Confirm exact post-patch values before writing anything.
if not re.search(r"(?m)^#define\s+CPU_DVFS_FREQ0_L_6781T\s+2200000\b", opp):
    fail("active big-cluster OPP macro validation failed")
if not re.search(r"(?m)^#define\s+CPU_DVFS_VOLT0_VPROC2_6781T\s+115625\b", opp):
    fail("active big-cluster voltage macro validation failed")
if not re.search(r"(?m)^#define\s+B_FREQ_BASE\s+2200000\b", eem):
    fail("EEM big-cluster frequency validation failed")
if not re.search(r"(?m)^#define\s+VMAX_VAL_B\s+\(0x79\)", eem):
    fail("EEM B voltage code validation failed")
if not re.search(r"(?m)^#define\s+VMAX_VAL_BH\s+\(0x79\)", eem):
    fail("EEM B_HI voltage code validation failed")

for path, data in (
    (DTS, dts),
    (OPP, opp),
    (PVT, pvt),
    (PLATFORM_H, platform_h),
    (EEM, eem),
):
    write(path, data)

print("R-OSS OC2 SOURCE AUDIT PASSED")
print("CPU6/CPU7 big-cluster maximum: 2200 MHz")
print("Big-cluster VPROC target: 1.15625 V; VSRAM software ceiling: 1.25625 V")
print("Verified: Linux OPP + DTB DOE + SSPM PVT + EEM")
print("Unchanged: little cluster, CCI, GPU, PMIC hardware ceilings, thermal trips, PPM/IMAX and SSPM firmware")
