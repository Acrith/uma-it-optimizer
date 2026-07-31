"""IT-run extractor — dumps the current Training Log to JSON.

Just run it (double-click the .exe, or `python dump_it_run.py`).
No arguments needed:
- Auto-detects the game process
- Waits for the game to launch if it isn't running yet
- Waits for a *completed* Training Log to appear in memory — you can
  launch this before finishing your IT run; it polls until it sees
  valid data, then captures automatically
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
CONFIG_PATH = BASE_DIR / "uma-it-config.json"
PROCESS_NAME = "UmamusumePrettyDerby.exe"
WAIT_POLL_SECONDS = 2.0
WAIT_MAX_SECONDS = 300  # 5 min — plenty of time to launch + navigate
UPLOAD_TIMEOUT_SECONDS = 30

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

    // walk() clamps at depth 3 to keep the top-level dumps compact. For
    // parent lineage we need to reach grandparent factors (nested 4-5 levels
    // deep in TrainedCharaData → SuccessionCharaList → item → FactorDataArray).
    // Cached derived fields are skipped by name to keep the payload lean.
    const LINEAGE_SKIP_FIELDS = new Set([
      '_sortedFactorList', '_sortedFactorProfileCardList',
      '_factorListIncludingSuccession', '_sortedFactorListForProfileCard',
      '_masterCharaData', '_masterCardRarityData', '_masterCardData',
      '_favoriteData', '_cachedCreateTimeTimeStamp',
      'IsSuccessionHistoryInitialized',
      '<SuccessionHistoryList>k__BackingField',
      '<TrainedCharaDataAccessor>k__BackingField',
      '_nickNameIdArray',
    ]);
    function walkDeep(v, typeName, depth, maxDepth) {
      if (v === null || v === undefined) return null;
      if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return v;
      if (typeName === 'System.String') return v.content !== undefined ? v.content : String(v);
      if (typeName === 'System.Int64' || typeName === 'System.UInt64') {
        try { return v.toString(); } catch (e) { return String(v); }
      }
      const oi = tryDecodeOI(v);
      if (oi !== null) return oi;
      if (typeName && typeName.endsWith('[]')) {
        const elemType = typeName.slice(0, -2);
        const out = [];
        let n = 0;
        try { n = v.length; } catch (e) { return '<arr-len-err:' + e.message + '>'; }
        for (let i = 0; i < n; i++) {
          try { out.push(walkDeep(v.get(i), elemType, depth + 1, maxDepth)); }
          catch (e) { out.push('<elem-err:' + e.message + '>'); }
        }
        return out;
      }
      if (depth < maxDepth && v.class) {
        const out = {};
        try {
          v.class.fields.forEach(f => {
            if (f.isStatic || f.isLiteral || f.isThreadStatic) return;
            if (LINEAGE_SKIP_FIELDS.has(f.name)) return;
            try { out[f.name] = walkDeep(v.field(f.name).value, f.type.name, depth + 1, maxDepth); }
            catch (e) { out[f.name] = '<err>'; }
          });
        } catch (e) {}
        return out;
      }
      return '<' + typeName + '>';
    }

    // Direct parents live in `Gallop.WorkTrainedCharaData.TrainedCharaData`,
    // a NESTED class not accessible via image.class('...') — iterate the
    // class list once and match by name.
    let _tcdClassCache = null;
    function findTcdClass() {
      if (_tcdClassCache) return _tcdClassCache;
      const it = mainAsm.classes;
      for (let i = 0; i < it.length; i++) {
        const cls = it[i];
        let n; try { n = cls.type.name; } catch (e) { continue; }
        if (n === 'Gallop.WorkTrainedCharaData.TrainedCharaData') {
          _tcdClassCache = cls; return cls;
        }
      }
      return null;
    }
    function decodeTcdId(t) {
      try {
        const w = t.field('_id').value;
        if (typeof w === 'number') return w;
        const v = tryDecodeOI(w); if (v !== null) return v;
      } catch (e) {}
      return null;
    }

    // Filter TrainedCharaData to the two direct parents referenced by
    // SingleModeChara.succession_trained_chara_id_1 / _2. Walks each deep
    // enough for grandparents (max depth 5).
    function dumpParents(id1, id2) {
      const tcd = findTcdClass();
      if (!tcd) { send({type: 'dump_err', label: 'Parents', err: 'no TrainedCharaData class'}); return; }
      try {
        const insts = Il2Cpp.gc.choose(tcd);
        const out = [];
        const wanted = new Set([id1, id2].filter(x => typeof x === 'number' && x > 0));
        for (let i = 0; i < insts.length && out.length < 2; i++) {
          const t = insts[i];
          const id = decodeTcdId(t);
          if (id !== null && wanted.has(id)) {
            // depth 6 is the minimum that reaches grandparent FactorData
            // scalar fields (TrainedCharaData → SuccessionCharaList →
            // _items → SuccessionCharaData → FactorDataArray → FactorData).
            out.push(walkDeep(t, 'Gallop.WorkTrainedCharaData.TrainedCharaData', 0, 6));
          }
        }
        send({type: 'dump', label: 'Parents', count: out.length, data: out});
      } catch (e) {
        send({type: 'dump_err', label: 'Parents', err: e.message});
      }
    }

    // ── SingleModeChara probe ─────────────────────────────────────────
    // Enumerate all live instances, pick the one most likely to represent
    // the *completed* run: prefer highest fans, tie-break by chara_grade,
    // then 5-stat sum. Returns { picked, totalCount, candidates } — where
    // picked has {w, fans, charaGrade, statSum} or is null if none exist.
    const smcCls = httpAsm.class('Gallop.SingleModeChara');
    function probeSmc() {
      const smcs = Il2Cpp.gc.choose(smcCls);
      const walked = smcs.map(inst => {
        try { return walk(inst, smcCls.type.name, 0); }
        catch (e) { return null; }
      }).filter(w => w !== null);
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
      return {
        picked: pool[0] || null,
        totalCount: smcs.length,
        candidates: walked.map(w => ({
          scenario_id: w.scenario_id, chara_grade: w.chara_grade, fans: w.fans,
          speed: w.speed, stamina: w.stamina, power: w.power, wiz: w.wiz, guts: w.guts,
          support_card_count: (w.support_card_array || []).length,
        })),
      };
    }

    // ── Poll loop ─────────────────────────────────────────────────────
    // Instead of dumping immediately (which is timing-sensitive — the
    // wrong screen produces pre-training data), poll SingleModeChara
    // until it looks like a completed career. Then do the full dump in
    // one shot. Player can launch the extractor before navigating to
    // the Training Log; it'll wait.
    const MIN_FANS_FOR_VALID = 100;   // any completed IT has thousands
    const MIN_GRADE_FOR_VALID = 2;    // 1 = fresh template, 10 = completed
    const POLL_INTERVAL_MS = 3000;
    const MAX_POLLS = 100;            // 100 × 3s = 5 min

    let pollNum = 0;
    function pollOnce() {
      pollNum++;
      const probe = probeSmc();
      if (!probe.picked) {
        send({type: 'poll', pollNum: pollNum, ok: false, reason: 'no_smc',
              total_smc: probe.totalCount});
        if (pollNum >= MAX_POLLS) { send({type: 'timeout'}); return; }
        setTimeout(pollOnce, POLL_INTERVAL_MS);
        return;
      }
      const p = probe.picked;
      const valid = p.fans >= MIN_FANS_FOR_VALID && p.charaGrade >= MIN_GRADE_FOR_VALID;
      if (!valid) {
        send({type: 'poll', pollNum: pollNum, ok: false, reason: 'pre_training',
              fans: p.fans, chara_grade: p.charaGrade, stat_sum: p.statSum,
              total_smc: probe.totalCount});
        if (pollNum >= MAX_POLLS) { send({type: 'timeout'}); return; }
        setTimeout(pollOnce, POLL_INTERVAL_MS);
        return;
      }
      // Valid! Full extraction now.
      send({type: 'poll', pollNum: pollNum, ok: true,
            fans: p.fans, chara_grade: p.charaGrade, stat_sum: p.statSum});
      send({type: 'smc_diag', total: probe.totalCount, candidates: probe.candidates});
      send({type: 'dump', label: 'SingleModeChara', count: 1, data: [p.w]});
      dumpAll(mainAsm.class('Gallop.ObscuredIdleSingleModeGainInfo'), 'GainInfo');
      dumpAll(mainAsm.class('Gallop.ObscuredIdleSingleModeSupportCardGainInfo'), 'SupportCardGainInfo');
      dumpAll(mainAsm.class('Gallop.ObscuredIdleSingleModeSuccessionFactorGainInfo'), 'SuccessionFactorGainInfo');
      dumpAll(httpAsm.class('Gallop.SingleRaceHistory'), 'RaceHistory');
      dumpAll(httpAsm.class('Gallop.IdleSingleModeRaceHistory'), 'IdleSingleModeRaceHistory');
      // Direct parents (+ nested grandparents) — needed for compat + lineage panel.
      dumpParents(p.w.succession_trained_chara_id_1, p.w.succession_trained_chara_id_2);
      send({type: 'done'});
    }
    pollOnce();
  }).catch(e => send({type: 'perform_err', err: e.message}));
});
"""


