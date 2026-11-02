# Fleux Beta 2 — 2.2 GHz AnyKernel3 (experimental)

**Target:** Redmi Note 11S 4G / fleur / MT6781  
**Big cluster:** CPU6 and CPU7, maximum declared OPP 2,200 MHz  
**Top VPROC OPP:** 1.15625 V (1,156,250 µV), 37.5 mV above the source stock top OPP of 1.11875 V  
**PMIC code:** 105, calculated from VPROC base 50000 and step 625 (10-µV source units)  
**Unchanged:** Little-cluster, CCI and GPU OPPs; thermal trip points; emergency shutdown; PMIC regulator ceilings; watchdog protections.

## What Beta 2 changes

The same CPU_LEVEL_0 / MT6781T top operating point is updated across the cooperating source paths:

1. arch/arm64/boot/dts/mediatek/mt6781.dts: big-cluster OPP frequency/voltage, CPU6/CPU7 clock-frequency declarations, and DOE B-table.
2. mtk_cpufreq_opp_table.h: Linux CPU_LEVEL_0 frequency and VPROC macros.
3. mtk_cpufreq_opp_pv_table.h: OPP_6781T_Tbl big-cluster row copied into the SSPM shared-memory/PVT table.

The build checks that fleur_defconfig enables SSPM V2, that the active CPU segment selector returns CPU_LEVEL_0, that the VPROC code maps to the requested voltage, and that the requested top point is within the source-declared PMIC regulator ceilings.

## Important limitations

- This is an experimental source-level OPP change, not a hardware-qualified overclock. The 2.2-GHz point may be rejected or capped by vendor firmware, may not train on all silicon samples, or may be unstable.
- The vendor SSPM firmware binary is not modified. Linux supplies the updated PVT table through the existing hybrid DVFS interface; this does not prove that firmware will accept or sustain the new point.
- Increased frequency and voltage raise power and heat and can cause instability, resets, shortened component life, or boot failure. Keep a known-good boot image and a recovery path.
- No thermal limit, emergency shutdown, PMIC safeguard, watchdog, or firmware safety mechanism is disabled or bypassed.
- The ZIP is packaged with the upstream AnyKernel3 installer framework and includes Image.gz-dtb, installer tools and license, a source patch, and build manifest.
- The installer device check is restricted to fleur. ROM/vendor/boot-image combinations have not been qualified.

The declared 2.2-GHz maximum is an OPP-table request, not a guarantee that the running handset will report or sustain 2.2 GHz.