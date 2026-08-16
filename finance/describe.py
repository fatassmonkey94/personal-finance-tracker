"""Turn a raw statement line into a short human description (<= 10 words)."""
from __future__ import annotations

import re

MAX_WORDS = 10

# Merchant strings that should always render as a clean, friendly name.
CANONICAL = [
    (r"FOOD\s*PANDA|FOODPANDA|PANDAMART", "Foodpanda order"),
    (r"GRAB\w*\s*FOOD|GRABFOOD", "GrabFood order"),
    (r"GRAB\w*\s*MART|GRABMART", "GrabMart order"),
    (r"DELIVEROO", "Deliveroo order"),
    (r"GRAB\w*\s*(RIDE|TAXI|CAR|TRANSPORT)|GRABTAXI", "Grab ride"),
    (r"^GRAB(PAY)?\b(?!.*FOOD)", "Grab ride"),
    (r"GOJEK", "Gojek ride"),
    (r"\bTADA\b", "TADA ride"),
    (r"COMFORTDELGRO|COMFORT\s*DELGRO|CDG\s*TAXI", "ComfortDelGro taxi"),
    (r"SIMPLYGO|TRANSITLINK|TRANSIT\s*LINK|EZ[\s-]*LINK|BUS\s*/\s*MRT", "Public transport fare"),
    (r"NETS\s*(FLASHPAY|TOP\s*[\s-]*UP|TOPUP)|FLASHPAY", "NETS FlashPay top-up"),
    (r"\bSHELL\b", "Shell fuel"),
    (r"\bESSO\b", "Esso fuel"),
    (r"\bCALTEX\b", "Caltex fuel"),
    (r"\bSPC\b|SINGAPORE\s*PETROLEUM", "SPC fuel"),
    (r"\bSINOPEC\b", "Sinopec fuel"),
    (r"FAIRPRICE|FAIR\s*PRICE|NTUC", "FairPrice groceries"),
    (r"COLD\s*STORAGE|CS\s*FRESH", "Cold Storage groceries"),
    (r"SHENG\s*SIONG", "Sheng Siong groceries"),
    (r"DON\s*DON\s*DONKI|DONKI", "Don Don Donki shopping"),
    (r"GIANT\s*(HYPER|SUPER|SINGAPORE)?", "Giant groceries"),
    (r"REDMART", "RedMart groceries"),
    (r"\bSPOTIFY\b", "Spotify subscription"),
    (r"\bNETFLIX\b", "Netflix subscription"),
    (r"APPLE\s*COM\s*BILL|ITUNES|APPLE\s*ICLOUD|\bICLOUD\b", "Apple iCloud subscription"),
    (r"GOOGLE\s*(ONE|STORAGE)", "Google One subscription"),
    (r"YOUTUBE\s*PREMIUM|YOUTUBEPREMIUM", "YouTube Premium subscription"),
    (r"DISNEY\s*PLUS|DISNEYPLUS", "Disney+ subscription"),
    (r"OPENAI|CHATGPT", "OpenAI subscription"),
    (r"ANTHROPIC|CLAUDE\s*AI", "Anthropic subscription"),
    (r"ADOBE", "Adobe subscription"),
    (r"MICROSOFT\s*(365|OFFICE)|OFFICE\s*365", "Microsoft 365 subscription"),
    (r"\bSINGTEL\b|SING\s*TEL", "Singtel bill"),
    (r"\bSTARHUB\b|STAR\s*HUB", "StarHub bill"),
    (r"\bM1\b", "M1 mobile bill"),
    (r"CIRCLES\s*(LIFE|ASIA)", "Circles.Life bill"),
    (r"SIMBA|TPG\s*TELECOM", "Simba mobile bill"),
    (r"MYREPUBLIC", "MyRepublic bill"),
    (r"\bYOUTRIP\b|YOU\s*TRIP|YOU\s*TECHNOLOG", "YouTrip top-up"),
    (r"\bWISE\b|TRANSFERWISE", "Wise transfer"),
    (r"\bREVOLUT\b", "Revolut top-up"),
    (r"\bAGODA\b", "Agoda booking"),
    (r"BOOKING\s*COM", "Booking.com reservation"),
    (r"\bAIRBNB\b", "Airbnb stay"),
    (r"\bKLOOK\b", "Klook experience booking"),
    (r"SINGAPORE\s*AIRLINES|\bSIA\b", "Singapore Airlines flight"),
    (r"\bSCOOT\b", "Scoot flight"),
    (r"\bJETSTAR\b", "Jetstar flight"),
    (r"AIR\s*ASIA|AIRASIA", "AirAsia flight"),
    (r"\bSHOPEE\b", "Shopee purchase"),
    (r"\bLAZADA\b", "Lazada purchase"),
    (r"AMAZON\s*WEB\s*SERVICES|\bAWS\b", "AWS cloud subscription"),
    (r"AMAZON|\bAMZN\b", "Amazon purchase"),
    (r"\bUNIQLO\b", "Uniqlo clothing"),
    (r"\bDECATHLON\b", "Decathlon sports gear"),
    (r"\bIKEA\b", "IKEA home goods"),
    (r"\bWATSONS\b", "Watsons personal care"),
    (r"\bGUARDIAN\b", "Guardian pharmacy"),
    (r"\bSEPHORA\b", "Sephora beauty"),
    (r"KOI\s*THE|\bKOI\b", "KOI bubble tea"),
    (r"\bSTARBUCKS\b", "Starbucks coffee"),
    (r"COFFEE\s*BEAN", "Coffee Bean drinks"),
    (r"MCDONALD", "McDonald's meal"),
    (r"\bKFC\b", "KFC meal"),
    (r"BURGER\s*KING", "Burger King meal"),
    (r"DIN\s*TAI\s*FUNG", "Din Tai Fung meal"),
    (r"HAI\s*DI\s*LAO|HAIDILAO", "Haidilao hotpot meal"),
    (r"GOLDEN\s*VILLAGE|\bGV\s*CINEMA", "Golden Village movie"),
    (r"SHAW\s*THEATRE", "Shaw Theatres movie"),
    (r"CATHAY\s*CINE", "Cathay Cineplex movie"),
    (r"CLASSPASS", "ClassPass fitness credits"),
    (r"FITNESS\s*FIRST", "Fitness First membership"),
    (r"ANYTIME\s*FITNESS", "Anytime Fitness membership"),
    (r"VIRGIN\s*ACTIVE", "Virgin Active membership"),
    (r"\bACTIVESG\b", "ActiveSG facility booking"),
    (r"\bAIA\b", "AIA insurance premium"),
    (r"\bPRUDENTIAL\b", "Prudential insurance premium"),
    (r"GREAT\s*EASTERN", "Great Eastern insurance premium"),
    (r"NTUC\s*INCOME|INCOME\s*INSURANCE", "Income insurance premium"),
    (r"\bSINGLIFE\b", "Singlife insurance premium"),
    (r"\bMANULIFE\b", "Manulife insurance premium"),
    (r"PAYMENT\s*(RECEIVED\s*)?[-–]?\s*THANK\s*YOU|THANK\s*YOU\s*FOR\s*YOUR\s*PAYMENT|"
     r"PAYMENT\s*RECEIVED", "Credit card bill payment"),
    (r"CREDIT\s*CARD\s*(BILL\s*)?(PAYMENT|PYMT)", "Credit card bill payment"),
    (r"\bPAYMT\b|PAY(MENT|MT)\s*THRU|E-?BANK\s*/?\s*HOMEB", "Credit card bill payment"),
    (r"\bMONEYSEND\b", "Credit card bill payment"),
    (r"(CCY|CURRENCY)\s*CONVERSION\s*FEE", "Currency conversion fee"),
    (r"\bEZYPAY\b.*ANYTIME\s*FITN|ANYTIME\s*FITN", "Anytime Fitness membership"),
    (r"\bSALARY\b|\bSALA\b|\bPAYROLL\b", "Monthly salary credited"),
    (r"BONUS\s*INTEREST|CREDIT\s*INTEREST|\bINTEREST\s*(EARNED|CREDIT)", "Bank interest earned"),
    (r"\bDIVIDEND\b", "Dividend received"),
    (r"\bCDP\b", "CDP dividend received"),
    (r"SP\s*(SERVICES|GROUP|POWER)", "SP Services utilities bill"),
    (r"\bATM\b|CASH\s*W(ITH)?D(RAWA)?L", "ATM cash withdrawal"),
]

