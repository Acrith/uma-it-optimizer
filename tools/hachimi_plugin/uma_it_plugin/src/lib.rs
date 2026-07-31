//! uma-it Hachimi plugin — v0.0.4 (Phase 1: proof of concept).
//!
//! What this version does:
//! - Loads via Hachimi-Edge's plugin loader (`hachimi_init_v3`)
//! - Eagerly installs the hook in `init()` (Hachimi late-load fires
//!   game_initialized before plugins load, so a callback would miss)
//! - Falls back to registering `on_game_initialized` if the eager
//!   install fails with the game not yet up (early-load path only)
//! - Resolves + hooks `Gallop.ObscuredIdleSingleModeGainInfo::.ctor`
//!   — the IT-specific data holder. The Frida extractor already
//!   proves this class is the right signal: it heap-scans for live
//!   instances, walks them, and dumps the run. edge-sdk doesn't
//!   expose heap enumeration, so we catch the instances at
//!   construction time instead — same signal, different trigger.
//! - When the hook fires, logs `this` and returns. Phase 2 will
//!   walk the fields (fans, stats, support cards, factors, races)
//!   and POST to the API.
//!
//! Prior versions (v0.0.1..v0.0.3) targeted
//! `Gallop.DialogTrainedCharacterDetail::CreateSetupParameter` on
//! the assumption Uma-ISC's older-build reference matched our
//! screen. Field test showed the hook installed but never fired on
//! Training Log open — that dialog is the Trained Umas inheritance
//! viewer, not the IT log we care about.
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

/// Resolve `Gallop.ObscuredIdleSingleModeGainInfo::.ctor` in the
/// loaded `umamusume` assembly and install our hook. Bails out
/// with a diagnostic string on any resolution failure — makes
/// game-version drift show up as a specific log line rather than
/// a silent no-op.
///
/// Why this class: the Frida extractor
/// (`tools/memory_extractor/dump_it_run.py:255`) proves
/// `ObscuredIdleSingleModeGainInfo` only exists in memory while
/// the IT Training Log dialog is open. Catching its constructor
/// gives us the same trigger without needing heap enumeration
/// (which edge-sdk doesn't expose).
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

    let method_name = CString::new(".ctor").unwrap();
    let get_method_addr = api
        .il2cpp_get_method_addr
        .ok_or("il2cpp_get_method_addr missing from vtable")?;
    // Default C# constructor is argc=0 (just `this`). Some classes
    // have overloaded ctors; try 0 first (fast path) then 1..4 so
    // we still find *a* ctor if the class was refactored. The
    // EXPECTED_ARGC check below refuses to install on mismatch.
    let mut method_addr: *mut c_void = std::ptr::null_mut();
    let mut hit_argc: i32 = -1;
    for argc in [0, 1, 2, 3, 4] {
        let addr = get_method_addr(class as *mut _, method_name.as_ptr(), argc);
        if !addr.is_null() {
            method_addr = addr;
            hit_argc = argc;
            break;
        }
    }
    if method_addr.is_null() {
        return Err(
            ".ctor not found at any arg count 0..4 on \
             ObscuredIdleSingleModeGainInfo — class refactored? Report \
             the log so we can dnSpy the current shape."
                .into(),
        );
    }
    info!(
        "[uma-it] target method resolved at {:p} (argc={})",
        method_addr, hit_argc
    );

    // Our hook function has a hardcoded 0-arg signature (just this).
    // If the resolved ctor takes params, calling the trampoline with
    // our signature would corrupt the stack. Refuse the install
    // (log loudly) so a future game version doesn't silently crash.
    const EXPECTED_ARGC: i32 = 0;
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
        hook_gain_info_ctor as *mut c_void,
    );
    if trampoline.is_null() {
        return Err("interceptor_hook returned null — hook install failed".into());
    }
    TRAMPOLINE.store(trampoline, Ordering::SeqCst);
    info!("[uma-it] hook installed; trampoline at {:p}", trampoline);
    Ok(())
}

/// Our replacement for `ObscuredIdleSingleModeGainInfo::.ctor`.
/// Runs FIRST when the game constructs a new instance, then we
/// invoke the original ctor via the stored trampoline so the
/// object is properly initialized before anything else touches it.
///
/// Signature: just `this` (default 0-arg C# ctor). `this` at ctor
/// entry points at freshly-allocated but uninitialized memory;
/// the fields are populated by the original ctor body we call
/// next. Phase 2 walks those fields *after* the trampoline
/// returns (post-init), not from the hook body directly.
///
/// For Phase 1 we just log that the ctor fired so we can confirm
/// the trigger works on Training Log open. Phase 2+ moves the
/// walk-and-POST logic in here.
unsafe extern "C" fn hook_gain_info_ctor(this: *mut c_void) {
    // Call the original ctor first so `this` is fully initialized
    // before we peek at anything. If TRAMPOLINE is somehow null
    // (shouldn't happen post-install), we skip the call — the game
    // will end up with an uninitialized object, but at least won't
    // crash immediately from a signature mismatch.
    let tramp = TRAMPOLINE.load(Ordering::SeqCst);
    if !tramp.is_null() {
        let orig: unsafe extern "C" fn(*mut c_void) = std::mem::transmute(tramp);
        orig(this);
    } else {
        error!("[uma-it] trampoline null — GainInfo may be uninitialized");
    }
    info!(
        "[uma-it] ObscuredIdleSingleModeGainInfo::.ctor fired: this={:p}",
        this
    );
}
