"""reviews_export.py — выгрузка отзывов WB и Ozon в CSV.

WB — публичный feedbacks API (без браузера).
Ozon — composer API внутри открытой страницы debug-Chrome.

CLI:
  python reviews_export.py wb 34036071 out.csv|out.xlsx
  python reviews_export.py ozon "https://www.ozon.ru/product/...-3371018537/" out.xlsx [pages]
"""
import csv
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 Chrome/120 Safari/537.36"}
HERE = os.path.dirname(os.path.abspath(__file__))


def _basket_num(vol):
    for top, n in [(143, 1), (287, 2), (431, 3), (719, 4), (1007, 5),
                   (1061, 6), (1115, 7), (1169, 8), (1313, 9), (1601, 10),
                   (1655, 11), (1919, 12), (2045, 13), (2337, 14),
                   (2387, 15), (2745, 16), (2819, 17), (2939, 18),
                   (3059, 19), (3179, 20), (3299, 21), (3419, 22),
                   (3529, 23), (3699, 24), (3869, 25), (4039, 26),
                   (4299, 27), (4499, 28), (4699, 29), (4899, 30)]:
        if vol <= top:
            return f"{n:02d}"
    return "31"


def _wb_card(nm):
    """card.json по артикулу: пробуем расчётный basket, потом соседние."""
    vol, part = int(nm) // 100000, int(nm) // 1000
    b0 = int(_basket_num(vol))
    for b in [b0, b0 - 1, b0 - 2, b0 + 1] + list(range(1, b0 - 2)):
        if b < 1:
            continue
        u = (f"https://basket-{b:02d}.wbbasket.ru/vol{vol}/part{part}"
             f"/{nm}/info/ru/card.json")
        try:
            r = requests.get(u, timeout=10)
            if r.ok:
                return r.json()
        except requests.RequestException:
            pass
    return {}


def export_wb(nm):
    """Отзывы WB по артикулу → список dict."""
    nm = int(nm)
    card = _wb_card(nm)
    imt = card.get("imt_id")
    d = requests.get(f"https://feedbacks1.wb.ru/feedbacks/v2/{imt}",
                     headers=UA, timeout=20).json()
    out = []
    for f in d.get("feedbacks") or []:
        out.append({
            "platform": "WB",
            "date": (f.get("createdDate") or "")[:19].replace("T", " "),
            "author": (f.get("wbUserDetails") or {}).get("name", ""),
            "rating": f.get("productValuation"),
            "text": f.get("text", ""),
            "pros": f.get("pros", ""),
            "cons": f.get("cons", ""),
            "size": f.get("size", ""),
            "color": f.get("color", ""),
            "photos": len(f.get("photo") or []) or len(f.get("photos") or []),
        })
    return out, card.get("imt_name")


def _ozon_reviews_page(page, path):
    return page.evaluate("""async (path) => {
      const r = await fetch('/api/composer-api.bx/page/json/v2?url=' + path,
                            {credentials: 'include'});
      if (!r.ok) return {__err: r.status};
      return await r.json();
    }""", path)


