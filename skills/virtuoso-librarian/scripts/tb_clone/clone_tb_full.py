"""CLI driver for cloning a TB + DUT hierarchy to another library.

Usage:
    python clone_tb_full.py SRC_LIB SRC_CELL DST_LIB

Or edit TARGETS below and run without args.

All the logic lives in tb_clone_lib.py (same directory); this file is
just glue. See the skill's references/testbench-duplication.md for the
"Cross-lib with full DUT hierarchy" section that explains why each
step exists.
"""
import os
import sys
from virtuoso_bridge import VirtuosoClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb_clone_lib import clone_tb_full


TARGETS = [
    # ("SRC_LIB", "SRC_CELL", "DST_LIB"),
]


def main():
    client = VirtuosoClient.from_env()
    jobs = TARGETS
    if len(sys.argv) == 4:
        jobs = [tuple(sys.argv[1:4])]
    if not jobs:
        print("Usage: python clone_tb_full.py SRC_LIB SRC_CELL DST_LIB")
        sys.exit(1)
    for src_lib, src_cell, dst_lib in jobs:
        clone_tb_full(client, src_lib, src_cell, dst_lib)


if __name__ == "__main__":
    main()
