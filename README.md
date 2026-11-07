# Marketplace Card Audit (WB / Ozon)

One-command audit of a product card on Wildberries or Ozon → a formatted
Excel report a seller can act on.

```bash
python audit.py wb 34036071 report.xlsx
python audit.py ozon 3371018537 report.xlsx
```

## What the report contains (see `docs/demo_wb_34036071.xlsx` — real output)

**Sheet «Аудит» — card health summary:**

- identity (name, brand, seller), price, stock, photo count
- reviews collected, average rating, negative count (1–3★), photos in
  reviews
- **auto-conclusions** — flagged problems like "rating 4.41 below 4.6
  hurts conversion", "16% negative — above the 15% norm", "only 1 photo
  — below competitive minimum"

**Sheet «Темы негатива» — what buyers actually complain about:**

complaints clustered into themes (Сервис/возврат, Качество/брак,
Размер/посадка, Доставка, Упаковка, Несоответствие описанию…) with counts
and quoted examples — so the seller sees *why* the rating dips, not just
that it does.

**Sheet «Отзывы» — raw export:** date, author, rating, text, pros/cons,
photo count — for manual digging.

## How it works

- WB: public basket CDN (`wbbasket.ru` card.json) + public feedbacks API
  (`feedbacks.wb.ru`). **No keys, no login, no browser** for the core.
- Ozon: public product page state parsing (falls back to a local debug
  Chrome for JS-heavy fields when available — see `lib/browser_heavy.py`,
  optional, Windows-oriented).
- Partial collection failures degrade gracefully: the report marks
  "частичные ошибки сбора" instead of dying.

## Install

```bash
pip install -r requirements.txt   # requests + openpyxl only
python audit.py wb <артикул> report.xlsx
```

## License

MIT — see LICENSE.
