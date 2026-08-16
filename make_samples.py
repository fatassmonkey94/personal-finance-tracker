"""Generate realistic sample statements so the app can be tried immediately.

Writes to sample_data/:
  dbs-multiplier-account-jun2025.csv   bank account CSV, preamble + Ref1..3 columns
  uob-one-card-jun2025.xlsx            card export, Debit/Credit column pair
  ocbc-90n-card-jun2025.pdf            card PDF with FX lines and no per-line year
  citi-card-nodate-jun2025.pdf         card PDF with descriptions + amounts only

The PDF writer here is deliberately dependency-free — it emits a minimal but
valid PDF with a text layer, which is all pdfplumber needs.
"""
from __future__ import annotations

import os
import zlib

import pandas as pd

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")


# ---------------------------------------------------------------------------
# Minimal PDF writer
# ---------------------------------------------------------------------------
def write_pdf(path: str, pages: list, font_size: float = 9.5,
              leading: float = 13.0) -> None:
    """pages: list of list-of-strings (one string per line)."""
    page_objects = []
    for lines in pages:
        parts = ["BT", "/F1 %.1f Tf" % font_size, "%.1f TL" % leading, "1 0 0 1 40 790 Tm"]
        for line in lines:
            escaped = (line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))
            parts.append("(%s) Tj T*" % escaped)
        parts.append("ET")
        page_objects.append("\n".join(parts).encode("latin-1", "replace"))

    objects = []           # 1-indexed list of raw object bodies
    font_id = 3 + 2 * len(page_objects)

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # obj 1
    kids = " ".join("%d 0 R" % (3 + 2 * i) for i in range(len(page_objects)))
    objects.append(
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_objects))).encode()
    )  # obj 2

    for i, stream in enumerate(page_objects):
        page_id = 3 + 2 * i
        content_id = page_id + 1
        objects.append((
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (font_id, content_id)
        ).encode())
        compressed = zlib.compress(stream)
        objects.append(
            ("<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(compressed)).encode()
            + compressed + b"\nendstream"
        )

    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % number).encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += ("%010d 00000 n \n" % offset).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref_at)).encode()

    with open(path, "wb") as fh:
        fh.write(bytes(out))


def _pad(left: str, right: str, width: int = 96) -> str:
    """Left-align description, right-align the amount, like a real statement."""
    space = max(2, width - len(left) - len(right))
    return left + " " * space + right


# ---------------------------------------------------------------------------
# 1. DBS-style bank account CSV
# ---------------------------------------------------------------------------
BANK_ROWS = [
    # date, code, debit, credit, ref1, ref2, ref3
    ("01/06/2025", "GIRO", "185.00", "", "GIRO  PAYMENT", "AIA SINGAPORE PTE LTD", "POLICY 88213"),
    ("02/06/2025", "IBG", "", "6800.00", "SALA", "NORTHWIND ANALYTICS PTE LTD", "JUN SALARY"),
    ("02/06/2025", "ITR", "420.00", "", "PayNow Transfer To", "ALEX TAN", "MONTHLY ALLOWANCE"),
    ("03/06/2025", "ITR", "300.00", "", "PayNow Transfer To", "JAMIE LOW", "ALLOWANCE"),
    ("03/06/2025", "GIRO", "68.90", "", "GIRO  PAYMENT", "SINGTEL MOBILE", "BILL 4471"),
    ("04/06/2025", "POS", "142.35", "", "NTUC FAIRPRICE FINEST", "SINGAPORE SG", ""),
    ("05/06/2025", "ITR", "45.00", "", "PayNow Transfer To", "TAN WEI MING", "DINNER SHARE"),
    ("06/06/2025", "GIRO", "129.00", "", "GIRO  PAYMENT", "SP SERVICES LTD", "UTILITIES"),
    ("08/06/2025", "ATM", "200.00", "", "CASH WITHDRAWAL", "ATM  BUKIT TIMAH", ""),
    ("10/06/2025", "ITR", "500.00", "", "FUNDS TRANSFER TO", "YOUTRIP TOP UP", "TRAVEL WALLET"),
    ("12/06/2025", "GIRO", "1240.55", "", "CREDIT CARD PAYMENT", "OCBC 90N CARD", "AUTO DEBIT"),
    ("15/06/2025", "ITR", "", "180.00", "PayNow Transfer From", "LIM JIA HUI", "TRIP REFUND"),
    ("18/06/2025", "GIRO", "58.00", "", "GIRO  PAYMENT", "ANYTIME FITNESS", "MEMBERSHIP JUN"),
    ("20/06/2025", "DIV", "", "312.40", "DIVIDEND", "CDP SECURITIES", "DBS GROUP HLDG"),
    ("22/06/2025", "GIRO", "890.00", "", "CREDIT CARD PAYMENT", "UOB ONE CARD", "AUTO DEBIT"),
    ("25/06/2025", "ITR", "1500.00", "", "FUNDS TRANSFER TO", "OWN ACCOUNT SAVINGS", "SAVINGS"),
    ("28/06/2025", "POS", "88.20", "", "SHENG SIONG SUPERMARKET", "SINGAPORE SG", ""),
    ("30/06/2025", "INT", "", "94.18", "BONUS INTEREST", "MULTIPLIER ACCOUNT", ""),
    ("30/06/2025", "FEE", "5.00", "", "SERVICE CHARGE", "MONTHLY FEE", ""),
]


