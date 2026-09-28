"""Proposal data model: build the editable proposal JSON and compute every derived number.

The drafting step (AI or manual) only supplies inputs such as rates, enrollment counts and
narrative. Every total, savings figure and break-even in the PDF comes from `compute()`, so
the arithmetic is always consistent with the tables.
"""

from __future__ import annotations

import copy
import datetime as dt
import re

from . import brand

SECTION_KEYS = ["recap", "executive", "medical", "ancillary", "wc_suta", "total", "roi", "rollout"]


def num(v):
    """Parse user/AI supplied numbers like '$1,234.50', '(12.5)', '4.1%'; None if blank."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.\-]", "", s)
    if s in ("", "-", ".", "-."):
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def parse_date(s) -> dt.date | None:
    if not s:
        return None
    if isinstance(s, dt.date):
        return s
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            pass
    return None


def long_date(d: dt.date | None) -> str:
    return f"{d:%B} {d.day}, {d.year}" if d else "TBD"


def short_date(d: dt.date | None) -> str:
    return f"{d.month}/{d.day}/{d.year}" if d else "TBD"


def empty_proposal() -> dict:
    return {
        "client": {
            "name": "", "industry": "", "employee_count": None, "states": [], "effective_date": "",
            "incumbent_name": "", "contact_name": "", "contact_title": "", "address": "",
        },
        "consultant": {"name": "", "title": "Business Consultant", "phone": "", "email": "", "office_address": ""},
        "prepared_date": dt.date.today().isoformat(),
        "pricing": {"admin_pepm": None, "admin_employee_count": None, "setup_fee": None, "epli": "Included"},
        "recap": {"intro": "", "rows": [], "commitment": ""},
        "executive": {"highlights": [], "bottom_line": ""},
        "services": copy.deepcopy(brand.DEFAULT_SERVICES),
        "medical": {"current_carrier": "", "proposed_carrier": "", "intro": "", "plans": [], "footnote": ""},
        "dental": {"rows": [], "note": ""},
        "vision": {"rows": [], "note": ""},
        "ancillary_recommendation": "",
        "additional_coverage": [],
        "additional_note": "",
        "wc_suta": {"rows": [], "note": ""},
        "addons": copy.deepcopy(brand.DEFAULT_ADDONS),
        "incumbent": {
            "medical_annual": None, "admin_annual": None, "wc_annual": None, "suta_annual": None,
            "ancillary_annual": None, "other_annual": None, "other_label": "Other fees",
        },
        "proposed_ancillary_annual": None,
        "roi": {"title": "ROI Analysis", "intro": "", "rows": [], "takeaways": []},
        "rollout": {"intro": "", "phases": [], "things_to_know": [], "next_step": ""},
        "service_callout": "",
        "sections": {k: True for k in SECTION_KEYS},
    }


def from_form(form: dict, pricing: dict | None) -> dict:
    """Seed a proposal from the intake form plus the parsed pricing illustration."""
    p = empty_proposal()
    c = p["client"]
    c["name"] = form.get("client_name", "").strip() or (pricing or {}).get("company", "")
    c["industry"] = form.get("industry", "").strip()
    c["employee_count"] = num(form.get("employee_count")) or (pricing or {}).get("employee_count")
    states = form.get("states", "")
    c["states"] = [s.strip().upper() for s in re.split(r"[,;/\s]+", states) if s.strip()]
    c["effective_date"] = form.get("effective_date", "").strip()
    c["incumbent_name"] = form.get("incumbent_name", "").strip()
    c["contact_name"] = form.get("contact_name", "").strip()
    c["contact_title"] = form.get("contact_title", "").strip()
    c["address"] = form.get("client_address", "").strip()

    k = p["consultant"]
    for f in ("name", "title", "phone", "email"):
        k[f] = form.get(f"consultant_{f}", "").strip() or k[f]
    k["office_address"] = form.get("consultant_address", "").strip()

    pr = p["pricing"]
    if pricing:
        pr["admin_pepm"] = pricing.get("admin_pepm")
        pr["setup_fee"] = pricing.get("setup_fee")
        pr["epli"] = pricing.get("epli") or "Included"
        p["wc_suta"]["rows"] = pricing["rows"]
        if pricing.get("addons"):
            p["addons"] = pricing["addons"]
        if not c["states"]:
            c["states"] = sorted({r["state"][:2] for r in pricing["rows"]})
    if num(form.get("admin_pepm")) is not None:
        pr["admin_pepm"] = num(form.get("admin_pepm"))
    if num(form.get("setup_fee")) is not None:
        pr["setup_fee"] = num(form.get("setup_fee"))

    inc = p["incumbent"]
    for f in ("medical", "admin", "wc", "suta", "ancillary", "other"):
        inc[f"{f}_annual"] = num(form.get(f"incumbent_{f}_annual"))
    p["proposed_ancillary_annual"] = num(form.get("proposed_ancillary_annual"))

    apply_defaults(p)
    return p


def apply_defaults(p: dict) -> dict:
    """Fill any narrative the drafting step left blank with sensible standard copy."""
    c = p["client"]
    name = c.get("name") or "the client"
    inc = c.get("incumbent_name") or "your current provider"
    eff = parse_date(c.get("effective_date"))
    ro = p["rollout"]
    if not ro.get("phases"):
        ro["phases"] = default_phases(eff, inc, p["consultant"].get("name") or "VensureHR")
    if not ro.get("intro") and eff:
        ro["intro"] = (
            f"A {long_date(eff).rsplit(',', 1)[0]} start gives {name} a clean switch point. "
            "Plan-year deductibles and out-of-pocket maximums line up with the new coverage, and "
            "payroll tax setup is completed before the first VensureHR payroll."
        )
    if not ro.get("things_to_know"):
        ro["things_to_know"] = [t.format(incumbent=inc) for t in brand.DEFAULT_THINGS_TO_KNOW]
    if not ro.get("next_step"):
        ro["next_step"] = (
            f"**Next step:** send one recent {inc} invoice detail report and current benefit enrollment. "
            "We will return a final side-by-side and schedule your kick-off."
        )
    if not p.get("service_callout"):
        p["service_callout"] = brand.DEFAULT_SERVICE_CALLOUT.format(client=name)
    if not p["wc_suta"].get("note") and p["wc_suta"].get("rows"):
        p["wc_suta"]["note"] = (
            "**What the terms mean:** WC rate is the cost per $100 of payroll. SUTA is state unemployment tax, "
            "charged on each employee's wages up to the state's taxable wage limit. \"Client Report\" means taxes "
            "in that state are reported under the client's own state account; VensureHR still processes the filings. "
            "Workers' comp pricing depends on a completed Risk Questionnaire and 3-5 years of loss runs."
        )
    return p


def default_phases(eff: dt.date | None, incumbent: str, consultant: str) -> list[dict]:
    """Standard seven-phase rollout, back-scheduled from the effective date."""
    spec = [
        ("Decision & Paperwork", -88, -77, "Sign Client Service Agreement and benefits agreement. Complete the Risk "
         "Questionnaire and provide 3-5 years of WC loss runs.", f"Client + {consultant}"),
        ("Data Collection", -74, -56, f"Send from {incumbent}: payroll journal detail, YTD wages, employee census, "
         "current benefit enrollment and dependents, PTO balances. Confirm state tax account numbers.", "Client"),
        ("Account Setup", -53, -35, "Build payroll in the VensureHR platform: state tax setup, pay schedule, "
         "deductions, GL mapping, user access. Kick-off meeting with your Payroll Specialist and Client Relations "
         "Manager.", "VensureHR Implementation"),
        ("Open Enrollment", -32, -21, "Employee benefits meeting (virtual). Employees enroll online in medical, "
         "dental, vision and any ancillary plans. Employee portal onboarding.", "Employees + VensureHR Benefits"),
        ("Validation", -18, -9, f"Underwriting approves final enrollment. Review a test payroll against a recent "
         f"{incumbent} payroll. Give termination notice per your current agreement once coverage is approved.",
         "Client + VensureHR"),
    ]
    phases = []
    today = dt.date.today()
    scale = 1.0
    if eff and (eff - today).days < 90:
        scale = max((eff - today).days - 2, 10) / 90
    for i, (title, a, b, what, who) in enumerate(spec, 1):
        if eff:
            start = _weekday(eff + dt.timedelta(days=round(a * scale)), forward=True)
            end = _weekday(eff + dt.timedelta(days=round(b * scale)), forward=False)
            timing = f"{start:%b} {start.day} - {end:%b} {end.day}"
        else:
            timing = f"Weeks {i * 2 - 1}-{i * 2}"
        phases.append({"phase": f"{i}. {title}", "timing": timing, "what": what, "who": who})
    phases.append({"phase": "6. Go-Live", "timing": long_date(eff) if eff else "Effective date",
                   "what": "Coverage starts; ID cards issued. First VensureHR payroll processed.", "who": "VensureHR"})
    phases.append({"phase": "7. Check-ins", "timing": "30 / 60 / 90 days",
                   "what": "Review payroll accuracy, open questions and employee feedback. HR assessment and "
                           "handbook review with your HR Partner.", "who": "Client Relations Manager"})
    return phases


def _weekday(d: dt.date, forward: bool) -> dt.date:
    while d.weekday() >= 5:
        d += dt.timedelta(days=1 if forward else -1)
    return d


# ---------------------------------------------------------------------------------------------
# Derived numbers
# ---------------------------------------------------------------------------------------------

def compute(p: dict) -> dict:
    """Return all computed figures used by the PDF (never stored back into the editable JSON)."""
    r: dict = {}

    # Medical
    plans = []
    tot_cur = tot_pro = 0.0
    have_cur = have_pro = False
    enrolled = 0
    for plan in p.get("medical", {}).get("plans", []):
        cur = pro = 0.0
        pc = pp = False
        cnt = 0
        for t in plan.get("tiers", []):
            n = num(t.get("count")) or 0
            cnt += n
            cr, prr = num(t.get("current_rate")), num(t.get("proposed_rate"))
            if cr is not None:
                cur += n * cr * 12
                pc = True
            if prr is not None:
                pro += n * prr * 12
                pp = True
        plans.append({"current_annual": cur if pc else None, "proposed_annual": pro if pp else None,
                      "savings": (cur - pro) if (pc and pp) else None, "enrolled": cnt})
        enrolled += cnt
        if pc:
            tot_cur += cur
            have_cur = True
        if pp:
            tot_pro += pro
            have_pro = True
    inc = p.get("incumbent", {})
    med_cur = num(inc.get("medical_annual"))
    if med_cur is None and have_cur:
        med_cur = tot_cur
    med_pro = tot_pro if have_pro else None
    med_sav = (med_cur - med_pro) if (med_cur is not None and med_pro is not None) else None
    r["medical"] = {
        "plans": plans, "enrolled": enrolled, "current": med_cur, "proposed": med_pro, "savings": med_sav,
        "pct": (med_sav / med_cur * 100) if (med_sav is not None and med_cur) else None,
    }

    # WC / SUTA: costs always follow the rates when both inputs are present
    wc_rows = []
    for x in p.get("wc_suta", {}).get("rows", []):
        payroll, wc_rate = num(x.get("payroll")), num(x.get("wc_rate"))
        taxable, suta_rate = num(x.get("taxable_wages")), num(x.get("suta_rate"))
        wc_cost = wc_rate / 100 * payroll if (wc_rate is not None and payroll is not None) else num(x.get("wc_cost"))
        suta_cost = (suta_rate / 100 * taxable if (suta_rate is not None and taxable is not None)
                     else num(x.get("suta_cost")))
        wc_rows.append({**x, "wc_cost": wc_cost, "suta_cost": suta_cost})
    r["wc_rows"] = wc_rows
    wc = [x["wc_cost"] for x in wc_rows]
    su = [x["suta_cost"] for x in wc_rows]
    r["wc_total"] = sum(v for v in wc if v is not None) if any(v is not None for v in wc) else None
    r["suta_total"] = sum(v for v in su if v is not None) if any(v is not None for v in su) else None
    r["payroll_total"] = sum(num(x.get("payroll")) or 0 for x in wc_rows) or None
    r["wc_ees"] = sum(num(x.get("ees")) or 0 for x in wc_rows) or None

    # Admin
    pr = p.get("pricing", {})
    pepm = num(pr.get("admin_pepm"))
    ees = num(pr.get("admin_employee_count")) or num(p["client"].get("employee_count")) or r["wc_ees"]
    r["admin_pepm"] = pepm
    r["admin_ees"] = ees
    r["admin_annual"] = pepm * ees * 12 if (pepm is not None and ees) else None
    r["setup_fee"] = num(pr.get("setup_fee"))
    r["ancillary_annual"] = num(p.get("proposed_ancillary_annual"))

    # Totals (VensureHR proposed)
    nonmed = [r["admin_annual"], r["wc_total"], r["suta_total"], r["ancillary_annual"]]
    r["nonmedical"] = sum(v for v in nonmed if v is not None)
    r["recurring"] = r["nonmedical"] + (med_pro or 0)
    r["year1"] = r["recurring"] + (r["setup_fee"] or 0)

    # Comparison against the incumbent
    cur = {
        "admin": num(inc.get("admin_annual")), "wc": num(inc.get("wc_annual")),
        "suta": num(inc.get("suta_annual")), "ancillary": num(inc.get("ancillary_annual")),
        "other": num(inc.get("other_annual")),
    }
    r["current"] = cur
    needed = [cur["admin"], cur["wc"], cur["suta"]]
    r["full_comparison"] = all(v is not None for v in needed)
    if r["full_comparison"]:
        cur_total = (med_cur or 0) + sum(v or 0 for v in cur.values())
        r["current_total"] = cur_total
        r["all_in_savings"] = cur_total - r["recurring"]
        r["all_in_savings_y1"] = cur_total - r["year1"]
    else:
        r["current_total"] = None
        r["all_in_savings"] = None
        r["all_in_savings_y1"] = None
    r["break_even"] = r["nonmedical"] - (med_sav or 0)
    r["break_even_y1"] = r["break_even"] + (r["setup_fee"] or 0)
    r["break_even_pepm"] = (r["break_even"] / ees / 12) if ees else None
    return r


def merge_ai(base: dict, ai: dict) -> dict:
    """Overlay AI-drafted content onto the form-seeded proposal.

    Anything the consultant typed on the form, and the deterministic pricing-illustration
    rows, win over the AI draft.
    """
    out = copy.deepcopy(base)
    for key in ("recap", "executive", "medical", "dental", "vision", "roi", "rollout"):
        if isinstance(ai.get(key), dict):
            for k, v in ai[key].items():
                if v not in (None, "", []):
                    out[key][k] = v
    for key in ("ancillary_recommendation", "additional_coverage", "additional_note", "service_callout"):
        if ai.get(key) not in (None, "", []):
            out[key] = ai[key]
    if not base["wc_suta"]["rows"] and ai.get("wc_suta", {}).get("rows"):
        out["wc_suta"]["rows"] = ai["wc_suta"]["rows"]
    if ai.get("wc_suta", {}).get("note"):
        out["wc_suta"]["note"] = ai["wc_suta"]["note"]
    for k, v in (ai.get("client") or {}).items():
        if not out["client"].get(k) and v not in (None, "", []):
            out["client"][k] = v
    for k, v in (ai.get("pricing") or {}).items():
        if out["pricing"].get(k) in (None, "") and v not in (None, ""):
            out["pricing"][k] = v
    for k, v in (ai.get("incumbent") or {}).items():
        if out["incumbent"].get(k) is None and v is not None:
            out["incumbent"][k] = v
    if out.get("proposed_ancillary_annual") is None and ai.get("proposed_ancillary_annual") is not None:
        out["proposed_ancillary_annual"] = ai["proposed_ancillary_annual"]
    apply_defaults(out)
    return out


def token_values(r: dict, p: dict) -> dict:
    """Values for {token} placeholders in narrative text (see ai.TOKENS)."""
    def m(v):
        return "TBD" if v is None else (f"(${abs(v):,.2f})" if v < 0 else f"${v:,.2f}")

    def pct(v):
        return "TBD" if v is None else f"{v:.2f}%"

    med = r["medical"]
    all_pct = (r["all_in_savings"] / r["current_total"] * 100) if (
        r["all_in_savings"] is not None and r["current_total"]) else None
    ees = r["admin_ees"]
    return {
        "medical_savings": m(med["savings"]), "medical_savings_pct": pct(med["pct"]),
        "medical_current": m(med["current"]), "medical_proposed": m(med["proposed"]),
        "admin_annual": m(r["admin_annual"]),
        "admin_pepm": "TBD" if r["admin_pepm"] is None else f"${r['admin_pepm']:,.0f}",
        "wc_total": m(r["wc_total"]), "suta_total": m(r["suta_total"]),
        "nonmedical_total": m(r["nonmedical"]), "recurring_total": m(r["recurring"]),
        "year1_total": m(r["year1"]), "setup_fee": m(r["setup_fee"]), "break_even": m(r["break_even"]),
        "all_in_savings": m(r["all_in_savings"]), "all_in_savings_pct": pct(all_pct),
        "employee_count": "TBD" if not ees else f"{ees:,.0f}",
    }


def fill_tokens(obj, values: dict):
    """Recursively replace {token} placeholders in every string of the proposal."""
    if isinstance(obj, str):
        return re.sub(r"\{(\w+)\}", lambda mt: values.get(mt.group(1), mt.group(0)), obj)
    if isinstance(obj, list):
        return [fill_tokens(x, values) for x in obj]
    if isinstance(obj, dict):
        return {k: fill_tokens(v, values) for k, v in obj.items()}
    return obj
