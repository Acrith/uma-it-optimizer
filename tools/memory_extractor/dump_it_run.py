"""IT-run extractor — dumps the current Training Log to JSON.

Just run it (double-click the .exe, or `python dump_it_run.py`).
No arguments needed:
- Auto-detects the game process
- Waits patiently if the game isn't running yet
- Auto-names the output JSON with a timestamp + scenario + uma id
- Saves into a ``runs/`` folder next to the script/exe

Whole thing is read-only (same technique UmaExtractor uses for the
veteran list, aimed at IT-run data instead). Class layout tied to the
2026-07 Global Steam build.
"""
from __future__ import annotations
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# When packaged with PyInstaller, __file__ is inside a temp extraction
# dir; sys.executable points at the .exe next to which we want to write
# runs. Use that as the anchor when frozen, else the script's own dir.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

BRIDGE_JS = BASE_DIR / "vendor" / "il2cpp_bridge.js"
# When frozen, bridge is bundled into the exe and extracted here:
if getattr(sys, "frozen", False):
    BRIDGE_JS = Path(sys._MEIPASS) / "vendor" / "il2cpp_bridge.js"  # type: ignore[attr-defined]

RUNS_DIR = BASE_DIR / "runs"
PROCESS_NAME = "UmamusumePrettyDerby.exe"
WAIT_POLL_SECONDS = 2.0
WAIT_MAX_SECONDS = 300  # 5 min — plenty of time to launch + navigate

AGENT_TAIL = r"""
setTimeout(() => {
  Il2Cpp.perform(() => {
    send({type: 'init'});
    const mainAsm = Il2Cpp.domain.assembly('umamusume').image;
    const httpAsm = Il2Cpp.domain.assembly('umamusume.Http').image;

    function tryDecodeOI(v) {
      try { return (v.field('hiddenValue').value ^ v.field('currentCryptoKey').value) | 0; }
      catch (e) { return null; }
    }

    function walk(v, typeName, depth) {
      if (v === null || v === undefined) return null;
      if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return v;
      if (typeName === 'System.String') return v.content !== undefined ? v.content : String(v);
      if (typeName === 'System.Int64' || typeName === 'System.UInt64') {
        try { return v.toString(); } catch (e) { return String(v); }
      }
      const oi = tryDecodeOI(v);
      if (oi !== null) return oi;
      if (typeName === 'Gallop.ObscuredIdleSingleModeSignedInt' && v.field) {
        const s = tryDecodeOI(v.field('<Sign>k__BackingField').value);
        const val = tryDecodeOI(v.field('<Value>k__BackingField').value);
        if (typeof s === 'number' && typeof val === 'number') return s < 0 ? -val : val;
      }
      if (typeName && typeName.endsWith('[]')) {
        try {
          const elemType = typeName.slice(0, -2);
          const out = [];
          for (let i = 0; i < v.length; i++) out.push(walk(v.get(i), elemType, depth + 1));
          return out;
        } catch (e) { return '<arr-err>'; }
      }
      if (depth < 3 && v.class) {
        const out = {};
        v.class.fields.forEach(f => {
          if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
          try { out[f.name] = walk(v.field(f.name).value, f.type.name, depth + 1); }
          catch (e) { out[f.name] = '<err>'; }
        });
        return out;
      }
      return '<' + typeName + '>';
    }

    function dumpAll(cls, label) {
      try {
        const insts = Il2Cpp.gc.choose(cls);
        const out = insts.map(inst => walk(inst, cls.type.name, 0));
        send({type: 'dump', label: label, count: insts.length, data: out});
      } catch (e) {
        send({type: 'dump_err', label: label, err: e.message});
      }
    }

    // SingleModeChara — enumerate all, then pick the instance most likely
    // to represent the *completed* run: prefer highest fans, tie-break by
    // chara_grade, then 5-stat sum. Also emits an smc_diag message with
    // every candidate's key fields so we can debug wrong-instance issues
    // (e.g. Grand Live keeping a pre-training instance alive alongside).
    const smcCls = httpAsm.class('Gallop.SingleModeChara');
    const smcs = Il2Cpp.gc.choose(smcCls);
    const walked = smcs.map(inst => {
      try { return walk(inst, smcCls.type.name, 0); }
      catch (e) { return null; }
    }).filter(w => w !== null);

    const diag = walked.map(w => ({
      scenario_id: w.scenario_id, chara_grade: w.chara_grade, fans: w.fans,
      speed: w.speed, stamina: w.stamina, power: w.power, wiz: w.wiz, guts: w.guts,
      support_card_count: (w.support_card_array || []).length,
    }));
    send({type: 'smc_diag', total: smcs.length, candidates: diag});

    const scored = walked.map((w, idx) => ({
      w: w, idx: idx,
      hasDeck: (w.support_card_array || []).length > 0,
      fans: (typeof w.fans === 'number' ? w.fans : 0),
      charaGrade: (typeof w.chara_grade === 'number' ? w.chara_grade : 0),
      statSum: ['speed','stamina','power','wiz','guts']
        .reduce((s, k) => s + (typeof w[k] === 'number' ? w[k] : 0), 0),
    }));
    const withDeck = scored.filter(s => s.hasDeck);
    const pool = withDeck.length > 0 ? withDeck : scored;
    pool.sort((a, b) =>
      (b.fans - a.fans) || (b.charaGrade - a.charaGrade) || (b.statSum - a.statSum)
    );
    const picked = pool[0];

    if (picked) send({type: 'dump', label: 'SingleModeChara', count: 1, data: [picked.w]});
    else        send({type: 'dump', label: 'SingleModeChara', count: 0, data: []});

    dumpAll(mainAsm.class('Gallop.ObscuredIdleSingleModeGainInfo'), 'GainInfo');
    dumpAll(mainAsm.class('Gallop.ObscuredIdleSingleModeSupportCardGainInfo'), 'SupportCardGainInfo');
    dumpAll(mainAsm.class('Gallop.ObscuredIdleSingleModeSuccessionFactorGainInfo'), 'SuccessionFactorGainInfo');
    dumpAll(httpAsm.class('Gallop.SingleRaceHistory'), 'RaceHistory');
    dumpAll(httpAsm.class('Gallop.IdleSingleModeRaceHistory'), 'IdleSingleModeRaceHistory');

    send({type: 'done'});
  }).catch(e => send({type: 'perform_err', err: e.message}));
});
"""


