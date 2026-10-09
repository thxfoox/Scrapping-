"""Print compact digests of candidate leads that still need the AI analysis.

    python digest.py --size 10            # next 10 candidates without analysis
    python digest.py --keys k1,k2         # specific places
"""

import argparse
import json

from build_report import DATA, candidates, load_analysis, load_places

MAX_REVIEWS = 14
CUT = 260


def short(text: str, n: int = CUT) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def digest(p: dict) -> str:
    lines = [f"### {p['key']}",
             f"{p['name']} | {p.get('category')} -> {p['rubro']} | {p['dist_km']} km | {p.get('address')}"]
    contact = p.get("phone", "sin teléfono") + (" (móvil)" if p.get("is_mobile") else "")
    socials = ", ".join(f"{k}" for k in p.get("socials", {})) or "sin redes"
    lines.append(f"tel: {contact} | web: {p.get('website') or '-'} | redes: {socials} | "
                 f"{p.get('rating')}★ ({p.get('reviews')}) | sin reclamar: {p.get('unclaimed')} | precio: {p.get('price') or '-'}")
    flags = []
    if p.get("chain_guess"):
        flags.append("POSIBLE CADENA")
    if p.get("mall_guess"):
        flags.append("POSIBLE MALL")
    if flags:
        lines.append("flags: " + ", ".join(flags))
    if p.get("hours"):
        lines.append("horario: " + "; ".join(f"{d[:3]} {h}" for d, h in p["hours"]))
    if p.get("limited_view"):
        lines.append("OJO: vista limitada, sin reseñas cargadas")
    if p.get("description"):
        lines.append("descripción: " + short(p["description"], 300))
    if p.get("review_topics"):
        lines.append("temas: " + ", ".join(f"{t}({n})" for t, n in p["review_topics"][:10]))
    if p.get("histogram"):
        lines.append("estrellas: " + " ".join(f"{k}★{v}" for k, v in sorted(p["histogram"].items(), reverse=True)))
    if p.get("photo_note"):
        lines.append("foto: " + p["photo_note"])
    items = p.get("review_items", [])
    replies = [r["owner_reply"] for r in items if r.get("owner_reply")]
    if replies:
        lines.append(f"respuestas del dueño ({len(replies)}): " + " || ".join(short(r, 180) for r in replies[:3]))
    for r in items[:MAX_REVIEWS]:
        if r.get("text"):
            lines.append(f"- {r.get('stars')}★ {r.get('date', '')}: {short(r['text'])}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--keys", default="")
    ap.add_argument("--count", action="store_true")
    args = ap.parse_args()
    cands, _ = candidates(load_places())
    done = load_analysis()
    photo_notes = json.loads((DATA / "photo_notes.json").read_text()) if (DATA / "photo_notes.json").exists() else {}
    if args.keys:
        wanted = set(args.keys.split(","))
        todo = [p for p in cands if p["key"] in wanted]
    else:
        todo = sorted((p for p in cands if p["key"] not in done), key=lambda p: p["dist_km"])
    if args.count:
        print(f"{len(cands)} candidates, {len(todo)} without analysis")
        return
    for p in todo[: args.size]:
        p["photo_note"] = photo_notes.get(p["key"], "")
        print(digest(p))
        print()


if __name__ == "__main__":
    main()
