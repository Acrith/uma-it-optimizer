"""Master-data class exploration probe.

Enumerates IL2CPP classes in the umamusume + umamusume.Http assemblies
that look master-data-shaped (Master*, *Data, *Info, etc.), counts how
many live instances each has in memory, and reports the top hits.

Run this against the game (title screen is fine — masters load early)
to figure out which classes to actually dump. This is a dev tool, not a
user-facing exe — no packaging, no wait loop, just attach → probe → exit.

Usage:
    python explore_masters.py

Writes a masters_probe_<timestamp>.json next to this script with the
full ranked list, and prints the top ~40 to console for quick reading.
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
PROCESS_NAME = "UmamusumePrettyDerby.exe"

AGENT = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    send({type: 'init'});

    // Assemblies known to hold Umamusume game logic. Add here if masters
    // turn out to live elsewhere (e.g. 'umamusume.Master' — some Cygames
    // games split masters into a dedicated assembly).
    const asmNames = ['umamusume', 'umamusume.Http'];

    // Wide net — Cygames master classes commonly named with any of these.
    // We over-collect here and let the count filter tell us what's real.
    const INCLUDE = ['Master', 'Data', 'Skill', 'Card', 'Chara', 'Uma',
                     'Race', 'Scenario', 'Factor', 'Support', 'Manager',
                     'Provider', 'Repository', 'Dictionary'];
    // Exclude noisy request/response DTOs (data-shaped names that aren't masters)
    const EXCLUDE = ['Response', 'Request', 'Packet', 'Params', 'Payload',
                     'Result', 'Command', 'Event', 'Effect', 'Anim',
                     'Config', 'Setting', 'Buff', 'Bonus'];

    // ── Phase 1: name-filter candidates ──────────────────────────────
    const candidates = [];
    for (const asmName of asmNames) {
      let img;
      try { img = Il2Cpp.domain.assembly(asmName).image; }
      catch (e) { send({type: 'asm_err', asm: asmName, err: e.message}); continue; }

      let cls_iter;
      try { cls_iter = img.classes; }
      catch (e) { send({type: 'asm_err', asm: asmName, err: 'classes: ' + e.message}); continue; }

      for (let i = 0; i < cls_iter.length; i++) {
        const cls = cls_iter[i];
        let name;
        try { name = cls.type.name; } catch (e) { continue; }
        if (!name) continue;
        // Skip generics/nested/arrays — noise
        if (name.includes('<') || name.includes('/') || name.includes('[')) continue;
        // Must match at least one INCLUDE and no EXCLUDE
        if (!INCLUDE.some(p => name.includes(p))) continue;
        if (EXCLUDE.some(p => name.includes(p))) continue;
        candidates.push({asm: asmName, name: name, klass: cls});
      }
    }
    send({type: 'phase1', total: candidates.length});

    // ── Phase 2: count live instances per candidate ──────────────────
    // gc.choose is expensive per call; batch progress so we don't look hung.
    const results = [];
    const BATCH = 25;
    for (let i = 0; i < candidates.length; i++) {
      const c = candidates[i];
      let count = 0;
      try { count = Il2Cpp.gc.choose(c.klass).length; } catch (e) { continue; }
      if (count > 0) results.push({asm: c.asm, name: c.name, count: count});
      if ((i + 1) % BATCH === 0) {
        send({type: 'progress', done: i + 1, total: candidates.length,
              found_nonzero: results.length});
      }
    }
    results.sort((a, b) => b.count - a.count);

    // ── Phase 3: also list interesting singleton-like Manager/Provider
    // classes even if instance count is 1 (they hold the master dicts)
    send({type: 'results', data: results});
    send({type: 'done'});
  }).catch(e => send({type: 'perform_err', err: e.message}));
});
"""


def _find_process_pid() -> int | None:
    import frida
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == PROCESS_NAME.lower():
            return proc.pid
    return None


def main() -> int:
    print("=== Master-data exploration probe ===")
    print()

    if not BRIDGE_JS.exists():
        print(f"[X] Missing bridge bundle at {BRIDGE_JS}")
        print(f"[X] Run `python setup.py` first.")
        return 3

    try:
        import frida
    except ImportError:
        print("[X] frida not installed. Run: pip install frida frida-tools")
        return 3

    pid = _find_process_pid()
    if pid is None:
        print(f"[X] {PROCESS_NAME} not running. Launch the game first (title screen is fine).")
        return 2
    print(f"[+] Attaching to PID {pid}")

    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT

    results: list[dict] = []
    done = [False]

    def on_msg(msg, _data):
        if msg["type"] != "send":
            return
        p = msg["payload"]
        t = p.get("type")
        if t == "init":
            print("[+] IL2CPP ready, enumerating classes...")
        elif t == "phase1":
            print(f"[+] {p['total']} candidate classes matched name filters")
            print("[+] Counting live instances (this takes ~30-60s)...")
        elif t == "progress":
            print(f"    ...{p['done']}/{p['total']} scanned, "
                  f"{p['found_nonzero']} with instances")
        elif t == "results":
            results.extend(p["data"])
        elif t == "asm_err":
            print(f"    [!] assembly {p['asm']}: {p['err']}")
        elif t == "done":
            done[0] = True
        elif t == "perform_err":
            print(f"[X] agent error: {p['err']}")
            done[0] = True

    script = session.create_script(src)
    script.on("message", on_msg)
    script.load()

    # Class enumeration + gc.choose per class can take a while
    max_wait = 240
    for _ in range(max_wait * 2):
        if done[0]:
            break
        time.sleep(0.5)
    session.detach()

    if not results:
        print()
        print("[!] Probe returned no non-zero-instance classes.")
        return 4

    # Save full output
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = BASE_DIR / f"masters_probe_{ts}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Print top hits by count
    print()
    print(f"[OK] Found {len(results)} classes with live instances")
    print(f"[OK] Full ranked list: {out.name}")
    print()
    print("Top 40 by instance count:")
    print(f"{'#':>4}  {'Instances':>10}  {'Assembly':<18}  Class")
    print("-" * 100)
    for i, r in enumerate(results[:40], 1):
        print(f"{i:>4}  {r['count']:>10}  {r['asm']:<18}  {r['name']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[X] Aborted")
        raise SystemExit(130)
