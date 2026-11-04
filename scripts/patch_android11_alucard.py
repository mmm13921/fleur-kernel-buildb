#!/usr/bin/env python3
"""Apply the Alucard CPUFreq governor to the Fleur Android-R 4.14 source tree."""

from pathlib import Path
import re
import shutil
import sys


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"Alucard patch: {label}: expected one match, found {count}")
    return updated


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_android11_alucard.py <kernel-source>")
    root = Path(sys.argv[1]).resolve()
    if not (root / "Makefile").is_file():
        raise SystemExit(f"Not a kernel source tree: {root}")

    governor_src = Path(__file__).resolve().parents[1] / "patches/android11/cpufreq_alucard.c"
    governor_dst = root / "drivers/cpufreq/cpufreq_alucard.c"
    if not governor_src.is_file():
        raise SystemExit(f"Governor source missing: {governor_src}")
    shutil.copy2(governor_src, governor_dst)

    kconfig_path = root / "drivers/cpufreq/Kconfig"
    kconfig = kconfig_path.read_text()
    symbol = "config CPU_FREQ_GOV_ALUCARD"
    if symbol not in kconfig:
        marker = 'comment "CPU frequency scaling drivers"'
        if kconfig.count(marker) != 1:
            raise SystemExit("Alucard patch: CPUFreq Kconfig insertion point not unique")
        block = """config CPU_FREQ_GOV_ALUCARD
\tbool "'alucard' CPUFreq governor"
\tdepends on CPU_FREQ
\thelp
\t  Alucard is a load-based CPUFreq governor with configurable sampling,
\t  load thresholds and frequency ramp steps. It uses the active CPUFreq
\t  policy and its frequency table.

"""
        kconfig = kconfig.replace(marker, block + marker, 1)
        kconfig_path.write_text(kconfig)

    makefile_path = root / "drivers/cpufreq/Makefile"
    makefile = makefile_path.read_text()
    obj_line = "obj-$(CONFIG_CPU_FREQ_GOV_ALUCARD)\t+= cpufreq_alucard.o"
    if obj_line not in makefile:
        lines = makefile.splitlines(keepends=True)
        matches = [
            i for i, line in enumerate(lines)
            if line.strip().startswith("obj-$(CONFIG_CPU_FREQ_GOV_INTERACTIVE)")
            and "cpufreq_interactive.o" in line
        ]
        if len(matches) != 1:
            raise SystemExit("Alucard patch: Interactive Makefile entry not unique")
        lines.insert(matches[0] + 1, obj_line + "\n")
        makefile_path.write_text("".join(lines))
        makefile = "".join(lines)

    # This public R-OSS tree references a KernelSU Kconfig file that is absent
    # from the checked-out tree. KernelSU is not needed for this governor test.
    drivers_kconfig_path = root / "drivers/Kconfig"
    drivers_kconfig = drivers_kconfig_path.read_text()
    ksu_source = 'source "drivers/kernelsu/Kconfig"'
    if ksu_source in drivers_kconfig:
        if drivers_kconfig.count(ksu_source) != 1:
            raise SystemExit("Alucard patch: KernelSU Kconfig source line is not unique")
        drivers_kconfig = drivers_kconfig.replace(ksu_source + "\n", "", 1)
        drivers_kconfig_path.write_text(drivers_kconfig)

    drivers_makefile_path = root / "drivers/Makefile"
    drivers_makefile = drivers_makefile_path.read_text()
    drivers_makefile = drivers_makefile.replace(
        "obj-$(CONFIG_KSU) += kernelsu/\n", ""
    )
    drivers_makefile_path.write_text(drivers_makefile)

    # Keep KSM disabled in this test tree: memory.c has a reuse_ksm_page()
    # call but the source revision has no implementation. The call is guarded
    # by the CONFIG_KSM stub below, so the disabled feature remains inert.
    ksm_header_path = root / "include/linux/ksm.h"
    ksm_header = ksm_header_path.read_text()
    ksm_marker = "#else  /* !CONFIG_KSM */"
    if "reuse_ksm_page" not in ksm_header:
        if ksm_header.count(ksm_marker) != 1:
            raise SystemExit("Alucard patch: KSM disabled-branch insertion point not unique")
        ksm_stub = """#else  /* !CONFIG_KSM */

static inline bool reuse_ksm_page(struct page *page,
                                  struct vm_area_struct *vma,
                                  unsigned long address)
{
    return false;
}
"""
        ksm_header = ksm_header.replace(ksm_marker, ksm_stub, 1)
        ksm_header_path.write_text(ksm_header)

    # The R-OSS snapshot has three ext4_check_dir_entry() call sites with an
    # extra trailing NULL although the macro accepts seven arguments.
    ext4_namei_path = root / "fs/ext4/namei.c"
    ext4_namei = ext4_namei_path.read_text()
    ext4_fixes = (
        ("((char *)de) - base, NULL))", "((char *)de) - base))"),
        ("bh->b_size, 0, NULL) ||", "bh->b_size, 0) ||"),
        ("bh->b_size, offset, NULL) ||", "bh->b_size, offset) ||"),
    )
    for before, after in ext4_fixes:
        if before not in ext4_namei or ext4_namei.count(before) != 1:
            raise SystemExit(f"Alucard patch: expected one ext4 compatibility site: {before}")
        ext4_namei = ext4_namei.replace(before, after, 1)
    ext4_namei_path.write_text(ext4_namei)

    defconfig_path = root / "arch/arm64/configs/fleur_defconfig"
    defconfig = defconfig_path.read_text()
    defconfig = re.sub(r"(?m)^CONFIG_KSU=y\n", "# CONFIG_KSU is not set\n", defconfig)
    defconfig = defconfig.replace(
        'CONFIG_LOCALVERSION="-hiiragi.rev_2-KSU"',
        'CONFIG_LOCALVERSION="-android11-alucard"',
    )
    defconfig = re.sub(r"(?m)^CONFIG_KSM=.*$", "# CONFIG_KSM is not set", defconfig)
    if "# CONFIG_KSM is not set" not in defconfig:
        defconfig += "\n# CONFIG_KSM is not set\n"
    defconfig_path.write_text(defconfig)
    config_line = "CONFIG_CPU_FREQ_GOV_ALUCARD=y"
    if config_line not in defconfig:
        defconfig = replace_once(
            defconfig,
            r"(?m)^CONFIG_CPU_FREQ_GOV_INTERACTIVE=y$",
            "CONFIG_CPU_FREQ_GOV_INTERACTIVE=y\n" + config_line,
            "fleur_defconfig option insertion",
        )
        defconfig_path.write_text(defconfig)

    source = governor_dst.read_text()
    for stale in (
        "cputime64_t",
        "cpufreq_frequency_get_table",
        "cpufreq_frequency_table_target(cpu_policy, this_alucard_cpuinfo->freq_table",
    ):
        if stale in source:
            raise SystemExit(f"Alucard patch: unadapted legacy API remains: {stale}")
    if source.count("cpufreq_frequency_table_target(cpu_policy, tmp_freq,") != 2:
        raise SystemExit("Alucard patch: expected two adapted frequency-table lookups")
    if "CONFIG_CPU_FREQ_GOV_ALUCARD=y" not in defconfig:
        raise SystemExit("Alucard patch: defconfig does not enable Alucard")
    if "CONFIG_KSM=y" in defconfig:
        raise SystemExit("Alucard patch: KSM must stay disabled in this source snapshot")
    if "reuse_ksm_page" not in (root / "include/linux/ksm.h").read_text():
        raise SystemExit("Alucard patch: missing disabled-KSM compatibility stub")
    if any(before in (root / "fs/ext4/namei.c").read_text()
           for before, _ in ext4_fixes):
        raise SystemExit("Alucard patch: ext4 extra-argument mismatch remains")
    if obj_line not in makefile:
        raise SystemExit("Alucard patch: Makefile does not build Alucard")
    if symbol not in kconfig:
        raise SystemExit("Alucard patch: Kconfig symbol is missing")

    print("ALUCARD SOURCE PATCH PASSED")
    print("Added: drivers/cpufreq/cpufreq_alucard.c")
    print("Enabled: CONFIG_CPU_FREQ_GOV_ALUCARD=y")
    print("CPUFreq table API adapted to this 4.14 tree")


if __name__ == "__main__":
    main()
