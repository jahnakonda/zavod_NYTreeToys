# -*- coding: utf-8 -*-
"""Панель управления NYTreeToys — локальный бэкенд по варианту C.

Запуск:  python panel/server.py            (из корня zavod_NYTreeToys или FABRICA — не важно)
Открывать: http://127.0.0.1:8123

Возможности:
  - «Запустить исследователя» — headless claude -p с заданием research/cron-task.md
    (тот же механизм, что у Планировщика задач).
  - «Сделать пост про X» — headless продюсер (writer -> editor -> fetch-photos);
    генерация ComfyUI исключена, картинки берутся из источников. Пост остаётся
    черновиком — в очередь публикации попадает только через владельца.
  - Отложенная публикация: пост + время + площадки -> очередь; в назначенное время
    сервер запускает panel/publish_tg.py (Bot API) и/или panel/publish_vk.py (UI).
    Автоповтора нет: провал = статус «не удалось» с причиной и кнопкой «Повторить».
  - VK-логин: одна кнопка открывает браузер автоматизации для входа; сессия
    сохраняется в panel/vk-profile (вне git — куки!).
Только stdlib Python; состояние — SQLite panel/panel.db (переносит перезапуск).
Сервер слушает только 127.0.0.1.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PANEL_DIR = Path(__file__).resolve().parent
PROJECT = PANEL_DIR.parent          # work/own/zavod_NYTreeToys
DB = PANEL_DIR / "panel.db"
RUNS = PANEL_DIR / "runs"
STATIC = PANEL_DIR / "static"
PORT = 8123

PUBLISH_SCRIPTS = {"tg": PANEL_DIR / "publish_tg.py", "vk": PANEL_DIR / "publish_vk.py"}

if not hasattr(sys, "ps1"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------- БД

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,            -- researcher | producer | vk-login | site-deploy
            params TEXT,          -- свободные параметры (тема поста и т.п.)
            status TEXT,          -- running | done | failed
            started TEXT, finished TEXT,
            exit_code INTEGER,
            meta TEXT             -- JSON: {card_file, run_at, platforms} для поста по карточке
        );
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post TEXT,            -- posts/2026-10-28-kolomeev-post.json
            run_at TEXT,          -- 'YYYY-MM-DD HH:MM' локальное
            platforms TEXT,       -- '["tg","vk"]'
            status TEXT,          -- draft | pending | publishing | deferred | done | failed | cancelled
            detail TEXT,          -- человекочитаемая причина/итог
            links TEXT,           -- JSON: {"tg": "…", "vk": "…"}
            attempts INTEGER DEFAULT 0,
            created TEXT,
            last_log TEXT,
            site_update INTEGER DEFAULT 0   -- после публикации пересобрать и задеплоить сайт
        );
        CREATE TABLE IF NOT EXISTS published (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post TEXT UNIQUE,     -- posts/<файл>.json; строка на пост: ссылки в links
            links TEXT,           -- JSON: {"tg": url, "vk": url}
            published_at TEXT
        );
        """)
        try:
            c.execute("ALTER TABLE queue ADD COLUMN site_update INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
        try:
            c.execute("ALTER TABLE runs ADD COLUMN meta TEXT")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
        seed_published(c)
        if not RUNS.exists():
            RUNS.mkdir()


# Опубликованные ДО появления панели (факты из журнала сессий 2026-10-10..28);
# ссылки ВК = wall-242169556_N, ТГ = первые id медиа-сообщений.
PUBLISHED_SEED = [
    ("posts/2026-10-10-rozhdestvenskoe-yabloko-post.json",
     {"vk": "https://vk.ru/wall-242169556_2", "tg": "https://t.me/nytreetoys/5"}, "2026-10-10"),
    ("posts/2026-10-10-yolochka-post.json",
     {"vk": "https://vk.ru/wall-242169556_3", "tg": "https://t.me/nytreetoys/6"}, "2026-10-10"),
    ("posts/2026-10-11-biryusinka-post.json",
     {"vk": "https://vk.ru/wall-242169556_4", "tg": "https://t.me/nytreetoys/7"}, "2026-10-11"),
    ("posts/2026-10-28-ariel-post.json",
     {"vk": "https://vk.ru/wall-242169556_5", "tg": "https://t.me/nytreetoys/11"}, "2026-10-28"),
    ("posts/2026-10-28-lenigrushka-post.json",
     {"vk": "https://vk.ru/wall-242169556_6", "tg": "https://t.me/nytreetoys/12"}, "2026-10-28"),
    ("posts/2026-10-28-kolomeev-post.json",
     {"vk": "https://vk.ru/wall-242169556_7", "tg": "https://t.me/nytreetoys/13"}, "2026-10-28"),
]


def seed_published(c: sqlite3.Connection) -> None:
    n = c.execute("SELECT COUNT(*) FROM published").fetchone()[0]
    if n:
        return
    for post, links, when in PUBLISHED_SEED:
        if (PROJECT / post).is_file():
            c.execute("INSERT OR IGNORE INTO published(post, links, published_at) VALUES (?,?,?)",
                      (post, json.dumps(links, ensure_ascii=False), when))


def post_title(post_file: str) -> str:
    """Заголовок поста: имя фабрики из карточки research/fabriki + город (как в блоге сайта)."""
    stem = Path(post_file).stem
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem).replace("-post", "")
    card = {}
    for f in (PROJECT / "research" / "fabriki").glob("*.json"):
        if f.stem == slug or f.stem.startswith(slug + "-"):
            try:
                card = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
            break

    def short_name(name: str) -> str:
        m = re.search(r"«([^»]+)»", str(name or ""))
        if m:
            return "«%s»" % m.group(1)
        return re.sub(r"^(Предприятие|Фабрика|Мастерская|Студия)\s+НХП?\s*", "",
                      str(name or "")).strip()

    name = short_name(card.get("name", ""))
    if not name:
        return slug
    city = str(card.get("city") or "")
    return name + (", %s" % city if city and city not in name else "")


