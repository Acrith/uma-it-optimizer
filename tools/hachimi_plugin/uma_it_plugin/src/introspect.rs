//! Walk IL2CPP object fields.
//!
//! What the Frida extractor's `walkDeep` (dump_it_run.py:115) does
//! natively via `v.class.fields.forEach(f => ...)`, we do here by
//! resolving Unity's IL2CPP metadata APIs at plugin load time and
//! calling them directly. No new capabilities in edge-sdk needed —
//! `il2cpp_resolve_symbol` reaches everything.
//!
//! v0.0.7 scope: enumerate fields declared on a class, read
//! primitive values (int/float/bool/etc.), decode obscured ints,
//! log human-readable output. No JSON, no recursion into object
//! refs, no arrays — those land in v0.0.7b / v0.0.8.
//!
//! ObscuredInt decoding matches the extractor's `tryDecodeOI`:
//!     value = hiddenValue XOR currentCryptoKey
//! Both are int32 private fields on `Gallop.ObscuredIdleSingleModeInt`
//! (and its friends). The XOR is deterministic per-instance —
//! same key/value pair every read.

use std::ffi::{c_void, CStr, CString};

use edge_sdk::api::Api;
use edge_sdk::ffi::{
    Il2CppClass, Il2CppString, Il2CppTypeEnum, Il2CppTypeEnum_IL2CPP_TYPE_BOOLEAN,
    Il2CppTypeEnum_IL2CPP_TYPE_CHAR, Il2CppTypeEnum_IL2CPP_TYPE_CLASS,
    Il2CppTypeEnum_IL2CPP_TYPE_GENERICINST, Il2CppTypeEnum_IL2CPP_TYPE_I1,
    Il2CppTypeEnum_IL2CPP_TYPE_I2, Il2CppTypeEnum_IL2CPP_TYPE_I4,
    Il2CppTypeEnum_IL2CPP_TYPE_I8, Il2CppTypeEnum_IL2CPP_TYPE_R4,
    Il2CppTypeEnum_IL2CPP_TYPE_R8, Il2CppTypeEnum_IL2CPP_TYPE_STRING,
    Il2CppTypeEnum_IL2CPP_TYPE_SZARRAY, Il2CppTypeEnum_IL2CPP_TYPE_U1,
    Il2CppTypeEnum_IL2CPP_TYPE_U2, Il2CppTypeEnum_IL2CPP_TYPE_U4,
    Il2CppTypeEnum_IL2CPP_TYPE_U8, Il2CppTypeEnum_IL2CPP_TYPE_VALUETYPE,
};
use log::{error, info};
use once_cell::sync::OnceCell;

use crate::json::JsonValue;

// ── Resolved metadata-inspection symbols ──────────────────────

/// Opaque IL2CPP type pointer (Unity's `Il2CppType`).
type Il2CppTypePtr = *const c_void;

/// Opaque IL2CPP field-info pointer. edge-sdk has a `FieldInfo`
/// type but we use `*const c_void` so we can pass it through
/// APIs that take `void*` iterators without extra transmutes.
type FieldInfoPtr = *const c_void;

#[allow(non_snake_case)]
pub struct MetaSymbols {
    /// Iterator over fields DECLARED on this class (no inheritance).
    /// Pass a mutable `iter: *mut c_void` starting as null; each
    /// call advances it. Returns null when exhausted.
    pub il2cpp_class_get_fields:
        unsafe extern "C" fn(klass: *mut Il2CppClass, iter: *mut *mut c_void) -> FieldInfoPtr,
    pub il2cpp_field_get_name: unsafe extern "C" fn(field: FieldInfoPtr) -> *const i8,
    pub il2cpp_field_get_type: unsafe extern "C" fn(field: FieldInfoPtr) -> Il2CppTypePtr,
    pub il2cpp_field_get_offset: unsafe extern "C" fn(field: FieldInfoPtr) -> i32,
    pub il2cpp_field_get_flags: unsafe extern "C" fn(field: FieldInfoPtr) -> u32,
    pub il2cpp_type_get_type: unsafe extern "C" fn(ty: Il2CppTypePtr) -> Il2CppTypeEnum,
    /// For VALUETYPE / CLASS / SZARRAY types, returns the class of
    /// the value / referenced object / element. For SZARRAY it's
    /// the element class, not the array class itself.
    pub il2cpp_type_get_class_or_element_class:
        unsafe extern "C" fn(ty: Il2CppTypePtr) -> *mut Il2CppClass,
    pub il2cpp_class_get_name: unsafe extern "C" fn(klass: *mut Il2CppClass) -> *const i8,
    pub il2cpp_class_get_namespace: unsafe extern "C" fn(klass: *mut Il2CppClass) -> *const i8,
    /// Size in bytes of an instance of a value-type class (i.e.
    /// the inline size, no Il2CppObject header). `out_align` is
    /// optional (may be null) — we don't care about alignment.
    /// For SZARRAY element striding of struct arrays.
    pub il2cpp_class_value_size:
        unsafe extern "C" fn(klass: *mut Il2CppClass, out_align: *mut u32) -> u32,
    /// True if the class is a value type (struct), false if it's
    /// a reference type (class). Determines SZARRAY element stride:
    /// value type → il2cpp_class_value_size; reference type → 8
    /// (pointer size on x64).
    pub il2cpp_class_is_valuetype: unsafe extern "C" fn(klass: *mut Il2CppClass) -> bool,
    /// Number of classes registered in an image. Used together
    /// with il2cpp_image_get_class to iterate — same approach
    /// Frida's `image.classes` uses (frida-il2cpp-bridge
    /// lib/structs/image.ts).
    pub il2cpp_image_get_class_count: unsafe extern "C" fn(image: *const c_void) -> usize,
    /// Fetches class at index i in the image's class array.
    /// Returns nested classes too (indexed alongside top-level).
    /// Together with class_get_type + type_get_name this is the
    /// most reliable way to find a class by its Frida-style
    /// flattened `type.name`.
    pub il2cpp_image_get_class:
        unsafe extern "C" fn(image: *const c_void, index: usize) -> *mut Il2CppClass,
    /// Returns the Il2CppType* for a class. type_get_name(type)
    /// gives the full flattened name (with nested-class dots).
    pub il2cpp_class_get_type: unsafe extern "C" fn(klass: *mut Il2CppClass) -> Il2CppTypePtr,
    /// Returns a fresh heap-allocated C string with the type's
    /// full flattened name. Caller must `il2cpp_free` it via
    /// the GC symbols API.
    pub il2cpp_type_get_name: unsafe extern "C" fn(ty: Il2CppTypePtr) -> *mut i8,
}

static META_SYMS: OnceCell<MetaSymbols> = OnceCell::new();

