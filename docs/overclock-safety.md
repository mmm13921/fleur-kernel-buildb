# MT6781 OPP / DVFS source audit

This note records source facts used to constrain the fleur kernel builder. It is not a hardware qualification report.

## Source and active path

Source: https://gitlab.com/daliboss/fleux/-/tree/lineage-24.0

- fleur_defconfig enables CONFIG_MTK_TINYSYS_SSPM_SUPPORT=y and CONFIG_MTK_TINYSYS_SSPM_V2=y.
- mtk_cpufreq_platform.c selects CPU_LEVEL_0 in _mt_cpufreq_get_cpu_level() for this source branch.
- mtk_cpufreq_hybrid.c constructs the PVT table from mtk_cpufreq_opp_pv_table.h and sends the initialized table through the existing SSPM/MCUPM DVFS setup path.
- mt6781.dts declares the big-cluster cluster1_opp table, CPU6/CPU7 clock-frequency values, and DOE B-table.
- mtk_cpufreq_opp_table.h defines CPU_LEVEL_0/MT6781T Linux OPP frequency and VPROC values.
- mtk_cpufreq_opp_pv_table.h defines the MT6781T PVT entries including frequency, Vproc code, post-divider and clock-divider.

## Beta 2 top OPP

The Beta 2 patch keeps the 16-entry OPP layout and changes only the top CPU_LEVEL_0 big-cluster point:

- Frequency: 2,050 MHz to 2,200 MHz.
- VPROC: 1,118,750 µV to 1,156,250 µV (+37,500 µV).
- PMIC voltage code: 99 to 105, where VPROC_BASE=50000 and VPROC_STEP=625.
- Matching cluster1_opp, CPU6/CPU7 clock-frequency, DOE B-table, Linux OPP macro and SSPM PVT row are checked by the build patch.

The source MT6359P Device Tree declares a VPROC2 upper bound of 1,193,750 µV and a VSRAM2 upper bound of 1,293,750 µV. The requested top VPROC point is below those regulator bounds. These are regulator ceilings, not a guarantee of safe silicon operation.

## Limitations

1. The Linux build can submit an updated PVT table through the configured SSPM interface, but the vendor SSPM firmware binary is closed and is not modified by this builder.
2. The PLL programming code computes DDS values from requested frequencies; that does not establish vendor PLL qualification or guarantee 2.2-GHz stability.
3. The source AP-side set_cur_volt helper is not used to rewrite the SSPM PVT table in this configured path; its fallback/debug bounds are deliberately left unchanged.
4. Thermal trip points, emergency shutdowns, PMIC regulator limits, watchdogs and firmware safety protections are not modified.
5. Every Beta 2 build is experimental and must be tested with a known-good boot image and recovery path.

## Files involved

- arch/arm64/boot/dts/mediatek/mt6781.dts
- arch/arm64/boot/dts/mediatek/mt6359p.dtsi (read-only regulator-ceiling verification)
- arch/arm64/configs/fleur_defconfig (read-only SSPM V2 verification)
- drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_platform.c (read-only CPU_LEVEL_0 verification)
- drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_platform.h (read-only VPROC conversion verification)
- drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_table.h
- drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_pv_table.h
- drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c

The kernel image output is Image.gz-dtb. The Beta 2 release workflow wraps it using the pinned upstream AnyKernel3 installer framework.