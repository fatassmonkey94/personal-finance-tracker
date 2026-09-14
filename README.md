# personal-finance-tracker

A personal finance tracker giving a comprehensive monthly transaction breakdown
and analysis of personal spending patterns.

It turns raw bank and credit card statements into a monthly transaction
compilation and an income statement (Revenues / Expenses / Net Income), in
Singapore Dollars.

Everything runs locally. No statement data leaves your machine — there are no
network calls in the app.

---

## Quick start

```bash
./run.sh
```

That creates the virtual environment on first run, installs dependencies, and
opens the app in your browser.

**Input new month statements** — the green button at the top right, and again at
the top of the sidebar — opens the page holding everything you feed the app:
drag statements onto the uploader, or, under *"…or read them straight off this
machine"*, point it at the folder you save statements into, which saves picking
files by hand every month. The same page carries the CPF and categorisation
settings, so the dashboard itself stays given over to your numbers. To have a
folder loaded before the page even opens:

```bash
PFT_STATEMENTS=~/Downloads/statements ./run.sh
```

To try it before you have statements to hand:

```bash
.venv/bin/python make_samples.py
```

which writes four realistic sample statements to `sample_data/` (a DBS-style
account CSV, a UOB-style card Excel export, and two card PDFs — one with
transaction dates and one without). Upload those.

Run the tests with:

```bash
.venv/bin/python -m pytest tests -q
```

### On another machine

Clone and run — `run.sh` builds the virtualenv and installs everything on first
launch:

```bash
git clone git@github.com:<you>/personal-finance-tracker.git && cd personal-finance-tracker && ./run.sh
```

Needs Python 3.9 or newer. Two escape hatches if the machine is awkward:
`PFT_PYTHON=python3.12 ./run.sh` picks a specific interpreter, and
`PFT_PIP_INDEX=<url> ./run.sh` uses your own package mirror — useful on a work
machine whose `PIP_INDEX_URL` points at a corporate index that is unreachable
off-VPN.

**What does not travel with the repo, by design:** the `data/` folder, which
holds `parent_names.txt`, your own categories in `custom_categories.json`, and
the learned category fixes in `category_overrides.json`. Point
`PFT_DATA_DIR=/somewhere/else` at another folder to keep them off the repo
entirely. Both are derived from your own statements, so they
are gitignored and stay on the machine that made them. On a new machine, retype
the allowance names once under **Input new month statements → Categorisation**; the file is
written for you. Your
statements are never in the repo either — keep them wherever you like and point
the loader at that folder.


---

## What you upload

| Format | What it needs | Notes |
| --- | --- | --- |
| **CSV / TSV** | date, description, amount, currency | Preamble rows above the header are skipped |
| **Excel** (`.xlsx`, `.xlsm`, `.xls`) | same | Every sheet is scanned; legacy `.xls` needs `xlrd` |
| **PDF** | description and amount; dates read when present | Needs a text layer — scans require OCR first |

Column names are matched flexibly rather than requiring a fixed template. All of
these are understood:

- **Dates** — `Transaction Date`, `Date`, `Posting Date`, `Value Date`, `Txn Date`
- **Descriptions** — `Description`, `Particulars`, `Narrative`, `Transaction Ref1..3`
  (multiple description columns are joined)
- **Amounts** — a `Debit`/`Credit` pair, a single signed `Amount`, or `Amount`
  plus a `DR/CR` indicator column
- **Currency** — `Currency`, `CCY`, plus an optional `Foreign Amount`

Where a statement has both a foreign and a local amount column — UOB writes
`Transaction Amount(Foreign)` *before* `Transaction Amount(Local)` — the local
SGD figure is always the one recorded, and the foreign one is kept for reference.
Account labels come from the export's own preamble (`Account Type:` /
`Account Number:`), so two cards from the same bank stay distinct.

Date formats handled include `dd/mm/yyyy`, `dd-mmm-yyyy`, `yyyy-mm-dd`,
`18 Jun`, `June 18, 2025`, and Excel serial dates. Day-first is assumed, which is
the Singapore convention.

### PDFs without transaction dates

The brief allows for a PDF that carries only descriptions and amounts. When a
line has no date, it is dated to the **end of the statement period** (detected
from "Statement Date" or "Statement Period" in the document), flagged with a 📅
in the compilation, and counted in the note at the foot of the income statement.
Set a fallback month under **Input new month statements → Statements** if a PDF has no
detectable period either.

---

## The two monthly outputs

### 1. Transaction compilation

Every transaction across every account and card, in chronological order, with:

