"""Merge scraped fichas + AI analysis, score every lead and render the HTML report.

    python build_report.py                      # writes ../informe-leads-maipu.html
    python build_report.py --candidates         # list leads that still need analysis
"""

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import config
import geo
from extract import normalize_phone

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE.parent / "informe-leads-maipu.html"

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]

TIERS = {"alta": 75, "media": 55}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# Google category -> rubro. Order matters: specific rules first.
RUBRO_RULES = [
    ("Sushi", ["sushi", "japones", "nikkei", "ramen"]),
    ("Pizzerías", ["pizz"]),
    ("Barberías", ["barber"]),
    ("Centros de estética", ["estetic", "unas", "manicur", "pedicur", "depila", "spa", "pestan", "ceja",
                             "masaj", "cosmet", "maquill", "bronce", "belleza facial", "lifting"]),
    ("Peluquerías", ["peluquer", "salon de belleza", "estilista", "salon de peluqueria"]),
    ("Botillerías", ["botiller", "licor", "vinoteca", "tienda de vinos", "distribuidora de bebidas", "cerveza",
                     "bebidas alcoholicas", "alcohol"]),
    ("Panaderías", ["panader", "amasander"]),
    ("Pastelerías", ["pastel", "reposter", "torta", "dulcer", "chocolat", "helader", "kuchen", "postre"]),
    ("Cafeterías", ["cafeter", "cafe", "coffee", "te y ", "salon de te", "brunch"]),
    ("Sangucherías", ["sangu", "sandw", "fuente de soda", "lomit", "churrasc", "chacarer"]),
    ("Comida rápida", ["comida rapida", "hamburgues", "completo", "hot dog", "pollo frito", "papas fritas",
                       "kebab", "shawarma", "taco", "burrito", "empanad", "food truck", "comida para llevar",
                       "pollo asado", "rosticer", "sopaipill", "pollo"]),
    ("Minimarkets", ["minimarket", "mini market", "almacen", "supermercado", "comestibles", "abarrote",
                     "conveniencia", "alimentacion", "tienda de alimentos", "market"]),
    ("Restaurantes", ["restaurant", "comida", "parrill", "marisquer", "picada", "cocineria", "asador",
                      "chifa", "peruan", "venezol", "colombian", "arabe", "mexican", "vegan", "vegetarian",
                      "bar ", "pub", "buffet", "cevich", "criolla", "casera", "gastronom"]),
    ("Tiendas de barrio", ["bazar", "ferreter", "verduler", "fruter", "librer", "papeler", "carnicer",
                           "pescader", "tienda", "zapater", "mascota", "regalo", "cotillon", "jugueter",
                           "merceria", "kiosco", "bicicleter", "articulos", "lavander", "imprenta",
                           "frutos secos", "huevos", "polleria", "boutique", "ropa", "plasticos"]),
]

EXCLUDE_CATEGORIES = ["banco", "cajero", "farmacia", "estacion de servicio", "gasolinera", "hipermercado",
                      "centro comercial", "iglesia", "colegio", "escuela", "clinica", "hospital", "consultorio",
                      "municipalidad", "parque", "plaza", "estacion de metro", "parada", "gimnasio", "jardin infantil",
                      "notaria", "cementerio", "dentista", "medico", "veterinari", "taller mecanico", "motel", "hotel"]

BIG_CHAINS = ["lider", "jumbo", "unimarc", "santa isabel", "tottus", "acuenta", "mayorista 10", "alvi",
              "cruz verde", "salcobrand", "ahumada", "dr. simi", "dr simi", "oxxo", "ok market", "upa!",
              "pronto copec", "spacio 1", "big john"]

