"""One-off scouting script: find where trainee "conditions" live in
IL2CPP memory (Fast Learner, Migraine, Skin Outbreak, Practice Perfect,
Pure Passion: Heirs to the Throne, etc.).

The regular extractor doesn't capture these — earlier attempts scanned
SingleModeChara's chara_effect_id_array which always came back empty on
completed runs. This script casts a wider net: enumerates IL2CPP classes
matching /condition|effect|status/i, heap-scans each, and prints sample
instance fields so we can identify which class holds the visible
Training Log conditions.

Prereqs:
- Game running with the Training Log popup OPEN and conditions visible
  (Removed and active).
- ``vendor/il2cpp_bridge.js`` populated (run ``setup.py`` once if not).
- Frida installed (``pip install frida frida-tools``).

Usage:
    cd tools/memory_extractor
    python scout_conditions.py

Output goes to stdout. Pipe to a file if you want to preserve for a
follow-up discussion: ``python scout_conditions.py > scout.log``.
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
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;

      const KEYWORDS = /condition|effect|status|debuff|buff/i;
      const IMAGES = [
        { name: 'umamusume', img: mainImg },
        { name: 'umamusume.Http', img: httpImg },
      ];

      // ─── Step 1 — enumerate candidate class names ────────────
      send({type: 'header', text: '=== CANDIDATE CLASSES (name matches condition|effect|status|debuff|buff) ==='});
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

      // ─── Step 2 — heap-scan each candidate, print counts + fields ──
      send({type: 'header', text: '=== HEAP SCAN OF EACH CANDIDATE ==='});
      candidates.forEach(({ img, klass, name }) => {
        let instances;
        try {
          instances = Il2Cpp.gc.choose(klass);
        } catch (e) {
          send({type: 'text', text: '  ' + name + ' — SCAN FAILED: ' + e.message});
          return;
        }
        if (!instances || instances.length === 0) return;
        send({type: 'text', text: ''});
        send({type: 'text', text: '  [' + img + '] ' + name + ' — ' + instances.length + ' instance(s)'});
        // Print field name+value for the first up-to-3 instances so
        // we can eyeball whether the same class is used for multiple
        // conditions (different values across instances).
        const N = Math.min(3, instances.length);
        for (let i = 0; i < N; i++) {
          const inst = instances[i];
          send({type: 'text', text: '    ── instance #' + i + ' ──'});
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
              else if (v.content !== undefined) repr = JSON.stringify(v.content);  // Il2Cpp.String
              else if (v.length !== undefined) repr = '<array len=' + v.length + '>';
              else if (v.class && v.class.type) repr = '<' + v.class.type.name + '>';
              else repr = '<' + typeof v + '>';
            } catch (e) {
              repr = '<read err: ' + e.message + '>';
            }
            const tname = (f.type && f.type.name) || '?';
            send({type: 'text', text: '      .' + f.name + ' [' + tname + '] = ' + repr});
          });
        }
      });

      // ─── Step 3 — SingleModeChara array/list fields ─────────
      // Anything on the chara that might BE a condition list, even
      // without matching the keyword — e.g. named like _statusList
      // (Japanese devs) or a bare "buff" field.
      send({type: 'header', text: '=== SingleModeChara ARRAY/LIST FIELDS ==='});
      try {
        const smcClass = httpImg.class('Gallop.SingleModeChara');
        const smcs = Il2Cpp.gc.choose(smcClass);
        send({type: 'text', text: '  Found ' + smcs.length + ' SingleModeChara instance(s)'});
        let best = null, bestFans = -1;
        smcs.forEach(s => {
          try {
            const f = s.field('fans').value | 0;
            if (f > bestFans) { bestFans = f; best = s; }
          } catch (e) {}
        });
        if (best) {
          send({type: 'text', text: '  Using SMC with fans=' + bestFans});
          smcClass.fields.forEach(f => {
            if (f.isStatic || f.isLiteral) return;
            const tn = (f.type && f.type.name) || '';
            // Array-ish: end in [], contain 'List', contain 'Array'.
            if (!tn.endsWith('[]') && !/List|Array/i.test(tn) && !/array/i.test(f.name)) return;
            let repr;
            try {
              const v = best.field(f.name).value;
              if (v === null || v === undefined) repr = 'null';
              else if (v.length !== undefined) {
                // Peek at first element's type if array is non-empty
                let elemHint = '';
                if (v.length > 0) {
                  try {
                    const e0 = v.get(0);
                    if (e0 && e0.class && e0.class.type) {
                      elemHint = ' [' + e0.class.type.name + ']';
                    } else if (typeof e0 === 'number') elemHint = ' [' + typeof e0 + '=' + e0 + ']';
                  } catch (e) {}
                }
                repr = 'len=' + v.length + elemHint;
              }
              else repr = '<' + typeof v + '>';
            } catch (e) { repr = '<err: ' + e.message + '>'; }
            send({type: 'text', text: '  .' + f.name + ' (' + tn + ') = ' + repr});
          });
        }
      } catch (e) {
        send({type: 'text', text: '  SingleModeChara scan failed: ' + e.message});
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
        # Wine/Proton hosting — see dump_it_run.py for the /proc scan
        # rationale. Reuse the same helper.
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

    # Poll for completion — the scout finishes fast (a few seconds) but
    # give it up to 60s in case class enumeration is slow.
    deadline = time.time() + 60
    while time.time() < deadline and not done["flag"]:
        time.sleep(0.1)
    if not done["flag"]:
        print("[X] scout didn't finish within 60s")
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
