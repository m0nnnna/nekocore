# Real player IPs behind NekoProxy (review later)

Status: **notes only, nothing changed yet.** Written 2026-10-01 while adding PROXY
protocol support to NekoProxy.

## The problem

`account.last_ip`, `logs_ip_actions`, IP bans and the account IP lock all see the
NekoProxy agent's WireGuard IP (e.g. `10.40.40.2`) instead of the player's address.
The agent is a userspace proxy: it accepts the player's connection on the VPS and opens
a new connection to authserver/worldserver, so AzerothCore only ever sees the agent.

## What already exists

AzerothCore already supports PROXY protocol, so no core patch is needed to read the
header itself:

- `server/src/server/shared/Network/Socket.h`: `ProxyReadHeaderHandler`
- `server/src/server/shared/Network/NetworkThread.h`: `HandleNewSocketsProxyReadingOnConnect`
- authserver: `EnableProxyProtocol = 1` (env `AC_ENABLE_PROXY_PROTOCOL=1`)
- worldserver: `Network.EnableProxyProtocol = 1` (env `AC_NETWORK_ENABLE_PROXY_PROTOCOL=1`)

Environment beats config in the ac-* images (see `deploy.md`), so the env var is the
reliable way to set it.

## Blockers before turning it on

### 1. NekoProxy sends v1, AzerothCore only reads v2 (NekoProxy change)

AzerothCore only parses the **binary v2** header (`Socket.h`: "v1 is not supported").
NekoProxy's per-rule PROXY toggle currently sends the **text v1** header, which
AzerothCore rejects as a "bad PROXY Protocol v2 signature" and drops the connection.
NekoProxy needs a v1/v2 choice per rule, and v2 for the auth (3724) and world (8085)
rules. That change belongs in the nekoproxy repo.

### 2. Login may hang if the header and the first packet arrive together (likely core patch)

From reading the code (not tested): the NekoProxy agent peeks at the client's first
bytes (scraper detection) before connecting to the backend. On the auth port those
bytes are the `AUTH_LOGON_CHALLENGE`, so the agent writes `[PROXY header][challenge]`
back to back and they can arrive in one read.

`ProxyReadHeaderHandler` consumes only the header (`ReadCompleted(len+16)`) and leaves
the challenge in `_readBuffer`. `AuthSession::Start()` then calls `AsyncRead()`, which
only calls `ReadHandler()` once *new* data arrives. The client is waiting for the
challenge reply, so nothing new ever arrives and the login hangs.

Worldserver is probably fine, because the server speaks first (`SMSG_AUTH_CHALLENGE`),
so the client sends nothing before the header has been processed.

Possible fixes (pick one):

- **Core patch (`core-patches/0003-…`):** after the PROXY header is processed, if
  `GetReadBuffer().GetActiveSize() > 0`, run `ReadHandler()` on the leftover bytes
  before the first `AsyncRead()`. The natural places are the end of
  `AuthSession::CheckIpCallback` and the equivalent spot in `WorldSocket`.
- **NekoProxy side:** skip the scraper peek on rules with PROXY protocol on, so the header
  always goes out before any client data exists. This makes coalescing much less
  likely but does not strictly guarantee it, so the core patch is the robust fix.

Test a real login through the proxy either way.

## Things to know once it's on

- **Every connection to those ports must carry the header.** AzerothCore has no
  "trusted proxy" list: with the flag on, a direct connection (LAN play, a website
  realm-status check, a health probe hitting 3724/8085) fails the header read and is
  dropped. Anything that talks to authserver/worldserver directly has to go through
  the proxy or use a separate realm/port.
- **IP lock / bans:** existing `account.last_ip` values are `10.40.40.2`. Accounts with
  the IP lock on will see a "new" IP on their first login after the switch. Existing IP
  bans on `10.40.40.2` (if any) would have banned everyone and need clearing.
- The realm row keeps the proxy's public IP as its address (commit b3d7f36). That is
  unaffected.

## Rollout order (when ready)

1. NekoProxy: add v2 (and update agents + controller).
2. NekoCore: fix blocker 2 (core patch and/or NekoProxy peek change), rebuild.
3. Set `AC_ENABLE_PROXY_PROTOCOL=1` and `AC_NETWORK_ENABLE_PROXY_PROTOCOL=1`, restart
   ac-authserver and ac-worldserver, **and at the same moment** turn on the PROXY toggle
   (v2) for the 3724 and 8085 rules, then Apply to Agents. Logins fail during the gap
   between the two.
4. Log in and check `SELECT last_ip FROM account WHERE username = '…'` shows a public IP.
