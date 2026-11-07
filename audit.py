"""audit.py — комплексный аудит карточки WB/Ozon → Excel-отчёт.

Собирает: идентичность карточки, продавца, цену/остатки, статистику
отзывов, темы негатива и авто-флаги проблем.

Запуск:
    python audit.py wb 34036071 out.xlsx [max_review_pages]
    python audit.py ozon 3371018537 out.xlsx
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "lib"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import reviews_export  # noqa: E402


def collect(nm, platform):
    """Собрать данные карточки. Возвращает (meta, rows, errors)."""
    meta, rows, errs = {}, [], []
    if platform == "wb":
        import wb
        meta = wb.card_info(nm) or {}
        meta["stock"] = wb.stock(nm)
        try:
            # число фото из card.json
            import requests
            vol, part = int(nm) // 100000, int(nm) // 1000
            b = reviews_export._basket_num(vol)
            d = requests.get(
                f"https://basket-{b}.wbbasket.ru/vol{vol}/part{part}/"
                f"{nm}/info/ru/card.json", timeout=15,
                headers={"User-Agent": "Mozilla/5.0"}).json()
            meta["photos"] = (d.get("media") or {}).get("photo_count")
            meta["created"] = d.get("created_at") or d.get("time")
            meta["description_len"] = len(
                d.get("description") or "")
        except Exception as e:
            errs.append(f"card.json: {e}")
        try:
            rows, name = reviews_export.export_wb(nm)
            meta.setdefault("name", name)
        except Exception as e:
            errs.append(f"reviews: {e}")
    else:
        try:
            rows, name = reviews_export.export_ozon(nm, max_pages=6)
            meta["name"] = name
        except Exception as e:
            errs.append(f"reviews: {e}")
        meta.setdefault("nm", nm)
        try:
            import ozon
            meta["nm"] = ozon.sku_from_url(nm) or nm
            snap = ozon.snapshot(nm)
            if snap:
                meta.update({k: v for k, v in snap.items() if v})
            else:
                errs.append("snapshot: пусто")
        except Exception as e:
            errs.append(f"snapshot: {e}")
    return meta, rows, errs


def findings(meta, a):
    """Авто-флаги проблем по собранным данным."""
    out = []
    st = a["stats"]
    if meta.get("photos") is not None and meta["photos"] < 5:
        out.append(f"Мало фото в карточке: {meta['photos']} — "
                   f"ниже конкурентного минимума")
    if st["avg"] and st["avg"] < 4.6:
        out.append(f"Рейтинг {st['avg']} ниже 4.6 — влияет на конверсию")
    if st["total"] and st["neg"] / max(1, st["total"]) > 0.15:
        out.append(f"Доля негатива {st['neg']}/{st['total']} "
                   f"({st['neg']*100//st['total']}%) — выше нормы 15%")
    if meta.get("description_len") is not None and meta["description_len"] < 200:
        out.append("Короткое описание (<200 зн.) — слабое SEO наполнение")
    if meta.get("stock") == 0:
        out.append("Товара нет в наличии — карточка теряет позиции")
    for t in a["topics"][:2]:
        out.append(f"Частый негатив: «{t['topic']}» — {t['count']} отзывов")
    return out


def save_audit_xlsx(meta, rows, a, errs, path, platform):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wbk = Workbook()
    hdr = PatternFill("solid", fgColor="1F4E78")
    hf = Font(bold=True, color="FFFFFF")

    # Лист 1: сводка
    ws = wbk.active
    ws.title = "Аудит"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 70
    rows1 = [
        ("Площадка", platform.upper()),
        ("Артикул / SKU", meta.get("nm", "")),
        ("Название", meta.get("name", "")),
        ("Бренд", meta.get("brand", "")),
        ("Продавец", meta.get("seller", "")),
        ("Цена, ₽", meta.get("price", "")),
        ("Остаток / наличие", meta.get("stock",
          "в наличии" if meta.get("in_stock") else "")),
        ("Фото в карточке", meta.get("photos", "")),
        ("Отзывов собрано", a["stats"]["total"]),
        ("Средняя оценка", a["stats"]["avg"]),
        ("Негативных (1-3★)", a["stats"]["neg"]),
        ("Отзывов с фото", a["stats"]["with_photos"]),
    ]
    for r, (k, v) in enumerate(rows1, 1):
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v)
    ws.cell(14, 1, "ВЫВОДЫ").font = hf
    ws.cell(14, 1).fill = hdr
    for i, f in enumerate(findings(meta, a), 15):
        ws.cell(i, 1, "•")
        ws.cell(i, 2, f)
    if errs:
        ws.cell(14 + len(findings(meta, a)) + 2, 1,
                "Частичные ошибки сбора: " + "; ".join(errs))

    # Лист 2: темы негатива
    ws2 = wbk.create_sheet("Темы негатива")
    ws2.append(["Тема", "Отзывов", "Примеры"])
    for c in ws2[1]:
        c.font = hf; c.fill = hdr
    for t in a["topics"]:
        ws2.append([t["topic"], t["count"], "\n---\n".join(t["examples"])])
    ws2.column_dimensions["A"].width = 26
    ws2.column_dimensions["B"].width = 10
    ws2.column_dimensions["C"].width = 90
    for r in ws2.iter_rows(min_row=2):
        r[2].alignment = Alignment(wrap_text=True, vertical="top")

    # Лист 3: сырые отзывы
    ws3 = wbk.create_sheet("Отзывы")
    cols = ["date", "author", "rating", "text", "pros", "cons", "photos"]
    ws3.append(cols)
    for c in ws3[1]:
        c.font = hf; c.fill = hdr
    for r in rows:
        ws3.append([r.get(c, "") for c in cols])
    for i, w in enumerate([18, 20, 8, 60, 40, 40, 8], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    wbk.save(path)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    plat = sys.argv[1].lower()
    ref = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else f"audit_{plat}.xlsx"
    if plat not in ("wb", "ozon"):
        # авто-детект: чистое число → wb
        plat = "wb" if re.match(r"^\d+$", ref) else "ozon"
    meta, rows, errs = collect(ref, plat)
    a = reviews_export.analyze_reviews(rows)
    save_audit_xlsx(meta, rows, a, errs, out, plat)
    print(f"OK: {out} | отзывов {a['stats']['total']}, "
          f"avg {a['stats']['avg']}, флагов {len(findings(meta, a))}, "
          f"ошибок сбора {len(errs)}")


if __name__ == "__main__":
    main()
