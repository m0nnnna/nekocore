# Releases, updates and backups

The realm box no longer installs from a drive. GitHub builds the server and
the realm box updates itself with one command, `nekocore`:

```
dev box ── git push master ──> GitHub Actions ──> images :edge + "edge" prerelease
        ── nekocore publish v1.2.3 ──> tag ──> images :v1.2.3/:stable + release v1.2.3
        └─ (same command) game data ──> private repo m0nnnna/nekocore-data, release v1.2.3 / edge

realm box ── nekocore update [--edge] ──> pulls all of it, backs up, swaps, checks, rolls back on failure
```

## What lives where

| What | Built by | Where it goes |
|---|---|---|
| worldserver / authserver / db-import / website images | GitHub Actions, from a clean checkout | `ghcr.io/m0nnnna/nekocore-*` (`:edge`, `:sha-<commit>`, `:v1.2.3`, `:stable`) |
| runtime bundle: compose files, server and module confs, Lua scripts, module SQL, ops scripts, `nekocore` itself | GitHub Actions | `nekocore-runtime.tar.gz` on the release |
| game data: the generated DBCs, mod-individual-progression's optional DBCs, the player patch zip | the dev box (needs the game client) | `nekocore-gamedata.tar.gz` on the **private** `m0nnnna/nekocore-data` release of the same tag |
| `acore_world` (the dev box owns it, see `deploy.md`) | the dev box, `--world` | `acore_world.sql.gz` on the same private release |
| accounts, characters, the box's passwords | the realm box | stay on the realm box (`backups/`, `server/.env`, `website/docker.env`, `nekocore.env`) |

The game data never goes on GitHub's build machines or in the public repo:
it is made from Blizzard's client files.

GitHub builds the images from exactly what the repo describes:

