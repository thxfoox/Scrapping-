"""Parsers for Google Maps search lists and place pages, built on Scrapling's Selector.

Google Maps class names are obfuscated and change over time, so every field is read
from the most stable hook available first (data-item-id, aria-label, role) and only
then from class names.
"""

import re
from urllib.parse import parse_qs, unquote, urlparse

from scrapling.parser import Selector

COORDS_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
AT_COORDS_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
PLACE_ID_RE = re.compile(r"!19s(ChIJ[\w-]+)")
FEATURE_ID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)")
TOPIC_RE = re.compile(r"^(.+?),\s*mencionad[oa]s?\s+en\s+([\d.]+)\s+reseñ", re.I)
STARS_RE = re.compile(r"(\d)(?:[.,]\d)?\s+estrella", re.I)
HIST_RE = re.compile(r"(\d)\s+estrellas?,\s*([\d.]+)\s+reseñ", re.I)

SOCIAL_HOSTS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "tiktok.com": "tiktok",
    "wa.me": "whatsapp",
    "whatsapp.com": "whatsapp",
    "linktr.ee": "linktree",
}


def _txt(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _first_attr(page: Selector, selectors: list[str], attr: str) -> str:
    for sel in selectors:
        for el in page.css(sel):
            val = el.attrib.get(attr)
            if val:
                return _txt(val)
    return ""


def _first_text(page: Selector, selectors: list[str]) -> str:
    for sel in selectors:
        for el in page.css(sel):
            val = _txt(el.get_all_text())
            if val:
                return val
    return ""


def parse_number(text: str) -> float | None:
    """'4,6' -> 4.6 ; '(1.234)' -> 1234 ; '1,2 mil' -> 1200."""
    if not text:
        return None
    t = text.strip().strip("()").lower().replace("\xa0", " ")
    mult = 1
    if "mil" in t:
        mult, t = 1000, t.replace("mil", "").strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    t = t.replace(",", ".")
    m = re.search(r"\d+(\.\d+)?", t)
    return float(m.group()) * mult if m else None


def coords_from_url(url: str) -> tuple[float, float] | tuple[None, None]:
    m = COORDS_RE.search(url or "") or AT_COORDS_RE.search(url or "")
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def ids_from_url(url: str) -> dict:
    url = unquote(url or "")
    out = {}
    if m := PLACE_ID_RE.search(url):
        out["place_id"] = m.group(1)
    if m := FEATURE_ID_RE.search(url):
        out["feature_id"] = m.group(1)
        out["cid"] = str(int(m.group(1).split(":")[1], 16))
    return out


def unwrap_link(href: str) -> str:
    """Google sometimes wraps outbound links as /url?q=..."""
    if not href:
        return ""
    if "/url?" in href:
        q = parse_qs(urlparse(href).query).get("q")
        if q:
            return q[0]
    return href


def classify_link(href: str) -> str | None:
    host = urlparse(href).netloc.lower().removeprefix("www.").removeprefix("m.")
    for key, kind in SOCIAL_HOSTS.items():
        if host == key or host.endswith("." + key):
            return kind
    return None


def normalize_phone(raw: str) -> dict:
    """Chilean numbers: mobiles are +56 9 XXXX XXXX (WhatsApp-capable)."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return {}
    if digits.startswith("56"):
        national = digits[2:]
    elif digits.startswith("0"):
        national = digits.lstrip("0")
    else:
        national = digits
    mobile = len(national) == 9 and national.startswith("9")
    if mobile:
        pretty = f"+56 9 {national[1:5]} {national[5:]}"
    elif len(national) == 9 and national.startswith("2"):
        pretty = f"+56 2 {national[1:5]} {national[5:]}"
    elif len(national) == 9:
        pretty = f"+56 {national[:2]} {national[2:5]} {national[5:]}"
    else:
        pretty = raw.strip()
    return {"phone": pretty, "phone_e164": "+56" + national, "is_mobile": mobile}


# ---------------------------------------------------------------- search lists


def parse_search(html: str) -> list[dict]:
    page = Selector(html)
    results, seen = [], set()
    for a in page.css('a[href*="/maps/place/"]'):
        href = a.attrib.get("href", "")
        name = _txt(a.attrib.get("aria-label"))
        if not href or not name or href in seen:
            continue
        seen.add(href)
        card = a.parent
        card_text = _txt(card.get_all_text(separator=" · ")) if card else ""
        lat, lng = coords_from_url(href)
        rating = None
        reviews = None
        for el in card.css('span[role="img"][aria-label]') if card else []:
            label = el.attrib.get("aria-label", "")
            if "estrella" in label:
                rating = parse_number(label.split("estrella")[0])
                m = re.search(r"([\d.]+)\s+reseñ", label)
                if m:
                    reviews = parse_number(m.group(1))
        phone_hint = ""
        m = re.search(r"(\+?56\s?)?(9\s?\d{4}\s?\d{4}|2\s?\d{4}\s?\d{4})", card_text)
        if m:
            phone_hint = m.group(0)
        results.append(
            {
                "name": name,
                "url": href.split("?")[0],
                "lat": lat,
                "lng": lng,
                "rating": rating,
                "reviews": reviews,
                "phone_hint": phone_hint,
                "card_text": card_text[:400],
                **ids_from_url(href),
            }
        )
    return results


# ---------------------------------------------------------------- place pages


def parse_hours(page: Selector) -> list[list[str]]:
    rows = []
    for tr in page.css("table tr"):
        cells = tr.css("td")
        if len(cells) >= 2:
            day = _txt(cells[0].get_all_text())
            hours = _txt(cells[1].attrib.get("aria-label") or cells[1].get_all_text())
            if day and hours and len(day) < 20:
                rows.append([day, hours.replace(", ", " y ")])
    if rows:
        return rows
    label = _first_attr(page, ['[aria-label*="horario de la semana"]', '[aria-label*="Horario"]'], "aria-label")
    for chunk in label.split(";"):
        chunk = chunk.split(". Ocultar")[0].split(". Mostrar")[0]
        if "," in chunk:
            day, hours = chunk.split(",", 1)
            rows.append([_txt(day), _txt(hours)])
    return rows


def parse_place(overview_html: str, reviews_html: str, url: str) -> dict:
    ov = Selector(overview_html or "<html></html>")
    rv = Selector(reviews_html or "<html></html>")

    name = _first_text(ov, ["h1.DUwDvf", "h1"])
    category = _first_text(ov, ["button.DkEaL", 'button[jsaction*="category"]'])

    rating, reviews = None, None
    for el in ov.css('div.F7nice span[aria-hidden="true"], span[role="img"][aria-label*="estrellas"]'):
        val = parse_number(el.attrib.get("aria-label") or el.get_all_text())
        if val is not None and 0 < val <= 5:
            rating = val
            break
    for el in ov.css('span[aria-label*="reseña"], button[aria-label*="reseña"]'):
        m = re.search(r"([\d.]+)\s+reseñ", el.attrib.get("aria-label", ""))
        if m:
            reviews = parse_number(m.group(1))
            break

    address = _first_attr(ov, ['button[data-item-id="address"]'], "aria-label")
    address = re.sub(r"^Dirección:\s*", "", address)
    plus_code = re.sub(r"^Plus Code:\s*", "", _first_attr(ov, ['button[data-item-id="oloc"]'], "aria-label"))

    phone_raw = ""
    for el in ov.css('button[data-item-id^="phone:tel:"]'):
        phone_raw = el.attrib.get("data-item-id", "").replace("phone:tel:", "")
        break

    website = unwrap_link(_first_attr(ov, ['a[data-item-id="authority"]'], "href"))
    socials = {}
    links = [unwrap_link(a.attrib.get("href", "")) for a in ov.css("a[href]")]
    for link in [website, *links]:
        kind = classify_link(link) if link else None
        if kind and kind not in socials:
            socials[kind] = link
    if website and classify_link(website):
        website = ""

    menu = unwrap_link(_first_attr(ov, ['a[data-item-id="menu"]'], "href"))
    order_links = [unwrap_link(a.attrib.get("href", "")) for a in ov.css('a[data-item-id^="action:"]')]

    unclaimed = bool(ov.css('a[data-item-id="merchant"]')) or "Reclamar esta empresa" in ov.get_all_text()
    price = re.sub(r"^Precio:\s*", "", _first_attr(ov, ['span[aria-label^="Precio"]'], "aria-label"))
    description = _first_text(ov, ["div.PYvSYb", 'div[aria-label^="Acerca de"] div.PYvSYb'])
    open_status = _first_text(ov, ["span.ZDu9vd", "div.MkV9 span"])

    photo = ""
    for img in ov.css("button img[src], img[src]"):
        src = img.attrib.get("src", "")
        if "googleusercontent.com" in src and ("/p/" in src or "/gps-" in src):
            photo = re.sub(r"=w\d+-h\d+[^&]*$", "=w480-h360-k-no", src)
            break

    final_lat, final_lng = coords_from_url(url)

    reviews_list, seen = [], set()
    for el in rv.css("div[data-review-id]"):
        rid = el.attrib.get("data-review-id")
        if rid in seen or not el.css("span.wiI7pd, div.MyEned"):
            continue
        seen.add(rid)
        stars = None
        for s in el.css('span[role="img"][aria-label]'):
            m = STARS_RE.search(s.attrib.get("aria-label", ""))
            if m:
                stars = int(m.group(1))
                break
        if stars is None:
            m = re.search(r"\b([1-5])/5\b", el.get_all_text())
            stars = int(m.group(1)) if m else None
        text_el = el.css("div.MyEned span.wiI7pd") or el.css("span.wiI7pd")
        text = _txt(text_el[0].get_all_text()) if text_el else ""
        owner = el.css("div.CDe7pd")
        reply = _txt(owner[0].get_all_text()) if owner else ""
        date = _first_text(el, ["span.rsqaWe", "span.xRkPPb"])
        if text or reply:
            reviews_list.append({"stars": stars, "text": text, "date": date, "owner_reply": reply})

    topics = []
    for el in rv.css("[aria-label]"):
        m = TOPIC_RE.match(el.attrib.get("aria-label", ""))
        if m and m.group(1) not in [t[0] for t in topics]:
            topics.append([m.group(1), int(parse_number(m.group(2)) or 0)])

    histogram = {}
    for el in rv.css("tr[aria-label], [aria-label*='estrellas,']"):
        m = HIST_RE.search(el.attrib.get("aria-label", ""))
        if m:
            histogram[m.group(1)] = int(parse_number(m.group(2)) or 0)

    return {
        "name": name,
        "category": category,
        "rating": rating,
        "reviews": int(reviews) if reviews is not None else None,
        "address": address,
        "plus_code": plus_code,
        **normalize_phone(phone_raw),
        "website": website,
        "socials": socials,
        "menu": menu,
        "order_links": [o for o in order_links if o][:3],
        "unclaimed": unclaimed,
        "price": price,
        "description": description,
        "open_status": open_status,
        "hours": parse_hours(ov),
        "photo": photo,
        "lat": final_lat,
        "lng": final_lng,
        **ids_from_url(url),
        "review_items": reviews_list,
        "review_topics": topics,
        "histogram": histogram,
    }
