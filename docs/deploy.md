# Go-live checklist

> **Superseded opening (kept because the rest of this section still applies).**
> This said "this box **is** the production realm ... nothing moves to another
> machine", which was true up to 2026-09-18. It is not any more: since drop 1
> the realm runs on a **separate production box** that installs from
> `Y:\nekocore-deploy\` (see "Deploy drops on the share" at the end). This box
> (`C:\nekocore`) is the **dev box** -- it builds the images, owns
> `acore_world`, and runs its own local realm for testing. Its
> `acore_auth.realmlist` row is *supposed* to be the dev row; the prod row
> belongs on the production box. "Deploying" now means
> `sh tools/server/build_deploy_drop.sh` here, then
> `update-from-mount.sh` there. The steps below describe the in-place go-live
> on a single box and are still the reference for what the drop scripts
> automate.

## Topology (as verified 2026-09-18, single-box era)

```
players ──> 108.174.48.199 (Ubuntu VPS, nginx + VPN proxy)
              ├─ 3724  ──> this box  ac-authserver     (forwarded, open)
              ├─ 8085  ──> this box  ac-worldserver    (forwarded, open)
              ├─ 80/443 nginx: wow.nekos.farm currently 404s here
              └─ 8088  NOT forwarded (neko-website unreachable from outside)

LAN  ──> 192.168.1.8  = this box seen through the VPN (MySQL 3306 reachable;
                        3724/8085 NOT reachable from this box itself -- test
                        from a real LAN client after go-live)
         192.168.1.7  = mail relay; wow.nekos.farm resolves here internally
         192.168.0.10 = this box's own LAN address (dev realmlist row)
```

## The one deliberate difference between dev and prod

`acore_auth.realmlist` row 1.

| | name | address | localAddress | mask |
|---|---|---|---|---|
| dev | AzerothCore | 192.168.0.10 | 127.0.0.1 | 255.255.255.0 |
| **prod** | NekoCore | 108.174.48.199 | 192.168.1.8 | 255.0.0.0 |

The prod address is the VPS proxy's **IP**, not `wow1.nekos.farm`: the authserver
resolves `address` itself, on the box, and hands clients the resulting IP -- a name
the box resolves to an internal address would send outside players somewhere they
can't reach. (Players' own `realmlist.wtf` keeps the hostname; their DNS is public.)

The prod row is `data/sql/db-auth/base/nekocore_realmlist.sql` (identical to
`Documents\scripts\wow\nekocore connection.sql`). Apply it with

```
sh tools/server/apply_realmlist.sh          # idempotent; run after any db-import / restore
```

A fresh `ac-db-import` or a dump restore brings the dev row back, so this
script is the last step of every deploy, not a one-off. The player side of
the address is `REALM_ADDRESS` in `tools/install_patch/install_client.py`
(baked into the patch zip's `Data/enUS/realmlist.wtf`) and `NEKO_REALM_ADDRESS`
(the site's "Server address" box, default `wow1.nekos.farm`); keep all three
in sync. `website/downloads/realmlist.wtf` still ships but nothing links it.

## Steps

1. **Freeze**: post a maintenance note in `/admin/`, `docker compose stop
   ac-worldserver ac-authserver` from `server/` (characters DB stops changing).
2. **Backup** all three DBs -- `tools/server/backup_db.sh acore_auth server`,
   `acore_characters`, `acore_world` (gzipped into `server/backups/`).
3. **Module SQL** if anything under `data/sql` or `third-party/` changed:
   `python tools/server/sync_module.py` (also stages the third-party
   `tp_*.sql`), then `tools/server/apply_module_sql.sh server`.
4. **Realm row**: `sh tools/server/apply_realmlist.sh`.
5. **Downloads**: the site offers **only the patch**, which also sets the
   realmlist, and a "Server address" box for setting it by hand -- no full client -- players bring their own 3.3.5a enUS client. Its "Get the
   patch" button serves `downloads/nekocore-patch.zip` (`NEKO_PATCH_URL`;
   point it elsewhere if a real patcher replaces the zip). Build it with
   `python tools/install_patch/install_client.py --wotlk-root <master client
   copy> --bundle-zip website/downloads/nekocore-patch.zip` -- the merged
   `patch-Z.mpq` (era talents + era spells + mod-uac + Prestige) and the
   player addons. `DEV_ONLY_ADDONS` in `install_client.py` (NekoTalentDebug)
   goes to the dev client and nowhere else. See `docs/third-party-mods.md`.

   **Rebuild it whenever anything under `data/generated/` or
   `client-patch/Interface/` changes** -- the client's DBCs must match the
   ones the realm bind-mounts. Both drop builders (`build_deploy_drop.sh`,
   `build_website_drop.sh`) refuse to run while the zip is missing or older
   than either (`tools/server/check_patch_zip.sh`), and both copy it into the
   drop; `update-from-mount.sh` / `update-website-from-mount.sh` put it on the
   box and delete any leftover `downloads/nekocore.zip`. A patch-only change
   needs just the website drop -- no realm restart.

   `build_client_zip.py` (a full patched client) still works for handing
   someone a client directly, but nothing publishes it.
6. **Website**: `docker compose build neko-website && docker compose up -d`
   from `server/` (also starts auth/world again).
7. **Expose the site** -- pick one:
   - on the VPS nginx: `server_name wow.nekos.farm; location / { proxy_pass
     http://<vpn-addr-of-this-box>:8088; proxy_set_header Host $host;
     proxy_set_header X-Forwarded-Proto $scheme; }` (the container honours
     `X-Forwarded-Proto`, so emailed links come out `https://`), **or**
   - forward 8088 on the VPS like 3724/8085 and link to `http://…:8088`.
   Then retire the Laragon copy so there is one site.
