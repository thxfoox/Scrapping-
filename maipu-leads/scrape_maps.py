"""Google Maps lead scraper for Maipú, built on Scrapling's AsyncDynamicSession.

Stages (each one is resumable and writes to data/):
    python scrape_maps.py geocode            # exact point of Av. Sur con Av. Portales
    python scrape_maps.py search --rings 0   # list businesses per rubro around it
    python scrape_maps.py details --limit 300 --radius 2.0
    python scrape_maps.py probe URL          # save a page's HTML for selector debugging
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from scrapling.fetchers import AsyncDynamicSession
from scrapling.parser import Selector

import config
from extract import coords_from_url, ids_from_url, parse_place, parse_search

DATA = Path(__file__).parent / "data"
PLACES_DIR = DATA / "places"
CHROMIUM = os.environ.get("SCRAPLING_EXECUTABLE_PATH", "/opt/pw-browsers/chromium")
HL = "hl=es-419&gl=cl"

BLOCK_MARKERS = ("/sorry/", "unusual traffic", "tráfico inusual")


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(path)


def center() -> dict:
    return load_json(DATA / "center.json", config.CENTER)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def offset_point(lat, lng, km, bearing_deg) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    dlat = km * math.cos(b) / 111.32
    dlng = km * math.sin(b) / (111.32 * math.cos(math.radians(lat)))
    return lat + dlat, lng + dlng


def new_session(max_pages=3) -> AsyncDynamicSession:
    return AsyncDynamicSession(
        headless=True,
        executable_path=CHROMIUM,
        locale="es-CL",
        timezone_id="America/Santiago",
        google_search=False,
        timeout=45000,
        retries=2,
        max_pages=max_pages,
        blocked_domains={"doubleclick.net", "googlesyndication.com", "google-analytics.com", "googletagmanager.com"},
    )


async def handle_consent(page):
    if "consent." not in page.url:
        return
    for label in ("Rechazar todo", "Aceptar todo", "Reject all", "Accept all"):
        btn = page.locator(f'button:has-text("{label}"), input[type=submit][value="{label}"]')
        if await btn.count():
            await btn.first.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1500)
            return


def is_blocked(url: str, html: str) -> bool:
    low = (html or "")[:200000].lower()
    return any(m in (url or "") or m in low for m in BLOCK_MARKERS)


# ------------------------------------------------------------------ geocode


async def geocode():
    query = "Avenida Sur & Avenida Portales, Maipú, Región Metropolitana, Chile"
    store = {}

    async def action(page):
        await handle_consent(page)
        for _ in range(20):
            if "!3d" in page.url or re.search(r"@-33\.\d+,-70\.\d+,\d+", page.url):
                break
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(2000)
        store["url"] = page.url
        store["title"] = await page.title()

    async with new_session(1) as s:
        resp = await s.fetch(f"https://www.google.com/maps/search/{quote(query)}?{HL}", page_action=action)
    url = store.get("url") or resp.url
    lat, lng = coords_from_url(url)
    h1 = Selector(resp.body.decode("utf-8", "ignore")).css("h1")
    label = h1[0].get_all_text().strip() if h1 else ""
    log("geocode url:", url)
    log("geocode h1:", label, "| coords:", lat, lng)
    if lat is None:
        sys.exit("Could not geocode the center")
    DATA.mkdir(exist_ok=True)
    save_json(DATA / "center.json", {"lat": lat, "lng": lng, "label": label or config.CENTER["label"], "url": url})


# ------------------------------------------------------------------ search


def make_search_action(max_results: int, store: dict):
    async def action(page):
        await handle_consent(page)
        feed = 'div[role="feed"]'
        try:
            await page.wait_for_selector(feed, timeout=12000)
        except Exception:
            store["single"] = True
            await page.wait_for_timeout(1500)
            store["url"] = page.url
            return
        prev, stagnant = -1, 0
        for _ in range(60):
            n = await page.locator(f'{feed} a[href*="/maps/place/"]').count()
            ended = await page.evaluate(
                "() => /final de la lista|end of the list/i.test(document.querySelector('div[role=\"feed\"]')?.innerText || '')"
            )
            if n >= max_results or ended:
                break
            await page.evaluate(
                "(sel) => { const f = document.querySelector(sel); if (f) f.scrollTop = f.scrollHeight; }", feed
            )
            await page.wait_for_timeout(1100 + random.randint(0, 600))
            stagnant = stagnant + 1 if n == prev else 0
            if stagnant >= 5:
                break
            prev = n
        store["url"] = page.url

    return action


async def run_search(s, term: str, lat: float, lng: float, max_results: int) -> list[dict]:
    store = {}
    url = f"https://www.google.com/maps/search/{quote(term)}/@{lat:.6f},{lng:.6f},{config.SEARCH_ZOOM}z?{HL}"
    resp = await s.fetch(url, page_action=make_search_action(max_results, store))
    html = resp.body.decode("utf-8", "ignore")
    if is_blocked(store.get("url", ""), html):
        raise RuntimeError("Google blocked the session (sorry page)")
    if store.get("single"):
        final = store.get("url", "")
        if "/maps/place/" in final:
            h1 = Selector(html).css("h1")
            plat, plng = coords_from_url(final)
            return [{"name": h1[0].get_all_text().strip() if h1 else term, "url": final.split("?")[0],
                     "lat": plat, "lng": plng, **ids_from_url(final)}]
        return []
    return parse_search(html)


def place_key(p: dict) -> str:
    return p.get("place_id") or p.get("feature_id") or p["url"]


async def search(rings: list[int], only_rubros: list[str] | None):
    c = center()
    done = set(load_json(DATA / "searches_done.json", []))
    index = load_json(DATA / "places_index.json", {})
    jobs = []
    for ring in rings:
        km = config.RINGS_KM[ring]
        bearings = [0] if km == 0 else config.RING_BEARINGS[: 4 if ring == 1 else 8]
        for bearing in bearings:
            lat, lng = offset_point(c["lat"], c["lng"], km, bearing)
            for rubro, terms in config.RUBROS.items():
                if only_rubros and rubro not in only_rubros:
                    continue
                for term in terms:
                    job_id = f"{ring}|{bearing}|{term}"
                    if job_id not in done:
                        jobs.append((job_id, ring, rubro, term, lat, lng))
    log(f"{len(jobs)} searches pending")
    sem = asyncio.Semaphore(2)

    async with new_session(2) as s:
        async def worker(job):
            job_id, ring, rubro, term, lat, lng = job
            async with sem:
                await asyncio.sleep(random.uniform(0.5, 2.0))
                try:
                    results = await run_search(s, term, lat, lng, config.MAX_RESULTS_PER_SEARCH)
                except Exception as e:
                    log("search failed", job_id, e)
                    if "blocked" in str(e):
                        raise
                    return
                for r in results:
                    if r.get("lat") is None:
                        continue
                    k = place_key(r)
                    entry = index.setdefault(k, {**r, "rubros": [], "terms": [], "rings": []})
                    entry["dist_km"] = round(haversine_km(c["lat"], c["lng"], r["lat"], r["lng"]), 3)
                    for field, val in (("rubros", rubro), ("terms", term), ("rings", ring)):
                        if val not in entry[field]:
                            entry[field].append(val)
                    for field in ("rating", "reviews", "phone_hint", "card_text"):
                        if r.get(field) and not entry.get(field):
                            entry[field] = r[field]
                done.add(job_id)
                near = sum(1 for r in results if r.get("lat") and haversine_km(c["lat"], c["lng"], r["lat"], r["lng"]) <= 2)
                log(f"[{job_id}] {len(results)} results, {near} within 2 km | index={len(index)}")
                save_json(DATA / "places_index.json", index)
                save_json(DATA / "searches_done.json", sorted(done))

        await asyncio.gather(*(worker(j) for j in jobs))
    log(f"index has {len(index)} places")


# ------------------------------------------------------------------ details

REVIEWS_JS_SCROLL = """
() => {
  const first = document.querySelector('div[data-review-id]');
  let el = first;
  while (el && el !== document.body) {
    const st = getComputedStyle(el);
    if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
      el.scrollTop = el.scrollHeight; return document.querySelectorAll('div[data-review-id]').length;
    }
    el = el.parentElement;
  }
  return -1;
}
"""

EXPAND_JS = """
() => { let n = 0; document.querySelectorAll('button.w8nwRe, button[aria-label="Ver más"], button[aria-label="See more"]')
  .forEach(b => { try { b.click(); n++; } catch (e) {} }); return n; }
