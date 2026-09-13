//! A minimal WDBC reader and writer.
//!
//! **Ported, not depended on.** The full reader -- every table this project's
//! client actually uses, verified against a real installation -- lives in
//! `open-wow-client`'s `dbc` crate. This is a deliberately small subset with
//! one job: read/write the handful of uniform, string-free tables this
//! server-side tool touches, so a server operator can build this without
//! also checking out the client repo. If the shape of what this needs ever
//! grows past "plain `u32` columns, no strings", pull in the real crate
//! instead of growing this one to match it.
//!
//! A DBC is a fixed-width table: a 20-byte header (magic `WDBC`, record
//! count, field count, record size, string-block size), a block of
//! equal-sized records, then a string block. Every field here is a 32-bit
//! word (`record_size == fields * 4`) and every table this tool reads or
//! writes carries an empty string block -- `Talent.dbc` has none of its own,
//! and this tool never touches `TalentTab.dbc`'s or `Spell.dbc`'s strings,
//! only their numeric columns.

pub struct Dbc {
    pub fields: u32,
    records: Vec<u8>,
}

impl Dbc {
    pub fn parse(bytes: &[u8]) -> Result<Self, String> {
        if bytes.len() < 20 {
            return Err(format!("{} bytes, too short for a 20-byte header", bytes.len()));
        }
        if &bytes[..4] != b"WDBC" {
            return Err(format!("bad magic {:?}", &bytes[..4]));
        }
        let word = |o: usize| u32::from_le_bytes(bytes[o..o + 4].try_into().unwrap());
        let (record_count, fields, record_size) = (word(4), word(8), word(12));
        if record_size != fields * 4 {
            return Err(format!(
                "record_size {record_size} is not fields({fields}) * 4 -- byte-packed tables are out of scope for this tool"
            ));
        }
        let body = record_count as usize * record_size as usize;
        if 20 + body > bytes.len() {
            return Err(format!("declares {record_count} x {record_size} bytes, file is only {}", bytes.len()));
        }
        Ok(Self { fields, records: bytes[20..20 + body].to_vec() })
    }

    pub fn len(&self) -> usize {
        if self.fields == 0 {
            0
        } else {
            self.records.len() / (self.fields as usize * 4)
        }
    }

    /// Field `field` of row `row`, as a raw `u32` -- every column this tool
    /// touches is one, including the ones a fuller reader would call `i32`
    /// or a string offset.
    pub fn u32(&self, row: usize, field: usize) -> u32 {
        let record_size = self.fields as usize * 4;
        let at = row * record_size + field * 4;
        u32::from_le_bytes(self.records[at..at + 4].try_into().unwrap())
    }

    pub fn raw_record(&self, row: usize) -> &[u8] {
        let record_size = self.fields as usize * 4;
        &self.records[row * record_size..(row + 1) * record_size]
    }
}

/// Assembles a WDBC file from raw records (each already `fields * 4` bytes,
/// in the table's own column order) and an empty string block -- every table
/// this tool writes needs none.
pub fn write_dbc(fields: u32, records: &[Vec<u8>]) -> Vec<u8> {
    let record_size = fields * 4;
    for r in records {
        assert_eq!(r.len(), record_size as usize, "record width does not match field count");
    }
    let mut out = Vec::with_capacity(20 + records.len() * record_size as usize + 1);
    out.extend_from_slice(b"WDBC");
    out.extend_from_slice(&(records.len() as u32).to_le_bytes());
    out.extend_from_slice(&fields.to_le_bytes());
    out.extend_from_slice(&record_size.to_le_bytes());
    out.extend_from_slice(&1u32.to_le_bytes()); // string block: just the mandatory leading NUL
    for r in records {
        out.extend_from_slice(r);
    }
    out.push(0);
    out
}

/// A record under construction -- every field zero until set, matching this
/// project's own convention (an absent field is a zero, not garbage).
pub struct Record(Vec<u8>);

impl Record {
    pub fn new(fields: u32) -> Self {
        Self(vec![0; fields as usize * 4])
    }

    pub fn set(&mut self, field: usize, value: u32) -> &mut Self {
        self.0[field * 4..field * 4 + 4].copy_from_slice(&value.to_le_bytes());
        self
    }

    pub fn into_bytes(self) -> Vec<u8> {
        self.0
    }
}
