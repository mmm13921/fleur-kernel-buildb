# Android 11 / Fleur / Alucard test build

This build is intentionally isolated from the existing Fleux 4.19 workflows.

## Source

- Device tree: POCO M4 Pro 4G / Redmi Note 11S 4G (fleur)
- Vendor branch: `fleur-r-oss` (Android R / Android 11 vendor)
- Kernel source commit: `29295d3eeaa5290732b52b5800a360e86c04301e`
- Kernel Makefile version on this tree: `4.14.343-openela`

The installed stock kernel previously reported as `4.14.186-perf` is not the same source revision. This is therefore a compile/integration test build, not a verified drop-in replacement for that exact binary.

## Governor

Adds the legacy Alucard CPUFreq governor, adapted to the target tree's CPUFreq table API. Existing performance, powersave, userspace, ondemand, conservative, interactive and schedutil support is not intentionally removed or replaced. The existing default governor remains unchanged.

## Outputs

The workflow uploads:
- `Image.gz-dtb`
- `Fleur-Android11-Alucard-4.14.343-AnyKernel3.zip`
- `kernel.config`
- `alucard-source.patch`
- checksums and build manifest

Do not flash this experimental build over a working kernel until the source-version mismatch and boot compatibility have been checked on the device.
