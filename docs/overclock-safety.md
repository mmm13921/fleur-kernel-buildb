# MT6781 OPP / DVFS source audit

This note records source facts used to constrain the initial builder. It is not a hardware qualification report and must not be treated as proof that an overclock is stable.

## Verified in the Fleux source ref

Source: https://gitlab.com/daliboss/fleux/-/tree/lineage-24.0

- `arch/arm64/boot/dts/mediatek/mt6781.dts` defines the big-cluster `cluster1_opp` table. Its highest declared point is 2,050,000,000 Hz at 1,118,750 µV.
- The same Device Tree describes CPU6 and CPU7 as Cortex-A75 compatible and references `cluster1_opp`.
- `drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_table.h` contains MT6781/MT6781T frequency and VPROC voltage macros. The SKU-specific table selection must be understood before editing values.
- `drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c` includes SSPM IPI code paths and sends `IPI_DVFS_INIT_PTBL` via the SSPM V2 path when configured.

## Consequences

1. An edit to only the Linux-side OPP list is not sufficient evidence that the running firmware-side DVFS table accepts that operating point.
2. The existing 2.05 GHz / 1.11875 V point is a source declaration, not a statement that every retail device or silicon bin can sustain any higher point.
3. Do not disable thermal shutdown, emergency protection, PMIC safety limits or watchdog protections to force a frequency.
4. Keep the first build unmodified. A future experiment must be expressed as a source diff, built separately, and audited against the corresponding SSPM/MCUPM firmware protocol and PLL programming before it is considered for device testing.
5. This builder currently does not expose tools that change OPP tables, voltage values, PLL registers, thermal limits or firmware binaries.

## Files to inspect

- `arch/arm64/boot/dts/mediatek/mt6781.dts`
- `drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_table.h`
- `drivers/misc/mediatek/base/power/cpufreq_v1/src/mach/mt6781/mtk_cpufreq_opp_pv_table.h`
- `drivers/misc/mediatek/base/power/cpufreq_v1/src/mtk_cpufreq_hybrid.c`
- `arch/arm64/configs/fleur_defconfig`

The source project's own README documents Android LLVM/Clang `r563880c`, cross-compilers for AArch64/ARM32, and the expected output `out/arch/arm64/boot/Image.gz-dtb`.
