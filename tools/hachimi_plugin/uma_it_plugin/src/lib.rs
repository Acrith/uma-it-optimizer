//! uma-it Hachimi plugin — v0.0.1 (Phase 1: proof of concept).
//!
//! What this version does:
//! - Loads via Hachimi-Edge's plugin loader (`hachimi_init_v3`)
//! - Registers `on_game_initialized` callback
//! - In the callback, resolves + hooks
//!   `Gallop.DialogTrainedCharacterDetail::CreateSetupParameter` (5 args)
//! - When the hook fires, logs the invocation with the `is_single_mode`
//!   / `is_follow` argument values, then calls the original method
//!   via the trampoline so game behaviour is unchanged.
//!
//! What it doesn't do yet (planned for Phase 2+):
//! - Walk `TrainedCharaData` and extract the run's stats/deck/skills
//! - Serialize to JSON matching the Frida extractor's schema
//! - POST to /api/runs
//!
//! This phase is deliberately minimal so testers can confirm the
//! plugin loads and the hook fires against the current Global game
//! build before we invest in the data walk.

use std::ffi::{c_void, CString};
use std::sync::atomic::{AtomicPtr, Ordering};

use edge_sdk::api::Api;
use log::{error, info};

/// Trampoline for calling the original `CreateSetupParameter` after
/// our hook body runs. Populated once by `install_hook`; the hook
/// function reads it on every invocation and stays no-op if it's
/// somehow null (which shouldn't happen after install).
static TRAMPOLINE: AtomicPtr<c_void> = AtomicPtr::new(std::ptr::null_mut());

edge_sdk::declare_plugin! {
    fn init() -> bool {
        info!("[uma-it] plugin loaded");
        // Try installing the hook right now. When Hachimi late-loads
        // (e.g. through LoadLibraryW hook rather than the DXGI proxy),
        // it initialises plugins AFTER IL2CPP hooks are already up —
        // 'game_initialized' has already fired by the time we're
        // instantiated, so the callback would never come. Try eager
        // install; fall back to the callback only if the image isn't
        // loaded yet (which happens on proxy-load paths).
        match unsafe { install_hook() } {
            Ok(()) => {
                info!("[uma-it] hook installed at init (game already up)");
                return true;
            }
            Err(msg) => {
                info!(
                    "[uma-it] eager install skipped ({msg}); registering game_initialized callback"
                );
            }
        }
        let api = Api::get();
        let register = match api.hachimi_register_on_game_initialized {
            Some(f) => f,
            None => {
                error!("[uma-it] hachimi_register_on_game_initialized not in vtable — Hachimi-Edge too old? Need VERSION >= 3");
                return false;
            }
        };
        unsafe { register(Some(on_game_initialized), std::ptr::null_mut()); }
        true
    }
}

/// Fires (if it fires) once Hachimi finishes hooking IL2CPP and the
/// game is done initializing. Only called on the early-load path
/// where our plugin runs BEFORE IL2CPP is ready; the late-load path
/// installs eagerly from `init()` instead.
unsafe extern "C" fn on_game_initialized(_userdata: *mut c_void) {
    info!("[uma-it] game_initialized fired — installing hook");
    if let Err(msg) = install_hook() {
        error!("[uma-it] hook install failed: {msg}");
    }
}