"""


def make_place_action(store: dict, review_scrolls: int):
    async def action(page):
        await handle_consent(page)
        try:
            await page.wait_for_selector("h1", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)
        store["overview"] = await page.content()
        store["url"] = page.url
        if is_blocked(page.url, store["overview"]):
            store["blocked"] = True
            return
        tab = page.locator('button[role="tab"][aria-label*="Reseñas"], button[role="tab"][aria-label*="Opiniones"]')
        if not await tab.count():
            tab = page.locator('button[role="tab"]:has-text("Reseñas")')
        if not await tab.count():
            return
        try:
            await tab.first.click()
            await page.wait_for_selector("div[data-review-id]", timeout=10000)
        except Exception:
            return
        await page.wait_for_timeout(1200)
        for _ in range(review_scrolls):
            n = await page.evaluate(REVIEWS_JS_SCROLL)
            await page.wait_for_timeout(900 + random.randint(0, 400))
            if n < 0:
                break
        await page.evaluate(EXPAND_JS)
        await page.wait_for_timeout(600)

    return action


async def fetch_place(s, entry: dict, review_scrolls: int) -> dict:
    store = {}
    url = entry["url"] + ("&" if "?" in entry["url"] else "?") + HL
    resp = await s.fetch(url, page_action=make_place_action(store, review_scrolls))
    if store.get("blocked"):
        raise RuntimeError("Google blocked the session (sorry page)")
    reviews_html = resp.body.decode("utf-8", "ignore")
    data = parse_place(store.get("overview", ""), reviews_html, store.get("url") or entry["url"])
    data["maps_url"] = entry["url"]
    return data


def safe_name(key: str) -> str:
    return re.sub(r"[^\w-]", "_", key)[:120]


async def details(limit: int, radius: float, review_scrolls: int, workers: int):
    c = center()
    index = load_json(DATA / "places_index.json", {})
    PLACES_DIR.mkdir(parents=True, exist_ok=True)
    todo = [
        (k, v) for k, v in sorted(index.items(), key=lambda kv: kv[1].get("dist_km", 99))
        if v.get("dist_km", 99) <= radius and not (PLACES_DIR / f"{safe_name(k)}.json").exists()
    ][:limit]
    log(f"{len(todo)} fichas to open (radius {radius} km)")
    sem = asyncio.Semaphore(workers)
    blocked = asyncio.Event()
    done_count = 0

    async with new_session(workers) as s:
        async def worker(k, entry):
            nonlocal done_count
            async with sem:
                if blocked.is_set():
                    return
                await asyncio.sleep(random.uniform(0.8, 2.5))
                try:
                    data = await fetch_place(s, entry, review_scrolls)
                except Exception as e:
                    log("ficha failed", entry.get("name"), e)
                    if "blocked" in str(e):
                        blocked.set()
                    return
                if not data.get("name"):
                    log("empty ficha", entry.get("name"))
                    return
                if data.get("lat") is None:
                    data["lat"], data["lng"] = entry.get("lat"), entry.get("lng")
                data["key"] = k
                data["dist_km"] = round(haversine_km(c["lat"], c["lng"], data["lat"], data["lng"]), 3)
                data["rubros_busqueda"] = entry.get("rubros", [])
                data["scraped_at"] = time.strftime("%Y-%m-%d %H:%M")
                save_json(PLACES_DIR / f"{safe_name(k)}.json", data)
                done_count += 1
                log(f"ok {done_count}/{len(todo)} {data['name']} | {data.get('category')} | "
                    f"{data.get('phone', '-')} | {data.get('rating')}★ {data.get('reviews')} | "
                    f"{len(data['review_items'])} reseñas leídas | {data['dist_km']} km")

        await asyncio.gather(*(worker(k, v) for k, v in todo))
    if blocked.is_set():
        log("STOPPED: Google is rate limiting this session")


# ------------------------------------------------------------------ probe


async def probe(url: str, out: str, reviews: bool):
    store = {}
    action = make_place_action(store, 2) if reviews else make_search_action(40, store)
    async with new_session(1) as s:
        resp = await s.fetch(url, page_action=action)
    Path(out).write_text(resp.body.decode("utf-8", "ignore"))
    if store.get("overview"):
        Path(out + ".overview.html").write_text(store["overview"])
    log("final url:", store.get("url") or resp.url, "| status:", resp.status, "| saved", out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("geocode")
    sp = sub.add_parser("search")
    sp.add_argument("--rings", default="0")
    sp.add_argument("--rubros", default="")
    dp = sub.add_parser("details")
    dp.add_argument("--limit", type=int, default=400)
    dp.add_argument("--radius", type=float, default=config.DETAIL_RADIUS_KM)
    dp.add_argument("--review-scrolls", type=int, default=3)
    dp.add_argument("--workers", type=int, default=3)
    pp = sub.add_parser("probe")
    pp.add_argument("url")
    pp.add_argument("--out", default="/tmp/probe.html")
    pp.add_argument("--place", action="store_true")
    args = ap.parse_args()

    if args.cmd == "geocode":
        asyncio.run(geocode())
    elif args.cmd == "search":
        rubros = [r.strip() for r in args.rubros.split(",") if r.strip()] or None
        asyncio.run(search([int(x) for x in args.rings.split(",")], rubros))
    elif args.cmd == "details":
        asyncio.run(details(args.limit, args.radius, args.review_scrolls, args.workers))
    elif args.cmd == "probe":
        asyncio.run(probe(args.url, args.out, args.place))


if __name__ == "__main__":
    main()
