"""Backtrace scout — when a known-firing formatter hook triggers, dump
the call stack so we see which methods route from network bytes to
the typed decoder. That tells us WHERE to hook for raw byte capture,
instead of guessing.
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
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;
      // Pick a formatter guaranteed to fire on any API status/response.
      // Status is best because it fires whenever the user opens IT screen.
      const targets = [
        'Gallop.MsgPack.Formatters.IdleSingleModeStatusResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeStartResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeEndResponseFormatter',
      ];
      let count = 0;
      targets.forEach(fqn => {
        let klass;
        try { klass = httpImg.class(fqn); } catch (e) {}
        if (!klass) { send({type: 'text', text: '[SKIP] ' + fqn}); return; }
        klass.methods.forEach(m => {
          if (m.name !== 'Deserialize') return;
          try {
            const targetName = fqn.split('.').pop();
            Interceptor.attach(m.virtualAddress, {
              onEnter(args) {
                try {
                  send({type: 'header', text: '=== HOOK FIRED: ' + targetName + ' ==='});
                  const bt = Thread.backtrace(this.context, Backtracer.ACCURATE);
                  // Build address → Il2Cpp method name lookup on first fire.
                  if (!globalThis.__methodByAddr) {
                    send({type: 'text', text: '(building il2cpp address→method index once...)'});
                    const idx = new Map();
                    let n = 0;
                    Il2Cpp.domain.assemblies.forEach(a => {
                      try {
                        a.image.classes.forEach(k => {
                          try {
                            k.methods.forEach(m => {
                              try {
                                const va = m.virtualAddress;
                                if (!va.isNull()) {
                                  const key = va.toString();
                                  const kn = (k.type && k.type.name) || k.name || '?';
                                  if (!idx.has(key)) idx.set(key, kn + '.' + m.name);
                                  n++;
                                }
                              } catch (e) {}
                            });
                          } catch (e) {}
                        });
                      } catch (e) {}
                    });
                    globalThis.__methodByAddr = idx;
                    send({type: 'text', text: '(indexed ' + n + ' methods, ' + idx.size + ' unique addresses)'});
                  }
                  const idx = globalThis.__methodByAddr;
                  bt.forEach((addr, i) => {
                    const sym = DebugSymbol.fromAddress(addr).toString();
                    // Try to find nearest il2cpp method at or below this address.
                    // Since IL2CPP method addresses are function entries, look up direct.
                    const direct = idx.get(addr.toString());
                    if (direct) {
                      send({type: 'text', text: '  [' + i + '] ' + addr + '  ' + direct + '  (' + sym + ')'});
                    } else {
                      // Nearest-below lookup — iterate all keys, find largest <= addr
                      let best = null, bestVal = null;
                      const target = parseInt(addr.toString(), 16);
                      idx.forEach((v, k) => {
                        const ka = parseInt(k, 16);
                        if (ka <= target && (best === null || ka > best)) {
                          best = ka; bestVal = v;
                        }
                      });
                      if (best !== null) {
                        const delta = target - best;
                        if (delta < 0x2000) {  // within reasonable function size
                          send({type: 'text', text: '  [' + i + '] ' + addr + '  ' + bestVal + ' +0x' + delta.toString(16) + '  (' + sym + ')'});
                          return;
                        }
                      }
                      send({type: 'text', text: '  [' + i + '] ' + addr + '  (' + sym + ')'});
                    }
                  });
                } catch (e) {
                  send({type: 'text', text: 'backtrace err: ' + e.message});
                }
              }
            });
            count++;
            send({type: 'text', text: '[OK] observing ' + fqn + '.Deserialize @ ' + m.virtualAddress});
          } catch (e) { send({type: 'text', text: '[ERR] ' + fqn + ': ' + e.message}); }
        });
      });
      send({type: 'text', text: 'installed ' + count + ' backtrace hook(s); trigger a Status/Start/End response...'});
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

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, arming backtrace hooks...")
            elif t == "header":
                print(); print(payload["text"])
            elif t == "text":
                print(payload["text"])
            elif t == "fatal":
                print(f"[X] agent: {payload.get('err')}")
        elif msg["type"] == "error":
            print(f"[X] JS err: {msg.get('description')}")

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()

    print("[+] listening 5 min — trigger a Status/Start/End response by opening IT screen or waiting for IT tick")
    time.sleep(300)
    session.detach()
    return 0


if __name__ == "__main__":
    sys.exit(main())
