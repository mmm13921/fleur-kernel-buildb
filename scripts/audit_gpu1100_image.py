#!/usr/bin/env python3
from pathlib import Path
import struct, sys, zlib
raw = Path(sys.argv[1]).read_bytes()
if raw[:2] != b"\x1f\x8b":
    raise SystemExit("GPU1100: Image.gz-dtb is not gzip")
dec = zlib.decompressobj(31)
kernel = dec.decompress(raw)
if not kernel or not dec.unused_data:
    raise SystemExit("GPU1100: kernel or appended DTB missing")
if struct.pack("<3I", 1100000, 100000, 110000) not in kernel:
    raise SystemExit("GPU1100: compiled GPU OPP0 record not found")
for value, label in ((1100000, "GPU reference frequency"), (100000, "GPU reference voltage"), (1950, "GPU reference power")):
    if struct.pack("<I", value) not in kernel:
        raise SystemExit(f"GPU1100: compiled {label} value missing")
print("GPU1100 IMAGE AUDIT PASSED")
print("GPU OPP0: 1100 MHz / VGPU 1.000 V / VSRAM 1.100 V")
