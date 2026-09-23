/*
 * The one thing outside NekoLog.cpp that needs to reach into it: the id of
 * the combat-log run it has open for an instance, so a challenge run can
 * record which log belongs to it (nekocore_challenge_run.log_run_id) and the
 * website can link a challenge straight to its full log.
 *
 * Deliberately this direction round. The alternative -- NekoLog writing a
 * challenge id onto nekolog_run -- would mean an extra column on a table
 * that already exists on the live realm, and MySQL 8 has no
 * `ADD COLUMN IF NOT EXISTS`, so the module's own idempotent base SQL
 * couldn't express it. Nothing in NekoLog has to know challenge runs exist.
 */
#ifndef NEKOCORE_NEKOLOG_H
#define NEKOCORE_NEKOLOG_H

#include "Define.h"

class Map;

namespace NekoLog
{
    /** nekolog_run.id for this instance's open run, or 0 if nothing is logged there yet. */
    uint64 RunIdFor(Map const* map);
}

#endif