8. **Secrets** (worth doing at the same time): `DOCKER_DB_ROOT_PASSWORD` in
   `server/.env` is still `password`. Changing it means `ALTER USER` inside
   `ac-database` *and* updating `.env` (the ac-* services and neko-website
   all read the same variable), then `docker compose up -d`.

## Restart order matters (core rev e13f1ef+, AzerothCore #26658)

The authserver sets `realmlist.flag |= 2` (OFFLINE) on *its* startup and only
a worldserver startup clears it. So: `docker compose restart ac-authserver`
while the world is up leaves the realm showing **offline** in the client
until the world restarts. Either restart both (`docker compose restart
ac-authserver ac-worldserver`, auth first) or clear it by hand:
`UPDATE acore_auth.realmlist SET flag = 0 WHERE id = 1`. A worldserver that
aborts mid-startup leaves `flag = 1` behind, which the authserver then ORs
into `3` and refuses to list at all (crash-loops with "No valid realms") --
same fix.

## Verify after every deploy

- `docker logs ac-worldserver | grep ready`; `docker ps` shows neko-website healthy
- Log in from **outside** (public address) and from a **LAN** client (gets
  192.168.1.8 via the /8 mask) -- talent frame opens (DBC bind mounts)
- Site: realm status both green, staff login lands on the post list, post a
  news item, RSS validates, register a throwaway account and click the mail
  link, `/downloads/nekocore-patch.zip` serves and contains `Data/enUS/realmlist.wtf`
- `SELECT address, localAddress FROM acore_auth.realmlist` still shows prod

## Rollback

`apply_realmlist.sh` in reverse is the dev row (see table); restore a dump
with `zcat server/backups/<db>/<file>.sql.gz | docker exec -i ac-database
mysql -uroot -p<pw> <db>` then re-run `apply_realmlist.sh`.

## Still manual on a truly fresh box

Not needed here, but if `server/` is ever rebuilt from scratch: its three
local commits have no remote (push `server` to your own fork first), the
gitignored inputs must be copied by hand (`data/generated/*.dbc`,
`client-patch/progression-optional/*.dbc`, `server/env/dist/{etc,data}`,
`modules/mod-xp-changer`, `modules/mod-live-reload`, `website/docker.env`,
`website/downloads`), and `docker save`/`load` the four locally built images
rather than re-compiling.