KNOWN_CHAINS = ["juan maestro", "doggis", "telepizza", "papa john", "domino", "pizza hut", "little caesars",
                "mcdonald", "burger king", "kfc", "subway", "starbucks", "juan valdez", "castano", "dunkin",
                "tarragona", "niu sushi", "sushi blue", "melt pizza", "pizza pizza", "lomiton", "fritz",
                "wendy", "taco bell", "popeyes", "carl's", "pedro juan", "china wok", "tommy beans",
                "la fete", "mamut", "tip y tap", "bigos", "pollo stop", "emporio la rosa", "bravissimo",
                "savory", "copec", "chicken love you", "sbarro", "johnny rockets", "kentucky",
                "marley coffee", "cafe haiti", "cafe caribe", "sushi house", "dimarco", "la cuchara de palo"]

MALL_MARKERS = ["mall ", "mall,", "patio de comida", "food court", "arauco maipu", "plaza oeste", "outlet"]


def map_rubro(category: str, search_rubros: list[str]) -> str | None:
    c = norm(category) + " "
    for rubro, keys in RUBRO_RULES:
        if any(k in c for k in keys):
            return rubro
    return search_rubros[0] if search_rubros else None


def is_excluded_category(category: str) -> bool:
    c = norm(category)
    return any(k in c for k in EXCLUDE_CATEGORIES)


def chain_guess(name: str, n_same_name: int) -> bool:
    n = norm(name)
    return any(k in n for k in KNOWN_CHAINS) or n_same_name >= 3


def mall_guess(address: str, name: str) -> bool:
    text = norm(address + " " + name) + " "
    return any(k in text for k in MALL_MARKERS)


def in_maipu(address: str) -> bool:
    return "maipu" in norm(address)


def rating_points(rating, reviews) -> int:
    if not rating:
        return 4
    table = [(4.8, 17), (4.6, 15), (4.4, 13), (4.2, 11), (4.0, 9), (3.7, 6), (3.4, 3)]
    pts = next((p for r, p in table if rating >= r), 1)
    if (reviews or 0) < 5:
        pts = min(pts, 9)
    return pts


def volume_points(reviews) -> int:
    n = reviews or 0
    for limit, pts in [(300, 8), (150, 7), (75, 6), (30, 5), (15, 4), (5, 2), (1, 1)]:
        if n >= limit:
            return pts
    return 0


def proximity_points(km: float) -> int:
    """km = distance to the band between Av. Portales and Av. Sur (0 inside it)."""
    for limit, pts in [(0.0, 8), (0.25, 7), (0.5, 5), (0.8, 3), (1.2, 2)]:
        if km <= limit:
            return pts
    return 1


def dist_label(km: float) -> str:
    if km <= 0:
        return "dentro del sector (Av. Portales a Nueva San Martín)"
    txt = f"{round(km * 1000 / 10) * 10} m" if km < 1 else f"{str(round(km, 1)).replace('.', ',')} km"
    return f"a {txt} del sector Av. Portales–Nueva San Martín"


ATIENDE_LABELS = {
    "owner": "Atiende el dueño",
    "family": "Negocio familiar",
    "staff": "Con encargados",
    "chain": "Cadena o franquicia",
    "unknown": "Quién atiende: sin datos",
}


def score_lead(p: dict, a: dict) -> tuple[int, list]:
    parts = []
    if p.get("phone"):
        parts.append(("Teléfono móvil o WhatsApp" if p.get("is_mobile") else "Teléfono fijo",
                      40 if p.get("is_mobile") else 34))
    else:
        parts.append(("Sin teléfono: solo Instagram o email", 14))

    kind, scale = a.get("atiende", "unknown"), a.get("escala", "pequeño")
    chain, mall = bool(a.get("cadena")), bool(a.get("mall"))
    if chain or mall:
        parts.append(("Cadena, franquicia o local de mall", 2))
    elif kind in ("owner", "family"):
        parts.append(("Negocio local atendido por su dueño o familia", 27))
    elif scale in ("micro", "pequeño"):
        parts.append(("Negocio local chico" + (" con personal" if kind == "staff" else ""), 18 if kind == "staff" else 20))
    elif scale == "mediano":
        parts.append(("Negocio local mediano con encargados", 13 if kind == "staff" else 14))
    else:
        parts.append(("Negocio independiente grande", 8))

    rating, reviews = p.get("rating"), p.get("reviews")
    rp, vp = rating_points(rating, reviews), volume_points(reviews)
    label = f"Valoración {str(rating).replace('.', ',')} con {reviews} reseñas" if rating else "Sin valoración en Maps"
    parts.append((label, rp + vp))

    km = p["dist_km"]
    parts.append((f"Cercanía: {dist_label(km)}", proximity_points(km)))

    if chain and mall:
        parts.append(("Cadena dentro de mall: quien atiende no decide", -18))
    elif chain:
        parts.append(("Cadena o franquicia: quien atiende no decide", -12))
    elif mall:
        parts.append(("Local de mall o patio de comidas", -12))

    total = max(0, min(100, sum(pts for _, pts in parts)))
    return total, [[label, pts] for label, pts in parts]


