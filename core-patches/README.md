# Core patches

Patches against the `D:\AzerothCore` checkout that nekocore needs and that
can't be done from a module hook. Apply from the AzerothCore root with
`git apply <path>` after any core update, then rebuild `ac-worldserver`.

- `0001-LearnTalent-count-spent-points-per-tab.patch` -- `Player::LearnTalent`
  counted "points spent in this tree" via the spell-keyed, last-writer-wins
  `sTalentSpellPosMap`, which misattributes every shared spell to the TBC
  era tab and rejects tier >= 2 talents in Vanilla/stock tabs. See
  `docs/era-talent-wrong-tab-bug.md`.
