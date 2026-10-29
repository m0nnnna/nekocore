-- Anvilrage Medics (General Angerforge, BRD): two of them healed him from 25% back to full in seconds
-- (Heal every 4-6s on anyone missing 2500, Prayer of Healing every 6-9s) and a lone player could never
-- out-damage that. Heal now 16-20s, Prayer 30-40s after a 20-25s wait; medics less tanky and hit softer.
UPDATE `smart_scripts` SET `event_param1`=20000,`event_param2`=25000,`event_param3`=30000,`event_param4`=40000
 WHERE `entryorguid`=8894 AND `source_type`=0 AND `id`=2;
UPDATE `smart_scripts` SET `event_param3`=16000,`event_param4`=20000
 WHERE `entryorguid`=8894 AND `source_type`=0 AND `id`=3;
UPDATE `creature_template` SET `HealthModifier`=1.5,`DamageModifier`=1.5 WHERE `entry`=8894;
