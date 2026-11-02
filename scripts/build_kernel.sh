#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_REF="${1:-lineage-24.0}"
BUILD_PROFILE="${2:-baseline}"
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

case "$BUILD_PROFILE" in
  baseline|beta1|beta2) ;;
  *)
    echo "Unsupported build profile: $BUILD_PROFILE" >&2
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

case "$BUILD_PROFILE" in
  beta1)
    bash "$WORKSPACE/scripts/apply_beta1_2100.sh" "$SRC_DIR"
    ;;
  beta2)
    bash "$WORKSPACE/scripts/apply_beta2_2200.sh" "$SRC_DIR"
    ;;
esac

git -C "$SRC_DIR" diff --check

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
SOURCE_COMMIT="$(git -C "$SRC_DIR" rev-parse HEAD)"
CLANG_VERSION="$(clang --version | head -n 1)"

case "$BUILD_PROFILE" in
  beta1)
    git -C "$SRC_DIR" diff --binary > "$ARTIFACT_DIR/beta1-source.patch"
    ;;
  beta2)
    git -C "$SRC_DIR" diff --binary > "$ARTIFACT_DIR/beta2-source.patch"
    ;;
esac

{
  echo "source_url=$SOURCE_URL"
  echo "source_ref=$SOURCE_REF"
  echo "source_commit=$SOURCE_COMMIT"
  echo "device_config=fleur_defconfig"
  echo "arch=arm64"
  echo "build_profile=$BUILD_PROFILE"
  if [[ "$BUILD_PROFILE" == "beta1" ]]; then
    echo "target_big_cluster_max_hz=2100000000"
    echo "target_big_cluster_voltage_policy=unchanged_stock_CPU_LEVEL_0"
    echo "stock_big_cluster_top_opp_voltage_uv=1118750"
    echo "thermal_protection=unchanged"
  elif [[ "$BUILD_PROFILE" == "beta2" ]]; then
    echo "target_big_cluster_cpus=6,7"
    echo "target_big_cluster_max_hz=2200000000"
    echo "target_big_cluster_max_uv=1156250"
    echo "target_big_cluster_voltage_delta_uv=37500"
    echo "target_big_cluster_pmic_code=105"
    echo "thermal_and_watchdog_protections=unchanged"
    echo "vendor_sspm_firmware_binary=unchanged"
  fi
  echo "toolchain=Android LLVM clang-r563880c"
  echo "compiler=$CLANG_VERSION"
  echo "kernel_image=Image.gz-dtb"
  if [[ "$BUILD_PROFILE" == "beta2" ]]; then
    echo "flashable_zip=AnyKernel3"
  else
    echo "flashable_zip=false"
  fi
  echo "build_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  sha256sum "$ARTIFACT_DIR/Image.gz-dtb" "$ARTIFACT_DIR/kernel.config"
  if [[ "$BUILD_PROFILE" == "beta1" ]]; then
    sha256sum "$ARTIFACT_DIR/beta1-source.patch"
  elif [[ "$BUILD_PROFILE" == "beta2" ]]; then
    sha256sum "$ARTIFACT_DIR/beta2-source.patch"
  fi
} | tee "$ARTIFACT_DIR/build-manifest.txt"

echo "Build completed; outputs are in $ARTIFACT_DIR"