def cards_list() -> list:
    """База карточек research/fabriki: поля + опубликована ли (есть пост -> карточка)."""
    pub = {}
    for r in published_list():
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", Path(r["post"]).stem).replace("-post", "")
        pub[slug] = r
    # карточки, для которых пост уже в очереди (сформирован/ждёт/публикуется) — не давать вторую
    queued = {}
    with db() as c:
        for r in c.execute("SELECT post, status FROM queue "
                           "WHERE status IN ('draft','pending','publishing','deferred')").fetchall():
            slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", Path(r["post"]).stem).replace("-post", "")
            queued[slug] = r["status"]
    out = []
    for f in sorted((PROJECT / "research" / "fabriki").glob("*.json")):
        try:
            card = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        post = None
        # та же связка, что find_card в sync-скрипте: card == slug или card начинается с slug + "-"
        for slug, r in pub.items():
            if f.stem == slug or f.stem.startswith(slug + "-"):
                post = r
                break
        out.append({
            "file": f"research/fabriki/{f.name}",
            "name": str(card.get("name") or f.stem),
            "city": card.get("city") or "",
            "type": card.get("type") or "",
            "status": card.get("status") or "",
            "post": post["post"] if post else None,
            "links": post["links"] if post else None,
            "queued": any(f.stem == s or f.stem.startswith(s + "-") for s in queued),
        })
    return out


def post_card_info(post_file: str) -> dict:
    """Карточка по связке пост↔карточка: имя, город, заголовок поста."""
    stem = Path(post_file).stem
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem).replace("-post", "")
    name, city = "", ""
    card_file = next((p for p in (PROJECT / "research" / "fabriki").glob("*.json")
                      if p.stem == slug or p.stem.startswith(slug + "-")), None)
    if card_file:
        try:
            card = json.loads(card_file.read_text(encoding="utf-8"))
            name = str(card.get("name") or "")
            city = str(card.get("city") or "")
        except Exception:
            pass
    return {"name": name, "city": city, "title": post_title(post_file)}


def site_post_link(post_file: str) -> str:
    """Ссылка на пост на сайте — только если он уже в задеплоенной копии (tmp/nytoys-pages/blog.html)."""
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", Path(post_file).stem).replace("-post", "")
    try:
        blog = (PAGES_DIR / "blog.html").read_text(encoding="utf-8")
    except OSError:
        return ""
    return f"https://jahnakonda.github.io/nytoys-site/blog.html#{slug}" if f'id="{slug}"' in blog else ""


def published_list() -> list:
    """Посты с публикациями: для sync-скрипта (только они попадают на сайт) и UI."""
    with db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM published ORDER BY post DESC")]
    for r in rows:
        r["links"] = json.loads(r["links"]) if r["links"] else {}
        site = site_post_link(r["post"])
        if site:
            r["links"]["site"] = site
        r["title"] = post_title(r["post"])
    return rows


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- Запуск headless-агентов

PROGRESS = {}  # run_id -> {"percent": int, "stage": str, "ts": str} — блок «Ход работы»


def progress(run_id: int, percent: int, stage: str) -> None:
    PROGRESS[run_id] = {"percent": percent, "stage": stage, "ts": now_str()}
    for old in sorted(PROGRESS)[:-40]:   # держим ход последних 40 запусков
        PROGRESS.pop(old, None)


