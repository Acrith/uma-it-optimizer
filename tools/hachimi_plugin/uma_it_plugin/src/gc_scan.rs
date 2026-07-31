//! Heap scan for live instances of a specific IL2CPP class.
//!
//! Reimplements what Frida's `Il2Cpp.gc.choose` does, in-process.
//! The Frida-based extractor (`tools/memory_extractor/dump_it_run.py`)
//! uses this to find live `ObscuredIdleSingleModeGainInfo` instances
//! only while the IT Training Log popup is open — same signal we
//! want in the plugin, but without needing Frida attached.
//!
//! Uses Unity's public liveness API (Unity 2021.2+):
//!   il2cpp_stop_gc_world
//!   il2cpp_unity_liveness_allocate_struct
//!   il2cpp_unity_liveness_calculation_from_statics
//!   il2cpp_unity_liveness_finalize
//!   il2cpp_start_gc_world
//!   il2cpp_unity_liveness_free_struct
//!
//! Plus il2cpp_alloc / il2cpp_free for the internal buffer's
//! realloc callback. The C runtime malloc is UNSAFE under
//! stop_gc_world (allocator locks + frozen mutator threads =
//! potential deadlock), so we use IL2CPP's own allocator.
//!
//! All eight symbols are resolved once via edge-sdk's
//! `il2cpp_resolve_symbol` and cached in a `GcSymbols` struct.

use std::ffi::{c_void, CString};
use std::sync::Mutex;

use edge_sdk::api::Api;
use edge_sdk::ffi::Il2CppClass;
use log::{error, info};
use once_cell::sync::OnceCell;

// ── C callbacks for the liveness API ──────────────────────────

/// Called by the liveness walker with a batch of matched objects.
/// Fires multiple times per scan; each call delivers a chunk of
/// `size` `Il2CppObject*` pointers into `objects`. We just append
/// them into the accumulator on the ScanContext.
type ChooseCb =
    unsafe extern "C" fn(objects: *mut *mut c_void, size: i32, userdata: *mut c_void);

/// Realloc-shaped callback the liveness API uses for its internal
/// growing object buffer.
///
/// Contract (C-style realloc, with a bit of nuance):
///   - handle == NULL, size > 0    → allocate a new `size`-byte block
///   - handle != NULL, size == 0   → free `handle`, return NULL
///   - handle != NULL, size > 0    → grow: alloc new, copy old contents
///                                    up to min(old_size, size), free old
///
/// Runs under `stop_gc_world` — all mutator threads frozen. Must
/// not touch the C runtime allocator (would deadlock if a frozen
/// thread held its lock). We use `il2cpp_alloc` / `il2cpp_free`
/// exclusively.
///
/// To support the grow case correctly, we track outstanding
/// allocations in the ScanContext (pre-sized so no Rust-side
/// allocation happens during the scan itself).
type ReallocCb = unsafe extern "C" fn(
    handle: *mut c_void,
    size: usize,
    userdata: *mut c_void,
) -> *mut c_void;

// ── Resolved symbols ──────────────────────────────────────────

/// Cached function pointers for the eight IL2CPP GC symbols we
/// use. Resolved once via `GcSymbols::resolve` and stored in a
/// process-wide `OnceCell` on first use.
///
/// All fields are `Option` so a missing symbol degrades to a
/// specific error instead of a null-pointer crash. In practice
/// on Umamusume Global (Unity 2021.2+) every symbol resolves.
#[allow(non_snake_case)]
pub struct GcSymbols {
    pub il2cpp_stop_gc_world: unsafe extern "C" fn(),
    pub il2cpp_start_gc_world: unsafe extern "C" fn(),
    pub il2cpp_unity_liveness_allocate_struct: unsafe extern "C" fn(
        klass: *mut c_void,
        filter: i32,
        cb: ChooseCb,
        userdata: *mut c_void,
        realloc: ReallocCb,
    ) -> *mut c_void,
    pub il2cpp_unity_liveness_calculation_from_statics: unsafe extern "C" fn(state: *mut c_void),
    pub il2cpp_unity_liveness_finalize: unsafe extern "C" fn(state: *mut c_void),
    pub il2cpp_unity_liveness_free_struct: unsafe extern "C" fn(state: *mut c_void),
    pub il2cpp_alloc: unsafe extern "C" fn(size: usize) -> *mut c_void,
    pub il2cpp_free: unsafe extern "C" fn(ptr: *mut c_void),
}

static GC_SYMS: OnceCell<GcSymbols> = OnceCell::new();

