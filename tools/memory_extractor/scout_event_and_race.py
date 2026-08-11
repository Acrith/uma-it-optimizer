"""Scout: hunt for per-event / per-turn granular data + unpack race
reward payloads.

**Runs in two modes.** Default (--phase=list) is cheap and does NOT
freeze the game — it just enumerates class NAMES matching a narrow
Gallop.SingleMode* / Gallop.WorkSingleMode* / Gallop.*Training* set
and prints them. No `Il2Cpp.gc.choose` calls. Fast (~1s).

Second mode (--phase=scan) heap-scans a curated list of classes we
know matter, and deep-walks IdleSingleModeRaceHistory[0] to unpack
RaceRewardData payloads the extractor's depth-6 walker truncates.
Emits progress BEFORE each gc.choose so the log tail always names
the class currently being scanned — if the game freezes, the log's
last line pinpoints the culprit and we can remove it from the list.

**Why the two-phase split.** An earlier version used a wide regex
that matched 5403 classes; one of them deadlocked gc.choose forever
and Frida has no timeout for a hung agent call. Wide heap-scans
freeze the game process for their entire duration; narrow ones are
the only safe pattern.

Prereqs (identical to scout_conditions.py):
- Game running with the Training Log popup OPEN on a finished IT.
- vendor/il2cpp_bridge.js populated (run setup.py once if not).
- Frida installed (pip install frida frida-tools).

Usage (from Windows PowerShell, or WSL bridged via powershell.exe):
    # List candidate class names — no freeze.
    python scout_event_and_race.py --phase=list

    # After picking classes from the list, scan them + deep-walk
    # the race reward payload.
    python scout_event_and_race.py --phase=scan
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"


# Curated classes to heap-scan in Phase B. Kept short + specific so
# gc.choose runs in seconds and any single bad class is easy to spot
# and remove from the list. Extend by name after Phase A tells you
# what's out there.
SCAN_TARGETS = [
    # Baseline sanity check.
    "Gallop.SingleModeChara",
    # Round-3 (mid-run hunt): where does the LIVE session state live?
    # The "Idle" prefix classes we've been targeting only populate at
    # end-of-IT for the summary UI. Session-runtime state must live in
    # a different family. Best guesses:
    "Gallop.SingleModeModelManager",
    "Gallop.SingleModeModelManager.Model",
    # WorkSingleMode* looks like the game's server-DTO staging layer —
    # populated between API round-trips during the run.
    "Gallop.WorkSingleModeData",
    "Gallop.WorkSingleModeData.EventInfo",
    "Gallop.WorkSingleModeData.ParamsIncDecInfo",
    "Gallop.WorkSingleModeData.EventChoiceReward",
    "Gallop.WorkSingleModeCharaData",
    "Gallop.WorkSingleModeChangeParameterInfo",
    "Gallop.WorkSingleModeChangeParameterInfo.EvaluationData",
    # Post-run baseline for A/B comparison.
    "Gallop.IdleSingleModeRaceHistory",
]


AGENT_LIST = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;

      // Narrow filters — anything nested under SingleMode / Training
      // in the Gallop namespace. This is cheap: just enumerating names,
      // no GC walks, so the game stays responsive.
      const NAME_RE = /^Gallop\.(SingleMode|WorkSingleMode|Training|IdleSingleMode)/;
      // Skip UI classes and compiler-generated closure types.
      const EXCLUDE = /Dialog|Parts|View$|Controller|<>c__/;

      send({type: 'header', text: '=== CLASS NAMES matching Gallop.SingleMode* / WorkSingleMode* / Training* / IdleSingleMode* ==='});
      const seen = [];
      [
        { name: 'umamusume', img: mainImg },
        { name: 'umamusume.Http', img: httpImg },
      ].forEach(({ name, img }) => {
        const bucket = [];
        img.classes.forEach(k => {
          const n = (k.type && k.type.name) || k.name || '<?>';
          if (NAME_RE.test(n) && !EXCLUDE.test(n)) {
            bucket.push(n);
          }
        });
        bucket.sort();
        send({type: 'text', text: ''});
        send({type: 'text', text: '  --- [' + name + '] ' + bucket.length + ' names ---'});
        bucket.forEach(n => send({type: 'text', text: '    ' + n}));
        seen.push(...bucket);
      });

      send({type: 'text', text: ''});
      send({type: 'text', text: '  Total: ' + seen.length + ' class names collected.'});
      send({type: 'done'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 500);
"""


