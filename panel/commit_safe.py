# -*- coding: utf-8 -*-
"""Коммит с блокировкой: сериализует коммиты параллельных агентов панели.

Несколько headless-агентов могут финишировать одновременно, и их прямые
`git add` + `git commit` сталкиваются на .git/index.lock (коммит не долетает).
Эта обёртка удерживает файловый замок (panel/commit.lock) на всё время
add + commit; если замок занят другим агентом — ждёт до 3 минут. Замок
осаждается системной блокировкой файла (msvcrt.locking), поэтому зависшим
не бывает: если процесс агента умер, ОС снимает замок сама.

Использование (агенты вызывают из своего каталога проекта):
    python panel/commit-safe.py -m "сообщение" <пути...>   # add путей + commit
    python panel/commit-safe.py -m "сообщение"             # add -A + commit

Коды выхода: 0 — закоммичено (или «нечего коммитить»); 1 — не дождался
замка либо git упал по другой причине.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

if sys.platform == "win32":
    import msvcrt

LOCK = Path(__file__).resolve().parent / "commit.lock"
WAIT_SEC = 180          # сколько ждать освобождения замка
RETRIES = 3             # повторов, если git упал на index.lock под замком


def acquire(timeout: int) -> bool:
    """Захватить замок, с интервалами ожидая освобождения. False — не дождались."""
    fh = LOCK.open("a+b")
    deadline = time.monotonic() + timeout
    while True:
        try:
            if sys.platform == "win32":
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # POSIX (на всякий случай): advisory lock через fcntl
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.seek(0)
            fh.truncate()
            fh.write(str(time.time()).encode())
            fh.flush()
            fh.seek(0)
            globals()["_LOCK_FH"] = fh   # держим хэндл открытым до release()
            return True
        except OSError:
            if time.monotonic() >= deadline:
                fh.close()
                return False
            time.sleep(2)


def release() -> None:
    fh = globals().get("_LOCK_FH")
    if fh is None:
        return
    try:
        if sys.platform == "win32":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        fh.close()
        globals()["_LOCK_FH"] = None


def main() -> int:
    ap = argparse.ArgumentParser(description="git add + commit внутри блокировки")
    ap.add_argument("-m", "--message", required=True)
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args()

    if not acquire(WAIT_SEC):
        print(f"COMMIT_SAFE_FAIL: замок занят дольше {WAIT_SEC} с, коммит не выполнен")
        return 1
    try:
        for attempt in range(1, RETRIES + 1):
            add = subprocess.run(["git", "add", *(args.paths or ["-A"])])
            if add.returncode != 0:
                print(f"COMMIT_SAFE_FAIL: git add вернул {add.returncode}")
                return 1
            done = subprocess.run(["git", "commit", "-m", args.message],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace")
            out = (done.stdout or "") + (done.stderr or "")
            if done.returncode == 0:
                print("COMMIT_SAFE_OK")
                return 0
            # «нечего коммитить» и «не в git-репозитории» — не ошибки блокировки
            if "nothing to commit" in out:
                print("COMMIT_SAFE_OK: нечего коммитить")
                return 0
            if "not a git repository" in out:
                print("COMMIT_SAFE_FAIL: каталог не в git-репозитории")
                return 1
            if "index.lock" in out or attempt < RETRIES:
                print(f"COMMIT_SAFE: retry {attempt}/{RETRIES} (git вернул {done.returncode})")
                time.sleep(5)
                continue
            print("COMMIT_SAFE_FAIL: " + out.strip()[-500:])
            return 1
    finally:
        release()
    return 1


if __name__ == "__main__":
    sys.exit(main())