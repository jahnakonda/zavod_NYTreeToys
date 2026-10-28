# -*- coding: utf-8 -*-
"""Публикация поста NYTreeToys в группу ВК vk.ru/club242169556 через UI-автоматизацию.

    python panel/publish_vk.py --post posts/2026-10-28-kolomeev-post.json   # опубликовать
    python panel/publish_vk.py --login                                      # сохранить сессию

Регламент — блок «Публикация в VK» скилла NYTreeToys-content (API-пути у VK закрыты,
штатный путь — UI). Сессия владельца живёт в профиле panel/vk-profile — один раз
логинятся (--login), дальше панель публикует сама.

Коды выхода: 0 — опубликовано; 2 — не залогинен (нужен --login); 1 — прочая ошибка.
Скриншот при ошибке кладётся в panel/runs/.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

try:  # stdout в UTF-8 (панель читает вывод как UTF-8)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PANEL_DIR = Path(__file__).resolve().parent
PROJECT = PANEL_DIR.parent
PROFILE = PANEL_DIR / "vk-profile"
RUNS = PANEL_DIR / "runs"
GROUP_URL = "https://vk.ru/club242169556"
CREATE = 'group_publish_create_button'
POST_ITEM = 'group_publish_post_menu_item'
MSG_INPUT = 'posting_base_screen_input_message'
NEXT_BTN = 'posting_base_screen_next'
STORY_SWITCH = 'posting_settings_repost_to_story_switch'
SUBMIT = 'posting_submit_button'
DEVICE_BTN = 'posting_base_screen_download_from_device'
CLOSE_BTN = 'modal-close-button'
ATTACH = '[data-testid^="posting_attachment"]'
PHOTO_REMOVE = 'posting_attachment_photo_item_remove'


def shot(page, tag: str) -> str:
    RUNS.mkdir(exist_ok=True)
    p = RUNS / f"vk-{tag}-{datetime.now().strftime('%H%M%S')}.png"
    try:
        page.screenshot(path=str(p), full_page=False)
    except Exception:
        pass
    return str(p)


def new_links(page) -> set:
    return set(page.eval_on_selector_all(
        'a[href*="/wall-242169556_"]', "els => els.map(e => e.getAttribute('href'))"))


def launch(pw):
    """Открыть Edge с профилем vk-profile.

    Профиль один на всех (публикатор, ВК-логин, парсеры агентов): если занят —
    Edge отвечает «Opening in existing browser session» и выходит, а Playwright
    остаётся с битой страницей. Ждём и пробуем снова до ~2 мин.
    """
    last = None
    for attempt in range(13):
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE), channel="msedge", headless=False,
                viewport={"width": 1280, "height": 900}, locale="ru-RU")
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.evaluate("1+1")   # проверка: CDP жив (иначе профиль занят чужой сессией)
            return ctx, page
        except Exception as e:
            last = e
            try:
                ctx.close()
            except Exception:
                pass
            print(f"WAIT: профиль vk-profile занят, попытка {attempt + 1}/13 — жду 10 сек")
            time.sleep(10)
    raise RuntimeError(f"не удалось открыть Edge с профилем ВК за 2 мин (профиль занят?): {last}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--dry", action="store_true",
                    help="прогнать весь цикл до кнопки «Опубликовать» — не публикуя")
    args = ap.parse_args()

    with sync_playwright() as pw:
        ctx, page = launch(pw)
        try:
            if args.login:
                mode_login(page)
            else:
                mode_publish(page, Path(PROJECT / args.post), dry=args.dry)
        except Exception as e:
            # необработанные ошибки (таймауты UI и пр.) тоже снимаем на экран
            print(f"FAIL: {e.__class__.__name__}: {str(e)[:400]}")
            last_shot = shot(page, "fail")
            print(f"Скриншот: {last_shot}")
            sys.exit(1)
        finally:
            page.context.close()


def mode_login(page) -> None:
    """Открывает группу, ждёт входа владельца до 5 минут, сохраняет сессию в профиль."""
    page.goto(GROUP_URL)
    if not find_logged(page):
        print("LOGIN_WAIT: войди вручную в открывшемся окне (vk.ru) — жду до 5 минут…")
        for i in range(60):
            time.sleep(5)
            try:
                if find_logged(page):
                    break
                # после входа vk.ru кидает на ленту — раз в минуту возвращаемся к группе
                if i % 12 == 11:
                    page.goto(GROUP_URL)
                find_logged(page)
            except Exception:
                pass
        else:
            shot(page, "login-timeout")
            print("LOGIN_FAIL: за 5 минут вход не случился")
            sys.exit(2)
    print("LOGIN_OK: сессия сохранена в panel/vk-profile")


def find_logged(page) -> bool:
    try:
        return page.locator(f'[data-testid="{CREATE}"]').count() > 0
    except Exception:
        return False


def open_composer(page) -> None:
    """Открыть компостер поста меню «Создать → Пост» и дождаться поля ввода."""
    page.locator(f'[data-testid="{CREATE}"]').click()
    page.locator(f'[data-testid="{POST_ITEM}"]').click(timeout=15000)
    inp = page.locator(f'[data-testid="{MSG_INPUT}"]')
    inp.wait_for(state="visible", timeout=15000)
    page.wait_for_timeout(800)


def close_composer_discard(page) -> None:
    """Закрыть компостер БЕЗ сохранения: крест → ответ «Выйти без сохранения»
    на возможный вопрос «Сохранить черновик?» (появляется, если есть контент)."""
    try:
        page.locator(f'[data-testid="{CLOSE_BTN}"]').first.click(timeout=5000)
        page.wait_for_timeout(1000)
    except Exception:
        pass
    # вопрос о сохранении — отказываемся
    try:
        page.get_by_text("Выйти без сохранения", exact=True).first.click(timeout=4000)
        page.wait_for_timeout(1000)
    except Exception:
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
    # редактор мог не закрыться — дожимаем
    try:
        page.locator(f'[data-testid="{MSG_INPUT}"]').wait_for(state="hidden", timeout=5000)
    except Exception:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)


def clear_stuck_draft(page) -> None:
    """Сбросить прилипший черновик компостера: ВК хранит недоопубликованный пост
    (фото прошлой попытки, карточки-сниппеты ссылок) между открытиями — в таком
    виде редактор показывает другой UI и локаторы ломаются. Закрытие крестом
    (без сохранения) + переоткрытие даёт чистый компостер (проверено пробой)."""
    try:
        stuck = page.eval_on_selector_all(ATTACH, "els => els.length")
    except Exception:
        stuck = 0
    for attempt in range(3):
        if stuck <= 0:
            return
        print(f"CLEANUP: прилипший черновик ({stuck} вложений), сбрасываю — попытка {attempt + 1}/3")
        try:
            page.locator(f'[data-testid="{PHOTO_REMOVE}"]').first.click(timeout=3000)
            page.wait_for_timeout(500)
        except Exception:
            pass
        close_composer_discard(page)
        open_composer(page)
        try:
            stuck = page.eval_on_selector_all(ATTACH, "els => els.length")
        except Exception:
            stuck = 0
    if stuck > 0:
        print(f"WARN: черновик не сбросился ({stuck}) — пробую продолжить как есть")


def mode_publish(page, post_path: Path, dry: bool = False) -> None:
    post = json.loads(post_path.read_text(encoding="utf-8"))
    name = post_path.stem
    text = post.get("platforms", {}).get("vk", {}).get("content") or ""
    if not text.strip():
        print("PREPARE_FAIL: в посте нет platforms.vk.content")
        sys.exit(3)

    images = resolve_vk_images(post, name)
    if not images:
        print("PREPARE_FAIL: картинки не найдены (ни -vk-вариантов, ни photos[0].file)")
        sys.exit(3)
    print(f"images: {', '.join(p.name for p in images)}")

    page.goto(GROUP_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if not find_logged(page):
        print("AUTH_FAIL: сессия ВК не жива — запусти python panel/publish_vk.py --login")
        shot(page, "not-logged")
        sys.exit(2)

    open_composer(page)
    clear_stuck_draft(page)

    before = new_links(page)

    inp = page.locator(f'[data-testid="{MSG_INPUT}"]')
    inp.fill(text)  # \n превращаются в корректные абзацы (проверено ранее)
    page.wait_for_timeout(800)

    # Загрузка фото. Вариантов компостера минимум два (VK A/B + вид от содержимого
    # черновика): 1) дропзона — кнопка устройства видна сразу; 2) компакт — она за
    # «Ещё» (add_more_attachments). Клик может открыть нативный диалог выбора файлов
    # (окно Проводника, блокирует страницу) — перехватываем штатно
    # через expect_file_chooser. Фолбэк — скрытый input, НО только внутри модалки
    # компостера: вне её input принадлежит альбому группы и заливает фото в альбом.
    uploaded = False
    for attempt in range(2):
        try:
            dev = page.locator(f'[data-testid="{DEVICE_BTN}"]')
            if not dev.count():
                more = page.locator('[data-testid="posting_base_screen_add_more_attachments"]')
                if more.count():
                    more.first.click(timeout=15000)
                    page.wait_for_timeout(900)
                dev = page.locator(f'[data-testid="{DEVICE_BTN}"]')
            if not dev.count():
                dev = page.get_by_text("Загрузить с устройства", exact=True)
            with page.expect_file_chooser(timeout=10000) as fc_info:
                dev.first.click(timeout=15000)
            fc_info.value.set_files([str(p) for p in images])
            uploaded = True
            break
        except Exception as e:
            print(f"WARN: chooser не перехвачен ({e.__class__.__name__}), попытка {attempt + 1}/2")
            if page.url.rstrip("/") != GROUP_URL.rstrip("/"):
                # клик увёл со страницы (например, «Добавление фотографий» альбома) —
                # назад, открываем компостер заново
                page.goto(GROUP_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                open_composer(page)
            page.wait_for_timeout(1200)
    if not uploaded:
        page.wait_for_selector(f'[data-testid="posting_modal_box"]', state="visible", timeout=10000)
        page.wait_for_selector('[data-testid="posting_modal_box"] input[type="file"]',
                               state="attached", timeout=15000)
        page.set_input_files('[data-testid="posting_modal_box"] input[type="file"]',
                             [str(p) for p in images])
    # Ждём появления превью (кнопки «Обрезать»/«Удалить») — до 30 сек на загрузку
    page.wait_for_selector('text="Удалить"', state="visible", timeout=30000)
    page.wait_for_timeout(1500)

    page.locator(f'[data-testid="{NEXT_BTN}"]').click(timeout=15000)
    page.wait_for_timeout(1500)

    # Тумблер «Опубликовать в истории» по умолчанию включён — выключаем (клик по самому свитчу)
    try:
        sw = page.locator(f'[data-testid="{STORY_SWITCH}"]')
        if sw.count() > 0 and sw.get_attribute("aria-checked") == "true":
            page.evaluate(f'document.querySelector(\'[data-testid="{STORY_SWITCH}"]\').click()')
            page.wait_for_timeout(400)
    except Exception as e:
        print(f"WARN: тумблер историй не проверился ({e})")

    if dry:
        # ДРЫ-режим: компостер с вложениями закрыть крестом, чтобы не прилипал
        print("DRY_OK: весь цикл до «Опубликовать» прошёл — публикация не выполнена")
        close_composer_discard(page)
        return

    page.locator(f'[data-testid="{SUBMIT}"]').click(timeout=15000)
    page.wait_for_selector(f'[data-testid="{SUBMIT}"]', state="hidden", timeout=60000)
    page.wait_for_timeout(4000)

    # Ищем новый пост на стене: ссылки до/после, берём максимальный номер
    page.goto(GROUP_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    created = [l for l in (new_links(page) - before)]
    if not created:
        shot(page, "no-link")
        print("VERIFY_FAIL: опубликовано, но новый /wall-242169556_N не найден на стене — проверь вручную")
        sys.exit(1)
    def wall_id(href: str) -> int:
        m = re.search(r"_(\d+)$", href)
        return int(m.group(1)) if m else 0
    href = max(created, key=wall_id)
    print(f"PUBLISH_OK: https://vk.ru{href} (ссылки: {', '.join(sorted(created))})")


def resolve_vk_images(post: dict, name: str) -> list:
    out = []
    folder = PROJECT / "assets" / name
    if folder.is_dir():
        def num_of(p: Path) -> int:
            stem = p.stem
            m = re.search(r"-vk-(\d+)$|-(\d+)-vk$", stem)
            if m:
                return int(m.group(1) or m.group(2))
            return 1 if stem.endswith("-vk") else -1
        out = sorted(
            [p for p in folder.iterdir()
             if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
             and p.name.startswith(name) and num_of(p) >= 0],
            key=num_of)
    if not out:
        # все фото из поля photos (продюсер берёт оригиналы с сайта — без -vk-вариантов)
        for ph in post.get("photos") or []:
            f = PROJECT / ph["file"] if ph.get("file") else None
            if f and f.is_file():
                out.append(f)
    if not out:
        # фолбэк: сама папка поста (продюсер взял оригиналы, но не сделал -vk-варианты)
        if folder.is_dir():
            out = sorted([p for p in folder.iterdir()
                          if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
                         key=lambda p: p.name)
    if not out:
        # фолбэк для постов с ген-картинками: assets/<пост>-<N>.png (в корне assets)
        gens = sorted((PROJECT / "assets").glob(f"{name}-*.png")) + \
               sorted((PROJECT / "assets").glob(f"{name}-*.jpg"))
        out = gens
    return [p for p in out if p.is_file()]


if __name__ == "__main__":
    main()