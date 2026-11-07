# Fleux Scheduler NR1 — Change Log

- Build source: Fleux tag `v5`, pinned to commit `caf4167e60fb81df4d1ac66e83c4e28a0396a01b` (Linux 4.19.325).
- Device configuration: the source tree's existing `fleur_defconfig`.
- Changes only the CFS `sched_nr_latency` threshold in `kernel/sched/fair.c`: its initial value is fixed at 1.
- The `sched_proc_update_handler` update path also writes 1, so changing `sched_latency_ns` or `sched_min_granularity_ns` does not recalculate this threshold.
- The CFS `__sched_period()` and `sched_slice()` code paths remain in place and continue to use this threshold.
- The build explicitly produces `Image.gz-dtb` for the AnyKernel3 package.
- CPU/GPU/CCI frequency tables, voltages, DVFS policy, thermal limits, SSPM firmware and watchdog protections are not intentionally modified.
- This is a scheduler experiment, not a claim of lower input latency or higher game performance. Verify boot, responsiveness, scheduling behavior and sustained stability on the device.
