"""
Keeps the live module settings under version control.

server/ is its own git checkout (AzerothCore's) and is ignored by this repo,
so the module .conf files the realm actually runs on -- AutoBalance,
individualProgression, nekocore, ... in server/env/dist/etc/modules -- had no
history here. This copies them to server-conf/modules/ (tracked), and back.
Only the live *.conf files move; the .dist templates and *.bak copies don't.

    python tools/server/sync_module_confs.py          # live -> repo, then commit
    python tools/server/sync_module_confs.py --push   # repo -> live (new checkout)
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "server" / "env" / "dist" / "etc" / "modules"
TRACKED = REPO / "server-conf" / "modules"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push", action="store_true", help="copy repo -> live instead of live -> repo")
    args = ap.parse_args()
    src, dst = (TRACKED, LIVE) if args.push else (LIVE, TRACKED)
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.conf")):
        if (dst / f.name).exists() and (dst / f.name).read_bytes() == f.read_bytes():
            continue
        shutil.copy2(f, dst / f.name)
        print(f"{f.name}: {src.name} -> {dst.name}")


if __name__ == "__main__":
    main()
