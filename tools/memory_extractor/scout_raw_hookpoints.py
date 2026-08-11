"""Enumerate every viable raw-byte hook point for MessagePack capture.

Goal: find methods with FIXED (non-generic) addresses that we can hook
to catch raw plaintext MessagePack bytes for every API response.

Categories scanned:
- MessagePack.LZ4MessagePackSerializer.DeserializeCore  — non-generic
  helper called by all Deserialize<T> after LZ4 decompression.
- MessagePack.MessagePackSerializer.DeserializeCore     — same for non-LZ4.
- MessagePack.MessagePackReader constructors            — invoked per read.
- MessagePack.MessagePackBinary.* static readers.
- Any Gallop.*Cryptor / Gallop.*WebApi* / Gallop.*Http* class methods
  that plausibly emit plaintext bytes.

Cheap name/method enumeration — no gc.choose, no game freeze.
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
      const assemblies = Il2Cpp.domain.assemblies;
      const targets = {
        mp: [],       // MessagePack lib classes
        gallop_crypt: [],
        gallop_http: [],
      };

      assemblies.forEach(a => {
        try {
          const img = a.image;
          img.classes.forEach(k => {
            const n = (k.type && k.type.name) || '';
            if (/^MessagePack\.(MessagePackSerializer|LZ4MessagePackSerializer|MessagePackReader|MessagePackBinary)/.test(n)) {
              targets.mp.push({ asm: a.name, klass: k, name: n });
            }
            if (/^Gallop\./.test(n) && /Cryptor|Cipher|Crypt|Decrypt|Encrypt/i.test(n)) {
              targets.gallop_crypt.push({ asm: a.name, klass: k, name: n });
            }
            if (/^Gallop\.(WebApi|WebRequest|HttpClient|HttpRequest|HttpResponse|ApiManager|CommonApiManager|WebSender|WebReceiver)/.test(n)) {
              targets.gallop_http.push({ asm: a.name, klass: k, name: n });
            }
          });
        } catch (e) {}
      });

      // Method filter — hookable methods that plausibly touch raw bytes.
      const RE = /(DeserializeCore|Deserialize$|Read$|ReadRaw|ReadBytes|OnReceive|HandleResponse|ProcessResponse|Decrypt|Decode|OnComplete|SetBuffer)/i;

      function dumpMethods(bucket, header) {
        send({type: 'header', text: '=== ' + header + ' (' + bucket.length + ' classes) ==='});
        bucket.forEach(({ asm, klass, name }) => {
          try {
            klass.methods.forEach(m => {
              if (!RE.test(m.name)) return;
              const params = m.parameters || [];
              const sig = params.map(p => (p.type && p.type.name) || '?').join(', ');
              send({type: 'text', text: '  [' + asm + '] ' + name + '.' + m.name + '(' + sig + ') @ ' + m.virtualAddress});
            });
          } catch (e) {}
        });
      }

      dumpMethods(targets.mp, 'MESSAGEPACK LIBRARY');
      dumpMethods(targets.gallop_crypt, 'GALLOP CRYPTO');
      dumpMethods(targets.gallop_http, 'GALLOP HTTP LAYER');

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
                print("[+] IL2CPP ready, enumerating raw-byte hook candidates...")
            elif t == "header":
                print(); print(payload["text"])
            elif t == "text":
                print(payload["text"])
            elif t == "done":
                print(); print("[+] done")
                done["flag"] = True
            elif t == "fatal":
                print(f"[X] agent: {payload.get('err')}"); done["flag"] = True
        elif msg["type"] == "error":
            print(f"[X] JS err: {msg.get('description')}"); done["flag"] = True

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()
    deadline = time.time() + 60
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
