//! Safe Rust wrapper over Hachimi-Edge's C `get_api` plugin surface.
//!
//! Minimal subset needed for the uma-it plugin — vendored from
//! jalbarrang/honse-tracker (GPL-3.0-or-later). We drop the `gui`,
//! `sdk`, and higher-level ergonomic wrappers that honse-tracker
//! ships since our plugin doesn't render any UI; it just hooks a
//! method and writes JSON. See `../NOTICE.md` for attribution.

pub mod api;
pub mod entry;
pub mod ffi;
pub mod log;

pub use api::Api;