def load_places() -> list[dict]:
    places = []
    for f in sorted((DATA / "places").glob("*.json")):
        places.append(json.loads(f.read_text()))
    return places


def load_analysis() -> dict:
    merged = {}
    for f in sorted((DATA / "analysis").glob("*.json")):
        merged.update(json.loads(f.read_text()))
    return merged


def candidates(places: list[dict]) -> tuple[list[dict], dict]:
    """Business rules that don't need AI: Maipú only, open, contactable, relevant rubro."""
    names = {}
    for p in places:
        names[norm(p.get("name"))] = names.get(norm(p.get("name")), 0) + 1
    out, reasons = [], {}
    seen = set()
    for p in places:
        if p.get("lat") is not None:  # distances always follow the current sector geometry
            p["dist_km"] = round(geo.band_distance_km(p["lat"], p["lng"]), 3)
            p["dist_center_km"] = round(geo.center_distance_km(p["lat"], p["lng"]), 3)
        why = None
        status = norm(p.get("open_status", ""))
        rubro = map_rubro(p.get("category", ""), p.get("rubros_busqueda", []))
        if not in_maipu(p.get("address", "")):
            why = "fuera de Maipú"
        elif "cerrado permanentemente" in status or "cerrado temporalmente" in status:
            why = "cerrado"
        elif is_excluded_category(p.get("category", "")):
            why = "rubro no objetivo"
        elif any(k in norm(p.get("name")) for k in BIG_CHAINS):
            why = "gran cadena"
        elif not rubro:
            why = "sin rubro"
        elif not (p.get("phone") or p.get("socials", {}).get("instagram") or p.get("email")):
            why = "sin teléfono, Instagram ni email"
        elif (p.get("cid") or p["key"]) in seen:
            why = "duplicado"
        if why:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        seen.add(p.get("cid") or p["key"])
        p["rubro"] = rubro
        p["chain_guess"] = chain_guess(p.get("name", ""), names[norm(p.get("name"))])
        p["mall_guess"] = mall_guess(p.get("address", ""), p.get("name", ""))
        out.append(p)
    return out, reasons


PLATFORMS = {
    "ubereats.com": "Uber Eats", "pedidosya.cl": "PedidosYa", "pedidosya.com": "PedidosYa", "rappi.cl": "Rappi",
    "didi-food.com": "DiDi Food", "agendapro.com": "AgendaPro", "fresha.com": "Fresha", "booksy.com": "Booksy",
    "linktr.ee": "Linktree", "wa.me": "WhatsApp", "wa.link": "WhatsApp", "whatsapp.com": "WhatsApp",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
}


def split_website(url: str) -> tuple[str, str]:
    """Own website vs. a page on someone else's platform (delivery apps, booking tools, link hubs)."""
    if not url:
        return "", ""
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, name in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return "", name
    return url, ""


