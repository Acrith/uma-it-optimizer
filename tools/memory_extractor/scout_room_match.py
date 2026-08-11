"""One-off scouting script: find where Room Match result data lives in
IL2CPP memory (per-runner uma, factors, skills, positions, times).

Run this while the game is sitting on the Room Match result screen —
the multi-player result page showing 12 finishers with names, positions,
times, running style, and favorite rank. Data likely lives only while
this screen is up; back out and the object refs may drop.

Two-phase to avoid the wide-gc.choose freeze:

1. Metadata walk — enumerate all IL2CPP classes matching
   /RoomMatch|TeamStadium|RaceResult|RaceInfo|RaceHorse|RaceScheme|
    RaceParameter|Nikkanken/i. Just reads type metadata, sub-second,
    no heap access.
2. Targeted gc.choose — for each shortlisted class ONLY, count live
   instances + dump first-instance field structure. Emits a heartbeat
   before each scan so a hang shows which class is the culprit.

Prereqs:
- Game running with the Room Match RESULT screen open (12 finishers
  visible, "Save to My Runners" / "Next" buttons at the bottom).
- ``vendor/il2cpp_bridge.js`` populated (run ``setup.py`` once if not).
- Frida installed (``pip install frida frida-tools``).

Usage:
    cd tools/memory_extractor
    python scout_room_match.py > scout_room_match.log

Pipe to a file — output is verbose (candidate fields per instance).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"

# Hard cap: if the keyword filter accidentally matches hundreds of
# classes we don't heap-scan them all — protects against the freeze
# scenario documented in feedback_frida_heap_scan_freezes.
MAX_HEAPSCAN_CLASSES = 40

AGENT = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;

      // Narrow filter — room match is CygNames' current term for the
      // multi-player race feature; TeamStadium is legacy (Champions'
      // Meeting era); Nikkanken shows up in some competitive contexts;
      // RaceResult/RaceInfo/RaceHorse/RaceScheme are the generic
      // race data containers.
      const KEYWORDS = /RoomMatch|TeamStadium|RaceResult|RaceInfo|RaceHorse|RaceScheme|RaceParameter|Nikkanken/i;
      const IMAGES = [
        { name: 'umamusume', img: mainImg },
        { name: 'umamusume.Http', img: httpImg },
      ];

      // ─── Phase 1: metadata walk ─────────────────────────────
      send({type: 'header', text: '=== PHASE 1: CANDIDATE CLASSES ==='});
      const candidates = [];
      IMAGES.forEach(({ name, img }) => {
        send({type: 'text', text: '--- ' + name + ' ---'});
        img.classes.forEach(k => {
          const n = (k.type && k.type.name) || k.name || '<?>';
          if (KEYWORDS.test(n)) {
            send({type: 'text', text: '  ' + n});
            candidates.push({ img: name, klass: k, name: n });
          }
        });
      });
      send({type: 'text', text: ''});
      send({type: 'text', text: 'Total candidates: ' + candidates.length});

      if (candidates.length > __MAX_HEAPSCAN_CLASSES__) {
        send({type: 'text', text: '[!] Too many candidates ('
          + candidates.length + ' > cap '
          + __MAX_HEAPSCAN_CLASSES__
          + '). Narrow the KEYWORDS filter or raise cap in scout.'});
        send({type: 'done'});
        return;
      }

      // ─── Phase 2: targeted gc.choose per candidate ──────────
      send({type: 'header', text: '=== PHASE 2: HEAP SCAN PER CANDIDATE ==='});
      candidates.forEach(({ img, klass, name }, i) => {
        send({type: 'text', text: '[' + (i+1) + '/' + candidates.length
          + '] scanning ' + name + ' ...'});
        let instances;
        try {
          instances = Il2Cpp.gc.choose(klass);
        } catch (e) {
          send({type: 'text', text: '  SCAN FAILED: ' + e.message});
          return;
        }
        if (!instances || instances.length === 0) {
          send({type: 'text', text: '  0 instances'});
          return;
        }
        send({type: 'text', text: ''});
        send({type: 'text', text: '  ═══ [' + img + '] ' + name
          + ' — ' + instances.length + ' instance(s) ═══'});
        // Print field name+value for the first instance only — that
        // tells us if this class is worth looking at further.
        const inst = instances[0];
        if (!inst.class || !inst.class.fields) {
          send({type: 'text', text: '    (no fields resolvable)'});
          return;
        }
        inst.class.fields.forEach(f => {
          if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
          let repr;
          try {
            const v = inst.field(f.name).value;
            if (v === null || v === undefined) repr = 'null';
            else if (typeof v === 'number' || typeof v === 'boolean') repr = String(v);
            else if (typeof v === 'string') repr = JSON.stringify(v);
            else if (v.content !== undefined) repr = JSON.stringify(v.content);
            else if (v.length !== undefined) {
              let hint = '';
              if (v.length > 0) {
                try {
                  const e0 = v.get(0);
                  if (e0 && e0.class && e0.class.type) hint = ' [' + e0.class.type.name + ']';
                  else if (typeof e0 === 'number') hint = ' [num=' + e0 + ']';
                } catch (e) {}
              }
              repr = '<array len=' + v.length + hint + '>';
            }
            else if (v.class && v.class.type) repr = '<' + v.class.type.name + '>';
            else repr = '<' + typeof v + '>';
          } catch (e) {
            repr = '<read err: ' + e.message + '>';
          }
          const tname = (f.type && f.type.name) || '?';
          send({type: 'text', text: '    .' + f.name + ' [' + tname + '] = ' + repr});
        });
      });

      send({type: 'done'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 500);
""".replace("__MAX_HEAPSCAN_CLASSES__", str(MAX_HEAPSCAN_CLASSES))


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
        print(f"[X] no {PROCESS_NAME} process found — launch the game first")
        return 1
    print(f"[+] attaching to PID {pid}")

    done = {"flag": False}

    def on_message(msg, data):
        if msg["type"] == "send":
            payload = msg["payload"]
            t = payload.get("type", "?")
            if t == "init":
                print("[+] IL2CPP ready, scouting...")
            elif t == "header":
                print()
                print(payload["text"])
            elif t == "text":
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

    # Room match has many candidate classes possibly; give it 120s.
    deadline = time.time() + 120
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] scout didn't finish within 120s")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
