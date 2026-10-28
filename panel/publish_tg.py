# -*- coding: utf-8 -*-
"""Публикация поста NYTreeToys в ТГ-канал @nytreetoys (Bot API, python requests).

Вызывается панелью (panel/server.py) при отложенной публикации или вручную:
    python panel/publish_tg.py --post posts/2026-10-28-kolomeev-post.json

Что делает:
  1. Шаг 0 — префлайт getMe (нет VPN / битый токен -> выход с кодом 2).
  2. Находит картинки поста для ТГ: assets/<пост>/<пост>-<N>-tg.jpg; если нет —
     единственная картинка из photos[0].file JSON-а поста.
  3. Одна картинка -> sendPhoto (фото + подпись, parse_mode HTML);
     несколько -> sendMediaGroup (подпись только у первого фото).
Токен берётся из secrets/доступы.md по маске; в вывод и командную строку не попадает.

Коды выхода: 0 — опубликовано; 2 — префлайт провален (включи VPN);
3 — подготовка (нет картинки / подпись длиннее 1024); 1 — ошибка API.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import requests

try:  # stdout в UTF-8 (панель и Git Bash читают байты как UTF-8)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PANEL_DIR = Path(__file__).resolve().parent
PROJECT = PANEL_DIR.parent            # work/own/zavod_NYTreeToys
FABRICA = PROJECT.parent.parent.parent
SECRET_FILE = FABRICA / "secrets" / "доступы.md"
CHAT = "@nytreetoys"
API = "https://api.telegram.org"
CAPTION_LIMIT = 1024


def find_images(post: dict, name: str, suffix: str) -> list:
    """Картинки поста под площадку: сперва -suffix-варианты из папки поста, затем photos[0].file."""
    out = []
    folder = PROJECT / "assets" / name
    if folder.is_dir():
        # <пост>-<N>-<suffix>.jpg — сортировка по номеру N, чтобы порядок был 1,2,3…
        def num_of(p: Path) -> int:
            """Номер картинки в имени: <пост>-N-tg.ext, <пост>-tg-N.ext или <пост>-tg.ext (=1)."""
            stem = p.stem
            m = re.search(rf"-{suffix}-(\d+)$|-(\d+)-{suffix}$", stem)
            if m:
                return int(m.group(1) or m.group(2))
            return 1 if stem.endswith(f"-{suffix}") else -1
        out = sorted(
            [p for p in folder.iterdir()
             if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
             and p.name.startswith(name) and num_of(p) >= 0],
            key=num_of,
        )
    if not out:
        photos = post.get("photos") or []
        if photos and photos[0].get("file"):
            f = PROJECT / photos[0]["file"]
            if f.is_file():
                out = [f]
    if not out:
        # фолбэк для постов с ген-картинками: assets/<пост>-<N>.png (в корне assets)
        gens = sorted((PROJECT / "assets").glob(f"{name}-*.png")) + \
               sorted((PROJECT / "assets").glob(f"{name}-*.jpg"))
        out = gens
    if not out:
        # фолбэк: сама папка поста без -tg-вариантов (продюсер взял оригиналы
        # с сайта, но не сделал площадочные варианты) — как у ВК-публикатора
        folder = PROJECT / "assets" / name
        if folder.is_dir():
            out = sorted([p for p in folder.iterdir()
                          if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
                         key=lambda p: p.name)
    return [p for p in out if p.is_file()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", required=True, help="путь к JSON поста, относительно корня проекта")
    args = ap.parse_args()

    post_path = PROJECT / args.post
    post = json.loads(post_path.read_text(encoding="utf-8"))
    name = post_path.stem

    caption = (post.get("platforms", {}).get("telegram", {}).get("content") or "").strip()
    if not caption:
        print("PREPARE_FAIL: в посте нет platforms.telegram.content")
        sys.exit(3)
    if len(caption) > CAPTION_LIMIT:
        print(f"PREPARE_FAIL: подпись {len(caption)} зн > {CAPTION_LIMIT} — сократи текст поста (не механической обрезкой)")
        sys.exit(3)

    images = find_images(post, name, "tg")
    if not images:
        print("PREPARE_FAIL: картинки поста не найдены (ни -tg-вариантов, ни photos[0].file)")
        sys.exit(3)
    print(f"images: {', '.join(p.name for p in images)}")

    # Токен по маске: <8-10 цифр>:<35+ символов>
    text = SECRET_FILE.read_text(encoding="utf-8")
    m = re.search(r"\d{8,10}:[A-Za-z0-9_-]{35,}", text)
    if not m:
        print("PREPARE_FAIL: токен бота в secrets/доступы.md не найден по маске")
        sys.exit(3)
    token = m.group(0)

    # Шаг 0 — префлайт
    try:
        resp = requests.get(f"{API}/bot{token}/getMe", timeout=15).json()
    except Exception as e:
        print(f"PREFLIGHT_FAIL: нет ответа от api.telegram.org ({e}) — включи VPN")
        sys.exit(2)
    if not resp.get("ok"):
        print(f"PREFLIGHT_FAIL: ok:false ({json.dumps(resp, ensure_ascii=False)}) — включи VPN")
        sys.exit(2)
    print(f"PREFLIGHT_OK: bot=@{resp['result'].get('username')}")

    base = f"{API}/bot{token}"
    if len(images) == 1:
        img = images[0]
        with img.open("rb") as f:
            r = requests.post(
                f"{base}/sendPhoto",
                data={"chat_id": CHAT, "parse_mode": "HTML", "caption": caption},
                files={"photo": (img.name, f, image_mime(img))},
                timeout=120,
            ).json()
        if not r.get("ok"):
            print("API_ERROR: " + json.dumps(r, ensure_ascii=False))
            sys.exit(1)
        msg_id = r["result"]["message_id"]
        print(f"PUBLISH_OK: message_id={msg_id} https://t.me/nytreetoys/{msg_id}")
        sys.exit(0)

    # Медиагруппа: подпись только у первого элемента
    files = {}
    media = []
    for i, img in enumerate(images):
        key = f"f{i}"
        files[key] = (img.name, img.open("rb").read(), image_mime(img))
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media.append(item)
    r = requests.post(
        f"{base}/sendMediaGroup",
        data={"chat_id": CHAT, "media": json.dumps(media, ensure_ascii=False)},
        files=files,
        timeout=120,
    ).json()
    if not r.get("ok"):
        print("API_ERROR: " + json.dumps(r, ensure_ascii=False))
        sys.exit(1)
    ids = [m_["message_id"] for m_ in r["result"]]
    print(f"PUBLISH_OK: messages={ids} https://t.me/nytreetoys/{ids[0]}")
    sys.exit(0)


def image_mime(p: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(p.suffix.lower(), "application/octet-stream")


if __name__ == "__main__":
    main()