/// Resolve `Gallop.DialogTrainedCharacterDetail::CreateSetupParameter`
/// in the loaded `umamusume` assembly and install our hook. Bails
/// out with a diagnostic string on any resolution failure — makes
/// game-version drift show up as a specific log line rather than a
/// silent no-op.
unsafe fn install_hook() -> Result<(), String> {
    // Idempotent: if the trampoline is already set, a prior install
    // succeeded (probably the eager path did the work and the
    // callback fell through anyway). Skip silently.
    if !TRAMPOLINE.load(Ordering::SeqCst).is_null() {
        return Ok(());
    }

    let api = Api::get();

    let umamusume = CString::new("umamusume").unwrap();
    let get_image = api
        .il2cpp_get_assembly_image
        .ok_or("il2cpp_get_assembly_image missing from vtable")?;
    let image = get_image(umamusume.as_ptr());
    if image.is_null() {
        return Err("umamusume assembly image not loaded — game not fully up?".into());
    }

    let ns = CString::new("Gallop").unwrap();
    let cls_name = CString::new("DialogTrainedCharacterDetail").unwrap();
    let get_class = api
        .il2cpp_get_class
        .ok_or("il2cpp_get_class missing from vtable")?;
    let class = get_class(image, ns.as_ptr(), cls_name.as_ptr());
    if class.is_null() {
        return Err("Gallop.DialogTrainedCharacterDetail class not found — game update?".into());
    }

    let method_name = CString::new("CreateSetupParameter").unwrap();
    let get_method_addr = api
        .il2cpp_get_method_addr
        .ok_or("il2cpp_get_method_addr missing from vtable")?;
    // Uma-ISC's hook was 5 args on an older Global build; v0.0.2 field
    // test showed CreateSetupParameter(5) returns null on the current
    // build. Try common arg counts and log which one hits so we know
    // the ground truth for future refs. Range covers realistic
    // deltas: original 5, ±2 for added/dropped params.
    let mut method_addr: *mut c_void = std::ptr::null_mut();
    let mut hit_argc: i32 = -1;
    for argc in [5, 4, 6, 3, 7, 2, 8] {
        let addr = get_method_addr(class as *mut _, method_name.as_ptr(), argc);
        if !addr.is_null() {
            method_addr = addr;
            hit_argc = argc;
            break;
        }
    }
    if method_addr.is_null() {
        return Err(
            "CreateSetupParameter not found at any arg count 2..8 — method \
             renamed? Report the log so we can dnSpy the current signature."
                .into(),
        );
    }
    info!(
        "[uma-it] target method resolved at {:p} (argc={})",
        method_addr, hit_argc
    );

    // Our hook_create_setup_parameter function has a hardcoded 5-arg
    // signature (this + 5 params matching Uma-ISC's reference).
    // If the actual method takes a different arg count, installing
    // the hook would corrupt the stack when the game calls it and
    // crash. Only install when the counts match; otherwise log the
    // mismatch loudly so we know to rebuild with the right signature
    // in the next version.
    const EXPECTED_ARGC: i32 = 5;
    if hit_argc != EXPECTED_ARGC {
        error!(
            "[uma-it] discovered argc={} but our hook is hardcoded to {}. \
             Skipping install to avoid stack corruption. \
             Rebuild plugin with matching signature and re-release.",
            hit_argc, EXPECTED_ARGC
        );
        // Return Ok so init() doesn't fall through to the fallback
        // callback register — we don't want the hook to be tried
        // again with a bad signature later.
        return Ok(());
    }

    let hachimi_instance = api
        .hachimi_instance
        .ok_or("hachimi_instance missing from vtable")?;
    let get_interceptor = api
        .hachimi_get_interceptor
        .ok_or("hachimi_get_interceptor missing from vtable")?;
    let interceptor_hook = api
        .interceptor_hook
        .ok_or("interceptor_hook missing from vtable")?;

    let hachimi = hachimi_instance();
    let interceptor = get_interceptor(hachimi);
    let trampoline = interceptor_hook(
        interceptor,
        method_addr,
        hook_create_setup_parameter as *mut c_void,
    );
    if trampoline.is_null() {
        return Err("interceptor_hook returned null — hook install failed".into());
    }
    TRAMPOLINE.store(trampoline, Ordering::SeqCst);
    info!("[uma-it] hook installed; trampoline at {:p}", trampoline);
    Ok(())
}

/// Our replacement for `CreateSetupParameter`. Runs FIRST when the
/// game calls the method, then we invoke the original via the
/// stored trampoline so game state stays consistent.
///
/// Signature: this + 5 args (TrainedCharaData ptr, trainer_name ptr,
/// on_change_partner delegate ptr, is_single_mode bool, is_follow
/// bool). Return type is void per Uma-ISC's usage — this is a setup
/// helper that mutates the dialog, not one that returns anything.
///
/// Phase 1 body just logs. Phase 2 will walk `chara_data` and
/// serialize to JSON.
unsafe extern "C" fn hook_create_setup_parameter(
    this: *mut c_void,
    chara_data: *mut c_void,
    trainer_name: *mut c_void,
    on_change_partner: *mut c_void,
    is_single_mode: bool,
    is_follow: bool,
) {
    info!(
        "[uma-it] CreateSetupParameter fired: is_single_mode={} is_follow={} chara_data={:p}",
        is_single_mode, is_follow, chara_data
    );
    // Always call the original after our peek — never break game
    // behaviour. If TRAMPOLINE is somehow null (shouldn't happen
    // post-install), we skip the call and log the miss; the game
    // will render a broken dialog but at least won't crash.
    let tramp = TRAMPOLINE.load(Ordering::SeqCst);
    if tramp.is_null() {
        error!("[uma-it] trampoline null — game dialog may not render");
        return;
    }
    let orig: unsafe extern "C" fn(
        *mut c_void, *mut c_void, *mut c_void, *mut c_void, bool, bool,
    ) = std::mem::transmute(tramp);
    orig(this, chara_data, trainer_name, on_change_partner, is_single_mode, is_follow);
}
