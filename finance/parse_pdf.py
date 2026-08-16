"""Parse PDF statements (credit card and bank).

Approach: pull text line by line, find the statement period so we know which
year/month applies, then read each line as
    [optional date(s)]  description  [optional foreign ccy + amount]  SGD amount [CR]

Foreign-currency detail often sits on the line below its SGD charge, so
continuation lines are folded into the transaction above them.

Per the brief, a PDF may carry no usable transaction dates at all. When that
happens the statement month is used and `date_is_inferred` is set, so those
rows are visibly flagged instead of silently mis-dated.
"""
from __future__ import annotations

import io
import re
from datetime import date, timedelta
from typing import List, Optional, Tuple

import pdfplumber

from .model import CREDIT, DEBIT, ParsedDocument, Transaction
from .parse_tabular import CURRENCY_CODES, _guess_account, parse_amount, parse_date

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6, "JULY": 7,
    "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

# A date at the start of a line: "18 JUN", "18 JUN 25", "18/06", "2025-06-18".
DATE_TOKEN = (
    r"(?:\d{1,2}\s*(?:%s)\s*\d{0,4}"
    r"|(?:%s)\s*\d{1,2},?\s*\d{0,4}"
    r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
    r"|\d{4}-\d{2}-\d{2})"
) % (_MONTH_ALT, _MONTH_ALT)

LEADING_DATES = re.compile(r"^\s*(%s)(?:\s+(%s))?\s+" % (DATE_TOKEN, DATE_TOKEN), re.IGNORECASE)

# Amount at end of line, optional CR/DR marker.
TRAILING_AMOUNT = re.compile(
    r"(?P<neg>-)?\(?\s*(?P<amount>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})\s*\)?"
    r"\s*(?P<marker>CR|DR|\+|-)?\s*$",
    re.IGNORECASE,
)

# Foreign currency detail, e.g. "USD 25.00" or "25.00 USD".
FOREIGN_DETAIL = re.compile(
    r"\b(?P<ccy>[A-Z]{3})\s*(?P<amt>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})\b"
    r"|(?P<amt2>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})\s*(?P<ccy2>[A-Z]{3})\b"
)

# Lines that are statement furniture, not transactions.
NOISE = re.compile(
    r"^\s*(?:"
    r"statement\s+(of|date|period|summary)|account\s+summary|summary\s+of|"
    r"previous\s+(statement\s+)?balance|opening\s+balance|closing\s+balance|"
    r"balance\s+(b/?f|carried|brought)|sub[\s-]?total|total\s+(debit|credit|amount|balance)|"
    r"grand\s+total|new\s+balance|current\s+balance|balance\s+due|amount\s+due|"
    r"minimum\s+(sum|payment|amount)|payment\s+due\s+date|due\s+date|"
    r"credit\s+limit|available\s+(credit|limit|balance)|cash\s+(limit|advance\s+limit)|"
    r"page\s+\d+|\d+\s+of\s+\d+\s*$|"
    r"co\.?\s*reg|gst\s+reg|swift|bic\b|"
    r"important\s+(notice|information)|please\s+(note|examine|pay)|"
    r"terms\s+and\s+conditions|for\s+enquir|customer\s+service|"
    r"this\s+is\s+a\s+computer|do\s+not\s+reply|"
    r"transaction\s+date|posting\s+date|value\s+date|description\s+of\s+transaction|"
    r"date\s+description|details\s+amount|withdrawal.*deposit|"
    r"interest\s+rate|annual\s+fee\s+waiver|reward\s+points\s+summary|"
    r"points\s+(balance|earned|expiring)|miles\s+(balance|earned)|"
    r"total\s+points|your\s+(card|account)\s+ending|card\s+number|"
    r"outstanding\s+balance|instalment\s+(summary|plan\s+summary)|"
    r"sub\s+total|subtotal"
    r")",
    re.IGNORECASE,
)

