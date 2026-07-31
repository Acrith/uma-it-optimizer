//! uma-it Hachimi plugin — v0.0.5 (Phase 1: safe no-op fallback).
//!
//! What this version does:
//! - Loads via Hachimi-Edge's plugin loader (`hachimi_init_v3`)
//! - Attempts to hook `Gallop.ObscuredIdleSingleModeGainInfo::.ctor`
//! - BEFORE installing, verifies the resolved `.ctor` is DECLARED
//!   on the target class, not inherited from `System.Object`.
//!   `il2cpp_get_method` walks the inheritance chain; if the class
//!   doesn't declare its own default ctor, we pick up Object's,
//!   which fires on every C# allocation in the game (~6.5k/sec in
//!   v0.0.4 field test → 500k log lines/minute, 5fps game).
//! - If the ctor is inherited: refuse to install, log the reason,
//!   plugin becomes a safe no-op. No game-perf impact.
//! - If the ctor is declared on the class (unlikely for a POCO
//!   like GainInfo, but possible): install the hook and rate-limit
//!   the fire log to the first 3 hits so we never spam even if
//!   the class turns out to be constructed often.
//!
//! Phase 1 is done as soon as the "declared on class" check
//! answers cleanly (which it will for at least ONE class we
//! target eventually). Phase 2 walks fields + POSTs to /api/runs.
//!
//! Prior versions:
//! - v0.0.1..v0.0.3: hooked DialogTrainedCharacterDetail::CreateSetupParameter
//!   (Uma-ISC's older-build reference) — installed cleanly but
//!   fired on the wrong dialog (Trained Umas viewer, not IT log)
//! - v0.0.4: hooked GainInfo::.ctor with no inheritance check —
//!   trampoline was Object.ctor, hosed the game
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
use std::sync::atomic::{AtomicPtr, AtomicU64, Ordering};

use edge_sdk::api::Api;
use edge_sdk::ffi::{Il2CppClass, MethodInfo};
use log::{error, info};

/// Trampoline for calling the original ctor after our hook body
/// runs. Populated once by `install_hook`; the hook function reads
/// it on every invocation and stays no-op if it's somehow null
/// (which shouldn't happen after install).
static TRAMPOLINE: AtomicPtr<c_void> = AtomicPtr::new(std::ptr::null_mut());

