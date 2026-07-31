//! uma-it Hachimi plugin — v1.0.0 (auto-upload to /api/runs).
//!
//! Adds a Hachimi in-game menu entry ("Extract IT Run") that walks
//! the IL2CPP GC heap for live IT gameplay classes, serializes them
//! to the same JSON schema the `.exe` Frida extractor emits, writes
//! it to disk, and (if the user has pasted an API token via the
//! Hachimi settings section) POSTs it to
//! `training.umaladder.moe/api/runs`.
//!
//! **v0.0.9 changes vs v0.0.8f (full-parity JSON on disk):**
//! - Extractor-style filename `<YYYYMMDDTHHMMSS>_scen<N>_uma<N>.json`
//!   built from SMC's scenario_id + card_id (v0.0.8 used
//!   `uma_it_capture_<epoch>.json` which the server's filename
//!   validator rejects).
//! - Config module (URL + token) persisted at
//!   `<hachimi_base>/uma_it_plugin_config.json`, matching the
//!   `.exe` extractor's config shape.
//! - Settings section in Hachimi's menu for pasting the token
//!   in-game — no file to edit externally.
//! - HTTP POST after successful disk write, if configured.
//!   Notifications surface success / dupe / error.
//!
//! Deliberately gated behind an explicit user click so the scan
//! (20-80ms, freezes all mutator threads) never runs when the user
//! doesn't expect it.
//!
//! Prior versions (dropped in v0.0.6):
//! - v0.0.1..v0.0.3: hooked DialogTrainedCharacterDetail::CreateSetupParameter
//!   (installed cleanly but fired on the wrong dialog — Trained
//!   Umas viewer, not IT log)
//! - v0.0.4: hooked GainInfo::.ctor with no inheritance check —
//!   trampoline was Object.ctor, hosed framerate to 5fps
//! - v0.0.5: added declared-on-class check so Object.ctor gets
//!   refused; plugin became a safe no-op (GainInfo has no
//!   declared ctor to hook)
//!
//! The pivot to heap-scan matches the Frida extractor's approach
//! (see `tools/memory_extractor/dump_it_run.py:255`) and is
//! resilient to game updates — Cygames can rename methods and
//! dialogs freely, we only depend on the data class name
//! (`ObscuredIdleSingleModeGainInfo`) which has been stable
//! across builds.

use std::ffi::{c_void, CString};

use edge_sdk::api::Api;
use log::{error, info};

mod config;
mod gc_scan;
mod http;
mod introspect;
mod json;
mod settings_ui;

edge_sdk::declare_plugin! {
    fn init() -> bool {
        info!("[uma-it] plugin loaded (v{})", env!("CARGO_PKG_VERSION"));

        // Try full init eagerly. On the late-load path (LoadLibraryW hook)
        // the game is already up when we arrive, so the assembly image and
        // GC symbols are all resolvable right now — no need to wait.
        //
        // On the early-load path (DXGI proxy) IL2CPP might not be up yet;
        // fall back to registering a game_initialized callback if any
        // resolution fails with "image not loaded" style errors.
        match unsafe { setup() } {
            Ok(()) => {
                info!("[uma-it] setup complete — 'Extract IT Run' available in Hachimi menu");
                return true;
            }
            Err(msg) => {
                info!("[uma-it] eager setup skipped ({msg}); registering game_initialized fallback");
            }
        }

        let api = Api::get();
        let register = match api.hachimi_register_on_game_initialized {
            Some(f) => f,
            None => {
                error!(
                    "[uma-it] hachimi_register_on_game_initialized not in vtable — \
                     Hachimi-Edge too old? Need VERSION >= 3"
                );
                return false;
            }
        };
        unsafe { register(Some(on_game_initialized), std::ptr::null_mut()); }
        true
    }
}

unsafe extern "C" fn on_game_initialized(_userdata: *mut c_void) {
    info!("[uma-it] game_initialized fired — running deferred setup");
    if let Err(msg) = setup() {
        error!("[uma-it] deferred setup failed: {msg}");
    } else {
        info!("[uma-it] deferred setup complete");
    }
}