def _find_process_pid() -> int | None:
    """Return the PID of a running game process, or None if not found."""
    import frida
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == PROCESS_NAME.lower():
            return proc.pid
    return None


def _wait_for_process() -> int:
    """Poll for the game process. Returns PID once found, exits after
    WAIT_MAX_SECONDS."""
    print(f"Looking for {PROCESS_NAME}...")
    deadline = time.monotonic() + WAIT_MAX_SECONDS
    dot_count = 0
    while time.monotonic() < deadline:
        pid = _find_process_pid()
        if pid is not None:
            if dot_count > 0:
                print()  # newline after dots
            print(f"[+] Found game process (PID {pid})")
            return pid
        if dot_count == 0:
            print("Game not running. Please launch it, then navigate to a Training Log.")
            print("Waiting", end="", flush=True)
        else:
            print(".", end="", flush=True)
        dot_count += 1
        time.sleep(WAIT_POLL_SECONDS)
    print(f"\n[X] Timed out after {WAIT_MAX_SECONDS}s waiting for the game. Aborting.")
    sys.exit(2)


def _extract(pid: int) -> dict:
    """Attach to the process, run the agent, collect the messages."""
    import frida
    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT_TAIL

    result: dict = {}
    done = [False]

    def on_msg(msg, _data):
        if msg["type"] != "send":
            return
        p = msg["payload"]
        t = p.get("type")
        if t == "init":
            print("[+] IL2CPP ready, walking classes...")
        elif t == "dump":
            print(f"    {p['label']}: {p['count']} instance(s)")
            result[p["label"]] = p["data"]
        elif t == "smc_diag":
            n = p.get("total", 0)
            cands = p.get("candidates", []) or []
            result["_smc_diag"] = cands
            if n > 1:
                print(f"    [SMC] {n} SingleModeChara instances found — picking best by fans:")
                for i, c in enumerate(cands):
                    ss = sum((c.get(k) or 0) for k in ("speed", "stamina", "power", "wiz", "guts"))
                    print(f"        #{i}: fans={c.get('fans','?')} grade={c.get('chara_grade','?')} "
                          f"stat_sum={ss} deck={c.get('support_card_count', 0)}")
            elif n == 1:
                c = cands[0] if cands else {}
                print(f"    [SMC] 1 SingleModeChara: fans={c.get('fans','?')} "
                      f"grade={c.get('chara_grade','?')} deck={c.get('support_card_count', 0)}")
            else:
                print("    [SMC] 0 SingleModeChara instances found (game not on Training Log?)")
        elif t == "dump_err":
            print(f"    [!] {p['label']}: {p['err']}")
        elif t == "done":
            done[0] = True
        elif t == "perform_err":
            print(f"[X] IL2CPP error: {p['err']}")
            done[0] = True

    script = session.create_script(src)
    script.on("message", on_msg)
    script.load()

    for _ in range(120):  # up to 60s
        if done[0]:
            break
        time.sleep(0.5)
    session.detach()
    return result


