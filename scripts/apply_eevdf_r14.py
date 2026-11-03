#!/usr/bin/env python3
"""Apply a conservative EEVDF scheduler prototype to the Fleur Android 11 4.14 tree.

This keeps the MediaTek WALT/HMP/EAS code in place. It deliberately uses a
linear scan of the existing CFS rb-tree for eligible entities; it is a
functional backport prototype, not the upstream augmented-rbtree O(log n)
implementation. Do not ship/flash without boot and scheduler testing.
"""
from pathlib import Path
import sys

def fail(msg):
    raise SystemExit("EEVDF patch error: " + msg)

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)

def function_span(text, needle, start_at=0):
    start = text.find(needle, start_at)
    if start < 0:
        fail(f"function not found: {needle}")
    brace = text.find("{", start)
    if brace < 0:
        fail(f"opening brace not found for: {needle}")
    depth = 0
    i = brace
    state = "code"
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if ch == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            if ch == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if ch == '"':
                state = "string"
                i += 1
                continue
            if ch == "'":
                state = "char"
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return start, i + 1
        elif state == "block":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
        elif state == "line":
            if ch == "\n":
                state = "code"
        elif state in ("string", "char"):
            if ch == "\\":
                i += 2
                continue
            if (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                state = "code"
        i += 1
    fail(f"unterminated function body: {needle}")

def replace_function(text, needle, new_function):
    start, end = function_span(text, needle)
    return text[:start] + new_function + text[end:]

def main(root):
    root = Path(root).resolve()
    fair_path = root / "kernel/sched/fair.c"
    sched_path = root / "include/linux/sched.h"
    if not fair_path.is_file() or not sched_path.is_file():
        fail(f"{root} is not the expected Fleur kernel source root")

    fair = fair_path.read_text()
    sched = sched_path.read_text()

    sched = replace_once(
        sched,
        "\tu64\t\t\t\tvruntime;\n",
        "\tu64\t\t\t\tvruntime;\n"
        "\t/* EEVDF virtual deadline; zero means it must be initialized. */\n"
        "\tu64\t\t\t\tdeadline;\n",
        "sched_entity deadline field",
    )

    fair = replace_once(
        fair,
        "#include <linux/sched/topology.h>\n",
        "#include <linux/sched/topology.h>\n#include <linux/math64.h>\n",
        "math64 include",
    )

    helpers = r'''
/*
 * EEVDF helpers.
 *
 * The average is calculated from the runnable entities currently represented
 * by this cfs_rq. The current entity is not in tasks_timeline, so include it
 * explicitly. scale_load_down() keeps the weighted sum within signed range
 * for realistic Android runqueue sizes.
 */
static u64 eevdf_avg_vruntime(struct cfs_rq *cfs_rq,
                              struct sched_entity *curr)
{
    struct rb_node *node;
    struct sched_entity *se;
    s64 avg = 0;
    u64 load = 0;

    for (node = rb_first_cached(&cfs_rq->tasks_timeline);
         node; node = rb_next(node)) {
        s64 weight;

        se = rb_entry(node, struct sched_entity, run_node);
        weight = (s64)scale_load_down(se->load.weight);
        avg += (s64)(se->vruntime - cfs_rq->min_vruntime) * weight;
        load += weight;
    }

    if (curr && curr->on_rq) {
        s64 weight = (s64)scale_load_down(curr->load.weight);

        avg += (s64)(curr->vruntime - cfs_rq->min_vruntime) * weight;
        load += weight;
    }

    if (unlikely(!load))
        return cfs_rq->min_vruntime;

    /* Round negative values down, rather than toward zero. */
    if (avg < 0)
        avg -= (s64)load - 1;

    return cfs_rq->min_vruntime + div64_s64(avg, (s64)load);
}

static bool eevdf_eligible(u64 avg_vruntime, struct sched_entity *se)
{
    return (s64)(se->vruntime - avg_vruntime) <= 0;
}

static bool eevdf_deadline_before(struct sched_entity *a,
                                   struct sched_entity *b)
{
    return (s64)(a->deadline - b->deadline) < 0;
}

/*
 * A new slice is assigned when an entity has consumed the slice represented
 * by its previous virtual deadline, or when it has no deadline yet.
 */
static void eevdf_update_deadline(struct cfs_rq *cfs_rq,
                                  struct sched_entity *se)
{
    if (!se->deadline || (s64)(se->vruntime - se->deadline) >= 0) {
        u64 slice = sched_slice(cfs_rq, se);

        se->deadline = se->vruntime + calc_delta_fair(slice, se);
    }
}

static struct sched_entity *
pick_eevdf_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)
{
    struct rb_node *node;
    struct sched_entity *se;
    struct sched_entity *best = NULL;
    u64 avg_vruntime = eevdf_avg_vruntime(cfs_rq, curr);

    if (curr && curr->on_rq) {
        eevdf_update_deadline(cfs_rq, curr);
        if (eevdf_eligible(avg_vruntime, curr))
            best = curr;
    }

    for (node = rb_first_cached(&cfs_rq->tasks_timeline);
         node; node = rb_next(node)) {
        se = rb_entry(node, struct sched_entity, run_node);
        eevdf_update_deadline(cfs_rq, se);

        if (!eevdf_eligible(avg_vruntime, se))
            continue;

        if (!best || eevdf_deadline_before(se, best))
            best = se;
    }

    /*
     * At least one entity should be eligible when the weighted average is
     * calculated correctly. Keep a deterministic vruntime fallback for
     * unusual empty/overflow/transition states.
     */
    if (unlikely(!best)) {
        if (curr && curr->on_rq)
            best = curr;

        for (node = rb_first_cached(&cfs_rq->tasks_timeline);
             node; node = rb_next(node)) {
            se = rb_entry(node, struct sched_entity, run_node);
            if (!best || entity_before(se, best))
                best = se;
        }
    }

    return best;
}
'''
    sched_slice_span = function_span(fair, "sched_slice(struct cfs_rq")
    fair = fair[:sched_slice_span[1]] + "\n" + helpers + fair[sched_slice_span[1]:]

    # Sleeping/waking placement establishes a fresh virtual deadline.
    fair = replace_function(
        fair,
        "place_entity(struct cfs_rq",
        r'''place_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int initial)
{
    u64 vruntime = cfs_rq->min_vruntime;

    if (initial && sched_feat(START_DEBIT))
        vruntime += sched_vslice(cfs_rq, se);

    if (!initial) {
        unsigned long thresh = sysctl_sched_latency;

        if (sched_feat(GENTLE_FAIR_SLEEPERS))
            thresh >>= 1;

        vruntime -= thresh;
    }

    if (entity_is_long_sleeper(se))
        se->vruntime = vruntime;
    else
        se->vruntime = max_vruntime(se->vruntime, vruntime);

    /* Recompute the virtual deadline after placement. */
    se->deadline = 0;
}''',
    )

    # Keep deadline in the same rq-relative virtual-time coordinate as vruntime.
    fair = replace_once(
        fair,
        "if (renorm && curr)\n\t\tse->vruntime += cfs_rq->min_vruntime;",
        "if (renorm && curr) {\n"
        "\t\tse->vruntime += cfs_rq->min_vruntime;\n"
        "\t\tif (se->deadline)\n\t\t\tse->deadline += cfs_rq->min_vruntime;\n"
        "\t}",
        "enqueue current vruntime normalization",
    )
    fair = replace_once(
        fair,
        "if (renorm && !curr)\n\t\tse->vruntime += cfs_rq->min_vruntime;",
        "if (renorm && !curr) {\n"
        "\t\tse->vruntime += cfs_rq->min_vruntime;\n"
        "\t\tif (se->deadline)\n\t\t\tse->deadline += cfs_rq->min_vruntime;\n"
        "\t}",
        "enqueue entity vruntime normalization",
    )
    fair = replace_once(
        fair,
        "if (!(flags & DEQUEUE_SLEEP))\n\t\tse->vruntime -= cfs_rq->min_vruntime;",
        "if (!(flags & DEQUEUE_SLEEP)) {\n"
        "\t\tse->vruntime -= cfs_rq->min_vruntime;\n"
        "\t\tif (se->deadline)\n"
        "\t\t\tse->deadline -= cfs_rq->min_vruntime;\n"
        "\t}",
        "dequeue vruntime normalization",
    )

    fair = replace_once(
        fair,
        "\t\tse->vruntime -= min_vruntime;\n",
        "\t\tse->vruntime -= min_vruntime;\n"
        "\t\tif (se->deadline)\n"
        "\t\t\tse->deadline -= min_vruntime;\n",
        "task migration vruntime normalization",
    )

    # New task starts with a new virtual deadline after its placement.
    fair = replace_once(
        fair,
        "\t\tswap(curr->vruntime, se->vruntime);\n",
        "\t\tswap(curr->vruntime, se->vruntime);\n"
        "\t\tcurr->deadline = 0;\n"
        "\t\tse->deadline = 0;\n",
        "fork child-runs-first deadline reset",
    )
    fair = replace_once(
        fair,
        "if (!vruntime_normalized(p))\n\t\tse->vruntime += cfs_rq->min_vruntime;",
        "if (!vruntime_normalized(p)) {\n"
        "\t\tse->vruntime += cfs_rq->min_vruntime;\n"
        "\t\tif (se->deadline)\n"
        "\t\t\tse->deadline += cfs_rq->min_vruntime;\n"
        "\t}",
        "attach task vruntime normalization",
    )

    # Use EEVDF for the fair scheduling class's next-entity selection.
    fair = replace_function(
        fair,
        "pick_next_entity(struct cfs_rq",
        r'''static struct sched_entity *
pick_next_entity(struct cfs_rq *cfs_rq, struct sched_entity *curr)
{
    struct sched_entity *se;

    se = pick_eevdf_entity(cfs_rq, curr);
    clear_buddies(cfs_rq, se);

    return se;
}''',
    )

    fair = replace_function(
        fair,
        "check_preempt_tick(struct cfs_rq",
        r'''static void
check_preempt_tick(struct cfs_rq *cfs_rq, struct sched_entity *curr)
{
    unsigned long ideal_runtime, delta_exec;
    struct sched_entity *se;

    ideal_runtime = sched_slice(cfs_rq, curr);
    delta_exec = curr->sum_exec_runtime - curr->prev_sum_exec_runtime;
    if (delta_exec > ideal_runtime) {
        resched_curr(rq_of(cfs_rq));
        clear_buddies(cfs_rq, curr);
        return;
    }

    if (delta_exec < sysctl_sched_min_granularity)
        return;

    /*
     * Re-evaluate EEVDF eligibility/deadlines on the tick. This catches
     * newly eligible tasks even when no wakeup event caused a preemption.
     */
    se = pick_eevdf_entity(cfs_rq, curr);
    if (se && se != curr)
        resched_curr(rq_of(cfs_rq));
}''',
    )

    # Remove CFS's vruntime/wakeup-granularity preemption helper. EEVDF compares
    # eligibility and virtual deadlines in check_preempt_wakeup() instead.
    decl = "static int\nwakeup_preempt_entity(struct sched_entity *curr, struct sched_entity *se);\n\n"
    if decl not in fair:
        fail("wakeup_preempt_entity forward declaration not found")
    fair = fair.replace(decl, "", 1)

    # Replace the full helper definitions.
    for needle in ("wakeup_gran(struct sched_entity",):
        a, b = function_span(fair, needle)
        fair = fair[:a] + fair[b:]
    a, b = function_span(fair, "wakeup_preempt_entity(struct sched_entity", fair.find("wakeup_preempt_entity(struct sched_entity") + 1)
    fair = fair[:a] + fair[b:]

    fair = replace_function(
        fair,
        "check_preempt_wakeup(struct rq",
        r'''static void check_preempt_wakeup(struct rq *rq, struct task_struct *p, int wake_flags)
{
    struct task_struct *curr = rq->curr;
    struct sched_entity *se = &curr->se, *pse = &p->se;
    struct cfs_rq *cfs_rq = task_cfs_rq(curr);
    u64 avg_vruntime;

    if (unlikely(se == pse))
        return;

    if (unlikely(throttled_hierarchy(cfs_rq_of(pse))))
        return;

    if (test_tsk_need_resched(curr))
        return;

    if (unlikely(curr->policy == SCHED_IDLE) &&
        likely(p->policy != SCHED_IDLE))
        goto preempt;

    if (unlikely(p->policy != SCHED_NORMAL) ||
        !sched_feat(WAKEUP_PREEMPTION))
        return;

    find_matching_se(&se, &pse);
    cfs_rq = cfs_rq_of(se);
    update_curr(cfs_rq);

    avg_vruntime = eevdf_avg_vruntime(cfs_rq, se);
    eevdf_update_deadline(cfs_rq, se);
    eevdf_update_deadline(cfs_rq, pse);

    /*
     * A waking task preempts only when it is eligible and either the
     * current entity is ineligible or the wakee has the earlier deadline.
     */
    if (!eevdf_eligible(avg_vruntime, pse))
        return;

    if (eevdf_eligible(avg_vruntime, se) &&
        !eevdf_deadline_before(pse, se))
        return;

preempt:
    resched_curr(rq);

    if (unlikely(!se->on_rq || curr == rq->idle))
        return;
}''',
    )

    if "wakeup_preempt_entity(" in fair or "wakeup_gran(" in fair:
        fail("obsolete CFS wakeup-preemption helper still referenced")

    fair_path.write_text(fair)
    sched_path.write_text(sched)
    print("Applied EEVDF prototype to:")
    print(" - kernel/sched/fair.c")
    print(" - include/linux/sched.h")
    print("Preserved WALT/HMP/EAS source hooks.")
    print("Selection uses a linear scan of eligible entities (prototype).")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        fail("usage: apply_eevdf_r14.py KERNEL_SOURCE_DIR")
    main(sys.argv[1])
