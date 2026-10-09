"""Download each candidate's main Maps photo and tile them into contact sheets for review.

    python photos.py download
    python photos.py sheets --per 9
"""

import argparse
import json
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from scrapling.fetchers import FetcherSession

from build_report import DATA, candidates, load_places

PHOTOS = DATA / "photos"
SHEETS = DATA / "sheets"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
TILE_W, TILE_H, CAPTION = 360, 270, 34


def download():
    PHOTOS.mkdir(parents=True, exist_ok=True)
    cands, _ = candidates(load_places())
    todo = [p for p in cands if p.get("photo") and not (PHOTOS / f"{p['key']}.jpg").exists()]
    ok = 0
    with FetcherSession(impersonate="chrome") as s:
        for p in todo:
            try:
                r = s.get(p["photo"], timeout=20, stealthy_headers=True)
                img = Image.open(BytesIO(r.body)).convert("RGB")
                img.thumbnail((TILE_W * 2, TILE_H * 2))
                img.save(PHOTOS / f"{p['key']}.jpg", quality=85)
                ok += 1
            except Exception as e:
                print("photo failed", p["name"], e)
    print(f"downloaded {ok}/{len(todo)} photos")


def sheets(per: int):
    SHEETS.mkdir(parents=True, exist_ok=True)
    cands, _ = candidates(load_places())
    cands = sorted((p for p in cands if (PHOTOS / f"{p['key']}.jpg").exists()), key=lambda p: p["dist_km"])
    font = ImageFont.truetype(FONT, 15)
    cols = 3
    index = {}
    for n, start in enumerate(range(0, len(cands), per)):
        chunk = cands[start:start + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * TILE_W, rows * (TILE_H + CAPTION)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, p in enumerate(chunk):
            x, y = (i % cols) * TILE_W, (i // cols) * (TILE_H + CAPTION)
            img = Image.open(PHOTOS / f"{p['key']}.jpg")
            img.thumbnail((TILE_W - 6, TILE_H - 6))
            sheet.paste(img, (x + (TILE_W - img.width) // 2, y + (TILE_H - img.height) // 2))
            label = f"{i + 1}. {p['name']}"[:40]
            draw.text((x + 6, y + TILE_H + 8), label, fill="black", font=font)
            index[f"{n:02d}-{i + 1}"] = p["key"]
        sheet.save(SHEETS / f"sheet_{n:02d}.jpg", quality=80)
    (SHEETS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"{len(cands)} photos in {n + 1 if cands else 0} sheets")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["download", "sheets"])
    ap.add_argument("--per", type=int, default=9)
    a = ap.parse_args()
    download() if a.cmd == "download" else sheets(a.per)