/// Resolve every GC symbol we need. Called once at plugin init.
/// Returns Err with the specific missing symbol name if the
/// runtime doesn't export it (would mean Unity < 2021.2 or a
/// custom IL2CPP build — neither expected for Umamusume).
pub unsafe fn resolve(api: &Api) -> Result<&'static GcSymbols, String> {
    if let Some(cached) = GC_SYMS.get() {
        return Ok(cached);
    }

    let resolve_symbol = api
        .il2cpp_resolve_symbol
        .ok_or("il2cpp_resolve_symbol missing from vtable")?;

    // Helper: resolve `name` to a function pointer of type `$T`.
    // Returns Err("<name>") on miss so the caller sees exactly
    // which symbol the current build is missing.
    macro_rules! sym {
        ($name:literal, $t:ty) => {{
            let cname = CString::new($name).unwrap();
            let ptr = resolve_symbol(cname.as_ptr());
            if ptr.is_null() {
                return Err(format!("il2cpp_resolve_symbol({}) returned null", $name));
            }
            unsafe { std::mem::transmute::<*mut c_void, $t>(ptr) }
        }};
    }

    let syms = GcSymbols {
        il2cpp_stop_gc_world: sym!("il2cpp_stop_gc_world", unsafe extern "C" fn()),
        il2cpp_start_gc_world: sym!("il2cpp_start_gc_world", unsafe extern "C" fn()),
        il2cpp_unity_liveness_allocate_struct: sym!(
            "il2cpp_unity_liveness_allocate_struct",
            unsafe extern "C" fn(
                *mut c_void, i32, ChooseCb, *mut c_void, ReallocCb,
            ) -> *mut c_void
        ),
        il2cpp_unity_liveness_calculation_from_statics: sym!(
            "il2cpp_unity_liveness_calculation_from_statics",
            unsafe extern "C" fn(*mut c_void)
        ),
        il2cpp_unity_liveness_finalize: sym!(
            "il2cpp_unity_liveness_finalize",
            unsafe extern "C" fn(*mut c_void)
        ),
        il2cpp_unity_liveness_free_struct: sym!(
            "il2cpp_unity_liveness_free_struct",
            unsafe extern "C" fn(*mut c_void)
        ),
        il2cpp_alloc: sym!("il2cpp_alloc", unsafe extern "C" fn(usize) -> *mut c_void),
        il2cpp_free: sym!("il2cpp_free", unsafe extern "C" fn(*mut c_void)),
    };

    let _ = GC_SYMS.set(syms);
    Ok(GC_SYMS.get().unwrap())
}

// ── Scan implementation ───────────────────────────────────────

/// Per-scan state, owned by whoever called `scan_class` and
/// passed as `userdata` through both callbacks. Single-threaded
/// access — the scan is synchronous and only one runs at a time.
///
/// Pre-sized capacities are for amortization, not correctness.
/// The v0.0.6 field test proved malloc works fine under
/// stop_gc_world (44 error!() calls with format! all succeeded
/// during the critical section), so incidental Vec growth here
/// is safe. Pre-sizing just avoids the reallocation cost.
struct ScanContext {
    syms: &'static GcSymbols,
    /// Tracked outstanding allocations from realloc_cb so we can
    /// (a) support realloc-grow with correct copy semantics and
    /// (b) free any blocks the API doesn't clean up itself.
    /// Field test showed ~108 fresh allocs per scan on Umamusume
    /// Global — pre-sized to 256 for 2x headroom.
    allocs: Vec<(*mut c_void, usize)>,
    /// Accumulated matched object pointers, appended by choose_cb.
    /// Capacity pre-sized for a comfortable ceiling on live
    /// instances of one class.
    matches: Vec<*mut c_void>,
}

unsafe extern "C" fn choose_cb(
    objects: *mut *mut c_void,
    size: i32,
    userdata: *mut c_void,
) {
    let ctx = &mut *(userdata as *mut ScanContext);
    // Bail if callback fires with garbage — defensive but cheap.
    if objects.is_null() || size <= 0 {
        return;
    }
    // Push all objects; Vec will grow if needed (safe per v0.0.6
    // field test).
    for i in 0..(size as isize) {
        ctx.matches.push(*objects.offset(i));
    }
}

