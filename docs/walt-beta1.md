# Fleux WALT Beta1

This experimental build is based on the Fleux 4.19.325 MT6781 kernel and
retains the OC2 coordinated 2.2 GHz big-cluster OPP profile.

## Scheduler and CPUFreq

- WALT window-based task demand tracking is enabled.
- The default WALT history window is 20 ms.
- WALT task demand feeds the scheduler task-utilization path.
- WALT runnable task demand is aggregated for CFS CPU utilization.
- A CPUFreq governor named walt is registered.
- The walt governor reuses schedutil frequency-selection callbacks; it is
  not the separate Qualcomm waltgov implementation.
- CPUFreq policy limits and the existing platform DVFS, SSPM, thermal and
  watchdog paths remain in place.

## Experimental status

This is a port from an MT6781 Linux 4.19 reference tree. It must pass the
GitHub Actions build and image audit before it is considered flashable.
The build output includes the final kernel config and source patch for review.
A successful compile does not establish runtime stability; test boot, governor
selection, CPU-frequency response and suspend/resume before daily use.

## Runtime verification

After boot, verify:

- /sys/devices/system/cpu/cpufreq/policy0/scaling_available_governors
  includes walt (policy numbers may differ by device configuration).
- The active policy reports walt as scaling_governor.
- /proc/sys/kernel and scheduler debug output show no WALT initialization
  warnings or lockdep failures.