# Statement furniture that can sit mid-line, so it cannot be anchored to the
# start like NOISE is. Citi puts "#04-76 Total Minimum Payment $50.00" on one
# line, where the address and the summary field share a row.
NOISE_ANYWHERE = re.compile(
    r"(minimum\s+payment|payment\s+due\s+date|credit\s+limit|current\s+balance|"
    r"total\s+for\s+the\s+card|grand\s+total|sub[\s-]?total|"
    r"previous\s+statement|statement\s+date|available\s+credit|"
    r"points\s+available|reward\s+programme|interest\s+rate|"
    r"balance\s+past\s+due|total\s+points|"
    # A bare 14-19 digit run is a full account number, which only appears on
    # payment slips and summary blocks — never in a purchase description.
    r"\b\d{14,19}\b)",
    re.IGNORECASE,
)

# A line that is only a masked card number belongs to the charge above it and is
# not a description tail: "XXXX-XXXX-XXXX-1234".
MASKED_CARD_ONLY = re.compile(
    r"^[\dX\*\s\-]{8,25}$", re.IGNORECASE,
)

# Citi spells the currency out instead of using an ISO code:
# "FOREIGN AMOUNT U.S. DOLLAR 69.99".
FOREIGN_AMOUNT_LINE = re.compile(
    r"(?:foreign|original|overseas)\s+amount\b(?P<name>[^\d]*?)"
    r"(?P<amt>\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})\s*$",
    re.IGNORECASE,
)

CURRENCY_NAMES = {
    "US DOLLAR": "USD", "U.S. DOLLAR": "USD", "USDOLLAR": "USD",
    "UNITED STATES DOLLAR": "USD", "US DOLLARS": "USD",
    "EURO": "EUR", "EUROS": "EUR",
    "POUND STERLING": "GBP", "BRITISH POUND": "GBP", "STERLING": "GBP",
    "JAPANESE YEN": "JPY", "YEN": "JPY",
    "AUSTRALIAN DOLLAR": "AUD", "NEW ZEALAND DOLLAR": "NZD",
    "HONG KONG DOLLAR": "HKD", "MALAYSIAN RINGGIT": "MYR", "RINGGIT": "MYR",
    "THAI BAHT": "THB", "BAHT": "THB", "CHINESE YUAN": "CNY",
    "CHINESE RENMINBI": "CNY", "RENMINBI": "CNY", "YUAN": "CNY",
    "INDONESIAN RUPIAH": "IDR", "RUPIAH": "IDR", "KOREAN WON": "KRW",
    "WON": "KRW", "SWISS FRANC": "CHF", "CANADIAN DOLLAR": "CAD",
    "INDIAN RUPEE": "INR", "RUPEE": "INR", "TAIWAN DOLLAR": "TWD",
    "VIETNAMESE DONG": "VND", "DONG": "VND", "PHILIPPINE PESO": "PHP",
    "UAE DIRHAM": "AED", "DIRHAM": "AED",
}


# Headers that name whose card a block of transactions belongs to.
CARDHOLDER = re.compile(
    r"(?:card\s*(?:no\.?|number)?\s*[:\-]?\s*)?"
    r"((?:\d{4}[\s-]?){1,3}(?:\d{4}|[X\*]{4}))",
    re.IGNORECASE,
)

STATEMENT_PERIOD = re.compile(
    r"(?:statement\s+period|period|for\s+the\s+period|from)\D{0,15}"
    r"(\d{1,2}\s*(?:%s)\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    r"\s*(?:to|[-–—])\s*"
    r"(\d{1,2}\s*(?:%s)\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})" % (_MONTH_ALT, _MONTH_ALT),
    re.IGNORECASE,
)
STATEMENT_DATE = re.compile(
    r"statement\s+date\D{0,15}(\d{1,2}\s*(?:%s)\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:%s)\s+\d{1,2},?\s*\d{4})" % (_MONTH_ALT, _MONTH_ALT),
    re.IGNORECASE,
)
MONTH_YEAR = re.compile(r"\b(%s)\s+(20\d{2})\b" % _MONTH_ALT, re.IGNORECASE)

