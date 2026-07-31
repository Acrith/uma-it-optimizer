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
    Il2CppClass, Il2CppTypeEnum, Il2CppTypeEnum_IL2CPP_TYPE_BOOLEAN,
    Il2CppTypeEnum_IL2CPP_TYPE_CHAR, Il2CppTypeEnum_IL2CPP_TYPE_CLASS,
    Il2CppTypeEnum_IL2CPP_TYPE_I1, Il2CppTypeEnum_IL2CPP_TYPE_I2,
    Il2CppTypeEnum_IL2CPP_TYPE_I4, Il2CppTypeEnum_IL2CPP_TYPE_I8,
    Il2CppTypeEnum_IL2CPP_TYPE_R4, Il2CppTypeEnum_IL2CPP_TYPE_R8,
    Il2CppTypeEnum_IL2CPP_TYPE_STRING, Il2CppTypeEnum_IL2CPP_TYPE_SZARRAY,
    Il2CppTypeEnum_IL2CPP_TYPE_U1, Il2CppTypeEnum_IL2CPP_TYPE_U2,
    Il2CppTypeEnum_IL2CPP_TYPE_U4, Il2CppTypeEnum_IL2CPP_TYPE_U8,
    Il2CppTypeEnum_IL2CPP_TYPE_VALUETYPE,
};
use log::{error, info};
use once_cell::sync::OnceCell;

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

/// Cache of (klass-as-address, (hiddenValue_offset, currentCryptoKey_offset))
/// for obscured-int classes we've seen. Uses `usize` (address) as the
/// key rather than `*mut Il2CppClass` because raw pointers aren't `Send`
/// — Vec<*mut _> can't live inside a Mutex. Comparing addresses works
/// because IL2CPP class pointers are stable for the process lifetime.
static OBSCURED_CACHE: OnceCell<Mutex<Vec<(usize, (i32, i32))>>> = OnceCell::new();

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
/// so we don't spam per-instance.
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
    // Fast path: cached.
    if let Ok(guard) = cache.lock() {
        for (k, off) in guard.iter() {
            if *k == key_addr {
                return Some(*off);
            }
        }
    }
    // Slow path: describe fields, find the two by name.
    let fields = describe_fields(klass).ok()?;

    // First-time diagnostic: log the class's field layout so we can
    // see whether il2cpp is returning header-adjusted offsets (16,
    // 20, ...) or bare inline offsets (0, 4, ...). Informs whether
    // try_decode_inline_obscured_int's -16 adjustment is right for
    // this build. Only fires once per class per session (cache miss).
    if let Some(syms) = META_SYMS.get() {
        let ns = cstr_or_empty((syms.il2cpp_class_get_namespace)(klass));
        let name = cstr_or_empty((syms.il2cpp_class_get_name)(klass));
        info!(
            "[uma-it] first-encounter layout: {}.{} ({} fields):",
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

    let mut hidden = None;
    let mut key = None;
    for f in &fields {
        if f.name == "hiddenValue" {
            hidden = Some(f.offset);
        } else if f.name == "currentCryptoKey" {
            key = Some(f.offset);
        }
    }
    if let (Some(h), Some(k)) = (hidden, key) {
        if let Ok(mut guard) = cache.lock() {
            guard.push((key_addr, (h, k)));
        }
        Some((h, k))
    } else {
        None
    }
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
            // The `max_length` field is what we want for count.
            let len_ptr = (ptr as *const u8).offset(24) as *const usize;
            let len = *len_ptr;
            format!("<array len={} @ {:p}>", len, ptr)
        }
        _ => format!("<type_enum={}>", f.type_enum),
    }
}

unsafe fn cstr_or_empty(p: *const i8) -> String {
    if p.is_null() {
        "".into()
    } else {
        CStr::from_ptr(p).to_string_lossy().into_owned()
    }
}