def maps_link(p: dict) -> str:
    if p.get("place_id"):
        from urllib.parse import quote
        return f"https://www.google.com/maps/search/?api=1&query={quote(p['name'])}&query_place_id={p['place_id']}"
    if p.get("cid"):
        return f"https://maps.google.com/?cid={p['cid']}"
    return p.get("maps_url", "")


def build():
    places = load_places()
    analysis = load_analysis()
    cands, reasons = candidates(places)
    center = {"label": "el sector entre Av. Portales y Nueva San Martín, de Av. El Conquistador a El Carmen"}
    searches = json.loads((DATA / "searches_done.json").read_text()) if (DATA / "searches_done.json").exists() else []

    leads, missing = [], []
    for p in cands:
        a = analysis.get(p["key"])
        if not a:
            missing.append(p["key"])
            continue
        if a.get("excluir"):
            reasons[a["excluir"]] = reasons.get(a["excluir"], 0) + 1
            continue
        if a.get("rubro"):
            p["rubro"] = a["rubro"]
        extra_wa = re.sub(r"\D", "", a.get("whatsapp", ""))
        wa_number = ""
        if extra_wa:  # WhatsApp number published by the business itself (e.g. on its listing photo)
            wa_info = normalize_phone(extra_wa)
            if not p.get("phone"):
                p.update(wa_info)
            elif wa_info["phone_e164"] != p.get("phone_e164"):
                wa_number = wa_info["phone"]
        score, breakdown = score_lead({**p, "is_mobile": p.get("is_mobile") or bool(extra_wa)}, a)
        socials = p.get("socials", {})
        wa = (f"https://wa.me/{extra_wa}" if extra_wa else "") or socials.get("whatsapp") or \
            (f"https://wa.me/{p['phone_e164'].lstrip('+')}" if p.get("is_mobile") else "")
        kind = a.get("atiende", "unknown")
        leads.append({
            "id": re.sub(r"[^\w-]", "", p.get("cid") or p["key"])[:40],
            "name": p["name"],
            "rubro": p["rubro"],
            "category": p.get("category", ""),
            "phone": p.get("phone", ""),
            "phone_e164": p.get("phone_e164", ""),
            "whatsapp": wa,
            "wa_number": wa_number,
            "phone_is_mobile": bool(p.get("is_mobile")),
            "email": a.get("email", ""),
            "address": re.sub(r",?\s*Región Metropolitana.*$", "", p.get("address", "")).strip(),
            "rating": p.get("rating"),
            "reviews": p.get("reviews") or 0,
            "website": split_website(p.get("website", ""))[0],
            "platform": split_website(p.get("website", ""))[1],
            "platform_url": p.get("website", "") if split_website(p.get("website", ""))[1] else "",
            "has_web": bool(split_website(p.get("website", ""))[0]),
            "socials": {k: v for k, v in socials.items() if k in ("instagram", "facebook", "tiktok")},
            "hours": p.get("hours", []),
            "price": p.get("price", ""),
            "maps_url": maps_link(p),
            "dist_km": p["dist_km"],
            "dist_center_km": p.get("dist_center_km", p["dist_km"]),
            "unclaimed": p.get("unclaimed", False),
            "resumen": a["resumen"],
            "elogios": a["elogios"],
            "reclamos": a["reclamos"],
            "atiende_tipo": kind,
            "atiende": a.get("atiende_label") or ATIENDE_LABELS.get(kind, ATIENDE_LABELS["unknown"]),
            "atiende_detalle": a["atiende_detalle"],
            "tip": a.get("tip", ""),
            "score": score,
            "score_breakdown": breakdown,
        })
    return leads, missing, reasons, places, center, searches


