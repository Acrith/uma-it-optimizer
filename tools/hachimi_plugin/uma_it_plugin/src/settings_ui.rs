//! Renders the "IT Extractor Settings" section in Hachimi's in-game
//! menu (F1). Lets the user paste an API token + optionally override
//! the API URL, then persists both to disk via [`crate::config`].
//!
//! **Why this exists as a UI instead of a config file to edit.** The
//! user reported that editing an external JSON in Notepad is friction
//! for community users — most only know the game and the site.
//! Reusing Hachimi's already-in-game menu means the whole flow (get
//! token from site → paste into game → click Save → click Extract) is
//! keyboard-and-mouse without leaving the game window.
//!
//! **imgui buffer lifecycle.** `gui_ui_text_edit_singleline` takes a
//! `*mut c_char` + capacity. The buffer must stay allocated across
//! frames because imgui writes into it as the user types. Solution:
//! a `Mutex`-wrapped `UiState` with fixed-size byte buffers, held for
//! the process lifetime. The mutex is uncontended in practice — the
//! UI thread is the only writer — but keeps future off-thread reads
//! safe.

use std::ffi::{c_char, c_void, CString};
use std::sync::Mutex;

use edge_sdk::api::Api;
use log::{error, info, warn};
use once_cell::sync::Lazy;

use crate::config;

/// Text-edit buffer sizes. Chosen wide enough that any realistic
/// API URL or token fits comfortably. Tokens from the site are
/// 43-char URL-safe base64 currently; 128 gives room to grow.
const URL_BUF_CAP: usize = 256;
const TOKEN_BUF_CAP: usize = 128;

struct UiState {
    /// Buffer that imgui writes user input into. Null-terminated
    /// C string. First frame loads from persisted config; subsequent
    /// frames leave alone so the user's in-progress edits survive
    /// menu reopen.
    url_buf: [u8; URL_BUF_CAP],
    token_buf: [u8; TOKEN_BUF_CAP],
    /// Set on first render — we need Api available to load config,
    /// which requires setup() to have completed. Fine to lazily
    /// initialize inside render_section.
    loaded_from_disk: bool,
    /// Sticky "last save/upload result" line. Refreshed by Save
    /// button and by the upload path after a capture. Empty string
    /// = don't render the status label at all.
    status_line: String,
}

impl UiState {
    const fn new() -> Self {
        Self {
            url_buf: [0u8; URL_BUF_CAP],
            token_buf: [0u8; TOKEN_BUF_CAP],
            loaded_from_disk: false,
            status_line: String::new(),
        }
    }

    /// Read what the user has typed as a Rust String, stopping at
    /// the first NUL. imgui always null-terminates on edit.
    fn url_as_string(&self) -> String {
        cstr_to_string(&self.url_buf)
    }
    fn token_as_string(&self) -> String {
        cstr_to_string(&self.token_buf)
    }
}

static STATE: Lazy<Mutex<UiState>> = Lazy::new(|| Mutex::new(UiState::new()));

/// Called from `on_menu_click` (or wherever an upload attempt runs)
/// to surface the outcome inside the settings section. Kept as a
/// plain fn rather than a method on UiState so callers don't have
/// to reach into the mutex themselves.
pub fn set_status(line: impl Into<String>) {
    let text = line.into();
    if let Ok(mut st) = STATE.lock() {
        st.status_line = text;
    }
}

/// Register the settings section with Hachimi. Called once from
/// `setup()`. Returns false if Hachimi is too old to expose the
/// register_menu_section entry — non-fatal, the plugin still works
/// with the on-disk config file, just no in-game editing.
pub fn register(api: &Api) -> bool {
    let register = match api.gui_register_menu_section {
        Some(f) => f,
        None => {
            warn!(
                "[uma-it] gui_register_menu_section missing — settings UI \
                 unavailable, users must edit uma_it_plugin_config.json by hand"
            );
            return false;
        }
    };
    let ok = unsafe { register(Some(render_section), std::ptr::null_mut()) };
    if ok {
        info!("[uma-it] settings section registered");
    } else {
        warn!("[uma-it] gui_register_menu_section returned false");
    }
    ok
}

