#!/usr/bin/env bash
set -Eeuo pipefail

SRC_DIR="${1:?Usage: apply_sched_nr_latency_1.sh <kernel-source-directory>}"
FAIR="$SRC_DIR/kernel/sched/fair.c"

if [[ ! -f "$FAIR" ]]; then
  echo "sched_nr_latency patch: missing $FAIR" >&2
  exit 2
fi

python3 - "$FAIR" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text()

old_decl = "static unsigned int sched_nr_latency = 8;"
new_decl = "static unsigned int sched_nr_latency = 1;"

if source.count(old_decl) == 1 and source.count(new_decl) == 0:
    source = source.replace(old_decl, new_decl, 1)
elif source.count(new_decl) == 1 and source.count(old_decl) == 0:
    pass
else:
    raise SystemExit(
        "sched_nr_latency patch: expected exactly one upstream declaration "
        "at 8 (or an already patched declaration at 1)"
    )

handler_assignment = re.compile(
    r"sched_nr_latency\s*=\s*DIV_ROUND_UP\s*\(\s*"
    r"sysctl_sched_latency\s*,\s*"
    r"sysctl_sched_min_granularity\s*\)\s*;",
    re.S,
)
matches = list(handler_assignment.finditer(source))
fixed_assignment = re.compile(r"(?m)^\s*sched_nr_latency\s*=\s*1\s*;")

if len(matches) == 1:
    source = handler_assignment.sub("sched_nr_latency = 1;", source, count=1)
elif len(matches) == 0 and len(fixed_assignment.findall(source)) == 1:
    pass
else:
    raise SystemExit(
        "sched_nr_latency patch: expected exactly one DIV_ROUND_UP update "
        "in sched_proc_update_handler (or one already fixed assignment)"
    )

if not re.search(
    r"(?m)^\s*static\s+unsigned\s+int\s+sched_nr_latency\s*=\s*1\s*;",
    source,
):
    raise SystemExit("sched_nr_latency patch: declaration audit failed")

if len(fixed_assignment.findall(source)) != 1:
    raise SystemExit("sched_nr_latency patch: fixed sysctl-handler audit failed")

if "nr_running > sched_nr_latency" not in source:
    raise SystemExit("sched_nr_latency patch: CFS period use-site is missing")

if "sched_nr_latency = DIV_ROUND_UP" in source:
    raise SystemExit("sched_nr_latency patch: dynamic recomputation remains")

path.write_text(source)
print("sched_nr_latency source patch applied and audited: fixed value = 1")
PY

git -C "$SRC_DIR" diff --check
