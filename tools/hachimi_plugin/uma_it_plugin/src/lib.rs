//! uma-it Hachimi plugin — v0.0.3 (Phase 1: proof of concept).
//!
//! What this version does:
//! - Loads via Hachimi-Edge's plugin loader (`hachimi_init_v3`)
//! - Eagerly installs the hook in `init()` (Hachimi late-load fires
//!   game_initialized before plugins load, so a callback would miss)
//! - Falls back to registering `on_game_initialized` if the eager
//!   install fails with the game not yet up (early-load path only)
//! - Resolves + hooks
//!   `Gallop.DialogTrainedCharacterDetail::CreateSetupParameter`
//!   (3 args + this on the current Global build; Uma-ISC's older
//!   reference was 5 args — game update dropped 2 params since)
//! - When the hook fires, logs the invocation with the three raw
//!   argument values as hex, then calls the original method via
//!   the trampoline so game behaviour is unchanged.
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
                // install_hook returns Ok both when it actually
                // installed AND when it deliberately skipped (argc
                // mismatch). Distinguish by whether TRAMPOLINE got
                // populated.
                if !TRAMPOLINE.load(Ordering::SeqCst).is_null() {
                    info!("[uma-it] hook installed at init (game already up)");
                } else {
                    // Skipped for safety — don't register the fallback
                    // callback either; it would fail the same way and
                    // spam the log.
                    info!("[uma-it] eager install declined; not registering fallback");
                }
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
    // Uma-ISC's hook was 5 args on an older Global build; v0.0.2a
    // field test discovered current Global has 3 args. Try 3 first
    // (fast path on the known-current build), fall back to nearby
    // counts so a future game update doesn't silently disable us —
    // we'll refuse to install if the discovered count doesn't match
    // our hook signature (see EXPECTED_ARGC check below).
    let mut method_addr: *mut c_void = std::ptr::null_mut();
    let mut hit_argc: i32 = -1;
    for argc in [3, 4, 5, 2, 6, 7, 1, 8] {
        let addr = get_method_addr(class as *mut _, method_name.as_ptr(), argc);
        if !addr.is_null() {
            method_addr = addr;
            hit_argc = argc;
            break;
        }
    }
    if method_addr.is_null() {
        return Err(
            "CreateSetupParameter not found at any arg count 1..8 — method \
             renamed? Report the log so we can dnSpy the current signature."
                .into(),
        );
    }
    info!(
        "[uma-it] target method resolved at {:p} (argc={})",
        method_addr, hit_argc
    );

    // Our hook_create_setup_parameter function has a hardcoded 3-arg
    // signature (this + 3 opaque params). If the actual method takes
    // a different arg count, installing the hook would corrupt the
    // stack when the game calls it and crash. Only install when the
    // counts match; otherwise log the mismatch loudly so we know to
    // rebuild with the right signature in the next version.
    const EXPECTED_ARGC: i32 = 3;
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
/// Signature: this + 3 opaque args. Current Global build resolves
/// with argc=3 (see install_hook), but we don't yet know which of
/// the three is `TrainedCharaData` vs bool/string/delegate. Using
/// `usize` for all three because on x64 Windows ABI all four params
/// go in registers (RCX/RDX/R8/R9) and every candidate type
/// (pointer, bool, int) fits in a register — so opaque
/// pass-through can never corrupt the stack regardless of which
/// arg is what.
///
/// Return type is void per Uma-ISC's older-build reference. If the
/// current build returns something, MinHook's trampoline will still
/// pass it through untouched — we just don't observe it.
///
/// Phase 1 body just logs the raw arg values. Once we identify
/// which arg is `TrainedCharaData`, v0.0.4+ walks it and serializes.
unsafe extern "C" fn hook_create_setup_parameter(
    this: *mut c_void,
    arg1: usize,
    arg2: usize,
    arg3: usize,
) {
    info!(
        "[uma-it] CreateSetupParameter fired: this={:p} arg1={:#x} arg2={:#x} arg3={:#x}",
        this, arg1, arg2, arg3
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
    let orig: unsafe extern "C" fn(*mut c_void, usize, usize, usize) =
        std::mem::transmute(tramp);
    orig(this, arg1, arg2, arg3);
}