/// One-time init: resolve the target class + GC symbols, register
/// the "Extract IT Run" menu item. Called eagerly from init() and
/// (if that fails) again from on_game_initialized.
///
/// Safe to call twice — resolve() short-circuits on the second
/// call, menu registration is idempotent-ish (registering the
/// same label twice would create a duplicate entry, but the
/// eager+fallback pattern never actually calls setup() twice on
/// the same launch — the eager Ok path returns before the
/// fallback registration).
unsafe fn setup() -> Result<(), String> {
    let api = Api::get();

    // Locate the two assembly images we scan classes from.
    // - `umamusume` holds the gameplay data classes (GainInfo etc.)
    // - `umamusume.Http` holds the HTTP DTOs (SingleModeChara,
    //   race histories) — same as what dump_it_run.py uses.
    let get_image = api
        .il2cpp_get_assembly_image
        .ok_or("il2cpp_get_assembly_image missing from vtable")?;
    let umamusume = CString::new("umamusume").unwrap();
    let umamusume_http = CString::new("umamusume.Http").unwrap();
    let img_main = get_image(umamusume.as_ptr());
    if img_main.is_null() {
        return Err("umamusume assembly image not loaded — game not fully up?".into());
    }
    let img_http = get_image(umamusume_http.as_ptr());
    if img_http.is_null() {
        return Err("umamusume.Http assembly image not loaded — game not fully up?".into());
    }
    let get_class = api
        .il2cpp_get_class
        .ok_or("il2cpp_get_class missing from vtable")?;
    let ns_gallop = CString::new("Gallop").unwrap();

    // Resolve the GC + metadata symbols EARLY — the Parents
    // registration below needs il2cpp_image_get_class,
    // il2cpp_type_get_name, and il2cpp_free from these
    // (find_class_by_full_name enumerates + matches type names).
    // Historically these were resolved after target registration,
    // which fine when all targets used il2cpp_get_class directly.
    gc_scan::resolve(api)?;
    info!("[uma-it] IL2CPP liveness API resolved (Unity 2021.2+ path)");
    introspect::resolve(api)?;
    info!("[uma-it] IL2CPP metadata API resolved (field enumeration + type-name lookup ready)");

    // Register every class the .exe extractor heap-scans
    // (dump_it_run.py:317-322 + dumpParents:150-192). Labels match
    // the extractor's JSON keys exactly — the web-app enrich
    // modules read those specific keys, so any rename here breaks
    // web-app compatibility.
    //
    // pick_by: for classes where the scan finds multiple template
    // instances but we only want the "real" one, pick the match
    // with the highest value at the given int32 field. Matches
    // the extractor's picker logic (dump_it_run.py:517).
    let targets: [(&'static str, &'static str, *const edge_sdk::ffi::Il2CppImage, Option<&'static str>); 6] = [
        ("GainInfo",                     "ObscuredIdleSingleModeGainInfo",                   img_main, None),
        ("SupportCardGainInfo",          "ObscuredIdleSingleModeSupportCardGainInfo",        img_main, None),
        // v0.0.8a used "FactorGainInfo" here — extractor uses the
        // full name "SuccessionFactorGainInfo" (dump_it_run.py:320),
        // and run_metrics.py:245 reads that specific key. Renamed.
        ("SuccessionFactorGainInfo",     "ObscuredIdleSingleModeSuccessionFactorGainInfo",   img_main, None),
        // v0.0.7f showed 3 SMC instances with the first being all-zeros
        // (template). Pick the one with highest fans — real gameplay data.
        ("SingleModeChara",              "SingleModeChara",                                  img_http, Some("fans")),
        ("RaceHistory",                  "SingleRaceHistory",                                img_http, None),
        // v0.0.8a used "IdleRaceHistory" — extractor uses the full
        // "IdleSingleModeRaceHistory" name (dump_it_run.py:322).
        ("IdleSingleModeRaceHistory",    "IdleSingleModeRaceHistory",                        img_http, None),
    ];
    let mut resolved = 0;
    for (label, cls_name, image, pick_by) in targets {
        let cname = CString::new(cls_name).unwrap();
        let klass = get_class(image, ns_gallop.as_ptr(), cname.as_ptr());
        if klass.is_null() {
            error!(
                "[uma-it] class not resolved: Gallop.{} — skipping (game update?)",
                cls_name
            );
            continue;
        }
        info!("[uma-it] target: [{}] Gallop.{} @ {:p}", label, cls_name, klass);
        // display is the fully-qualified name for the "no matches" hint.
        // Leaking the String is fine — 7 tiny allocations that live for
        // the process lifetime.
        let display: &'static str = Box::leak(format!("Gallop.{}", cls_name).into_boxed_str());
        gc_scan::add_target(gc_scan::TargetClass {
            label,
            display,
            class: klass,
            pick_by,
        });
        resolved += 1;
    }

    // Parents — enumerate img_main's classes and find the one
    // whose flattened type name matches
    // `"Gallop.WorkTrainedCharaData.TrainedCharaData"`. This
    // matches what Frida's `image.classes` + `type.name` check
    // does in the .exe extractor (dump_it_run.py:150-165).
    //
    // History of getting this right:
    // - v0.0.8b: il2cpp_find_nested_class assumed truly nested
    //   → returned a private inner helper class whose live set
    //   was 269 stale records, all with SCL=null.
    // - v0.0.8d: il2cpp_get_class(image, "Gallop.WorkTrainedCharaData",
    //   "TrainedCharaData") assumed dotted-namespace top-level
    //   → returned NULL (class isn't registered under that name
    //   in the get_class lookup table).
    // - v0.0.8e (this): enumerate + match by full type name via
    //   il2cpp_type_get_name, same algorithm Frida uses. Whichever
    //   representation IL2CPP uses internally, this finds it.
    match unsafe {
        introspect::find_class_by_full_name(
            img_main as *const _,
            "Gallop.WorkTrainedCharaData.TrainedCharaData",
        )
    } {
        Some(parents_class) => {
            info!(
                "[uma-it] target: [Parents] Gallop.WorkTrainedCharaData.TrainedCharaData @ {:p} (found via image.classes enumeration)",
                parents_class
            );
            let display: &'static str = Box::leak(
                "Gallop.WorkTrainedCharaData.TrainedCharaData"
                    .to_string()
                    .into_boxed_str(),
            );
            gc_scan::add_target(gc_scan::TargetClass {
                label: "Parents",
                display,
                class: parents_class,
                pick_by: None,
            });
            resolved += 1;
        }
        None => {
            error!(
                "[uma-it] Gallop.WorkTrainedCharaData.TrainedCharaData not found in img_main class iteration — Parents scan disabled"
            );
        }
    }

    if resolved == 0 {
        return Err("no target classes resolved — either the game version is very off or the images aren't loaded".into());
    }
    info!("[uma-it] {}/7 target classes resolved for scanning", resolved);

    // GC + metadata symbols already resolved earlier in this
    // function (moved up so Parents registration could use
    // find_class_by_full_name).

    // Register "Extract IT Run" as a top-level menu item under
    // Hachimi's Plugins category. v1.0.1 tried moving it into the
    // settings section to group Extract + Token together; user
    // preferred the original split (button up top, config below),
    // so it's back here. Callback fires on the game's GUI thread —
    // safe context for IL2CPP GC scans.
    let register_menu = api.gui_register_menu_item.ok_or(
        "gui_register_menu_item missing from vtable — Hachimi-Edge too old?",
    )?;
    let label = CString::new("Extract IT Run").unwrap();
    let ok = register_menu(label.as_ptr(), Some(on_menu_click), std::ptr::null_mut());
    if !ok {
        return Err(
            "gui_register_menu_item returned false — menu likely not ready yet".into(),
        );
    }

    // Persistent config for auto-upload. We need Hachimi's base dir
    // to know where to load/save the config file. Fine to init here
    // (rather than lazily on first UI render) so the config is
    // available for a POST attempt even if the user never opens the
    // settings section this session.
    let get_base_dir = api
        .hachimi_get_base_dir
        .ok_or("hachimi_get_base_dir missing from vtable — needed for config persistence")?;
    let base_dir_ptr = get_base_dir();
    if base_dir_ptr.is_null() {
        return Err("hachimi_get_base_dir returned null during setup".into());
    }
    let base_dir_str = std::ffi::CStr::from_ptr(base_dir_ptr)
        .to_string_lossy()
        .into_owned();
    config::init(std::path::Path::new(&base_dir_str));

    // Settings section: URL + token inputs. Non-fatal if it fails
    // to register (older Hachimi missing the API) — the plugin still
    // works with an on-disk config the user edits by hand.
    settings_ui::register(api);

    Ok(())
}