def sweep_interrupted() -> None:
    """После рестарта панели: работавшие запуски считать упавшими (поток умер),
    неподтверждённые посты продюсера вернуть в статус «сформирован»."""
    with db() as c:
        for (rid,) in c.execute("SELECT id FROM runs WHERE status='running'").fetchall():
            c.execute("UPDATE runs SET status='failed', exit_code=1, finished=? WHERE id=?",
                      (now_str(), rid))
            lf = RUNS / f"{rid}.log"
            if lf.is_file():
                with lf.open("a", encoding="utf-8") as f:
                    f.write("=== ПРИОСТАНОВЛЕНО: панель перезапустили во время работы ===\n")
        c.execute("UPDATE queue SET status='draft', detail='сформирован, ждёт подтверждения' "
                  "WHERE status='pending' AND detail LIKE 'создано продюсером%'")


# субагент -> (процент готовности, что происходит)
SUBAGENT_STAGE = {
    "nytoys-writer": (30, "писатель: готовит текст поста"),
    "nytoys-editor": (55, "редактор: вычитывает и правит"),
    "nytoys-fetch-photos": (75, "фото: собирает снимки из источников"),
    "nytoys-image": (75, "изображения: генерирует картинку"),
    "nytoys-researcher": (20, "исследователь: работа с базой карточек"),
}


def tool_line(name: str, inp: dict, tools_seen: int) -> tuple:
    """Событие инструмента -> (строка лога, процент или None, стадия или None)."""
    ts = datetime.now().strftime("%H:%M")
    if name == "Task":
        sa = str(inp.get("subagent_type") or "агент")
        pct, stage = SUBAGENT_STAGE.get(sa, (None, None))
        desc = str(inp.get("description") or inp.get("prompt") or "")[:100]
        return f"[{ts}] субагент {sa}: {desc}", pct, stage
    if name in ("Write", "Edit"):
        fp = str(inp.get("file_path") or "")
        verb = "пишет" if name == "Write" else "правит"
        if "posts/" in fp and fp.endswith(".json"):
            return f"[{ts}] пост собран: {fp}", 88, "пост собран, финализация"
        return f"[{ts}] {verb}: {fp}", None, None
    if name == "Read":
        return f"[{ts}] читает: {str(inp.get('file_path') or '')}", None, None
    if name in ("Glob", "Grep"):
        q = str(inp.get("pattern") or inp.get("query") or "")
        return f"[{ts}] ищет: {q[:80]}", None, None
    if name == "Bash":
        return f"[{ts}] команда: {str(inp.get('command') or '')[:90]}", None, None
    if name in ("WebSearch", "WebFetch"):
        q = str(inp.get("query") or inp.get("url") or "")
        return f"[{ts}] ищет в вебе: {q[:80]}", None, None
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        done = sum(1 for t in todos if t.get("status") == "completed")
        pct = 10 + round(70 * done / max(1, len(todos)))
        return (f"[{ts}] план: {done}/{len(todos)} шагов", pct, f"шагов сделано: {done}/{len(todos)}")
    return f"[{ts}] инструмент {name}", None, None


def spawn_claude(log_path: Path, task_brief: str, run_id: int = 0) -> int:
    """Кладёт задание в UTF-8 файл (кодировки cmd обходятся) и запускает claude -p.

    Вывод --output-format stream-json разбирается по событиям: из них складываются
    понятные строки прогресса в лог и в PROGRESS (блок «Ход работы»).
    """
    task_id = log_path.stem
    task_file = RUNS / f"task-{task_id}.md"
    task_file.write_text(task_brief, encoding="utf-8")
    prompt = ("Read the task file panel/runs/task-" + task_id + ".md and execute it fully "
              "and autonomously. This is an unattended run: do not ask questions, work to "
              "completion. Write the final report (in Russian) to stdout.")
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("claude не найден в PATH")
    cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if claude.lower().endswith(".cmd"):
        cmd = ["cmd", "/c"] + cmd
    p = subprocess.Popen(cmd, cwd=str(PROJECT), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    tools_seen = 0
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"=== START {now_str()} ===\n")
        log.flush()
        progress(run_id, 2, "агент запускается")
        for raw in p.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                log.write(line + "\n")   # не-JSON (ошибки CLI и т.п.) — как есть
                continue
            kind = ev.get("type")
            if kind == "system" and ev.get("subtype") == "init":
                log.write(f"[{datetime.now():%H:%M}] старт: сессия открыта "
                          f"(модель {ev.get('model') or '?'})\n")
            elif kind == "assistant":
                for blk in (ev.get("message") or {}).get("content") or []:
                    if blk.get("type") == "tool_use":
                        tools_seen += 1
                        out, pct, stage = tool_line(str(blk.get("name")),
                                                    blk.get("input") or {}, tools_seen)
                        if out:
                            log.write(out + "\n")
                        if pct or stage:
                            prev = PROGRESS.get(run_id, {"percent": 0})
                            progress(run_id, max(prev.get("percent", 0), pct or 0),
                                     stage or prev.get("stage", ""))
                    elif blk.get("type") == "text":
                        s = (blk.get("text") or "").strip()
                        if s:
                            log.write(f"[{datetime.now():%H:%M}] сообщение: "
                                      f"{s.splitlines()[0][:120]}\n")
            elif kind == "result":
                res = (ev.get("result") or "").strip().splitlines()
                log.write(f"[{datetime.now():%H:%M}] агент завершил ({'ошибка' if ev.get('is_error') else 'успех'}): "
                          f"{res[0][:150] if res else ''}\n")
        p.wait()
        code = p.returncode
        log.write(f"=== END {now_str()} exit={code} ===\n")
    return code


