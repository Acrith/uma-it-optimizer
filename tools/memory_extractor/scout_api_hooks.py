"""Scout: find server-response handler / deserializer functions to hook.

Cheap name-enumeration pass (no gc.choose, no game freeze) that lists:
- Classes in the umamusume.Http assembly that look like API response
  types (their names match /Response$|ResponseTask|Handler|Receive/).
- Methods on those classes with names suggesting response handling
  (OnReceive, HandleResponse, Deserialize, Callback, Handle, etc.).

Second phase (opt-in via --phase=hook) attaches Frida Interceptor to
the top candidates and logs each invocation's argument types + first
few bytes of any string/array arg — proof that we can catch API
payloads mid-run and see what shape they take.

Usage:
    python scout_api_hooks.py --phase=list
    python scout_api_hooks.py --phase=hook   # only after picking targets
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"


AGENT_HOOK_SAFE = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;
      // Full IT lifecycle — responses (server → client) AND requests
      // (client → server via Serialize). Setup flow includes PreStart
      // + Start; polling would use Status/CheckProgress; end submits
      // Result. Adding *Request formatters catches what the client
      // sends when the user picks a deck / starts a run.
      const RESPONSE_TARGETS = [
        'Gallop.MsgPack.Formatters.IdleSingleModePreStartResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeStartResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeStatusResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeCheckProgressLogResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeEndResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeResultResponseFormatter',
      ];
      const REQUEST_TARGETS = [
        'Gallop.MsgPack.Formatters.IdleSingleModePreStartRequestFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeStartRequestFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeStatusRequestFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeCheckProgressLogRequestFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeEndRequestFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeResultRequestFormatter',
      ];

      // Defensive walker — every field wrapped in try/catch, capped
      // depth, capped array length. NEVER mutates the input.
      function walkSafe(v, depth, maxDepth) {
        try {
          if (depth > maxDepth) return '<max-depth>';
          if (v === null || v === undefined) return null;
          if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return v;
          if (v.content !== undefined) return v.content;
          if (v.length !== undefined && v.get !== undefined) {
            const out = [];
            const N = Math.min(v.length, 12);
            for (let i = 0; i < N; i++) {
              try { out.push(walkSafe(v.get(i), depth + 1, maxDepth)); }
              catch (e) { out.push('<get-err>'); }
            }
            if (v.length > N) out.push('… (+' + (v.length - N) + ' more)');
            return out;
          }
          if (v.class && v.class.fields) {
            const obj = { '__type__': (v.class.type && v.class.type.name) || '' };
            v.class.fields.forEach(f => {
              if (f.isStatic || f.isLiteral) return;
              try {
                obj[f.name] = walkSafe(v.field(f.name).value, depth + 1, maxDepth);
              } catch (e) { obj[f.name] = '<field-err>'; }
            });
            return obj;
          }
          return '<opaque>';
        } catch (e) {
          return '<walk-err: ' + e.message + '>';
        }
      }

      let hookCount = 0;

      // Response side — Deserialize onLeave observes the decoded
      // C# object returned to the game after the server responds.
      RESPONSE_TARGETS.forEach(fqn => {
        let klass;
        try { klass = httpImg.class(fqn); } catch (e) {}
        if (!klass) { send({type: 'text', text: '[SKIP-resp] ' + fqn}); return; }
        klass.methods.forEach(m => {
          if (m.name !== 'Deserialize') return;
          try {
            const targetName = fqn.split('.').pop();
            Interceptor.attach(m.virtualAddress, {
              onLeave(retval) {
                try {
                  let walked;
                  try {
                    let obj;
                    try { obj = new Il2Cpp.Object(retval); }
                    catch (e) { obj = Il2Cpp.Object.fromRaw ? Il2Cpp.Object.fromRaw(retval) : null; }
                    walked = obj ? walkSafe(obj, 0, 8) : '<cannot-wrap-retval>';
                  } catch (e) { walked = '<wrap-err: ' + e.message + '>'; }
                  send({type: 'header', text: '=== RESPONSE FIRED: ' + targetName + ' ==='});
                  const pretty = JSON.stringify(walked, null, 2);
                  pretty.split('\n').forEach(l => send({type: 'text', text: l}));
                } catch (e) {
                  send({type: 'text', text: 'onLeave resp err: ' + e.message});
                }
              }
            });
            hookCount++;
            send({type: 'text', text: '[OK-resp] ' + fqn + '.Deserialize @ ' + m.virtualAddress});
          } catch (e) {
            send({type: 'text', text: '[ERR-resp] ' + fqn + '.Deserialize: ' + e.message});
          }
        });
      });

      // Request side — Serialize takes (writer, value) so args[1] is
      // the C# object about to be sent. Hook onEnter to inspect it
      // before the game writes bytes to the network. We DON'T touch
      // args or return — pure observation.
      REQUEST_TARGETS.forEach(fqn => {
        let klass;
        try { klass = httpImg.class(fqn); } catch (e) {}
        if (!klass) { send({type: 'text', text: '[SKIP-req] ' + fqn}); return; }
        klass.methods.forEach(m => {
          if (m.name !== 'Serialize') return;
          try {
            const targetName = fqn.split('.').pop();
            Interceptor.attach(m.virtualAddress, {
              onEnter(args) {
                try {
                  // Serialize signature typically: Serialize(this, writer, value, options)
                  // or Serialize(writer, value, options) as static.
                  // The C# object is one of the later args — try args[1]
                  // through args[3] to find one wrappable.
                  let obj = null;
                  for (let i = 1; i < Math.min(args.length || 4, 4); i++) {
                    try {
                      const cand = new Il2Cpp.Object(args[i]);
                      if (cand && cand.class && cand.class.fields) { obj = cand; break; }
                    } catch (e) {}
                  }
                  const walked = obj ? walkSafe(obj, 0, 8) : '<no-wrappable-arg>';
                  send({type: 'header', text: '=== REQUEST FIRED: ' + targetName + ' ==='});
                  const pretty = JSON.stringify(walked, null, 2);
                  pretty.split('\n').forEach(l => send({type: 'text', text: l}));
                } catch (e) {
                  send({type: 'text', text: 'onEnter req err: ' + e.message});
                }
              }
            });
            hookCount++;
            send({type: 'text', text: '[OK-req] ' + fqn + '.Serialize @ ' + m.virtualAddress});
          } catch (e) {
            send({type: 'text', text: '[ERR-req] ' + fqn + '.Serialize: ' + e.message});
          }
        });
      });
      send({type: 'text', text: 'installed ' + hookCount + ' observer(s); waiting for API traffic...'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 300);
"""