def _find_process_pid() -> int | None:
    """Return the PID of a running game process, or None if not found.

    Windows: frida reports the process's .exe name directly, so a
    case-insensitive match on PROCESS_NAME works.

    Linux (wine/proton): the game runs inside a wine loader Linux
    process, and frida reports that loader's name (usually
    ``wine64-preloader`` or ``wine``), NOT the .exe. The .exe name
    lives only in the process cmdline. Fall back to a /proc scan
    for that case."""
    import frida
    for proc in frida.get_local_device().enumerate_processes():
        if proc.name.lower() == PROCESS_NAME.lower():
            return proc.pid
    if sys.platform.startswith("linux"):
        return _find_wine_hosted_process_pid()
    return None


def _find_wine_hosted_process_pid() -> int | None:
    """Locate the wine/proton-hosted game process. Two strategies —
    the game IS whichever process the SECOND strategy finds, but the
    first is faster when it works:

    1. cmdline scan — matches processes whose argv contains an entry
       whose basename equals the exe. Fast, but fails if the game
       rewrote its own argv after launch (Unity/IL2CPP builds do this
       on some setups — the wine wrapper processes retain the arg,
       but the actual game process's /proc/pid/cmdline goes empty).
    2. maps scan — matches processes whose memory map lists a file
       ending in the exe name. The game .exe HAS to be mapped for
       the process to be running, so this catches the case above.

    maps-scan hits win over cmdline-scan hits (a wine wrapper only
    has the exe in its argv, never mapped into its address space, so
    a maps hit unambiguously identifies the actual game process)."""
    from pathlib import Path

    exe_needle = PROCESS_NAME.lower().encode()
    cmdline_matches: list[int] = []
    maps_matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)

        # Strategy 1: cmdline
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            raw = b""
        if raw and exe_needle in raw.lower():
            argv = [a for a in raw.split(b"\x00") if a]
            for arg in argv:
                tail = arg.rsplit(b"/", 1)[-1].rsplit(b"\\", 1)[-1]
                if tail.lower() == exe_needle:
                    cmdline_matches.append(pid)
                    break

        # Strategy 2: memory-mapped files (survives argv rewriting).
        # /proc/pid/maps is line-per-mapping; last whitespace-separated
        # field is the file path (if any). Match basename against exe.
        try:
            maps_raw = (entry / "maps").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if exe_needle not in maps_raw.lower():
            continue
        for line in maps_raw.splitlines():
            # Only interested in lines whose last field is a path.
            parts = line.rsplit(None, 1)
            if len(parts) < 2:
                continue
            path = parts[-1]
            tail = path.rsplit(b"/", 1)[-1].rsplit(b"\\", 1)[-1]
            if tail.lower() == exe_needle:
                maps_matches.append(pid)
                break

    # Prefer maps hits — those are unambiguously the game (the exe
    # is mapped into that process's address space). cmdline hits
    # include wine wrappers (reaper, srt-bwrap, python3 proton, etc.)
    # that only reference the exe in their argv without loading it.
    if maps_matches:
        return max(maps_matches)
    if cmdline_matches:
        return max(cmdline_matches)
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
    if sys.platform.startswith("linux"):
        # On Linux the game runs under wine — most 'game not found'
        # cases are either (a) the wine process is running but frida
        # can't attach because ptrace is locked down, or (b) frida
        # sees the wine loader but the game exe never appears in any
        # cmdline (e.g. game crashed early). Point users at both.
        print("[!] Linux hint: make sure the game is actually running (check")
        print("    `ps aux | grep -i umamusume`). If it is but this script")
        print("    still can't see it, ptrace may be restricted — try:")
        print("      sudo sysctl kernel.yama.ptrace_scope=0")
        print("    (or add kernel.yama.ptrace_scope=0 to /etc/sysctl.d/).")
    sys.exit(2)


