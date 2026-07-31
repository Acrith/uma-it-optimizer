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

    // Locate the umamusume assembly image + our target class.
    let umamusume = CString::new("umamusume").unwrap();
    let get_image = api
        .il2cpp_get_assembly_image
        .ok_or("il2cpp_get_assembly_image missing from vtable")?;
    let image = get_image(umamusume.as_ptr());
    if image.is_null() {
        return Err("umamusume assembly image not loaded — game not fully up?".into());
    }
    let ns = CString::new("Gallop").unwrap();
    let cls_name = CString::new("ObscuredIdleSingleModeGainInfo").unwrap();
    let get_class = api
        .il2cpp_get_class
        .ok_or("il2cpp_get_class missing from vtable")?;
    let class = get_class(image, ns.as_ptr(), cls_name.as_ptr());
    if class.is_null() {
        return Err(
            "Gallop.ObscuredIdleSingleModeGainInfo class not found — game update?".into(),
        );
    }
    info!("[uma-it] target class resolved: Gallop.ObscuredIdleSingleModeGainInfo @ {:p}", class);
    gc_scan::set_target_class(class);

    // Resolve the eight IL2CPP GC symbols we use for heap scanning.
    // Failure here means Unity < 2021.2 or a stripped IL2CPP build —
    // neither expected for Umamusume Global as of the current build.
    gc_scan::resolve(api)?;
    info!("[uma-it] IL2CPP liveness API resolved (Unity 2021.2+ path)");

    // Resolve field-introspection symbols (Il2Cpp metadata APIs)
    // — used by v0.0.7's field walker to enumerate + read instance
    // fields on matched GainInfo objects.
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
/// clicks "Extract IT Run". Runs a heap scan and logs the count.
/// v0.0.7 will walk fields on each match and serialize; v0.0.8
/// POSTs the run to /api/runs.
///
/// This is `extern "C"` (not `unsafe extern "C"`) because
/// `GuiMenuCallback` in edge-sdk is defined that way. The scan
/// itself is unsafe, but the callback wrapper isn't.
extern "C" fn on_menu_click(_userdata: *mut c_void) {
    gc_scan::scan_and_log();
}