def render(leads, reasons, places, center, searches):
    today = date.today()
    fecha = f"{today.day} de {MONTHS[today.month - 1]} de {today.year}"
    reviews_read = sum(len(p.get("review_items", [])) for p in places)
    radius = max((l["dist_km"] for l in leads), default=0)
    inside = sum(1 for l in leads if l["dist_km"] <= 0)
    meta = {
        "generated": fecha,
        "fichas_revisadas": len(places),
        "rubros_buscados": len(config.RUBROS),
        "tiers": TIERS,
        "lede": (f"{len(leads)} negocios seleccionados entre {len(places)} fichas de Google Maps revisadas en el sector de "
                 "Av. Portales, Av. Sur y Nueva San Martín, hasta la esquina de Av. Sur con El Carmen (Maipú), ordenados "
                 "según lo interesante que es contactarlos. Cada ficha trae su contacto, lo que dicen sus clientes y quién "
                 "atiende, para llegar preparado a la llamada o a la visita."),
        "weights": [
            {"label": "Teléfono o WhatsApp", "max": 40},
            {"label": "Negocio local y quién atiende", "max": 27},
            {"label": "Valoración y número de reseñas", "max": 25},
            {"label": "Cercanía al sector Portales–Sur–Nueva San Martín", "max": 8},
        ],
        "method_note": ("Cadenas, franquicias y locales de mall restan entre 12 y 18 puntos. Sin teléfono solo entran "
                        "si tienen Instagram o email, y con menos nota. Tener web no cambia la nota: en empates va "
                        f"primero el que no tiene. Prioridad alta desde {TIERS['alta']} puntos; media desde {TIERS['media']}."),
        "methodology": (f"Datos de Google Maps extraídos con Scrapling (navegador automatizado) el {fecha}: "
                        f"{len(searches)} búsquedas de {len(config.RUBROS)} rubros en {center['label']} y las villas vecinas. "
                        "Av. Portales, Av. Sur y Nueva San Martín son paralelas, así que la zona objetivo es la franja entre "
                        "Av. Portales y Nueva San Martín, incluida la esquina de Av. Sur con El Carmen: "
                        f"{inside} negocios están dentro y el resto a menos de {str(round(radius, 1)).replace('.', ',')} km, siempre en Maipú. "
                        f"Se abrieron {len(places)} fichas y se leyeron {reviews_read:,} reseñas".replace(",", ".") +
                        ". El resumen, los elogios, los reclamos y quién atiende los redactó una IA leyendo cada ficha, "
                        "sus reseñas, las respuestas del dueño y su foto principal."),
        "caveats": ("Quedaron fuera " + ", ".join(f"{n} por {r}" for r, n in sorted(reasons.items(), key=lambda kv: -kv[1])) +
                    ". Los datos de Maps cambian: confirma teléfono y horario antes de visitar. «Con quién hablarás» "
                    "es una inferencia a partir de reseñas y respuestas del propietario, no un dato verificado."),
    }
    tpl = (HERE / "template.html").read_text()
    leads_json = json.dumps(leads, ensure_ascii=False).replace("</", "<\\/")
    meta_json = json.dumps(meta, ensure_ascii=False).replace("</", "<\\/")
    eyebrow = f"Informe de prospección · {MONTHS[today.month - 1].capitalize()} {today.year}"
    html = tpl.replace("__LEADS_JSON__", leads_json).replace("__META_JSON__", meta_json).replace("__EYEBROW__", eyebrow)
    OUT.write_text(html)
    return OUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    leads, missing, reasons, places, center, searches = build()
    if args.candidates:
        print(f"{len(missing)} candidates without analysis")
        print("\n".join(missing))
        return
    if args.out:
        global OUT
        OUT = Path(args.out)
    out = render(leads, reasons, places, center, searches)
    scores = sorted((l["score"] for l in leads), reverse=True)
    print(f"{len(leads)} leads -> {out}")
    print("excluded:", reasons, "| awaiting analysis:", len(missing))
    if scores:
        alta = sum(s >= TIERS["alta"] for s in scores)
        media = sum(TIERS["media"] <= s < TIERS["alta"] for s in scores)
        print(f"scores: max {scores[0]} median {scores[len(scores) // 2]} min {scores[-1]} | alta {alta} media {media} baja {len(scores) - alta - media}")


if __name__ == "__main__":
    main()