The third-party mods are reproducible instead of hand-copied:
`python tools/third_party/fetch.py` (pinned clones + patches), then
`build_mod_dbcs.py`, `stage_third_party.py`, `sync_module.py` -- the full
order is in `docs/third-party-mods.md`. Two `worldserver.conf` settings
they need (`PlayerStart.CustomSpells = 1`, `Warden.Enabled = 1`) live in
the gitignored `etc/`, so re-set them on a fresh copy. Same for the solo
difficulty tuning in `etc/modules/AutoBalance.conf`: every
`AutoBalance.InflectionPoint*.CurveFloor` (dungeon, heroic, raid, raid
heroic) is `0.5` on the live box (solo = 56% of a full group's boss
health/damage instead of the module's default 12%); the `.dist` file still
says `0.0`.

Combat logging (`src/NekoLog.cpp`, website Logs/Rankings) needs nothing
beyond the module SQL that `apply_module_sql.sh` already applies
(`nekolog.sql`, `nekolog_rank.sql`); `Nekocore.Log.*` defaults to on.

## How a .sql file reaches a database (and what stops it wrecking one)

The short version: **the only thing that ever migrates a database is a
deliberate `ac-db-import` run.** Neither server does it, so no restart can
change your schema.

### The path

1. You write the file in this repo under
   `data/sql/db-<auth|characters|world>/base/*.sql`. **The directory name is
   the only thing that picks the database** -- nothing inside the file does.
   A file in the wrong folder runs against the wrong DB.
2. `python tools/server/sync_module.py` copies `data/sql/` into
   `server/modules/nekocore/data/sql/` as real files. Not optional and not
   cosmetic: Docker's build context cannot follow the junction, which once cost
   a whole session of silently-empty builds (see the README).
3. `sh tools/server/apply_module_sql.sh server` does two steps in one call:
   `docker compose build ac-db-import`, then
   `docker compose up --exit-code-from ac-db-import ac-db-import`. The rebuild
   is the step people skip -- without it you run whatever SQL was baked into
   the last image, which may predate everything you just wrote.
4. AzerothCore's updater walks every module's `data/sql/db-*/{base,updates}/`
   and applies what it hasn't seen.

On the production box the same thing happens inside
`update-from-mount.sh`, which runs `ac-db-import` once after loading the
images (its step "applying module SQL"). So module SQL rides along with a
normal drop update -- `RESTORE_WORLD=1` is only for wholesale world-DB content
replacement, not for getting a new table or NPC out there.

### What protects the databases

**Neither server applies SQL.** `worldserver.conf` says
`Updates.EnableDatabases = 7`, but `AC_UPDATES_ENABLE_DATABASES=0` is baked
into the upstream worldserver image and environment beats config. The startup
log says so out loud:

```
> Config: Found config value 'Updates.EnableDatabases' from environment variable 'AC_UPDATES_ENABLE_DATABASES'.
> AUTOUPDATER: Automatic database updates are disabled for all databases in the config! This is not recommended!
```

That warning is a *good* thing here. It means one door to the schema, opened on
purpose, instead of every restart being a migration.

**Applied files are hash-tracked.** Each database has an `updates` table:
`name` (primary key), `hash` (SHA1 of the file), `state`
(`RELEASED|CUSTOM|MODULE|ARCHIVED|PENDING`), `timestamp`, `speed`. Ours land as
`MODULE`. A file whose name and hash are already there is skipped, so
re-running `apply_module_sql.sh` is cheap and safe.

**The sharp edge: editing a `base/` file re-runs the whole file.** The hash
changes, so the updater reapplies it from the top -- observed live on the
2026-09-22 deploy:

```
>> Applying update "nekocore_challenge.sql" '89F070B'...
>> Reapplying update "nekolog.sql" '32D89BD' -> '13FCB07' (it changed)...
```

So everything in `base/` must be safe to run again, every time it is touched.
The rules that follow from that, and which this repo's files already keep:

- `CREATE TABLE IF NOT EXISTS`, never bare `CREATE TABLE`.
- To change rows, `DELETE` a range **we own** then `INSERT` it -- e.g.
  `DELETE FROM creature WHERE guid BETWEEN 5300722 AND 5300723`. Never an
  unqualified `DELETE FROM`, never `TRUNCATE`.
- **No `ALTER TABLE ... ADD COLUMN`.** MySQL 8 has no `IF NOT EXISTS` for it,
  so the second run errors and aborts the import. This is exactly why the
  challenge/combat-log link is a `log_run_id` column on the *new*
  `nekocore_challenge_run` table rather than a `challenge_id` column added to
  the existing `nekolog_run`.
- No `DROP` of anything a player owns. A derived table that rebuilds itself
  (`nekolog_rank`) may say so in a comment; real data may not.
- Keep one concern per file. A reapplied file re-runs *everything* in it.

**Failures are actually noticed.** `--exit-code-from ac-db-import` exists
because a plain `docker compose up` exits 0 no matter how the service died --
a bad SQL file would otherwise look exactly like success.

**Back up first, and freeze first.** `tools/server/backup_db.sh <db> server`
for all three before any import (it runs `mysqldump` inside the container, so
it needs nothing installed). Stop `ac-worldserver`/`ac-authserver` first so the
characters DB is not moving under the import. Note that
`--exit-code-from` implies `--abort-on-container-exit`: when `ac-db-import`
finishes, Compose stops the containers **that same command started**. With
`ac-database` already up from an earlier `up` it is left alone (verified on the
2026-09-22 deploy -- only `ac-db-import` stopped), but do not count on that
from a cold stack.

**Restarting the worldserver alone is cheap; restarting the authserver is
not.** The authserver sets `REALM_FLAG_OFFLINE` on *every* realm at startup
(`authserver/Main.cpp`) and each worldserver only clears its own on the
`UpdateUptimeInterval` tick -- 10 minutes here, measured at 480s on
2026-09-22. So a code-only worldserver deploy has no offline window at all,
while bouncing both can grey the realm out in the client list for up to ten
minutes. `UPDATE realmlist SET flag = 0 WHERE id = 1;` clears it immediately
once the worldserver reports `World Initialized`.

### The five-line version

```
# edit data/sql/db-<db>/base/<file>.sql   (idempotent, non-destructive, one concern)
python tools/server/sync_module.py
sh tools/server/backup_db.sh acore_auth server && ... characters && ... world
cd server && docker compose stop ac-worldserver ac-authserver
sh ../tools/server/apply_module_sql.sh .    # build + run ac-db-import, exit code honoured
docker compose up -d ac-authserver ac-worldserver
```

## Who owns which database (the update contract)

| DB | Owner | How changes reach live |
|---|---|---|
| `acore_world` | dev box -- an artifact, like the images | replaced wholesale from the drop's dump (`RESTORE_WORLD=1`). Never edit it on live: no `.npc add`, no GM `.reload`-and-forget -- do it here and ship it. |
| `acore_characters` | live (players) | never overwritten after launch; only module SQL via `ac-db-import` (tracked in its `updates` table, idempotent). |
| `acore_auth` | live (accounts, `web_news`, tokens, realm row) | same as characters; `apply_realmlist.sh` re-asserts the prod row. |

This is why neither MySQL needs to accept connections from the other machine:
the share carries the dump, the box applies it, and the two live-owned
databases only ever receive the same migrations the dev database already went
through. `RESTORE_DB=1` (all three) is a pre-launch-only reset.

## Deploy drops on the share

`Y:\nekocore-deploy\` (`\deploy\deploy`) holds the full production drop --
images, DB dumps, runtime tree, `install-from-mount.sh` / `update-from-mount.sh` /
`update-website-from-mount.sh` (website only: loads `images/website.tar` and recreates
`neko-website` without stopping the realm; its dev-side pair is `build_website_drop.sh`).
Its README covers running it on the box and carries a per-drop changelog.
Rebuild it with `sh tools/server/build_deploy_drop.sh` (the box scripts are
versioned in `tools/server/` and copied onto the share by it). It copies every
`data/generated` DBC that `server/docker-compose.override.yml` mounts, read from
the override itself (drop 4 and earlier hard-coded three and missed
`SkillLineAbility.dbc`/`SpellRange.dbc`). `wow1.nekos.farm` is the realm's
public name (resolves to the VPS); `wow.nekos.farm` is the website, routed
through the VPS nginx to this stack's port 8088.