# Noise to strip out of an otherwise-unknown description.
NOISE_PATTERNS = [
    # Bank transaction-type codes that CSV exports put in their own column and
    # we join into the description (DBS: ITR, IBG, MST; OCBC: ICT, AWL; etc).
    r"^\s*(ITR|IBG|ICT|IDT|MST|TFR|TRF|AWL|DDR|SI|GIRO|POS|PIB|IBK|MBK|CDM|FEE|CHG|CHQ|SVC)\b",
    r"\bSINGAPORE\s*SG\b",
    r"\bSG\s*$",
    r"\bSGP\b",
    r"\bPTE\.?\s*LTD\.?\b",
    r"\bPRIVATE\s*LIMITED\b",
    r"\bLIMITED\b",
    r"\bLLP\b",
    r"\bCO\.?\s*$",
    r"\bREF(ERENCE)?\s*[:#]?\s*\w{4,}",
    r"\bTRANS(ACTION)?\s*(REF|NO|ID)\s*[:#]?\s*\w+",
    r"\b[A-Z]{2,4}\d{7,}(-\d+)?\b",   # PIB2605020170225493, IB527202812
    r"\bOTHR\b",
    r"\bPAYNOW[\s-]*FAST\b",
    r"\bINWARD\s*(CR|DR|TRF|CREDIT)\b",
    r"\bTRSF\b",
    r"\bI[\s-]?BANKING\b",
    r"\bVIA\s+(IBANKING|PAYNOW|FAST|MOBILE)\b",
    r"\bXX+[\dX]*\b",
    r"\b\d{6,}\b",
    r"\b[\dX]{4}[-\s]?[\dX]{4}[-\s]?[\dX]{4}[-\s]?\d{4}\b",
    r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b",
    r"[*#|]+",
    r"\s{2,}",
]