def export_ozon(url_or_sku, max_pages=10, page=None):
    """Отзывы Ozon по ссылке/SKU → (rows, name). Нужен открытый debug-Chrome."""
    import ozon
    close = False
    if page is None:
        from playwright.sync_api import sync_playwright
        # heavy-Chrome (9223) периодически попадает в сетевой бан Ozon
        # (commit висит). Main-Chrome (9222) — живой профиль, Ozon ему
        # доверяет. Пробуем heavy, при неудаче — новая вкладка в main.
        pw = sync_playwright().start()
        try:
            from browser_heavy import ensure_heavy, connect_heavy_page
            ensure_heavy()
            page = connect_heavy_page(pw)
            page.goto("https://www.ozon.ru/", wait_until="commit",
                      timeout=15000)
        except Exception:
            b = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
            page = b.contexts[0].new_page()
        close = True
    try:
        base = url_or_sku
        if re.match(r"^\d+$", str(base).strip()):
            # резолвим SKU в реальный slug; Ozon часто виснет на goto,
            # но origin уже загружен — продолжаем после таймаута
            try:
                page.goto(f"https://www.ozon.ru/product/x-{base}/",
                          wait_until="domcontentloaded", timeout=45000)
            except Exception:
                if "ozon.ru" not in (page.url or ""):
                    raise
            page.wait_for_timeout(3000)
            base = page.url
        prod_path = base.split("ozon.ru")[-1].split("?")[0].rstrip("/")
        reviews_path = prod_path + "/reviews/?sort=publishedAt_desc"
        rows, name = [], None
        for _ in range(max_pages):
            data = _ozon_reviews_page(page, reviews_path)
            if not isinstance(data, dict) or data.get("__err"):
                break
            ws = data.get("widgetStates") or {}
            key = next((k for k in ws if k.startswith("webListReviews")), None)
            if not key:
                break
            v = ws[key]
            v = json.loads(v) if isinstance(v, str) else v
            prods = v.get("products") or {}
            for pdat in prods.values():
                name = name or pdat.get("name")
            for rv in v.get("reviews") or []:
                c = rv.get("content") or {}
                au = rv.get("author") or {}
                aname = " ".join(x for x in (au.get("firstName"),
                                           au.get("lastName")) if x)
                import datetime as _dt
                ts = rv.get("publishedAt") or rv.get("createdAt")
                date = (_dt.datetime.fromtimestamp(ts).strftime(
                    "%Y-%m-%d %H:%M:%S") if ts else "")
                rows.append({
                    "platform": "Ozon",
                    "date": date,
                    "author": aname,
                    "rating": (c.get("rating") or {}).get("value")
                              or c.get("score"),
                    "text": c.get("comment", ""),
                    "pros": c.get("positive", ""),
                    "cons": c.get("negative", ""),
                    "size": "", "color": "",
                    "photos": len(c.get("photos") or []),
                })
            cur = (v.get("paging") or {}).get("page", 0)
            nxt = next(
                (l for l in (v.get("paging") or {}).get("links", [])
                 if (l.get("text") or "").strip().isdigit()
                 and int(l["text"]) == int(cur) + 1),
                None)
            if not nxt or not nxt.get("urlParams"):
                break
            reviews_path = prod_path + "/reviews/" + nxt["urlParams"]
        return rows, name
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


TOPICS = {
    "Размер/посадка": ["маломер", "большемер", "размер не подош", "маленьк",
                     "больш", "узк", "широк", "сели после", "не по размеру",
                     "размерн", "посадк"],
    "Качество/брак": ["брак", "сломал", "порвал", "трещин", "отвалил",
                      "дефект", "потёрт", "потерт", "пятн", "нитк", "клея",
                      "разошл", "рассыпал", "сломан", "крив"],
    "Упаковка": ["упаков", "коробк", "помят", "вскрыт", "мят", "плёнк"],
    "Доставка/логистика": ["доставк", "пвз", "курьер", "пришл", "опоздал",
                           "долго", "пункт выдач", "склад"],
    "Несоответствие описанию": ["не соответств", "на фото", "отличается",
                                "ожидал", "не такой", "другой цвет",
                                "в описании"],
    "Запах": ["запах", "пахнет", "вонь", "химичес"],
    "Сервис/возврат": ["возврат", "обмен", "вернуть", "поддержк", "продавец",
                       "отказ"],
}


def analyze_reviews(rows):
    """Разбор негатива по темам + базовая статистика.

    Возвращает dict: stats + topics [{topic, count, examples}]."""
    from collections import Counter
    neg = [r for r in rows if int(r.get("rating") or 5) <= 3]
    topics = []
    for topic, words in TOPICS.items():
        hits = []
        for r in neg:
            txt = " ".join([r.get("text") or "", r.get("cons") or "",
                            r.get("pros") or ""]).lower()
            if any(w in txt for w in words):
                hits.append(r)
        if hits:
            examples = [((h.get("text") or h.get("cons") or "")
                         .strip().replace("\n", " "))[:160]
                        for h in hits[:3]]
            topics.append({"topic": topic, "count": len(hits),
                           "examples": [e for e in examples if e]})
    topics.sort(key=lambda t: -t["count"])
    rc = Counter(int(r.get("rating") or 0) for r in rows)
    stats = {
        "total": len(rows),
        "avg": round(sum(k * v for k, v in rc.items()) /
                     max(1, sum(rc.values())), 2),
        "neg": sum(v for k, v in rc.items() if k <= 3),
        "with_photos": sum(1 for r in rows if r.get("photos")),
        "dist": {s: rc.get(s, 0) for s in range(1, 6)},
    }
    return {"stats": stats, "topics": topics, "neg_rows": neg}


