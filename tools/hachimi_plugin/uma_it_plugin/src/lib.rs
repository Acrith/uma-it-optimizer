//! uma-it Hachimi plugin — v0.0.7 (Phase 1: heap-scan + field walk POC).
//!
//! Adds a Hachimi in-game menu entry ("Extract IT Run") that,
//! when clicked, walks the IL2CPP GC heap for live instances of
//! `Gallop.ObscuredIdleSingleModeGainInfo` — the same class the
//! Frida extractor scans for. Instances only exist while the
//! Training Log popup is open, so the count directly tells us
//! whether the game state is "ready to capture."
//!
//! This is a proof of concept — v0.0.6 only logs the count.
//! v0.0.7 walks the instances' fields; v0.0.8 POSTs the run to
//! /api/runs. Deliberately gated behind an explicit user click
//! so the scan (20-80ms, freezes all mutator threads) never
//! runs when the user doesn't expect it.
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

mod gc_scan;
mod introspect;
mod json;

edge_sdk::declare_plugin! {
    fn init() -> bool {
        info!("[uma-it] plugin loaded (v0.0.6 heap-scan POC)");

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

    // Parents — TOP-LEVEL class with dot-in-namespace naming.
    // Namespace `Gallop.WorkTrainedCharaData`, class name
    // `TrainedCharaData`. NOT a nested class — despite the dot
    // in the name suggesting one.
    //
    // Extractor's dumpParents finds this by iterating
    // image.classes (top-level only, no nested-class recursion)
    // and matching `type.name` == the full flattened name
    // (dump_it_run.py:150-165, verified against frida-il2cpp-bridge
    // lib/structs/image.ts).
    //
    // v0.0.8b used il2cpp_find_nested_class assuming truly nested
    // — that returned a DIFFERENT Il2CppClass* (probably an inner
    // private helper) whose live-instance set was 269 stale
    // TrainedCharaData records, all with SuccessionCharaList=null.
    // Same-session comparison with the .exe extractor proved the
    // discrepancy: extractor found 2 objects (current parents,
    // SCL populated), plugin's nested-class scan found 269 (all
    // SCL null). Fixed by using il2cpp_get_class with the
    // dot-separated namespace instead of find_nested_class.
    let parents_ns = CString::new("Gallop.WorkTrainedCharaData").unwrap();
    let parents_name = CString::new("TrainedCharaData").unwrap();
    let parents_class = get_class(img_main, parents_ns.as_ptr(), parents_name.as_ptr());
    if parents_class.is_null() {
        error!(
            "[uma-it] Gallop.WorkTrainedCharaData.TrainedCharaData not found — Parents scan disabled"
        );
    } else {
        info!(
            "[uma-it] target: [Parents] Gallop.WorkTrainedCharaData.TrainedCharaData @ {:p}",
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
            // Extractor filters by SMC.succession_trained_chara_id_1/_2
            // then walks up to 2 matches. Simpler for plugin: walk
            // all matches (should now be ~2), post-filter to
            // succession IDs in write_capture_to_disk (v0.0.8c).
            pick_by: None,
        });
        resolved += 1;
    }

    if resolved == 0 {
        return Err("no target classes resolved — either the game version is very off or the images aren't loaded".into());
    }
    info!("[uma-it] {}/7 target classes resolved for scanning", resolved);

    // Resolve the eight IL2CPP GC symbols we use for heap scanning.
    // Failure here means Unity < 2021.2 or a stripped IL2CPP build —
    // neither expected for Umamusume Global as of the current build.
    gc_scan::resolve(api)?;
    info!("[uma-it] IL2CPP liveness API resolved (Unity 2021.2+ path)");

    // Resolve field-introspection symbols (Il2Cpp metadata APIs)
    // — used by v0.0.7's field walker to enumerate + read instance
    // fields on matched objects.
    introspect::resolve(api)?;
    info!("[uma-it] IL2CPP metadata API resolved (field enumeration ready)");

    // Register the menu item. Hachimi surfaces this in its in-game
    // menu (F1 by default on PC). The callback fires on the game's
    // GUI thread, which is what we want — GC scans need to run
    // from an IL2CPP-attached thread.
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
    Ok(())
}

/// Menu callback. Fires from Hachimi's GUI thread when the user
/// clicks "Extract IT Run".
///
/// v0.0.8 pipeline: run heap scans (with log-based dump for
/// visibility), then build a JSON capture and write it to disk.
///
/// This is `extern "C"` (not `unsafe extern "C"`) because
/// `GuiMenuCallback` in edge-sdk is defined that way. The scan
/// itself is unsafe, but the callback wrapper isn't.
extern "C" fn on_menu_click(_userdata: *mut c_void) {
    gc_scan::scan_and_log();
    if let Err(msg) = write_capture_to_disk() {
        error!("[uma-it] failed to write capture file: {msg}");
    }
}

/// Extract `succession_trained_chara_id_1` and `_2` from a walked
/// SingleModeChara JsonValue. Returns `[id1, id2]` if both present
/// and non-zero, else None. Used to filter Parents down to the
/// two direct-parent instances.
fn extract_succession_ids(smc: &json::JsonValue) -> Option<[i64; 2]> {
    let json::JsonValue::Object(entries) = smc else { return None; };
    let mut id1: Option<i64> = None;
    let mut id2: Option<i64> = None;
    for (k, v) in entries {
        if k == "succession_trained_chara_id_1" {
            if let json::JsonValue::Int(i) = v {
                id1 = Some(*i);
            }
        } else if k == "succession_trained_chara_id_2" {
            if let json::JsonValue::Int(i) = v {
                id2 = Some(*i);
            }
        }
    }
    match (id1, id2) {
        (Some(a), Some(b)) if a > 0 && b > 0 => Some([a, b]),
        _ => None,
    }
}

/// Re-scan every registered class and build a JSON capture, then
/// write it to `<game>/hachimi/uma_it_capture.json`.
///
/// This is a SECOND set of scans on top of gc_scan::scan_and_log's
/// dumps. Doubles the click-to-file latency but keeps the log
/// dump as a distinct debug artifact — we can drop the log-based
/// dump later once the JSON is confirmed correct across builds.
fn write_capture_to_disk() -> Result<(), String> {
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
    root.push(("plugin_version".into(), JsonValue::string("hachimi-v0.0.8")));

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
                // can filter Parents.
                if target.label == "SingleModeChara" {
                    parent_id_filter = extract_succession_ids(&walked);
                    if let Some(ids) = parent_id_filter {
                        info!("[uma-it] parent-filter IDs from SMC: {} and {}", ids[0], ids[1]);
                    }
                }
                walked
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
    // Timestamped filename in a hachimi\IT\ subfolder so multiple
    // captures don't overwrite each other and are all in one place.
    // Uses UNIX seconds — sorts chronologically; users can rename
    // to match the .exe extractor's YYYYMMDDT...json format if they
    // want.
    let base = base_dir.trim_end_matches(['/', '\\']);
    let dir = format!("{}\\IT", base);
    std::fs::create_dir_all(&dir).map_err(|e| format!("create dir {}: {}", dir, e))?;
    let epoch_secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let path = format!("{}\\uma_it_capture_{}.json", dir, epoch_secs);
    std::fs::write(&path, &json).map_err(|e| format!("write {}: {}", path, e))?;
    info!("[uma-it] wrote capture ({} bytes) to {}", json.len(), path);
    Ok(())
}