def _extract(pid: int) -> dict:
    """Attach to the process, run the agent, collect the messages.

    Waits up to ~5 minutes for the agent's poll loop to find valid data
    (a completed-looking SingleModeChara). This lets the player launch
    the extractor before navigating to the Training Log — it just waits."""
    import frida
    session = frida.attach(pid)
    src = BRIDGE_JS.read_text(encoding="utf-8") + "\n" + AGENT_TAIL

    result: dict = {}
    done = [False]
    timed_out = [False]

    def on_msg(msg, _data):
        if msg["type"] != "send":
            return
        p = msg["payload"]
        t = p.get("type")
        if t == "init":
            print("[+] IL2CPP ready. Watching for Training Log data...")
        elif t == "poll":
            n = p.get("pollNum", 0)
            reason = p.get("reason", "")
            if p.get("ok"):
                print(f"    [poll #{n}] Training Log data ready "
                      f"(fans={p.get('fans')} grade={p.get('chara_grade')} "
                      f"stat_sum={p.get('stat_sum')})")
            elif reason == "no_smc":
                print(f"    [poll #{n}] no SingleModeChara in memory "
                      f"— not in an IT scenario yet?")
            elif reason == "pre_training":
                print(f"    [poll #{n}] pre-training state "
                      f"(fans={p.get('fans')} grade={p.get('chara_grade')} "
                      f"stat_sum={p.get('stat_sum')} instances={p.get('total_smc')}) "
                      f"— navigate to Training Log to trigger capture")
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
                print("    [SMC] 0 SingleModeChara instances found")
        elif t == "dump_err":
            print(f"    [!] {p['label']}: {p['err']}")
        elif t == "done":
            done[0] = True
        elif t == "timeout":
            timed_out[0] = True
            done[0] = True
        elif t == "perform_err":
            print(f"[X] IL2CPP error: {p['err']}")
            done[0] = True

    script = session.create_script(src)
    script.on("message", on_msg)
    script.load()

    # Agent's poll loop is 100 × 3s = 5 min; add generous buffer for
    # full walk after valid state detected.
    max_wait_seconds = 5 * 60 + 60
    for _ in range(max_wait_seconds * 2):
        if done[0]:
            break
        time.sleep(0.5)
    session.detach()
    if timed_out[0]:
        print("[X] Timed out (5 min) waiting for Training Log data to appear.")
        print("[X] Are you completing an IT run? Reach the Training Log screen and try again.")
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
    """No SingleModeChara means the poll loop timed out without ever
    seeing a completed run — either the player never reached the
    Training Log, or the game wasn't in an IT scenario at all."""
    return not (result.get("SingleModeChara") and len(result["SingleModeChara"]) > 0)


