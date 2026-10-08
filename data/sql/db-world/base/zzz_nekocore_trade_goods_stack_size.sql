-- Trade goods stack to 20, not 10.
--
-- mod-individual-progression's zz_optional_item_stack_sizes.sql puts items
-- back to their Vanilla/TBC stack sizes, which caps profession materials
-- (meat, ore, leather, cloth bolts, enchanting dust and shards, flux,
-- engineering parts and explosives) at 10. Keep the rest of that file
-- (potions, elixirs, flasks, scrolls, poisons) and lift only its Trade
-- Goods (class 7) rows that it set to 10. Runs after it by name. Idempotent.
UPDATE `item_template` SET `stackable` = 20 WHERE `class` = 7 AND `entry` IN (
    723,   -- Goretusk Liver
    729,   -- Stringy Vulture Meat
    730,   -- Murloc Eye
    731,   -- Goretusk Snout
    769,   -- Chunk of Boar Meat
    1015,  -- Lean Wolf Flank
    1080,  -- Tough Condor Meat
    1081,  -- Crisp Spider Meat
    1468,  -- Murloc Fin
    2251,  -- Gooey Spider Leg
    2296,  -- Great Goretusk Snout
    2318,  -- Light Leather
    2319,  -- Medium Leather
    2672,  -- Stringy Wolf Meat
    2673,  -- Coyote Meat
    2674,  -- Crawler Meat
    2675,  -- Crawler Claw
    2677,  -- Boar Ribs
    2770,  -- Copper Ore
    2771,  -- Tin Ore
    2772,  -- Iron Ore
    2775,  -- Silver Ore
    2776,  -- Gold Ore
    2880,  -- Weak Flux
    2886,  -- Crag Boar Rib
    2924,  -- Crocolisk Meat
    2934,  -- Ruined Leather Scraps
    2996,  -- Bolt of Linen Cloth
    2997,  -- Bolt of Woolen Cloth
    3172,  -- Boar Intestines
    3173,  -- Bear Meat
    3174,  -- Spider Ichor
    3404,  -- Buzzard Wing
    3466,  -- Strong Flux
    3667,  -- Tender Crocolisk Meat
    3685,  -- Raptor Egg
    3712,  -- Turtle Meat
    3730,  -- Big Bear Meat
    3731,  -- Lion Meat
    3857,  -- Coal
    3858,  -- Mithril Ore
    4231,  -- Cured Light Hide
    4233,  -- Cured Medium Hide
    4234,  -- Heavy Leather
    4236,  -- Cured Heavy Hide
    4304,  -- Thick Leather
    4305,  -- Bolt of Silk Cloth
    4339,  -- Bolt of Mageweave
    4359,  -- Handful of Copper Bolts
    4360,  -- Rough Copper Bomb
    4361,  -- Copper Tube
    4363,  -- Copper Modulator
    4370,  -- Large Copper Bomb
    4371,  -- Bronze Tube
    4374,  -- Small Bronze Bomb
    4380,  -- Big Bronze Bomb
    4390,  -- Iron Grenade
    4394,  -- Big Iron Bomb
    4395,  -- Goblin Land Mine
    4398,  -- Large Seaforium Charge
    4655,  -- Giant Clam Meat
    5465,  -- Small Spider Leg
    5466,  -- Scorpid Stinger
    5467,  -- Kodo Meat
    5468,  -- Soft Frenzy Flesh
    5469,  -- Strider Meat
    5470,  -- Thunder Lizard Tail
    5471,  -- Stag Meat
    5503,  -- Clam Meat
    5504,  -- Tangy Clam Meat
    6889,  -- Small Egg
    7911,  -- Truesilver Ore
    7974,  -- Zesty Clam Meat
    8170,  -- Rugged Leather
    8172,  -- Cured Thick Hide
    9262,  -- Black Vitriol
    10514, -- Mithril Frag Bomb
    10559, -- Mithril Tube
    10562, -- Hi-Explosive Bomb
    10586, -- The Big One
    10620, -- Thorium Ore
    10646, -- Goblin Sapper Charge
    10940, -- Strange Dust
    10978, -- Small Glimmering Shard
    11083, -- Soul Dust
    11084, -- Large Glimmering Shard
    11137, -- Vision Dust
    11138, -- Small Glowing Shard
    11139, -- Large Glowing Shard
    11176, -- Dream Dust
    11177, -- Small Radiant Shard
    11178, -- Large Radiant Shard
    11370, -- Dark Iron Ore
    12037, -- Mystery Meat
    12184, -- Raptor Flesh
    12202, -- Tiger Meat
    12203, -- Red Wolf Meat
    12204, -- Heavy Kodo Meat
    12205, -- White Spider Meat
    12206, -- Tender Crab Meat
    12207, -- Giant Egg
    12208, -- Tender Wolf Meat
    12223, -- Meaty Bat Wing
    12810, -- Enchanted Leather
    14048, -- Bolt of Runecloth
    14343, -- Small Brilliant Shard
    14344, -- Large Brilliant Shard
    15417, -- Devilsaur Leather
    15419, -- Warbear Leather
    15993, -- Thorium Grenade
    16000, -- Thorium Tube
    16005, -- Dark Iron Bomb
    16040, -- Arcane Bomb
    16204, -- Illusion Dust
    17012, -- Core Leather
    17771, -- Elementium Bar
    18562, -- Elementium Ore
    18567, -- Elemental Flux
    18594, -- Powerful Seaforium Charge
    19767, -- Primal Bat Leather
    19768, -- Primal Tiger Leather
    20725, -- Nexus Crystal
    21840, -- Bolt of Netherweave
    21844, -- Bolt of Soulcloth
    22644, -- Crunchy Spider Leg
    23736, -- Fel Iron Bomb
    23737, -- Adamantite Grenade
    23783, -- Handful of Fel Iron Bolts
    23785, -- Hardened Adamantite Tube
    23826, -- The Bigger One
    23827, -- Super Sapper Charge
    24477, -- Jaggal Clam Meat
    27668, -- Lynx Meat
    27669, -- Bat Flesh
    32413  -- Frost Grenade
);
