"""Sales hooks written by AI for each lead, in batches (best score first).

    python pitch.py digest --size 45        # next leads without a hook, in compact text
    python pitch.py save /path/batch.json   # positional keys "1".."N" -> data/pitch/batch_NNN.json

Each entry: {"_name": ..., "nombre": who to ask for or "", "gancho": one specific, positive sentence
about the business, "angulo": one sentence on what the first service would do for it}.
"""
import argparse
import json
import sys
from pathlib import Path

from build_report import DATA, build, load_pitch

CURRENT = DATA / "pitch_current.txt"
SERVICE = {"google": "Google Maps", "redes": "redes sociales", "web": "página web"}


def digest(size: int):
    leads = build()[0]
    done = load_pitch()
    todo = sorted((l for l in leads if l["id"] not in done), key=lambda l: -l["score"])[:size]
    for i, l in enumerate(todo, 1):
        o = l["offer"]
        presence = ", ".join(k for k in ("instagram", "facebook") if l["socials"].get(k)) or "sin redes"
        rating = f"{l['rating']}★ ({l['reviews']})" if l["rating"] else "sin reseñas"
        print(f"[{i}] {l['name']} | {l['rubro']} | {l['score']} pts | {rating} | web: {'sí' if l['has_web'] else 'no'}"
              f"{' (' + l['platform'] + ')' if l['platform'] else ''} | {presence}{' | sin reclamar' if l['unclaimed'] else ''}")
        print(f"atiende: {l['atiende']} — {l['atiende_detalle']}")
        print(f"resumen: {l['resumen']}")
        print(f"elogian: {l['elogios']} | reclaman: {l['reclamos']}")
        print(f"ofrecer: {' > '.join(SERVICE[s] for s in o['services'])} | porque: {'; '.join(o['why'])}")
        print()
    CURRENT.write_text("\n".join(l["id"] for l in todo))
    print(f"{len(todo)} in this batch, {len(leads) - len(done) - len(todo)} left after it", file=sys.stderr)


def save(path: str):
    ids = CURRENT.read_text().split("\n")
    names = {l["id"]: l["name"] for l in build()[0]}
    raw = json.loads(Path(path).read_text())
    out = {}
    for pos, entry in raw.items():
        lid = ids[int(pos) - 1]
        if entry.get("_name") and not names[lid].startswith(entry["_name"]):  # a prefix is enough to verify
            sys.exit(f"position {pos} is {names[lid]!r}, not {entry['_name']!r}")
        out[lid] = {k: v for k, v in entry.items() if not k.startswith("_")}
    folder = DATA / "pitch"
    folder.mkdir(exist_ok=True)
    target = folder / f"batch_{len(list(folder.glob('batch_*.json'))) + 1:03d}.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"saved {len(out)} hooks -> {target.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest").add_argument("--size", type=int, default=45)
    sub.add_parser("save").add_argument("path")
    args = ap.parse_args()
    digest(args.size) if args.cmd == "digest" else save(args.path)
