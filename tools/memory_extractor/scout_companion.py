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

  account     The account's collections through the game's own data
              singleton (Gallop.WorkDataManager, a static field away):
              support cards with limit breaks, trained umas, characters.
              No heap scan: counts plus a few sample entries.
              Game state: HOME screen, logged in. Nothing open.

  itsetup     The Independent Training state (WorkIdleSingleModeData
              and friends) the same way: trainee, parents, deck, times.
              Game state: IT setup screen (before Start), or a run going.

  view        The current screen's controller, through the scene manager
              singleton: what a setup screen holds before Start (the
              trainee, parents, deck being chosen). No heap scan.
              Game state: any screen; run it once per screen.

  entry       Only the career/IT setup selection (the setup controller's
              Entry: trainee, parents, deck, borrowed card, scenario),
              followed by its exact path from the scene manager.
              Game state: a career / IT setup screen.

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
    python scout_companion.py account    > scout_account.log
    python scout_companion.py itsetup    > scout_itsetup.log

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
    # account / itsetup walk from the WorkDataManager singleton: no heap
    # scan. `keywords` lists classes from metadata; `targets` picks which
    # of the singleton's members to open.
    "account": {
        "keywords": r"^gallop\.work.*(support|trainedchara|chara|card)",
        "must_have_field": r"$^",
        "max_scans": 0,
        "targets": r"support|trainedchara|chara",
        "state": "HOME screen, logged in, nothing open",
    },
    "view": {
        "keywords": r"singlemode.*(start|select|entry|deck|succession)|(chara|deck|support).*select",
        "must_have_field": r"$^",
        "max_scans": 0,
        "targets": r"^_currentViewController$",
        "singleton": "Gallop.SceneManager",
        "depth": 4,
        "state": "any screen (once per screen)",
    },
    "entry": {
        "keywords": r"$^",
        "must_have_field": r"$^",
        "max_scans": 0,
        "singleton": "Gallop.SceneManager",
        "path": ["_currentViewController", "<ChildCurrentController>k__BackingField",
                 "<Entry>k__BackingField"],
        "depth": 5,
        "state": "a career / IT setup screen",
    },
    "decks": {
        "keywords": r"$^",
        "must_have_field": r"$^",
        "max_scans": 0,
        "path": ["<SupportDeckData>k__BackingField"],
        "depth": 4,
        "samples": 10,
        "state": "any screen",
    },
    "dialogs": {
        "keywords": r"$^",
        "must_have_field": r"$^",
        "max_scans": 0,
        "singleton": "Gallop.DialogManager",
        "targets": r"dialog|list|stack|queue",
        "depth": 3,
        "state": "a dialog open",
    },
    "startconfirm": {
        "keywords": r"$^",
        "must_have_field": r"$^",
        "max_scans": 0,
        "singleton": "Gallop.DialogManager",
        "path": ["_dialogList", "[0]", "_data", "RightButtonCallBack", "m_target"],
        "depth": 3,
        "samples": 10,
        "state": "the career / IT Final Confirmation dialog open",
    },
    "itprefs": {
        "keywords": r"racereserve|reservepreset|preferenceskill",
        "must_have_field": r"$^",
        "max_scans": 0,
        "singleton": "Gallop.DialogManager",
        "path": ["_dialogList", "[0]", "_data", "RightButtonCallBack", "m_target", "_viewModel",
                 "<DialogSetupParameter>k__BackingField", "<PreferenceSkillIdList>k__BackingField"],
        "depth": 2,
        "samples": 20,
        "state": "the Final Confirmation dialog open on the Independent Training tab",
    },
    "itsetup": {
        "keywords": r"^gallop\.work.*idle|idlesinglemode.*(entry|start|deck|setup|load|progress)",
        "must_have_field": r"$^",
        "max_scans": 0,
        "targets": r"idle|<singlemode>",
        "state": "IT setup screen (before Start), or a run in progress",
    },
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
      const TARGETS = %(targets)s ? new RegExp(%(targets)s, 'i') : null;
      const SINGLETON = %(singleton)s;
      const DEPTH = %(depth)d;
      const PATH = %(path)s;

      // Obscured* wrappers keep value ^ key.
      function obscured(v) {
        try { return (v.field('hiddenValue').value ^ v.field('currentCryptoKey').value) | 0; }
        catch (e) { return undefined; }
      }
      const tname = v => { try { return v.class.type.name; } catch (e) { return '?'; } };

      // A short, safe description of a value: scalars as-is, strings,
      // Obscured decoded, collections as their size plus SAMPLES entries,
      // objects as their fields down to `depth`.
      const SAMPLES = %(samples)d;
      function describe(v, depth, indent) {
        const pad = '  '.repeat(indent);
        if (v === null || v === undefined) return 'null';
        if (typeof v === 'number' || typeof v === 'boolean') return String(v);
        if (typeof v === 'string') return JSON.stringify(v);
        if (typeof v === 'bigint' || (v.toString && v.constructor && v.constructor.name === 'Int64')) return v.toString();
        if (v.content !== undefined) return JSON.stringify(v.content);
        const ob = obscured(v);
        if (ob !== undefined) return String(ob) + ' (obscured)';
        const tn = tname(v);
        if (v.length !== undefined && v.get) {                 // Il2Cpp.Array
          const out = ['<' + tn + ' len=' + v.length + '>'];
          for (let i = 0; i < Math.min(SAMPLES, v.length); i++)
            out.push(pad + '  [' + i + '] ' + describe(v.get(i), depth - 1, indent + 2));
          return out.join('\n');
        }
        if (depth <= 0) return '<' + tn + '>';
        let fields = [];
        try { fields = ownAndInherited(v.class); }
        catch (e) { return '<' + tn + '>'; }
        // List<T> and Dictionary<K,V>: show the size and a few entries.
        const has = n => fields.some(f => f.name === n);
        if (has('_items') && has('_size')) {
          const size = v.field('_size').value, items = v.field('_items').value;
          const out = ['<' + tn + ' count=' + size + '>'];
          for (let i = 0; i < Math.min(SAMPLES, size); i++)
            out.push(pad + '  [' + i + '] ' + describe(items.get(i), depth - 1, indent + 2));
          return out.join('\n');
        }
        if (has('_entries') && has('_count')) {
          const count = v.field('_count').value, entries = v.field('_entries').value;
          const out = ['<' + tn + ' count=' + count + '>'];
          let shown = 0;
          for (let i = 0; entries && i < entries.length && shown < SAMPLES; i++) {
            const e = entries.get(i);
            let key;
            try { key = e.field('key').value; } catch (x) { continue; }
            out.push(pad + '  {' + describe(key, 0, 0) + '} ' + describe(e.field('value').value, depth - 1, indent + 2));
            shown++;
          }
          return out.join('\n');
        }
        const out = ['<' + tn + '>'];
        fields.forEach(f => {
          let r;
          try { r = describe(v.field(f.name).value, depth - 1, indent + 1); }
          catch (e) { r = '<read err: ' + e.message + '>'; }
          out.push(pad + '  .' + f.name + ' = ' + r);
        });
        return out.join('\n');
      }

      // Instance fields of a class and its game-side parents (a child
      // view slot often lives on a base controller); Unity's and .NET's
      // own base classes are left out.
      function ownAndInherited(klass) {
        const out = [];
        for (let c = klass; c; c = c.parent) {
          const cn = (c.type && c.type.name) || c.name || '';
          if (c !== klass && /^(UnityEngine|System)\./.test(cn)) break;
          c.fields.forEach(f => { if (!f.isStatic && !f.isLiteral && !f.isThreadStatic) out.push(f); });
        }
        return out;
      }

      function findClass(images, fullName) {
        for (const { img } of images) {
          for (const k of img.classes) {
            if (((k.type && k.type.name) || k.name) === fullName) return k;
          }
        }
        return null;
      }

      function singletonOf(images, name) {
        const k = findClass(images, name);
        if (!k) return null;
        for (let c = k; c; c = c.parent) {
          for (const f of c.fields) {
            if (f.isStatic && ((f.type && f.type.name) || '') === name) {
              try { return f.value; } catch (e) {}
            }
          }
        }
        try { return k.method('get_Instance').invoke(); } catch (e) { return null; }
      }

      // From the singleton down PATH (field names), then describe the end.
      function followPath(images) {
        send({type: 'header', text: '=== ' + SINGLETON + ' -> ' + PATH.join(' -> ') + ' ==='});
        let v = singletonOf(images, SINGLETON);
        for (const name of PATH) {
          if (!v || (v.isNull && v.isNull())) { send({type: 'text', text: '  null before ' + name}); return; }
          const idx = /^\[(\d+)\]$/.exec(name);
          const key = /^\{(-?\d+)\}$/.exec(name);
          try {
            if (key) {
              // Dictionary<int, T>: scan _entries for the key.
              const entries = v.field('_entries').value, want = Number(key[1]);
              let hit = null;
              for (let i = 0; i < entries.length && !hit; i++) {
                const e = entries.get(i);
                let k; try { k = e.field('key').value; } catch (x) { continue; }
                if (Number(k) === want) hit = e.field('value').value;
              }
              if (!hit) throw new Error('no key ' + want);
              v = hit;
            } else if (idx) {
              // List<T> keeps its items in _items; arrays index directly.
              const arr = v.get ? v : v.field('_items').value;
              v = arr.get(Number(idx[1]));
            } else {
              v = v.field(name).value;
            }
          }
          catch (e) { send({type: 'text', text: '  no ' + name + ' on ' + tname(v) + ': ' + e.message}); return; }
          send({type: 'text', text: '  ' + name + ': ' + tname(v)});
        }
        describe(v, DEPTH, 1).split('\n').forEach(line => send({type: 'text', text: '  ' + line}));
      }

      // The singleton: a static field of its own type on the class or a
      // parent (Singleton<T>), else a static get_Instance().
      function walkSingleton(images, targets) {
        const name = SINGLETON;
        send({type: 'header', text: '=== ' + name + ' (no heap scan) ==='});
        const k = findClass(images, name);
        if (!k) { send({type: 'text', text: '  class not found'}); return; }
        let inst = null, how = '';
        for (let c = k; c && !inst; c = c.parent) {
          c.fields.forEach(f => {
            if (!f.isStatic || inst) return;
            const ft = (f.type && f.type.name) || '';
            send({type: 'text', text: '  static ' + ((c.type && c.type.name) || c.name) + '.' + f.name + ': ' + ft});
            if (ft === name) { try { inst = f.value; how = 'static ' + f.name; } catch (e) {} }
          });
        }
        if (!inst) {
          try { inst = k.method('get_Instance').invoke(); how = 'get_Instance()'; } catch (e) {}
        }
        if (!inst || inst.isNull && inst.isNull()) { send({type: 'text', text: '  no instance found'}); return; }
        send({type: 'text', text: '  instance via ' + how});
        const members = ownAndInherited(inst.class);
        send({type: 'text', text: '  members (' + members.length + '):'});
        members.forEach(f => send({type: 'text', text: '    ' + f.name + ': ' + ((f.type && f.type.name) || '?')}));
        members.filter(f => targets.test(f.name) || targets.test((f.type && f.type.name) || '')).forEach(f => {
          send({type: 'text', text: ''});
          send({type: 'text', text: '  --- ' + f.name + ' ---'});
          let text;
          try { text = describe(inst.field(f.name).value, DEPTH, 2); }
          catch (e) { text = '<read err: ' + e.message + '>'; }
          text.split('\n').forEach(line => send({type: 'text', text: '    ' + line}));
        });
      }

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

      // ─── 2b. account / itsetup: walk from the WorkDataManager singleton ──
      if (PATH.length) {
        followPath(IMAGES);
      } else if (TARGETS) {
        walkSingleton(IMAGES, TARGETS);
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
    # path SINGLETON FIELD [FIELD ...] [--depth N] [--samples N]: follow any
    # field path from a singleton (fields, or [i] for list items).
    if mode == "path" and len(sys.argv) > 3:
        args = sys.argv[2:]
        opts = {"--depth": 3, "--samples": 5}
        for flag in list(opts):
            if flag in args:
                i = args.index(flag)
                opts[flag] = int(args[i + 1])
                del args[i:i + 2]
        MODES["path"] = {
            "keywords": r"$^", "must_have_field": r"$^", "max_scans": 0,
            "singleton": args[0], "path": args[1:],
            "depth": opts["--depth"], "samples": opts["--samples"],
            "state": "whatever the path needs",
        }
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
        "targets": json.dumps(spec.get("targets", "")),
        "singleton": json.dumps(spec.get("singleton", "Gallop.WorkDataManager")),
        "depth": spec.get("depth", 4),
        "path": json.dumps(spec.get("path", [])),
        "samples": spec.get("samples", 2),
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
