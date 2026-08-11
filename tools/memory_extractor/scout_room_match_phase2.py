"""Phase 2 scout: targeted heap scan of the exact-name whitelist we
identified from phase 1 (scout_room_match.py). Prints full field
structure per instance so we can eyeball payload shape.

Run this while on the Room Match result screen — same as phase 1.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"

# Whitelist — every entry is scanned; safe because count is bounded.
# Ordered by suspected priority (response payload first, then work
# data, then temp/live containers).
TARGETS_MAIN = [
    # Response object — this is the actual deserialized RoomMatchRaceEndResult
    # server response. The prime target for capture: contains the full result
    # payload with every participant's data.
    "Gallop.RoomMatchRaceEndResultResponse",
    # "Save to My Runners" flow's payload
    "Gallop.RoomMatchGetSavedRaceResultResponse",
]

# WorkRoomMatchData containers — these hold the enriched/normalized
# game-side model built from the response. Often easier to walk than
# the raw response because field names are declarative rather than
# msgpack-index-driven.
TARGETS_WORK = [
    "Gallop.WorkRoomMatchData",
    "Gallop.WorkRoomMatchData.RaceResultData",
    "Gallop.WorkRoomMatchData.SavedRaceResultData",
    "Gallop.WorkRoomMatchData.RoomMatchTrainedCharaData",
    "Gallop.WorkRoomMatchData.UserData",
    "Gallop.WorkRoomMatchData.RoomData",
    "Gallop.WorkRoomMatchData.RestrictCharaData",
]

# Session/live containers
TARGETS_LIVE = [
    "Gallop.TempData.RoomMatchTempData",
    "Gallop.RoomMatchTrainedChara",
    "Gallop.RoomMatchUser",
    "Gallop.RoomMatchUserDetail",
    "Gallop.RoomMatchRoomInfo",
    "Gallop.RoomMatchEntryChara",
]

# Formatter — points to the msgpack field mapping. Even if the response
# object is already collected, the formatter is a static class so it
# always has resolvable fields (constants + Deserialize method).
TARGETS_FORMATTER = [
    "Gallop.MsgPack.Formatters.RoomMatchRaceEndResultResponseFormatter",
]

ALL_TARGETS = TARGETS_MAIN + TARGETS_WORK + TARGETS_LIVE + TARGETS_FORMATTER


AGENT = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;
      const targets = __TARGETS__;

      // ─── Locate each target class across our two images ─────
      const found = [];
      targets.forEach(fqn => {
        let klass = null, imgName = null;
        try { klass = mainImg.class(fqn); imgName = 'umamusume'; } catch (e) {}
        if (!klass) {
          try { klass = httpImg.class(fqn); imgName = 'umamusume.Http'; } catch (e) {}
        }
        if (klass) found.push({ fqn, klass, img: imgName });
        else send({type: 'text', text: '[NOT FOUND] ' + fqn});
      });

      // ─── Heap scan each ─────────────────────────────────────
      send({type: 'header', text: '=== HEAP SCAN (' + found.length + ' targets) ==='});
      found.forEach(({ fqn, klass, img }, i) => {
        send({type: 'text', text: '[' + (i+1) + '/' + found.length
          + '] ' + fqn + ' (' + img + ')'});
        let instances;
        try {
          instances = Il2Cpp.gc.choose(klass);
        } catch (e) {
          send({type: 'text', text: '  SCAN FAILED: ' + e.message});
          return;
        }
        if (!instances || instances.length === 0) {
          send({type: 'text', text: '  0 live instances'});
          return;
        }
        send({type: 'text', text: '  → ' + instances.length + ' instance(s)'});

        // Dump full fields for first 2 instances (or 1 if singleton).
        const N = Math.min(2, instances.length);
        for (let n = 0; n < N; n++) {
          const inst = instances[n];
          send({type: 'text', text: '  ── instance #' + n + ' ──'});
          if (!inst.class || !inst.class.fields) {
            send({type: 'text', text: '    (no fields resolvable)'});
            continue;
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
                    else if (typeof e0 === 'string') hint = ' [str]';
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
        }
      });

      send({type: 'done'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 500);
""".replace("__TARGETS__", str(ALL_TARGETS).replace("'", '"'))


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

    deadline = time.time() + 60
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] scout didn't finish within 60s")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
