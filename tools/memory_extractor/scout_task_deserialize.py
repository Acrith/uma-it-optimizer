"""Raw byte capture via Gallop.*Task.Deserialize hooks.

Backtrace revealed the API response chain:
    Cute.Http.HttpManager.FastUpdate
      -> Gallop.<Endpoint>Task.Deserialize      ← raw bytes go in
        -> MsgPack.Formatters.<Endpoint>ResponseFormatter.Deserialize

Every endpoint has a Task class with a Deserialize method — that's
the layer between "raw HTTP bytes" and "typed C# object." Hooking it
gives us raw bytes ONCE per response, no generic-template madness.

Only hooks Gallop.IdleSingleMode*Task classes here (the IT lifecycle
we care about). Extend by name for other endpoints.
"""
from __future__ import annotations

import argparse
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
      const uma = Il2Cpp.domain.assembly('umamusume').image;
      const http = Il2Cpp.domain.assembly('umamusume.Http').image;

      const TASK_NAMES = [
        'Gallop.IdleSingleModePreStartTask',
        'Gallop.IdleSingleModeStartTask',
        'Gallop.IdleSingleModeStatusTask',
        'Gallop.IdleSingleModeCheckProgressLogTask',
        'Gallop.IdleSingleModeEndTask',
        'Gallop.IdleSingleModeResultTask',
      ];

      function readByteArray(arrPtr) {
        if (!arrPtr || arrPtr.isNull()) return null;
        let length;
        try { length = arrPtr.add(24).readU32(); } catch (e) { return null; }
        if (length <= 0 || length > 32 * 1024 * 1024) return null;
        try { return { length: length, bytes: arrPtr.add(32).readByteArray(length) }; }
        catch (e) { return null; }
      }

      function findClass(name) {
        try { const k = uma.class(name); if (k) return k; } catch (e) {}
        try { const k = http.class(name); if (k) return k; } catch (e) {}
        return null;
      }

      let seq = 0;
      TASK_NAMES.forEach(fqn => {
        const klass = findClass(fqn);
        if (!klass) { send({type: 'text', text: '[SKIP] ' + fqn}); return; }
        klass.methods.forEach(m => {
          if (m.name !== 'Deserialize') return;
          const params = m.parameters || [];
          const sig = params.map(p => (p.type && p.type.name) || '?').join(', ');
          const tag = fqn.split('.').pop();
          try {
            Interceptor.attach(m.virtualAddress, {
              onEnter(args) {
                try {
                  // For instance methods (non-static): args[0] = this,
                  // args[1] = first C# param. For static, args[0] is first.
                  // Try args[1] first (assume instance method), fall back to args[0].
                  let captured = readByteArray(args[1]);
                  let which = 'args[1]';
                  if (!captured) {
                    captured = readByteArray(args[0]);
                    which = 'args[0]';
                  }
                  if (!captured) {
                    send({type: 'text', text: '[.] ' + tag + '.Deserialize fired but no byte[] found in args[0]/[1] (sig: ' + sig + ')'});
                    return;
                  }
                  const s = ++seq;
                  send({type: 'payload', seq: s, tag: tag, size: captured.length,
                        sig: sig, argix: which}, captured.bytes);
                } catch (e) {
                  send({type: 'text', text: 'onEnter err (' + tag + '): ' + e.message});
                }
              }
            });
            send({type: 'text', text: '[OK] ' + fqn + '.Deserialize(' + sig + ') @ ' + m.virtualAddress});
          } catch (e) {
            send({type: 'text', text: '[ERR] ' + fqn + '.Deserialize: ' + e.message});
          }
        });
      });
      send({type: 'text', text: 'installed task-deserialize hooks'});
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=3600)
    ap.add_argument("--outdir", default="raw_tasks")
    args = ap.parse_args()

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[+] dumping to {outdir}")

    if not BRIDGE_JS.exists(): print(f"[X] {BRIDGE_JS} missing"); return 1
    try: import frida
    except ImportError: print("[X] frida not installed"); return 1
    pid = _find_pid()
    if pid is None: print(f"[X] no {PROCESS_NAME}"); return 1
    print(f"[+] attaching to PID {pid}")

    counts = {"n": 0, "bytes": 0}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, arming task-deserialize hooks...")
            elif t == "text":
                print(payload["text"])
            elif t == "fatal":
                print(f"[X] {payload.get('err')}")
            elif t == "payload":
                seq = payload.get("seq", 0)
                tag = payload.get("tag", "?")
                size = payload.get("size", 0)
                argix = payload.get("argix", "?")
                if data is None:
                    print(f"[!] #{seq} {tag} size={size} no data"); return
                fname = outdir / f"task_{seq:04d}_{tag}_{argix}_{size}b.bin"
                fname.write_bytes(data)
                counts["n"] += 1; counts["bytes"] += size
                print(f"[+] #{seq:04d} {tag:<40} {size:>8}b [{argix}] -> {fname.name}")
        elif msg["type"] == "error":
            print(f"[X] JS: {msg.get('description')}")

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()
    print(f"[+] listening for {args.seconds}s...")
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline: time.sleep(0.2)
    except KeyboardInterrupt: pass
    print(f"[+] detached; {counts['n']} payloads, {counts['bytes']:,} bytes")
    session.detach()
    return 0


if __name__ == "__main__":
    sys.exit(main())