def _output_name(result: dict) -> str:
    """Auto-name: <local-ts>_scen<N>_uma<N>.json — matches the user's
    hand-naming convention in IT-references/ and stays sortable."""
    smc_list = result.get("SingleModeChara") or []
    scenario_id = "?"
    card_id = "?"
    if smc_list:
        smc = smc_list[0]
        scenario_id = smc.get("scenario_id", "?")
        card_id = smc.get("card_id", "?")
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{ts}_scen{scenario_id}_uma{card_id}.json"


def _looks_empty(result: dict) -> bool:
    """No SingleModeChara = user isn't on a Training Log screen."""
    return not (result.get("SingleModeChara") and len(result["SingleModeChara"]) > 0)


def main() -> int:
    print("=== IT-run extractor ===")
    print(f"Output folder: {RUNS_DIR}")
    print()

    if not BRIDGE_JS.exists():
        print(f"[X] Missing bridge bundle at {BRIDGE_JS}")
        print(f"[X] If running from source, run `python setup.py` first.")
        return 3

    try:
        import frida  # noqa: F401
    except ImportError:
        print("[X] `frida` Python module not installed.")
        print("[X] If running from source: pip install frida frida-tools")
        return 3

    pid = _wait_for_process()

    try:
        result = _extract(pid)
    except Exception as e:
        print(f"\n[X] Extraction failed: {e}")
        traceback.print_exc()
        return 4

    if _looks_empty(result):
        print()
        print("[!] Extraction ran but found no active Training Log data.")
        print("[!] Are you sure you're on the Training Log screen right now?")
        print("[!] (Complete an IT run, or open a saved run's Log entry.)")
        return 5

    RUNS_DIR.mkdir(exist_ok=True)
    out_path = RUNS_DIR / _output_name(result)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print()
    print(f"[OK] Saved: {out_path}")
    print(f"     Size: {out_path.stat().st_size // 1024} KB")
    smc = result["SingleModeChara"][0]
    print(f"    Trainee: card_id={smc.get('card_id')}, scenario={smc.get('scenario_id')}")
    print(f"    Support cards: {len(smc.get('support_card_array', []) or [])}")
    print(f"    Races run: {len(result.get('RaceHistory', []) or [])}")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n[X] Aborted by user")
        code = 130
    if getattr(sys, "frozen", False):
        # Keep the console window open when double-clicked
        input("\nPress Enter to close...")
    sys.exit(code)