_CURRENCY_TAIL = re.compile(
    r"\b(USD|EUR|GBP|AUD|JPY|MYR|THB|IDR|HKD|CNY|KRW|VND|PHP|TWD|NZD|CHF|CAD|INR|AED)\b"
    r"\s*[\d,]*\.?\d*",
    re.IGNORECASE,
)

# Words that add nothing once the merchant is identified.
FILLER = {
    "THE", "AND", "OF", "FOR", "TO", "AT", "ON", "VIA", "BY", "PAYMENT",
    "PURCHASE", "TRANSACTION", "DEBIT", "CREDIT", "CARD", "POS", "SALE",
}


def summarise(raw_description: str, category: str = "", direction: str = "") -> str:
    """Produce a <= 10 word description of the transaction."""
    text = (raw_description or "").strip()
    if not text:
        return "Unlabelled transaction"

    upper = text.upper()

    # 1. Known merchant? Use the curated phrase, plus the payee if it adds info.
    for pattern, label in CANONICAL:
        if re.search(pattern, upper):
            payee = _trailing_payee(upper, pattern)
            if payee:
                return _clip(f"{label} - {payee}")
            return label

    # 2. Otherwise clean up the raw text.
    cleaned = _CURRENCY_TAIL.sub(" ", upper)
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned)
    cleaned = re.sub(r"[^A-Z0-9&'\.\- ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -.")

    words = [w for w in cleaned.split() if w and w not in FILLER]
    if not words:
        words = [w for w in cleaned.split() if w]
    # Joined statement columns often repeat a word ("... SAVINGS SAVINGS").
    words = [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]

    if not words:
        return "Unlabelled transaction"

    phrase = _titlecase(" ".join(words[:MAX_WORDS]))

    # A bare name tells you little — add the category as a hint if there's room.
    if len(phrase.split()) <= 3 and category:
        hint = category.split("(")[0].strip().lower()
        candidate = f"{phrase} ({hint})"
        if len(candidate.split()) <= MAX_WORDS:
            phrase = candidate

    return _clip(phrase)


def _trailing_payee(upper_text: str, matched_pattern: str) -> str:
    """For transfers, keep the counterparty name (e.g. 'PayNow to ALEX TAN')."""
    match = re.search(
        r"\b(?:TO|FROM)\s+([A-Z][A-Z\s'\.\-]{3,30})", upper_text
    )
    if not match:
        return ""
    name = re.sub(r"\s+", " ", match.group(1)).strip(" .-")
    if not name or re.search(matched_pattern, name):
        return ""
    words = name.split()
    if len(words) > 3:
        words = words[:3]
    return _titlecase(" ".join(words))


_KEEP_UPPER = {
    "SG", "SGD", "USD", "NETS", "MRT", "LRT", "ATM", "CPF", "GST", "AIA", "GE",
    "OCBC", "DBS", "UOB", "POSB", "HSBC", "CIMB", "SCB", "AMEX", "KFC", "GV",
    "IKEA", "HDB", "URA", "LTA", "PUB", "SPC", "TCM", "KTV", "IT", "AI", "TV",
    "IBM", "SIA", "M1", "F45", "PS", "BBQ", "AWS", "NTUC", "SMRT", "SBS",
}


def _titlecase(text: str) -> str:
    out = []
    for word in text.split():
        stripped = word.strip(".,'-")
        if stripped in _KEEP_UPPER or (len(stripped) <= 3 and stripped.isalpha() and stripped.isupper()
                                       and stripped in _KEEP_UPPER):
            out.append(stripped)
        elif any(ch.isdigit() for ch in word):
            out.append(word)
        else:
            out.append(word.capitalize())
    return " ".join(out)


def _clip(phrase: str) -> str:
    words = phrase.split()
    if len(words) <= MAX_WORDS:
        return phrase
    return " ".join(words[:MAX_WORDS])
