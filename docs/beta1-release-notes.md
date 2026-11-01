# Beta 1 — experimental 2.1 GHz

**Target:** Redmi Note 11S 4G (fleur), MT6781  
**Big cluster:** 2,100 MHz maximum on CPU6/CPU7  
**Voltage policy:** unchanged stock CPU_LEVEL_0 top OPP (1,118,750 µV in the source Device Tree; VPROC code 99 retained)  
**Little cluster / GPU / CCI:** unchanged  
**Thermal and emergency protections:** unchanged

## Important limitations

- This is an experimental source-level OPP change, not a validated overclock.
- The Linux kernel sends the CPU DVFS OPP table to the MediaTek SSPM path. The exact device firmware/PLL acceptance and sustained stability at 2.1 GHz have not been verified on a physical handset.
- Keeping the stock voltage does not guarantee that an individual silicon sample can sustain 2.1 GHz. Instability, hangs, boot failure, or resets are possible.
- The release contains a raw `Image.gz-dtb`, kernel configuration, build manifest, and exact source patch. It is **not** an AnyKernel3/Recovery flashable ZIP and should not be flashed as a ZIP.
- ROM/vendor/boot-image compatibility has not been qualified. Keep a known-good boot image and a recovery path before any device testing.

No thermal limit, emergency shutdown, PMIC safeguard, or watchdog protection is disabled or bypassed in this build.