- **Date**
- **Description** — auto-summarised to **10 words or fewer**
- **Category**
- **Type** — Debit (money out) or Credit (money in)
- **Amount (SGD)** — the figure the bank or card converted at the point of
  transaction. Where a statement showed a foreign amount too, it is kept in the
  *Original Currency* / *Original Amount* columns for reference; the SGD figure
  is never re-converted with a rate of our own.
- **Source account**, the raw statement text, and any flags

Editable in the app — change a category or description and the income statement
recalculates. Corrections can be remembered so the same merchant is right next
month (stored in `data/category_overrides.json`).

### 2. Income statement

```
REVENUES
    Gross Salary (credited to bank)
    CPF Contribution (per CPF Board's rates)
    Additional Income (interest, dividends, other)
  Total Revenues                                    <- bold

EXPENSES
  Fixed Expenses
    Insurance
    Telco
    Subscriptions
    Allowance to Parents
    Tax
   Total Fixed Expenses                             <- bold

  Variable Expenses
    Transport (Bus/MRT)
    Transport (Cab)
    Transport (Car Maintenance)
    Food
    Groceries
    Shopping
    Experiences/Hobbies
    Additional Expenses
    Uncategorised
   Total Variable Expenses                          <- bold

  Total Expenses                                    <- bold

NET INCOME  = Total Revenues - (Fixed Expenses + Variable Expenses)
```

Each section lists **every item**, not a category total: revenues as *item ·
category · amount*, and each expense section as *item · category · payment
method · amount*, where payment method is the card or account the money
actually moved through. A category roll-up sits below in *Summary by category*,
where clicking a line still opens the transactions behind it — and is the only
place the CPF working is shown, since CPF is computed rather than parsed.

**Uncategorised vs Additional Expenses** — two buckets that look similar and are
not. *Uncategorised* is where the app parks what it could not place, and those
rows are tinted in the transaction table and listed in the Review tab.
*Additional Expenses* is the bucket **you** put a genuine one-off in. Folding
them together would make an unread guess look like your decision.

Export both sheets, for one month or several, as a formatted `.xlsx` from
**Export** in the sidebar.

---

## Getting around the app

The sidebar is the whole navigation: a green **Input new month statements**
button at the top, then **each year, expanding to its months**, then Uploaded
documents and Export under *Tools*. A month button carries its own review count
("May · 24 to review"), so you can see where the work is without opening
anything. The same green button sits at the right of the header.

### The dashboard — the landing page

Selecting a year gives an annual read of everything loaded for it:

1. **Two pies and a savings bar.** *Income* split by source — one green stepped
   light to dark, so the sources read as parts of a single thing. *Expenses*
   split by category, fixed commitments warm (orange / red / yellow) and
   discretionary spend maroon to purple, so the split the income statement makes
   is visible on the wheel without a second legend; the three biggest wedges
   name themselves without a hover. *Savings* is a stacked bar of what was kept
   against what was spent, in blue, with last year beside it as a dashed outline
   — an outline, because it is a reference, not a second reading. It appears
   only when statements for that year are actually loaded. A category that nets
   negative over the year — a refund larger than the spend — cannot be drawn as
   a wedge, so it is named in a caption beneath rather than quietly folded in.
2. **Cumulative savings, year on year** — what each year put aside, in light
   blue, with a least-squares trend line across them. A year is marked **YTD**
   until all twelve months have statements loaded. That is stricter than the
   calendar — a finished year with two months missing is still YTD — but the
   label then describes what the bar is built from rather than what the date
   says.
3. **Month on month** — income, expenses and savings as dots, joined by a solid
   connector and shadowed by a dashed least-squares fit. The connector answers
   "what happened between March and April"; the fit answers "which way is the
   year going", and a volatile month against a steady trend is the useful read.
   The x axis always runs January to December; a month with no statements loaded
   keeps its column but carries no dot, because a zero there would read as
   "earned nothing" rather than "not known". Hovering a dot gives the amount,
   the change on the month before, and the change against the year's average.
   A year picker sits beside the heading.
4. **Where your income came from** — the top three payers by total received,
   each with the amount year to date and the last payment. Names are read out of
   the statement's own wording: a Singapore bank credit wraps the payer in
   routing text ("Inward CR - GIRO TO42... SALA Salary Payment ACME PTE. LTD."),
   so the name is taken as the words before the legal suffix, stopping at the
   bank's routing words. A line with no counterparty at all — bank interest, a
   dividend credit — keeps its own description rather than being given a
   fabricated name.
5. **Expenses by category, cumulative for the year** — one bar per category for
   the whole year, coloured by fixed or variable.
