/*
 * Consumable rules that differ by era. The core implements the 3.x ones:
 *
 *   - Battle / Guardian elixirs (spell_group 1 and 2, EXCLUSIVE): a new one
 *     replaces the old of its kind. 2.1.0 introduced that split; in 1.12 any
 *     elixirs and flasks coexisted and only collided on identical effects.
 *   - Potions (Spell::SendSpellCooldown): the cooldown does not start on use
 *     but when combat ends, so one potion per fight. 1.12 started the item's
 *     own timer (120 s) on use, in combat or out of it.
 *
 * Both are decided deep inside core code that has no era concept, so
 * core-patches/0005 asks g_nekoUnitIsVanilla, which this file installs.
 * TBC and WotLK keep the stock behaviour.
 */

#include "Player.h"
#include "SpellMgr.h"

#include "EraTalents.h"

namespace
{
    bool UnitIsVanilla(Unit const* unit)
    {
        Player const* player = unit ? unit->ToPlayer() : nullptr;
        return player && NekoEraTalents::EraOfPlayer(player) == NekoEraTalents::ERA_VANILLA;
    }
}

void AddSC_era_consumables()
{
    g_nekoUnitIsVanilla = &UnitIsVanilla;
}