def make_bank_csv(path: str) -> None:
    lines = [
        "Account Details For:,DBS Multiplier Account",
        "Account No.:,XXX-X-XXX456",
        "Available Balance:,18425.63",
        "",
        "Statement Period:,01 Jun 2025 to 30 Jun 2025",
        "",
        "Transaction Date,Reference,Debit Amount,Credit Amount,"
        "Transaction Ref1,Transaction Ref2,Transaction Ref3",
    ]
    for row in BANK_ROWS:
        lines.append(",".join('"%s"' % field for field in row))
    lines.append("")
    lines.append("Total Debit,,5587.00,,,,")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 2. UOB-style card export as Excel
# ---------------------------------------------------------------------------
CARD_ROWS = [
    ("03/06/2025", "04/06/2025", "GRABFOOD SINGAPORE SG", "SGD", 24.80, ""),
    ("04/06/2025", "05/06/2025", "GRAB  RIDE SINGAPORE SG", "SGD", 13.60, ""),
    ("05/06/2025", "06/06/2025", "SPOTIFY AB STOCKHOLM", "SGD", 11.98, ""),
    ("06/06/2025", "07/06/2025", "SHELL SERVICE STATION 07", "SGD", 82.40, ""),
    ("07/06/2025", "09/06/2025", "DIN TAI FUNG PARAGON", "SGD", 76.50, ""),
    ("09/06/2025", "10/06/2025", "COLD STORAGE JELITA", "SGD", 96.15, ""),
    ("11/06/2025", "12/06/2025", "SHOPEE SINGAPORE", "SGD", 138.90, ""),
    ("13/06/2025", "14/06/2025", "GOLDEN VILLAGE VIVOCITY", "SGD", 32.00, ""),
    ("14/06/2025", "16/06/2025", "FOODPANDA SINGAPORE", "SGD", 38.25, ""),
    ("16/06/2025", "17/06/2025", "APPLE COM BILL ITUNES", "SGD", 12.98, ""),
    ("17/06/2025", "18/06/2025", "TRANSITLINK SIMPLYGO", "SGD", 62.30, ""),
    ("19/06/2025", "20/06/2025", "REFUND SHOPEE SINGAPORE", "SGD", -45.00, ""),
    ("21/06/2025", "23/06/2025", "DECATHLON SINGAPORE", "SGD", 119.00, ""),
    ("24/06/2025", "25/06/2025", "UNIQLO ORCHARD CENTRAL", "SGD", 89.90, ""),
    ("26/06/2025", "27/06/2025", "AGODA COM SINGAPORE", "USD", 286.44, "USD 212.00"),
    ("27/06/2025", "28/06/2025", "STARBUCKS HOLLAND V", "SGD", 8.60, ""),
    ("29/06/2025", "30/06/2025", "CLIMB CENTRAL KALLANG", "SGD", 34.00, ""),
]


def make_card_excel(path: str) -> None:
    header = ["Transaction Date", "Posting Date", "Description", "Currency",
              "Transaction Amount (SGD)", "Foreign Amount"]
    preamble = pd.DataFrame([
        ["UOB One Card", None, None, None, None, None],
        ["Card Number", "4111-XXXX-XXXX-7823", None, None, None, None],
        ["Statement Period", "01 Jun 2025 to 30 Jun 2025", None, None, None, None],
        [None, None, None, None, None, None],
        header,
    ] + [list(row) for row in CARD_ROWS])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        preamble.to_excel(writer, sheet_name="Transactions", index=False, header=False)


