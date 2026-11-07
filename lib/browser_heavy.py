"""browser_heavy.py — отдельный Chrome для тяжёлых маркетплейс-страниц.

Зачем: страницы WB/Ozon периодически вешают renderer, а с ним browser-level
CDP-эндпоинт — все playwright-клиенты отваливаются. Основной debug-Chrome
(9222) держит ценные сессии (Google, Kwork, Standoff), его рестартовать
нельзя. Этот инстанс (порт 9223, профиль .chrome_heavy) — расходник:
при зависании его можно убивать и поднимать заново без потерь.

  from browser_heavy import ensure_heavy, kill_heavy, connect_heavy_page
"""
import json
import os
import re
import subprocess
import time
import urllib.request

HEAVY_PORT = 9223
BASE = os.path.dirname(os.path.abspath(__file__))
HEAVY_PROFILE = os.path.join(BASE, ".chrome_heavy")
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def heavy_port_up(timeout=3):
    try:
        urllib.request.urlopen(
            f"http://localhost:{HEAVY_PORT}/json", timeout=timeout)
        return True
    except Exception:
        return False


def ensure_heavy(url=None, wait_sec=15):
    """Поднять heavy-Chrome если ещё не запущен."""
    if heavy_port_up():
        return None
    os.makedirs(HEAVY_PROFILE, exist_ok=True)
    args = [
        CHROME_EXE,
        f"--remote-debugging-port={HEAVY_PORT}",
        f"--user-data-dir={HEAVY_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--mute-audio",
        # невидимое окно: свёрнутое и за экраном — headed-режим сохраняется
        # (Ozon/WB антибот лояльнее к headed), но окно не мешает пользователю
        "--start-minimized",
        "--window-position=-32000,-32000",
        "--window-size=1280,800",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
    ]
    if url:
        args.append(url)
    proc = subprocess.Popen(args)
    for _ in range(wait_sec):
        if heavy_port_up():
            return proc
        time.sleep(1)
    try:
        proc.terminate()
    except Exception:
        pass
    return None


def kill_heavy():
    """Убить все процессы heavy-Chrome (по user-data-dir в cmdline)."""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='chrome.exe'",
             "get", "processid,commandline"],
            capture_output=True, text=True).stdout
        for line in out.splitlines():
            if ".chrome_heavy" in line:
                m = re.search(r"(\d+)\s*$", line.strip())
                if m:
                    subprocess.run(["taskkill", "//PID", m.group(1),
                                    "//F"], capture_output=True)
    except Exception:
        pass


def restart_heavy():
    kill_heavy()
    time.sleep(2)
    ensure_heavy()


def cleanup_heavy_pages(keep_blank=True):
    """Закрыть все page-таргеты маркетплейсов в heavy-Chrome.

    Зависшие вкладки WB/Ozon копятся и вешают весь браузер —
    connect_over_cdp начинает отваливаться. Вызывать перед открытием
    новой рабочей вкладки: расходный инстанс, жертв не будет.
    """
    try:
        ts = json.loads(urllib.request.urlopen(
            f"http://localhost:{HEAVY_PORT}/json", timeout=5).read())
        for t in ts:
            if t.get("type") != "page":
                continue
            url = t.get("url", "")
            if ("ozon.ru" in url or "wildberries.ru" in url
                    or "wb.ru" in url or url == "about:blank"):
                try:
                    urllib.request.urlopen(
                        f"http://localhost:{HEAVY_PORT}/json/close/{t['id']}",
                        timeout=5).read()
                except Exception:
                    pass
    except Exception:
        pass


def connect_heavy_page(p):
    """Playwright page в heavy-Chrome (новая вкладка).

    Перед созданием вкладки чистит зависшие page-таргеты маркетплейсов —
    иначе мёртвые вкладки копятся и вешают CDP-рукопожатие.
    """
    cleanup_heavy_pages()
    browser = p.chromium.connect_over_cdp(
        f"http://localhost:{HEAVY_PORT}", timeout=30000)
    return browser.contexts[0].new_page()
