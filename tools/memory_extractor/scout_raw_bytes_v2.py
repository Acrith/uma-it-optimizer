"""Raw byte capture v2 — hook the non-generic lower-level methods.

Earlier attempt failed because `MessagePackSerializer.Deserialize<T>`
is a generic template at address 0x7ffc9e097490 — after IL2CPP JIT,
each specialized <T> gets its own address, and the template address
never actually runs.

This script hooks methods with UNIQUE (non-shared) addresses that
ARE called for every deserialization:

  - Gallop.CryptAES.Decrypt(byte[]) — game's AES decrypt; output is
    still LZ4-compressed but at least it's every response
  - LZ4MessagePackSerializer.Decode(byte[]) — LZ4-decompress step;
    output is plaintext MessagePack ready to decode
  - LZ4MessagePackSerializer.Decode(ArraySegment<byte>) — same
  - LZ4MessagePackSerializer.DecodeUnsafe(byte[]) — faster path
  - LZ4MessagePackSerializer.DecodeUnsafe(ArraySegment<byte>) — same

For each hook, we capture the INPUT byte[] (onEnter) and OUTPUT byte[]
(onLeave). Whichever path the game uses, we catch the payload before
it enters the typed-DTO decoder.

Output: one .msgpack file per capture in --outdir, named with:
  raw_<seq>_<method-tag>_<in|out>_<size>b.msgpack
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
      const mp = Il2Cpp.domain.assembly('MessagePack').image;
      const uma = Il2Cpp.domain.assembly('umamusume').image;

      // Il2CppArray layout (SZARRAY of byte on 64-bit):
      //   +0   klass pointer
      //   +16  bounds
      //   +24  length (uint32)
      //   +32  data start
      function readByteArray(arrPtr) {
        if (!arrPtr || arrPtr.isNull()) return null;
        let length;
        try { length = arrPtr.add(24).readU32(); }
        catch (e) { return null; }
        if (length <= 0 || length > 32 * 1024 * 1024) return null;
        try {
          const bytes = arrPtr.add(32).readByteArray(length);
          return { length: length, bytes: bytes };
        } catch (e) { return null; }
      }

      // ArraySegment<byte> struct layout (16 bytes):
      //   +0   byte[] Array (pointer)
      //   +8   int Offset
      //   +12  int Count
      // Passed by value on Windows x64 = via pointer to stack slot.
      function readByteArraySegment(segPtr) {
        if (!segPtr || segPtr.isNull()) return null;
        try {
          const arrPtr = segPtr.readPointer();
          const offset = segPtr.add(8).readU32();
          const count = segPtr.add(12).readU32();
          if (arrPtr.isNull() || count <= 0 || count > 32 * 1024 * 1024) return null;
          const bytes = arrPtr.add(32 + offset).readByteArray(count);
          return { length: count, bytes: bytes };
        } catch (e) { return null; }
      }

      let seq = 0;

      function attachHook(klassName, methodName, methodFilter, tag, inputExtractor) {
        let klass;
        try {
          if (klassName.startsWith('Gallop.')) klass = uma.class(klassName);
          else klass = mp.class(klassName);
        } catch (e) {
          send({type: 'text', text: '[SKIP] class not found: ' + klassName});
          return;
        }
        if (!klass) { send({type: 'text', text: '[SKIP] null class: ' + klassName}); return; }
        klass.methods.forEach(m => {
          if (m.name !== methodName) return;
          if (!methodFilter(m)) return;
          const params = (m.parameters || []).map(p => (p.type && p.type.name) || '?').join(', ');
          try {
            Interceptor.attach(m.virtualAddress, {
              onEnter(args) {
                try {
                  const captured = inputExtractor(args);
                  if (!captured) {
                    send({type: 'text', text: '[.] ' + tag + ' fired but input extraction returned null'});
                    return;
                  }
                  const s = ++seq;
                  this._seq = s;
                  send({type: 'payload', seq: s, tag: tag, dir: 'in',
                        size: captured.length, params: params}, captured.bytes);
                } catch (e) {
                  send({type: 'text', text: 'onEnter err (' + tag + '): ' + e.message});
                }
              },
              onLeave(retval) {
                try {
                  const captured = readByteArray(retval);
                  if (!captured) return;  // some methods return non-byte[]
                  const s = this._seq || ++seq;
                  send({type: 'payload', seq: s, tag: tag, dir: 'out',
                        size: captured.length, params: params}, captured.bytes);
                } catch (e) {
                  send({type: 'text', text: 'onLeave err (' + tag + '): ' + e.message});
                }
              }
            });
            send({type: 'text', text: '[OK] ' + klassName + '.' + methodName + '(' + params + ') @ ' + m.virtualAddress + ' [' + tag + ']'});
          } catch (e) {
            send({type: 'text', text: '[ERR] ' + klassName + '.' + methodName + ': ' + e.message});
          }
        });
      }

      // Method filters — match by first param type to hook the right overload.
      const isByteArrayFirstParam = (m) => {
        const p = m.parameters || [];
        return p.length >= 1 && (p[0].type && p[0].type.name) === 'System.Byte[]';
      };
      const isArraySegmentFirstParam = (m) => {
        const p = m.parameters || [];
        return p.length >= 1 && (p[0].type && p[0].type.name).indexOf('ArraySegment') >= 0;
      };
      const isSingleByteArray = (m) => {
        const p = m.parameters || [];
        return p.length === 1 && (p[0].type && p[0].type.name) === 'System.Byte[]';
      };
      const isSingleArraySegment = (m) => {
        const p = m.parameters || [];
        return p.length === 1 && (p[0].type && p[0].type.name).indexOf('ArraySegment') >= 0;
      };

      // ── LZ4 decode variants (unique addresses per enum) ──
      attachHook('MessagePack.LZ4MessagePackSerializer', 'Decode',
                 isSingleByteArray, 'lz4-decode-byte',
                 (args) => readByteArray(args[0]));
      attachHook('MessagePack.LZ4MessagePackSerializer', 'Decode',
                 isSingleArraySegment, 'lz4-decode-seg',
                 (args) => readByteArraySegment(args[0]));
      attachHook('MessagePack.LZ4MessagePackSerializer', 'DecodeUnsafe',
                 isSingleByteArray, 'lz4-decodeunsafe-byte',
                 (args) => readByteArray(args[0]));
      attachHook('MessagePack.LZ4MessagePackSerializer', 'DecodeUnsafe',
                 isSingleArraySegment, 'lz4-decodeunsafe-seg',
                 (args) => readByteArraySegment(args[0]));

      // ── Game AES decrypt (byte[] variant only — String is text) ──
      attachHook('Gallop.CryptAES', 'Decrypt',
                 isByteArrayFirstParam, 'aes-decrypt-byte',
                 (args) => readByteArray(args[0]));

      send({type: 'text', text: 'installed raw-byte capture hooks'});
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=int, default=3600)
    ap.add_argument("--outdir", default="raw_dumps_v2")
    args = ap.parse_args()

    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"[+] dumping to {outdir}")

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

    counts = {"n": 0, "bytes": 0}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, arming raw hooks...")
            elif t == "text":
                print(payload["text"])
            elif t == "fatal":
                print(f"[X] agent: {payload.get('err')}")
            elif t == "payload":
                seq = payload.get("seq", 0)
                tag = payload.get("tag", "?")
                direction = payload.get("dir", "?")
                size = payload.get("size", 0)
                if data is None:
                    print(f"[!] #{seq:04d} {tag} {direction} size={size} no data")
                    return
                fname = outdir / f"raw_{seq:04d}_{tag}_{direction}_{size}b.bin"
                fname.write_bytes(data)
                counts["n"] += 1
                counts["bytes"] += size
                print(f"[+] #{seq:04d} {tag:<25} {direction:<3} {size:>8} bytes -> {fname.name}")
        elif msg["type"] == "error":
            print(f"[X] JS err: {msg.get('description')}")

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()

    print(f"[+] listening for {args.seconds}s...")
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    print(f"[+] detached; captured {counts['n']} payloads, {counts['bytes']:,} bytes total")
    session.detach()
    return 0


if __name__ == "__main__":
    sys.exit(main())
