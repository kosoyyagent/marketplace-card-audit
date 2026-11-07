"""wb.py — сбор данных по артикулу Wildberries.

Название/продавец — basket CDN (HTTP, без браузера).
Остаток — product-order-qnt (HTTP).
Цена — карточка WB через debug-Chrome (Playwright), если доступен.
"""
import json
import os
import re
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def dbglog(msg):
    try:
        with open(__file__.rsplit("\\", 1)[0] + "\\wb_debug.log", "a",
                  encoding="utf-8") as f:
            import datetime
            f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")
    except Exception:
        pass


def _basket_num(vol):
    for top, n in [(143, 1), (287, 2), (431, 3), (719, 4), (1007, 5),
                   (1061, 6), (1115, 7), (1169, 8), (1313, 9), (1601, 10),
                   (1655, 11), (1919, 12), (2045, 13), (2337, 14),
                   (2387, 15), (2745, 16), (2819, 17), (2939, 18),
                   (3059, 19), (3179, 20), (3299, 21), (3419, 22)]:
        if vol <= top:
            return f"{n:02d}"
    return "23"


def card_info(nm):
    """Имя товара и продавец — по basket CDN."""
    nm = int(nm)
    vol, part = nm // 100000, nm // 1000
    b = _basket_num(vol)
    out = {"nm": nm, "name": None, "brand": None, "seller": None}
    base = f"https://basket-{b}.wbbasket.ru/vol{vol}/part{part}/{nm}/info"
    try:
        d = requests.get(f"{base}/ru/card.json", headers=UA, timeout=15).json()
        out["name"] = d.get("imt_name")
        out["brand"] = d.get("selling", {}).get("brand_name") or d.get("brand")
    except Exception:
        pass
    try:
        d = requests.get(f"{base}/sellers.json", headers=UA, timeout=15).json()
        out["seller"] = d.get("supplierName")
    except Exception:
        pass
    return out


def stock(nm):
    """Суммарный остаток по SKU (по всем складам)."""
    try:
        r = requests.get(
            f"https://product-order-qnt.wildberries.ru/v2/by-nm/?nm={int(nm)}",
            headers=UA, timeout=15)
        arr = r.json()
        return sum(x.get("qnt", 0) for x in arr) if arr else 0
    except Exception:
        return None


def price_browser(nm, page=None):
    """Цена с карточки WB через открытый debug-Chrome.

    Возвращает dict(price, wallet_price, old_price) или None.
    """
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
        page.goto(f"https://www.wildberries.ru/catalog/{int(nm)}/detail.aspx",
                  wait_until="domcontentloaded")
        # антибот «Проверяем браузер» — в реальном Chrome проходит сама
        for _ in range(3):
            try:
                body = page.evaluate(
                    "() => (document.body.innerText || '').slice(0, 200)")
            except Exception:
                break
            if "Проверяем браузер" not in body:
                break
            page.wait_for_timeout(4000)
            page.reload(wait_until="domcontentloaded")
        try:
            page.wait_for_selector("ins", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        res = page.evaluate("""() => {
          const ins = [...document.querySelectorAll('ins')]
            .map(e => e.innerText.trim()).filter(t => /\\d/.test(t));
          const dels = [...document.querySelectorAll('del')]
            .map(e => e.innerText.trim()).filter(t => /\\d/.test(t));
          const m = document.body.innerText.match(/([\\d\\s\\xa0]{2,15})₽/g) || [];
          const btns = [...document.querySelectorAll('button')]
            .map(e=>e.innerText.trim());
          const sizes = [...document.querySelectorAll(
            '.sizes-list__item, [class*=sizesList] li, [class*=size] button')]
            .length;
          return {ins: ins.slice(0, 6), dels: dels.slice(0, 6),
                  any: m.slice(0, 8), sizes,
                  noStock: /нет в наличии|закончился/i.test(document.body.innerText),
                  buyBtn: btns.some(t=>/в корзину|купить/i.test(t))};
        }""")
        def toint(s):
            d = re.sub(r"[^\d]", "", s)
            return int(d) if d else None
        ins = [toint(x) for x in res["ins"] if toint(x)]
        dels = [toint(x) for x in res["dels"] if toint(x)]
        if not ins:
            anyp = [toint(x) for x in res.get("any", []) if toint(x)]
            if anyp:
                ins = anyp[:1]
        if not ins:
            try:
                body = page.evaluate(
                    "()=>document.body.innerText.slice(0,300)") or ""
                dbglog(f"no price for {nm}; url={page.url}; body={body!r}")
            except Exception as e2:
                dbglog(f"no price for {nm}; eval err {e2}")
            return None
        out = {"price": ins[0],
               "wallet_price": ins[1] if len(ins) > 1 else None,
               "old_price": dels[0] if dels else None}
        out["in_stock"] = bool(res.get("buyBtn")) and not res.get("noStock")
        out["sizes_count"] = res.get("sizes") or None
        return out
    except Exception as e:
        try:
            dbglog(f"price_browser err {nm}: {e!r}")
        except Exception:
            pass
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


def snapshot(nm, page=None):
    """Полный снимок товара для мониторинга."""
    info = card_info(nm)
    snap = dict(info)
    snap["stock"] = stock(nm)
    pr = price_browser(nm, page=page)
    if pr:
        snap.update(pr)
    return snap


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    nm = sys.argv[1] if len(sys.argv) > 1 else "34036071"
    print(json.dumps(snapshot(nm), ensure_ascii=False, indent=1))