/// Menu callback for "Extract IT Run" — fires on Hachimi's GUI
/// thread when the user clicks the item. Heap-scans every target
/// class, serializes to the extractor's JSON schema, writes to
/// disk, POSTs to /api/runs if configured. Each step is surfaced
/// via a Hachimi notification + the settings-panel status line.
///
/// extern "C" (not unsafe extern "C") because GuiMenuCallback in
/// edge-sdk is defined that way. The scan itself is unsafe, but
/// the callback wrapper isn't.
extern "C" fn on_menu_click(_userdata: *mut c_void) {
    gc_scan::scan_and_log();
    let (filename, bytes) = match write_capture_to_disk() {
        Ok(pair) => pair,
        Err(msg) => {
            error!("[uma-it] failed to write capture file: {msg}");
            notify(&format!("Extract failed: {msg}"));
            settings_ui::set_status(format!("Last extract: FAILED ({msg})"));
            return;
        }
    };
    notify(&format!("Saved capture: {filename}"));

    // Upload — silently a no-op if the user hasn't configured a
    // token. That's fine: the on-disk JSON is the fallback for a
    // manual upload via the site's Upload page.
    let cfg = config::get();
    if !cfg.is_ready() {
        settings_ui::set_status(format!(
            "Last extract: {filename} (saved locally — set an API token to auto-upload)"
        ));
        return;
    }
    match http::upload_run(&cfg.api_url, &cfg.api_token, &filename, &bytes) {
        http::UploadOutcome::Created { url } => {
            info!("[uma-it] uploaded {} → {:?}", filename, url);
            notify(&format!("Uploaded {filename}"));
            settings_ui::set_status(format!("Last upload: OK ({filename})"));
            // Opt-in browser hand-off. Off by default because Alt-
            // tabbing out of a fullscreen game mid-session is
            // disruptive; users who want the extractor-style "open
            // page on upload" flip the checkbox in settings.
            if cfg.open_after_upload {
                if let Some(u) = url {
                    open_url_in_browser(&u);
                }
            }
        }
        http::UploadOutcome::Duplicate => {
            info!("[uma-it] {} was a duplicate — server already has it", filename);
            notify("Already uploaded (server has this run)");
            settings_ui::set_status(format!("Last upload: DUPLICATE ({filename})"));
        }
        http::UploadOutcome::HttpError { code, body_snippet } => {
            error!("[uma-it] upload {} failed: HTTP {} — {}", filename, code, body_snippet);
            notify(&format!("Upload failed: HTTP {code}"));
            settings_ui::set_status(format!(
                "Last upload: HTTP {code} — check log ({filename})"
            ));
        }
        http::UploadOutcome::Transport(msg) => {
            error!("[uma-it] upload {} network error: {}", filename, msg);
            notify(&format!("Upload failed: network — {msg}"));
            settings_ui::set_status(format!("Last upload: NETWORK error ({filename})"));
        }
        http::UploadOutcome::NotConfigured => {
            // is_ready() gated this branch; getting here means the
            // config emptied between the check and the call. Treat
            // as the same "saved locally" path.
            settings_ui::set_status(format!(
                "Last extract: {filename} (saved locally — token missing)"
            ));
        }
    }
}