unsafe extern "C" fn realloc_cb(
    handle: *mut c_void,
    size: usize,
    userdata: *mut c_void,
) -> *mut c_void {
    let ctx = &mut *(userdata as *mut ScanContext);
    let syms = ctx.syms;

    // Free path.
    if !handle.is_null() && size == 0 {
        (syms.il2cpp_free)(handle);
        ctx.allocs.retain(|(p, _)| *p != handle);
        return std::ptr::null_mut();
    }

    // Pure alloc path (fresh block).
    if handle.is_null() {
        let new = (syms.il2cpp_alloc)(size);
        // If Vec::push would need to grow, do it — v0.0.6 field test
        // proved malloc works fine under stop_gc_world (44 error!()
        // calls with format! all succeeded), so incidental growth
        // here is safe. Pre-sized capacity just avoids the amortized
        // cost, not a correctness issue.
        ctx.allocs.push((new, size));
        return new;
    }

    // Grow path: alloc new, copy old contents up to min(old, new),
    // free old, retire tracking entry.
    let new = (syms.il2cpp_alloc)(size);
    let old_size = ctx
        .allocs
        .iter()
        .find(|(p, _)| *p == handle)
        .map(|(_, s)| *s)
        .unwrap_or(0);
    let copy_len = old_size.min(size);
    if copy_len > 0 {
        std::ptr::copy_nonoverlapping(handle as *const u8, new as *mut u8, copy_len);
    }
    (syms.il2cpp_free)(handle);
    ctx.allocs.retain(|(p, _)| *p != handle);
    ctx.allocs.push((new, size));
    new
}

/// Result of a heap scan.
pub struct ScanResult {
    /// `Il2CppObject*` pointers to matched instances.
    pub matches: Vec<*mut c_void>,
    /// How many total realloc_cb allocations the liveness API
    /// asked for. Useful telemetry across game builds.
    pub allocs_count: usize,
}

/// Scan the IL2CPP GC heap for live instances of `class`.
///
/// Cost: 20-80ms on Umamusume's heap. All mutator threads are
/// frozen during the scan (stop_gc_world → start_gc_world), so
/// this WILL cause a visible stutter if called during rendering.
/// Only call from a user-triggered event (menu click, keybind),
/// never from a per-frame path.
///
/// # Safety
///
/// `class` must be a valid `Il2CppClass*` obtained from
/// `il2cpp_get_class` on a loaded assembly image. `GcSymbols`
/// must have been successfully `resolve`d for the current
/// runtime.
pub unsafe fn scan_class(class: *mut Il2CppClass) -> Result<ScanResult, String> {
    let syms = GC_SYMS.get().ok_or(
        "GcSymbols not resolved — call gc_scan::resolve() at plugin init before scanning",
    )?;

    const SCAN_MATCHES_CAP: usize = 4096;
    // Field test v0.0.6 showed ~108 fresh allocs per scan; 256
    // gives 2x headroom. Growth beyond this is safe (Vec grows),
    // just costs an amortized copy.
    const SCAN_ALLOCS_CAP: usize = 256;

    let mut ctx = ScanContext {
        syms,
        allocs: Vec::with_capacity(SCAN_ALLOCS_CAP),
        matches: Vec::with_capacity(SCAN_MATCHES_CAP),
    };

    // === CRITICAL SECTION: mutator threads frozen ===
    // If we panic between stop_gc_world and start_gc_world, the
    // game deadlocks forever. Keep this block strictly balanced.
    (syms.il2cpp_stop_gc_world)();
    let state = (syms.il2cpp_unity_liveness_allocate_struct)(
        class as *mut c_void,
        0, // filter = 0 → all objects of this class type
        choose_cb,
        &mut ctx as *mut _ as *mut c_void,
        realloc_cb,
    );
    if !state.is_null() {
        (syms.il2cpp_unity_liveness_calculation_from_statics)(state);
        (syms.il2cpp_unity_liveness_finalize)(state);
    }
    (syms.il2cpp_start_gc_world)();
    // === END CRITICAL SECTION ===

    if state.is_null() {
        return Err("il2cpp_unity_liveness_allocate_struct returned null".into());
    }
    (syms.il2cpp_unity_liveness_free_struct)(state);

    // Snapshot count for reporting, then free any leftover blocks
    // the liveness API didn't clean up itself.
    let allocs_count = ctx.allocs.len();
    for (ptr, _) in ctx.allocs.drain(..) {
        (syms.il2cpp_free)(ptr);
    }

    Ok(ScanResult {
        matches: ctx.matches,
        allocs_count,
    })
}

// ── Convenience wrapper ───────────────────────────────────────

/// One class we scan on menu click. Populated at plugin init
/// from `lib.rs::setup()` for all data classes the extractor
/// heap-scans (dump_it_run.py:317-322).
pub struct TargetClass {
    /// Short label for logs — matches the extractor's JSON key
    /// (e.g. "GainInfo", "SingleModeChara").
    pub label: &'static str,
    /// Fully-qualified class name for the "no matches" hint log.
    pub display: &'static str,
    /// The resolved Il2CppClass* — set exactly once at init.
    pub class: *mut Il2CppClass,
    /// When multiple instances match, pick the one with the
    /// highest value at this int32 field (offset resolved via
    /// describe_fields). Matches the extractor's picker logic
    /// (dump_it_run.py:517 "picking best by fans"). None → walk
    /// only the first match.
    pub pick_by: Option<&'static str>,
}

