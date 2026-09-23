/*
 * Shared surface of the challenge-run system. ChallengeRun.cpp owns the
 * state (tiers, armed challenges, flagged instances, the Keeper NPC, and
 * clear/wipe detection); ChallengeScaling.cpp is the part that actually
 * makes a flagged instance harder, and reads its numbers from here.
 *
 * Kept in a header rather than merged into one file because the two halves
 * hook completely different things -- one is gossip/teleport/database
 * bookkeeping on the world thread, the other is per-creature and per-hit
 * work on map threads inside mod-autobalance's own pipeline. They only ever
 * need these few values to cross between them.
 */
#ifndef NEKOCORE_CHALLENGE_RUN_H
#define NEKOCORE_CHALLENGE_RUN_H

#include "Define.h"

class Map;

namespace NekocoreChallenge
{
    struct ActiveRun
    {
        uint64 id         = 0;
        uint32 mapId      = 0;
        uint8  bracket    = 0;   // 60 / 70 / 80 -- the level the dungeon is pinned to
        uint16 tier       = 0;
        float  healthMult = 1.0f;
        float  damageMult = 1.0f;
    };

    /** Nekocore.Challenge.Enable. */
    bool Enabled();

    /**
     * Nekocore.Challenge.SuppressLevelScalingOutsideChallenges -- see the
     * long note in ChallengeScaling.cpp for why the AutoBalance global has
     * to be on for challenge runs to scale at all, and why that then has to
     * be neutered everywhere else.
     */
    bool SuppressOutsideChallenges();

    uint8 DynamicLevelCeiling();
    uint8 DynamicLevelFloor();

    /**
     * Fills `out` with this instance's challenge state and returns true, or
     * returns false if this map isn't a flagged challenge instance.
     *
     * Called from the damage path, so it takes a lock-free early out (an
     * atomic count of flagged instances) before it touches the mutex that
     * guards the table -- with no challenge run anywhere on the realm this
     * costs one relaxed atomic load per hit.
     */
    bool ActiveRunFor(Map const* map, ActiveRun& out);

    /**
     * Makes mod-autobalance re-evaluate every creature on a map.
     *
     * Its per-creature work is skipped while the creature's own recorded
     * mapConfigTime still matches the map's, so flagging an instance that
     * already has creatures standing in it needs that comparison to fail
     * once. This is the same nudge AutoBalance's own code gives itself when a
     * map's settings change underneath it (ABUtils.cpp). Lives on the
     * ChallengeScaling.cpp side because that is the half of this module that
     * already includes AutoBalance's headers.
     */
    void ForceAutoBalanceRefresh(Map* map);
}

#endif