/// Show a toast via Hachimi if available. No-op if the API isn't
/// resolvable (very old Hachimi) — the settings status line and
/// the log still carry the message.
fn notify(text: &str) {
    let api = Api::get();
    if let Some(show) = api.gui_show_notification {
        if let Ok(cs) = CString::new(text) {
            unsafe { show(cs.as_ptr()); }
        }
    }
}

/// Launch the system default browser at `url` on Windows via
/// `cmd /C start "" <url>`. The empty `""` is start's window-title
/// argument — required so start doesn't treat the URL itself as
/// the title. We fire-and-forget; any failure just logs so a
/// broken shell association doesn't cascade into a plugin crash.
fn open_url_in_browser(url: &str) {
    // Reject URLs with control chars or embedded shell metacharacters
    // as a defence-in-depth measure. The server-emitted url in
    // /api/runs's 201 response is a plain https URL under our own
    // domain, so a hostile URL would only arise from a
    // man-in-the-middle attack on the upload response — but there's
    // no good reason ever to pass one of these into a shell start.
    if url.chars().any(|c| c.is_control() || c == '"' || c == '&' || c == '|' || c == '^') {
        error!("[uma-it] refusing to open URL with suspicious characters: {url:?}");
        return;
    }
    match std::process::Command::new("cmd")
        .args(["/C", "start", "", url])
        .spawn()
    {
        Ok(_) => info!("[uma-it] opened {} in default browser", url),
        Err(e) => error!("[uma-it] failed to launch browser for {}: {}", url, e),
    }
}