- AzerothCore at `build/azerothcore.lock`
- `core-patches/` (0000 is mod-solo-lfg's core hook)
- the modules pinned in `tools/third_party/fetch.py` with `third-party-patches/`
- our own `modules/` and `src/`

`tools/build/prepare-server.sh` puts that tree together; it is the same on
the dev box and in CI.

## Dev box

```bash
tools/build/prepare-server.sh            # server/ from the repo (safe to re-run)
tools/build/prepare-server.sh --check    # is server/ exactly what CI will build?
bin/nekocore build                       # prepare + docker compose build (images :local)
```

Change a module pin, a core patch or `src/`, then commit and push. Every push
to `master` builds edge (about an hour on GitHub's runners; ccache makes later
ones faster). Watch it with `gh run watch`.

**Edge game data:** after rebuilding the DBCs/patch (`install_client.py`), run:

```bash
bin/nekocore publish --edge           # DBCs + patch -> the private "edge" release
bin/nekocore publish --edge --world   # ... and the world DB from the running dev realm
```

**A stable release:**

```bash
git push                              # CI builds what is on GitHub
bin/nekocore publish v1.2.3 --world   # checks, tags, uploads the game data, pushes the tag
gh run watch                          # Actions builds the images and the release
```

`publish` refuses unless:

- the tree is clean
- `prepare-server.sh --check` passes
- HEAD is pushed

That way the release is what you tested. Leave `--world` out when the world DB
didn't change; the box keeps its own. `--notes FILE` uses your own tag message
for the release notes.

`publish` creates the private `m0nnnna/nekocore-data` repository on first use.

## Realm box

Settings live in `/opt/nekocore/nekocore.env`:

```
NEKOCORE_REPO=m0nnnna/nekocore
NEKOCORE_DATA_REPO=m0nnnna/nekocore-data
NEKOCORE_CHANNEL=stable              # what a bare `nekocore update` follows
GITHUB_TOKEN=github_pat_...          # fine-grained token, read-only "Contents" on nekocore-data
                                     # (and on nekocore while that is private); also used for ghcr.io
BACKUP_KEEP=48                       # dumps kept per database
NEKOCORE_TOTP_SECRET=...             # filled in by the first update from the old worldserver.conf
```

```bash
nekocore status                  # version, channel, images, players online, last backup
nekocore update                  # newest stable release
nekocore update --edge           # newest master build
nekocore update --check          # exit 10 = an update is waiting
nekocore rollback                # back to what ran before the last update (files + images)
nekocore channel edge            # make bare `update` follow edge
nekocore backup                  # all three DBs -> backups/<db>/<db>_YYYYmmdd_HHMMSS.sql.gz
nekocore backups                 # list them
nekocore restore latest acore_characters
nekocore cron                    # hourly auth/characters, daily world backups; nightly update when empty
nekocore logs [worldserver|authserver|website|database]
nekocore restart
```

What `update` does:

1. It finds the release (`releases/latest` for stable, the `edge` release
   for edge) and downloads the runtime bundle and the game data, checking
   their checksums.
2. It pulls the images. If anything so far fails, nothing on the box has
   changed.
3. It backs up all three databases (`--no-backup` skips that) and keeps a
   copy of the managed files in `.previous.tar.gz`.
4. It installs the bundle. `server/.env`, `website/docker.env`, the client
   data and `backups/` are never touched. The TOTP secret is put back into
   `worldserver.conf`/`authserver.conf`.
5. It stops the realm. If the release carries a world DB it hasn't restored
   yet, that replaces `acore_world` (`--no-world` keeps the old one). Then it
   runs `ac-db-import` for module SQL and applies the realmlist row
   (`REALM_*` in `server/.env`).
6. It starts everything and waits for the worldserver's `ready...`. If the
   worldserver crashes or fails to start, the files and images go back
   automatically. The databases stay as they are; `nekocore restore latest
   <db>` puts the pre-update backup back.

`update` won't restart a realm with players online unless you answer yes or
pass `--yes`. The cron job only updates when nobody is on.

### Moving the existing box over (once)

The box installed from the drive already has everything `nekocore` needs:

```bash
# on the dev box, after the first stable release (or edge) is out:
scp bin/nekocore realmbox:/opt/nekocore/bin/nekocore     # or download it from the release
# on the realm box:
apk add curl                                             # Alpine; docker + compose are there already
cat >> /opt/nekocore/nekocore.env <<EOF
GITHUB_TOKEN=github_pat_...
EOF
chmod 600 /opt/nekocore/nekocore.env
/opt/nekocore/bin/nekocore update --no-world    # or --edge
```

The first update moves this box's settings into `server/.env` and
`nekocore.env`, where updates leave them alone:

- the realmlist row (from the database) becomes `REALM_*`
- the `extra_hosts` pin becomes `REALM_HOSTS_ENTRY`
- the TOTP secret becomes `NEKOCORE_TOTP_SECRET`

It also switches the containers to the ghcr.io images.
`nekocore rollback` goes back to the drop's images (still loaded) if you need
to.

### A new box

```bash
# docker, compose v2 and curl installed; as the user that runs the realm:
curl -fsSLo /tmp/nekocore https://raw.githubusercontent.com/m0nnnna/nekocore/master/bin/nekocore
GITHUB_TOKEN=github_pat_... sh /tmp/nekocore install     # writes /opt/nekocore, a random DB password
# edit server/.env (REALM_*), website/docker.env, then:
/opt/nekocore/bin/nekocore update --force --yes
```

Moving players to it: `nekocore backup` on the old box, copy the dumps over,
then `nekocore restore FILE acore_auth` and `... acore_characters`.

## Making the repository public

Nothing in the tracked tree carries a password, token or private address. The
remaining box-specific values are in each box's `server/.env`. Before
switching the repository to public:

- In the GitHub package settings, set the four `nekocore-*` packages to
  public too (otherwise boxes need `GITHUB_TOKEN` to pull them, which works
  but isn't needed).
- `m0nnnna/nekocore-data` stays private.

Older commits still mention the addresses that are now in `.env` (the public
VPS IP and LAN addresses). History was not rewritten.
