//! Builds a merged `Talent.dbc` for one class: the stock WotLK rows,
//! unchanged, plus a new row for every Classic (1.12.1) talent that is not
//! already served by an identical WotLK one.
//!
//! **This is the server-side twin of `open-wow-client`'s
//! `tools/wow-cli/examples/build_talent_merge.rs`.** Same logic, live-tested
//! on the local realm from that copy first -- ported here, with a vendored
//! DBC layer (see `dbc.rs`), so producing this file doesn't require checking
//! out the client repo at all. If the two ever disagree, the client repo's
//! version is the one that was actually run against a live character; bring
//! this one back in line with it, not the other way round.
//!
//! **No new tabs.** All 27 Classic `TalentTab.dbc` ids are a strict subset
//! of WotLK's 33 (confirmed against a real 3.3.5a install) -- the same tree,
//! the same id, in both builds. A talent this tool adds is filed under that
//! same existing tab id, which is what lets AzerothCore's own
//! tier-point-gating and prerequisite checks in `LearnTalent` apply to it
//! with no engine changes.
//!
//! **New ids are `classic_id + ID_OFFSET`.** Keep this modest --
//! `DBCStorage::LookupEntry` is a flat array indexed by raw id, sized to
//! `max_id + 1` at load (`DBCFileLoader::AutoProduceData` in AzerothCore's
//! own source). An offset of 900,000 was tried first and broke silently: a
//! point was spent and nothing was learned, for a 913-row table forced into
//! a 900,762-slot array. 10,000 works cleanly and is nowhere near WotLK's own
//! max talent id (~2,300, measured).
//!
//! **A talent is only added if every rank it can teach is a real spell in
//! this server's own `Spell.dbc`.** `Player::LearnTalent` in AzerothCore
//! calls `addTalent()` but never checks its return value, so a talent whose
//! spell does not exist here still costs the player a point in total
//! silence -- confirmed live. Found this way for Druid: 13 of 21
//! originally-planned additions reference a spell that was cut along with
//! the talent (Improved Nature's Grasp among them), not just renumbered.
//! Skipped, and anything depending on a skipped talent is skipped too,
//! transitively.
//!
//! **`depends_on` is translated, not copied.** A prerequisite that is itself
//! identical keeps its original id; one that was also renumbered needs the
//! *new* id.
//!
//! ## Getting the four input files
//!
//! This tool has no MPQ reader of its own -- it takes already-extracted flat
//! `.dbc` files. Pull them out with `open-wow-client`'s `wow-cli`:
//!
//! ```text
//! wow-cli --data "<1.12.1 install>\Data" extract "DBFilesClient\Talent.dbc"    --out classic-Talent.dbc
//! wow-cli --data "<1.12.1 install>\Data" extract "DBFilesClient\TalentTab.dbc" --out classic-TalentTab.dbc
//! wow-cli --data "<3.3.5a install>\Data" extract "DBFilesClient\Talent.dbc"    --out wotlk-Talent.dbc
//! wow-cli --data "<3.3.5a install>\Data" extract "DBFilesClient\Spell.dbc"     --out wotlk-Spell.dbc
//! ```
//!
//! Or copy `wotlk-Talent.dbc`/`wotlk-Spell.dbc` straight out of the running
//! server's own data volume (`docker run --rm -v
//! azerothcore-wotlk_ac-client-data:/data -v "<out dir>:/out" alpine cp
//! /data/dbc/Talent.dbc /data/dbc/Spell.dbc /out/`) instead of the reference
//! client, if there is any doubt they might have drifted from stock -- they
//! are the actual file this tool's output has to sit next to.
//!
//! Usage: `build-talent-merge <classic Talent.dbc> <classic TalentTab.dbc> <wotlk Talent.dbc> <wotlk Spell.dbc> <class_mask> <out Talent.dbc> <out mapping.csv>`

#[path = "dbc.rs"]
mod dbc;

use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;

use dbc::{write_dbc, Dbc, Record};

/// See the module doc comment for why this number and not a larger one.
const ID_OFFSET: u32 = 10_000;