/// Extract `succession_trained_chara_id_1` and `_2` from a walked
/// SingleModeChara JsonValue. Returns `[id1, id2]` if both present
/// and non-zero, else None. Used to filter Parents down to the
/// two direct-parent instances.
fn extract_succession_ids(smc: &json::JsonValue) -> Option<[i64; 2]> {
    let id1 = extract_int_field(smc, "succession_trained_chara_id_1")?;
    let id2 = extract_int_field(smc, "succession_trained_chara_id_2")?;
    if id1 > 0 && id2 > 0 {
        Some([id1, id2])
    } else {
        None
    }
}

/// Pull one named integer field from a walked Object value. Returns
/// None if the value isn't an Object, the key isn't there, or its
/// value isn't an Int. Small helper used to grab scenario_id /
/// card_id from SMC for the extractor-style filename.
fn extract_int_field(obj: &json::JsonValue, key: &str) -> Option<i64> {
    let json::JsonValue::Object(entries) = obj else { return None; };
    for (k, v) in entries {
        if k == key {
            if let json::JsonValue::Int(i) = v {
                return Some(*i);
            }
        }
    }
    None
}

/// Build the extractor-compatible filename
/// `<YYYYMMDDTHHMMSS>_scen<N>_uma<N>.json` from SMC's metadata.
///
/// Uses local time (not UTC) to match the `.exe` extractor's
/// `_output_name()` which uses `datetime.now().strftime(...)` —
/// keeps filenames consistent between the two capture paths so
/// they sort together in a shared runs folder.
///
/// Returns None if SMC didn't yield the two required IDs; callers
/// fall back to the epoch-based name and skip API upload (which
/// would fail server-side filename validation anyway).
fn extractor_filename(smc: &json::JsonValue) -> Option<String> {
    let scenario_id = extract_int_field(smc, "scenario_id")?;
    let card_id = extract_int_field(smc, "card_id")?;
    let ts = chrono::Local::now().format("%Y%m%dT%H%M%S").to_string();
    Some(format!("{ts}_scen{scenario_id}_uma{card_id}.json"))
}

