#!/usr/bin/env python3
import pathlib, re, shutil, sys

kernel = pathlib.Path(sys.argv[1]).resolve()
govsrc = pathlib.Path(sys.argv[2]).resolve()
cpufreq = kernel / "drivers/cpufreq"
kconfig = cpufreq / "Kconfig"
makefile = cpufreq / "Makefile"
defconfig = kernel / "arch/arm64/configs/fleur_defconfig"

# Only governors with real C implementations in the pinned source collection.
# Names that are aliases, hotplug controllers, or lack a compatible source are
# deliberately not fabricated as CPUFreq governors.
items = [
    ("INTERACTIVE", "interactive"),
    ("YANKACTIVE", "yankactive"),
    ("INTELLIACTIVE", "intelliactive"),
    ("IMPULSE", "impulse"),
    ("BLU_ACTIVE", "blu_active"),
    ("SMARTASS2", "smartass2"),
    ("SMARTMAX", "smartmax"),
    ("SMARTMAX_EPS", "smartmax_eps"),
    ("LIONHEART", "lionheart"),
    ("WHEATLEY", "wheatley"),
    ("LAGFREE", "lagfree"),
    ("ALUCARD", "alucard"),
    ("DARKNESS", "darkness"),
    ("NIGHTMARE", "nightmare"),
    ("DANCEDANCE", "dancedance"),
    ("PEGASUSQ", "pegasusq"),
]
added = []
missing = []
for symbol, name in items:
    filename = f"cpufreq_{name}.c"
    candidates = [govsrc / filename, govsrc / "sammy gov_freq" / filename]
    source = next((p for p in candidates if p.is_file()), None)
    if source is None:
        missing.append(name)
        continue
    target = cpufreq / filename
    shutil.copy2(source, target)
    added.append((symbol, name, filename))

k = kconfig.read_text()
marker = 'comment "CPU frequency scaling drivers"'
if marker not in k:
    raise SystemExit("Kconfig insertion marker not found")
blocks = []
for symbol, name, filename in added:
    key = f"config CPU_FREQ_GOV_{symbol}"
    if key in k:
        continue
    blocks.append(
        f'config CPU_FREQ_GOV_{symbol}\n'
        f'\ttristate "\'{name}\' CPUFreq governor"\n'
        f'\tdepends on CPU_FREQ\n'
        f'\tselect CPU_FREQ_GOV_COMMON\n'
        f'\thelp\n'
        f'\t  Enable the {name} CPU frequency governor.\n'
    )
k = k.replace(marker, "\n".join(blocks) + "\n" + marker, 1)
kconfig.write_text(k)

m = makefile.read_text()
marker = "# CPUfreq governors"
if marker not in m:
    raise SystemExit("Makefile insertion marker not found")
entries = []
for symbol, name, filename in added:
    line = f"obj-$(CONFIG_CPU_FREQ_GOV_{symbol})\t+= {filename[:-2]}.o"
    if line not in m:
        entries.append(line)
m = m.replace(marker, marker + "\n" + "\n".join(entries), 1)
makefile.write_text(m)

cfg = defconfig.read_text()
cfg = re.sub(r"^CONFIG_CPU_FREQ_DEFAULT_GOV_[A-Z0-9_]+=.*\n", "", cfg, flags=re.M)
cfg = re.sub(r"^# CONFIG_CPU_FREQ_DEFAULT_GOV_[A-Z0-9_]+ is not set\n", "", cfg, flags=re.M)
for symbol, name, filename in added:
    cfg = re.sub(rf"^(?:CONFIG_CPU_FREQ_GOV_{symbol}=.*|# CONFIG_CPU_FREQ_GOV_{symbol} is not set)\n", "", cfg, flags=re.M)
cfg += "\n# MX Guardian CPUFreq governors\nCONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL=y\n"
for symbol, name, filename in added:
    cfg += f"CONFIG_CPU_FREQ_GOV_{symbol}=y\n"
defconfig.write_text(cfg)

print("MX Guardian governors added:")
for symbol, name, filename in added:
    print(f"  {name}: {filename}")
print("Not available in pinned source collection: " + (", ".join(missing) if missing else "none"))
print("Not implemented as standalone CPUFreq governors: interactiveX, lionheartX, lazy, zzmoove, hotplug, slp, intellimm")