def new_run(kind: str, params: str) -> int:
    with db() as c:
        c.execute("INSERT INTO runs(kind, params, status, started) VALUES (?,?,?,?)",
                  (kind, params, "running", now_str()))
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def finish_run(run_id: int, exit_code: int) -> None:
    status = "done" if exit_code == 0 else "failed"
    with db() as c:
        c.execute("UPDATE runs SET status=?, finished=?, exit_code=? WHERE id=?",
                  (status, now_str(), exit_code, run_id))


def run_run_thread(run_id: int, kind: str, params: str, meta: dict = None) -> None:
    log_path = RUNS / f"{run_id}.log"
    before = {p.name for p in (PROJECT / "posts").glob("*.json")} if (kind == "producer" and meta) else None
    try:
        if kind == "researcher":
            brief = (PROJECT / "research" / "cron-task.md").read_text(encoding="utf-8")
        else:  # producer
            tpl = (PANEL_DIR / "producer-task.md").read_text(encoding="utf-8")
            card_file = (meta or {}).get("card_file")
            brief = (tpl.replace("{TOPIC}", params)
                        .replace("{CARD_FILE}", card_file or "(карточка не указана — найди источник сам)"))
        code = spawn_claude(log_path, brief, run_id)
    except Exception as e:
        log_path.write_text(f"ERROR: {e}\n", encoding="utf-8")
        code = 1
    finish_run(run_id, code)
    progress(run_id, 100, "готово" if code == 0 else f"завершено с ошибкой (код {code})")
    # Пост по карточке: продюсер отработал — находим созданный пост и ставим в очередь
    if kind == "producer" and meta and code == 0:
        after = {p.name for p in (PROJECT / "posts").glob("*.json")}
        created = sorted(after - (before or set()))
        run_at = meta.get("run_at") or ""
        platforms = meta.get("platforms") or ["vk", "tg"]
        if created and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", run_at):
            post = "posts/" + max(created)   # если вдруг несколько — берём новейшую по дате поста
            no_photo = not post_has_photos(post)
            with db() as c:
                c.execute("INSERT INTO queue(post, run_at, platforms, status, detail, links, "
                          "attempts, created, site_update) VALUES (?,?,?,?,?,?,0,?,1)",
                          (post, run_at, json.dumps(platforms), "draft",
                           "сформирован из карточки, ждёт подтверждения"
                           + (" · БЕЗ ФОТО" if no_photo else ""),
                           json.dumps({}), now_str()))
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"=== DRAFT: {post} -> {run_at} ({', '.join(platforms)})"
                        + ("; снимков нет — владелец добавит" if no_photo else "") +
                        f"; владелец подтверждает публикацию ===\n")
        else:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"=== NOSCHEDULE: новые посты не найдены, в очередь не поставлено ===\n")


# ---------------------------------------------------------------- Очередь публикаций

pub_lock = threading.Lock()


