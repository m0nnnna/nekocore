# Core patches

Patches against AzerothCore (the commit in `build/azerothcore.lock`) that
nekocore needs and that can't be done from a module hook.
`tools/build/prepare-server.sh` applies them in order (skipping any already
applied), on the dev box and in CI; `--check` confirms `server/` carries them.

- `0000-solo-lfg-toggle.patch` -- `LFGMgr::IsSoloLFG` / `ToggleSoloLFG`, the
  core hook mod-solo-lfg calls to let one player queue for a dungeon.
- `0001-LearnTalent-count-spent-points-per-tab.patch` -- `Player::LearnTalent`
  counted "points spent in this tree" via the spell-keyed, last-writer-wins
  `sTalentSpellPosMap`, which misattributes every shared spell to the TBC
  era tab and rejects tier >= 2 talents in Vanilla/stock tabs. (Fixed;
  the investigation write-up that used to live in docs/ was removed once
  the fix landed in commit f6339be.)
- `0002-era-copies-of-id-checked-talents.patch` -- the core recognises a
  few spells by hardcoded WotLK id, which the Vanilla/TBC copies
  (`build_era_spells.py`, id + 300000 / + 400000) never match: Spirit of
  Redemption (20711) in `Unit::Kill`, and Bestial Wrath (19574) / The Beast
  Within (34692 -> 34471) in `Aura::HandleAuraSpecificMods`, plus Bestial
  Wrath's crowd-control immunity in `SpellInfo`, `SpellInfoCorrections` and
  `Spell::CheckCasterAuras`. A module hook cannot reach any of these: they
  run inside the death path and the aura/immunity setup.
- `0003-era-pushback-resist-is-a-chance.patch` -- 1.12/2.4 rolled the summed
  pushback-resist value (Concentration Aura, Spiritual Focus, Healing Focus,
  Fel Concentration, Earth Shield, ...) as a chance to lose no casting time
  at all. 3.0 kept the same DBC fields but made them a flat reduction of the
  delay. `Spell::Delayed` / `Spell::DelayedChannel` now roll for era copies
  (id 300000-499999), so a Vanilla/TBC character gets its era's mechanic.
  `build_era_spells.py` takes the era tooltip for those spells to match.
- `0004-vanilla-spell-level-penalty.patch` -- `Unit::CalculateLevelPenalty`
  gives Vanilla copies (id 300000-399999) 1.12's rule: only spells below
  level 20 lose spell power, 3.75% per level short. The stock function also
  scales by `(SpellLevel + 6) / level` (a 2.0 downranking penalty) and skips
  spells whose MaxLevel is not above their level. It pairs with the 1.12
  coefficients `build_era_spells.py` derives for Vanilla copies.
- `0005-era-consumables.patch` -- two consumable rules the core hardcodes
  at 3.x: Battle/Guardian elixir exclusivity (`Aura::CanStackWith`, added in
  2.1) and the potion lockout until combat ends (`Spell::SendSpellCooldown`).
  Both now ask `g_nekoUnitIsVanilla` (installed by `src/EraConsumables.cpp`)
  and a Vanilla-era player gets 1.12's rules: elixirs and flasks coexist, and
  a potion starts its item cooldown on use. TBC and WotLK are unchanged.
- `0006-era-exorcism-crit-and-holy-resist.patch` -- two 3.x rules in
  `Unit.cpp`. Exorcism's guaranteed crit on undead and demons
  (`Unit::SpellTakenCritChance`, by category 19) is skipped for the era
  copies (id 300000-499999), which roll crit normally as in 1.12/2.4. And
  `Unit::CalcAbsorbResist` no longer partially resists a Vanilla-era
  player's Holy damage on creatures (`g_nekoUnitIsVanilla`, from 0005):
  1.12 never partially resisted Holy.
- `0007-vanilla-hit-crit-percent.patch` -- 1.12's "+1% hit/crit" items
  became 3.x rating at level 60's ratio (7597 "Increased Critical 14",
  15464 "Increased Hit Rating 10", ...), so below 60 the level-scaled gt
  table made them worth far more than 1%, and 3.0's merged masks let melee
  crit/hit boost spells and spell crit/hit boost melee. For a Vanilla-era
  player (`g_nekoUnitIsVanilla`, from 0005) `Player::GetRatingMultiplier`
  reads CR_HIT_*/CR_CRIT_* at level 60 at every level (10 hit, 8 spell hit,
  14 crit per 1%), and `UpdateRating` drops the part of each bonus its 1.12
  form did not give. `g_nekoVanillaExcludedRatings` (installed by
  `src/EraHitCrit.cpp`) names that part per spell aura, item stat or
  enchant; the core tallies it on every apply/remove in every era, so an
  era change only needs `UpdateAllRatings`. TBC and WotLK are unchanged.
