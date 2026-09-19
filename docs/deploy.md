# Go-live checklist

This box **is** the production realm. "Deploying" means taking the stack in
`server/` from its dev identity to the real one and putting the website in
front of players. Nothing moves to another machine.

## Topology (as verified 2026-09-18)

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
| **prod** | NekoCore | wow1.nekos.farm | 192.168.1.8 | 255.0.0.0 |

The prod row is `data/sql/db-auth/base/nekocore_realmlist.sql` (identical to
`Documents\scripts\wow\nekocore connection.sql`). Apply it with

```
sh tools/server/apply_realmlist.sh          # idempotent; run after any db-import / restore
```

A fresh `ac-db-import` or a dump restore brings the dev row back, so this
script is the last step of every deploy, not a one-off. `website/downloads/
realmlist.wtf` says `set realmlist wow1.nekos.farm`; keep the two in sync.

## Steps

1. **Freeze**: post a maintenance note in `/admin/`, `docker compose stop
   ac-worldserver ac-authserver` from `server/` (characters DB stops changing).
2. **Backup** all three DBs -- `tools/server/backup_db.sh acore_auth server`,
   `acore_characters`, `acore_world` (gzipped into `server/backups/`).
3. **Module SQL** if anything under `data/sql` or `third-party/` changed:
   `python tools/server/sync_module.py` (also stages the third-party
   `tp_*.sql`), then `tools/server/apply_module_sql.sh server`.
4. **Realm row**: `sh tools/server/apply_realmlist.sh`.
5. **Downloads**: `website/downloads/nekocore.zip` (client) present next to
   `realmlist.wtf`; the site links to `/downloads/...`. Build the client
   payload with `python tools/install_patch/install_client.py --wotlk-root
   <master client copy> --bundle-zip website/downloads/nekocore-patch.zip`
   *before* zipping the client -- that puts the merged `patch-Z.mpq` (era
   talents + mod-uac + Prestige + Delves, ~350 MB) and the four addons in
   place. See `docs/third-party-mods.md`.
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
  link, `/downloads/nekocore.zip` and `/downloads/realmlist.wtf` serve
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
the gitignored `etc/`, so re-set them on a fresh copy.

## Deploy drops on the share

`Y:\nekocore-deploy\` (`\deploy\deploy`) holds the full production drop --
images, DB dumps, runtime tree, `install-from-mount.sh` / `update-from-mount.sh`.
Its README covers running it on the box. `wow1.nekos.farm` is the realm's
public name (resolves to the VPS); `wow.nekos.farm` is the website, routed
through the VPS nginx to this stack's port 8088.
