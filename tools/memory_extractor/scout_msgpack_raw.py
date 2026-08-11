"""Raw MessagePack payload capture — hook LZ4MessagePackSerializer.Deserialize
onEnter, grab the byte[] arg, dump to disk.

Cygames compresses API responses with LZ4-MessagePack. Hooking the
deserializer's byte[] input gives us the raw payload BEFORE it's
decoded into typed C# DTOs. If the game's generated Gallop classes
silently drop unknown keys or extension values, those would appear
in the raw bytes but NOT in the typed object we captured earlier.

Output: one .msgpack file per hooked call, in --outdir. Filename
carries a monotonic index + timestamp + size for correlation with
the response-formatter hook fires we're catching in parallel.

Usage:
    python scout_msgpack_raw.py --seconds 3600 --outdir raw_dumps

Then schema-less decode each .msgpack with the Python util in
independent_training_research_handoff.md §17.
"""
from __future__ import annotations

import argparse
import struct
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
      const mpAsm = Il2Cpp.domain.assembly('MessagePack');
      const mpImg = mpAsm.image;
      const lz4 = mpImg.class('MessagePack.LZ4MessagePackSerializer');
      const std = mpImg.class('MessagePack.MessagePackSerializer');
      if (!lz4 || !std) {
        send({type: 'fatal', err: 'MessagePack serializer classes not found'});
        return;
      }

      // Il2CppArray memory layout (assuming standard 64-bit):
      //   +0   klass pointer
      //   +16  bounds/length (varies)
      //   +24  length (uint32 for SZARRAY)
      //   +32  data start
      // We only need length + data-start.
      function readByteArrayFromIl2CppArray(arrPtr) {
        if (arrPtr.isNull()) return null;
        const length = arrPtr.add(24).readU32();
        if (length <= 0 || length > 20 * 1024 * 1024) return null;  // 20MB sanity cap
        const bytes = arrPtr.add(32).readByteArray(length);
        return { length: length, bytes: bytes };
      }

      let hookCount = 0;
      let callSeq = 0;
      const seenAddrs = new Set();  // avoid double-hooking shared method addresses

      // Hook every Deserialize overload whose FIRST param is byte[].
      // Covers: (byte[]), (byte[], resolver), and (byte[], int, resolver, int&).
      // The 4-arg variant is the one that takes an offset — likely used
      // by the game's network path to skip a 1-byte compression header.
      // Hook every Deserialize on both serializers regardless of arg
      // type. onEnter tries to read args[0] as a byte[] first, then as
      // an ArraySegment (struct with byte[] at +0). If neither works,
      // we still LOG the fire so we know which overload the game hits.
      [
        { klass: lz4, tag: 'lz4' },
        { klass: std, tag: 'std' },
      ].forEach(({ klass, tag }) => {
        klass.methods.forEach(m => {
          if (m.name !== 'Deserialize') return;
          const addr = m.virtualAddress.toString();
          if (seenAddrs.has(addr)) return;
          seenAddrs.add(addr);
          const params = m.parameters || [];
          const sig = params.map(p => (p.type && p.type.name) || '?').join(', ');
          const p0 = (params[0] && params[0].type && params[0].type.name) || '';
          try {
            Interceptor.attach(m.virtualAddress, {
              onEnter(args) {
                try {
                  const seq = ++callSeq;
                  // Try byte[] direct read.
                  let captured = readByteArrayFromIl2CppArray(args[0]);
                  // Try ArraySegment<byte> — struct { byte[] Array; int Offset; int Count; }
                  // Passed by value; args[0] is a pointer to the stack slot.
                  if (!captured && p0.indexOf('ArraySegment') >= 0) {
                    try {
                      const arrPtr = args[0].readPointer();
                      const offset = args[0].add(8).readU32();
                      const count = args[0].add(12).readU32();
                      const inner = readByteArrayFromIl2CppArray(arrPtr);
                      if (inner) {
                        // Slice to (offset, offset+count)
                        const bytes = arrPtr.add(32 + offset).readByteArray(count);
                        captured = { length: count, bytes: bytes };
                      }
                    } catch (e) {
                      send({type: 'text', text: 'seg-parse err: ' + e.message});
                    }
                  }
                  if (!captured) {
                    send({type: 'firetag', tag: tag, seq: seq, sig: sig,
                          note: 'called but no bytes extracted'});
                    return;
                  }
                  send({type: 'payload', tag: tag, seq: seq, size: captured.length,
                        sig: sig}, captured.bytes);
                } catch (e) {
                  send({type: 'text', text: 'onEnter err (' + tag + '): ' + e.message});
                }
              }
            });
            hookCount++;
            send({type: 'text', text: '[OK] ' + klass.type.name + '.Deserialize(' + sig + ') @ ' + m.virtualAddress + ' [' + tag + ']'});
          } catch (e) {
            send({type: 'text', text: '[ERR] ' + klass.type.name + '.Deserialize(' + sig + '): ' + e.message});
          }
        });
      });
      send({type: 'text', text: 'installed ' + hookCount + ' raw-byte capture hook(s)'});
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
    ap.add_argument("--outdir", default="raw_dumps",
                    help="Where to write captured .msgpack files")
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

    captured_count = {"n": 0, "bytes": 0}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, hooking raw byte serializer...")
            elif t == "text":
                print(payload["text"])
            elif t == "fatal":
                print(f"[X] agent: {payload.get('err')}")
            elif t == "nobytes":
                print(f"[.] call #{payload.get('seq')} ({payload.get('tag')}) — null/invalid byte[]")
            elif t == "firetag":
                print(f"[!] call #{payload.get('seq')} ({payload.get('tag')}) sig=[{payload.get('sig')}] — {payload.get('note')}")
            elif t == "payload":
                seq = payload.get("seq", 0)
                tag = payload.get("tag", "?")
                size = payload.get("size", 0)
                if data is None:
                    print(f"[!] call #{seq} ({tag}) size={size} but no data")
                    return
                fname = outdir / f"call_{seq:04d}_{tag}_{int(time.time())}_{size}b.msgpack"
                fname.write_bytes(data)
                captured_count["n"] += 1
                captured_count["bytes"] += size
                print(f"[+] call #{seq} ({tag}) — {size} bytes -> {fname.name}")
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
    print(f"[+] detaching; captured {captured_count['n']} payloads, "
          f"{captured_count['bytes']:,} bytes total")
    session.detach()
    return 0


if __name__ == "__main__":
    sys.exit(main())