// Column indices, transcribed once and shared with `open-wow-client`'s copy
// of this schema (`crates/dbc/src/schema.rs`) -- see that crate for how each
// one was confirmed against real data rather than assumed.
mod classic_talent {
    pub const TAB_ID: usize = 1;
    pub const TIER: usize = 2;
    pub const COLUMN: usize = 3;
    pub const RANK_0: usize = 4;
    pub const DEPENDS_ON: usize = 13;
    pub const DEPENDS_ON_RANK: usize = 16;
    pub const FIELDS: u32 = 21;
}
mod classic_talent_tab {
    pub const CLASS_MASK: usize = 12;
    pub const FIELDS: u32 = 15;
}
mod wotlk_talent {
    pub const TAB_ID: usize = 1;
    pub const DEPENDS_ON: usize = 13;
    pub const FIELDS: u32 = 23;
}

fn ranks(dbc: &Dbc, row: usize, rank_0_field: usize) -> [u32; 5] {
    std::array::from_fn(|i| dbc.u32(row, rank_0_field + i))
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let usage = "usage: <classic Talent.dbc> <classic TalentTab.dbc> <wotlk Talent.dbc> <wotlk Spell.dbc> <class_mask> <out Talent.dbc> <out mapping.csv>";
    let [classic_talent_path, classic_tab_path, wotlk_talent_path, wotlk_spell_path, class_mask, out_dbc, out_mapping] =
        <[String; 7]>::try_from(args).unwrap_or_else(|_| panic!("{usage}"));
    let class_mask: u32 = class_mask.parse().expect("class_mask must be a number");

    let read = |path: &str| fs::read(path).unwrap_or_else(|e| panic!("reading {path}: {e}"));
    let classic_talents = Dbc::parse(&read(&classic_talent_path)).expect("parsing classic Talent.dbc");
    let classic_tabs = Dbc::parse(&read(&classic_tab_path)).expect("parsing classic TalentTab.dbc");
    let wotlk_talents = Dbc::parse(&read(&wotlk_talent_path)).expect("parsing wotlk Talent.dbc");
    let wotlk_spell = Dbc::parse(&read(&wotlk_spell_path)).expect("parsing wotlk Spell.dbc");
    assert_eq!(classic_talents.fields, classic_talent::FIELDS, "classic Talent.dbc: unexpected field count -- wrong build?");
    assert_eq!(classic_tabs.fields, classic_talent_tab::FIELDS, "classic TalentTab.dbc: unexpected field count -- wrong build?");
    assert_eq!(wotlk_talents.fields, wotlk_talent::FIELDS, "wotlk Talent.dbc: unexpected field count -- wrong build?");

    let wotlk_spell_ids: HashSet<u32> = (0..wotlk_spell.len()).map(|i| wotlk_spell.u32(i, 0)).collect();

    let class_tab_ids: Vec<u32> = (0..classic_tabs.len())
        .filter(|&i| classic_tabs.u32(i, classic_talent_tab::CLASS_MASK) == class_mask)
        .map(|i| classic_tabs.u32(i, 0))
        .collect();
    assert_eq!(class_tab_ids.len(), 3, "expected exactly 3 tabs for class_mask {class_mask}, got {class_tab_ids:?}");
    println!("class_mask {class_mask}: tabs {class_tab_ids:?}");

    let wotlk_by_id: HashMap<u32, [u32; 5]> = (0..wotlk_talents.len())
        .map(|i| (wotlk_talents.u32(i, 0), ranks(&wotlk_talents, i, 4)))
        .collect();

    let mut class_rows: Vec<usize> = (0..classic_talents.len())
        .filter(|&i| class_tab_ids.contains(&classic_talents.u32(i, classic_talent::TAB_ID)))
        .collect();
    class_rows.sort_by_key(|&i| classic_talents.u32(i, 0));

    let mut mapping: HashMap<u32, u32> = HashMap::new();
    let mut needs_new_row: Vec<usize> = Vec::new();
    let mut unsafe_ids: HashSet<u32> = HashSet::new();
    for &row in &class_rows {
        let id = classic_talents.u32(row, 0);
        let row_ranks = ranks(&classic_talents, row, classic_talent::RANK_0);
        if wotlk_by_id.get(&id) == Some(&row_ranks) {
            mapping.insert(id, id);
            continue;
        }
        let missing: Vec<u32> = row_ranks.iter().copied().filter(|&s| s != 0 && !wotlk_spell_ids.contains(&s)).collect();
        if !missing.is_empty() {
            println!("  {id} SKIPPED: rank spell(s) {missing:?} do not exist in WotLK's Spell.dbc");
            unsafe_ids.insert(id);
            continue;
        }
        needs_new_row.push(row);
        mapping.insert(id, id + ID_OFFSET);
    }

    // Transitive skip: repeated to a fixed point, since a skip can cascade.
    loop {
        let mut changed = false;
        needs_new_row.retain(|&row| {
            let id = classic_talents.u32(row, 0);
            let depends_on = classic_talents.u32(row, classic_talent::DEPENDS_ON);
            let blocked = depends_on != 0 && unsafe_ids.contains(&depends_on);
            if blocked {
                println!("  {id} SKIPPED: depends on {depends_on}, which was itself skipped");
                unsafe_ids.insert(id);
                mapping.remove(&id);
                changed = true;
            }
            !blocked
        });
        if !changed {
            break;
        }
    }

    println!(
        "{} talent(s) total: {} identical, {} added, {} skipped (spell does not exist here)",
        class_rows.len(),
        class_rows.len() - needs_new_row.len() - unsafe_ids.len(),
        needs_new_row.len(),
        unsafe_ids.len()
    );

    let mut new_records = Vec::with_capacity(needs_new_row.len());
    for &row in &needs_new_row {
        let id = classic_talents.u32(row, 0);
        let new_id = mapping[&id];
        // WotLK's field count, not Classic's -- the output is a WotLK-shaped
        // Talent.dbc (23 fields), with Classic's leading 21 columns copied in
        // and the two WotLK-only trailing ones left at their zero default.
        let mut record = Record::new(wotlk_talent::FIELDS);
        record.set(0, new_id);
        record.set(wotlk_talent::TAB_ID, classic_talents.u32(row, classic_talent::TAB_ID)); // unchanged -- same real tab
        record.set(2, classic_talents.u32(row, classic_talent::TIER));
        record.set(3, classic_talents.u32(row, classic_talent::COLUMN));
        for (i, &spell) in ranks(&classic_talents, row, classic_talent::RANK_0).iter().enumerate() {
            record.set(4 + i, spell);
        }
        let depends_on = classic_talents.u32(row, classic_talent::DEPENDS_ON);
        if depends_on != 0 {
            let translated = *mapping
                .get(&depends_on)
                .unwrap_or_else(|| panic!("talent {id} depends on {depends_on}, not in this class's set"));
            record.set(wotlk_talent::DEPENDS_ON, translated);
            record.set(classic_talent::DEPENDS_ON_RANK, classic_talents.u32(row, classic_talent::DEPENDS_ON_RANK));
            if translated != depends_on {
                println!("  {id} -> {new_id}: depends_on {depends_on} -> {translated}");
            } else {
                println!("  {id} -> {new_id}: depends_on {depends_on} (unchanged)");
            }
        } else {
            println!("  {id} -> {new_id}");
        }
        new_records.push(record.into_bytes());
    }

    let mut all_records: Vec<Vec<u8>> = (0..wotlk_talents.len()).map(|i| wotlk_talents.raw_record(i).to_vec()).collect();
    let stock_count = all_records.len();
    all_records.extend(new_records);

    let merged = write_dbc(wotlk_talent::FIELDS, &all_records);
    fs::write(&out_dbc, &merged).unwrap_or_else(|e| panic!("writing {out_dbc}: {e}"));
    println!("\nwrote {out_dbc}: {} rows ({stock_count} stock + {} new)", all_records.len(), needs_new_row.len());

    // Self-verification: re-parse what was just written and confirm every
    // stock row survived untouched. Not a formality -- this is exactly the
    // class of file a wrong writer produces that "looks done" and loads a
    // corrupted tree.
    let reparsed = Dbc::parse(&merged).expect("re-parsing the file just written");
    assert_eq!(reparsed.len(), all_records.len());
    for i in 0..stock_count {
        assert_eq!(reparsed.raw_record(i), wotlk_talents.raw_record(i), "stock row {i} changed");
    }
    println!("verified: all {stock_count} stock rows byte-identical after the round trip");

    let mut csv = String::from("classic_id,server_id\n");
    let mut rows: Vec<(u32, u32)> = mapping.into_iter().collect();
    rows.sort_by_key(|(classic_id, _)| *classic_id);
    for (classic_id, server_id) in rows {
        csv.push_str(&format!("{classic_id},{server_id}\n"));
    }
    fs::write(&out_mapping, csv).unwrap_or_else(|e| panic!("writing {out_mapping}: {e}"));
    println!("wrote {out_mapping}");
}