pub unsafe fn resolve(api: &Api) -> Result<&'static MetaSymbols, String> {
    if let Some(cached) = META_SYMS.get() {
        return Ok(cached);
    }
    let resolve_symbol = api
        .il2cpp_resolve_symbol
        .ok_or("il2cpp_resolve_symbol missing from vtable")?;
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
    let syms = MetaSymbols {
        il2cpp_class_get_fields: sym!(
            "il2cpp_class_get_fields",
            unsafe extern "C" fn(*mut Il2CppClass, *mut *mut c_void) -> FieldInfoPtr
        ),
        il2cpp_field_get_name: sym!(
            "il2cpp_field_get_name",
            unsafe extern "C" fn(FieldInfoPtr) -> *const i8
        ),
        il2cpp_field_get_type: sym!(
            "il2cpp_field_get_type",
            unsafe extern "C" fn(FieldInfoPtr) -> Il2CppTypePtr
        ),
        il2cpp_field_get_offset: sym!(
            "il2cpp_field_get_offset",
            unsafe extern "C" fn(FieldInfoPtr) -> i32
        ),
        il2cpp_field_get_flags: sym!(
            "il2cpp_field_get_flags",
            unsafe extern "C" fn(FieldInfoPtr) -> u32
        ),
        il2cpp_type_get_type: sym!(
            "il2cpp_type_get_type",
            unsafe extern "C" fn(Il2CppTypePtr) -> Il2CppTypeEnum
        ),
        il2cpp_type_get_class_or_element_class: sym!(
            "il2cpp_type_get_class_or_element_class",
            unsafe extern "C" fn(Il2CppTypePtr) -> *mut Il2CppClass
        ),
        il2cpp_class_get_name: sym!(
            "il2cpp_class_get_name",
            unsafe extern "C" fn(*mut Il2CppClass) -> *const i8
        ),
        il2cpp_class_get_namespace: sym!(
            "il2cpp_class_get_namespace",
            unsafe extern "C" fn(*mut Il2CppClass) -> *const i8
        ),
        il2cpp_class_value_size: sym!(
            "il2cpp_class_value_size",
            unsafe extern "C" fn(*mut Il2CppClass, *mut u32) -> u32
        ),
        il2cpp_class_is_valuetype: sym!(
            "il2cpp_class_is_valuetype",
            unsafe extern "C" fn(*mut Il2CppClass) -> bool
        ),
        il2cpp_image_get_class_count: sym!(
            "il2cpp_image_get_class_count",
            unsafe extern "C" fn(*const c_void) -> usize
        ),
        il2cpp_image_get_class: sym!(
            "il2cpp_image_get_class",
            unsafe extern "C" fn(*const c_void, usize) -> *mut Il2CppClass
        ),
        il2cpp_class_get_type: sym!(
            "il2cpp_class_get_type",
            unsafe extern "C" fn(*mut Il2CppClass) -> Il2CppTypePtr
        ),
        il2cpp_type_get_name: sym!(
            "il2cpp_type_get_name",
            unsafe extern "C" fn(Il2CppTypePtr) -> *mut i8
        ),
    };
    let _ = META_SYMS.set(syms);
    Ok(META_SYMS.get().unwrap())
}

// ── Field-metadata + primitive readers ────────────────────────

/// C# field attribute flags we care about. IL2CPP uses .NET's
/// FieldAttributes enum unchanged. STATIC + LITERAL fields aren't
/// per-instance and would give nonsense at instance+offset.
const FIELD_ATTRIBUTE_STATIC: u32 = 0x0010;
const FIELD_ATTRIBUTE_LITERAL: u32 = 0x0040;

/// A single field's metadata, as we care about for the walk.
/// Ownership: the name is heap-copied from IL2CPP so we're not
/// holding a pointer into freshly-collected metadata.
pub struct Field {
    pub name: String,
    pub type_enum: Il2CppTypeEnum,
    /// Raw type pointer. Kept so we can resolve the underlying
    /// class for VALUETYPE / CLASS / SZARRAY fields via
    /// `il2cpp_type_get_class_or_element_class`.
    pub type_ptr: Il2CppTypePtr,
    /// Offset in bytes from the object pointer (including the
    /// 16-byte Il2CppObject header for reference types on x64).
    /// For fields on a value-type class, this is offset from the
    /// value data (no header).
    pub offset: i32,
}

/// Enumerate instance fields declared on `class`. Skips static
/// and literal fields (they aren't at any object+offset).
pub unsafe fn describe_fields(class: *mut Il2CppClass) -> Result<Vec<Field>, String> {
    let syms = META_SYMS.get().ok_or(
        "MetaSymbols not resolved — call introspect::resolve() at plugin init first",
    )?;
    let mut out = Vec::new();
    let mut iter: *mut c_void = std::ptr::null_mut();
    for _ in 0..4096 {
        let f = (syms.il2cpp_class_get_fields)(class, &mut iter as *mut _);
        if f.is_null() {
            return Ok(out);
        }
        let flags = (syms.il2cpp_field_get_flags)(f);
        if flags & (FIELD_ATTRIBUTE_STATIC | FIELD_ATTRIBUTE_LITERAL) != 0 {
            continue;
        }
        let name_ptr = (syms.il2cpp_field_get_name)(f);
        if name_ptr.is_null() {
            continue;
        }
        let name = CStr::from_ptr(name_ptr).to_string_lossy().into_owned();
        let ty = (syms.il2cpp_field_get_type)(f);
        let type_enum = if ty.is_null() {
            0
        } else {
            (syms.il2cpp_type_get_type)(ty)
        };
        let offset = (syms.il2cpp_field_get_offset)(f);
        out.push(Field {
            name,
            type_enum,
            type_ptr: ty,
            offset,
        });
    }
    Err("il2cpp_class_get_fields exceeded 4096 iterations — API misuse?".into())
}

