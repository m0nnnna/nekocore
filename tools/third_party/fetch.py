"""
Fetches the third-party AzerothCore mods nekocore ships with, pinned to
exact commits, into the (gitignored) places the rest of the tooling reads
them from.

Why a lock table in a script and not git submodules: the C++ modules have
to live inside the live AzerothCore checkout (`server/modules/`, which is
itself gitignored and its own repo -- see README), while the Lua/SQL/asset
mods are never compiled and just get staged from `third-party/` by
sync_module.py / install_client.py / stage_third_party.py. Submodules can't
point outside this repo's tree, and some of these are hundreds of MB of
assets that have no business in our history. One table, one command, reproducible.

Deliberately NOT in this list: araxiaonline/Delves (installed and working
on 2026-09-19, then removed: it's all level 82-85 content and the realm is
capped at 60 for the foreseeable future -- see git history before commit
"Drop Delves" to bring it back), and heyitsbench/mod-worgoblin. It's unmaintained,
needs a signature-patched Wow.exe on every client, and its 30 whole-file DBC
replacements (Spell, SkillLine*, TalentTab, ...) collide with the era-talent
DBCs and mod-individual-progression's optional set. Decided 2026-09-19.

After checkout, any third-party-patches/<name>/*.patch files are applied
in order (`git apply`, skipped if already applied). That's where fixes the
upstream repo doesn't have live -- e.g. Breaking-News-Rewrite still calls
the PQuery()/non-const CanPacketSend() API that AzerothCore removed.

Usage:
    python tools/third_party/fetch.py            # clone/update everything
    python tools/third_party/fetch.py mod-uac    # just one
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
THIRD_PARTY_DIR = REPO_ROOT / "third-party"
PATCHES_DIR = REPO_ROOT / "third-party-patches"
SERVER_MODULES_DIR = REPO_ROOT / "server" / "modules"

# name -> (git url, pinned commit, kind)
#   kind "cpp":  compiled AzerothCore module -> server/modules/<name>
#   kind "data": Lua/SQL/DBC/client assets   -> third-party/<name>
MODS: dict[str, tuple[str, str, str]] = {
    # Character-select "Breaking News" panel via Warden payload. C++ only.
    "Breaking-News-Rewrite": (
        "https://github.com/imagionationeditor/Breaking-News-Rewrite",
        "ca9909da667e878590ea37e193a114eb30178b37", "cpp"),
    # Any race / any class. C++ + SQL (auto-applied by db updater) + client patch-z.mpq
    # (CharBaseInfo/SkillRaceClassInfo/CharStartOutfit -- we merge those ourselves,
    # see tools/build_patch/build_mod_dbcs.py, rather than shipping its MPQ).
    "mod-uac": (
        "https://github.com/berubejd/mod-uac",
        "1df8053b34c7d031317b3824f441e863e9fd8c18", "cpp"),
    # `.chat` world-wide chat. C++ only.
    "mod-global-chat": (
        "https://github.com/azerothcore/mod-global-chat",
        "c6809a7faf631fff6b07d2af8d60b96e2ddc6467", "cpp"),
    # Prestige reset + Draft Mode. Lua (Eluna/ALE) + SQL (chars + world) +
    # server DBC overrides + client addon + patch-P.mpq (merged into ours).
    "Prestige-and-Draft-Mode": (
        "https://github.com/Youpeoples/Prestige-and-Draft-Mode",
        "7e745f61af72c5bb38f7f221e305852e521bb97c", "data"),
    # Mat-exchange NPC. One Lua file + one world SQL.
    "Acore_ExchangeNpc": (
        "https://github.com/55Honey/Acore_ExchangeNpc",
        "6e99cfc5cbcc2af6a90620a1224f9645397aab8a", "data"),
}


def dest_for(name: str) -> Path:
    kind = MODS[name][2]
    return (SERVER_MODULES_DIR if kind == "cpp" else THIRD_PARTY_DIR) / name


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def fetch(name: str) -> None:
    url, commit, kind = MODS[name]
    dest = dest_for(name)
    if kind == "cpp" and not SERVER_MODULES_DIR.is_dir():
        raise SystemExit(f"{SERVER_MODULES_DIR} missing -- the AzerothCore checkout isn't in place")
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--quiet", url, str(dest)])
    else:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True,
                              text=True, check=True).stdout.strip()
        if head == commit:
            print(f"{name}: already at {commit[:12]} ({dest})")
            apply_patches(name)
            return
        run(["git", "fetch", "--quiet", "origin"], cwd=dest)
    run(["git", "-c", "advice.detachedHead=false", "checkout", "--quiet", commit], cwd=dest)
    print(f"{name}: at {commit[:12]} -> {dest}")
    apply_patches(name)


def apply_patches(name: str) -> None:
    dest = dest_for(name)
    for patch in sorted((PATCHES_DIR / name).glob("*.patch")) if (PATCHES_DIR / name).is_dir() else []:
        already = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=dest,
                                 capture_output=True).returncode == 0
        if already:
            print(f"{name}: {patch.name} already applied")
            continue
        run(["git", "apply", str(patch)], cwd=dest)
        print(f"{name}: applied {patch.name}")


def main(argv: list[str]) -> int:
    names = argv or list(MODS)
    unknown = [n for n in names if n not in MODS]
    if unknown:
        raise SystemExit(f"unknown mod(s) {unknown}; known: {', '.join(MODS)}")
    for n in names:
        fetch(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
