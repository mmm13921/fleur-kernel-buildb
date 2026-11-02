#!/usr/bin/env python3
"""Integrate the MT6781 Linux 4.19 WALT implementation into Fleux 4.19."""

from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if ROOT is None or not (ROOT / "Makefile").is_file():
    raise SystemExit("Usage: apply_walt.py <kernel-source-directory>")

def read(path):
    p = ROOT / path
    if not p.is_file():
        raise SystemExit(f"WALT: required source file is missing: {path}")
    return p.read_text()

def write(path, data):
    (ROOT / path).write_text(data)

def replace_once(data, old, new, label):
    n = data.count(old)
    if n != 1:
        raise SystemExit(f"WALT: {label}: expected exactly one anchor, found {n}")
    return data.replace(old, new, 1)

def insert_before_once(data, anchor, addition, label):
    return replace_once(data, anchor, addition + anchor, label)

def struct_close(data, anchor, label):
    start = data.find(anchor)
    if start < 0:
        raise SystemExit(f"WALT: {label}: structure not found")
    opening = data.find("{", start)
    if opening < 0:
        raise SystemExit(f"WALT: {label}: opening brace not found")
    depth = 0
    state = "code"
    i = opening
    while i < len(data):
        ch = data[i]
        nxt = data[i + 1] if i + 1 < len(data) else ""
        if state == "code":
            if ch == "/" and nxt == "*":
                state = "block"
                i += 1
            elif ch == "/" and nxt == "/":
                state = "line"
                i += 1
            elif ch == '"':
                state = "string"
            elif ch == "'":
                state = "char"
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        elif state == "block":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 1
        elif state == "line":
            if ch == "\n":
                state = "code"
        elif state in ("string", "char"):
            if ch == "\\\\":
                i += 1
            elif (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                state = "code"
        i += 1
    raise SystemExit(f"WALT: {label}: unterminated structure")

def replace_function(data, signature, replacement, label):
    start = data.find(signature)
    if start < 0:
        raise SystemExit(f"WALT: {label}: function not found")
    close = struct_close(data, signature, label)
    opening = data.find("{", start)
    return data[:start] + replacement + data[close + 1:]

def add_once(data, marker, addition, label):
    if addition.strip() in data:
        return data
    return insert_before_once(data, marker, addition, label)

# Use a pinned, device-family 4.19 WALT reference, then remove the reference
# tree's OPLUS-only hooks and tracepoints that are not part of Fleux.
walt_src = read("patches/walt/upstream-walt.c")
walt_hdr = read("patches/walt/upstream-walt.h")

walt_src = walt_src.replace('#include <trace/events/sched.h>\n', '')
walt_src = walt_src.replace(
    '#ifdef OPLUS_FEATURE_SCHED_ASSIST\n'
    '#include <linux/sched.h>\n'
    '#include <linux/sched_assist/sched_assist_common.h>\n'
    '#endif /* OPLUS_FEATURE_SCHED_ASSIST */\n', ''
)
walt_src = re.sub(
    r'#if defined\(OPLUS_FEATURE_SCHED_ASSIST\) && defined\(CONFIG_OPLUS_FEATURE_SCHED_SPREAD\).*?#endif\s*',
    '', walt_src, flags=re.S
)
walt_src = re.sub(
    r'#if defined\(OPLUS_FEATURE_SCHED_ASSIST\) && defined\(CONFIG_SCHED_WALT\)\s*'
    r'p->last_wake_ts = wallclock;\s*#endif[^\n]*\n', '', walt_src
)
walt_src = re.sub(
    r'(?m)^\s*trace_walt_[A-Za-z0-9_]+\([^;]*\);\s*\n', '', walt_src
)
walt_src = walt_src.replace(
    'extern unsigned long capacity_curr_of(int cpu);\n', ''
)
walt_src = replace_once(
    walt_src,
    'static u64 scale_exec_time(u64 delta, struct rq *rq)\n'
    '{\n'
    '\tunsigned long capcurr = capacity_curr_of(cpu_of(rq));\n'
    '\n'
    '\treturn (delta * capcurr) >> SCHED_CAPACITY_SHIFT;\n'
    '}',
    'static u64 scale_exec_time(u64 delta, struct rq *rq)\n'
    '{\n'
    '\tint cpu = cpu_of(rq);\n'
    '\tunsigned long capcurr = capacity_orig_of(cpu);\n'
    '\n'
    '#ifdef arch_scale_freq_capacity\n'
    '\tcapcurr = capcurr * arch_scale_freq_capacity(cpu) >> SCHED_CAPACITY_SHIFT;\n'
    '#endif\n'
    '\treturn (delta * capcurr) >> SCHED_CAPACITY_SHIFT;\n'
    '}',
    "replace unavailable MediaTek capacity_curr_of() with scheduler capacity"
)
if "OPLUS_FEATURE" in walt_src or "trace_walt_" in walt_src or "capacity_curr_of" in walt_src:
    raise SystemExit("WALT: upstream scheduler file still contains vendor-only dependencies")
if "p->last_wake_ts" in walt_src or "p->ld_flag" in walt_src:
    raise SystemExit("WALT: vendor-only task fields remain after sanitization")

# Install the WALT implementation in kernel/sched.
sched_dir = ROOT / "kernel/sched"
if (sched_dir / "walt.c").exists() or (sched_dir / "walt.h").exists():
    raise SystemExit("WALT: target already has walt.c/walt.h; refusing to overwrite")
write("kernel/sched/walt.c", walt_src)
write("kernel/sched/walt.h", walt_hdr)

# Add WALT's per-task history and event identifiers to the public task header.
p = "include/linux/sched.h"
s = read(p)
event_enum = (
    "#ifdef CONFIG_SCHED_WALT\n"
    "enum task_event {\n"
    "\tPUT_PREV_TASK = 0,\n"
    "\tPICK_NEXT_TASK = 1,\n"
    "\tTASK_WAKE = 2,\n"
    "\tTASK_MIGRATE = 3,\n"
    "\tTASK_UPDATE = 4,\n"
    "\tIRQ_UPDATE = 5,\n"
    "};\n"
    "#endif /* CONFIG_SCHED_WALT */\n\n"
)
s = add_once(s, "/* Task command name length: */", event_enum, "task event enum")
ravg_struct = (
    "#ifdef CONFIG_SCHED_WALT\n"
    "#define RAVG_HIST_SIZE_MAX 5\n"
    "struct ravg {\n"
    "\tu64 mark_start;\n"
    "\tu32 sum, demand;\n"
    "\tu32 sum_history[RAVG_HIST_SIZE_MAX];\n"
    "\tu32 curr_window, prev_window;\n"
    "\tu16 active_windows;\n"
    "};\n"
    "#endif /* CONFIG_SCHED_WALT */\n\n"
)
s = insert_before_once(s, "struct task_struct {", ravg_struct, "task ravg definition")
s = replace_once(
    s,
    "\tstruct sched_rt_entity\t\trt;\n",
    "\tstruct sched_rt_entity\t\trt;\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\tstruct ravg ravg;\n"
    "\tu32 init_load_pct;\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "task_struct WALT fields"
)
write(p, s)

# Add the window anchor to each per-CPU runqueue.
p = "kernel/sched/sched.h"
s = read(p)
end = struct_close(s, "struct rq {", "struct rq")
s = s[:end] + (
    "\n#ifdef CONFIG_SCHED_WALT\n"
    "\tu64 window_start;\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
) + s[end:]
s = replace_once(
    s,
    "bool uclamp_boosted(struct task_struct *p);\n",
    "bool uclamp_boosted(struct task_struct *p);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "extern unsigned int walt_ravg_window;\n"
    "extern bool walt_disabled;\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "WALT scheduler declarations"
)

# Feed WALT runnable demand into schedutil's per-CPU CFS utilization input.
s = replace_function(
    s,
    "static inline unsigned long cpu_util_cfs(struct rq *rq)",
    "static inline unsigned long cpu_util_cfs(struct rq *rq)\n"
    "{\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\tif (!READ_ONCE(walt_disabled)) {\n"
    "\t\tstruct task_struct *p;\n"
    "\t\tunsigned long util = 0;\n"
    "\t\tunsigned int divisor = READ_ONCE(walt_ravg_window) >> SCHED_CAPACITY_SHIFT;\n"
    "\n"
    "\t\tif (divisor) {\n"
    "\t\t\tlist_for_each_entry(p, &rq->cfs_tasks, se.group_node) {\n"
    "\t\t\t\tutil += READ_ONCE(p->ravg.demand) / divisor;\n"
    "\t\t\t\tif (util >= SCHED_CAPACITY_SCALE)\n"
    "\t\t\t\t\treturn SCHED_CAPACITY_SCALE;\n"
    "\t\t\t}\n"
    "\t\t\treturn util;\n"
    "\t\t}\n"
    "\t}\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\tunsigned long util = READ_ONCE(rq->cfs.avg.util_avg);\n"
    "\n"
    "\tif (sched_feat(UTIL_EST))\n"
    "\t\tutil = max_t(unsigned long, util,\n"
    "\t\t\t     READ_ONCE(rq->cfs.avg.util_est.enqueued));\n"
    "\n"
    "\treturn util;\n"
    "}",
    "WALT cpu_util_cfs"
)
write(p, s)

# Enable WALT task utilization for placement and scheduler decisions.
p = "kernel/sched/fair.c"
s = read(p)
s = replace_function(
    s,
    "static inline unsigned long task_util(struct task_struct *p)",
    "static inline unsigned long task_util(struct task_struct *p)\n"
    "{\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\tif (!READ_ONCE(walt_disabled)) {\n"
    "\t\tunsigned int divisor = READ_ONCE(walt_ravg_window) >> SCHED_CAPACITY_SHIFT;\n"
    "\t\tif (divisor)\n"
    "\t\t\treturn min_t(unsigned long,\n"
    "\t\t\t\t     READ_ONCE(p->ravg.demand) / divisor,\n"
    "\t\t\t\t     SCHED_CAPACITY_SCALE);\n"
    "\t}\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\treturn READ_ONCE(p->se.avg.util_avg);\n"
    "}",
    "WALT task_util"
)
s = replace_function(
    s,
    "unsigned long task_util_est(struct task_struct *p)",
    "unsigned long task_util_est(struct task_struct *p)\n"
    "{\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\tif (!READ_ONCE(walt_disabled))\n"
    "\t\treturn task_util(p);\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\treturn max(task_util(p), _task_util_est(p));\n"
    "}",
    "WALT task_util_est"
)
write(p, s)

# Add scheduler event accounting. WALT state updates are done with the rq lock held.
p = "kernel/sched/core.c"
s = read(p)
s = insert_before_once(
    s,
    "DEFINE_PER_CPU_SHARED_ALIGNED(struct rq, runqueues);",
    "#ifdef CONFIG_SCHED_WALT\n"
    "static inline void walt_try_to_wake_up(struct task_struct *p)\n"
    "{\n"
    "\tstruct rq *rq = cpu_rq(task_cpu(p));\n"
    "\tstruct rq_flags rf;\n"
    "\tu64 wallclock;\n"
    "\n"
    "\trq_lock_irqsave(rq, &rf);\n"
    "\twallclock = walt_ktime_clock();\n"
    "\twalt_update_task_ravg(rq->curr, rq, TASK_UPDATE, wallclock, 0);\n"
    "\twalt_update_task_ravg(p, rq, TASK_WAKE, wallclock, 0);\n"
    "\trq_unlock_irqrestore(rq, &rf);\n"
    "}\n"
    "#endif /* CONFIG_SCHED_WALT */\n\n",
    "WALT wake accounting helper"
)
s = insert_before_once(s, '#include "pelt.h"\n',
    '#ifdef CONFIG_SCHED_WALT\n#include "walt.h"\n#endif\n',
    "WALT core header include")
s = replace_once(
    s,
    "\tsmp_cond_load_acquire(&p->on_cpu, !VAL);\n",
    "\tsmp_cond_load_acquire(&p->on_cpu, !VAL);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\twalt_try_to_wake_up(p);\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "WALT task wake hook"
)

# Initialize new tasks and seed their first WALT history window.
fn = "void wake_up_new_task(struct task_struct *p)"
def patch_new_task(body):
    body = replace_once(
        body,
        "\trq = __task_rq_lock(p, &rf);\n\tupdate_rq_clock(rq);\n",
        "\trq = __task_rq_lock(p, &rf);\n"
        "#ifdef CONFIG_SCHED_WALT\n"
        "\twalt_init_new_task_load(p);\n"
        "#endif /* CONFIG_SCHED_WALT */\n"
        "\tupdate_rq_clock(rq);\n",
        "new-task WALT initialization"
    )
    body = replace_once(
        body,
        "\tpost_init_entity_util_avg(&p->se);\n",
        "\tpost_init_entity_util_avg(&p->se);\n"
        "#ifdef CONFIG_SCHED_WALT\n"
        "\twalt_mark_task_starting(p);\n"
        "#endif /* CONFIG_SCHED_WALT */\n",
        "new-task WALT start marker"
    )
    return body
# Work on the function block without touching the rest of core.c.
start = s.find(fn)
if start < 0:
    raise SystemExit("WALT: wake_up_new_task() not found")
close = struct_close(s, fn, "wake_up_new_task")
body = s[start:close + 1]
body = patch_new_task(body)
s = s[:start] + body + s[close + 1:]

# Add the WALT per-window update to scheduler_tick().
fn = "void scheduler_tick(void)"
start = s.find(fn)
if start < 0:
    raise SystemExit("WALT: scheduler_tick() not found")
close = struct_close(s, fn, "scheduler_tick")
body = s[start:close + 1]
body = replace_once(
    body,
    "\trq_lock(rq, &rf);\n\n\tupdate_rq_clock(rq);",
    "\trq_lock(rq, &rf);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\twalt_set_window_start(rq, &rf);\n"
    "\twalt_update_task_ravg(rq->curr, rq, TASK_UPDATE, walt_ktime_clock(), 0);\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\tupdate_rq_clock(rq);",
    "scheduler tick WALT update"
)
s = s[:start] + body + s[close + 1:]

# Account the previous/next tasks at every context switch.
fn = "static void __sched notrace __schedule(bool preempt)"
start = s.find(fn)
if start < 0:
    raise SystemExit("WALT: __schedule() not found")
close = struct_close(s, fn, "__schedule")
body = s[start:close + 1]
body = replace_once(
    body,
    "\tint cpu;\n",
    "\tint cpu;\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\tu64 wallclock;\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "__schedule WALT clock declaration"
)
body = replace_once(
    body,
    "\tupdate_rq_clock(rq);\n",
    "\tupdate_rq_clock(rq);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\twallclock = walt_ktime_clock();\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "__schedule WALT time capture"
)
body = replace_once(
    body,
    "\tif (likely(prev != next)) {\n\t\trq->nr_switches++;",
    "\tif (likely(prev != next)) {\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\twalt_update_task_ravg(prev, rq, PUT_PREV_TASK, wallclock, 0);\n"
    "\twalt_update_task_ravg(next, rq, PICK_NEXT_TASK, wallclock, 0);\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\t\trq->nr_switches++;",
    "__schedule WALT context-switch accounting"
)
body = replace_once(
    body,
    "\t} else {\n\t\trq->clock_update_flags &= ~(RQCF_ACT_SKIP|RQCF_REQ_SKIP);",
    "\t} else {\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\t\twalt_update_task_ravg(prev, rq, TASK_UPDATE, wallclock, 0);\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\t\trq->clock_update_flags &= ~(RQCF_ACT_SKIP|RQCF_REQ_SKIP);",
    "__schedule WALT no-switch accounting"
)
s = s[:start] + body + s[close + 1:]

# Keep the first CPU's WALT window synchronized when CPUs hotplug.
fn = "static void sched_rq_cpu_starting(unsigned int cpu)"
start = s.find(fn)
if start < 0:
    raise SystemExit("WALT: sched_rq_cpu_starting() not found")
close = struct_close(s, fn, "sched_rq_cpu_starting")
body = s[start:close + 1]
body = replace_once(
    body,
    "\tstruct rq *rq = cpu_rq(cpu);\n",
    "\tstruct rq *rq = cpu_rq(cpu);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\tstruct rq_flags rf;\n"
    "\trq_lock(rq, &rf);\n"
    "\twalt_set_window_start(rq, &rf);\n"
    "\trq_unlock(rq, &rf);\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "CPU start WALT window sync"
)
s = s[:start] + body + s[close + 1:]

fn = "int sched_cpu_dying(unsigned int cpu)"
start = s.find(fn)
if start < 0:
    raise SystemExit("WALT: sched_cpu_dying() not found")
close = struct_close(s, fn, "sched_cpu_dying")
body = s[start:close + 1]
body = replace_once(
    body,
    "\trq_lock_irqsave(rq, &rf);\n",
    "\trq_lock_irqsave(rq, &rf);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\twalt_migrate_sync_cpu(cpu);\n"
    "#endif /* CONFIG_SCHED_WALT */\n",
    "CPU dying WALT sync migration"
)
s = s[:start] + body + s[close + 1:]
write(p, s)


# Add a final source-side WALT sample before load-balancer migration.
p = "kernel/sched/fair.c"
s = read(p)
fn = "static void detach_task(struct task_struct *p, struct lb_env *env)"
start = s.find(fn)
if start < 0:
    raise SystemExit("WALT: fair detach_task() not found")
close = struct_close(s, fn, "fair detach_task")
body = s[start:close + 1]
body = replace_once(
    body,
    "\tp->on_rq = TASK_ON_RQ_MIGRATING;\n\tdeactivate_task(env->src_rq, p, DEQUEUE_NOCLOCK);\n\tset_task_cpu(p, env->dst_cpu);",
    "\tp->on_rq = TASK_ON_RQ_MIGRATING;\n\tdeactivate_task(env->src_rq, p, DEQUEUE_NOCLOCK);\n"
    "#ifdef CONFIG_SCHED_WALT\n"
    "\twalt_update_task_ravg(p, env->src_rq, TASK_MIGRATE, walt_ktime_clock(), 0);\n"
    "#endif /* CONFIG_SCHED_WALT */\n"
    "\tset_task_cpu(p, env->dst_cpu);",
    "task migration WALT accounting"
)
s = s[:start] + body + s[close + 1:]
write(p, s)

# Build WALT as part of the scheduler.
p = "kernel/sched/Makefile"
s = read(p)
if "obj-$(CONFIG_SCHED_WALT) += walt.o" not in s:
    s = s.rstrip() + "\nobj-$(CONFIG_SCHED_WALT) += walt.o\n"
write(p, s)

# Expose WALT as an optional default governor. Its rate/frequency policy is
# schedutil's, while schedutil receives WALT-derived CPU utilization above.
p = "drivers/cpufreq/Kconfig"
s = read(p)
choice = (
    "config CPU_FREQ_DEFAULT_GOV_WALT\n"
    "\tbool \"walt\"\n"
    "\tdepends on SMP && SCHED_WALT\n"
    "\tselect CPU_FREQ_GOV_WALT\n"
    "\tselect CPU_FREQ_GOV_SCHEDUTIL\n"
    "\thelp\n"
    "\t  Use the WALT-backed schedutil governor by default. WALT supplies\n"
    "\t  the scheduler utilization signal; schedutil performs frequency\n"
    "\t  selection and applies the CPUFreq policy limits.\n\n"
)
s = insert_before_once(s, "endchoice\n", choice, "WALT default CPUFreq choice")
gov = (
    "config CPU_FREQ_GOV_WALT\n"
    "\tbool \"'walt' WALT-backed CPUFreq governor\"\n"
    "\tdepends on CPU_FREQ && SCHED_WALT && CPU_FREQ_GOV_SCHEDUTIL\n"
    "\tdefault y if CPU_FREQ_DEFAULT_GOV_WALT\n"
    "\thelp\n"
    "\t  Register the WALT-backed schedutil policy under the governor name\n"
    "\t  'walt'. It uses WALT task/rq utilization and schedutil frequency\n"
    "\t  selection; it is not an independent Qualcomm waltgov implementation.\n\n"
)
s = insert_before_once(s, 'comment "CPU frequency scaling drivers"', gov, "WALT governor Kconfig")
write(p, s)

p = "init/Kconfig"
s = read(p)
walt_kconfig = (
    "config SCHED_WALT\n"
    "\tbool \"Window Assisted Load Tracking (WALT)\"\n"
    "\tdepends on SMP && FAIR_GROUP_SCHED\n"
    "\tdefault n\n"
    "\thelp\n"
    "\t  Maintain a window-based runnable history for tasks. The WALT task\n"
    "\t  demand is used by the scheduler and by the WALT-backed schedutil\n"
    "\t  CPUFreq governor. The default window is 20 ms.\n\n"
)
s = insert_before_once(s, "config SYSFS_DEPRECATED", walt_kconfig, "WALT scheduler Kconfig")
write(p, s)

# Set WALT and its governor as the phone's default CPUFreq policy.
p = "arch/arm64/configs/fleur_defconfig"
s = read(p)
if "CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y" not in s:
    raise SystemExit("WALT: fleur_defconfig does not contain the expected schedutil default")
s = s.replace("CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y",
              "# CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL is not set\nCONFIG_CPU_FREQ_DEFAULT_GOV_WALT=y", 1)
if "CONFIG_SCHED_WALT=y" not in s:
    s = insert_before_once(s, "CONFIG_SCHED_MC=y", "CONFIG_SCHED_WALT=y\n", "fleur WALT config")
if "CONFIG_CPU_FREQ_GOV_WALT=y" not in s:
    s = insert_before_once(s, "CONFIG_CPU_FREQ_GOV_POWERSAVE=y", "CONFIG_CPU_FREQ_GOV_WALT=y\n", "fleur WALT governor config")
write(p, s)

# Ensure no duplicate or contradictory configuration symbols were introduced.
for symbol in ("CONFIG_SCHED_WALT=y", "CONFIG_CPU_FREQ_DEFAULT_GOV_WALT=y",
               "CONFIG_CPU_FREQ_GOV_WALT=y", "# CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL is not set"):
    if symbol not in s:
        raise SystemExit(f"WALT: final defconfig is missing {symbol}")
if s.count("CONFIG_SCHED_WALT=y") != 1:
    raise SystemExit("WALT: duplicate CONFIG_SCHED_WALT entry")
if s.count("CONFIG_CPU_FREQ_DEFAULT_GOV_WALT=y") != 1:
    raise SystemExit("WALT: duplicate WALT default governor entry")

# Add a second cpufreq governor descriptor using the verified schedutil
# callbacks. The WALT-backed cpu_util_cfs() path is active when CONFIG_SCHED_WALT.
p = "kernel/sched/cpufreq_schedutil.c"
s = read(p)
descriptor = (
    "\n#ifdef CONFIG_CPU_FREQ_GOV_WALT\n"
    "struct cpufreq_governor walt_gov = {\n"
    "\t.name\t\t\t= \"walt\",\n"
    "\t.owner\t\t\t= THIS_MODULE,\n"
    "\t.dynamic_switching\t= true,\n"
    "\t.init\t\t\t= sugov_init,\n"
    "\t.exit\t\t\t= sugov_exit,\n"
    "\t.start\t\t\t= sugov_start,\n"
    "\t.stop\t\t\t= sugov_stop,\n"
    "\t.limits\t\t\t= sugov_limits,\n"
    "};\n"
    "#endif /* CONFIG_CPU_FREQ_GOV_WALT */\n"
)
s = replace_once(
    s,
    "struct cpufreq_governor schedutil_gov = {",
    "struct cpufreq_governor schedutil_gov = {",
    "schedutil governor anchor"
)
end_marker = (
    "\t.limits\t\t\t= sugov_limits,\n"
    "};\n"
)
s = replace_once(s, end_marker, end_marker + descriptor, "WALT governor descriptor")
s = replace_once(
    s,
    "#ifdef CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL\n"
    "struct cpufreq_governor *cpufreq_default_governor(void)\n"
    "{\n"
    "\treturn &schedutil_gov;\n"
    "}\n"
    "#endif",
    "#if defined(CONFIG_CPU_FREQ_DEFAULT_GOV_WALT)\n"
    "struct cpufreq_governor *cpufreq_default_governor(void)\n"
    "{\n"
    "\treturn &walt_gov;\n"
    "}\n"
    "#elif defined(CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL)\n"
    "struct cpufreq_governor *cpufreq_default_governor(void)\n"
    "{\n"
    "\treturn &schedutil_gov;\n"
    "}\n"
    "#endif",
    "default CPUFreq governor selection"
)
s = replace_once(
    s,
    "static int __init sugov_register(void)\n"
    "{\n"
    "\treturn cpufreq_register_governor(&schedutil_gov);\n"
    "}",
    "static int __init sugov_register(void)\n"
    "{\n"
    "\tint ret = cpufreq_register_governor(&schedutil_gov);\n"
    "\tif (ret)\n"
    "\t\treturn ret;\n"
    "#ifdef CONFIG_CPU_FREQ_GOV_WALT\n"
    "\tret = cpufreq_register_governor(&walt_gov);\n"
    "\tif (ret)\n"
    "\t\tpr_err(\"cpufreq: failed to register walt governor: %d\\\\n\", ret);\n"
    "#endif\n"
    "\treturn 0;\n"
    "}",
    "register WALT CPUFreq governor"
)
# Make EAS treat the WALT alias as a schedutil-capable governor.
s = replace_once(
    s,
    "if (old_gov == &schedutil_gov || policy->governor == &schedutil_gov) {",
    "if (old_gov == &schedutil_gov || policy->governor == &schedutil_gov\n"
    "#ifdef CONFIG_CPU_FREQ_GOV_WALT\n"
    "\t    || old_gov == &walt_gov || policy->governor == &walt_gov\n"
    "#endif\n"
    "\t   ) {",
    "EAS governor-switch detection"
)
write(p, s)

# Confirm scheduler hooks and source wiring before the build begins.
checks = {
    "include/linux/sched.h": ["struct ravg", "enum task_event", "init_load_pct"],
    "kernel/sched/sched.h": ["window_start", "walt_ravg_window", "p->ravg.demand"],
    "kernel/sched/fair.c": ["walt_ravg_window", "p->ravg.demand"],
    "kernel/sched/core.c": ["walt_try_to_wake_up", "walt_set_window_start",
                            "walt_update_task_ravg", "walt_init_new_task_load"],
    "kernel/sched/Makefile": ["obj-$(CONFIG_SCHED_WALT) += walt.o"],
    "drivers/cpufreq/Kconfig": ["CPU_FREQ_DEFAULT_GOV_WALT", "CPU_FREQ_GOV_WALT"],
    "kernel/sched/cpufreq_schedutil.c": ['.name\t\t\t= "walt"', "&walt_gov"],
    "arch/arm64/configs/fleur_defconfig": ["CONFIG_SCHED_WALT=y",
            "CONFIG_CPU_FREQ_DEFAULT_GOV_WALT=y", "CONFIG_CPU_FREQ_GOV_WALT=y"]
}
for path, tokens in checks.items():
    data = read(path)
    for token in tokens:
        if token not in data:
            raise SystemExit(f"WALT: post-patch validation failed: {path} missing {token}")

print("WALT integration source patch applied.")
print("Scheduler: WALT window tracking + WALT task demand + WALT CPU util aggregation.")
print("CPUFreq: 'walt' governor alias uses schedutil callbacks with WALT utilization.")
print("Default governor: walt.")
