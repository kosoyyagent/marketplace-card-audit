"""ozon.py — сбор данных по товару Ozon.

Через debug-Chrome (Playwright): открывает карточку, вызывает composer API
в контексте страницы (прямой запрос снаружи блокируется антиботом),
достаёт цену/название/наличие из widgetStates.
"""
import json
import os
import re

DEBUG_PORT = "http://localhost:9222"


def dbglog(msg):
    try:
        with open(__file__.rsplit("\\", 1)[0] + "\\ozon_debug.log", "a",
                  encoding="utf-8") as f:
            import datetime
            f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")
    except Exception:
        pass


def _toint(s):
    if not s:
        return None
    d = re.sub(r"[^\d]", "", str(s))
    return int(d) if d else None


def sku_from_url(url):
    """SKU — последнее число в пути товара."""
    m = re.findall(r"(\d{5,})", url)
    return m[-1] if m else None


def _product_url(sku_or_url):
    if re.match(r"^\d+$", str(sku_or_url).strip()):
        return f"https://www.ozon.ru/product/x-{sku_or_url}/"
    return str(sku_or_url).split("?")[0]


def _fetch_page_json(page, path):
    return page.evaluate("""async (path) => {
      const r = await fetch('/api/composer-api.bx/page/json/v2?url=' + path,
                            {credentials: 'include'});
      if (!r.ok) return {__err: r.status};
      return await r.json();
    }""", path)


def _open(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        # Ozon часто не доходит до domcontentloaded, но origin уже
        # прогружен — composer fetch работает. Не на ozon.ru — бросаем.
        if "ozon.ru" not in (page.url or ""):
            raise
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def _parse_states(data):
    ws = data.get("widgetStates") or {}
    out = {}
    for key, raw in ws.items():
        try:
            v = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if key.startswith("webPrice-"):
            out["price"] = _toint(v.get("price"))
            out["card_price"] = _toint(v.get("cardPrice"))
            out["old_price"] = _toint(v.get("originalPrice"))
            out["in_stock"] = bool(v.get("isAvailable"))
        elif key.startswith("webProductHeading-"):
            out["name"] = v.get("title")
        elif key.startswith("webStickyProducts-"):
            out.setdefault("name", v.get("name"))
            seller = v.get("seller") or {}
            if isinstance(seller, dict):
                out["seller"] = seller.get("name") or seller.get("title")
        elif key.startswith("webAddToCart-") and "in_stock" not in out:
            btn = (v.get("firstButton") or {})
            out["in_stock"] = bool(btn.get("toCart"))
    return out


def snapshot(sku_or_url, page=None):
    """Полный снимок товара Ozon: name/price/card_price/old_price/in_stock/seller."""
    close = False
    if page is None:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from playwright.sync_api import sync_playwright  # noqa
        from browser_heavy import ensure_heavy, connect_heavy_page  # noqa
        ensure_heavy()
        pw = sync_playwright().start()
        page = connect_heavy_page(pw)
        close = True
    try:
        url = _product_url(sku_or_url)
        _open(page, url)
        if "/product/" not in page.url:
            dbglog(f"redirect away: {page.url}")
            return None
        data = _fetch_page_json(page, page.url.split("ozon.ru")[-1].split("?")[0])
        if not isinstance(data, dict) or data.get("__err"):
            dbglog(f"composer err {data.get('__err') if isinstance(data,dict) else '?'}")
            return None
        snap = _parse_states(data)
        snap["nm"] = sku_from_url(page.url)
        return snap if snap.get("price") or snap.get("name") else None
    except Exception as e:
        dbglog(f"snapshot err {sku_or_url}: {e!r}")
        # мёртвый браузер/вкладка — пробрасываем наверх, чтобы воркер
        # перезапустил heavy-Chrome; контентные сбои остаются None
        if ("TargetClosed" in type(e).__name__
                or "Target page" in str(e)
                or "has been closed" in str(e)
                or "Connection" in str(e)[:40]):
            raise
        return None
    finally:
        if close:
            try:
                page.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    arg = sys.argv[1] if len(sys.argv) > 1 else "3371018537"
    print(json.dumps(snapshot(arg), ensure_ascii=False, indent=1))
