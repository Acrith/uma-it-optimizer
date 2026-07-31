//! Minimal hand-rolled JSON: no serde dep, keeps the DLL small.
//!
//! Ordered `Object` (Vec<(k,v)>) rather than a map preserves the
//! insertion order — matches the C# field declaration order we
//! walk, which in turn matches what the Frida extractor's output
//! shows. Handy for diffing.

use std::fmt::Write as _;

pub enum JsonValue {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    /// Already-escaped display string. For raw strings from the
    /// runtime, use `JsonValue::string(s)` to escape.
    String(String),
    Array(Vec<JsonValue>),
    Object(Vec<(String, JsonValue)>),
}

impl JsonValue {
    pub fn string(s: impl Into<String>) -> JsonValue {
        JsonValue::String(escape(&s.into()))
    }

    pub fn to_pretty(&self) -> String {
        let mut out = String::new();
        self.write(&mut out, 0);
        out
    }

    fn write(&self, out: &mut String, indent: usize) {
        match self {
            JsonValue::Null => out.push_str("null"),
            JsonValue::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            JsonValue::Int(i) => {
                let _ = write!(out, "{}", i);
            }
            JsonValue::Float(f) => {
                if f.is_nan() || f.is_infinite() {
                    out.push_str("null"); // JSON has no NaN/Inf
                } else {
                    let _ = write!(out, "{}", f);
                }
            }
            JsonValue::String(s) => {
                out.push('"');
                out.push_str(s);
                out.push('"');
            }
            JsonValue::Array(items) => {
                if items.is_empty() {
                    out.push_str("[]");
                    return;
                }
                out.push('[');
                let pad = "  ".repeat(indent + 1);
                let close_pad = "  ".repeat(indent);
                for (i, item) in items.iter().enumerate() {
                    out.push('\n');
                    out.push_str(&pad);
                    item.write(out, indent + 1);
                    if i + 1 < items.len() {
                        out.push(',');
                    }
                }
                out.push('\n');
                out.push_str(&close_pad);
                out.push(']');
            }
            JsonValue::Object(entries) => {
                if entries.is_empty() {
                    out.push_str("{}");
                    return;
                }
                out.push('{');
                let pad = "  ".repeat(indent + 1);
                let close_pad = "  ".repeat(indent);
                for (i, (k, v)) in entries.iter().enumerate() {
                    out.push('\n');
                    out.push_str(&pad);
                    out.push('"');
                    out.push_str(&escape(k));
                    out.push_str("\": ");
                    v.write(out, indent + 1);
                    if i + 1 < entries.len() {
                        out.push(',');
                    }
                }
                out.push('\n');
                out.push_str(&close_pad);
                out.push('}');
            }
        }
    }
}

fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out
}
