"""Era conformance audit, spell layer.

Compares every Vanilla spell the realm serves against cMaNGOS classic's
spell_template (1.12.1 ground truth) and prints every field that differs.

  python -I tools/audit/spell_audit.py --classic-db era-data/classicmangos.sqlite \
      [--spell-dbc data/generated/Spell.dbc] [--out audit-vanilla.csv]

Checks, per spell id N:
  * clone (N+300000) in the realm Spell.dbc  vs  era row N   -> "clone" findings
  * if N has NO clone: the realm's plain row N vs era row N  -> "uncloned" findings
    (these are what mobs/items/consumables still run today)
Index fields (CastingTime, Duration, Range, Radius) are resolved to real values:
era via the 1.12.1 client MPQs (--client-1121, needs mpyq), realm via the
tables the server loads (--realm-dbc-dir, plus data/generated/SpellRange.dbc).
"""
import argparse, csv, json, sqlite3, sys, tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dbc"))
from schemas import BUILD_SCHEMAS  # noqa: E402
from wdbc import LOCALE_COUNT, read_dbc  # noqa: E402

OFFSET = 300_000
# era column -> realm field
SCALAR = {
    "RecoveryTime": "RecoveryTime", "CategoryRecoveryTime": "CategoryRecoveryTime",
    "Category": "Category", "StartRecoveryTime": "StartRecoveryTime",
    "StartRecoveryCategory": "StartRecoveryCategory", "ProcChance": "ProcChance",
    "ProcCharges": "ProcCharges", "ManaCost": "ManaCost", "ManaCostPercentage": "ManaCostPct",
    "StackAmount": "CumulativeAura", "Mechanic": "Mechanic", "Dispel": "DispelType",
    "MaxAffectedTargets": "MaxTargets", "InterruptFlags": "InterruptFlags",
    "AuraInterruptFlags": "AuraInterruptFlags", "ChannelInterruptFlags": "ChannelInterruptFlags",
    "MaxLevel": "MaxLevel", "BaseLevel": "BaseLevel", "SpellLevel": "SpellLevel",
    "PowerType": "PowerType", "ManaPerSecond": "ManaPerSecond",
}
PER_EFFECT = {  # era base -> realm base
    "Effect": "Effect", "EffectApplyAuraName": "EffectAura", "EffectAmplitude": "EffectAuraPeriod",
    "EffectBasePoints": "EffectBasePoints", "EffectDieSides": "EffectDieSides",
    "EffectMiscValue": "EffectMiscValue", "EffectTriggerSpell": "EffectTriggerSpell",
    "EffectMechanic": "EffectMechanic", "EffectChainTarget": "EffectChainTargets",
    "EffectImplicitTargetA": "ImplicitTargetA", "EffectImplicitTargetB": "ImplicitTargetB",
}

# (spell column, table, value fields)  -> compared by resolved value, not index
INDEXED = [
    ("DurationIndex", "SpellDuration.dbc", ("Duration",)),
    ("CastingTimeIndex", "SpellCastTimes.dbc", ("Base",)),
    ("RangeIndex", "SpellRange.dbc", ("RangeMax_0",)),
    ("EffectRadiusIndex_0", "SpellRadius.dbc", ("Radius",)),
    ("EffectRadiusIndex_1", "SpellRadius.dbc", ("Radius",)),
    ("EffectRadiusIndex_2", "SpellRadius.dbc", ("Radius",)),
]
# era spell_template column for each index field
ERA_IDX = {"DurationIndex": "DurationIndex", "CastingTimeIndex": "CastingTimeIndex",
           "RangeIndex": "RangeIndex", "EffectRadiusIndex_0": "EffectRadiusIndex1",
           "EffectRadiusIndex_1": "EffectRadiusIndex2", "EffectRadiusIndex_2": "EffectRadiusIndex3"}

def load_tables(client, realm_dir, a_gen):
    from mpq_source import resolve
    td = Path(tempfile.mkdtemp())
    era, realm = {}, {}
    for _, name, _ in INDEXED:
        if name in era:
            continue
        _, data = resolve(client, name)
        (td / name).write_bytes(data)
        era[name] = {r["ID"]: r for r in read_dbc(td / name, BUILD_SCHEMAS["1.12.1"][name],
                                                  LOCALE_COUNT["1.12.1"]).rows}
        d = (a_gen if name == "SpellRange.dbc" else realm_dir)
        realm[name] = {r["ID"]: r for r in read_dbc(d / name, BUILD_SCHEMAS["3.3.5a"][name],
                                                    LOCALE_COUNT["3.3.5a"]).rows}
    return era, realm

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classic-db", required=True, type=Path)
    ap.add_argument("--spell-dbc", type=Path, default=ROOT / "data/generated/Spell.dbc")
    ap.add_argument("--client-1121", type=Path)
    ap.add_argument("--realm-dbc-dir", type=Path, default=ROOT / "server/env/dist/data/dbc")
    ap.add_argument("--out", type=Path, default=Path("audit-vanilla.csv"))
    a = ap.parse_args()

    db = sqlite3.connect(f"file:{a.classic_db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    era = {r["Id"]: r for r in db.execute("select * from spell_template")}
    realm = {r["ID"]: r for r in read_dbc(a.spell_dbc, BUILD_SCHEMAS["3.3.5a"]["Spell.dbc"],
                                          LOCALE_COUNT["3.3.5a"]).rows}
    idx = load_tables(a.client_1121, a.realm_dbc_dir, a.spell_dbc.parent) if a.client_1121 else None
    out, tally = [], Counter()
    for sid, e in era.items():
        kind, r = ("clone", realm.get(sid + OFFSET)) 
        if r is None:
            kind, r = "uncloned", realm.get(sid)
        if r is None:
            tally["missing_in_realm"] += 1
            continue
        tally[kind] += 1
        def cmp(field, ev, rv):
            if ev != rv:
                out.append((sid, e["SpellName"], e["Rank1"], kind, field, ev, rv))
        for ef, rf in SCALAR.items():
            cmp(rf, e[ef], r[rf])
        if idx:
            for rf, tbl, vf in INDEXED:
                ei, ri = e[ERA_IDX[rf]], r[rf]
                et, rt = idx[0][tbl].get(ei), idx[1][tbl].get(ri)
                for v in vf:
                    ev = (et.get(v, et.get("RangeMax")) if et else 0)
                    cmp(f"{rf}.{v}", ev, rt[v] if rt else 0)
        for i in range(3):
            for ef, rf in PER_EFFECT.items():
                cmp(f"{rf}[{i}]", e[f"{ef}{i+1}"], r[f"{rf}_{i}"])
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["spell_id", "name", "rank", "kind", "field", "era_value", "realm_value"])
        w.writerows(out)
    by = Counter((k, f.split("[")[0]) for _, _, _, k, f, _, _ in out)
    print(dict(tally))
    for (k, f), n in by.most_common(40):
        print(f"{k:9} {f:24} {n}")
    print("spells with a diff:", len({(o[0], o[3]) for o in out}), "->", a.out)

main()
