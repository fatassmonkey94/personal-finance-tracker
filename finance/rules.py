"""Keyword rule engine that maps a raw statement description to a category.

Rules are ordered: the first match wins. That ordering matters — "GRABFOOD"
must be tested before "GRAB", and the parents' names before generic PayNow.

Everything here is deterministic and inspectable. `rule_matched` on each
transaction records which rule fired so you can audit any categorisation.
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional, Tuple

from .model import (
    CAT_ADDITIONAL_INCOME,
    CAT_CARD_PAYMENT,
    CAT_EXPERIENCES,
    CAT_FOOD,
    CAT_GROCERIES,
    CAT_INSURANCE,
    CAT_INTERNAL_TRANSFER,
    CAT_PARENTS,
    CAT_SALARY,
    CAT_SHOPPING,
    CAT_SUBSCRIPTIONS,
    CAT_TAX,
    CAT_TELCO,
    CAT_TRANSPORT_CAB,
    CAT_TRANSPORT_CAR,
    CAT_TRANSPORT_PUBLIC,
    CAT_UNCATEGORISED,
    CAT_UNCLASSIFIED_TRANSFER,
    migrate_category,
    CREDIT,
    DEBIT,
)

# Names that identify an allowance transfer to parents. Deliberately empty in
# source: these are real people. Set them in the sidebar, or keep them in the
# gitignored data/parent_names.txt so they persist without being committed.
DEFAULT_PARENT_NAMES: List[str] = []

# A rule is (name, regex, category, applies_to_direction or None)
Rule = Tuple[str, str, str, Optional[str]]


def _alt(*words: str) -> str:
    """Build an alternation that tolerates spaces/dots/hyphens inside names.

    Note: escape each word *token* separately. `re.escape` escapes spaces too,
    so escaping the whole phrase first and then substituting the whitespace
    leaves the backslash behind and turns "CIRCLES LIFE" into a pattern that
    demands a literal "[" — silently matching nothing.

    Alternatives are fenced with alphanumeric lookarounds so "SIA" does not fire
    inside "MALAYSIA", while still allowing "AMAZON SG" to match "AMAZON.SG".
    """
    parts = []
    for word in words:
        tokens = [re.escape(t) for t in word.upper().split()]
        if not tokens:
            continue
        core = r"[\s.\-_/*]*".join(tokens)
        stripped = word.strip()
        prefix = r"(?<![A-Z0-9])" if stripped[:1].isalnum() else ""
        suffix = r"(?![A-Z0-9])" if stripped[-1:].isalnum() else ""
        parts.append(prefix + core + suffix)
    return "(?:" + "|".join(parts) + ")"


# ---------------------------------------------------------------------------
# Rules, highest priority first.
# ---------------------------------------------------------------------------
def build_rules(parent_names: Optional[List[str]] = None,
                employer_keywords: Optional[List[str]] = None) -> List[Rule]:
    parents = [p.strip().upper() for p in (parent_names or DEFAULT_PARENT_NAMES) if p.strip()]
    employers = [e.strip().upper() for e in (employer_keywords or []) if e.strip()]

    rules: List[Rule] = []

    # -- Excluded: money moving between your own pockets ---------------------
    rules += [
        ("card-bill-payment", r"(PAYMENT\s*[-–]?\s*THANK\s*YOU|THANK\s*YOU\s*FOR\s*YOUR\s*PAYMENT|"
                              r"PYMT\s*(RECEIVED|THANK)|PAYMENT\s*RECEIVED|"
                              r"\bPAYMT\b|PAY(MENT|MT)\s*THRU|\bMONEYSEND\b|"
                              r"E-?BANK\s*/?\s*HOMEB)", CAT_CARD_PAYMENT, None),
        # UOB internet banking writes card bills as "Bill payment mBK-Citi CC"
        # or "Card payment mBK-UOB Cards", so match a bill payment aimed at any
        # issuer or at something calling itself a card.
        ("card-bill-payment-bank", r"(CREDIT\s*CARD\s*(BILL\s*)?(PAYMENT|PYMT)|CARD\s*PAYMENT|"
                                   r"\bCCPAY\b|BILL\s*PAYMENT\s*TO\s*(VISA|MASTERCARD|AMEX)|"
                                   r"AUTO[\s-]*DEBIT\s*CARD|"
                                   r"BILL\s*PAY(MENT)?\b.*\b(CC|CARDS?)\b|"
                                   r"\bM?BK\s*[-–]\s*(CITI|UOB|DBS|POSB|OCBC|HSBC|SCB|AMEX|"
                                   r"MAYBANK|CIMB|STANDARD\s*CHARTERED)\b)",
         CAT_CARD_PAYMENT, DEBIT),
        ("internal-transfer", r"(FUNDS?\s*TRANSFER\s*TO\s*OWN|OWN\s*ACCOUNT|"
                              r"TRANSFER\s*(TO|FROM)\s*(MY\s*)?(SAVINGS|CURRENT|MULTIPLIER|360)|"
                              r"\bIBFT\s*OWN\b|SELF\s*TRANSFER)", CAT_INTERNAL_TRANSFER, None),
    ]

    # -- Revenue ------------------------------------------------------------
    if employers:
        rules.append(("salary-employer", _alt(*employers), CAT_SALARY, CREDIT))
    rules += [
        ("salary", r"(\bSALARY\b|\bSALA\b|\bPAYROLL\b|\bGIRO\s*[-–]?\s*SALA|"
                   r"\bSAL\s*CREDIT\b|MONTHLY\s*SALARY|\bWAGES\b|\bPAYROL\b)", CAT_SALARY, CREDIT),
        ("bonus", r"(\bBONUS\s*PAY|13TH\s*MONTH|\bAWS\b)", CAT_SALARY, CREDIT),
        ("interest", r"(\bINTEREST\b|\bINT\s*CREDIT\b|BONUS\s*INT\b|CREDIT\s*INT\b|"
                     r"\bINT\s*EARNED\b|\bINTT\b)", CAT_ADDITIONAL_INCOME, CREDIT),
        # Only an explicit payout counts as income here. The platform names are
        # deliberately absent: a credit from a broker or exchange is usually your
        # own capital coming back, and `investment-platform` below handles it.
        ("dividend", r"(\bDIVIDEND|\bDIV\b|\bCDP\b|CENTRAL\s*DEPOSITORY|\bSGX\b|"
                     r"\bCOUPON\s*PAY|\bDISTRIBUTION\b|SSB\s*INTEREST|"
                     r"SINGAPORE\s*SAVINGS\s*BOND|\bT[\s-]?BILL)",
         CAT_ADDITIONAL_INCOME, CREDIT),
        ("cashback-rebate", r"(\bCASHBACK\b|\bCASH\s*BACK\b|\bREBATE\b|\bREWARD\s*CREDIT\b|"
                            r"\bMILES\s*REDEMPTION\b)", CAT_ADDITIONAL_INCOME, CREDIT),
        ("govt-payout", r"(GOVT?\s*PAYOUT|GST\s*VOUCHER|\bCDC\s*VOUCHER|ASSURANCE\s*PACKAGE|"
                        r"\bIRAS\b\s*REFUND|\bSKILLSFUTURE\b)", CAT_ADDITIONAL_INCOME, CREDIT),
    ]

    # -- Fixed: allowance to parents (before generic transfer rules) ---------
    if parents:
        rules.append(("parents-allowance", _alt(*parents), CAT_PARENTS, None))
    rules.append(
        ("parents-keyword", r"(ALLOWANCE\s*(TO\s*)?(PARENT|MUM|MOM|DAD|MOTHER|FATHER)|"
                            r"PARENTS?\s*ALLOWANCE)", CAT_PARENTS, DEBIT)
    )

    # -- Fixed: insurance ---------------------------------------------------
    rules.append((
        "insurance",
        r"(" + _alt(
            "AIA", "PRUDENTIAL", "GREAT EASTERN", "NTUC INCOME", "INCOME INSURANCE",
            "MANULIFE", "SINGLIFE", "AVIVA", "ETIQA", "TOKIO MARINE", "MSIG",
            "CHUBB", "ALLIANZ", "TRANSAMERICA", "HSBC LIFE", "FWD INSURANCE",
            "FWD SINGAPORE", "RAFFLES HEALTH INSURANCE", "AXA INSURANCE",
            "QBE INSURANCE", "DIRECT ASIA", "BUDGET DIRECT", "SOMPO", "LIBERTY INSURANCE",
        ) + r"|\bINSURANCE\b|\bINSURNCE\b|\bLIFE\s*ASSURANCE\b|\bPREMIUM\s*PAYMENT\b|"
        r"\bPOLICY\s*(NO|PREMIUM)\b|\bINTEGRATED\s*SHIELD\b|\bGE\s*LIFE\b)",
        CAT_INSURANCE, DEBIT,
    ))

    # -- Fixed: telco -------------------------------------------------------
    rules.append((
        "telco",
        r"(" + _alt(
            "SINGTEL", "SING TEL", "STARHUB", "STAR HUB", "M1 LIMITED", "M1 SINGAPORE",
            "CIRCLES LIFE", "CIRCLES ASIA", "MYREPUBLIC", "SIMBA TELECOM", "TPG TELECOM",
            "GIGA", "REDONE", "VIEWQWEST", "GOMO", "ZERO MOBILE", "WHIZ COMMS",
            "CHANGI BROADBAND", "GEENET", "ZERO1", "EIGHT TELECOM",
        ) + r"|\bM1\b|\bTELCO\b|\bTELECOM\b|\bMOBILE\s*BILL\b|\bBROADBAND\b|"
        r"\bFIBRE\s*BROADBAND\b|\bMOBILE\s*PLAN\b)",
        CAT_TELCO, DEBIT,
    ))

    # -- Fixed: subscriptions (incl. gym memberships) -----------------------
    rules.append((
        "subscriptions",
        r"(" + _alt(
            "SPOTIFY", "NETFLIX", "APPLE COM BILL", "APPLE ICLOUD", "ICLOUD",
            "ITUNES", "APPLE MUSIC", "APPLE TV", "APPLE ONE", "GOOGLE STORAGE",
            "GOOGLE ONE", "GOOGLE YOUTUBE", "YOUTUBE PREMIUM", "YOUTUBEPREMIUM",
            "DISNEY PLUS", "DISNEYPLUS", "HBO", "MAX COM", "AMAZON PRIME",
            "PRIME VIDEO", "VIU", "MEWATCH", "CRUNCHYROLL", "AUDIBLE", "KINDLE UNLIMITED",
            "AMAZON WEB SERVICES", "ADOBE", "MICROSOFT 365", "MICROSOFT OFFICE", "OFFICE 365", "DROPBOX",
            "NOTION", "EVERNOTE", "CANVA", "FIGMA", "GITHUB", "OPENAI", "CHATGPT",
            "ANTHROPIC", "CLAUDE AI", "MIDJOURNEY", "PERPLEXITY", "GRAMMARLY",
            "LINKEDIN PREMIUM", "MEDIUM COM", "SUBSTACK", "NYTIMES", "STRAITS TIMES",
            "BUSINESS TIMES", "THE ECONOMIST", "FINANCIAL TIMES", "WSJ",
            "FITNESS FIRST", "ANYTIME FITNESS", "VIRGIN ACTIVE", "PURE FITNESS",
            "GYMMBOXX", "F45", "ACTIVESG", "TRUE FITNESS", "GOLDS GYM", "ULTIMATE PERFORMANCE",
            "EZYPAY", "GYM MEMBERSHIP", "CLUB MEMBERSHIP", "STRAVA", "MYFITNESSPAL", "WHOOP",
            "PLAYSTATION PLUS", "NINTENDO SWITCH ONLINE", "XBOX GAME PASS", "STEAM SUBSCRIPTION",
            "NORDVPN", "EXPRESSVPN", "1PASSWORD", "LASTPASS", "BACKBLAZE",
        ) + r"|\bSUBSCRIPTION\b|\bMONTHLY\s*PLAN\b|\bMEMBERSHIP\s*FEE\b|\bANNUAL\s*FEE\b|"
        r"\bANYTIME\s*FITN|\bFITNESS\s*FIRS|\bVIRGIN\s*ACTIV)",
        CAT_SUBSCRIPTIONS, DEBIT,
    ))

    # -- Variable: food delivery (BEFORE transport, so GrabFood != Grab ride)
    rules.append((
        "food-delivery",
        r"(" + _alt(
            "FOODPANDA", "FOOD PANDA", "PANDAMART", "GRABFOOD", "GRAB FOOD",
            "DELIVEROO", "ODDLE", "WHYQ", "CHOPE DELIVERY", "GRABMART", "GRAB MART",
            "DELIVERY HERO", "SHOPEEFOOD", "SHOPEE FOOD", "LALAMOVE FOOD",
        ) + r"|GRAB\w*\s*FOOD|\bFOOD\s*DELIVERY\b)",
        CAT_FOOD, DEBIT,
    ))

    # -- Variable: travel (before transport: airlines/hotels are not commuting)
    rules.append((
        "travel",
        r"(" + _alt(
            # YouTrip tops up under its corporate name, "YOU TECHNOLOGIES GROUP",
            # which bank exports then truncate — hence the stem match below.
            "YOUTRIP", "YOU TRIP", "YTP",
            "WISE PAYMENTS", "TRANSFERWISE", "REVOLUT",
            "AGODA", "BOOKING COM", "BOOKINGCOM", "AIRBNB", "EXPEDIA", "HOTELS COM",
            "TRIP COM", "TRIPCOM", "CTRIP", "TRAVELOKA", "KAYAK", "SKYSCANNER",
            "SINGAPORE AIRLINES", "SIA ", "SCOOT", "JETSTAR", "AIRASIA", "AIR ASIA",
            "EMIRATES", "QATAR AIRWAYS", "CATHAY PACIFIC", "MALAYSIA AIRLINES",
            "GARUDA", "THAI AIRWAYS", "VIETJET", "CEBU PACIFIC", "ANA ", "JAL ",
            "KOREAN AIR", "EVA AIR", "CHINA AIRLINES", "TURKISH AIRLINES", "LUFTHANSA",
            "BRITISH AIRWAYS", "KLM", "AIR FRANCE", "UNITED AIRLINES", "DELTA AIR",
            "MARRIOTT", "HILTON", "HYATT", "SHANGRI LA", "IHG", "HOLIDAY INN",
            "ACCOR", "NOVOTEL", "IBIS ", "FOUR SEASONS", "RITZ CARLTON", "BANYAN TREE",
            "CAPELLA", "PAN PACIFIC", "MANDARIN ORIENTAL", "SWISSOTEL", "FAIRMONT",
            "CHANGI AIRPORT", "JEWEL CHANGI", "ICHANGI", "DFS ", "DUTY FREE",
            "KLOOK", "GETYOURGUIDE", "VIATOR", "TRAVEL INSURANCE", "VISA APPLICATION",
            "ICA SINGAPORE", "PASSPORT", "SEA LIMITED TRAVEL", "TRIPADVISOR",
        ) + r"|\bHOTEL\b|\bRESORT\b|\bHOSTEL\b|\bAIRLINE\b|\bAIRWAYS\b|\bFLIGHT\b|"
        r"\bBOARDING\b|\bFOREX\b|\bMONEY\s*CHANGER\b|"
        # Stem, not whole word: exports truncate "YOU TECHNOLOGIES GROUP".
        r"\bYOU\s*TECHNOLOG)",
        CAT_EXPERIENCES, DEBIT,
    ))

    # -- Excluded: money moving to or from your own investment accounts ------
    # Buying investments is not an expense and withdrawing is not income, so
    # these belong outside the statement. An actual dividend or interest payout
    # says so in the description and is matched by the rules above this one.
    rules.append((
        "investment-platform",
        r"(" + _alt(
            "IBKR", "INTERACTIVE BROKERS", "TIGER BROKERS", "MOOMOO", "FUTU",
            "SAXO", "PHILLIP SECURITIES", "POEMS", "DBS VICKERS", "FSMONE",
            "ENDOWUS", "SYFE", "STASHAWAY", "AUTOWEALTH", "MOOMOO SG",
            "OKX", "BINANCE", "COINBASE", "COINHAKO", "CRYPTO COM", "KRAKEN",
            "BYBIT", "GEMINI TRUST", "INDEPENDENT RESERVE", "GATE IO", "KUCOIN",
            "LUNO", "BITSTAMP", "UPBIT", "TOKENIZE", "SPARROW EXCHANGE",
        # Bank exports truncate long payee names ("INTERACTIVE BR SG-"), so also
        # match the prefixes rather than only the full names.
        ) + r"|\bINTERACTIVE\s*BR|\bTIGER\s*BROK|\bPHILLIP\s*SEC|\bCRYPTO\s*\.?\s*COM\b|"
        r"\bBROKERAGE\b|\bSECURITIES\s*ACCOUNT\b)",
        CAT_INTERNAL_TRANSFER, None,
    ))

    # -- Variable: transport, in three lines -------------------------------
    # Cabs first: a ride-hailing app is a named brand, and the car and public
    # lists below carry generic words ("SERVICING", "BUS") that a brand name
    # could otherwise collide with.
    rules.append((
        "transport-cab",
        r"(" + _alt(
            "GRAB", "GRABPAY RIDE", "GRABTAXI", "GOJEK", "TADA", "RYDE", "ZIG",
            "COMFORTDELGRO", "COMFORT DELGRO", "CDG TAXI", "TRANS CAB", "PREMIER TAXI",
            "PRIME TAXI", "STRIDES", "SMRT TAXI", "UBER",
        ) + r")",
        CAT_TRANSPORT_CAB, DEBIT,
    ))

    # Running a car: fuel, servicing, parking, and the road charges that only a
    # car owner pays. Car-sharing sits here rather than with cabs — you are
    # driving it yourself, and it is priced like a rental, not a fare.
    rules.append((
        "transport-car",
        r"(" + _alt(
            "VICOM", "MOTORIST SG", "CARRO", "GETGO", "BLUESG", "TRIBECAR", "SHARIOT",
            "SHELL", "ESSO", "CALTEX", "SINOPEC", "SPC ", "SINGAPORE PETROLEUM",
            "PETROL", "FUEL", "TYRE", "TYRES", "MOTOR WORKSHOP", "AUTO WORKSHOP",
            "CAR WORKSHOP", "AUTOMOBILE", "SERVICING", "CAR SERVICING", "CARPARK",
            "CAR PARK", "PARKING", "HDB PARKING", "URA PARKING", "WILSON PARKING",
            "EPS PARKING", "SEASON PARKING", "ERP ", "COE ", "ROAD TAX",
            "LTA ", "ONE MOTORING", "CAR INSURANCE", "WORKSHOP",
        ) + r")",
        CAT_TRANSPORT_CAR, DEBIT,
    ))

    rules.append((
        "transport-public",
        r"(" + _alt(
            "SMRT", "SBS TRANSIT", "TRANSITLINK", "TRANSIT LINK", "SIMPLYGO",
            "EZ LINK", "EZLINK", "NETS FLASHPAY", "NETS TOPUP", "NETS TOP UP",
            "FLASHPAY", "CONCESSION", "BUS SERVICE",
        ) + r"|\bTOP[\s-]*UP\s*NETS\b)",
        CAT_TRANSPORT_PUBLIC, DEBIT,
    ))

    # -- Variable: groceries (before dining: FairPrice is not a restaurant) --
    rules.append((
        "groceries",
        r"(" + _alt(
            "FAIRPRICE", "FAIR PRICE", "NTUC", "CHEERS", "COLD STORAGE", "CS FRESH",
            "GIANT", "SHENG SIONG", "PRIME SUPERMARKET", "DON DON DONKI", "DONKI",
            "REDMART", "LAZADA REDMART", "LITTLE FARMS", "MUSTAFA", "ANG MO SUPERMARKET",
            "HAO MART", "U STARS", "SUPERMARKET", "MARKETPLACE", "JASONS", "SCARLETT",
            "RYANS GROCERY", "HUBER BUTCHERY", "SONG FA GROCERY", "MEIDI YA", "MEIDIYA",
            "WET MARKET", "PASAR", "FRUIT", "BUTCHER", "AMAZON FRESH", "OPEN TASTE",
            "GROCER", "PANTRY", "EMPORIUM SHOKUHIN MARKET",
        ) + r"|\bGROCERIES\b|\bGROCERY\b|\bMINIMART\b|\bMINI\s*MART\b|\b7[\s-]*ELEVEN\b)",
        CAT_GROCERIES, DEBIT,
    ))

    # -- Variable: recreation, wellness, health, sport ----------------------
    rules.append((
        "recreation",
        r"(" + _alt(
            "CLASSPASS", "GUAVAPASS", "SPA", "MASSAGE", "WELLNESS", "TCM",
            "CHIROPRACTIC", "PHYSIOTHERAPY", "PHYSIO", "ACUPUNCTURE", "FLOAT",
            "SAUNA", "ONSEN", "YOGA", "PILATES", "BARRE", "SPIN STUDIO",
            "CROSSFIT", "CLIMB CENTRAL", "BOULDER", "CLIMBING", "GOLF", "DRIVING RANGE",
            "TENNIS", "BADMINTON", "SWIM", "SPORTS HALL", "STADIUM", "SPORTS SG",
            "GOLDEN VILLAGE", "CATHAY CINEPLEX", "SHAW THEATRES", "FILMGARDE",
            "CINEMA", "CINEPLEX", "KTV", "KARAOKE", "TEO HENG", "K STAR",
            "ESCAPE ROOM", "BOWLING", "ARCADE", "TIMEZONE", "ZOO", "BIRD PARADISE",
            "RIVER WONDERS", "GARDENS BY THE BAY", "SCIENCE CENTRE", "ARTSCIENCE",
            "NATIONAL GALLERY", "MUSEUM", "SENTOSA", "UNIVERSAL STUDIOS", "ADVENTURE COVE",
            "WILD WILD WET", "SKY HELIX", "SINGAPORE FLYER", "TICKETMASTER", "SISTIC",
            "EVENTBRITE", "CONCERT", "THEATRE", "ESPLANADE", "CLINIC", "MEDICAL",
            "DENTAL", "DENTIST", "HOSPITAL", "POLYCLINIC", "RAFFLES MEDICAL",
            "PARKWAY", "MOUNT ELIZABETH", "GLENEAGLES", "HEALTHWAY", "GUARDIAN HEALTH",
            "WATSONS PHARMACY", "PHARMACY", "OPTOMETRY", "OPTICAL", "EYE CENTRE",
            "AESTHETIC", "DERMATOLOGY", "SALON", "HAIRDRESS", "BARBER", "NAIL",
            "BEAUTY", "FACIAL", "SUPPLEMENT", "GNC", "NATURE'S FARM", "IHERB",
        ) + r"|\bHEALTH\b|\bFITNESS\s*CLASS\b|\bRECREATION\b)",
        CAT_EXPERIENCES, DEBIT,
    ))

    # -- Variable: dining ---------------------------------------------------
    rules.append((
        "dining",
        r"(" + _alt(
            "STARBUCKS", "COFFEE BEAN", "TOAST BOX", "YA KUN", "KOPITIAM", "KOUFU",
            "FOOD REPUBLIC", "FOOD COURT", "FOODCOURT", "HAWKER", "MCDONALD", "MCDONALDS",
            "KFC", "BURGER KING", "SUBWAY", "TEXAS CHICKEN", "POPEYES", "SHAKE SHACK",
            "FIVE GUYS", "MOS BURGER", "JOLLIBEE", "PIZZA HUT", "DOMINOS", "PEZZO",
            "SUSHI", "RAMEN", "IPPUDO", "TONKOTSU", "SABURO", "GENKI", "SAKAE",
            "DIN TAI FUNG", "CRYSTAL JADE", "PARADISE GROUP", "JUMBO SEAFOOD",
            "TUNG LOK", "IMPERIAL TREASURE", "HAI DI LAO", "HAIDILAO", "BEAUTY IN THE POT",
            "SWEE CHOON", "TIM HO WAN", "SONG FA", "BAK KUT TEH", "CHICKEN RICE",
            "NASI", "PRATA", "ROTI", "MURTABAK", "BRIYANI", "ZAM ZAM", "SPRINGLEAF",
            "SALAD STOP", "SALADSTOP", "GRAIN", "STUFF D", "GUZMAN", "CHIPOTLE",
            "SUBWAY SG", "LIHO", "KOI THE", "GONG CHA", "CHICHA", "MIXUE", "HEYTEA",
            "TIGER SUGAR", "BUBBLE TEA", "BOOST JUICE", "JAMBA", "SMOOTHIE",
            "BAKERY", "BREADTALK", "PAUL", "TIONG BAHRU BAKERY", "DELIFRANCE",
            "CEDELE", "PS CAFE", "COMMON MAN COFFEE", "TOBYS ESTATE", "APARTMENT COFFEE",
            "CAFE", "COFFEE", "BISTRO", "RESTAURANT", "RESTORAN", "EATERY", "DINER",
            "GRILL", "STEAKHOUSE", "BAR ", "PUB ", "BREWERY", "BREWERKZ", "TAP HOUSE",
            "WINE", "COCKTAIL", "LOUNGE", "IZAKAYA", "YAKINIKU", "KOREAN BBQ",
            "DESSERT", "ICE CREAM", "GELATO", "BASKIN", "AWFULLY CHOCOLATE",
            "CHOPE", "OPENRICE", "BURPPLE", "EATIGO", "QUANDOO",
            "OLD CHANG KEE", "FUN TOAST", "MR BEAN", "POLAR PUFFS",
        ) + r"|\bDINING\b|\bDIN\s*IN\b|\bF\s*&\s*B\b|\bBISTRO\b|\bTEAHOUSE\b|\bZI\s*CHAR\b|"
        # Generic food words, so an unknown eatery abroad still lands in Dining
        # rather than Other. Deliberately after Groceries and before Shopping.
        r"\bCOFFE|\bNOODLE|\bUDON\b|\bSOBA\b|\bPHO\b|\bPOCHA\b|\bDELI\b|"
        r"\bTOAST\b|\bSEAFOOD\b|\bHOTPOT\b|\bSHABU\b|\bGYOZA\b|\bKATSU\b|"
        r"\bTERIYAKI\b|\bTAPAS\b|\bTRATTORIA\b|\bOSTERIA\b|\bBRASSERIE\b|"
        r"\bGASTROPUB\b|\bPATISSERIE\b|\bCREPERIE\b|\bFRIED\s*CHICKEN\b|"
        r"\bDIM\s*SUM\b|\bCANTEEN\b|\bFOOD\s*HALL\b|\bEATING\s*HOUSE\b|"
        r"\bTEA\s*HOUSE\b|\bJUICE\s*BAR\b|\bCHAR\s*SIEW\b|\bSATAY\b)",
        CAT_FOOD, DEBIT,
    ))

    # -- Variable: shopping -------------------------------------------------
    rules.append((
        "shopping",
        r"(" + _alt(
            "SHOPEE", "LAZADA", "AMAZON SG", "AMAZON COM", "AMZN", "QOO10", "TAOBAO",
            "ALIEXPRESS", "TEMU", "ALIBABA", "EZBUY", "CAROUSELL", "ZALORA", "ASOS",
            "SHEIN", "UNIQLO", "GU SINGAPORE", "ZARA", "H M ", "H&M", "COS ",
            "MASSIMO DUTTI", "MUJI", "IKEA", "COURTS", "HARVEY NORMAN", "CHALLENGER",
            "BEST DENKI", "GAIN CITY", "AUDIO HOUSE", "APPLE STORE", "APPLE SINGAPORE",
            "SAMSUNG", "XIAOMI", "DYSON", "DECATHLON", "ROYAL SPORTING HOUSE",
            "NIKE", "ADIDAS", "NEW BALANCE", "ASICS", "LULULEMON", "UNDER ARMOUR",
            "SEPHORA", "WATSONS", "GUARDIAN", "INNISFREE", "THE FACE SHOP", "LANEIGE",
            "TYPO", "SMIGGLE", "POPULAR BOOK", "KINOKUNIYA", "TIMES BOOKSTORE",
            "DAISO", "VALU DOLLAR", "MINISO", "ACE HARDWARE", "HOME FIX", "SELFFIX",
            "TANGS", "TAKASHIMAYA", "ISETAN", "METRO DEPT", "ROBINSONS", "MARKS SPENCER",
            "CHARLES KEITH", "PEDRO", "COACH", "LONGCHAMP", "MICHAEL KORS", "GUCCI",
            "LOUIS VUITTON", "DIOR", "CHANEL", "PRADA", "ROLEX", "TIFFANY",
            "LOVE BONITO", "OSSIE", "PAZZION", "RUBI", "COTTON ON", "FACTORIE",
            "FURNITURE", "HOMEWARE", "STATIONERY", "TOY R US", "TOYS R US",
        ) + r"|\bSHOPPING\b|\bDEPARTMENT\s*STORE\b|\bBOUTIQUE\b|\bRETAIL\b|\bSTORE\b|\bMALL\b)",
        CAT_SHOPPING, DEBIT,
    ))

    # -- Transport, generic terms -------------------------------------------
    # These sit *after* the merchant lists on purpose. "MRT", "BUS" and "TAXI"
    # show up in Singapore shop names as locations — "GIANT-SIMEI MRT" is a
    # supermarket, not a train fare — so a named merchant must win first.
    rules.append((
        "transport-generic-cab",
        r"(\bTAXI\b|\bCAB\s*FARE\b)",
        CAT_TRANSPORT_CAB, DEBIT,
    ))
    rules.append((
        "transport-generic-public",
        r"(\bMRT\b|\bLRT\b|\bBUS\b|\bTRAIN\s*FARE\b|\bFARE\b)",
        CAT_TRANSPORT_PUBLIC, DEBIT,
    ))

    # -- Utilities / misc that fall to Other, plus card fees ----------------
    rules += [
        ("bank-fee", r"(SERVICE\s*(CHARGE|FEE)|\bLATE\s*(PAYMENT\s*)?CHARGE\b|"
                     r"FINANCE\s*CHARGE|INTEREST\s*CHARGE|\bGST\b\s*ON|CASH\s*ADVANCE\s*FEE|"
                     r"FOREIGN\s*(CURRENCY\s*)?TRANSACTION\s*FEE|\bADMIN\s*FEE\b|"
                     r"(CCY|CURRENCY)\s*CONVERSION\s*FEE|\bGST\s*ON\b|"
                     r"\bFALL\s*BELOW\s*FEE\b)", CAT_UNCATEGORISED, DEBIT),
        # Tax is a fixed commitment, not a stray debit. It sits before the
        # utilities rule because IRAS appears in both and the Fixed line wins.
        ("tax", r"(\bIRAS\b|\bPROPERTY\s*TAX\b|\bINCOME\s*TAX\b|"
                r"\bTAX\s*(PAYMENT|INSTAL?MENT|RETURN)\b|\bGIRO\s*IRAS\b|"
                r"\bINLAND\s*REVENUE\b)", CAT_TAX, DEBIT),
        ("utilities", r"(\bSP\s*(SERVICES|GROUP|POWER)\b|\bPUB\s*UTILIT|\bUTILITIES\b|"
                      r"\bCITY\s*ENERGY\b|\bGENECO\b|\bKEPPEL\s*ELECTRIC\b|\bSENOKO\b|"
                      r"\bTUAS\s*POWER\b|\bSEMBCORP\s*POWER\b|\bELECTRICITY\b|"
                      r"\bTOWN\s*COUNCIL\b|\bS\s*C\s*C\s*\b|\bCONSERVANCY\b|"
                      r"\bHDB\b|\bMORTGAGE\b|\bHOME\s*LOAN\b|\bRENT\b|"
                      r"\bCPF\s*(TOP|CONTRIB)|\bSRS\b)",
         CAT_UNCATEGORISED, DEBIT),
        ("atm-cash", r"(\bATM\b|CASH\s*WITHDRAWAL|CASH\s*WDL|\bWDL\b|CASH\s*ADVANCE)",
         CAT_UNCATEGORISED, DEBIT),
    ]

    # -- PayNow / generic transfers: dining per spec, but flagged ------------
    rules += [
        ("paynow-out", r"(\bPAYNOW\b|\bPAY\s*NOW\b|\bPAYLAH\b|\bPAY\s*LAH\b|"
                       r"\bFAST\s*PAYMENT\b|\bIBG\b|\bFUNDS?\s*TRANSFER\b|"
                       r"\bTRANSFER\s*TO\b|\bBILL\s*PAYMENT\b|\bGIRO\b|"
                       r"\bMEPS\b|\bIBFT\b|\bTELEGRAPHIC\s*TRANSFER\b)", CAT_FOOD, DEBIT),
        ("paynow-in", r"(\bPAYNOW\b|\bPAY\s*NOW\b|\bPAYLAH\b|\bINCOMING\b|"
                      r"\bTRANSFER\s*FROM\b|\bFUNDS?\s*TRANSFER\b|\bIBG\b|\bFAST\b)",
         CAT_ADDITIONAL_INCOME, CREDIT),
        ("refund", r"(\bREFUND\b|\bREVERSAL\b|\bREVERSED\b|\bFEE\s*REV\b|"
                    r"\bCHARGEBACK\b|\bCREDIT\s*ADJUSTMENT\b)",
         CAT_UNCATEGORISED, CREDIT),
    ]

    return rules


# Rules whose match is a guess rather than a merchant identification — these
# get flagged for review in the UI.
LOW_CONFIDENCE_RULES = {
    "paynow-out",
    "paynow-in",
    "atm-cash",
    "utilities",
    "refund",
    "bank-fee",
}

# Rules that identify an actual merchant. A refund is looked up against these
# so the money comes back off the category it was spent from.
MERCHANT_RULES = {
    "insurance", "telco", "subscriptions", "food-delivery", "travel",
    "transport-cab", "transport-car", "transport-public",
    "groceries", "recreation", "dining", "shopping", "tax",
}


# Above this many SGD, an unidentified transfer is set aside rather than booked
# on a guess. A four-figure PayNow is not a restaurant bill.
DEFAULT_TRANSFER_REVIEW_THRESHOLD = 500.0


class Categoriser:
    def __init__(self, parent_names=None, employer_keywords=None, overrides_path=None,
                 transfer_review_threshold: float = DEFAULT_TRANSFER_REVIEW_THRESHOLD):
        self.rules = [
            (name, re.compile(pattern, re.IGNORECASE), cat, direction)
            for name, pattern, cat, direction in build_rules(parent_names, employer_keywords)
        ]
        self.overrides_path = overrides_path
        self.overrides = _load_overrides(overrides_path) if overrides_path else {}
        self.transfer_review_threshold = transfer_review_threshold

    def _too_big_to_guess(self, amount: Optional[float]) -> bool:
        threshold = self.transfer_review_threshold
        return bool(threshold and amount is not None and amount >= threshold)

    def categorise(self, raw_description: str, direction: str,
                   amount: Optional[float] = None):
        """Return (category, rule_name, needs_review, note)."""
        text = raw_description.upper()

        # 1. User overrides win outright.
        key = merchant_key(raw_description)
        if key and key in self.overrides:
            return self.overrides[key], "user-override", False, ""

        # 2. Keyword rules, first match wins.
        for name, pattern, category, only_direction in self.rules:
            if only_direction and only_direction != direction:
                continue
            if pattern.search(text):
                needs_review = name in LOW_CONFIDENCE_RULES
                note = ""
                if name in ("paynow-out", "paynow-in"):
                    # A named merchant inside a transfer wins: a PayNow credit
                    # from "Prudential Assurance" is an insurance refund, not
                    # generic income.
                    merchant = self._merchant_category(text)
                    if merchant:
                        return (merchant, "transfer-to-merchant", True,
                                "Transfer naming a known merchant — categorised from "
                                "the merchant. Confirm it is not something else.")
                    if self._too_big_to_guess(amount):
                        return (
                            CAT_UNCLASSIFIED_TRANSFER, name + "-large", True,
                            f"Unidentified transfer of S${amount:,.2f} — too large to "
                            f"assume. Held out of the income statement until you "
                            f"assign it a category.",
                        )
                if name == "paynow-out":
                    note = "Transfer out — assumed Food per your rule; confirm."
                elif name == "paynow-in":
                    note = "Incoming transfer — counted as additional income; confirm."
                elif name == "atm-cash":
                    note = "Cash withdrawal — left uncategorised; assign it if you know the spend."
                elif name == "utilities":
                    note = "Household or utility item — no line exists for it, so it is left uncategorised."
                elif name == "refund":
                    # Send the money back to whatever category it was spent from,
                    # so the refund nets off that line instead of sitting in Other.
                    merchant = self._merchant_category(text)
                    if merchant:
                        return (merchant, "refund-to-merchant", False,
                                "Refund — netted off the original category.")
                    note = "Refund — offsets its category; move it to the right one."
                elif name == "bank-fee":
                    note = "Bank or card fee — left uncategorised."
                return category, name, needs_review, note

        # 3. A credit that names a merchant is almost always a refund of that
        #    merchant's charge, not fresh income.
        if direction == CREDIT:
            merchant = self._merchant_category(text)
            if merchant:
                return (merchant, "credit-to-merchant", True,
                        "Credit from a known merchant — treated as a refund against "
                        "that category rather than income.")

        # 4. Nothing matched.
        if direction == CREDIT:
            if self._too_big_to_guess(amount):
                return (
                    CAT_UNCLASSIFIED_TRANSFER, "large-credit", True,
                    f"Unidentified credit of S${amount:,.2f} — held out of the income "
                    f"statement rather than assumed to be income. Assign it a category "
                    f"to include it.",
                )
            return CAT_ADDITIONAL_INCOME, "", True, "Unmatched credit — verify it is income."
        return CAT_UNCATEGORISED, "", True, "No rule matched — please categorise."

    def _merchant_category(self, upper_text: str) -> Optional[str]:
        """Which merchant rule does this text hit, ignoring direction?"""
        for name, pattern, category, _direction in self.rules:
            if name in MERCHANT_RULES and pattern.search(upper_text):
                return category
        return None


# ---------------------------------------------------------------------------
# Learned overrides: remember a correction so next month is right first time.
# ---------------------------------------------------------------------------
_STRIP_NOISE = re.compile(
    r"(SINGAPORE\s*SG|\bSGP?\b|\bSG\b|\bSINGAPORE\b|\bPTE\s*LTD\b|\bLTD\b|\bLLP\b|"
    r"\bREF\s*\w+|\bTXN\b|\b\d{4,}\b|[*#/\\]|\bXX+\d*\b)",
    re.IGNORECASE,
)


def merchant_key(raw_description: str) -> str:
    """A stable-ish key for a merchant so overrides survive small text changes."""
    text = _STRIP_NOISE.sub(" ", raw_description.upper())
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    words = [w for w in text.split() if len(w) > 1]
    return " ".join(words[:4])


def _load_overrides(path) -> dict:
    """Your saved merchant fixes, with old category names brought forward.

    An override stores a category *name*, so renaming or merging a category
    would strand every fix pointing at the old one. Anything migrate_category
    declines to map — "Transport", which split three ways with nothing in the
    old name to say which branch a merchant belongs to — is dropped, so the
    rule engine decides again rather than the app guessing on your behalf.
    """
    if path and os.path.exists(path):
        try:
            with open(path) as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {}
        migrated = {}
        for key, category in raw.items():
            current = migrate_category(category)
            if current is not None:
                migrated[key] = current
        return migrated
    return {}


def save_overrides(path, overrides: dict) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(overrides, fh, indent=2, sort_keys=True)
