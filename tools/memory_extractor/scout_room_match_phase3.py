"""Phase 3 scout: walk the object graph reachable from
Gallop.WorkRoomMatchData._savedRaceResultInfo, which phase 2 confirmed
is a live pointer to the saved race result payload.

This mirrors what an extractor would do — find the WorkRoomMatchData
singleton, dereference _savedRaceResultInfo, and dump the whole
structure so we can see if it contains every participant's
uma / factors / skills / times we need for umaladder.moe.

Also dumps _currentRoomData (room metadata: weather, track,
distance, etc.) and _currentRoomUserList (per-participant player
metadata).

Run while on the Room Match result screen.
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

      const WRM = mainImg.class('Gallop.WorkRoomMatchData');
      const instances = Il2Cpp.gc.choose(WRM);
      if (!instances || instances.length === 0) {
        send({type: 'text', text: '[X] no WorkRoomMatchData instances'});
        send({type: 'done'});
        return;
      }
      send({type: 'text', text: '[+] found ' + instances.length + ' WorkRoomMatchData'});
      const wrm = instances[0];

      // ─── Helper: dump one object's fields (one level) ─────
      function dumpFields(obj, indent, depthLeft, maxArrayItems) {
        const pad = ' '.repeat(indent);
        if (!obj) { send({type: 'text', text: pad + '(null)'}); return; }
        if (!obj.class || !obj.class.fields) {
          send({type: 'text', text: pad + '(no fields)'});
          return;
        }
        obj.class.fields.forEach(f => {
          if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
          const tname = (f.type && f.type.name) || '?';
          let v;
          try { v = obj.field(f.name).value; }
          catch (e) {
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = <err: ' + e.message + '>'});
            return;
          }
          if (v === null || v === undefined) {
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = null'});
            return;
          }
          if (typeof v === 'number' || typeof v === 'boolean') {
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = ' + v});
            return;
          }
          if (typeof v === 'string') {
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = ' + JSON.stringify(v)});
            return;
          }
          if (v.content !== undefined) {  // Il2Cpp.String
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = ' + JSON.stringify(v.content)});
            return;
          }
          if (v.length !== undefined) {  // array
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = <array len=' + v.length + '>'});
            if (depthLeft > 0 && v.length > 0 && v.length <= 32) {
              const N = Math.min(maxArrayItems, v.length);
              for (let i = 0; i < N; i++) {
                let e0;
                try { e0 = v.get(i); }
                catch (e) { continue; }
                if (e0 && e0.class && e0.class.type) {
                  send({type: 'text', text: pad + '  [' + i + '] <' + e0.class.type.name + '>'});
                  dumpFields(e0, indent + 4, depthLeft - 1, maxArrayItems);
                } else if (typeof e0 === 'number' || typeof e0 === 'string' || typeof e0 === 'boolean') {
                  send({type: 'text', text: pad + '  [' + i + '] = ' + JSON.stringify(e0)});
                }
              }
            }
            return;
          }
          if (v.class && v.class.type) {
            send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = <' + v.class.type.name + '>'});
            if (depthLeft > 0) dumpFields(v, indent + 2, depthLeft - 1, maxArrayItems);
            return;
          }
          send({type: 'text', text: pad + '.' + f.name + ' [' + tname + '] = <' + typeof v + '>'});
        });
      }

      // ─── SavedRaceResultInfo — the main prize ─────────────
      send({type: 'header', text: '=== _savedRaceResultInfo ==='});
      let saved;
      try { saved = wrm.field('_savedRaceResultInfo').value; }
      catch (e) { send({type: 'text', text: 'read err: ' + e.message}); saved = null; }
      if (!saved) send({type: 'text', text: '(null pointer)'});
      else {
        send({type: 'text', text: 'class = ' + (saved.class && saved.class.type && saved.class.type.name)});
        // Depth 2 with 12 items per array — we expect a list of ~12 runners
        dumpFields(saved, 2, 2, 12);
      }

      // ─── CurrentRoomData — room metadata ──────────────────
      send({type: 'header', text: '=== _currentRoomData ==='});
      let room;
      try { room = wrm.field('_currentRoomData').value; }
      catch (e) { send({type: 'text', text: 'read err: ' + e.message}); room = null; }
      if (!room) send({type: 'text', text: '(null pointer)'});
      else {
        send({type: 'text', text: 'class = ' + (room.class && room.class.type && room.class.type.name)});
        dumpFields(room, 2, 2, 12);
      }

      // ─── CurrentRoomUserList — per-participant player info ─
      send({type: 'header', text: '=== _currentRoomUserList ==='});
      let userList;
      try { userList = wrm.field('_currentRoomUserList').value; }
      catch (e) { send({type: 'text', text: 'read err: ' + e.message}); userList = null; }
      if (!userList) send({type: 'text', text: '(null pointer)'});
      else {
        // List<UserData> — has an internal _items array. Try both.
        let count = 0;
        try {
          const size = userList.field('_size').value;
          count = size;
          send({type: 'text', text: 'List<>._size = ' + size});
        } catch (e) {
          send({type: 'text', text: '_size read err: ' + e.message});
        }
        try {
          const items = userList.field('_items').value;
          if (items && items.length !== undefined) {
            send({type: 'text', text: '_items len = ' + items.length + ' (used ' + count + ')'});
            const N = Math.min(count || items.length, 12);
            for (let i = 0; i < N; i++) {
              const u = items.get(i);
              if (!u) { send({type: 'text', text: '  [' + i + '] null'}); continue; }
              send({type: 'text', text: '  [' + i + '] ' + (u.class && u.class.type && u.class.type.name)});
              dumpFields(u, 4, 1, 4);
            }
          }
        } catch (e) {
          send({type: 'text', text: '_items read err: ' + e.message});
        }
      }

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
    if sys.platform.startswith("linux"):
        from dump_it_run import _find_wine_hosted_process_pid
        return _find_wine_hosted_process_pid()
    return None


def main() -> int:
    if not BRIDGE_JS.exists():
        print(f"[X] {BRIDGE_JS} missing")
        return 1
    try:
        import frida
    except ImportError:
        print("[X] frida not installed")
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
                print("[+] IL2CPP ready")
            elif t == "header":
                print()
                # Replace unicode arrows to avoid cp1252 issues on Windows console.
                print(payload["text"].encode("ascii", "replace").decode("ascii"))
            elif t == "text":
                print(payload["text"].encode("ascii", "replace").decode("ascii"))
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

    deadline = time.time() + 60
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] scout didn't finish within 60s")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
