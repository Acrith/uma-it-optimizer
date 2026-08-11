"""Locate MessagePackSerializer.Deserialize entry points to hook for raw
byte capture. Cheap name/method enumeration only — no gc.choose, no
game freeze.

Goal: find a Deserialize overload that takes `byte[]` (or similar) as
input. Hooking that gives us the RAW MessagePack payload BEFORE it's
decoded to a typed C# object — which lets us schema-less decode with
Python's msgpack library and look for ext values / unknown keys the
generated Gallop DTOs might silently drop.
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
      send({type: 'init'});
      // Try every assembly loaded — MessagePack may be in its own
      // assembly, in umamusume.Http, or elsewhere.
      const assemblies = Il2Cpp.domain.assemblies;
      send({type: 'text', text: 'assemblies: ' + assemblies.length});

      const targets = [];
      assemblies.forEach(a => {
        try {
          const img = a.image;
          img.classes.forEach(k => {
            const n = (k.type && k.type.name) || '';
            // Grab MessagePack-related classes broadly.
            if (/MessagePack(Serializer|Reader)|MsgPackSerializer/i.test(n)) {
              targets.push({ asm: a.name, klass: k, name: n });
            }
          });
        } catch (e) {}
      });

      send({type: 'header', text: '=== MESSAGEPACK SERIALIZER CLASSES ==='});
      targets.forEach(({ asm, name }) => {
        send({type: 'text', text: '  [' + asm + '] ' + name});
      });

      send({type: 'header', text: '=== METHODS OF INTEREST ==='});
      targets.forEach(({ asm, klass, name }) => {
        try {
          klass.methods.forEach(m => {
            if (!/Deserialize/i.test(m.name)) return;
            // Show method signature by listing param types.
            const params = m.parameters || [];
            const sig = params.map(p => (p.type && p.type.name) || '?').join(', ');
            send({type: 'text', text: '  [' + asm + '] ' + name + '.' + m.name + '(' + sig + ')'});
          });
        } catch (e) {
          send({type: 'text', text: '  [' + asm + '] ' + name + ' — method enum err: ' + e.message});
        }
      });

      send({type: 'done'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 300);
"""


def _find_pid() -> int | None:
    import frida
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == PROCESS_NAME.lower():
            return proc.pid
    if sys.platform.startswith("linux"):
        from dump_it_run import _find_wine_hosted_process_pid
        return _find_wine_hosted_process_pid()
    return None


def main() -> int:
    if not BRIDGE_JS.exists():
        print(f"[X] {BRIDGE_JS} missing"); return 1
    try:
        import frida
    except ImportError:
        print("[X] frida not installed"); return 1
    pid = _find_pid()
    if pid is None:
        print(f"[X] no {PROCESS_NAME} process found"); return 1
    print(f"[+] attaching to PID {pid}")

    done = {"flag": False}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, scanning MessagePack surface...")
            elif t == "header":
                print(); print(payload["text"])
            elif t == "text":
                print(payload["text"])
            elif t == "done":
                print(); print("[+] done")
                done["flag"] = True
            elif t == "fatal":
                print(f"[X] agent error: {payload.get('err')}")
                done["flag"] = True
        elif msg["type"] == "error":
            print(f"[X] JS runtime error: {msg.get('description')}")
            done["flag"] = True

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()
    deadline = time.time() + 60
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] didn't finish")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