def _load_upload_config() -> dict | None:
    """Return the parsed uma-it-config.json sidecar if present and it
    has an api_token; return None otherwise. Missing or empty config
    means 'local-only mode' — extraction still runs, we just don't
    auto-upload."""
    if not CONFIG_PATH.exists():
        return None
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[!] Ignoring {CONFIG_PATH.name}: {e}")
        return None
    token = (cfg.get("api_token") or "").strip()
    if not token:
        return None
    cfg.setdefault("api_url", "https://training.umaladder.moe")
    cfg["api_token"] = token
    cfg["api_url"] = cfg["api_url"].rstrip("/")
    return cfg


def _upload_run(json_path: Path, cfg: dict) -> None:
    """POST the just-written run JSON to /api/runs with a bearer
    token. Prints outcome; never raises — the local file always
    lands, so a network hiccup can't cost the user a run. Uses
    urllib from stdlib so PyInstaller doesn't have to bundle
    requests."""
    import urllib.error
    import urllib.request

    url = f"{cfg['api_url']}/api/runs"
    body = json_path.read_bytes()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['api_token']}",
            "X-Filename": json_path.name,
            "Content-Type": "application/octet-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_SECONDS) as resp:
            status = resp.status
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8") or "{}")
        except (json.JSONDecodeError, ValueError):
            msg = {}
        if e.code == 409:
            # Server already had this run — silent-accept, not an error.
            print(f"[i] Already uploaded ({msg.get('message', 'duplicate')})")
            return
        print(f"[!] Upload failed: HTTP {e.code} — {msg.get('error', e.reason)}")
        if e.code == 401:
            print(f"[!] Check api_token in {CONFIG_PATH.name}")
        return
    except urllib.error.URLError as e:
        print(f"[!] Upload failed: {e.reason}")
        print(f"[!] Local file is safe at {json_path.name}; retry later.")
        return

    if status == 201:
        detail_url = payload.get("url", "(no url)")
        print(f"[OK] Uploaded → {detail_url}")
    else:
        print(f"[!] Unexpected response: HTTP {status} {payload}")


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

    print()
    print("The extractor will now wait until a completed Training Log")
    print("appears in memory. Feel free to launch it before finishing an")
    print("IT run — capture happens automatically when you reach the")
    print("Training Log screen. (Times out after 5 minutes.)")
    print()

    try:
        result = _extract(pid)
    except Exception as e:
        print(f"\n[X] Extraction failed: {e}")
        traceback.print_exc()
        return 4

    if _looks_empty(result):
        print()
        print("[!] No completed Training Log data appeared within the wait window.")
        print("[!] Run the extractor again once you've finished an IT run and")
        print("[!] the Training Log popup is on screen.")
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

    # Optional auto-upload. Config sidecar is opt-in; local file always
    # written first so a failed POST doesn't cost the user a run.
    cfg = _load_upload_config()
    if cfg:
        _upload_run(out_path, cfg)
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