/// Re-scan every registered class, build a JSON capture, write it
/// to `<hachimi_base>\IT\<filename>.json`, and return (filename,
/// bytes) so the caller can also POST it.
///
/// This is a SECOND set of scans on top of gc_scan::scan_and_log's
/// dumps. Doubles the click-to-file latency but keeps the log
/// dump as a distinct debug artifact — we can drop the log-based
/// dump later once the JSON is confirmed correct across builds.
fn write_capture_to_disk() -> Result<(String, Vec<u8>), String> {
    use json::JsonValue;
    let api = Api::get();
    let get_base_dir = api
        .hachimi_get_base_dir
        .ok_or("hachimi_get_base_dir missing from vtable")?;
    let base_dir_ptr = unsafe { get_base_dir() };
    if base_dir_ptr.is_null() {
        return Err("hachimi_get_base_dir returned null".into());
    }
    let base_dir = unsafe { std::ffi::CStr::from_ptr(base_dir_ptr) }
        .to_string_lossy()
        .into_owned();

    let targets = gc_scan::snapshot_targets();
    if targets.is_empty() {
        return Err("no target classes registered".into());
    }
    let mut root: Vec<(String, JsonValue)> = Vec::new();
    root.push((
        "plugin_version".into(),
        JsonValue::string(concat!("hachimi-v", env!("CARGO_PKG_VERSION"))),
    ));

    // Stash the walked SMC — needed after the loop for the
    // extractor-style filename (scenario_id + card_id come from it).
    let mut smc_walked: Option<JsonValue> = None;

    // Two-pass build so we can filter Parents by SMC's succession
    // IDs: iterate SMC first, remember its two parent IDs, use
    // them to filter the Parents scan down from 269 heap instances
    // to just the 2 direct parents (matches extractor behavior).
    // Extractor filter: succession_trained_chara_id_1 / _2 →
    // TrainedCharaData._id must match one.
    let mut parent_id_filter: Option<[i64; 2]> = None;

    let mut per_class_counts: Vec<(String, JsonValue)> = Vec::new();
    // Iterate in registration order — SingleModeChara is registered
    // before Parents in setup(), so its succession IDs are
    // available when we get to Parents. Not a hard guarantee; if
    // this ever breaks, restructure into an explicit two-phase
    // walk.
    for target in &targets {
        if target.class.is_null() {
            continue;
        }
        let scan = unsafe { gc_scan::scan_class(target.class) };
        let res = match scan {
            Ok(r) => r,
            Err(msg) => {
                error!("[uma-it] rescan for JSON failed on [{}]: {msg}", target.label);
                continue;
            }
        };
        per_class_counts.push((
            target.label.to_string(),
            JsonValue::Int(res.matches.len() as i64),
        ));
        if res.matches.is_empty() {
            root.push((target.label.to_string(), JsonValue::Null));
            continue;
        }
        // For classes with a picker (SingleModeChara), only emit
        // the picked one as a single object. Others: emit array
        // of all walked matches (matches the extractor's format).
        let value = match target.pick_by {
            Some(field_name) => {
                let picked = unsafe {
                    introspect::pick_best_by_int_field(&res.matches, field_name)
                        .map(|(p, _)| p)
                        .unwrap_or(res.matches[0])
                };
                let walked = unsafe { introspect::walk_to_json(picked) };
                // If this is SingleModeChara (or any class with a
                // picker), extract the two succession IDs so we
                // can filter Parents, AND stash the walked object
                // so we can pull scenario_id + card_id after the
                // loop for the extractor-style filename.
                if target.label == "SingleModeChara" {
                    parent_id_filter = extract_succession_ids(&walked);
                    if let Some(ids) = parent_id_filter {
                        info!("[uma-it] parent-filter IDs from SMC: {} and {}", ids[0], ids[1]);
                    }
                    smc_walked = Some(walked.clone());
                }
                // Wrap picked-single in a 1-element array so the
                // output schema matches the .exe extractor's
                // (`SingleModeChara: [{...}]`, not `SingleModeChara:
                // {...}`). Server-side ingest validates this shape
                // and rejects with HTTP 400 "SingleModeChara must be
                // a non-empty list" if we emit a bare object.
                JsonValue::Array(vec![walked])
            }
            None if target.label == "Parents" => {
                // Filter to matches whose `_id` is in the succession
                // set. Walking still happens per match; filter after
                // walk is fine (Parent walk is small — ~few KB each).
                let filter = parent_id_filter;
                let items: Vec<JsonValue> = res
                    .matches
                    .iter()
                    .map(|&obj| unsafe { introspect::walk_to_json(obj) })
                    .filter(|v| {
                        let Some(ids) = filter else { return true; };
                        // Extract _id from walked JsonValue::Object
                        match v {
                            JsonValue::Object(entries) => entries.iter().any(|(k, val)| {
                                if k != "_id" { return false; }
                                if let JsonValue::Int(i) = val {
                                    return ids.contains(i);
                                }
                                false
                            }),
                            _ => false,
                        }
                    })
                    .collect();
                info!(
                    "[uma-it] Parents filtered from {} → {} matching succession IDs",
                    res.matches.len(),
                    items.len()
                );
                JsonValue::Array(items)
            }
            None => {
                let items: Vec<JsonValue> = res
                    .matches
                    .iter()
                    .map(|&obj| unsafe { introspect::walk_to_json(obj) })
                    .collect();
                JsonValue::Array(items)
            }
        };
        root.push((target.label.to_string(), value));
    }
    root.push(("_scan_counts".into(), JsonValue::Object(per_class_counts)));

    let json = JsonValue::Object(root).to_pretty();
    // Extractor-style filename `<local-ts>_scen<N>_uma<N>.json`
    // built from SMC's scenario_id + card_id. Server-side filename
    // validator rejects anything else, so if SMC didn't yield both
    // IDs we fall back to an epoch-suffixed name and let the caller
    // skip the API upload — the on-disk file is still recoverable
    // via manual upload.
    let filename = match smc_walked.as_ref().and_then(extractor_filename) {
        Some(name) => name,
        None => {
            let epoch = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0);
            format!("uma_it_capture_{epoch}.json")
        }
    };
    let base = base_dir.trim_end_matches(['/', '\\']);
    let dir = format!("{}\\IT", base);
    std::fs::create_dir_all(&dir).map_err(|e| format!("create dir {}: {}", dir, e))?;
    let path = format!("{}\\{}", dir, filename);
    let bytes = json.into_bytes();
    std::fs::write(&path, &bytes).map_err(|e| format!("write {}: {}", path, e))?;
    info!("[uma-it] wrote capture ({} bytes) to {}", bytes.len(), path);
    Ok((filename, bytes))
}
