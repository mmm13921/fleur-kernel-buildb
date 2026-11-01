# Fleux Kernel Builder

A reproducible build and inspection service for the public Fleux kernel source used by Redmi Note 11S 4G / POCO M4 Pro 4G (MT6781, fleur family).

## Current scope

- Build the unmodified Fleux source for `fleur_defconfig` with the toolchain documented by the source project.
- Record the exact source commit, compiler version and SHA-256 of the output.
- Publish the kernel image as a GitHub Actions artifact.
- Provide an authenticated MCP service to inspect source OPP/DVFS data, dispatch builds, query recent runs and list artifacts.

The first build produces `Image.gz-dtb` only. It is **not** a flashable ZIP and does not modify a phone or any partition. AnyKernel3 packaging will be a separate stage after boot-image layout and installer compatibility are verified.

## Source of truth

- Kernel source: https://gitlab.com/daliboss/fleux
- Source ref: `lineage-24.0`
- Device config: `arch/arm64/configs/fleur_defconfig`
- Kernel release family documented by the source: Linux 4.19.325
- Compiler documented by the source README: Android LLVM/Clang `r563880c`

The workflow downloads the named Android Clang archive, installs the ARM cross-compilers and follows the Fleux README build commands. It does not silently change CPU/GPU OPPs.

## Run a baseline build

1. Open the Actions tab in this repository.
2. Select **Fleux baseline kernel build**.
3. Select **Run workflow** and keep the source ref at `lineage-24.0`.
4. Download the `fleux-baseline` artifact when the run succeeds.

The artifact contains `Image.gz-dtb`, the generated `.config`, and a build manifest. The manifest records the exact source commit and checksums.

## MCP service

The MCP server is in `server.py` and uses Streamable HTTP at `/mcp`.

### Tools

- `project_info` — source and build target metadata.
- `read_kernel_source_file` — read a small allowlist of source files from GitLab.
- `inspect_cpu_opp_tables` — report CPU OPP, voltage and SSPM-related source evidence.
- `start_baseline_build` — dispatch the baseline GitHub Actions workflow.
- `latest_build_status` — inspect recent workflow runs.
- `list_build_artifacts` — list artifacts for a workflow run.

The service deliberately has no arbitrary shell, arbitrary file-write, voltage-edit or thermal-disable tool. OPP modifications are not enabled until the firmware/SSPM and PLL side can be audited together.

### Required environment variables

- `GH_TOKEN`: a fine-grained GitHub token restricted to this repository, with **Actions: Read and write** and **Metadata: Read-only**. Do not commit it.
- `MCP_AUTH_TOKEN`: a separate random bearer token used to protect the MCP endpoint.
- `BUILDER_WORKFLOW_REF`: workflow branch to dispatch; default is `main`. The workflow must first be merged into that branch.

Run locally:

    python -m pip install -r requirements.txt
    export GH_TOKEN='...'
    export MCP_AUTH_TOKEN='...'
    uvicorn server:app --host 0.0.0.0 --port 8000

Connect a Bearer-capable remote MCP client to `https://YOUR-HOST/mcp` using HTTP Bearer authentication. Do not expose the service without TLS and authentication.

**ChatGPT-specific limitation:** this initial server uses a static bearer secret and is not yet a ChatGPT-compatible OAuth server. ChatGPT custom MCP connections require an OAuth 2.1 authorization flow; ChatGPT does not accept a customer-supplied static API key as its client credential. See [ChatGPT MCP authentication requirements](https://developers.openai.com/plugins/build/auth). The current ChatGPT account tier also matters: custom MCP connections are available on Business and Enterprise/Edu; Pro is read/fetch only, and Free is not listed as supporting custom MCP connections. See [OpenAI's current availability matrix](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt).

## Local baseline build

The CI workflow invokes `scripts/build_kernel.sh`. For a local build, install the Android Clang `r563880c` toolchain and the GNU ARM cross-compilers, then run:

    export TOOLCHAIN_DIR=/path/to/clang-r563880c
    bash scripts/build_kernel.sh lineage-24.0

The script clones the source into `kernel-src`, builds to `out`, and places verified outputs in `artifacts/`.

## Device-specific constraints

The source Device Tree currently declares the big-cluster final OPP as 2,050,000,000 Hz at 1,118,750 µV. The CPU DVFS hybrid path uses SSPM IPI messaging. Editing only the kernel OPP arrays is therefore not a verified overclock path.

No 2.2–2.6 GHz profile, increased voltage table, thermal bypass, or flashable image is claimed by this initial tooling release. See [the source audit notes](docs/overclock-safety.md).

## Safety and recovery

Build artifacts are research outputs, not installation instructions. Before any later flashing stage, verify the exact ROM/vendor base, device variant, boot header, DTB placement, ramdisk handling and recovery path. Keep a known-good boot image available. Never disable hardware thermal emergency protection as part of an overclock experiment.


## Deploy the MCP endpoint on Render

1. In the [Render Dashboard](https://dashboard.render.com), choose **New → Blueprint** and connect this repository on branch `main`.
2. Review the `fleux-kernel-builder` service and deploy the Blueprint.
3. During initial setup, enter:
   - `GH_TOKEN`: a repository-scoped fine-grained GitHub token with **Actions: Read and write** and **Metadata: Read-only**. Do not grant Contents write access; the MCP service does not need it.
   - `MCP_AUTH_TOKEN`: a separate high-entropy bearer secret. Save it securely; it is required when configuring the MCP connection in ChatGPT.
4. After Render reports the service healthy, use `https://YOUR-SERVICE.onrender.com/mcp` as the MCP URL and configure HTTP Bearer authentication with the `MCP_AUTH_TOKEN` value. The public health probe is `/health`.

The Blueprint uses Render's **Free** compute plan to avoid opting into paid compute automatically. Free web services spin down after 15 minutes without inbound traffic and can take about a minute to start on the next request. Upgrade only if an always-on endpoint is required.
