-- One level gate per spell, whichever trainer sells it.
--
-- mod-individual-progression's zz_optional_limit_spells_to_expansion.sql
-- holds back spells an expansion added (Judgement of Wisdom -> 71,
-- Righteous Defense -> 61, the Libram-only Vanilla ranks -> 61, ...) by
-- raising ReqLevel, but only on the trainer ids it names. The same spell
-- sold by another trainer of that class kept its WotLK level, so a level 12
-- Vanilla paladin could buy Judgement of Wisdom at trainers 4 and 5 while
-- trainer 3 showed it at 71. zzz_nekocore_era_spells.sql then cloned those
-- rows onto the era copies, carrying the same mismatch along.
--
-- Rule: a spell gated past 60 by any trainer is gated at that level by all
-- of them. Written as a rule rather than a list so it also covers era
-- copies and whatever a later module update gates. Idempotent.
UPDATE `trainer_spell` t
JOIN (
    SELECT `SpellId`, MAX(`ReqLevel`) AS `gate`
    FROM `trainer_spell`
    GROUP BY `SpellId`
    HAVING MAX(`ReqLevel`) > 60 AND MIN(`ReqLevel`) <= 60
) g ON g.`SpellId` = t.`SpellId`
SET t.`ReqLevel` = g.`gate`
WHERE t.`ReqLevel` < g.`gate`;