CREDIT_WORDS = re.compile(
    r"payment\s*[-–]?\s*thank\s*you|thank\s*you\s*for\s*your\s*payment|"
    r"\brefund\b|\breversal\b|\brebate\b|\bcashback\b|\bcash\s*back\b|"
    r"\bcredit\s*adjustment\b|\bpayment\s*received\b|\breversed\b|"
    r"\bsalary\b|\bsala\b|\bpayroll\b|\bdividend\b|\binterest\s*(earned|credit)\b|"
    r"\bdeposit\b|\bincoming\b|\bgiro\s*(salary|credit)\b|\btransfer\s*from\b",
    re.IGNORECASE,
)


def parse_pdf(data: bytes, filename: str, account_hint: str = "",
              fallback_month: Optional[str] = None,
              password: Optional[str] = None) -> ParsedDocument:
    doc = ParsedDocument(
        filename=filename,
        account=account_hint or _guess_account(filename),
        doc_type="pdf",
    )

    try:
        kwargs = {"password": password} if password else {}
        with pdfplumber.open(io.BytesIO(data), **kwargs) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
                pages.append(text)
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "password" in msg.lower() or "encrypt" in msg.lower():
            doc.warnings.append(
                f"{filename} is password protected. Supply the password in the "
                f"sidebar, or save an unlocked copy and re-upload."
            )
        else:
            doc.warnings.append(f"Could not read {filename}: {exc}")
        return doc

    full_text = "\n".join(pages)
    if not full_text.strip():
        doc.warnings.append(
            f"{filename} has no extractable text — it is probably a scan. "
            f"Run OCR on it, or export the statement as CSV instead."
        )
        return doc

    period_start, period_end = _detect_period(full_text)
    anchor = period_end or period_start
    if anchor:
        doc.statement_month = anchor.strftime("%Y-%m")
        doc.notes.append(
            f"Statement period detected: "
            f"{period_start.isoformat() if period_start else '?'} to "
            f"{period_end.isoformat() if period_end else '?'}"
        )
    elif fallback_month:
        doc.statement_month = fallback_month
        doc.notes.append(f"No statement period found; using {fallback_month} as the month.")

    default_year = anchor.year if anchor else None
    fallback_date = _fallback_date(doc.statement_month, period_end)

    current_account = doc.account
    pending: Optional[Transaction] = None

    for page_no, page_text in enumerate(pages, start=1):
        for raw_line in page_text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line or len(line) < 4:
                continue

            # A card-number header switches which card the rows belong to.
            card_label = _cardholder_label(line, doc.account)
            if card_label:
                current_account = card_label
                pending = None
                continue

            if NOISE.search(line) or NOISE_ANYWHERE.search(line):
                pending = None
                continue

            # A bare masked card number annotates the charge above it.
            if MASKED_CARD_ONLY.match(line):
                continue

            # "FOREIGN AMOUNT U.S. DOLLAR 69.99" — the currency is spelled out,
            # so there is no ISO code for _foreign_detail to find. Without this
            # the 69.99 would be booked as a second, phantom transaction.
            named = FOREIGN_AMOUNT_LINE.match(line)
            if named:
                code = _currency_from_name(named.group("name"))
                if pending is not None:
                    pending.original_currency = code or "FX"
                    try:
                        pending.original_amount = float(
                            named.group("amt").replace(",", ""))
                    except ValueError:
                        pass
                continue

            # "USD 25.00 EXCHANGE RATE 1.3500" carries the foreign-currency
            # detail for the charge above it. Catch it before anything else: the
            # trailing figure is an FX rate, not a transaction amount, and the
            # line must not be glued onto the description either.
            if pending is not None and not LEADING_DATES.match(line):
                fx = _foreign_detail(line)
                if fx and _is_fx_only(FOREIGN_DETAIL.sub(" ", line.upper()), fx[0]):
                    pending.original_currency, pending.original_amount = fx
                    continue

            amount_match = TRAILING_AMOUNT.search(line)
            if not amount_match:
                # No amount: could be the tail of a wrapped description.
                if pending is not None and _is_description_tail(line):
                    pending.raw_description = (pending.raw_description + " " + line).strip()
                continue

            head = line[: amount_match.start()].strip()
            amount = float(amount_match.group("amount").replace(",", ""))
            marker = (amount_match.group("marker") or "").upper()
            is_negative = bool(amount_match.group("neg")) or ("(" in line and ")" in line)

            date_match = LEADING_DATES.match(line)
            txn_date = None
            inferred = False
            if date_match:
                txn_date = _to_date(date_match.group(1), default_year)
                if txn_date is None and date_match.group(2):
                    txn_date = _to_date(date_match.group(2), default_year)
                head = line[date_match.end(): amount_match.start()].strip()

            if txn_date is None:
                txn_date = fallback_date
                inferred = True

            description = head.strip(" .-|")
            # Strip any foreign-currency detail that shares the line.
            fx_inline = _foreign_detail(description)
            original_currency, original_amount = ("SGD", None)
            if fx_inline:
                original_currency, original_amount = fx_inline
                description = FOREIGN_DETAIL.sub(" ", description)
                description = re.sub(r"\s+", " ", description).strip(" .-|")

            if not description or len(re.sub(r"[^A-Za-z]", "", description)) < 2:
                doc.skipped_lines.append(f"p{page_no}: {line[:80]}")
                pending = None
                continue
            if amount == 0:
                continue
            if _looks_like_running_balance(description):
                pending = None
                continue

            direction = DEBIT
            if marker == "CR" or is_negative or CREDIT_WORDS.search(description):
                direction = CREDIT
            if marker == "DR":
                direction = DEBIT

            if txn_date is None:
                doc.skipped_lines.append(f"p{page_no} (no date): {line[:80]}")
                continue

            # Keep the statement period honest: a "18 JAN" line on a December
            # statement is January of the following year.
            txn_date = _snap_into_period(txn_date, period_start, period_end)

            txn = Transaction(
                date=txn_date,
                description="",
                raw_description=description,
                amount_sgd=round(amount, 2),
                direction=direction,
                source_account=current_account,
                source_file=filename,
                original_currency=original_currency,
                original_amount=original_amount,
                date_is_inferred=inferred,
                # An inferred date is flagged in its own column, not in the review
                # queue — that queue is for uncertain *categorisation*.
                review_note=(
                    "No transaction date on this PDF line — dated to the statement "
                    "period end. Adjust if you need the exact day."
                ) if inferred else "",
            )
            doc.transactions.append(txn)
            pending = txn

    if not doc.transactions:
        doc.warnings.append(
            f"{filename}: text extracted but no transaction lines recognised. "
            f"Check the 'Unparsed lines' expander to see what was skipped."
        )
    return doc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_date(token: str, default_year: Optional[int]) -> Optional[date]:
    token = token.strip()
    match = re.match(r"^(\d{1,2})\s*(%s)\s*(\d{2,4})?$" % _MONTH_ALT, token, re.IGNORECASE)
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2).upper()]
        year = _resolve_year(match.group(3), default_year)
        return _safe_date(year, month, day)
    match = re.match(r"^(%s)\s*(\d{1,2}),?\s*(\d{2,4})?$" % _MONTH_ALT, token, re.IGNORECASE)
    if match:
        month = MONTHS[match.group(1).upper()]
        day = int(match.group(2))
        year = _resolve_year(match.group(3), default_year)
        return _safe_date(year, month, day)
    return parse_date(token, default_year)