/// Count of hook fires so far. Used to rate-limit the "fired" log
/// line — never spam the log even if the hooked method turns out
/// to be called more often than expected. First `FIRE_LOG_LIMIT`
/// calls log; after that, silence.
static FIRE_COUNT: AtomicU64 = AtomicU64::new(0);
const FIRE_LOG_LIMIT: u64 = 3;

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
    let get_method = api
        .il2cpp_get_method
        .ok_or("il2cpp_get_method missing from vtable")?;
    let get_method_addr = api
        .il2cpp_get_method_addr
        .ok_or("il2cpp_get_method_addr missing from vtable")?;
    // Default C# constructor is argc=0 (just `this`). Some classes
    // have overloaded ctors; try 0 first (fast path) then 1..4 so
    // we still find *a* ctor if the class was refactored. The
    // EXPECTED_ARGC check below refuses to install on mismatch.
    let mut method_info: *const MethodInfo = std::ptr::null();
    let mut method_addr: *mut c_void = std::ptr::null_mut();
    let mut hit_argc: i32 = -1;
    for argc in [0, 1, 2, 3, 4] {
        let mi = get_method(class as *mut _, method_name.as_ptr(), argc);
        if !mi.is_null() {
            let addr = get_method_addr(class as *mut _, method_name.as_ptr(), argc);
            if !addr.is_null() {
                method_info = mi;
                method_addr = addr;
                hit_argc = argc;
                break;
            }
        }
    }
    if method_addr.is_null() || method_info.is_null() {
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

    // === CRITICAL: verify method is declared on the class ===
    //
    // `il2cpp_get_method` walks up the inheritance chain to find
    // methods by name. `ObscuredIdleSingleModeGainInfo` is a POCO
    // that inherits from `System.Object` — if it doesn't declare
    // its own `.ctor(0)`, we get `Object::.ctor` back, which fires
    // on every allocation in the game. v0.0.4 skipped this check
    // and hosed the tester's framerate.
    //
    // Fix: enumerate methods declared ON the class via
    // `il2cpp_class_get_methods` (iterator-style — the returned
    // MethodInfo pointers are ONLY methods declared on this klass,
    // no inheritance). If our resolved MethodInfo isn't in that
    // set, we picked up an inherited one and MUST NOT hook.
    if !method_declared_on_class(api, class, method_info)? {
        error!(
            "[uma-it] .ctor at argc={} is inherited from a base class, \
             NOT declared on ObscuredIdleSingleModeGainInfo. Refusing \
             to install — hooking an inherited default ctor fires on \
             every allocation in the game (hosed framerate in v0.0.4). \
             Plugin will be a safe no-op this session; v0.0.6 will use \
             a different trigger mechanism.",
            hit_argc
        );
        return Ok(());
    }

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

/// Check whether `target` is declared ON `class`, as opposed to
/// inherited from a base class. `il2cpp_class_get_methods` is an
/// iterator that walks ONLY methods declared on this klass — no
/// inheritance — so if `target`'s MethodInfo pointer appears in
/// the iteration, it's declared here; otherwise it's inherited.
///
/// Safety: `target` must have come from `il2cpp_get_method` (or
/// another edge-sdk API returning a live MethodInfo pointer) so
/// pointer comparison is meaningful.
unsafe fn method_declared_on_class(
    api: &Api,
    class: *mut Il2CppClass,
    target: *const MethodInfo,
) -> Result<bool, String> {
    let get_methods = api
        .il2cpp_class_get_methods
        .ok_or("il2cpp_class_get_methods missing from vtable")?;

    // Iterator: pass a null-initialized `*mut *mut c_void`; each
    // call advances it and returns the next MethodInfo, or null
    // when exhausted. Bounded to 4096 iterations as a paranoid
    // runaway-loop backstop (any real class has <1000 methods).
    let mut iter: *mut c_void = std::ptr::null_mut();
    for _ in 0..4096 {
        let mi = get_methods(class, &mut iter as *mut _);
        if mi.is_null() {
            return Ok(false);
        }
        if mi == target {
            return Ok(true);
        }
    }
    Err("il2cpp_class_get_methods exceeded 4096 iterations — API misuse?".into())
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
/// Rate-limited to `FIRE_LOG_LIMIT` log lines per plugin lifetime.
/// Even with the inheritance check in `install_hook`, we never
/// want to trust that a hooked method is called only rarely — one
/// misidentified target would flood the log again. Log the count
/// on the last allowed line so the tester knows to expect silence.
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
        // Only log this once — it should never happen, but if it
        // does on every fire that's another log-flood.
        if FIRE_COUNT.load(Ordering::Relaxed) == 0 {
            error!("[uma-it] trampoline null — GainInfo may be uninitialized");
        }
    }

    let n = FIRE_COUNT.fetch_add(1, Ordering::Relaxed);
    if n < FIRE_LOG_LIMIT {
        if n + 1 == FIRE_LOG_LIMIT {
            info!(
                "[uma-it] ObscuredIdleSingleModeGainInfo::.ctor fired: this={:p} \
                 (log #{}/{} — silencing further fires this session)",
                this,
                n + 1,
                FIRE_LOG_LIMIT
            );
        } else {
            info!(
                "[uma-it] ObscuredIdleSingleModeGainInfo::.ctor fired: this={:p} \
                 (log #{}/{})",
                this,
                n + 1,
                FIRE_LOG_LIMIT
            );
        }
    }
}