AGENT_SCAN_TEMPLATE = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;

      const TARGETS = __TARGETS__;

      function resolveClass(name) {
        try { const k = mainImg.class(name); if (k) return k; } catch (e) {}
        try { const k = httpImg.class(name); if (k) return k; } catch (e) {}
        // Fallback: nested types often fail the direct lookup even
        // when they exist. Iterate BOTH images' full class list and
        // match on the type name.
        let found = null;
        [mainImg, httpImg].forEach(img => {
          if (found) return;
          img.classes.forEach(k => {
            if (found) return;
            const n = (k.type && k.type.name) || '';
            if (n === name) { found = k; }
          });
        });
        return found;
      }

      // ─── Phase B.1 — heap-scan each curated target ──────────────
      send({type: 'header', text: '=== HEAP-SCAN CURATED TARGETS ==='});
      const results = [];
      for (let i = 0; i < TARGETS.length; i++) {
        const name = TARGETS[i];
        // Send progress BEFORE the scan so if this one hangs, the
        // log's last line names the culprit.
        send({type: 'text', text: '  [' + (i + 1) + '/' + TARGETS.length + '] scanning: ' + name});
        const klass = resolveClass(name);
        if (!klass) {
          send({type: 'text', text: '    (class not found in either image)'});
          continue;
        }
        let instances;
        try {
          instances = Il2Cpp.gc.choose(klass);
        } catch (e) {
          send({type: 'text', text: '    (gc.choose failed: ' + e.message + ')'});
          continue;
        }
        const n = instances ? instances.length : 0;
        send({type: 'text', text: '    ->' + n + ' instance(s)'});
        if (n > 0) results.push({ name, sample: instances[0] });
      }

      // ─── Phase B.2 — dump fields for the first instance of each hit ──
      send({type: 'header', text: '=== FIELD DUMPS ==='});
      results.forEach(({ name, sample }) => {
        send({type: 'text', text: ''});
        send({type: 'text', text: '  == ' + name + ' =='});
        try {
          if (!sample.class || !sample.class.fields) {
            send({type: 'text', text: '    (no fields resolvable)'});
            return;
          }
          sample.class.fields.forEach(f => {
            if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
            let repr;
            try {
              const v = sample.field(f.name).value;
              if (v === null || v === undefined) repr = 'null';
              else if (typeof v === 'number' || typeof v === 'boolean') repr = String(v);
              else if (typeof v === 'string') repr = JSON.stringify(v);
              else if (v.content !== undefined) repr = JSON.stringify(v.content);
              else if (v.length !== undefined) repr = '<array len=' + v.length + '>';
              else if (v.class && v.class.type) repr = '<' + v.class.type.name + '>';
              else repr = '<' + typeof v + '>';
            } catch (e) {
              repr = '<read err: ' + e.message + '>';
            }
            const tname = (f.type && f.type.name) || '?';
            send({type: 'text', text: '    .' + f.name + ' [' + tname + '] = ' + repr});
          });
        } catch (e) {
          send({type: 'text', text: '    (dump failed: ' + e.message + ')'});
        }
      });

      // ─── Phase B.3 — deep-walk IdleSingleModeRaceHistory[0] ─────
      // Goal: see what's inside each RaceRewardData that our depth-6
      // extractor walker currently prints as literal '<Gallop.RaceRewardData>'.
      send({type: 'header', text: '=== IdleSingleModeRaceHistory[0] deep-walk (maxDepth=12) ==='});
      function walkDeep(v, typeName, depth, maxDepth) {
        if (depth > maxDepth) return '<max-depth>';
        if (v === null || v === undefined) return null;
        if (typeof v === 'number' || typeof v === 'boolean') return v;
        if (typeof v === 'string') return v;
        if (v.content !== undefined) return v.content;
        if (v.length !== undefined && v.get !== undefined) {
          const out = [];
          const N = Math.min(v.length, 6);
          const elemType = (typeName || '').replace(/\[\]$/, '');
          for (let i = 0; i < N; i++) {
            try { out.push(walkDeep(v.get(i), elemType, depth + 1, maxDepth)); }
            catch (e) { out.push('<get-err: ' + e.message + '>'); }
          }
          if (v.length > N) out.push('… (+' + (v.length - N) + ' more)');
          return out;
        }
        if (v.class && v.class.fields) {
          const obj = { '__type__': (v.class.type && v.class.type.name) || typeName };
          v.class.fields.forEach(f => {
            if (f.isStatic || f.isLiteral) return;
            try {
              obj[f.name] = walkDeep(v.field(f.name).value, f.type && f.type.name, depth + 1, maxDepth);
            } catch (e) {
              obj[f.name] = '<field-err: ' + e.message + '>';
            }
          });
          return obj;
        }
        return '<opaque: ' + typeof v + '>';
      }
      try {
        const ishClass = resolveClass('Gallop.IdleSingleModeRaceHistory');
        if (!ishClass) {
          send({type: 'text', text: '  IdleSingleModeRaceHistory class not found'});
        } else {
          send({type: 'text', text: '  scanning IdleSingleModeRaceHistory instances (this is one gc.choose)...'});
          const ishs = Il2Cpp.gc.choose(ishClass);
          send({type: 'text', text: '  found ' + ishs.length + ' instance(s)'});
          if (ishs.length > 0) {
            send({type: 'text', text: '  walking instance #0 at depth 12...'});
            const walked = walkDeep(ishs[0], 'Gallop.IdleSingleModeRaceHistory', 0, 12);
            const pretty = JSON.stringify(walked, null, 2);
            pretty.split('\n').forEach(line => send({type: 'text', text: '    ' + line}));
          }
        }
      } catch (e) {
        send({type: 'text', text: '  deep-walk failed: ' + e.message});
      }

      // ─── Phase B.5 — deep-walk WorkSingleModeData (the live model) ─
      // This is the JACKPOT class if it lives at end-of-IT the same
      // way it lives mid-run: EventChoiceRewardDict, _raceHistoryInfoList,
      // _changeParameterInfo — all the per-event data we've been hunting.
      send({type: 'header', text: '=== WorkSingleModeData deep-walk (maxDepth=10) ==='});
      try {
        const wsmClass = resolveClass('Gallop.WorkSingleModeData');
        if (!wsmClass) {
          send({type: 'text', text: '  WorkSingleModeData class not found'});
        } else {
          const wsms = Il2Cpp.gc.choose(wsmClass);
          send({type: 'text', text: '  found ' + wsms.length + ' instance(s)'});
          if (wsms.length > 0) {
            const walked = walkDeep(wsms[0], 'Gallop.WorkSingleModeData', 0, 10);
            const pretty = JSON.stringify(walked, null, 2);
            pretty.split('\n').forEach(line => send({type: 'text', text: '    ' + line}));
          }
        }
      } catch (e) {
        send({type: 'text', text: '  deep-walk failed: ' + e.message});
      }

      // ─── Phase B.4 — deep-walk SingleModeLogPool ────────────────
      // Same idea for the training-log popup's backing pool: we want
      // to see what's inside _logGroupPool so we can tell if it holds
      // real per-event data (turn, event_id, gains) or is just pooled
      // UI slots.
      send({type: 'header', text: '=== SingleModeLogPool deep-walk (maxDepth=10) ==='});
      try {
        const poolClass = resolveClass('Gallop.SingleModeLogPool');
        if (!poolClass) {
          send({type: 'text', text: '  SingleModeLogPool class not found'});
        } else {
          send({type: 'text', text: '  scanning SingleModeLogPool instances...'});
          const pools = Il2Cpp.gc.choose(poolClass);
          send({type: 'text', text: '  found ' + pools.length + ' instance(s)'});
          if (pools.length > 0) {
            send({type: 'text', text: '  walking instance #0 at depth 10...'});
            const walked = walkDeep(pools[0], 'Gallop.SingleModeLogPool', 0, 10);
            const pretty = JSON.stringify(walked, null, 2);
            pretty.split('\n').forEach(line => send({type: 'text', text: '    ' + line}));
          }
        }
      } catch (e) {
        send({type: 'text', text: '  deep-walk failed: ' + e.message});
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


def _build_agent(phase: str) -> str:
    if phase == "list":
        return AGENT_LIST
    if phase == "scan":
        # Inline the target list as a JS array literal.
        import json
        return AGENT_SCAN_TEMPLATE.replace("__TARGETS__", json.dumps(SCAN_TARGETS))
    raise ValueError(f"unknown phase {phase!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", choices=("list", "scan"), default="list",
                    help="'list' = cheap name enumeration (no freeze); "
                         "'scan' = curated gc.choose + deep-walk (brief freeze)")
    args = ap.parse_args()

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
    print(f"[+] attaching to PID {pid}  (phase={args.phase})")

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
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + _build_agent(args.phase)
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()

    # 'list' is fast; 'scan' can take 30-60s on the curated set.
    deadline = time.time() + (60 if args.phase == "list" else 300)
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] scout didn't finish before deadline")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
