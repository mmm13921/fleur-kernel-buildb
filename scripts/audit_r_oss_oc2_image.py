#!/usr/bin/env python3
"""Audit the compiled Image.gz-dtb for the Fleur R-OSS 2.2 GHz big OPP."""
from pathlib import Path
import struct
import sys
import zlib

path = Path(sys.argv[1])
raw = path.read_bytes()
if raw[:2] != b"\x1f\x8b":
    raise SystemExit("R-OSS OC2 image audit: Image.gz-dtb is not gzip")

decoder = zlib.decompressobj(31)
kernel = decoder.decompress(raw)
dtb = decoder.unused_data
if not kernel or not dtb:
    raise SystemExit("R-OSS OC2 image audit: compressed kernel or appended DTB is missing")

MAGIC = b"\xd0\x0d\xfe\xed"

def parse_fdt(blob, base):
    if blob[base:base + 4] != MAGIC or base + 40 > len(blob):
        return None
    header = struct.unpack_from(">10I", blob, base)
    total, off_struct, off_strings = header[1], header[2], header[3]
    size_strings, size_struct = header[8], header[9]
    if (
        total < 40
        or base + total > len(blob)
        or off_struct + size_struct > total
        or off_strings + size_strings > total
    ):
        return None

    strings = blob[base + off_strings:base + off_strings + size_strings]
    pos = base + off_struct
    end = pos + size_struct
    stack = []
    result = {"cpu6": {}, "cpu7": {}, "dvfsp": {}}

    while pos + 4 <= end:
        token = struct.unpack_from(">I", blob, pos)[0]
        pos += 4

        if token == 1:  # FDT_BEGIN_NODE
            name_end = blob.find(b"\0", pos, end)
            if name_end < 0:
                raise SystemExit("R-OSS OC2 image audit: malformed FDT node")
            name = blob[pos:name_end].decode("ascii", errors="replace")
            pos = (name_end + 4) & ~3
            stack.append(name)

        elif token == 2:  # FDT_END_NODE
            if stack:
                stack.pop()

        elif token == 3:  # FDT_PROP
            if pos + 8 > end:
                raise SystemExit("R-OSS OC2 image audit: truncated FDT property")
            length, nameoff = struct.unpack_from(">II", blob, pos)
            pos += 8
            if pos + length > end or nameoff >= len(strings):
                raise SystemExit("R-OSS OC2 image audit: invalid FDT property")
            name_end = strings.find(b"\0", nameoff)
            if name_end < 0:
                raise SystemExit("R-OSS OC2 image audit: invalid FDT property name")
            name = strings[nameoff:name_end].decode("ascii", errors="replace")
            value = blob[pos:pos + length]
            node = stack[-1] if stack else ""

            if node == "cpu@102" and name == "clock-frequency":
                result["cpu6"][name] = value
            elif node == "cpu@103" and name == "clock-frequency":
                result["cpu7"][name] = value
            elif node == "dvfsp@0011bc00" and name in ("change_flag", "B-table"):
                result["dvfsp"][name] = value

            pos = (pos + length + 3) & ~3

        elif token == 4:  # FDT_NOP
            continue
        elif token == 9:  # FDT_END
            break
        else:
            raise SystemExit(f"R-OSS OC2 image audit: unknown FDT token {token}")

    if any(result.values()):
        return result
    return None

found = None
offset = 0
while True:
    offset = dtb.find(MAGIC, offset)
    if offset < 0:
        break
    candidate = parse_fdt(dtb, offset)
    if candidate:
        found = candidate
        if (
            candidate["cpu6"].get("clock-frequency")
            and candidate["cpu7"].get("clock-frequency")
            and candidate["dvfsp"].get("B-table")
        ):
            break
    offset += 4

if found is None:
    raise SystemExit("R-OSS OC2 image audit: no valid Fleur device tree found")

expected_clock = struct.pack(">I", 2200000000)
for cpu in ("cpu6", "cpu7"):
    if found[cpu].get("clock-frequency") != expected_clock:
        actual = found[cpu].get("clock-frequency")
        actual_value = struct.unpack(">I", actual)[0] if actual and len(actual) == 4 else actual
        raise SystemExit(f"R-OSS OC2 image audit: {cpu} clock is {actual_value}, expected 2200000000")

flag = found["dvfsp"].get("change_flag")
if flag is None or len(flag) != 4 or struct.unpack(">I", flag)[0] != 1:
    raise SystemExit("R-OSS OC2 image audit: DVFSP DOE change_flag is not 1")

table = found["dvfsp"].get("B-table")
if table is None or len(table) != 16 * 4 * 4:
    raise SystemExit("R-OSS OC2 image audit: DVFSP B-table is missing or not 16 rows")

cells = struct.unpack(">64I", table)
rows = [tuple(cells[i:i + 4]) for i in range(0, 64, 4)]
if rows[0] != (2200, 105, 1, 1):
    raise SystemExit(f"R-OSS OC2 image audit: B-table top row is {rows[0]}")
if any(a[0] <= b[0] for a, b in zip(rows, rows[1:])):
    raise SystemExit("R-OSS OC2 image audit: B-table is not strictly descending")

print("R-OSS OC2 IMAGE AUDIT PASSED")
print("Image.gz-dtb CPU6 clock-frequency: 2200000000")
print("Image.gz-dtb CPU7 clock-frequency: 2200000000")
print("Appended DTB DVFSP: change_flag=1; B-table top row=2200/105; 16 descending rows")
print(f"Uncompressed kernel payload: {len(kernel)} bytes")
