"""Tiny scout: dump Gallop.SingleModeDefine.CommandType enum members.

Static metadata read — no gc.choose, no game freeze. Just enumerates
the enum's declared fields (each is a static const int) and prints
name+value. Also dumps any adjacent enums we spot (FacilityType,
TurnPeriod, etc.).
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
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;

      // Enum classes to dump. Add more here as we discover them.
      const ENUMS = [
        'Gallop.SingleModeDefine.CommandType',
        'Gallop.SingleModeDefine.TurnPeriod',
        'Gallop.SingleModeDefine.EventContentsInfoType',
        'Gallop.SingleModeDefine.TrainingEventType',
        'Gallop.SingleModeDefine.CharaEffectType',
        'Gallop.SingleModeDefine.ParameterGainLimitType',
      ];

      // Nested types in il2cpp use '+' or '/' separator in the metadata
      // — bridge accepts either shape depending on version. Try dotted
      // (the source form), plus-separated, then hunt via image.classes.
      function findClass(name) {
        // First try direct.
        try { const k = mainImg.class(name); if (k) return k; } catch (e) {}
        // Try with + between outer + inner (last dot).
        const parts = name.split('.');
        const outer = parts.slice(0, -1).join('.');
        const inner = parts[parts.length - 1];
        try { const k = mainImg.class(outer + '+' + inner); if (k) return k; } catch (e) {}
        try { const k = mainImg.class(outer + '/' + inner); if (k) return k; } catch (e) {}
        // Last resort — scan the image.
        let found = null;
        mainImg.classes.forEach(k => {
          const n = (k.type && k.type.name) || '';
          if (n === name || n.replace('+', '.').replace('/', '.') === name) {
            found = k;
          }
        });
        return found;
      }

      ENUMS.forEach(name => {
        send({type: 'header', text: '=== ' + name + ' ==='});
        const klass = findClass(name);
        if (!klass) { send({type: 'text', text: '  (not found)'}); return; }
        try {
          klass.fields.forEach(f => {
            // Enum members are `static literal` int fields; skip the
            // implicit __value backing field.
            if (!f.isLiteral) return;
            if (f.name === 'value__') return;
            let val;
            try { val = f.value; } catch (e) { val = '?'; }
            send({type: 'text', text: '  ' + String(val).padStart(6) + '  ' + f.name});
          });
        } catch (e) {
          send({type: 'text', text: '  (enumeration failed: ' + e.message + ')'});
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
        print(f"[X] {BRIDGE_JS} missing — run `python setup.py` first")
        return 1
    try:
        import frida
    except ImportError:
        print("[X] frida not installed — `pip install frida frida-tools`")
        return 1

    pid = _find_pid()
    if pid is None:
        print(f"[X] no {PROCESS_NAME} process found")
        return 1
    print(f"[+] attaching to PID {pid}")

    done = {"flag": False}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, dumping enums...")
            elif t == "header":
                print()
                print(payload["text"])
            elif t == "text":
                print(payload["text"])
            elif t == "done":
                print()
                print("[+] enum dump complete")
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
        print("[X] enum dump didn't finish in 30s")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