def _resolve_year(raw: Optional[str], default_year: Optional[int]) -> int:
    if raw:
        value = int(raw)
        if value < 100:
            value += 2000
        return value
    return default_year or date.today().year


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _detect_period(text: str) -> Tuple[Optional[date], Optional[date]]:
    match = STATEMENT_PERIOD.search(text)
    if match:
        start = parse_date(match.group(1)) or _to_date(match.group(1), None)
        end = parse_date(match.group(2)) or _to_date(match.group(2), None)
        if start and end and start <= end:
            return start, end

    match = STATEMENT_DATE.search(text)
    if match:
        end = parse_date(match.group(1)) or _to_date(match.group(1), None)
        if end:
            # Card statements close mid-month; the cycle is roughly the prior month.
            start = (end.replace(day=1) - timedelta(days=1)).replace(day=1)
            return start, end

    match = MONTH_YEAR.search(text)
    if match:
        month = MONTHS[match.group(1).upper()]
        year = int(match.group(2))
        start = _safe_date(year, month, 1)
        end = _month_end(year, month)
        return start, end
    return None, None


def _month_end(year: int, month: int) -> Optional[date]:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return nxt - timedelta(days=1)


def _fallback_date(statement_month: Optional[str], period_end: Optional[date]) -> Optional[date]:
    """Where to date a line that has no date of its own."""
    if period_end:
        return period_end
    if statement_month:
        try:
            year, month = (int(p) for p in statement_month.split("-"))
            return _month_end(year, month)
        except ValueError:
            return None
    return None


