"""Focused scout: reverse-engineer CodeStage's ObscuredBool.

The general condition-scout confirmed Gallop.ObscuredCharaEffectLog
holds our conditions with fields (CharaEffectId, IsActive). ObscuredInt
(CharaEffectId) decodes correctly via hidden XOR key; ObscuredBool
(IsActive) does NOT — our existing decoder gives noise (181, 213)
instead of 0/1.

This script pulls the 3 live ObscuredCharaEffectLog instances, dumps
raw bytes of each IsActive struct, and (if callable) invokes the
Value getter so we have ground-truth booleans alongside the bytes.
User then correlates with the visible Training Log to figure out the
formula.

Usage:
    python scout_obscured_bool.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"


AGENT = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;

      // ── ObscuredBool class layout ────────────────────────────
      const boolCls = Il2Cpp.domain.assembly('mscorlib').image  // safe fallback
        ? null : null;  // real lookup below
      // ObscuredBool actually lives in the game's own assemblies —
      // let's find it via CharaEffectLog's IsActive field type.
      const logCls = mainImg.class('Gallop.ObscuredCharaEffectLog');
      const isActiveField = logCls.fields.find(f =>
        f.name === '<IsActive>k__BackingField');
      if (!isActiveField) {
        send({type: 'fatal', err: '<IsActive>k__BackingField not found on ObscuredCharaEffectLog'});
        return;
      }
      const oboolCls = isActiveField.type.class;
      send({type: 'text', text: 'ObscuredBool class: ' + oboolCls.type.name});
      send({type: 'text', text: '  size: ' + (oboolCls.instanceSize || '?') + ' bytes'});
      send({type: 'text', text: '  fields:'});
      oboolCls.fields.forEach(f => {
        if (f.isStatic) return;
        send({type: 'text', text: '    .' + f.name + ' [' + f.type.name + '] @ offset=' + f.offset});
      });
      send({type: 'text', text: '  methods:'});
      oboolCls.methods.forEach(m => {
        if (/get_Value|op_Implicit|GetDecrypted|Decrypt/.test(m.name)) {
          send({type: 'text', text: '    ' + m.returnType.name + ' ' + m.name + '(' +
            m.parameters.map(p => p.type.name + ' ' + p.name).join(', ') + ')'});
        }
      });

      // ── Instance walk ────────────────────────────────────────
      send({type: 'text', text: ''});
      send({type: 'text', text: '=== ObscuredCharaEffectLog instances ==='});
      const insts = Il2Cpp.gc.choose(logCls);
      send({type: 'text', text: 'Found ' + insts.length + ' instance(s)'});

      // Field offsets on the LOG class — need the byte offset of
      // IsActive within an instance so we can point at the inline
      // struct bytes.
      const isActiveOffset = isActiveField.offset;
      const charaIdField = logCls.fields.find(f => f.name === '<CharaEffectId>k__BackingField');
      const charaIdOffset = charaIdField ? charaIdField.offset : null;
      send({type: 'text', text: 'IsActive field offset within instance: ' + isActiveOffset});
      send({type: 'text', text: 'CharaEffectId offset: ' + charaIdOffset});

      insts.forEach((inst, i) => {
        send({type: 'text', text: ''});
        send({type: 'text', text: '── instance #' + i + ' @ ' + inst.handle + ' ──'});
        // Dump full IsActive struct bytes (20 bytes is safe upper bound)
        const structPtr = inst.handle.add(isActiveOffset);
        const bytes = [];
        for (let b = 0; b < 20; b++) {
          bytes.push(structPtr.add(b).readU8().toString(16).padStart(2, '0'));
        }
        send({type: 'text', text: '  IsActive raw bytes @ off ' + isActiveOffset + ':'});
        send({type: 'text', text: '    ' + bytes.join(' ')});
        // Named field values for clarity
        oboolCls.fields.forEach(f => {
          if (f.isStatic) return;
          const p = structPtr.add(f.offset - isActiveOffset >= 0 ? 0 : 0);  // NOT used; use inst.field path
        });
        // Read specific interesting bytes:
        //   currentCryptoKey @ +offset (u8)
        //   hiddenValue @ +offset (i32)
        //   inited/fakeValue/fakeValueActive @ +offset (bool = u8)
        oboolCls.fields.forEach(f => {
          if (f.isStatic) return;
          const at = structPtr.add(f.offset);
          let val;
          try {
            switch (f.type.name) {
              case 'System.Byte': val = at.readU8(); break;
              case 'System.SByte': val = at.readS8(); break;
              case 'System.Int32': val = at.readS32(); break;
              case 'System.UInt32': val = at.readU32(); break;
              case 'System.Boolean': val = at.readU8() !== 0; break;
              default: val = '?type=' + f.type.name;
            }
          } catch (e) { val = '<read err>'; }
          send({type: 'text', text: '    .' + f.name + ' [' + f.type.name + '] = ' + val});
        });
        // Try calling get_Value if it exists — via boxed struct
        try {
          const structVal = inst.field('<IsActive>k__BackingField').value;
          if (structVal.method) {
            const getV = structVal.class.methods.find(m => m.name === 'get_Value');
            if (getV) {
              const result = getV.invoke.call(structVal);
              send({type: 'text', text: '    get_Value() => ' + result});
            } else {
              send({type: 'text', text: '    (no get_Value method found)'});
            }
          } else {
            send({type: 'text', text: '    (structVal has no .method)'});
          }
        } catch (e) {
          send({type: 'text', text: '    get_Value() FAILED: ' + e.message});
        }
      });

      send({type: 'done'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 500);
"""


def _find_pid() -> int | None:
    import frida
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == PROCESS_NAME.lower():
            return proc.pid
    return None


def main() -> int:
    if not BRIDGE_JS.exists():
        print(f"[X] {BRIDGE_JS} missing — run `python setup.py` first")
        return 1
    try:
        import frida
    except ImportError:
        print("[X] frida not installed — `pip install frida`")
        return 1

    pid = _find_pid()
    if pid is None:
        print(f"[X] no {PROCESS_NAME} process found — launch the game first")
        return 1
    print(f"[+] attaching to PID {pid}")

    done = {"flag": False}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "text":
                print(payload["text"])
            elif t == "done":
                print()
                print("[+] scout complete")
                done["flag"] = True
            elif t == "fatal":
                print(f"[X] agent error: {payload.get('err')}")
                print(payload.get("stack", ""))
                done["flag"] = True
        elif msg["type"] == "error":
            print(f"[X] JS runtime error: {msg.get('description')}")
            done["flag"] = True

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()

    deadline = time.time() + 30
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] scout didn't finish within 30s")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
