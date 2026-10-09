"""Google Maps lead scraper for Maipú, built on Scrapling's AsyncStealthySession.

The target is the corridor between Av. Portales and Av. Sur (two parallel avenues), see geo.py.

Stages (each one is resumable and writes to data/):
    python scrape_maps.py search --points centro,oeste,este   # list businesses per rubro
    python scrape_maps.py details --limit 300 --radius 0.8     # open fichas within 0.8 km of the band
    python scrape_maps.py probe URL [--place]                  # save a page's HTML for selector debugging
"""

import argparse
import asyncio
import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import quote

from scrapling.fetchers import AsyncStealthySession
from scrapling.parser import Selector

import config
import geo
from extract import coords_from_url, ids_from_url, parse_place, parse_search

DATA = Path(__file__).parent / "data"
PLACES_DIR = DATA / "places"
# a preinstalled Chromium if there is one, else the browser `scrapling install` downloads
CHROMIUM = os.environ.get("SCRAPLING_EXECUTABLE_PATH") or (
    "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
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


def new_session(max_pages=3, allow_photos=True) -> AsyncStealthySession:
    # Stealth mode hides navigator.webdriver; without it Google Maps serves a "limited view"
    # with no reviews tab. Certificate checks stay on (Scrapling's stealth default turns them off).
    return AsyncStealthySession(
        additional_args={"ignore_https_errors": False},
        headless=True,
        executable_path=CHROMIUM,
        locale="es-CL",
        timezone_id="America/Santiago",
        google_search=False,
        timeout=45000,
        retries=2,
        max_pages=max_pages,
        blocked_domains={"doubleclick.net", "googlesyndication.com", "google-analytics.com", "googletagmanager.com",
                         "streetviewpixels-pa.googleapis.com",
                         *(() if allow_photos else ("googleusercontent.com", "ggpht.com"))},
    )


# Map tiles are rendered in software here and eat the CPU; the data never needs them.
# (Fonts must load: without the icon font the reviews list stops paging.)
HEAVY = re.compile(r"/maps/vt|/kh/v=|/vt/pb=")


async def block_heavy(page):
    async def handler(route):
        await route.abort()

    await page.route(HEAVY, handler)


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


async def warm_up(s):
    """Google serves a 'limited view' (no reviews) to cookie-less first visits; one visit sets the cookies."""
    lat, lng = geo.CENTER

    async def act(page):
        await handle_consent(page)
        await page.wait_for_timeout(3000)

    await s.fetch(f"https://www.google.com/maps/@{lat},{lng},15z?{HL}", page_action=act, page_setup=block_heavy)


def is_blocked(url: str, html: str) -> bool:
    low = (html or "")[:200000].lower()
    return any(m in (url or "") or m in low for m in BLOCK_MARKERS)


def distances(lat: float, lng: float) -> dict:
    return {"dist_km": round(geo.band_distance_km(lat, lng), 3),
            "dist_center_km": round(geo.center_distance_km(lat, lng), 3)}


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
    resp = await s.fetch(url, page_action=make_search_action(max_results, store), page_setup=block_heavy)
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


async def search(points: list[str], only_rubros: list[str] | None, workers: int):
    done = set(load_json(DATA / "searches_done.json", []))
    index = load_json(DATA / "places_index.json", {})
    jobs = []
    for point in points:
        lat, lng = geo.SEARCH_POINTS[point]
        for rubro, terms in config.RUBROS.items():
            if only_rubros and rubro not in only_rubros:
                continue
            for term in terms:
                job_id = f"{point}|{term}"
                if job_id not in done:
                    jobs.append((job_id, point, rubro, term, lat, lng))
    log(f"{len(jobs)} searches pending")
    sem = asyncio.Semaphore(workers)
    blocked = asyncio.Event()

    async with new_session(workers) as s:
        await warm_up(s)

        async def worker(job):
            job_id, point, rubro, term, lat, lng = job
            async with sem:
                if blocked.is_set():
                    return
                await asyncio.sleep(random.uniform(0.5, 2.0))
                try:
                    results = await run_search(s, term, lat, lng, config.MAX_RESULTS_PER_SEARCH)
                except Exception as e:
                    log("search failed", job_id, e)
                    if "blocked" in str(e):
                        blocked.set()
                    return
                near = 0
                for r in results:
                    if r.get("lat") is None:
                        continue
                    k = place_key(r)
                    entry = index.setdefault(k, {**r, "rubros": [], "terms": [], "points": []})
                    entry.update(distances(r["lat"], r["lng"]))
                    near += entry["dist_km"] <= 0.5
                    for field, val in (("rubros", rubro), ("terms", term), ("points", point)):
                        if val not in entry[field]:
                            entry[field].append(val)
                    for field in ("rating", "reviews", "phone_hint", "card_text"):
                        if r.get(field) and not entry.get(field):
                            entry[field] = r[field]
                done.add(job_id)
                log(f"[{job_id}] {len(results)} results, {near} within 500 m of the band | index={len(index)}")
                save_json(DATA / "places_index.json", index)
                save_json(DATA / "searches_done.json", sorted(done))

        await asyncio.gather(*(worker(j) for j in jobs))
    if blocked.is_set():
        log("STOPPED: Google is rate limiting this session")
    log(f"index has {len(index)} places")


# ------------------------------------------------------------------ details

REVIEWS_JS_SCROLL = """
() => {
  const items = document.querySelectorAll('div.jftiEf');
  let el = items[items.length - 1];
  while (el && el !== document.body) {
    const st = getComputedStyle(el);
    if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
      el.scrollTop = el.scrollHeight; return items.length;
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

REVIEW_TOTAL_JS = """
() => {
  for (const e of document.querySelectorAll('[aria-label]')) {
    const m = (e.getAttribute('aria-label') || '').trim().match(/^([\\d.,\\s]+)\\s*(opini|reseñ)/);
    if (m) return parseInt(m[1].replace(/\\D/g, '')) || 0;
  }
  for (const e of document.querySelectorAll('div, span')) {  // newer layout: plain text "1,205 opiniones"
    const t = e.firstChild && e.firstChild.nodeType === 3 ? e.firstChild.textContent.trim() : '';
    const m = t.match(/^([\\d.,\\s]+)\\s*(opiniones|reseñas)$/);
    if (m) return parseInt(m[1].replace(/\\D/g, '')) || 0;
  }
  return 0;
}
"""
# newer layout shows 5 reviews and a "Ver más opiniones (N)" button instead of an endless list
MORE_REVIEWS = ('button[aria-label^="Ver más opiniones"], button[aria-label^="Más opiniones"], '
                'button[aria-label^="Ver más reseñas"], button[aria-label^="Más reseñas"]')

HERO_JS = """
() => {
  for (const img of document.querySelectorAll('button[jsaction*="heroHeaderImage"] img, button[aria-label^="Foto de"] img')) {
    if (img.src && img.src.includes('googleusercontent') && !/\\/a-?\\//.test(img.src)) return img.src;
  }
  for (const el of document.querySelectorAll('[style*="googleusercontent.com/"]')) {
    const m = (el.getAttribute('style') || '').match(/url\\("?(https:\\/\\/lh\\d\\.googleusercontent\\.com\\/[^")]+)/);
    if (m && !/\\/a-?\\//.test(m[1])) return m[1];
  }
  return '';
}
"""


async def wait_hero(page, ms=3000) -> str:
    for _ in range(ms // 250):
        src = await page.evaluate(HERO_JS)
        if src:
            return src
        await page.wait_for_timeout(250)
    return ""


TAB_SEL = ('button[role="tab"][aria-label^="Revisiones"], button[role="tab"][aria-label^="Reseñas"], '
           'button[role="tab"][aria-label^="Opiniones"]')


def make_place_action(store: dict, review_scrolls: int):
    async def action(page):
        await handle_consent(page)
        try:
            await page.wait_for_selector("h1", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)
        if is_blocked(page.url, await page.content()):
            store["blocked"] = True
            return
        tab = page.locator(TAB_SEL)
        has_rating = await page.locator('div.F7nice span[aria-hidden="true"]').count() > 0
        if has_rating and not await tab.count():
            # limited view: a second load with cookies set usually shows the full listing
            await page.reload()
            try:
                await page.wait_for_selector("h1", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            tab = page.locator(TAB_SEL)
        store["limited"] = has_rating and not await tab.count()
        try:
            expander = page.locator('[aria-label^="Mostrar el horario"]')
            if await expander.count():
                await expander.first.click(timeout=3000)
                await page.wait_for_timeout(700)
        except Exception:
            pass
        store["hero"] = await wait_hero(page, 2500)
        store["overview"] = await page.content()
        store["url"] = page.url
        if not await tab.count():
            return
        total = await page.evaluate(REVIEW_TOTAL_JS)  # 0 when the counter isn't rendered yet
        target = min(6, total) if total else 6
        try:
            await tab.first.click()
            # the overview already holds up to 3 reviews, so wait for the reviews list itself to fill
            await page.wait_for_function(f"document.querySelectorAll('div.jftiEf').length >= {target}", timeout=9000)
        except Exception:
            pass
        await page.wait_for_timeout(900)
        more = page.locator(MORE_REVIEWS)
        if await more.count():
            try:
                shown = await page.evaluate("document.querySelectorAll('div.jftiEf').length")
                await more.first.click()
                await page.wait_for_function(f"document.querySelectorAll('div.jftiEf').length > {shown}", timeout=9000)
            except Exception:
                pass
            await page.wait_for_timeout(700)
        for _ in range(review_scrolls if (total == 0 or total > 10) else 0):
            n = await page.evaluate(REVIEWS_JS_SCROLL)
            await page.wait_for_timeout(1100 + random.randint(0, 500))
            if n < 0:
                break
        await page.evaluate(EXPAND_JS)
        await page.wait_for_timeout(500)

    return action


async def fetch_place(s, entry: dict, review_scrolls: int) -> dict:
    store = {}
    url = entry["url"] + ("&" if "?" in entry["url"] else "?") + HL
    resp = await s.fetch(url, page_action=make_place_action(store, review_scrolls), page_setup=block_heavy)
    if store.get("blocked"):
        raise RuntimeError("Google blocked the session (sorry page)")
    reviews_html = resp.body.decode("utf-8", "ignore")
    data = parse_place(store.get("overview", ""), reviews_html, store.get("url") or entry["url"])
    data["maps_url"] = entry["url"]
    data["limited_view"] = store.get("limited", False)
    if not data.get("photo") and store.get("hero"):
        data["photo"] = re.sub(r"=w\d+-h\d+[^&]*$", "=w480-h360-k-no", store["hero"])
    return data


def safe_name(key: str) -> str:
    return re.sub(r"[^\w-]", "_", key)[:120]


async def details(limit: int, radius: float, review_scrolls: int, workers: int, keys: list[str] | None = None):
    index = load_json(DATA / "places_index.json", {})
    PLACES_DIR.mkdir(parents=True, exist_ok=True)
    if keys:  # re-read specific fichas, overwriting what was saved
        todo = [(k, index[k]) for k in keys if k in index]
    else:
        todo = [
            (k, v) for k, v in sorted(index.items(), key=lambda kv: (kv[1].get("dist_km", 99), kv[1].get("dist_center_km", 99)))
            if v.get("dist_km", 99) <= radius and not (PLACES_DIR / f"{safe_name(k)}.json").exists()
        ][:limit]
    log(f"{len(todo)} fichas to open (within {radius} km of the band)")
    sem = asyncio.Semaphore(workers)
    blocked = asyncio.Event()
    done_count = 0

    async with new_session(workers) as s:
        await warm_up(s)

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
                data.update(distances(data["lat"], data["lng"]))
                data["rubros_busqueda"] = entry.get("rubros", [])
                data["scraped_at"] = time.strftime("%Y-%m-%d %H:%M")
                save_json(PLACES_DIR / f"{safe_name(k)}.json", data)
                done_count += 1
                log(f"ok {done_count}/{len(todo)} {data['name']} | {data.get('category')} | "
                    f"{data.get('phone', '-')} | {data.get('rating')}★ {data.get('reviews')} | "
                    f"{len(data['review_items'])} reseñas leídas{' | LIMITED' if data['limited_view'] else ''} | "
                    f"{data['dist_km']} km")

        await asyncio.gather(*(worker(k, v) for k, v in todo))
    if blocked.is_set():
        log("STOPPED: Google is rate limiting this session")


async def photo_pass(only_keys: list[str] | None, workers: int):
    """Fill in the main photo for saved fichas that have none (overview only, no reviews)."""
    files = sorted(PLACES_DIR.glob("*.json"))
    todo = []
    for f in files:
        d = json.loads(f.read_text())
        if not d.get("photo") and (not only_keys or d["key"] in only_keys):
            todo.append((f, d))
    log(f"{len(todo)} fichas without photo")
    sem = asyncio.Semaphore(workers)
    async with new_session(workers) as s:
        await warm_up(s)

        async def worker(f, d):
            async with sem:
                store = {}

                async def act(page):
                    await handle_consent(page)
                    try:
                        await page.wait_for_selector("h1", timeout=15000)
                    except Exception:
                        pass
                    store["hero"] = await wait_hero(page, 5000)

                try:
                    await s.fetch(d["maps_url"] + "?" + HL, page_action=act, page_setup=block_heavy)
                except Exception as e:
                    log("photo failed", d["name"], e)
                    return
                if store.get("hero"):
                    d["photo"] = re.sub(r"=w\d+-h\d+[^&]*$", "=w480-h360-k-no", store["hero"])
                    save_json(f, d)
                log(("photo ok " if store.get("hero") else "no photo ") + d["name"])

        await asyncio.gather(*(worker(f, d) for f, d in todo))


def reindex():
    """Recompute distances in the index after the sector geometry changes."""
    index = load_json(DATA / "places_index.json", {})
    for entry in index.values():
        if entry.get("lat") is not None:
            entry.update(distances(entry["lat"], entry["lng"]))
    save_json(DATA / "places_index.json", index)
    for limit in (0, 0.25, 0.5, 0.8):
        log(f"within {limit} km of the sector: {sum(1 for e in index.values() if e.get('dist_km', 99) <= limit)}")


# ------------------------------------------------------------------ probe


async def probe(url: str, out: str, place: bool):
    store = {}
    action = make_place_action(store, 2) if place else make_search_action(40, store)
    async with new_session(1) as s:
        await warm_up(s)
        resp = await s.fetch(url, page_action=action, page_setup=block_heavy)
    Path(out).write_text(resp.body.decode("utf-8", "ignore"))
    if store.get("overview"):
        Path(out + ".overview.html").write_text(store["overview"])
    log("final url:", store.get("url") or resp.url, "| status:", resp.status, "| saved", out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("search")
    sp.add_argument("--points", default="centro,oeste,este")
    sp.add_argument("--rubros", default="")
    sp.add_argument("--workers", type=int, default=2)
    dp = sub.add_parser("details")
    dp.add_argument("--limit", type=int, default=400)
    dp.add_argument("--radius", type=float, default=0.8)
    dp.add_argument("--review-scrolls", type=int, default=2)
    dp.add_argument("--workers", type=int, default=3)
    dp.add_argument("--keys", default="", help="comma-separated place keys to re-read")
    sub.add_parser("reindex")
    php = sub.add_parser("photos")
    php.add_argument("--keys", default="")
    php.add_argument("--workers", type=int, default=3)
    pp = sub.add_parser("probe")
    pp.add_argument("url")
    pp.add_argument("--out", default="/tmp/probe.html")
    pp.add_argument("--place", action="store_true")
    args = ap.parse_args()

    if args.cmd == "search":
        rubros = [r.strip() for r in args.rubros.split(",") if r.strip()] or None
        asyncio.run(search([p.strip() for p in args.points.split(",")], rubros, args.workers))
    elif args.cmd == "details":
        asyncio.run(details(args.limit, args.radius, args.review_scrolls, args.workers,
                            [k for k in args.keys.split(",") if k] or None))
    elif args.cmd == "photos":
        asyncio.run(photo_pass([k for k in args.keys.split(",") if k] or None, args.workers))
    elif args.cmd == "reindex":
        reindex()
    elif args.cmd == "probe":
        asyncio.run(probe(args.url, args.out, args.place))


if __name__ == "__main__":
    main()