# ---------------------------------------------------------------------------
# 3. OCBC-style card PDF, dates present, some FX lines
# ---------------------------------------------------------------------------
def make_card_pdf(path: str) -> None:
    lines = [
        "OCBC BANK",
        "OCBC 90°N CARD STATEMENT",
        "",
        "Statement Date: 25 JUN 2025",
        "Statement Period: 26 MAY 2025 to 25 JUN 2025",
        "Credit Limit: 15,000.00",
        "",
        "CARD NO: 5412-XXXX-XXXX-3391",
        "",
        _pad("TRANSACTION DATE   DESCRIPTION", "AMOUNT (SGD)"),
        "",
        _pad("28 MAY   PAYMENT - THANK YOU", "1,105.20 CR"),
        _pad("29 MAY   GRAB  A-7HKQMNP SINGAPORE SG", "16.40"),
        _pad("30 MAY   PRUDENTIAL ASSURANCE PREMIUM", "268.00"),
        _pad("31 MAY   FAIRPRICE XTRA NEX", "112.85"),
        _pad("02 JUN   NETFLIX COM SINGAPORE", "19.98"),
        _pad("03 JUN   AMAZON WEB SERVICES", "33.75"),
        "         USD 25.00  EXCHANGE RATE 1.3500",
        _pad("04 JUN   FOODPANDA SG SINGAPORE", "42.10"),
        _pad("05 JUN   ESSO JURONG EAST", "75.20"),
        _pad("07 JUN   SINGAPORE AIRLINES LTD", "684.00"),
        _pad("08 JUN   MARRIOTT HOTEL BANGKOK", "412.66"),
        "         THB 10,800.00  EXCHANGE RATE 0.0382",
        _pad("10 JUN   TIONG BAHRU BAKERY", "18.40"),
        _pad("11 JUN   WATSONS SINGAPORE", "36.75"),
        _pad("12 JUN   RAFFLES MEDICAL CLINIC", "88.00"),
        _pad("14 JUN   GRABFOOD SINGAPORE", "31.20"),
        _pad("15 JUN   SISTIC SINGAPORE", "148.00"),
        _pad("16 JUN   KOI THE BUGIS", "6.80"),
        _pad("18 JUN   CIRCLES LIFE SINGAPORE", "28.00"),
        _pad("19 JUN   DON DON DONKI CLARKE QUAY", "64.30"),
        _pad("20 JUN   HDB CARPARK SEASON PARKING", "110.00"),
        _pad("22 JUN   IKEA TAMPINES", "213.45"),
        _pad("23 JUN   REFUND - IKEA TAMPINES", "58.00 CR"),
        _pad("24 JUN   MCDONALDS HOLLAND VILLAGE", "14.20"),
        "",
        _pad("SUB TOTAL", "2,634.79"),
        _pad("NEW BALANCE", "2,634.79"),
        _pad("MINIMUM PAYMENT", "50.00"),
        "PAYMENT DUE DATE: 15 JUL 2025",
        "",
        "Please examine this statement and report any discrepancy within 14 days.",
        "This is a computer generated statement. No signature is required.",
        "Page 1 of 1",
    ]
    write_pdf(path, [lines])


# ---------------------------------------------------------------------------
# 4. A card PDF with descriptions and amounts only — no transaction dates.
#    The brief allows for this; the app dates these to the statement month.
# ---------------------------------------------------------------------------
def make_dateless_pdf(path: str) -> None:
    lines = [
        "CITIBANK SINGAPORE LIMITED",
        "CITI PREMIERMILES CARD",
        "",
        "Statement Date: 20 JUN 2025",
        "",
        "CARD NO: 4726-XXXX-XXXX-1120",
        "",
        _pad("DESCRIPTION", "AMOUNT (S$)"),
        "",
        _pad("PAYMENT RECEIVED - THANK YOU", "780.00 CR"),
        _pad("GREAT EASTERN LIFE ASSURANCE", "196.40"),
        _pad("STARHUB BROADBAND SERVICES", "49.90"),
        _pad("GOOGLE ONE STORAGE", "3.79"),
        _pad("ANYTIME FITNESS BUKIT TIMAH", "58.00"),
        _pad("COMFORTDELGRO TAXI", "22.50"),
        _pad("SHENG SIONG SUPERMARKET", "74.15"),
        _pad("DELIVEROO SINGAPORE", "27.90"),
        _pad("CRYSTAL JADE KITCHEN", "68.00"),
        _pad("LAZADA SINGAPORE", "154.20"),
        _pad("VIRGIN ACTIVE SINGAPORE", "42.00"),
        _pad("AGODA COM PTE LTD", "318.75"),
        _pad("KLOOK TRAVEL TECHNOLOGY", "96.00"),
        _pad("GUARDIAN HEALTH BEAUTY", "31.60"),
        "",
        _pad("TOTAL AMOUNT DUE", "1,143.19"),
        "Page 1 of 1",
    ]
    write_pdf(path, [lines])


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    make_bank_csv(os.path.join(OUT_DIR, "dbs-multiplier-account-jun2025.csv"))
    make_card_excel(os.path.join(OUT_DIR, "uob-one-card-jun2025.xlsx"))
    make_card_pdf(os.path.join(OUT_DIR, "ocbc-90n-card-jun2025.pdf"))
    make_dateless_pdf(os.path.join(OUT_DIR, "citi-card-nodate-jun2025.pdf"))
    for name in sorted(os.listdir(OUT_DIR)):
        size = os.path.getsize(os.path.join(OUT_DIR, name))
        print(f"  {name}  ({size:,} bytes)")


if __name__ == "__main__":
    main()
