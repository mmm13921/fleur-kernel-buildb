#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_REF="${1:-lineage-24.0}"
SOURCE_URL="https://gitlab.com/daliboss/fleux.git"
WORKSPACE="${GITHUB_WORKSPACE:-$PWD}"
SRC_DIR="${SRC_DIR:-$WORKSPACE/kernel-src}"
OUT_DIR="${OUT_DIR:-$WORKSPACE/out}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$WORKSPACE/artifacts}"
TOOLCHAIN_DIR="${TOOLCHAIN_DIR:-}"

case "$SOURCE_REF" in
  ""|-*|*..*|*//*|*[!A-Za-z0-9._/-]*)
    echo "Invalid source ref: $SOURCE_REF" >&2
    exit 2
    ;;
esac

if [[ -z "$TOOLCHAIN_DIR" || ! -x "$TOOLCHAIN_DIR/bin/clang" ]]; then
  echo "Set TOOLCHAIN_DIR to the extracted Android Clang r563880c directory." >&2
  exit 2
fi

if [[ -e "$SRC_DIR" ]]; then
  echo "Source directory already exists: $SRC_DIR" >&2
  exit 2
fi

mkdir -p "$(dirname "$SRC_DIR")" "$ARTIFACT_DIR"
git clone --depth=1 --branch "$SOURCE_REF" "$SOURCE_URL" "$SRC_DIR"
git -C "$SRC_DIR" submodule sync --recursive
git -C "$SRC_DIR" submodule update --init --depth=1 --recursive

bash "$WORKSPACE/scripts/apply_sched_nr_latency_1.sh" "$SRC_DIR"
git -C "$SRC_DIR" diff --check

python3 - "$SRC_DIR/kernel/sched/fair.c" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1]).read_text()
assert re.search(
    r"(?m)^\s*static\s+unsigned\s+int\s+sched_nr_latency\s*=\s*1\s*;",
    source,
), "sched_nr_latency declaration is not fixed at 1"
assert len(re.findall(r"(?m)^\s*sched_nr_latency\s*=\s*1\s*;", source)) == 1, (
    "expected exactly one fixed assignment in the sysctl update handler"
)
assert "sched_nr_latency = DIV_ROUND_UP" not in source, (
    "dynamic sched_nr_latency recalculation remains"
)
assert "nr_running > sched_nr_latency" in source, (
    "CFS period calculation no longer references sched_nr_latency"
)
print("SOURCE AUDIT PASSED: sched_nr_latency is fixed at 1")
PY

export PATH="$TOOLCHAIN_DIR/bin:$PATH"
export ARCH=arm64
export SUBARCH=arm64
export KBUILD_BUILD_USER="${KBUILD_BUILD_USER:-fleux-builder}"
export KBUILD_BUILD_HOST="${KBUILD_BUILD_HOST:-reproducible-runner}"

make -C "$SRC_DIR" O="$OUT_DIR" fleur_defconfig \
  CC=clang LD=ld.lld LLVM=1 LLVM_IAS=1

make -C "$SRC_DIR" -j"$(nproc)" O="$OUT_DIR" \
  CC=clang LD=ld.lld LLVM=1 LLVM_IAS=1 \
  CLANG_TRIPLE=aarch64-linux-gnu- \
  CROSS_COMPILE=aarch64-linux-gnu- \
  CROSS_COMPILE_ARM32=arm-linux-gnueabi-

IMAGE="$OUT_DIR/arch/arm64/boot/Image.gz-dtb"
if [[ ! -s "$IMAGE" ]]; then
  echo "Expected output missing or empty: $IMAGE" >&2
  find "$OUT_DIR/arch/arm64/boot" -maxdepth 2 -type f -printf '%p\n' || true
  exit 1
fi

cp "$IMAGE" "$ARTIFACT_DIR/Image.gz-dtb"
cp "$OUT_DIR/.config" "$ARTIFACT_DIR/kernel.config"
git -C "$SRC_DIR" diff --binary > "$ARTIFACT_DIR/sched-nr-latency-1-source.patch"

SOURCE_COMMIT="$(git -C "$SRC_DIR" rev-parse HEAD)"
CLANG_VERSION="$(clang --version | head -n 1)"

{
  echo "source_url=$SOURCE_URL"
  echo "source_ref=$SOURCE_REF"
  echo "source_commit=$SOURCE_COMMIT"
  echo "device_config=fleur_defconfig"
  echo "arch=arm64"
  echo "build_profile=baseline_sched_nr_latency_1"
  echo "sched_nr_latency=1"
  echo "sched_nr_latency_initial_value=1"
  echo "sched_nr_latency_sysctl_update_value=1"
  echo "cpu_gpu_cci_dvfs_changes=none"
  echo "voltage_changes=none"
  echo "thermal_and_watchdog_protections=unchanged"
  echo "toolchain=Android LLVM clang-r563880c"
  echo "compiler=$CLANG_VERSION"
  echo "kernel_image=Image.gz-dtb"
  echo "flashable_zip=AnyKernel3"
  echo "build_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  sha256sum "$ARTIFACT_DIR/Image.gz-dtb" "$ARTIFACT_DIR/kernel.config" \
    "$ARTIFACT_DIR/sched-nr-latency-1-source.patch"
} | tee "$ARTIFACT_DIR/build-manifest.txt"

echo "Build completed; outputs are in $ARTIFACT_DIR"