6. **More annual detail**, collapsed — the connected dot plot of spending by
   category month on month, the month-by-month table, and notes on anything
   still needing review and on the transfers held outside the totals.

### A month

1. The five headline figures for that month sit at the top.
2. **Income Statement** is the first sub-tab: revenues, then fixed and variable
   expenses, each listed item by item with its payment method and a bold total.
   Under *Summary by category*, **clicking any line** opens a scrollable pop-up
   listing the transactions behind it, with money-in and money-out subtotals.
   Clicking the CPF line shows how the figure was derived instead.
3. **Transactions** is next, filterable on every column under *Filters*: date
   range, category, account, type, section, amount range, free-text search across
   description and raw statement text, plus flag-only and foreign-currency-only
   toggles. The expander reports how many filters are active and stays open while
   any are set, so a forgotten filter cannot quietly skew what you are reading.
4. **⚠ Review** is tinted red, because it is the tab that needs you — it lists
   what was categorised on a guess and why. Those same rows are tinted in the
   Transactions table itself, so you meet them while scrolling rather than only
   when you go looking.

---

## Design

Dark, minimalist: a near-black ground (`#0B0C0E`), one teal accent, hairline
borders, near-square corners, and no chrome that does not carry information.
Numbers are set in tabular figures so columns align, and metric labels drop to
small uppercase so the figures lead.