AGENT_HOOK = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;

      // Formatters we want to catch — MessagePack code-gen: each response
      // type has a Formatter with Deserialize(reader, options) that
      // returns the typed C# object. Hooking there gives us the fully-
      // decoded payload without touching MessagePack bytes ourselves.
      const TARGETS = [
        'Gallop.MsgPack.Formatters.IdleSingleModeCheckProgressLogResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeStatusResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeEndResponseFormatter',
        'Gallop.MsgPack.Formatters.IdleSingleModeResultResponseFormatter',
      ];

      function walkDeep(v, depth, maxDepth) {
        if (depth > maxDepth) return '<max-depth>';
        if (v === null || v === undefined) return null;
        if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return v;
        if (v.content !== undefined) return v.content;
        if (v.length !== undefined && v.get !== undefined) {
          const out = [];
          const N = Math.min(v.length, 8);
          for (let i = 0; i < N; i++) {
            try { out.push(walkDeep(v.get(i), depth + 1, maxDepth)); }
            catch (e) { out.push('<get-err>'); }
          }
          if (v.length > N) out.push('… (+' + (v.length - N) + ' more)');
          return out;
        }
        if (v.class && v.class.fields) {
          const obj = { '__type__': (v.class.type && v.class.type.name) || '' };
          v.class.fields.forEach(f => {
            if (f.isStatic || f.isLiteral) return;
            try {
              obj[f.name] = walkDeep(v.field(f.name).value, depth + 1, maxDepth);
            } catch (e) { obj[f.name] = '<field-err>'; }
          });
          return obj;
        }
        return '<opaque>';
      }

      let hookCount = 0;
      TARGETS.forEach(fqn => {
        let klass;
        try { klass = httpImg.class(fqn); } catch (e) {
          send({type: 'text', text: '[SKIP] ' + fqn + ' not found'});
          return;
        }
        if (!klass) { send({type: 'text', text: '[SKIP] ' + fqn + ' null'}); return; }
        // Find Deserialize methods
        klass.methods.forEach(m => {
          if (m.name !== 'Deserialize') return;
          try {
            const targetName = fqn.split('.').pop();
            const origImpl = m.implementation;
            m.implementation = function (...args) {
              const ret = origImpl.apply(this, args);
              try {
                send({type: 'header', text: '=== HOOK FIRED: ' + targetName + ' ==='});
                const walked = walkDeep(ret, 0, 8);
                const pretty = JSON.stringify(walked, null, 2);
                pretty.split('\n').forEach(l => send({type: 'text', text: l}));
              } catch (e) {
                send({type: 'text', text: 'hook post-process err: ' + e.message});
              }
              return ret;
            };
            hookCount++;
            send({type: 'text', text: '[OK] hooked ' + fqn + '.Deserialize'});
          } catch (e) {
            send({type: 'text', text: '[ERR] ' + fqn + '.Deserialize: ' + e.message});
          }
        });
      });
      send({type: 'text', text: 'installed ' + hookCount + ' hook(s); waiting for API traffic...'});
    } catch (e) {
      send({type: 'fatal', err: e.message, stack: e.stack});
    }
  });
}, 300);
"""


AGENT_LIST = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    try {
      send({type: 'init'});
      const mainImg = Il2Cpp.domain.assembly('umamusume').image;
      const httpImg = Il2Cpp.domain.assembly('umamusume.Http').image;

      // Class filter — API response types + web-request infra.
      const CLASS_RE = /(Response|WebApi|WebRequest|ApiManager|MessagePack|HttpClient|Client\b|Sender|Receiver|Deserializ|Serializ)/i;
      const CLASS_EXCLUDE = /Dialog|Parts|View$|Controller|<>c|Loop|Scroll|Motion|Panel|Bg\b|Anim|Sequence|Impl$/;

      // Method filter — response handling / deserialization entry points.
      const METHOD_RE = /(OnReceive|HandleResponse|OnResponse|Deserialize|Parse|Handle$|Callback|OnComplete|OnFinish)/i;

      send({type: 'header', text: '=== CANDIDATE CLASSES (both assemblies) ==='});
      const candidates = [];
      [
        { name: 'umamusume.Http', img: httpImg },
        { name: 'umamusume', img: mainImg },
      ].forEach(({ name, img }) => {
        const bucket = [];
        img.classes.forEach(k => {
          const n = (k.type && k.type.name) || '<?>';
          if (CLASS_RE.test(n) && !CLASS_EXCLUDE.test(n)) {
            bucket.push({ img: name, klass: k, name: n });
          }
        });
        bucket.sort((a, b) => a.name.localeCompare(b.name));
        send({type: 'text', text: ''});
        send({type: 'text', text: '  --- [' + name + '] ' + bucket.length + ' names ---'});
        bucket.forEach(({ name: n }) => send({type: 'text', text: '    ' + n}));
        candidates.push(...bucket);
      });
      send({type: 'text', text: ''});
      send({type: 'text', text: '  Total candidate classes: ' + candidates.length});

      // For each candidate class, list its methods that match the
      // response-handling pattern. Method names hint at the hook point.
      send({type: 'header', text: '=== INTERESTING METHODS ON CANDIDATE CLASSES ==='});
      let methodCount = 0;
      candidates.forEach(({ img, klass, name }) => {
        try {
          const matches = [];
          klass.methods.forEach(m => {
            if (METHOD_RE.test(m.name)) {
              matches.push(m.name);
            }
          });
          if (matches.length) {
            send({type: 'text', text: ''});
            send({type: 'text', text: '  [' + img + '] ' + name});
            matches.forEach(mn => send({type: 'text', text: '    .' + mn}));
            methodCount += matches.length;
          }
        } catch (e) {}
      });
      send({type: 'text', text: ''});
      send({type: 'text', text: '  Total interesting methods: ' + methodCount});

      send({type: 'done'});
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
    ap.add_argument("--phase", choices=("list", "hook", "observe"), default="list",
                    help="'hook' = OLD unsafe m.implementation swap (broke game). "
                         "'observe' = Interceptor.attach onLeave — safe.")
    ap.add_argument("--seconds", type=int, default=90,
                    help="How long to keep hooks attached (hook mode only)")
    args = ap.parse_args()

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
                print("[+] IL2CPP ready, scouting API surface...")
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
    if args.phase == "list":
        agent = AGENT_LIST
    elif args.phase == "observe":
        agent = AGENT_HOOK_SAFE
    else:
        agent = AGENT_HOOK
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + agent
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()

    if args.phase == "list":
        deadline = time.time() + 60
        while time.time() < deadline and not done["flag"]:
            time.sleep(0.1)
    else:
        # Hook mode — stay attached for a fixed window, log every
        # incoming payload the hooks catch. No done flag from agent.
        print(f"[+] listening for API responses for {args.seconds}s...")
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            time.sleep(0.1)
        print("[+] window elapsed; detaching")
    session.detach()
    return 0


if __name__ == "__main__":
    sys.exit(main())