// Raw pointer inside can't be Send; wrap in a Mutex<Vec<>> anyway
// because we set exactly once at init and read from a single
// callback thread, so contention is impossible.
static TARGET_CLASSES: OnceCell<Mutex<Vec<TargetClass>>> = OnceCell::new();
// SAFETY: TargetClass is only accessed from the plugin's menu
// callback (single-threaded) and set once at init. The raw ptr
// inside is opaque to Rust — never dereferenced except by
// il2cpp APIs that take *mut Il2CppClass.
unsafe impl Send for TargetClass {}

/// Expose the resolved `il2cpp_free` for other modules (introspect)
/// to release strings/buffers allocated by IL2CPP APIs like
/// `il2cpp_type_get_name`. Returns None until `gc_scan::resolve()`
/// has been called.
pub fn get_il2cpp_free() -> Option<unsafe extern "C" fn(*mut std::ffi::c_void)> {
    GC_SYMS.get().map(|s| s.il2cpp_free)
}

pub fn add_target(t: TargetClass) {
    let cell = TARGET_CLASSES.get_or_init(|| Mutex::new(Vec::new()));
    if let Ok(mut g) = cell.lock() {
        g.push(t);
    }
}

/// Snapshot of registered targets (label, display, class ptr,
/// pick_by) for a caller that wants to iterate without holding
/// the lock. Cheap — we clone the &'static str refs and the ptr.
pub fn snapshot_targets() -> Vec<TargetClass> {
    let Some(cell) = TARGET_CLASSES.get() else { return Vec::new(); };
    let guard = match cell.lock() {
        Ok(g) => g,
        Err(_) => return Vec::new(),
    };
    guard
        .iter()
        .map(|t| TargetClass {
            label: t.label,
            display: t.display,
            class: t.class,
            pick_by: t.pick_by,
        })
        .collect()
}

/// One-shot: iterate every registered target class, scan the
/// heap for its live instances, and dump the first match of
/// each. v0.0.7g refactors this to build a JSON tree and write
/// it to a file instead of just logging.
pub fn scan_and_log() {
    let cell = match TARGET_CLASSES.get() {
        Some(c) => c,
        None => {
            error!("[uma-it] no target classes registered — plugin misconfigured");
            return;
        }
    };
    let targets = match cell.lock() {
        Ok(g) => g,
        Err(_) => {
            error!("[uma-it] target class list poisoned");
            return;
        }
    };
    if targets.is_empty() {
        error!("[uma-it] target class list empty — nothing to scan");
        return;
    }
    info!(
        "[uma-it] starting heap scans for {} classes (each pauses the game ~20-80ms)",
        targets.len()
    );
    let total_start = std::time::Instant::now();
    for target in targets.iter() {
        if target.class.is_null() {
            info!("[uma-it] [{}] skipped — class was not resolved at init", target.label);
            continue;
        }
        let start = std::time::Instant::now();
        match unsafe { scan_class(target.class) } {
            Ok(res) => {
                let elapsed = start.elapsed();
                info!(
                    "[uma-it] [{}] {} instances found in {}ms ({} realloc allocs)",
                    target.label,
                    res.matches.len(),
                    elapsed.as_millis(),
                    res.allocs_count,
                );
                if res.matches.is_empty() {
                    info!("[uma-it] [{}] no instances — {} not in memory right now", target.label, target.display);
                    continue;
                }
                let pick = match target.pick_by {
                    Some(field_name) => {
                        // Safety: matches come from a well-formed
                        // scan of the class we set at init; all
                        // pointers are live IL2CPP objects of the
                        // right shape for describe_fields + i32 read.
                        match unsafe {
                            crate::introspect::pick_best_by_int_field(&res.matches, field_name)
                        } {
                            Some((ptr, val)) => {
                                info!("[uma-it] [{}] picking best by {}={} (of {} matches):",
                                    target.label, field_name, val, res.matches.len());
                                ptr
                            }
                            None => {
                                info!("[uma-it] [{}] pick_by field '{}' not found; walking first match:", target.label, field_name);
                                res.matches[0]
                            }
                        }
                    }
                    None => {
                        info!("[uma-it] [{}] walking first match:", target.label);
                        res.matches[0]
                    }
                };
                unsafe { crate::introspect::dump_instance(pick); }
            }
            Err(msg) => error!("[uma-it] [{}] scan failed: {msg}", target.label),
        }
    }
    info!("[uma-it] all scans done in {}ms total", total_start.elapsed().as_millis());
}