def publish_due_worker() -> None:
    """Фоновый поток: раз в 20 сек проверяет очередь и публикует подошвшие задачи.

    «Сформированные» (draft) тоже активируются по времени — владелец мог их уже
    отредактировать; отменить можно до наступления времени.
    """
    while True:
        try:
            with db() as c:
                rows = c.execute(
                    "SELECT id FROM queue WHERE status IN ('pending','draft') "
                    "AND run_at <= ? ORDER BY run_at",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"),)).fetchall()
            if rows and pub_lock.acquire(blocking=False):
                try:
                    for r in rows:
                        publish_queue_task(r["id"])
                finally:
                    pub_lock.release()
        except Exception as e:
            print(f"[scheduler] {e}", file=sys.stderr)
        time.sleep(20)


def subprocess_env() -> dict:
    """Дочерние публикаторы печатают UTF-8 (иначе cp1251-мусор в логах панели)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_publish_step(platform: str, post: str) -> tuple:
    """Один шаг публикации: (код выхода, вывод-хвост)."""
    cmd = [sys.executable, str(PUBLISH_SCRIPTS[platform]), "--post", post]
    p = subprocess.run(cmd, cwd=str(PROJECT), capture_output=True, timeout=600, env=subprocess_env())
    out = (p.stdout or b"") + (p.stderr or b"")
    try:
        tail = out.decode("utf-8", errors="replace")[-4000:]
    except Exception:
        tail = repr(out)[-1000:]
    return p.returncode, tail


def post_has_photos(post_file: str) -> bool:
    """Есть ли у поста снимки: photos[] или картинки в assets/<пост>/ (или <пост>-* в assets)."""
    stem = Path(post_file).stem
    try:
        post = json.loads((PROJECT / post_file).read_text(encoding="utf-8"))
    except Exception:
        post = {}
    if post.get("photos"):
        return True
    fold = PROJECT / "assets" / stem
    try:
        if any(f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") for f in fold.iterdir()):
            return True
    except OSError:
        pass
    return any(p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
               for p in (PROJECT / "assets").glob(f"{stem}-*"))


def publish_queue_task(qid: int) -> None:
    with db() as c:
        row = c.execute("SELECT * FROM queue WHERE id=?", (qid,)).fetchone()
    if not row or row["status"] not in ("pending", "draft"):
        return
    if not post_has_photos(row["post"]):
        # без снимков публикация заведомо упадёт (код 3) — не выпускаем, ждём владельца
        if "нет фото" not in (row["detail"] or ""):
            with db() as c:
                c.execute("UPDATE queue SET detail=? WHERE id=?",
                          ((row["detail"] or "") + " · нет фото — публикация заблокирована, "
                           "добавь снимки и жми «Опубликовать сейчас»", qid))
        return
    platforms = json.loads(row["platforms"])
    links = json.loads(row["links"]) if row["links"] else {}
    details, logs = [], []
    with db() as c:
        c.execute("UPDATE queue SET status='publishing', attempts=attempts+1 WHERE id=?", (qid,))
    for plat in platforms:
        if links.get(plat):
            # уже ушло в прошлый раз (например, ТГ ок, а ВК упал) — не задублировать
            details.append(f"{plat}: уже опубликован ранее, пропущено")
            continue
        code, out = run_publish_step(plat, row["post"])
        logs.append(f"--- {plat.upper()} ---\n{out}")
        if code == 0:
            m2 = re.search(r"PUBLISH_OK:? (\S+)", out) or re.search(r"https://\S+", out)
            links[plat] = m2.group(1) if m2 else None
            details.append(f"{plat}: ок")
        else:
            reason = "включи VPN" if code == 2 else ("подготовка" if code == 3 else "ошибка")
            details.append(f"{plat}: не удалось ({reason}, код {code})")
            status = "failed"
            break
    else:
        status = "done"
    with db() as c:
        c.execute("UPDATE queue SET status=?, detail=?, links=?, last_log=? WHERE id=?",
                  (status, " | ".join(details), json.dumps(links, ensure_ascii=False),
                   "\n".join(logs)[-8000:], qid))
    if status == "done":
        with db() as c:
            c.execute("INSERT OR REPLACE INTO published(post, links, published_at) VALUES (?,?,?)",
                      (row["post"], json.dumps(links, ensure_ascii=False), now_str()))
        if row["site_update"]:
            rid = new_run("site-deploy", f"после публикации {row['post']}")
            threading.Thread(target=run_site_deploy, args=(rid,), daemon=True).start()


PAGES_DIR = Path("K:/FABRICA/tmp/nytoys-pages")   # демо-репо GitHub Pages (журнал 2026-10-16)


def run_site_deploy(run_id: int) -> None:
    """Пересборка сайта: sync (только опубликованные) → линк-чекер → копия в pages-репо → push."""
    log = []
    import shutil
    try:
        pub = published_list()
        names = [Path(r["post"]).name for r in pub if (PROJECT / r["post"]).is_file()]
        (PANEL_DIR / "site-published.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
        steps = [
            ("sync", [sys.executable, "tmp/sync_nytoys_blog.py", "--published",
                      str((PANEL_DIR / "site-published.txt").resolve())]),
            ("check", [sys.executable, "knowledge/scripts/check_site_links.py",
                       "work/own/zavod_NYTreeToys/site"]),
        ]
        for title, cmd in steps:
            p = subprocess.run(cmd, cwd="K:/FABRICA", capture_output=True, timeout=300,
                               env=subprocess_env())
            log.append(f"=== {title} (exit {p.returncode}) ===\n"
                       f"{(p.stdout or b'').decode('utf-8', 'replace')[-2000:]}"
                       f"{(p.stderr or b'').decode('utf-8', 'replace')[-1000:]}")
            if p.returncode != 0:
                finish_run(run_id, 1)
                _write_run_log(run_id, log + [f"СТОП: {title} провален"])
                return
        # Копия в pages-репо (.git не трогаем; img/ заменяем целиком — грабля деплоя 28.10)
        if not (PAGES_DIR / ".git").is_dir():
            finish_run(run_id, 1)
            _write_run_log(run_id, log + [f"СТОП: {PAGES_DIR} — нет .git (демо-репо потерян?)"])
            return
        img_src, img_dst = PROJECT / "site" / "img", PAGES_DIR / "img"
        if img_dst.exists():
            shutil.rmtree(img_dst)
        shutil.copytree(PROJECT / "site", PAGES_DIR, dirs_exist_ok=True)
        # коммит + push (деплой по кнопке/чекбоксу владельца в панели — его команда)
        for cmd in (
            ["git", "add", "-A"],
            ["git", "commit", "-m",
             f"NYTreeToys site sync: {len(names)} постов, {now_str()}\n\n"
             "Co-Authored-By: Claude Code <noreply@anthropic.com>"],
            ["git", "push"],
        ):
            p = subprocess.run(cmd, cwd=str(PAGES_DIR), capture_output=True, timeout=180)
            log.append(f"=== {cmd[0]} {cmd[1] if len(cmd) > 1 else ''} (exit {p.returncode}) ===\n"
                       f"{(p.stdout or b'').decode('utf-8', 'replace')[-1500:]}"
                       f"{(p.stderr or b'').decode('utf-8', 'replace')[-1500:]}")
            if p.returncode != 0 and (b"nothing to commit" not in (p.stdout or b"") + (p.stderr or b"")):
                finish_run(run_id, 1)
                _write_run_log(run_id, log + ["СТОП: git провален"])
                return
        log.append(f"DEPLOY_OK: задеплоено {len(names)} постов в {PAGES_DIR.name} (Pages обновится через 1–2 мин)")
        _write_run_log(run_id, log)
        finish_run(run_id, 0)
    except Exception as e:
        finish_run(run_id, 1)
        _write_run_log(run_id, log + [f"ERROR: {e}"])


def _write_run_log(run_id: int, lines: list) -> None:
    (RUNS / f"{run_id}.log").write_text("\n".join(str(x) for x in lines), encoding="utf-8")


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # тишина в консоль
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _post_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        for enc in ("utf-8", "cp1251"):
            try:
                return json.loads(raw.decode(enc))
            except UnicodeDecodeError:
                continue
            except Exception:
                return {}
        return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/" or u.path == "/index.html":
            f = STATIC / "index.html"
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/state":
            self.api_state()
        elif u.path == "/api/posts":
            self.api_posts()
        elif u.path == "/api/log":
            self.api_log(parse_qs(u.query).get("run", [""])[0])
        elif u.path == "/api/post-view":
            self.api_post_view(parse_qs(u.query).get("post", [""])[0])
        elif u.path == "/api/asset":
            self.api_asset(parse_qs(u.query).get("name", [""])[0])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/researcher":
                rid = new_run("researcher", "")
                threading.Thread(target=run_run_thread, args=(rid, "researcher", ""), daemon=True).start()
                self._json({"run": rid})
            elif u.path == "/api/publish-card":
                self.api_publish_card()
            elif u.path == "/api/producer":
                topic = (self._post_body().get("topic") or "").strip()
                if not topic:
                    self._json({"error": "укажи тему поста"}, 400)
                    return
                rid = new_run("producer", topic)
                threading.Thread(target=run_run_thread, args=(rid, "producer", topic), daemon=True).start()
                self._json({"run": rid})
            elif u.path == "/api/vk-login":
                rid = new_run("vk-login", "вход ВК для сохранённой сессии")
                threading.Thread(target=run_vk_login, args=(rid,), daemon=True).start()
                self._json({"run": rid})
            elif u.path == "/api/site-deploy":
                rid = new_run("site-deploy", "ручной деплой по кнопке")
                threading.Thread(target=run_site_deploy, args=(rid,), daemon=True).start()
                self._json({"run": rid})
            elif u.path == "/api/queue":
                self.api_queue_add()
            elif u.path == "/api/queue/confirm":
                self.api_queue_confirm()
            elif u.path == "/api/queue/action":
                self.api_queue_action()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---------------- API

    def api_state(self):
        with db() as c:
            runs = [dict(r) for r in c.execute(
                "SELECT id, kind, params, status, started, finished, exit_code FROM runs ORDER BY id DESC LIMIT 15")]
            queue = [dict(r) for r in c.execute("SELECT * FROM queue ORDER BY run_at DESC LIMIT 50")]
        for r in queue:
            info = post_card_info(r["post"])
            r["title"], r["city"] = info["title"], info["city"]
        pub = {"busy": pub_lock.locked()}
        self._json({"now": now_str(), "runs": runs, "queue": queue, "publisher": pub,
                    "published": published_list(), "cards": cards_list(),
                    "progress": {k: v for k, v in PROGRESS.items()}})

    def api_posts(self):
        items = []
        for f in sorted((PROJECT / "posts").glob("*.json"), reverse=True):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            vk_len = len(p.get("platforms", {}).get("vk", {}).get("content") or "")
            tg_len = len(p.get("platforms", {}).get("telegram", {}).get("content") or "")
            photos = p.get("photos") or []
            folder = PROJECT / "assets" / f.stem
            items.append({
                "file": f"posts/{f.name}", "name": f.stem, "rubric": p.get("rubric", ""),
                "vk_len": vk_len, "tg_len": tg_len,
                "photos": len(photos) + (1 if not photos and folder.is_dir() else 0),
                "has_tg_caption": 0 < tg_len <= 1024,
            })
        self._json({"posts": items})

    def api_log(self, run):
        f = RUNS / f"{run}.log"
        if not f.is_file():
            self._json({"log": "лог ещё пуст"})
            return
        text = f.read_text(encoding="utf-8", errors="replace")
        self._json({"log": text[-16000:]})

    IMG_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".gif": "image/gif"}

    def api_post_view(self, post):
        """«Проверить»: тексты и картинки сформированного поста."""
        if not str(post).replace("\\", "/").startswith("posts/"):
            self._json({"error": "пост не найден"}, 400)
            return
        f = PROJECT / post
        if not f.is_file():
            self._json({"error": "пост не найден"}, 400)
            return
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            self._json({"error": f"пост не читается: {e}"}, 400)
            return
        plats = p.get("platforms", {})
        vk = str((plats.get("vk") or {}).get("content") or "")
        tg = str((plats.get("telegram") or {}).get("content") or "")
        stem = f.stem
        # картинки: папка assets/<пост>, потом photos[] (с подписями), потом gen-варианты в assets
        files = []
        def add(fn, what="", credit=""):
            if fn and fn.replace("\\", "/") not in [x["file"] for x in files]:
                files.append({"file": fn.replace("\\", "/"), "what": what, "credit": credit})
        d = PROJECT / "assets" / stem
        if d.is_dir():
            for im in sorted(d.iterdir()):
                if im.suffix.lower() in self.IMG_TYPES:
                    add("assets/" + stem + "/" + im.name)
        for ph in p.get("photos") or []:
            fn = ph.get("file")
            if fn and (PROJECT / str(fn).replace("\\", "/")).is_file():
                add(fn, ph.get("what") or "", ph.get("credit") or "")
        for im in (PROJECT / "assets").glob(f"{stem}-*"):
            if im.suffix.lower() in self.IMG_TYPES:
                add("assets/" + im.name)
        info = post_card_info(post)
        self._json({"post": post, "name": info["name"], "city": info["city"],
                    "title": info["title"], "rubric": p.get("rubric") or "",
                    "vk": vk, "tg": tg, "images": files})

    def api_asset(self, name):
        """Картинки для «Проверить»: /api/asset?name=assets/... (только внутри проекта)."""
        p = (PROJECT / str(name).replace("\\", "/")).resolve()
        try:
            p.relative_to(PROJECT.resolve())
        except ValueError:
            self._json({"error": "путь вне проекта"}, 404)
            return
        if not p.is_file() or p.suffix.lower() not in self.IMG_TYPES:
            self._json({"error": "файл не найден"}, 404)
            return
        body = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", self.IMG_TYPES[p.suffix.lower()])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_queue_add(self):
        b = self._post_body()
        post, run_at, platforms = b.get("post"), b.get("run_at", ""), b.get("platforms", [])
        platforms = [p for p in platforms if p in PUBLISH_SCRIPTS]
        if not post or not (PROJECT / post).is_file():
            self._json({"error": "пост не найден"}, 400)
            return
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", run_at):
            self._json({"error": "укажи дату и время"}, 400)
            return
        if not platforms:
            self._json({"error": "выбери хотя бы одну площадку"}, 400)
            return
        run_at_norm = run_at[:16].replace("T", " ")
        site_update = 1 if b.get("site_update") else 0
        with db() as c:
            c.execute("INSERT INTO queue(post, run_at, platforms, status, detail, links, attempts, "
                      "created, site_update) VALUES (?,?,?,?,?,?,0,?,?)",
                      (post, run_at_norm, json.dumps(platforms), "pending", "ждёт времени",
                       json.dumps({}), now_str(), site_update))
        self._json({"ok": True})

    def api_queue_action(self):
        b = self._post_body()
        qid, action = b.get("id"), b.get("action")
        with db() as c:
            row = c.execute("SELECT id, status, run_at FROM queue WHERE id=?", (qid,)).fetchone()
            if not row:
                self._json({"error": "задача не найдена"}, 404)
                return
            if action == "defer" and row["status"] in ("draft", "pending"):
                # отложить: уходит в блок «Отложенные», планировщик её не трогает;
                # пост и картинки остаются — заново формировать не нужно
                c.execute("UPDATE queue SET status='deferred', detail='отложено владельцем' "
                          "WHERE id=?", (qid,))
            elif action == "resume" and row["status"] == "deferred":
                # вернуть в очередь как «сформирован» (снова редактируемый);
                # если время уже прошло — переносим на завтра 18:00, чтобы не улетело сразу
                new_at = row["run_at"] or ""
                if new_at <= now_str()[:16]:
                    new_at = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") + " 18:00"
                c.execute("UPDATE queue SET status='draft', run_at=?, "
                          "detail='возвращено из отложенных', last_log=NULL WHERE id=?",
                          (new_at, qid))
            elif action == "cancel" and row["status"] in ("draft", "pending"):
                c.execute("UPDATE queue SET status='cancelled', detail='отменено владельцем' "
                          "WHERE id=?", (qid,))
            elif action == "retry" and row["status"] in ("failed", "cancelled"):
                c.execute("UPDATE queue SET status='pending', detail='ждёт времени', last_log=NULL "
                          "WHERE id=?", (qid,))
            else:
                self._json({"error": "такое действие для этого статуса недоступно"}, 400)
                return
        self._json({"ok": True})

    def api_queue_confirm(self):
        """«Опубликовать» у сформированного поста: параметры закреплены, задача активна."""
        b = self._post_body()
        qid, run_at, platforms = b.get("id"), str(b.get("run_at", "")), b.get("platforms", [])
        platforms = [p for p in platforms if p in PUBLISH_SCRIPTS]
        site_update = 1 if b.get("site_update") else 0
        with db() as c:
            row = c.execute("SELECT id, status FROM queue WHERE id=?", (qid,)).fetchone()
            if not row or row["status"] != "draft":
                self._json({"error": "пост не найден или уже подтверждён"}, 400)
                return
            if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", run_at):
                self._json({"error": "выбери дату и время публикации"}, 400)
                return
            if not platforms:
                self._json({"error": "выбери хотя бы одну площадку (ТГ или ВК)"}, 400)
                return
            c.execute("UPDATE queue SET run_at=?, platforms=?, site_update=?, status='pending', "
                      "detail='ждёт времени' WHERE id=?", (run_at, json.dumps(platforms),
                                                            site_update, qid))
        self._json({"ok": True})

    def api_publish_card(self):
        """«Сделать пост» у карточки: продюсер пишет пост; дата/время выберутся в очереди."""
        b = self._post_body()
        cfile = b.get("file")
        if not cfile or not (PROJECT / cfile).is_file():
            self._json({"error": "карточка не найдена"}, 400)
            return
        if not str(cfile).replace("\\", "/").startswith("research/fabriki/"):
            self._json({"error": "это не карточка фабрики"}, 400)
            return
        # тема = имя карточки (короткое), как в post_title
        try:
            card = json.loads((PROJECT / cfile).read_text(encoding="utf-8"))
        except Exception:
            card = {}
        topic = str(card.get("name") or Path(cfile).stem)
        rid = new_run("producer", topic)
        # дефолт: сегодня 18:00 — точные дата/время и площадки задаются в очереди
        run_at = now_str()[:10] + " 18:00"
        with db() as c:
            c.execute("UPDATE runs SET meta=? WHERE id=?",
                      (json.dumps({"card_file": cfile, "run_at": run_at,
                                   "platforms": ["vk", "tg"]}, ensure_ascii=False), rid))
        threading.Thread(target=run_run_thread, args=(rid, "producer", topic,
                       {"card_file": cfile, "run_at": run_at, "platforms": ["vk", "tg"]}),
                       daemon=True).start()
        self._json({"run": rid})


def run_vk_login(run_id: int) -> None:
    """Кнопка «ВК-логин»: открывает окно для входа и сохраняет сессию."""
    cmd = [sys.executable, str(PUBLISH_SCRIPTS["vk"]), "--login"]
    p = subprocess.run(cmd, cwd=str(PROJECT), capture_output=True, timeout=400, env=subprocess_env())
    out = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", errors="replace")[-4000:]
    (RUNS / f"{run_id}.log").write_text(out, encoding="utf-8")
    finish_run(run_id, p.returncode)


def main():
    init_db()
    sweep_interrupted()
    threading.Thread(target=publish_due_worker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Панель NYTreeToys: http://127.0.0.1:{PORT}  (Ctrl+C — остановить)")
    srv.serve_forever()


if __name__ == "__main__":
    main()