/// Read a primitive at `obj + offset`. Returns None for anything
/// that isn't a simple scalar (strings, class refs, arrays — those
/// need dedicated handling that lands in v0.0.7b).
///
/// Returned strings are display-format ("42", "3.14", "true").
///
/// # Safety
///
/// `obj` must point at a valid initialized Il2CppObject of the
/// class the field belongs to, and `offset` must be that field's
/// offset. Reading at wrong offset = arbitrary memory read.
pub unsafe fn read_primitive(obj: *mut c_void, offset: i32, type_enum: Il2CppTypeEnum) -> Option<String> {
    let base = obj as *const u8;
    let at = base.offset(offset as isize);
    match type_enum {
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_BOOLEAN => Some((*(at as *const u8) != 0).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_CHAR => {
            let c = *(at as *const u16);
            Some(format!("'{}' (u16={})", char::from_u32(c as u32).unwrap_or('?'), c))
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I1 => Some((*(at as *const i8)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U1 => Some((*(at as *const u8)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I2 => Some((*(at as *const i16)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U2 => Some((*(at as *const u16)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I4 => Some((*(at as *const i32)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U4 => Some((*(at as *const u32)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I8 => Some((*(at as *const i64)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U8 => Some((*(at as *const u64)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_R4 => Some((*(at as *const f32)).to_string()),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_R8 => Some((*(at as *const f64)).to_string()),
        _ => None,
    }
}

/// Read a raw pointer field (CLASS or STRING type — both are
/// reference types on x64, 8 bytes at the offset).
pub unsafe fn read_ref(obj: *mut c_void, offset: i32) -> *mut c_void {
    let base = obj as *const u8;
    let at = base.offset(offset as isize);
    *(at as *const *mut c_void)
}

// ── ObscuredInt decoding ──────────────────────────────────────

/// `Gallop.ObscuredIdleSingleModeInt` and friends hide their real
/// int32 as `hiddenValue XOR currentCryptoKey`. This mirrors the
/// extractor's `tryDecodeOI` (dump_it_run.py:52).
///
/// Returns None if `obscured_obj` isn't actually an obscured-int
/// (doesn't have the two expected fields) — the caller can then
/// fall back to walking the object's fields normally.
///
/// Caches (class → offsets) on first-seen so subsequent decodes
/// of the same class are constant-time.
/// CodeStage.AntiCheat.ObscuredTypes.ObscuredBool stores its value
/// as one of two magic constants XOR'd with the key. Reverse-
/// engineered 2026-08-02 by dumping raw bytes of live
/// ObscuredCharaEffectLog.IsActive fields against a known-state
/// Training Log; correlation was 3/3.
const OBOOL_FALSE: i32 = 181;
const OBOOL_TRUE: i32 = 213;

/// If `klass`'s type name ends with "ObscuredBool", interpret an
/// already-XOR-decoded int as a bool via the magic constants.
/// Returns None for non-ObscuredBool classes (caller falls back to
/// emitting the raw int). Returns Some(JsonValue::Null) for
/// ObscuredBool values that don't match either magic constant —
/// treated as corruption / unexpected rather than silently mapping
/// to true or false.
unsafe fn obscured_int_as_bool(v: i32, klass: *mut Il2CppClass) -> Option<JsonValue> {
    let syms = META_SYMS.get()?;
    let name_ptr = (syms.il2cpp_class_get_name)(klass);
    if name_ptr.is_null() {
        return None;
    }
    let name = CStr::from_ptr(name_ptr).to_bytes();
    if !name.ends_with(b"ObscuredBool") {
        return None;
    }
    Some(match v {
        OBOOL_TRUE => JsonValue::Bool(true),
        OBOOL_FALSE => JsonValue::Bool(false),
        _ => JsonValue::Null,
    })
}

pub unsafe fn try_decode_obscured_int(obscured_obj: *mut c_void) -> Option<i32> {
    if obscured_obj.is_null() {
        return None;
    }
    // First 8 bytes of any Il2CppObject are `Il2CppClass* klass`.
    let klass = *(obscured_obj as *const *mut Il2CppClass);
    if klass.is_null() {
        return None;
    }
    let (hidden_offset, key_offset) = obscured_offsets_for(klass)?;
    let hidden = *((obscured_obj as *const u8).offset(hidden_offset as isize) as *const i32);
    let key = *((obscured_obj as *const u8).offset(key_offset as isize) as *const i32);
    Some(hidden ^ key)
}

use std::sync::Mutex;

/// Cache of (klass-as-address, Option<(hiddenValue_offset, currentCryptoKey_offset)>)
/// for obscured-int classes we've seen. `None` means "not obscured" —
/// caching negative results too so we don't re-describe + re-log
/// non-obscured classes on every field access.
///
/// Uses `usize` (address) as the key rather than `*mut Il2CppClass`
/// because raw pointers aren't `Send`. Comparing addresses works
/// because IL2CPP class pointers are stable for the process lifetime.
static OBSCURED_CACHE: OnceCell<Mutex<Vec<(usize, Option<(i32, i32)>)>>> = OnceCell::new();

/// Try to decode an `ObscuredIdleSingleModeSignedInt` (or any
/// object with a `<Sign>k__BackingField` + `<Value>k__BackingField`
/// pair). Mirrors the extractor's second branch in `walk()`
/// (dump_it_run.py:67).
///
/// v0.0.7a's version assumed both fields were CLASS refs (pointer
/// to ObscuredInt heap object). That's wrong for
/// `ObscuredIdleSingleModeInt` on the current build — it's a
/// VALUETYPE struct, so the wrapper's `<Sign>`/`<Value>` fields
/// are inline structs, not pointers. Reading struct bytes as a
/// pointer and dereferencing crashed the game.
///
/// This version iterates the wrapper's fields, dispatches on each
/// one's actual type (CLASS → deref + decode, VALUETYPE → decode
/// inline), and short-circuits once both are found.
unsafe fn try_decode_signed_int(obj: *mut c_void) -> Option<i32> {
    if obj.is_null() {
        return None;
    }
    let klass = *(obj as *const *mut Il2CppClass);
    if klass.is_null() {
        return None;
    }
    let fields = describe_fields(klass).ok()?;

    // First-time diagnostic for SignedInt-shaped classes: log the
    // wrapper's layout so we can see what type <Sign>/<Value> are
    // and their offsets. Complements the diagnostic in
    // obscured_offsets_for which fires for ObscuredInt structs.
    log_signed_layout_once(klass, &fields);

    let mut sign = None;
    let mut value = None;
    for f in &fields {
        let is_sign = f.name == "<Sign>k__BackingField";
        let is_value = f.name == "<Value>k__BackingField";
        if !is_sign && !is_value {
            continue;
        }
        let decoded = decode_field_as_obscured(obj, f);
        if is_sign {
            sign = decoded;
        } else {
            value = decoded;
        }
        if sign.is_some() && value.is_some() {
            break;
        }
    }
    let (s, v) = (sign?, value?);
    Some(if s < 0 { -v } else { v })
}

/// Log the SignedInt wrapper's field layout the first time we see
/// each such class. Uses a small dedupe set keyed by klass address
/// so we don't spam per-instance. In practice only fires for
/// `ObscuredIdleSingleModeSignedInt` on Umamusume Global.
static SIGNED_LOG_SEEN: OnceCell<Mutex<Vec<usize>>> = OnceCell::new();
unsafe fn log_signed_layout_once(klass: *mut Il2CppClass, fields: &[Field]) {
    let key = klass as usize;
    let seen = SIGNED_LOG_SEEN.get_or_init(|| Mutex::new(Vec::new()));
    if let Ok(mut g) = seen.lock() {
        if g.contains(&key) {
            return;
        }
        g.push(key);
    }
    // Additional guard: only log for classes that actually look
    // SignedInt-shaped (have <Sign>k__BackingField field). Otherwise
    // this fires for every non-signed class we describe (like
    // SingleRaceHistory) and floods the log.
    let has_sign = fields.iter().any(|f| f.name == "<Sign>k__BackingField");
    if !has_sign {
        return;
    }
    if let Some(syms) = META_SYMS.get() {
        let ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(klass));
        let name = cstr_or_empty((syms.il2cpp_class_get_name)(klass));
        info!(
            "[uma-it] first-encounter SignedInt-like layout: {}.{} ({} fields):",
            ns,
            name,
            fields.len()
        );
        for f in fields {
            info!(
                "[uma-it]   field: {} @ offset={}, type={}",
                f.name, f.offset, f.type_enum
            );
        }
    }
}

/// Decode a single field on `container` as an ObscuredInt-shaped
/// value, dispatching on the field's actual type.
///
/// - CLASS: read pointer at container+offset, treat as
///   Il2CppObject*, decode via `try_decode_obscured_int`
/// - VALUETYPE: struct data lives inline at container+offset,
///   decode via `try_decode_inline_obscured_int` using the
///   struct's class from the field's type ptr
/// - anything else: None
unsafe fn decode_field_as_obscured(container: *mut c_void, f: &Field) -> Option<i32> {
    match f.type_enum {
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_CLASS => {
            let ptr = read_ref(container, f.offset);
            if ptr.is_null() {
                return None;
            }
            try_decode_obscured_int(ptr)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_VALUETYPE => {
            if f.type_ptr.is_null() {
                return None;
            }
            let syms = META_SYMS.get()?;
            let sc = (syms.il2cpp_type_get_class_or_element_class)(f.type_ptr);
            if sc.is_null() {
                return None;
            }
            try_decode_inline_obscured_int(container, f.offset, sc)
        }
        _ => None,
    }
}

/// Try to decode an inline value-type struct at `container + offset`
/// as an ObscuredInt-shaped struct. `struct_class` is the struct's
/// own class (obtained via `il2cpp_type_get_class_or_element_class`
/// on the field's type). If the struct declares `hiddenValue` and
/// `currentCryptoKey` i32 fields, we XOR them; otherwise None.
///
/// Unity IL2CPP wrinkle: `il2cpp_field_get_offset` on a value-type
/// class returns offsets AS IF the struct were boxed (with a
/// 16-byte Il2CppObject header prefix). Inline access has no
/// header, so we subtract 16 from the reported offset to get the
/// actual inline byte offset.
///
/// If the reported offset is < 16, either (a) this isn't actually
/// a value type or (b) the runtime uses a different convention on
/// this build. Log-once-and-fall-back rather than read wildly.
unsafe fn try_decode_inline_obscured_int(
    container: *mut c_void,
    struct_offset: i32,
    struct_class: *mut Il2CppClass,
) -> Option<i32> {
    let (hidden_off, key_off) = obscured_offsets_for(struct_class)?;
    // Subtract Il2CppObject header size to convert boxed→inline offset.
    // If either is < 16, il2cpp on this build doesn't apply the
    // boxed-header bias for value types; use raw offsets.
    const IL2CPP_OBJECT_HEADER: i32 = 16;
    let (h_use, k_use) = if hidden_off >= IL2CPP_OBJECT_HEADER
        && key_off >= IL2CPP_OBJECT_HEADER
    {
        (hidden_off - IL2CPP_OBJECT_HEADER, key_off - IL2CPP_OBJECT_HEADER)
    } else {
        (hidden_off, key_off)
    };
    let base = (container as *const u8).offset(struct_offset as isize);
    let hidden = *(base.offset(h_use as isize) as *const i32);
    let key = *(base.offset(k_use as isize) as *const i32);
    Some(hidden ^ key)
}

unsafe fn obscured_offsets_for(klass: *mut Il2CppClass) -> Option<(i32, i32)> {
    let key_addr = klass as usize;
    let cache = OBSCURED_CACHE.get_or_init(|| Mutex::new(Vec::new()));
    // Fast path: cached (positive or negative).
    if let Ok(guard) = cache.lock() {
        for (k, off) in guard.iter() {
            if *k == key_addr {
                return *off;
            }
        }
    }
    // Slow path: describe fields, find the two by name.
    let fields = describe_fields(klass).ok()?;

    let mut hidden = None;
    let mut key = None;
    for f in &fields {
        if f.name == "hiddenValue" {
            hidden = Some(f.offset);
        } else if f.name == "currentCryptoKey" {
            key = Some(f.offset);
        }
    }
    let result = match (hidden, key) {
        (Some(h), Some(k)) => Some((h, k)),
        _ => None,
    };

    // Diagnostic log: ONLY for classes that turn out to be obscured
    // (positive match). Non-obscured classes would spam the log
    // without adding info.
    if result.is_some() {
        if let Some(syms) = META_SYMS.get() {
            let ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(klass));
            let name = cstr_or_empty((syms.il2cpp_class_get_name)(klass));
            info!(
                "[uma-it] first-encounter obscured layout: {}.{} ({} fields):",
                ns,
                name,
                fields.len()
            );
            for f in &fields {
                info!(
                    "[uma-it]   field: {} @ offset={}, type={}",
                    f.name, f.offset, f.type_enum
                );
            }
        }
    }

    // Cache both positive and negative results — non-obscured
    // classes get re-visited many times per scan (SingleRaceHistory
    // etc.), and we don't want to re-describe them every time.
    if let Ok(mut guard) = cache.lock() {
        guard.push((key_addr, result));
    }
    result
}

// ── Human-readable dump for one instance ──────────────────────

/// Walk one instance and log each field to `info!`. v0.0.7 debug
/// output — validates against the extractor's known-good JSON
/// (`IT-references/*.json`) by eyeballing values.
///
/// Handles:
/// - Primitive scalars (int/float/bool/etc.) → value
/// - Reference-typed fields whose class matches an ObscuredInt-
///   shape → decoded value
/// - Other reference-typed fields → just log the pointer
/// - Strings + arrays → placeholder (v0.0.7b)
pub unsafe fn dump_instance(obj: *mut c_void) {
    if obj.is_null() {
        info!("[uma-it]   (null instance)");
        return;
    }
    let klass = *(obj as *const *mut Il2CppClass);
    if klass.is_null() {
        info!("[uma-it]   instance @ {:p} has null klass ptr — bad object?", obj);
        return;
    }
    let syms = match META_SYMS.get() {
        Some(s) => s,
        None => {
            error!("[uma-it] introspect not resolved");
            return;
        }
    };
    let ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(klass));
    let name = cstr_or_empty((syms.il2cpp_class_get_name)(klass));
    let fields = match describe_fields(klass) {
        Ok(fs) => fs,
        Err(e) => {
            error!("[uma-it] field enumeration failed: {e}");
            return;
        }
    };
    info!("[uma-it] {}.{} @ {:p} — {} instance fields:", ns, name, obj, fields.len());
    for f in &fields {
        let rendered = render_field(obj, f);
        info!("[uma-it]   {} (offset={}, type={}) = {}", f.name, f.offset, f.type_enum, rendered);
    }
}

unsafe fn render_field(obj: *mut c_void, f: &Field) -> String {
    if let Some(s) = read_primitive(obj, f.offset, f.type_enum) {
        return s;
    }
    let syms = META_SYMS.get().unwrap();
    match f.type_enum {
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_STRING => {
            let ptr = read_ref(obj, f.offset);
            if ptr.is_null() { "null".into() } else { format!("<string @ {:p}>", ptr) }
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_CLASS => {
            let ptr = read_ref(obj, f.offset);
            if ptr.is_null() {
                return "null".into();
            }
            // Level 1: direct ObscuredInt (hiddenValue + currentCryptoKey).
            if let Some(v) = try_decode_obscured_int(ptr) {
                return format!("{} (obscured)", v);
            }
            // Level 2: ObscuredSignedInt (wraps two ObscuredInts as
            // <Sign>k__BackingField + <Value>k__BackingField).
            if let Some(v) = try_decode_signed_int(ptr) {
                return format!("{} (obscured signed)", v);
            }
            // Unknown class: log the type and pointer.
            let klass = *(ptr as *const *mut Il2CppClass);
            if klass.is_null() {
                return format!("<obj @ {:p} (no klass)>", ptr);
            }
            let ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(klass));
            let name = cstr_or_empty((syms.il2cpp_class_get_name)(klass));
            format!("<{}.{} @ {:p}>", ns, name, ptr)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_VALUETYPE => {
            // Inline value-type struct. Resolve its class from the
            // field's type ptr, then try decoding as ObscuredInt.
            if f.type_ptr.is_null() {
                return "<valuetype: null type ptr>".into();
            }
            let struct_class = (syms.il2cpp_type_get_class_or_element_class)(f.type_ptr);
            if struct_class.is_null() {
                return "<valuetype: no class>".into();
            }
            if let Some(v) = try_decode_inline_obscured_int(obj, f.offset, struct_class) {
                return format!("{} (obscured struct)", v);
            }
            let ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(struct_class));
            let name = cstr_or_empty((syms.il2cpp_class_get_name)(struct_class));
            format!("<struct {}.{}>", ns, name)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_SZARRAY => {
            let ptr = read_ref(obj, f.offset);
            if ptr.is_null() {
                return "null[]".into();
            }
            // Il2CppArray layout (x64):
            //   +0   Il2CppObject header (klass + monitor) — 16 bytes
            //   +16  Il2CppArrayBounds* bounds — 8 bytes
            //   +24  il2cpp_array_size_t max_length — 8 bytes
            //   +32  first element
            let len_ptr = (ptr as *const u8).offset(24) as *const usize;
            let len = *len_ptr;
            if len == 0 {
                return format!("[] (len=0) @ {:p}", ptr);
            }
            // Get element class from the array-field type ptr.
            if f.type_ptr.is_null() {
                return format!("<array len={} @ {:p} (no type ptr)>", len, ptr);
            }
            let elem_class = (syms.il2cpp_type_get_class_or_element_class)(f.type_ptr);
            if elem_class.is_null() {
                return format!("<array len={} @ {:p} (no element class)>", len, ptr);
            }
            let elem_ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(elem_class));
            let elem_name = cstr_or_empty((syms.il2cpp_class_get_name)(elem_class));
            let elem_is_value = (syms.il2cpp_class_is_valuetype)(elem_class);
            // Stride depends on whether elements are inline (structs)
            // or references (pointers to heap objects). v0.0.7d
            // used il2cpp_class_value_size for both, which was
            // wrong for reference-typed arrays (pointer stride is 8,
            // but value_size returns the boxed instance size).
            let stride: usize = if elem_is_value {
                (syms.il2cpp_class_value_size)(elem_class, std::ptr::null_mut()) as usize
            } else {
                8 // pointer size on x64
            };
            let data_start = (ptr as *const u8).offset(32);
            let show = len.min(5);
            let kind_marker = if elem_is_value { "struct" } else { "ref" };
            let mut lines = vec![format!(
                "[{}.{} × {} ({}) @ {:p}, stride={}]:",
                elem_ns, elem_name, len, kind_marker, ptr, stride
            )];
            for i in 0..show {
                let slot = data_start.offset((i * stride) as isize);
                let rendered = if elem_is_value {
                    render_inline_element(slot as *mut c_void, elem_class)
                } else {
                    let elem_ptr = *(slot as *const *mut c_void);
                    if elem_ptr.is_null() {
                        "null".into()
                    } else {
                        render_object_element(elem_ptr, elem_class)
                    }
                };
                lines.push(format!("    [{}] = {}", i, rendered));
            }
            if len > show {
                lines.push(format!("    ... {} more", len - show));
            }
            lines.join("\n")
        }
        _ => format!("<type_enum={}>", f.type_enum),
    }
}

/// Enumerate all classes in an IL2CPP image and return the one
/// whose flattened type name matches `target_full_name` (e.g.
/// `"Gallop.WorkTrainedCharaData.TrainedCharaData"`). Mirrors
/// what Frida's `image.classes` iteration does for classes with
/// dotted namespaces or nested-class flattening.
///
/// Returns None if no match. On success, both the outer type ptr
/// and the flattened name string produced by
/// `il2cpp_type_get_name` are freed via the resolved
/// `il2cpp_free` (also passed here since it lives in the GC
/// symbols module).
///
/// Uses il2cpp_free from the GC symbols cache since MetaSymbols
/// doesn't include it — the free is only for the transient
/// type-name strings we get back.
///
/// # Safety
///
/// `image` must be a valid Il2CppImage pointer from
/// il2cpp_get_assembly_image. MetaSymbols must be resolved.
pub unsafe fn find_class_by_full_name(
    image: *const c_void,
    target_full_name: &str,
) -> Option<*mut Il2CppClass> {
    let syms = META_SYMS.get()?;
    let count = (syms.il2cpp_image_get_class_count)(image);
    if count == 0 {
        return None;
    }
    // Also need il2cpp_free from GC symbols to free the type-name
    // strings that il2cpp_type_get_name allocates. Fetching via
    // the crate::gc_scan module — a bit of a layering violation
    // but keeps this reusable.
    let free_fn = crate::gc_scan::get_il2cpp_free();
    for i in 0..count {
        let klass = (syms.il2cpp_image_get_class)(image, i);
        if klass.is_null() {
            continue;
        }
        let ty = (syms.il2cpp_class_get_type)(klass);
        if ty.is_null() {
            continue;
        }
        let name_ptr = (syms.il2cpp_type_get_name)(ty);
        if name_ptr.is_null() {
            continue;
        }
        let name = CStr::from_ptr(name_ptr).to_string_lossy().into_owned();
        if let Some(free) = free_fn {
            free(name_ptr as *mut c_void);
        }
        if name == target_full_name {
            return Some(klass);
        }
    }
    None
}

/// Pick the object from `matches` whose int32 field named
/// `field_name` has the highest value. Returns `(ptr, value)` of
/// the winner. Used by scan_and_log for classes like
/// SingleModeChara where heap-scan finds multiple template
/// instances and the extractor picks by fans (dump_it_run.py:517).
///
/// Assumes all matches share the same class (they do — they came
/// from a scan filtered to one class). Resolves the field offset
/// once from the first match's class.
/// Snapshot of the 4 int fields that identify which IT run an SMC
/// instance represents. Cheap: one describe_fields lookup + direct
/// memory reads (same pattern pick_best_by_int_field uses). Used
/// for logging pre-pick candidates so we can diagnose the "picker
/// chose stale SMC from earlier IT in the same game session" case
/// if it's ever reported.
///
/// All fields are `Option` because a template SMC may lack them or
/// the type_enum could be non-I4 (in which case the read is
/// deliberately skipped — never a wild pointer deref).
pub struct SmcDiag {
    pub card_id: Option<i32>,
    pub scenario_id: Option<i32>,
    pub fans: Option<i32>,
    pub turn: Option<i32>,
}

pub unsafe fn peek_smc_diag(obj: *mut c_void) -> SmcDiag {
    let klass = *(obj as *const *mut Il2CppClass);
    if klass.is_null() {
        return SmcDiag { card_id: None, scenario_id: None, fans: None, turn: None };
    }
    let fields = describe_fields(klass).ok();
    let read = |name: &str| -> Option<i32> {
        let fs = fields.as_ref()?;
        let f = fs
            .iter()
            .find(|f| f.name == name && f.type_enum == edge_sdk::ffi::Il2CppTypeEnum_IL2CPP_TYPE_I4)?;
        Some(*((obj as *const u8).offset(f.offset as isize) as *const i32))
    };
    SmcDiag {
        card_id: read("card_id"),
        scenario_id: read("scenario_id"),
        fans: read("fans"),
        turn: read("turn"),
    }
}

pub unsafe fn pick_best_by_int_field(
    matches: &[*mut c_void],
    field_name: &str,
) -> Option<(*mut c_void, i32)> {
    if matches.is_empty() {
        return None;
    }
    let first = matches[0];
    let klass = *(first as *const *mut Il2CppClass);
    if klass.is_null() {
        return None;
    }
    let fields = describe_fields(klass).ok()?;
    let f = fields.iter().find(|f| f.name == field_name)?;
    // Only int32 fields are candidates for pick-by (that's what
    // the extractor uses for "fans" / "chara_grade").
    if f.type_enum != edge_sdk::ffi::Il2CppTypeEnum_IL2CPP_TYPE_I4 {
        return None;
    }
    let mut best = matches[0];
    let mut best_val: i32 = *((best as *const u8).offset(f.offset as isize) as *const i32);
    for &obj in &matches[1..] {
        let val = *((obj as *const u8).offset(f.offset as isize) as *const i32);
        if val > best_val {
            best_val = val;
            best = obj;
        }
    }
    Some((best, best_val))
}

unsafe fn cstr_or_empty(p: *const i8) -> String {
    if p.is_null() {
        "".into()
    } else {
        CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}

// ── JSON walker ─────────────────────────────────────────────

/// Depth budget for recursion into nested class refs. Keeps the
/// output tractable and rules out cycles. The extractor's
/// walkDeep uses depth 6 for parent lineage
/// (dump_it_run.py:150-192) — we match that to capture grandparent
/// factor arrays under Parents. v0.0.8a used 4 which was too
/// shallow for inheritance lineage.
const MAX_JSON_DEPTH: u32 = 6;

/// Walk one Il2CppObject to a JsonValue::Object with entries for
/// each declared instance field. Recurses into class refs and
/// value-type structs up to `MAX_JSON_DEPTH` (short-circuits with
/// null past that).
pub unsafe fn walk_to_json(obj: *mut c_void) -> JsonValue {
    walk_object(obj, 0)
}

unsafe fn walk_object(obj: *mut c_void, depth: u32) -> JsonValue {
    if obj.is_null() {
        return JsonValue::Null;
    }
    let klass = *(obj as *const *mut Il2CppClass);
    if klass.is_null() {
        return JsonValue::Null;
    }
    let fields = match describe_fields(klass) {
        Ok(f) => f,
        Err(_) => return JsonValue::Null,
    };
    let mut entries: Vec<(String, JsonValue)> = Vec::with_capacity(fields.len());
    for f in &fields {
        entries.push((f.name.clone(), value_for_field(obj, f, depth, false)));
    }
    JsonValue::Object(entries)
}

// NOTE: v0.0.8a had a `clean_field_name` helper that stripped
// `<Foo>k__BackingField` → `Foo`. Removed in v0.0.8b — the web
// app's enrich modules read the RAW C# field names literally
// (grep for `<GainInfo>k__BackingField`, `<Speed>k__BackingField`,
// etc. in uma_it_web/enrich/compat.py, run_metrics.py, per_run_detail.py).
// Stripping the decoration silently broke web-app compat.
// Keep raw names to match the .exe extractor's output.

/// Read a single field's value at `container + offset`, returning
/// a JsonValue. Dispatches on `f.type_enum`. `inline=true` means
/// container is inline struct data (no header) — apply -16 offset
/// adjust for value-type fields (matches try_decode_inline_obscured_int).
unsafe fn value_for_field(
    container: *mut c_void,
    f: &Field,
    depth: u32,
    inline: bool,
) -> JsonValue {
    const HDR: i32 = 16;
    let use_off = if inline && f.offset >= HDR {
        f.offset - HDR
    } else {
        f.offset
    };
    // Primitive scalars.
    if let Some(v) = value_primitive_json(container, use_off, f.type_enum) {
        return v;
    }
    let syms = match META_SYMS.get() {
        Some(s) => s,
        None => return JsonValue::Null,
    };
    match f.type_enum {
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_STRING => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() {
                return JsonValue::Null;
            }
            match decode_string(ptr as *mut Il2CppString) {
                Some(s) => JsonValue::string(s),
                None => JsonValue::Null,
            }
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_CLASS => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() {
                return JsonValue::Null;
            }
            if let Some(v) = try_decode_obscured_int(ptr) {
                // Same obscured layout, different interpretation:
                // if the referent's class is ObscuredBool, decoded
                // int is one of the 213/181 magic constants → bool.
                let klass = *(ptr as *const *mut Il2CppClass);
                if let Some(b) = obscured_int_as_bool(v, klass) {
                    return b;
                }
                return JsonValue::Int(v as i64);
            }
            if let Some(v) = try_decode_signed_int(ptr) {
                return JsonValue::Int(v as i64);
            }
            if depth + 1 >= MAX_JSON_DEPTH {
                return JsonValue::Null;
            }
            walk_object(ptr, depth + 1)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_VALUETYPE => {
            if f.type_ptr.is_null() {
                return JsonValue::Null;
            }
            let struct_class = (syms.il2cpp_type_get_class_or_element_class)(f.type_ptr);
            if struct_class.is_null() {
                return JsonValue::Null;
            }
            if let Some(v) = try_decode_inline_obscured_int(container, use_off, struct_class) {
                // Same dispatch as the CLASS branch above — inline
                // ObscuredBool structs (e.g. IsActive on
                // ObscuredCharaEffectLog) decode to true/false, not
                // the raw magic byte.
                if let Some(b) = obscured_int_as_bool(v, struct_class) {
                    return b;
                }
                return JsonValue::Int(v as i64);
            }
            // Non-obscured value type: walk its fields inline.
            if depth + 1 >= MAX_JSON_DEPTH {
                return JsonValue::Null;
            }
            walk_inline(container, use_off, struct_class, depth + 1)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_GENERICINST => {
            // Generic type instantiation (List<T>, Dictionary<K,V>,
            // Nullable<T>, or generic value types). Resolve the
            // underlying class from the type ptr, then dispatch on
            // value-type-ness: reference generics (List) read as
            // pointer + walk_object; value generics read inline.
            //
            // Blocking bug pre-fix: SuccessionCharaList
            // (List<SuccessionCharaData>) is type=21 GENERICINST.
            // Without this branch it fell through to the default
            // and returned null — losing all grandparent lineage.
            if f.type_ptr.is_null() {
                return JsonValue::Null;
            }
            let generic_class = (syms.il2cpp_type_get_class_or_element_class)(f.type_ptr);
            if generic_class.is_null() {
                return JsonValue::Null;
            }
            let is_value = (syms.il2cpp_class_is_valuetype)(generic_class);
            if is_value {
                // Inline generic value type (rare — Nullable<T>,
                // KeyValuePair<K,V>, custom structs).
                if depth + 1 >= MAX_JSON_DEPTH {
                    return JsonValue::Null;
                }
                walk_inline(container, use_off, generic_class, depth + 1)
            } else {
                // Reference generic (List, Dictionary, etc.):
                // read pointer + walk as object.
                let ptr = read_ref(container, use_off);
                if ptr.is_null() {
                    return JsonValue::Null;
                }
                if depth + 1 >= MAX_JSON_DEPTH {
                    return JsonValue::Null;
                }
                walk_object(ptr, depth + 1)
            }
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_SZARRAY => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() {
                return JsonValue::Array(Vec::new());
            }
            walk_array(ptr, f.type_ptr, depth + 1)
        }
        _ => JsonValue::Null,
    }
}

unsafe fn value_primitive_json(obj: *mut c_void, offset: i32, type_enum: Il2CppTypeEnum) -> Option<JsonValue> {
    let base = obj as *const u8;
    let at = base.offset(offset as isize);
    match type_enum {
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_BOOLEAN => Some(JsonValue::Bool(*(at as *const u8) != 0)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I1 => Some(JsonValue::Int(*(at as *const i8) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U1 => Some(JsonValue::Int(*(at as *const u8) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I2 => Some(JsonValue::Int(*(at as *const i16) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U2 => Some(JsonValue::Int(*(at as *const u16) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I4 => Some(JsonValue::Int(*(at as *const i32) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U4 => Some(JsonValue::Int(*(at as *const u32) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_I8 => Some(JsonValue::Int(*(at as *const i64))),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_U8 => Some(JsonValue::Int(*(at as *const u64) as i64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_R4 => Some(JsonValue::Float(*(at as *const f32) as f64)),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_R8 => Some(JsonValue::Float(*(at as *const f64))),
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_CHAR => Some(JsonValue::Int(*(at as *const u16) as i64)),
        _ => None,
    }
}

/// Walk inline value-type struct data starting at `container + offset`
/// (no Il2CppObject header). Emits {name: value} for each declared
/// field, with -16 offset adjust for value-type field metadata.
unsafe fn walk_inline(
    container: *mut c_void,
    offset: i32,
    struct_class: *mut Il2CppClass,
    depth: u32,
) -> JsonValue {
    let fields = match describe_fields(struct_class) {
        Ok(f) => f,
        Err(_) => return JsonValue::Null,
    };
    let base = (container as *const u8).offset(offset as isize) as *mut c_void;
    let mut entries: Vec<(String, JsonValue)> = Vec::with_capacity(fields.len());
    for f in &fields {
        entries.push((f.name.clone(), value_for_field(base, f, depth, true)));
    }
    JsonValue::Object(entries)
}

/// Walk a SZARRAY. `array_ptr` points at the Il2CppArray header.
/// `array_type_ptr` is the field's type ptr (used to get element class).
unsafe fn walk_array(
    array_ptr: *mut c_void,
    array_type_ptr: *const c_void,
    depth: u32,
) -> JsonValue {
    let syms = match META_SYMS.get() {
        Some(s) => s,
        None => return JsonValue::Null,
    };
    let len = *((array_ptr as *const u8).offset(24) as *const usize);
    if len == 0 {
        return JsonValue::Array(Vec::new());
    }
    if array_type_ptr.is_null() {
        return JsonValue::Null;
    }
    let elem_class = (syms.il2cpp_type_get_class_or_element_class)(array_type_ptr);
    if elem_class.is_null() {
        return JsonValue::Null;
    }
    let is_value = (syms.il2cpp_class_is_valuetype)(elem_class);
    let stride: usize = if is_value {
        (syms.il2cpp_class_value_size)(elem_class, std::ptr::null_mut()) as usize
    } else {
        8 // pointer
    };
    let data_start = (array_ptr as *const u8).offset(32);
    // Cap array walk to keep JSON payload manageable and avoid
    // pathological cases (500-element inner arrays × 40 top-level).
    const MAX_ARRAY_ELEMS: usize = 200;
    let take = len.min(MAX_ARRAY_ELEMS);
    let mut items: Vec<JsonValue> = Vec::with_capacity(take);
    for i in 0..take {
        let slot = data_start.offset((i * stride) as isize);
        let item = if is_value {
            // Try obscured-int decode first — the element class might be
            // ObscuredInt/ObscuredBool (e.g. _winSaddleIdArray on a
            // grandparent is ObscuredInt[]). Without this, walk_inline
            // dumps raw {hiddenValue, currentCryptoKey, ...} structs
            // and downstream compat code treats every entry as 0. Same
            // dispatch as value_for_field TYPE_VALUETYPE branch.
            if let Some(v) = try_decode_inline_obscured_int(slot as *mut c_void, 0, elem_class) {
                if let Some(b) = obscured_int_as_bool(v, elem_class) {
                    b
                } else {
                    JsonValue::Int(v as i64)
                }
            } else {
                walk_inline(slot as *mut c_void, 0, elem_class, depth)
            }
        } else {
            let elem_ptr = *(slot as *const *mut c_void);
            if depth + 1 >= MAX_JSON_DEPTH {
                JsonValue::Null
            } else {
                walk_object(elem_ptr, depth + 1)
            }
        };
        items.push(item);
    }
    JsonValue::Array(items)
}

/// Decode an Il2CppString to a Rust String via edge-sdk's
/// il2cpp_string_length + il2cpp_string_chars helpers. Returns None
/// if the API isn't in the vtable (very unlikely on current Hachimi).
unsafe fn decode_string(s: *mut Il2CppString) -> Option<String> {
    if s.is_null() {
        return None;
    }
    let api = Api::get();
    let string_len = api.il2cpp_string_length?;
    let string_chars = api.il2cpp_string_chars?;
    let len = string_len(s);
    if len < 0 {
        return None;
    }
    let chars = string_chars(s);
    if chars.is_null() {
        return None;
    }
    let slice = std::slice::from_raw_parts(chars, len as usize);
    Some(String::from_utf16_lossy(slice))
}

/// Render a single reference-typed array element as `{f1=v1, f2=v2, ...}`.
/// Walks fields on the element's class, decoding primitives, obscured
/// values (level 1, level 2, inline struct), and logging placeholders
/// for nested arrays / class refs (recursion left to v0.0.8's JSON
/// walker).
///
/// `elem_ptr` is the dereferenced pointer to an Il2CppObject of
/// `elem_class`. Field offsets on `elem_class` are OBJECT-relative
/// (include the 16-byte header) since it's a reference type.
unsafe fn render_object_element(elem_ptr: *mut c_void, elem_class: *mut Il2CppClass) -> String {
    let fields = match describe_fields(elem_class) {
        Ok(f) => f,
        Err(_) => return format!("<obj @ {:p} (fields?)>", elem_ptr),
    };
    let mut parts = Vec::with_capacity(fields.len());
    for f in &fields {
        parts.push(format!("{}={}", f.name, render_nested_value(elem_ptr, f, false)));
    }
    format!("{{{}}}", parts.join(", "))
}

/// Render a single value-typed array element (inline struct at
/// `elem_ptr`, no header). Tries obscured-int shape first, else
/// walks the struct's fields with -16 offset adjust for value-type
/// context.
unsafe fn render_inline_element(elem_ptr: *mut c_void, elem_class: *mut Il2CppClass) -> String {
    if let Some(v) = try_decode_inline_obscured_int(elem_ptr, 0, elem_class) {
        return format!("{} (obscured struct)", v);
    }
    let fields = match describe_fields(elem_class) {
        Ok(f) => f,
        Err(_) => return format!("<struct @ {:p} (fields?)>", elem_ptr),
    };
    let mut parts = Vec::with_capacity(fields.len());
    for f in &fields {
        parts.push(format!("{}={}", f.name, render_nested_value(elem_ptr, f, true)));
    }
    format!("{{{}}}", parts.join(", "))
}

/// Shared field renderer for nested contexts (inside array elements
/// or nested class refs). Handles primitives, obscured shapes, and
/// nested value-type structs. Does NOT recurse into nested class
/// refs (would risk infinite loops or huge log volume) — logs the
/// class name + ptr instead. v0.0.8 (JSON) will add depth-limited
/// class-ref recursion.
///
/// `inline` = true when we're inside a value-type context (struct
/// array element or the outer struct itself). Determines whether
/// field offsets need the -16 header adjust.
unsafe fn render_nested_value(container: *mut c_void, f: &Field, inline: bool) -> String {
    const HDR: i32 = 16;
    let use_off = if inline && f.offset >= HDR {
        f.offset - HDR
    } else {
        f.offset
    };
    if let Some(v) = read_primitive(container, use_off, f.type_enum) {
        return v;
    }
    let syms = match META_SYMS.get() {
        Some(s) => s,
        None => return format!("<t{}>", f.type_enum),
    };
    match f.type_enum {
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_CLASS => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() {
                return "null".into();
            }
            if let Some(v) = try_decode_obscured_int(ptr) {
                return v.to_string();
            }
            if let Some(v) = try_decode_signed_int(ptr) {
                return v.to_string();
            }
            let klass = *(ptr as *const *mut Il2CppClass);
            if klass.is_null() {
                return format!("<obj @ {:p}>", ptr);
            }
            let name = cstr_or_empty((syms.il2cpp_class_get_name)(klass));
            format!("<{} @ {:p}>", name, ptr)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_VALUETYPE => {
            if f.type_ptr.is_null() {
                return "<vt:null>".into();
            }
            let struct_class = (syms.il2cpp_type_get_class_or_element_class)(f.type_ptr);
            if struct_class.is_null() {
                return "<vt:noclass>".into();
            }
            if let Some(v) = try_decode_inline_obscured_int(container, use_off, struct_class) {
                return v.to_string();
            }
            let name = cstr_or_empty((syms.il2cpp_class_get_name)(struct_class));
            format!("<struct {}>", name)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_SZARRAY => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() {
                return "null[]".into();
            }
            let len = *((ptr as *const u8).offset(24) as *const usize);
            format!("[len={}]", len)
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_STRING => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() { "null".into() } else { format!("<str @ {:p}>", ptr) }
        }
        x if x == Il2CppTypeEnum_IL2CPP_TYPE_GENERICINST => {
            let ptr = read_ref(container, use_off);
            if ptr.is_null() {
                return "null (generic)".into();
            }
            format!("<generic @ {:p}>", ptr)
        }
        _ => format!("<t{}>", f.type_enum),
    }
}
