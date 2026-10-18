-- #76 Desolace "Book of the Ancients": the Gem of the Serpent opens the Serpent
-- Statue (177673), whose SmartAI summons the "Naga Beam" trap GO (177705), and the
-- Naga Beam's SmartAI (event JUST_CREATED) summons Lord Kragaru (12369).
-- mod-individual-progression's zone_desolace.sql ships that smart_scripts row, but
-- gameobject_template 177705 has AIName '' so SmartGameObjectAI never loads and the
-- row never fires. Enable it.
UPDATE `gameobject_template` SET `AIName` = 'SmartGameObjectAI' WHERE `entry` = 177705 AND `AIName` = '';
