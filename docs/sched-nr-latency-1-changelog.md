# Fleux Scheduler NR1 — Change Log

- Built from the Fleux `lineage-24.0` source branch using the existing `fleur_defconfig`.
- Changes only `sched_nr_latency` in `kernel/sched/fair.c`: the initial value is fixed at 1.
- The `sched_proc_update_handler` update path also writes 1, so changing `sched_latency_ns` or `sched_min_granularity_ns` does not recalculate this threshold.
- The CFS code continues to use `sched_nr_latency` for its scheduling-period logic and related scheduler decisions.
- CPU/GPU/CCI frequency tables, voltages, DVFS policy, thermal limits, SSPM firmware and watchdog protections are not intentionally modified.
- `sched_nr_latency` is not a CPU migration control. Migration cost and load-balancing settings remain unchanged.
- This is a scheduler experiment, not a claim of lower input latency or higher game performance. Verify boot, responsiveness, scheduling behavior and sustained stability on the device.
