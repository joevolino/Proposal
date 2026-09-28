"""Deterministic parser for the VensureHR Pricing Illustration workbook (Admin, WC, Taxes).

The template's formulas are recomputed here so the numbers are right even when the
workbook was filled in by a tool that did not store cached formula results:

    Taxable Wages = EE Count x State Wage Base
    WC Cost       = WC Rate% x Est. Annual Payroll   (rate per $100 of payroll)
    SUTA Cost     = SUTA Rate% x Taxable Wages
    Yearly Admin  = PEPM x Total EE Count x 12
"""

from __future__ import annotations

import re

import openpyxl

# 2026 SUTA wage bases from the template's Sheet1 (used when the workbook's table is missing).
WAGE_BASES = {
    "AL": 8000, "AK": 51700, "AZ": 8000, "AR": 7000, "CA": 7000, "CO": 30600, "CT": 26100,
    "DE": 12500, "DC": 9000, "FL": 7000, "GA": 9500, "HI": 61958, "ID": 55300, "IL": 13916,
    "IN": 9500, "IA": 39500, "KS": 15100, "KY": 11700, "LA": 7700, "ME": 12000, "MD": 8500,
    "MA": 15000, "MI": 9000, "MN": 42000, "MS": 14000, "MO": 9500, "MT": 45100, "NE": 9000,
    "NV": 41800, "NH": 14000, "NJ": 44800, "NM": 31700, "NY": 13000, "NC": 32600, "ND": 45100,
    "OH": 9000, "OK": 28200, "OR": 54300, "PA": 10000, "PR": 7000, "RI": 29800, "SC": 14000,
    "SD": 15000, "TN": 7000, "TX": 9000, "UT": 48900, "VT": 14800, "VA": 8000, "WA": 72800,
    "WV": 9500, "WI": 14000, "WY": 32400,
}


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.startswith("#"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _text(v):
    return "" if v is None else str(v).strip()


def looks_like_pricing_illustration(wb) -> bool:
    if "Pricing Illustration" in wb.sheetnames:
        return True
    ws = wb.worksheets[0]
    return _text(ws["A2"].value).lower() == "state" and "wc" in _text(ws["G2"].value).lower()


def parse_pricing_illustration(path: str) -> dict | None:
    """Return structured pricing data, or None if the workbook isn't a pricing illustration."""
    wb_f = openpyxl.load_workbook(path, data_only=False, read_only=False, keep_vba=False)
    if not looks_like_pricing_illustration(wb_f):
        return None
    wb_v = openpyxl.load_workbook(path, data_only=True)
    name = "Pricing Illustration" if "Pricing Illustration" in wb_v.sheetnames else wb_v.sheetnames[0]
    ws = wb_v[name]

    wage_bases = dict(WAGE_BASES)
    if "Sheet1" in wb_v.sheetnames:
        for row in wb_v["Sheet1"].iter_rows(min_row=2, max_col=2, values_only=True):
            st, base = _text(row[0]).upper(), _num(row[1])
            if len(st) == 2 and base:
                wage_bases[st] = base

    rows = []
    for r in range(4, 35):
        state = _text(ws.cell(r, 1).value).upper()
        code = _text(ws.cell(r, 2).value)
        ees = _num(ws.cell(r, 3).value)
        payroll = _num(ws.cell(r, 4).value)
        if not state or state.startswith("#") or (ees is None and payroll is None):
            continue
        wc_rate = _num(ws.cell(r, 7).value)
        suta_raw = ws.cell(r, 9).value
        suta_rate = _num(suta_raw)
        base = _num(ws.cell(r, 5).value) or wage_bases.get(state[:2])
        taxable = (ees or 0) * base if base else _num(ws.cell(r, 6).value)
        wc_cost = (wc_rate or 0) / 100 * (payroll or 0) if wc_rate is not None else None
        suta_cost = (suta_rate / 100 * taxable) if (suta_rate is not None and taxable) else None
        note = "" if suta_rate is not None else (_text(suta_raw) or "Client Report")
        rows.append({
            "state": state, "class_code": code.split(".")[0], "ees": ees, "payroll": payroll,
            "taxable_wages": taxable, "wc_rate": wc_rate, "wc_cost": wc_cost,
            "suta_rate": suta_rate, "suta_cost": suta_cost, "suta_note": note,
        })

    company = _text(ws["A1"].value)
    if company.startswith("{"):
        company = ""
    pepm = _num(ws["C37"].value)
    setup = _num(ws["J39"].value)
    epli = _text(ws["J40"].value) or "Included"

    ee_total = sum(r["ees"] or 0 for r in rows)
    addons = []
    for r in range(45, 70):
        label = _text(ws.cell(r, 1).value)
        if not label or label.startswith("=") or label.startswith("*"):
            continue
        tier = re.search(r"\(Groups\s*(\d+)\s*-\s*(\d+)\)", label)
        if tier:
            lo, hi = int(tier.group(1)), int(tier.group(2))
            if ee_total and not (lo <= ee_total <= hi):
                continue
            if not ee_total and lo != 1:
                continue
            label = label[: tier.start()].strip()
        addons.append({"name": label.rstrip("*").strip(), "rate": _addon_rate(ws, r)})

    return {
        "source": "pricing_illustration",
        "company": company,
        "admin_pepm": pepm,
        "setup_fee": setup,
        "epli": epli,
        "rows": rows,
        "addons": addons,
        "employee_count": sum(r["ees"] or 0 for r in rows) or None,
    }


def _addon_rate(ws, r) -> str:
    rate, per, impl = ws.cell(r, 6).value, _text(ws.cell(r, 7).value).lower(), ws.cell(r, 8).value
    if isinstance(rate, str) and "\n" in rate:
        lines = [ln.split(" - ")[0].strip() + " " + ln.split(" - ")[1].split()[0].lower()
                 for ln in rate.splitlines()[:2] if " - " in ln]
        s = " / ".join(lines) or rate.splitlines()[0]
    else:
        s = _money_label(rate)
    s += {"pepm": " PEPM", "per month": " / mo", "verification": " per verification",
          "one time fee": " one time", "": ""}.get(per, f" {per}")
    impl_n = _num(impl)
    if impl_n and per != "one time fee":
        s += f" + ${impl_n:,.0f} setup"
    return s.strip()


def _money_label(v) -> str:
    n = _num(v)
    if n is None:
        return _text(v)
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"
