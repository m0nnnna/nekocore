"""
Copies this repo's src/ into D:\\AzerothCore\\modules\\nekocore\\src so the
AzerothCore module build system can actually see it.

Why this exists, and why it's a COPY and not a live link: this module used
to be linked into D:\\AzerothCore\\modules\\nekocore via an NTFS junction
(mklink /J). That looked like it worked -- the host filesystem shows real
junction content, `dir`/`ls` on the Windows side sees every file fine -- but
Docker Desktop's build-context computation on this machine turns the
junction into a broken symlink pointing at the literal string "C:/nekocore"
inside the Linux build container (confirmed directly: `ls
/azerothcore/modules/nekocore` inside the build stage showed
`nekocore -> C:/nekocore`, a dangling link, not real content). The result:
EVERY worldserver build all session silently compiled nekocore's C++ as if
the module didn't exist at all -- no error, no warning, the module glob
just saw nothing there. EraTalentGate.cpp's server-side era-lock enforcement
has never actually been live because of this, despite the client-visible
(DBC-driven) parts of the feature genuinely working -- those ship via a
direct docker-compose volume bind mount, unrelated to compilation, which is
exactly why that part looked "confirmed working" while this didn't.

So: no more junction. Run this before every `docker compose build
ac-worldserver` (and, if data/sql changed, before every
`docker compose build ac-db-import`) to get this repo's CURRENT content
into the checkout as real files Docker can actually see. There's no build
hook that does this automatically yet -- it's a manual step for now.

Also syncs data/sql/ (module SQL, e.g. spell_script_names bindings) and
conf/ (module .conf.dist files) the same way, when present -- same
underlying problem, same fix.

After data/sql is recreated, the SQL of the Lua-only third-party mods
(third-party/, see tools/third_party/fetch.py) is staged into it as
tp_*.sql -- AzerothCore's updater only looks at data/sql under compiled
modules, and this is the one we control. See stage_third_party.stage_sql.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_third_party import THIRD_PARTY, stage_sql  # noqa: E402
# The live server checkout sits inside this repo folder (gitignored) -- see README.
DEST = REPO_ROOT / "server" / "modules" / "nekocore"

# (source dir in this repo, dest subdir name under DEST)
SYNC_DIRS = [("src", "src"), ("data/sql", "data/sql"), ("conf", "conf")]


def main() -> int:
    src_dir = REPO_ROOT / "src"
    if not src_dir.is_dir():
        raise SystemExit(f"missing {src_dir}")

    for rel_src, rel_dest in SYNC_DIRS:
        src = REPO_ROOT / rel_src
        if not src.is_dir():
            continue  # optional (e.g. data/sql doesn't exist until a module needs SQL)
        dest = DEST / rel_dest
        if dest.is_dir():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        copied = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
        print(f"synced {src} -> {dest} ({len(copied)} files: {', '.join(copied)})")

    if THIRD_PARTY.is_dir():
        stage_sql(DEST / "data" / "sql")
    else:
        print(f"note: {THIRD_PARTY} missing, third-party SQL not staged (tools/third_party/fetch.py)")

    gitkeep = DEST / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