def _snap_into_period(txn_date: date, start: Optional[date], end: Optional[date]) -> date:
    if not start or not end:
        return txn_date
    if start <= txn_date <= end:
        return txn_date
    for shift in (-1, 1):
        try:
            candidate = txn_date.replace(year=txn_date.year + shift)
        except ValueError:
            continue
        if start <= candidate <= end:
            return candidate
    return txn_date


def _foreign_detail(text: str) -> Optional[Tuple[str, float]]:
    for match in FOREIGN_DETAIL.finditer(text.upper()):
        ccy = match.group("ccy") or match.group("ccy2")
        amt = match.group("amt") or match.group("amt2")
        if ccy in CURRENCY_CODES and ccy != "SGD" and amt:
            try:
                return ccy, float(amt.replace(",", ""))
            except ValueError:
                continue
    return None


def _is_fx_only(head: str, ccy: str) -> bool:
    """True if the line carries only exchange detail, not a new merchant."""
    residue = re.sub(r"(?i)\b(%s|exchange\s*rate|rate|foreign\s*currency|"
                     r"conversion|amount|fx|at)\b" % ccy, " ", head)
    residue = re.sub(r"[\d.,%\s\-@/]", "", residue)
    return len(residue) <= 3


_TAIL_OK = re.compile(r"^[A-Za-z][A-Za-z0-9 &'.,\-/]{2,}$")


def _letters(text: str) -> str:
    return re.sub(r"[^A-Z]", "", (text or "").upper())


# Compare on letters only, so "U.S. DOLLAR", "US DOLLAR" and "USDOLLAR" all
# reduce to the same key.
_CURRENCY_NAMES_FLAT = {_letters(name): code for name, code in CURRENCY_NAMES.items()}


def _currency_from_name(text: str) -> Optional[str]:
    """'U.S. DOLLAR' -> 'USD'. Returns None if the name isn't recognised."""
    flat = _letters(text)
    if not flat:
        return None
    if flat in _CURRENCY_NAMES_FLAT:
        return _CURRENCY_NAMES_FLAT[flat]
    if flat in CURRENCY_CODES:
        return flat
    # Longest name first, so "US DOLLAR" is not shadowed by "DOLLAR".
    for name in sorted(_CURRENCY_NAMES_FLAT, key=len, reverse=True):
        if name in flat:
            return _CURRENCY_NAMES_FLAT[name]
    return None


def _is_description_tail(line: str) -> bool:
    if NOISE.search(line) or NOISE_ANYWHERE.search(line) or LEADING_DATES.match(line):
        return False
    if MASKED_CARD_ONLY.match(line):
        return False
    if re.search(r"exchange\s*rate|conversion\s*rate|\bfx\s*rate\b|"
                 r"(foreign|original|overseas)\s+amount", line, re.IGNORECASE):
        return False
    return bool(_TAIL_OK.match(line)) and len(line) <= 60


def _looks_like_running_balance(description: str) -> bool:
    return bool(re.match(r"^(bal|balance|b/?f|c/?f)\b", description.strip(), re.IGNORECASE))


def _cardholder_label(line: str, base_account: str) -> Optional[str]:
    """Detect 'CARD NO: 4xxx-xxxx-xxxx-1234' style block headers."""
    if not re.search(r"card\s*(no\.?|number)|ending", line, re.IGNORECASE):
        return None
    match = CARDHOLDER.search(line)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    if len(digits) < 4:
        return None
    return f"{base_account} ••{digits[-4:]}"
