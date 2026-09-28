"""Read ONE borrowable parent from the career/IT setup screen, by its lender's
trainer id (12 digits, as uma.moe shows it), with its sparks, G1 win saddles
and its parents'. Run on Windows with the game on the parent-selection
screen; the filter runs inside the game, so no other lender leaves it.

    python rental_one.py TRAINER_ID [--bridge path/to/il2cpp_bridge.js] > rental.json

Output: the JSON the loop tools take as --rental.
"""
import argparse, frida, time, json, sys
ap = argparse.ArgumentParser()
ap.add_argument("trainer_id")
ap.add_argument("--bridge", default="vendor/il2cpp_bridge.js")
args = ap.parse_args()
BRIDGE = open(args.bridge, encoding="utf-8").read()
WANT = args.trainer_id
AGENT = r"""
const WANT = '%s';
setTimeout(() => Il2Cpp.perform(() => {
  const isNull = v => v === null || v === undefined || (v.isNull && v.isNull());
  const field = (o, n) => { if (isNull(o)) return null; const v = o.field(n).value; return isNull(v) ? null : v; };
  const num = v => { if (isNull(v)) return null; if (typeof v === 'number') return v; if (typeof v === 'bigint') return Number(v);
    try { return Number(BigInt(v.field('hiddenValue').value) ^ BigInt(v.field('currentCryptoKey').value)); } catch (e) {}
    try { return (v.field('hiddenValue').value ^ v.field('currentCryptoKey').value); } catch (e) {}
    try { return Number(v.toString()); } catch (e) { return null; } };
  const items = v => { if (isNull(v)) return []; const arr = v.length !== undefined && v.get ? v : field(v, '_items');
    const n = v.length !== undefined && v.get ? v.length : num(field(v, '_size')); const o = []; for (let i = 0; i < (n||0); i++) o.push(arr.get(i)); return o; };
  const part = f => { try { return f(); } catch (e) { return null; } };
  const img = Il2Cpp.domain.assembly('umamusume').image;
  const single = name => { const k = img.class(name); for (let c = k; c; c = c.parent) for (const f of c.fields) if (f.isStatic && f.type && f.type.name === name) return f.value; return null; };
  const hub = field(single('Gallop.SceneManager'), '_currentViewController');
  const ctl = part(() => field(hub, '<ChildCurrentController>k__BackingField'));
  const entry = part(() => field(ctl, '<Entry>k__BackingField'));
  if (!entry) { send({err: 'no setup entry: ' + (ctl ? ctl.class.type.name : 'none')}); send('__done'); return; }
  const facts = o => part(() => items(field(o, '<FactorDataArray>k__BackingField')).map(f => num(field(f, '<FactorId>k__BackingField'))));
  const wins = o => part(() => items(field(o, '_winSaddleIdArray')).map(num));
  let found = 0, total = 0;
  for (const [tl, ul] of [['RentalTrainedCharaArray', 'RentalUserInfoArray'], ['EventRentalTrainedCharaArray', 'EventRentalUserInfoArray']]) {
    const rs = part(() => items(field(entry, tl))) || [], us = part(() => items(field(entry, ul))) || [];
    total += rs.length;
    rs.forEach((r, i) => {
      const tid = String(num(field(us[i], 'viewer_id')));
      if (tid !== WANT) return;
      found++;
      send({card: num(field(r, '_cardId')), rank_score: num(field(r, '_rankScore')), factors: facts(r), wins: wins(r),
        lineage: (part(() => items(field(r, '<SuccessionCharaList>k__BackingField'))) || []).map(g => ({
          pos: num(field(g, '_positionId')), card: num(field(g, '<CardId>k__BackingField')), factors: facts(g), wins: wins(g)}))});
    });
  }
  send({found, total});
  send('__done');
}, 'free'));
""" % WANT
done = False; out = []
def on(m, d):
    global done
    if m['type'] == 'send':
        if m['payload'] == '__done': done = True
        else: out.append(m['payload'])
    else: out.append(m)
pid = next(p.pid for p in frida.get_local_device().enumerate_processes() if p.name.lower() == 'umamusumeprettyderby.exe')
s = frida.attach(pid); sc = s.create_script(BRIDGE + AGENT); sc.on('message', on); sc.load()
t = time.time()
while not done and time.time() - t < 60: time.sleep(0.2)
sc.unload(); s.detach()
found = [x for x in out if isinstance(x, dict) and "card" in x]
if not found:
    sys.exit(f"not found: {out}")
print(json.dumps(found[0]))
