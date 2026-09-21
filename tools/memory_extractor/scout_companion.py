"""Scouting for the companion plan (docs/companion-plan.md, M1).

One script, three modes, each run with the game in a different state.
Together they answer the three unknowns that gate plugin v2:

  collection  Which class holds the account's support cards (id, limit
              break, level/exp) and where it lives.
              Game state: HOME screen, logged in. Nothing open.

  dialog      Which class IS the Training Log popup and what its
              lifecycle methods are called, so the plugin can hook its
              opening for zero-click IT capture. Also prints the
              inheritance chain so a vtable-slot hook on the base class
              is an option.
              Game state: Training Log popup OPEN after an IT run.

  career      What is resident during a MANUAL career at the skill
              purchase screen: SingleModeChara, owned skills, hint tips
              and levels, SP. Confirms the SP planner can be fed live.
              Game state: manual career, skill purchase screen open.

Why the split: heap scans (gc.choose) freeze the game for their whole
duration (feedback_frida_heap_scan_freezes), so this script enumerates
class NAMES and FIELD LAYOUTS from metadata (free) for as wide a net as
you like, and only heap-scans a short list it picks by field-name
heuristics, capped at MAX_SCANS. Widen KEYWORDS, not the cap.

Prereqs: ``vendor/il2cpp_bridge.js`` (run ``setup.py`` once), frida
installed, game running on Windows.

Usage:
    cd tools/memory_extractor
    python scout_companion.py collection > scout_collection.log
    python scout_companion.py dialog     > scout_dialog.log
    python scout_companion.py career     > scout_career.log

Keep the logs; they are the input to the plugin work.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"

# Per mode: which class names to list, which field names mark a class
# as worth a heap scan, and how many scans we allow ourselves.
MODES = {
    "collection": {
        "keywords": r"supportcard|support_card",
        "must_have_field": r"limit_break|support_card_id|favorite|exp\b|stock",
        "max_scans": 6,
        "state": "HOME screen, logged in, nothing open",
    },
    "dialog": {
        "keywords": r"traininglog|idle.*(log|result|dialog|view)|singlemodeidle|"
                    r"idlesinglemode|dialog.*(idle|training)",
        "must_have_field": r".",          # any: we want lifecycle methods, not data
        "max_scans": 4,
        "state": "Training Log popup OPEN after an IT run",
    },
    "career": {
        "keywords": r"singlemodechara$|skilltips|skill_tips|singlemodeskill|"
                    r"learnskill|skilllearn|singlemodehint",
        "must_have_field": r"skill|hint|tips|point",
        "max_scans": 6,
        "state": "MANUAL career, skill purchase screen open",
    },
}

AGENT_TEMPLATE = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const KEYWORDS = new RegExp(%(keywords)s, 'i');
      const MUST_HAVE = new RegExp(%(must_have)s, 'i');
      const MAX_SCANS = %(max_scans)d;
      const MODE = %(mode)s;

      const IMAGES = [];
      for (const asm of ['umamusume', 'umamusume.Http', 'Assembly-CSharp']) {
        try { IMAGES.push({ name: asm, img: Il2Cpp.domain.assembly(asm).image }); }
        catch (e) { send({type: 'text', text: '  (no assembly ' + asm + ')'}); }
      }

      // ─── 1. names + field layouts from metadata: free, cast wide ──
      send({type: 'header', text: '=== ' + MODE.toUpperCase() + ': candidate classes ==='});
      const candidates = [];
      IMAGES.forEach(({ name, img }) => {
        img.classes.forEach(k => {
          const n = (k.type && k.type.name) || k.name || '<?>';
          if (!KEYWORDS.test(n)) return;
          const fields = [];
          try {
            k.fields.forEach(f => {
              if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
              fields.push(f.name + ':' + ((f.type && f.type.name) || '?'));
            });
          } catch (e) {}
          const hit = fields.some(f => MUST_HAVE.test(f));
          send({type: 'text', text: '  [' + name + '] ' + n + (hit ? '   <-- field match' : '')});
          if (fields.length) send({type: 'text', text: '      ' + fields.join(', ')});
          candidates.push({ img: name, klass: k, name: n, hit });
        });
      });

      // ─── 2. dialog mode: lifecycle methods + inheritance chain ──
      if (MODE === 'dialog') {
        send({type: 'header', text: '=== DIALOG: methods and parents (hook targets) ==='});
        candidates.forEach(({ img, klass, name }) => {
          send({type: 'text', text: ''});
          send({type: 'text', text: '  ' + name});
          // Parent chain: a vtable-slot hook on a base virtual survives
          // renames of the leaf class's own methods.
          let p = klass.parent, chain = [];
          while (p) { chain.push((p.type && p.type.name) || p.name); p = p.parent; }
          send({type: 'text', text: '    parents: ' + (chain.join(' -> ') || '(none)')});
          try {
            klass.methods.forEach(m => {
              const LIFECYCLE = /^(Initialize|Init|OnEnter|OnStart|Open|Show|Setup|Start|Awake|OnEnable|Play|Begin|Create)/i;
              if (LIFECYCLE.test(m.name) || /Initialize|Open|Show/i.test(m.name)) {
                send({type: 'text', text: '    method ' + m.name + '(' + m.parameterCount + ' args)'
                                          + (m.isStatic ? ' static' : '')
                                          + '  @' + m.virtualAddress});
              }
            });
          } catch (e) { send({type: 'text', text: '    (methods unreadable: ' + e.message + ')'}); }
        });
      }

      // ─── 3. heap-scan a short list: costly, capped ──
      const shortlist = candidates.filter(c => c.hit).slice(0, MAX_SCANS);
      send({type: 'header', text: '=== HEAP SCAN (' + shortlist.length + ' of '
                                    + candidates.length + ' candidates, cap ' + MAX_SCANS + ') ==='});
      shortlist.forEach(({ img, klass, name }) => {
        let instances;
        const t0 = Date.now();
        try { instances = Il2Cpp.gc.choose(klass); }
        catch (e) { send({type: 'text', text: '  ' + name + ' scan failed: ' + e.message}); return; }
        send({type: 'text', text: ''});
        const count = instances ? instances.length : 0;
        send({type: 'text', text: '  [' + img + '] ' + name + ': ' + count
                                  + ' instance(s), ' + (Date.now() - t0) + ' ms'});
        if (!instances || !instances.length) return;
        const N = Math.min(3, instances.length);
        for (let i = 0; i < N; i++) {
          const inst = instances[i];
          send({type: 'text', text: '    instance #' + i});
          if (!inst.class || !inst.class.fields) continue;
          inst.class.fields.forEach(f => {
            if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
            let repr;
            try {
              const v = inst.field(f.name).value;
              if (v === null || v === undefined) repr = 'null';
              else if (typeof v === 'number' || typeof v === 'boolean') repr = String(v);
              else if (typeof v === 'string') repr = JSON.stringify(v);
              else if (v.content !== undefined) repr = JSON.stringify(v.content);
              else if (v.length !== undefined) repr = '<array len=' + v.length + '>';
              else if (v.class && v.class.type) repr = '<' + v.class.type.name + '>';
              else repr = '<' + typeof v + '>';
            } catch (e) { repr = '<read err: ' + e.message + '>'; }
            send({type: 'text', text: '      .' + f.name + ' = ' + repr});
          });
        }
        // Collection mode: a class with hundreds of instances and a
        // support_card_id field is the roster. Say so.
        if (MODE === 'collection' && instances.length > 50) {
          send({type: 'text', text: '    ^ ' + instances.length
                                    + ' instances: this looks like the collection'});
        }
      });

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
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        print(f"usage: python scout_companion.py {{{'|'.join(MODES)}}}")
        return 2
    spec = MODES[mode]
    print(f"[i] mode {mode}: run this with the game at: {spec['state']}")

    if not BRIDGE_JS.exists():
        print(f"[X] {BRIDGE_JS} missing: run `python setup.py` first")
        return 1
    try:
        import frida
    except ImportError:
        print("[X] frida not installed: `pip install frida frida-tools`")
        return 1

    pid = _find_pid()
    if pid is None:
        print(f"[X] no {PROCESS_NAME} process found: launch the game first")
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
                print("[+] scout complete; detach happens now")
                done["flag"] = True
            elif t == "fatal":
                print(f"[X] agent error: {payload.get('err')}")
                print(payload.get("stack", ""))
                done["flag"] = True
        elif msg["type"] == "error":
            print(f"[X] {msg.get('description')}")
            done["flag"] = True

    agent = AGENT_TEMPLATE % {
        "keywords": json.dumps(spec["keywords"]),
        "must_have": json.dumps(spec["must_have_field"]),
        "max_scans": spec["max_scans"],
        "mode": json.dumps(mode),
    }
    session = frida.attach(pid)
    script = session.create_script(BRIDGE_JS.read_text(encoding="utf-8") + "\n" + agent)
    script.on("message", on_message)
    script.load()
    deadline = time.time() + 180
    while not done["flag"] and time.time() < deadline:
        time.sleep(0.2)
    if not done["flag"]:
        print("[X] timed out after 180 s")
    # One-shot: detach as soon as we have what we came for.
    session.detach()
    return 0 if done["flag"] else 1


if __name__ == "__main__":
    sys.exit(main())
