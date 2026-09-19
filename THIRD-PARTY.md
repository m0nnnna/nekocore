# Third-party credits

nekocore is built on other people's work. None of the projects below are
vendored into this repository -- `tools/third_party/fetch.py` clones each one
at a pinned commit from its own home, and what this repo adds is the glue
(merge tooling, staging, and a handful of compatibility patches under
`third-party-patches/`, which are offered back upstream where they apply).
Please credit and support the original authors, not us, for the features
themselves.

| Project | Authors | License | What it gives this realm |
|---|---|---|---|
| [AzerothCore](https://github.com/azerothcore/azerothcore-wotlk) | the AzerothCore community | AGPL-3.0 | the server itself |
| [mod-individual-progression](https://github.com/ZhengPeiRu21/mod-individual-progression) | ZhengPeiRu21 and contributors | AGPL-3.0 | per-character expansion progression (we run our own fork) |
| [mod-ale](https://github.com/azerothcore/mod-ale) (derived from [Eluna](https://github.com/ElunaLuaEngine/Eluna)) | AzerothCore / Eluna teams | GPL-3.0 | Lua scripting engine the mods below run on |
| [Breaking-News-Rewrite](https://github.com/imagionationeditor/Breaking-News-Rewrite) | Mojispectre (imagionationeditor); original [mod-breaking-news-override](https://github.com/azerothcore/mod-breaking-news-override) by Foe and the AzerothCore community | AGPL-3.0 | character-select news / server stats panel |
| [mod-uac](https://github.com/berubejd/mod-uac) | berubejd | see upstream repo | any race can play any class, with starter gear and trainers |
| [mod-global-chat](https://github.com/azerothcore/mod-global-chat) | AzerothCore community; based on [mod-world-chat](https://github.com/azerothcore/mod-world-chat) by wizzymore | MIT | `.chat` world-wide chat |
| [Prestige-and-Draft-Mode](https://github.com/Youpeoples/Prestige-and-Draft-Mode) | Youpeoples | MIT | prestige resets, Draft Mode, Chromie, the PrestigeSystem addon |
| [Delves](https://github.com/araxiaonline/Delves) | Araxia Online | MIT | thirteen custom single-player delve maps, boss scripts, DelvesTeleporter addon |
| [Acore_ExchangeNpc](https://github.com/55Honey/Acore_ExchangeNpc) | 55Honey (Honey) | AGPL-3.0 | the item / honor exchange NPC |

Also see `docs/third-party-mods.md` for how each is wired in, and each
project's own README for its full credits (several of them build on earlier
scripts by other people, listed there).

Game data (DBCs, maps, MPQ contents) derived from Blizzard's client is never
committed here -- see `.gitignore`. Each operator produces it from their own
client with the tools in this repo.