The typeface is **Space Grotesk** — neutral in tone, angular in its terminals and
geometric in its bowls — with **JetBrains Mono** for code. Both are self-hosted
from `static/fonts/` (about 72 KB), so the app makes no request to a font CDN and
works offline. Theme colours, fonts and the chart palette live in
`.streamlit/config.toml`; only what Streamlit exposes no API for (the header
button's green, the red Review tab) is done in CSS — and that CSS is scoped to
the one container it belongs to, so the Review tint cannot leak onto the third
tab of some unrelated group.

---

## Decisions worth knowing about

**Large unidentified transfers are held back.** A PayNow transfer with no
recognisable merchant is booked to Food (out) or Additional Income (in)
per your rules — but only up to a threshold, S$500 by default. Above that the
guess is too consequential to make silently: a S$24,000 PayNow is not a
restaurant bill, and a S$26,000 inbound transfer is not salary. Those are tagged
*Unclassified Transfer*, listed below the income statement with a total, and
counted normally the moment you assign a category. Set the threshold to 0 under **Input new
month statements → Categorisation** to follow your rule literally in every case.

**Transfers to and from investment accounts are excluded.** Funding a brokerage
or exchange account is not an expense, and withdrawing from one is not income —
both are your own capital moving. Interactive Brokers, Tiger, moomoo, Endowus,
Syfe, StashAway, OKX, Binance, Coinbase and similar are treated as internal
transfers. An actual dividend or interest payout says so in the description and
still counts as income.

**Credit card bill payments are excluded.** Paying your card from your bank
account is a transfer between your own pockets, not spending — the spending is
already itemised on the card statement. Counting both would double-count it, so
those rows (and transfers between your own accounts) are tagged and reported
separately below the income statement rather than silently dropped. The same
applies to the "PAYMENT — THANK YOU" credit on the card side.

**CPF follows CPF Board's published rules, not a flat 20%.** Two things make a
flat percentage wrong, and both applied to real statements:

- **The Ordinary Wage ceiling.** Only the first S$8,000 of a month's wages
  attracts CPF (2026; S$7,400 in 2025, S$6,800 in 2024, S$6,300 from Sep 2023).
  On a S$16,067 gross salary the employee share is 20% × S$8,000 = **S$1,600**,
  not 20% × S$16,067 = S$3,213.
- **The low-wage bands.** Below S$50 there is no contribution; from S$50 to S$500
  the employer contributes and the employee does not; from S$500 to S$750 the
  employee share phases in as 0.6 × (wages − 500).

Rates come from CPF Board's rate table and step down with age — 37% total / 20%
employee at 55 and below, through to 12.5% / 5% above 70. The form defaults to
**Singapore Citizen** (CPF Board's Table 1, which also covers PRs from their 3rd
year); the SPR graduated tables are selectable. Rounding follows the Board's
stated steps: total to the nearest dollar, employee share rounded down, employer
share the difference. `tests/test_cpf.py` asserts every figure against the
"Max." column printed in the official table.

**Where the salary figure comes from.** A Singapore salary credit is normally
*net* of your own CPF, so by default the app treats the bank credit as take-home
and works the gross back from it — which makes *Salary credited + CPF = true
gross pay*. Switch to "Already the gross figure" to treat the credit
as gross and add CPF on top, the literal reading of the original brief. The
employer's 17% share is available as an extra revenue line, off by default.

Sources: [contribution rates](https://www.cpf.gov.sg/employer/employer-obligations/how-much-cpf-contributions-to-pay) ·
[rate table PDF](https://www.cpf.gov.sg/content/dam/web/employer/employer-obligations/documents/CPFcontributionratesfrom1Jan2026.pdf) ·
[OW ceiling](https://www.cpf.gov.sg/service/article/what-is-the-ordinary-wage-ow-ceiling)

---

## How categorisation works

A deterministic, ordered keyword rule engine over roughly 500 Singapore merchant
patterns (`finance/rules.py`). First match wins, and order carries meaning —
GrabFood is tested before Grab so a food delivery isn't booked as transport, and
airlines and hotels are tested before transport so a flight isn't a commute.

Every transaction records which rule fired, visible under **Uploaded documents**,
so no categorisation is a black box.

Specific behaviours from your brief:

- **Allowance to parents** — transfers naming whoever you list in the form. No
  names ship in source; yours are kept in `data/parent_names.txt`, which is
  gitignored, so real names never reach the repository.
- **PayNow / transfers out** — booked to *Food* as you specified, but flagged
  for review since a transfer could be anything.
- **Transport, three ways** — ride-hailing and taxis to *Transport (Cab)*; fares,
  EZ-Link and NETS top-ups to *Transport (Bus/MRT)*; fuel, servicing, parking,
  road tax and car-sharing to *Transport (Car Maintenance)*. Cabs are tested
  first, because the car and public lists carry generic words ("SERVICING",
  "BUS") that a brand name could otherwise collide with.
- **Tax** — IRAS, income tax and property tax are a *Fixed* commitment. "Road
  tax" is not: it contains the word, but it is what you pay to keep a car on the
  road, so it stays with the car.
- **Travel and YouTrip top-ups** — *Experiences/Hobbies*, since the requirements
  list has no Travel row of its own.
- **Refunds** — netted off the category they were spent from rather than counted
  as income, so a returned IKEA purchase reduces Shopping.
- **Wellness, health and sports** — *Experiences/Hobbies*, including clinics,
  dental and pharmacy.
- **Utilities, rent, ATM withdrawals and bank fees** — no line exists for these
  in your structure, so they land in *Uncategorised* and are flagged, rather
  than being hidden or dropped.
- **Merchant names beat location names** — `GIANT-SIMEI MRT` is a supermarket,
  not a train fare, so the generic MRT/BUS/TAXI terms are only tested after every
  named merchant has had a chance to match.

Anything unmatched goes to *Uncategorised* and appears in the **Review** tab.
Nothing is ever silently discarded — unrecognised statement lines are listed
under **Uploaded documents** so you can see exactly what was skipped.

### Your own categories

Add one under **Input new month statements → Categorisation**, choosing whether
it belongs to fixed or variable expenses. A new category has no merchant
keywords behind it, so nothing lands in it automatically at first — assign a
transaction to it with *remember my fixes* ticked and that merchant goes there
from then on, which is the same mechanism that corrects a wrong guess. Your
categories are kept in `data/custom_categories.json`, alongside the learned
fixes and out of the repository.

### When a category is renamed

Learned fixes store a category *name*, so the app brings old names forward when
it loads them: `Food & Dining` and `Food Delivery` both become `Food`, `Travel`
becomes `Experiences/Hobbies`, `Other` becomes `Uncategorised`. The one
exception is `Transport`, which split three ways — nothing in the old name says
whether a merchant was a bus fare, a cab or a workshop, so those fixes are
dropped and the rule engine, which does draw that distinction, decides again.

---

## Layout

```
app.py                    Streamlit UI
finance/
  model.py                Transaction, categories, sections
  rules.py                categorisation rule engine + learned overrides
  describe.py             10-word description generator
  parse_tabular.py        CSV / Excel parsing
  parse_pdf.py            PDF statement parsing
  ingest.py               dispatch, enrich, deduplicate
  cpf.py                  CPF rates, ceilings and gross-up (from cpf.gov.sg)
  report.py               monthly compilation, income statement, annual roll-up
  export_excel.py         formatted .xlsx writer
make_samples.py           generates sample statements
static/fonts/             self-hosted Space Grotesk + JetBrains Mono
tests/                    283 tests, incl. CPF and real-statement regressions
```

Duplicate uploads are detected: exact repeats are dropped, and the same amount
appearing on the same day across two different files is flagged in case you
uploaded one statement in two formats.
