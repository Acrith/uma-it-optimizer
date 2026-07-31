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
use std::sync::atomic::{AtomicPtr, Ordering};

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
/// Pre-sized capacities avoid any Rust-side heap allocation
/// during the critical section (between stop_gc_world and
/// start_gc_world) — allocating there would risk the same
/// deadlock the C-runtime allocator warning is about.
struct ScanContext {
    syms: &'static GcSymbols,
    /// Tracked outstanding allocations from realloc_cb, needed
    /// so realloc-grow can copy old contents to the new block.
    /// Capacity pre-sized generously — the liveness API's
    /// internal buffer typically resizes <10 times per scan.
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
    for i in 0..(size as isize) {
        let obj = *objects.offset(i);
        // If matches would need to grow (allocate), warn and drop
        // the excess rather than deadlock. This shouldn't happen
        // with our generous initial capacity but is defensive.
        if ctx.matches.len() == ctx.matches.capacity() {
            error!(
                "[uma-it] scan matches vec at capacity ({}); dropping excess. \
                 Bump SCAN_MATCHES_CAP if this fires.",
                ctx.matches.capacity()
            );
            return;
        }
        ctx.matches.push(obj);
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
        if ctx.allocs.len() < ctx.allocs.capacity() {
            ctx.allocs.push((new, size));
        } else {
            // Overflow — we can still return the ptr but won't be
            // able to track it for a future grow. Log and hope
            // the API doesn't grow this specific block.
            error!(
                "[uma-it] scan allocs vec at capacity ({}); \
                 tracking dropped for this block",
                ctx.allocs.capacity()
            );
        }
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
    if ctx.allocs.len() < ctx.allocs.capacity() {
        ctx.allocs.push((new, size));
    }
    new
}

/// Scan the IL2CPP GC heap for live instances of `class`.
/// Returns a Vec of `Il2CppObject*` pointers to matched instances.
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
pub unsafe fn scan_class(class: *mut Il2CppClass) -> Result<Vec<*mut c_void>, String> {
    let syms = GC_SYMS.get().ok_or(
        "GcSymbols not resolved — call gc_scan::resolve() at plugin init before scanning",
    )?;

    const SCAN_MATCHES_CAP: usize = 4096;
    const SCAN_ALLOCS_CAP: usize = 64;

    let mut ctx = ScanContext {
        syms,
        allocs: Vec::with_capacity(SCAN_ALLOCS_CAP),
        matches: Vec::with_capacity(SCAN_MATCHES_CAP),
    };

    // === CRITICAL SECTION: mutator threads frozen ===
    // If we panic between stop_gc_world and start_gc_world, the
    // game deadlocks forever. No fallible code, no allocations,
    // no logging inside this block.
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

    // Free the liveness state outside the critical section — it
    // may internally call the C allocator which is safe now.
    (syms.il2cpp_unity_liveness_free_struct)(state);

    // Any allocs still tracked at this point weren't freed by the
    // API — free them ourselves so we don't leak IL2CPP heap.
    for (ptr, _) in ctx.allocs.drain(..) {
        (syms.il2cpp_free)(ptr);
    }

    Ok(ctx.matches)
}

// ── Convenience wrapper ───────────────────────────────────────

/// Global cache of the target class pointer, populated once at
/// plugin init. Reads on scan are lock-free via AtomicPtr.
static TARGET_CLASS: AtomicPtr<Il2CppClass> = AtomicPtr::new(std::ptr::null_mut());

pub fn set_target_class(class: *mut Il2CppClass) {
    TARGET_CLASS.store(class, Ordering::SeqCst);
}

pub fn get_target_class() -> *mut Il2CppClass {
    TARGET_CLASS.load(Ordering::SeqCst)
}

/// One-shot: run a scan for the previously-set target class and
/// log the match count. Used by the menu-item callback in
/// `lib.rs` — kept here so the whole scan lifecycle lives in one
/// module.
pub fn scan_and_log() {
    let class = get_target_class();
    if class.is_null() {
        error!("[uma-it] scan requested but target class not set — plugin misconfigured");
        return;
    }
    info!("[uma-it] starting heap scan for GainInfo instances (this pauses the game ~20-80ms)");
    let start = std::time::Instant::now();
    match unsafe { scan_class(class) } {
        Ok(matches) => {
            let elapsed = start.elapsed();
            info!(
                "[uma-it] scan complete: {} GainInfo instances found in {}ms",
                matches.len(),
                elapsed.as_millis()
            );
            if matches.is_empty() {
                info!(
                    "[uma-it] no instances — is the Training Log popup open? \
                     GainInfo only exists in memory while that dialog is visible."
                );
            }
        }
        Err(msg) => error!("[uma-it] scan failed: {msg}"),
    }
}