/// Hachimi's callback for the settings section. Called every frame
/// the menu is open. Renders heading → URL edit → token edit → Save
/// button → status line.
extern "C" fn render_section(ui: *mut c_void, _userdata: *mut c_void) {
    let api = Api::get();

    let mut st = match STATE.lock() {
        Ok(s) => s,
        Err(_) => return, // mutex poisoned — bail silently, will retry next frame
    };

    // Lazy load-from-disk on first render. We can't do it in
    // register() because at that point config::init() may not have
    // been called yet if register runs before setup's config::init
    // call — cheap to defer.
    if !st.loaded_from_disk {
        let cfg = config::get();
        write_into_cstr_buf(&mut st.url_buf, &cfg.api_url);
        write_into_cstr_buf(&mut st.token_buf, &cfg.api_token);
        st.loaded_from_disk = true;
    }

    // No heading — gui_ui_heading renders at page-title size which
    // reads as visually broken inside a narrow menu section. The
    // label "IT auto-upload" on the small hint below is enough to
    // orient the user, and the URL/Token labels self-describe the
    // fields. (Earlier v0.0.9 used gui_ui_heading and the text
    // wrapped mid-word — see git log for the screenshot.)

    // One-line hint. Keep short — Hachimi's menu is narrow and any
    // wrap looks messy.
    if let Some(small) = api.gui_ui_small {
        let s = CString::new("IT auto-upload — token: umaladder.moe/settings/tokens").unwrap();
        unsafe { small(ui, s.as_ptr()); }
    }

    // URL row
    if let Some(label) = api.gui_ui_label {
        let s = CString::new("URL").unwrap();
        unsafe { label(ui, s.as_ptr()); }
    }
    if let Some(edit) = api.gui_ui_text_edit_singleline {
        unsafe {
            edit(
                ui,
                st.url_buf.as_mut_ptr() as *mut c_char,
                URL_BUF_CAP,
            );
        }
    }

    // Token row
    if let Some(label) = api.gui_ui_label {
        let s = CString::new("Token").unwrap();
        unsafe { label(ui, s.as_ptr()); }
    }
    if let Some(edit) = api.gui_ui_text_edit_singleline {
        unsafe {
            edit(
                ui,
                st.token_buf.as_mut_ptr() as *mut c_char,
                TOKEN_BUF_CAP,
            );
        }
    }

    // Save button
    if let Some(button) = api.gui_ui_button {
        let s = CString::new("Save").unwrap();
        let clicked = unsafe { button(ui, s.as_ptr()) };
        if clicked {
            let new_cfg = config::Config {
                api_url: st.url_as_string(),
                api_token: st.token_as_string(),
            };
            match config::set(new_cfg) {
                Ok(()) => {
                    st.status_line = "Saved.".to_string();
                    info!("[uma-it] settings saved via UI");
                }
                Err(msg) => {
                    st.status_line = format!("Save failed: {}", msg);
                    error!("[uma-it] settings save failed: {}", msg);
                }
            }
        }
    }

    // Status line inline (no separator above — the section itself
    // is already visually separated from other menu content).
    if !st.status_line.is_empty() {
        if let Some(small) = api.gui_ui_small {
            if let Ok(cs) = CString::new(st.status_line.as_str()) {
                unsafe { small(ui, cs.as_ptr()); }
            }
        }
    }
}

/// Copy `src` into `buf`, truncating if too long, always leaving
/// room for a trailing NUL. Zeroes any trailing bytes so imgui sees
/// a clean null-terminated string even if the previous buffer
/// content was longer.
fn write_into_cstr_buf(buf: &mut [u8], src: &str) {
    for b in buf.iter_mut() {
        *b = 0;
    }
    let cap = buf.len().saturating_sub(1);
    let bytes = src.as_bytes();
    let n = bytes.len().min(cap);
    buf[..n].copy_from_slice(&bytes[..n]);
}

/// Read a Rust String from a null-terminated byte buffer. Stops at
/// the first NUL; non-UTF-8 bytes are lossily replaced. In practice
/// URLs and base64 tokens are always ASCII.
fn cstr_to_string(buf: &[u8]) -> String {
    let end = buf.iter().position(|&b| b == 0).unwrap_or(buf.len());
    String::from_utf8_lossy(&buf[..end]).into_owned()
}