def save_report_xlsx(rows, path, name="", analysis=None, replies=None):
    """Полный отчёт кворка: отзывы + статистика + темы негатива."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.chart import BarChart, Reference

    a = analysis or analyze_reviews(rows)
    blue = PatternFill("solid", fgColor="1F4E78")

    wb = Workbook()
    ws = wb.active
    ws.title = "Отзывы"
    hdr = HEADERS_RU + (["Черновик ответа"] if replies else [])
    ws.append(hdr)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = blue
    rfill = {1: "FFC7CE", 2: "FFC7CE", 3: "FFEB9C", 4: "C6EFCE",
             5: "C6EFCE"}
    for i, r in enumerate(rows):
        row = [r.get(k, "") for k in COLS]
        if replies:
            row.append((replies[i] if i < len(replies) else "") or "")
        ws.append(row)
        try:
            ws.cell(ws.max_row, 4).fill = PatternFill(
                "solid", fgColor=rfill.get(int(r.get("rating") or 0),
                                           "FFFFFF"))
        except Exception:
            pass
    widths = [10, 18, 13, 7, 55, 30, 30, 9, 11, 6] + ([55] if replies else [])
    for i, wd in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = wd
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    ws2 = wb.create_sheet("Статистика")
    ws2.append(["Метрика", "Значение"])
    s = a["stats"]
    ws2.append(["Товар", name])
    ws2.append(["Отзывов выгружено", s["total"]])
    ws2.append(["Средняя оценка", s["avg"]])
    ws2.append(["Негативных (1-3★)", s["neg"]])
    ws2.append(["С фото", s["with_photos"]])
    for c in ws2[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = blue
    ws2.column_dimensions["A"].width = 26
    ws2.column_dimensions["B"].width = 44
    ws2.append([])
    ws2.append(["Оценка", "Кол-во"])
    st = ws2.max_row
    for star in range(5, 0, -1):
        ws2.append([f"{star}★", s["dist"].get(star, 0)])
    ch = BarChart()
    ch.title = "Распределение оценок"
    ch.height = 7
    ch.width = 13
    ch.add_data(Reference(ws2, min_col=2, min_row=st, max_row=st + 4),
                titles_from_data=True)
    ch.set_categories(Reference(ws2, min_col=1, min_row=st + 1,
                                max_row=st + 5))
    ws2.add_chart(ch, "D8")

    ws3 = wb.create_sheet("Темы негатива")
    ws3.append(["Тема", "Отзывов", "Примеры"])
    for c in ws3[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = blue
    for t in a["topics"]:
        ws3.append([t["topic"], t["count"], "\n---\n".join(t["examples"])])
    ws3.column_dimensions["A"].width = 28
    ws3.column_dimensions["B"].width = 10
    ws3.column_dimensions["C"].width = 90
    for row in ws3.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)


COLS = ["platform", "date", "author", "rating", "text",
        "pros", "cons", "size", "color", "photos"]
HEADERS_RU = ["Площадка", "Дата", "Автор", "Оценка", "Отзыв",
              "Плюсы", "Минусы", "Размер", "Цвет", "Фото"]


def save_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def save_xlsx(rows, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Отзывы"
    ws.append(HEADERS_RU)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    for r in rows:
        ws.append([r.get(k, "") for k in COLS])
    widths = [10, 20, 16, 8, 60, 40, 40, 10, 12, 8]
    for col, w in zip("ABCDEFGHIJ", widths):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def save_rows(rows, path):
    if path.lower().endswith(".xlsx"):
        save_xlsx(rows, path)
    else:
        save_csv(rows, path)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    kind, ref = sys.argv[1].lower(), sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else f"reviews_{kind}.csv"
    pages = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    if kind == "wb":
        rows, name = export_wb(ref)
    elif kind == "report":
        # полный кворк-отчёт: wb|ozon + ссылка/артикул
        plat, ref2 = ref.split("|", 1)
        rows, name = (export_wb(ref2) if plat == "wb"
                      else export_ozon(ref2, max_pages=pages))
        save_report_xlsx(rows, out, name=name)
        a = analyze_reviews(rows)
        print(f"OK report: {len(rows)} отзывов, тем негатива "
              f"{len(a['topics'])} -> {out}")
        return
    else:
        rows, name = export_ozon(ref, max_pages=pages)
    save_rows(rows, out)
    print(f"OK: {len(rows)} отзывов -> {out} ({name or ''})")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
