"""Column/sheet names for the Path B input template -- single source of truth
shared by the template writer and the producer, so they can never drift.
"""
from __future__ import annotations

COMPANY_SHEET = "Company"
LINE_ITEMS_SHEET = "Line Items"

COMPANY_FIELD_COL = "Field"
COMPANY_VALUE_COL = "Value"

FIELD_ENTITY_ID = "entity_id"
FIELD_FY_END_MONTH = "fiscal_year_end_month"
FIELD_FY_END_DAY = "fiscal_year_end_day"

COMPANY_FIELDS = (FIELD_ENTITY_ID, FIELD_FY_END_MONTH, FIELD_FY_END_DAY)

# Line Items sheet: fixed metadata columns, in header order, followed by one
# column per fiscal year (a plain 4-digit year, e.g. "2024"). scope_flag and
# method_flag may be left blank (contract models them as nullable); every
# other metadata column is a required declaration -- see producer.py.
COL_CLIENT_LABEL = "client_label"
COL_STD_ID = "std_id"
COL_FRAMEWORK = "framework"
COL_PNL_METHOD = "pnl_method"
COL_UNIT = "unit"
COL_CURRENCY = "currency"
COL_PRESENTATION_BASIS = "presentation_basis"
COL_SCOPE_FLAG = "scope_flag"
COL_METHOD_FLAG = "method_flag"

METADATA_COLUMNS = (
    COL_CLIENT_LABEL, COL_STD_ID, COL_FRAMEWORK, COL_PNL_METHOD, COL_UNIT,
    COL_CURRENCY, COL_PRESENTATION_BASIS, COL_SCOPE_FLAG, COL_METHOD_FLAG,
)

# Columns the analyst must fill for every non-blank row. scope_flag and
# method_flag are deliberately excluded: the contract types them `str | None`,
# so an explicit blank is a valid declaration, not a missing one.
REQUIRED_LINE_ITEM_COLUMNS = (
    COL_CLIENT_LABEL, COL_STD_ID, COL_FRAMEWORK, COL_PNL_METHOD, COL_UNIT,
    COL_CURRENCY, COL_PRESENTATION_BASIS,
)

VALID_FRAMEWORKS = ("hgb", "ifrs")
VALID_PNL_METHODS = ("gkv", "ukv")
VALID_UNITS = ("EUR", "TEUR")
VALID_CURRENCIES = ("EUR", "GBP", "USD")
VALID_PRESENTATION_BASES = (
    "umsatzerloese", "bruttoumsatzerloese", "nettoumsatzerloese",
    "gesamtleistung", "rohergebnis", "betriebsleistung", "n/a",
)
