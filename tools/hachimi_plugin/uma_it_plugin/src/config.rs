//! Persistent plugin config: API URL + auth token for auto-upload.
//!
//! Mirrors the `.exe` extractor's config shape (see
//! `tools/memory_extractor/dump_it_run.py:582`) — `{api_url,
//! api_token}` at a well-known path. Kept compatible so a user who
//! already has the extractor configured can copy their token in
//! without confusion about the format.
//!
//! **Persistence location.** Hachimi exposes a base directory via
//! `hachimi_get_base_dir()`. We write to `<base>/uma_it_plugin_config.json`
//! rather than the Umamusume install dir — that keeps the plugin's
//! state next to Hachimi's own state, survives game updates, and
//! doesn't need Program Files write permissions.
//!
//! **Concurrency.** The config is touched from two places:
//! - The Hachimi UI thread (settings section render, save button)
//! - The Hachimi menu-click thread (upload after capture)
//! Both are the game's main GUI thread in practice, but we still
//! use a `RwLock` so any future off-thread reads (e.g. background
//! upload) are safe. Reads dominate; writes only happen on Save.

use once_cell::sync::Lazy;
use std::path::{Path, PathBuf};
use std::sync::RwLock;

use log::{info, warn};

const CONFIG_FILENAME: &str = "uma_it_plugin_config.json";
/// Default API endpoint — the production web app. Same default the
/// `.exe` extractor ships with. Users can override via the settings
/// UI if they run a local dev server.
pub const DEFAULT_API_URL: &str = "https://training.umaladder.moe";

#[derive(Clone, Debug, Default)]
pub struct Config {
    pub api_url: String,
    pub api_token: String,
    /// If true, on a successful upload the plugin opens the run's
    /// detail page in the user's default browser. Off by default —
    /// popping a browser Alt-Tabs the user out of the game, which
    /// some players won't want mid-session.
    pub open_after_upload: bool,
}

impl Config {
    /// True iff the config has enough to attempt an upload.
    /// URL alone isn't enough — no token means we can't auth, so
    /// skip the POST rather than trigger a 401 the user won't see.
    pub fn is_ready(&self) -> bool {
        !self.api_url.is_empty() && !self.api_token.is_empty()
    }

    /// Trim + strip trailing slash from URL to keep POST target
    /// concatenation clean. Called before every save so the on-disk
    /// state is always normalized.
    pub fn normalize(&mut self) {
        self.api_url = self.api_url.trim().trim_end_matches('/').to_string();
        self.api_token = self.api_token.trim().to_string();
    }
}

static CONFIG: Lazy<RwLock<Config>> = Lazy::new(|| {
    RwLock::new(Config {
        api_url: DEFAULT_API_URL.to_string(),
        api_token: String::new(),
    })
});

/// Where we persist. Filled in by [`init`]; `None` until then means
/// we're running before setup completed and save/reload is a no-op.
static CONFIG_PATH: Lazy<RwLock<Option<PathBuf>>> = Lazy::new(|| RwLock::new(None));

/// Called once from `setup()` with Hachimi's base directory. Reads
/// the on-disk config if present, otherwise leaves the in-memory
/// default (production URL, empty token — upload will be a no-op
/// until the user pastes a token into the UI).
pub fn init(base_dir: &Path) {
    let path = base_dir.join(CONFIG_FILENAME);
    match std::fs::read_to_string(&path) {
        Ok(text) => match parse_json(&text) {
            Some(mut cfg) => {
                cfg.normalize();
                let ready = cfg.is_ready();
                *CONFIG.write().unwrap() = cfg;
                info!(
                    "[uma-it] config loaded from {} (ready={})",
                    path.display(),
                    ready
                );
            }
            None => {
                warn!(
                    "[uma-it] config at {} is unparseable — leaving defaults",
                    path.display()
                );
            }
        },
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
            info!(
                "[uma-it] no config yet at {} — will be created on first Save",
                path.display()
            );
        }
        Err(err) => {
            warn!("[uma-it] failed to read config {}: {}", path.display(), err);
        }
    }
    *CONFIG_PATH.write().unwrap() = Some(path);
}

/// Read the current config. Cheap — clones two small strings.
pub fn get() -> Config {
    CONFIG.read().unwrap().clone()
}

/// Overwrite in memory + persist to disk. Errors bubble up so the
/// UI can surface a save-failed message. Callers must have called
/// [`init`] first, or the on-disk write becomes a no-op with a
/// warning.
pub fn set(mut new_cfg: Config) -> Result<(), String> {
    new_cfg.normalize();
    let path_guard = CONFIG_PATH.read().unwrap();
    let path = match &*path_guard {
        Some(p) => p.clone(),
        None => {
            return Err("config not initialized — setup() didn't call config::init()".into());
        }
    };
    drop(path_guard);

    let json = serialize_json(&new_cfg);
    std::fs::write(&path, json).map_err(|e| format!("write {}: {}", path.display(), e))?;
    *CONFIG.write().unwrap() = new_cfg;
    Ok(())
}

/// Minimal JSON parse — we control both writer and reader, so we
/// only need to handle the exact shape we produce. Anything else
/// returns None and the caller keeps the defaults.
///
/// Deliberately not pulling in serde/serde_json for two fields —
/// that's ~200 KB of binary bloat we don't need. If the config
/// schema ever grows to more than a handful of fields, switch.
fn parse_json(text: &str) -> Option<Config> {
    let mut cfg = Config::default();
    let mut matched_anything = false;
    for line in text.lines() {
        let line = line.trim().trim_end_matches(',');
        // Match `"key": "value"` OR `"key": bool`. The value trim
        // strategy handles both — booleans have no surrounding
        // quotes, so trim_matches('"') on them is a no-op.
        let (raw_key, raw_val) = match line.split_once(':') {
            Some(pair) => pair,
            None => continue,
        };
        let key = raw_key.trim().trim_matches('"');
        let val = raw_val.trim().trim_matches('"').trim_end_matches(',').trim_matches('"');
        match key {
            "api_url" => { cfg.api_url = val.to_string(); matched_anything = true; }
            "api_token" => { cfg.api_token = val.to_string(); matched_anything = true; }
            "open_after_upload" => {
                cfg.open_after_upload = val.eq_ignore_ascii_case("true");
                matched_anything = true;
            }
            _ => {}
        }
    }
    // Refuse to return if we matched no known keys — sign we're
    // reading a garbage file, better to keep in-memory defaults
    // (production URL, empty token, upload-then-stay-in-game).
    if !matched_anything {
        return None;
    }
    if cfg.api_url.is_empty() {
        cfg.api_url = DEFAULT_API_URL.to_string();
    }
    Some(cfg)
}

/// Emit `{"api_url": "...", "api_token": "..."}` with basic JSON
/// escaping. Tokens shouldn't contain `"` or `\` but the URL
/// theoretically could (path with a special char), so escape both.
/// Emit `{"api_url": "...", "api_token": "...", "open_after_upload": bool}`.
/// Deliberately one-field-per-line: the parser is line-based (splits
/// on `\n` then `:`) so a hand-edit that collapses everything onto
/// one line breaks parsing. If someone reformats this file, they
/// need to keep the newlines. Documented in [`parse_json`] too.
fn serialize_json(cfg: &Config) -> String {
    format!(
        "{{\n  \"api_url\": \"{}\",\n  \"api_token\": \"{}\",\n  \"open_after_upload\": {}\n}}\n",
        escape(&cfg.api_url),
        escape(&cfg.api_token),
        if cfg.open_after_upload { "true" } else { "false" },
    )
}

fn escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            _ => out.push(c),
        }
    }
    out
}
