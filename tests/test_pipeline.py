"""End-to-end checks against the QCIC sample proposal's published numbers."""

import copy
import io
import json
import os

import pytest

from proposal_tool import ai, model
from proposal_tool.extract import extract_files
from proposal_tool.pdf import build_pdf
from proposal_tool.pricing import parse_pricing_illustration

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
PRICING = os.path.join(FIX, "qcic_pricing_illustration.xlsm")
TEMPLATE = os.path.join(ROOT, "VensureHR Pricing Illustration (Admin, WC, Taxes) - 2026 TEMPLATE UPDATED 3.xlsm")
ANCILLARY_ZIP = os.path.join(ROOT, "2026-27 MetLife Ancillaries.zip")


def load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


@pytest.fixture
def qcic():
    p = model.from_form(load("qcic_form.json"), parse_pricing_illustration(PRICING))
    return model.merge_ai(p, load("qcic_ai_draft.json"))


def test_pricing_illustration_matches_sample():
    d = parse_pricing_illustration(PRICING)
    assert d["admin_pepm"] == 100 and d["setup_fee"] == 1500 and d["company"] == "QCIC, Inc."
    assert len(d["rows"]) == 9
    assert round(sum(r["wc_cost"] for r in d["rows"]), 2) == 2150.70
    assert round(sum(r["suta_cost"] or 0 for r in d["rows"]), 2) == 9024.64
    pa = next(r for r in d["rows"] if r["state"] == "PA")
    assert pa["suta_cost"] is None and pa["suta_note"] == "Client Report"
    names = [a["name"] for a in d["addons"]]
    assert "Applicant Tracking System" in names and len(names) == 7  # only the 1-20 tier kept


def test_blank_template_has_no_rows():
    d = parse_pricing_illustration(TEMPLATE)
    assert d is not None and d["rows"] == [] and d["admin_pepm"] == 145


def test_compute_matches_sample(qcic):
    r = model.compute(qcic)
    med = r["medical"]
    assert med["enrolled"] == 9
    assert round(med["current"], 2) == 212268.00
    assert round(med["proposed"], 2) == 202377.24
    assert round(med["savings"], 2) == 9890.76
    assert round(med["pct"], 2) == 4.66
    assert r["admin_annual"] == 24000
    assert round(r["nonmedical"], 2) == 35175.34
    assert round(r["recurring"], 2) == 237552.58
    assert round(r["year1"], 2) == 239052.58
    assert round(r["break_even"], 2) == 25284.58
    assert round(r["break_even_y1"], 2) == 26784.58
    assert round(r["break_even_pepm"], 2) == 105.35
    assert not r["full_comparison"]


def test_full_comparison_when_incumbent_known(qcic):
    qcic["incumbent"].update(admin_annual=30000, wc_annual=3000, suta_annual=9500)
    r = model.compute(qcic)
    assert r["full_comparison"]
    assert round(r["current_total"], 2) == 212268 + 42500
    assert round(r["all_in_savings"], 2) == round(254768 - 237552.5804525, 2)


def test_wc_cost_follows_edited_rate(qcic):
    qcic["wc_suta"]["rows"][0]["wc_rate"] = 1.0  # FL: $122,381.90 payroll
    r = model.compute(qcic)
    assert round(r["wc_rows"][0]["wc_cost"], 2) == 1223.82


def test_rollout_dates_match_sample(qcic):
    timing = [ph["timing"] for ph in qcic["rollout"]["phases"]]
    assert timing[:5] == ["Oct 5 - Oct 16", "Oct 19 - Nov 6", "Nov 9 - Nov 27", "Nov 30 - Dec 11", "Dec 14 - Dec 23"]


def test_tokens_fill_from_computed(qcic):
    qcic["recap"]["intro"] = "Save {medical_savings} ({medical_savings_pct}); keep {unknown_token}."
    out = model.fill_tokens(qcic, model.token_values(model.compute(qcic), qcic))
    assert out["recap"]["intro"] == "Save $9,890.76 (4.66%); keep {unknown_token}."


@pytest.mark.parametrize("variant", ["full", "comparison", "empty", "no_sections"])
def test_pdf_builds(qcic, variant):
    p = copy.deepcopy(qcic)
    if variant == "comparison":
        p["incumbent"].update(admin_annual=30000, wc_annual=3000, suta_annual=9500)
        p["roi"]["rows"] = [{"item": "Total cost", "current": "$254,768.00", "proposed": "$237,552.58",
                             "difference": "$17,215.42", "note": "From ROI workbook"}]
    elif variant == "empty":
        p = model.from_form({}, None)
    elif variant == "no_sections":
        p["sections"] = {k: False for k in model.SECTION_KEYS}
    data = build_pdf(p)
    assert data.startswith(b"%PDF") and len(data) > 3000


def test_ai_numbers_are_coerced():
    out = ai._coerce_numbers({"medical": {"plans": [{"tiers": [{"tier": "EE", "count": "5", "current_rate": "$1,432.00",
                                                                 "proposed_rate": ""}]}]},
                              "incumbent": {"admin_annual": "24000", "other_label": "Other"}})
    t = out["medical"]["plans"][0]["tiers"][0]
    assert t == {"tier": "EE", "count": 5.0, "current_rate": 1432.0, "proposed_rate": None}
    assert out["incumbent"] == {"admin_annual": 24000.0, "other_label": "Other"}


def test_extract_zip_and_excel():
    with open(ANCILLARY_ZIP, "rb") as f:
        zdata = f.read()
    with open(PRICING, "rb") as f:
        xdata = f.read()
    ex = extract_files([("ancillary", "metlife.zip", zdata), ("pricing_illustration", "pi.xlsm", xdata),
                        ("transcripts", "call.txt", b"We pay too much.")])
    kinds = [d.kind for d in ex.docs]
    assert kinds.count("pdf") == 24 and kinds.count("text") == 2
    assert ex.pricing and ex.pricing["file"] == "pi.xlsm"
    assert "Rates(EE / ES / EC / Fam)" in next(d.text for d in ex.docs if "Dental Band 1" in d.name)


def test_draft_endpoint_with_stubbed_ai(monkeypatch):
    import app as webapp

    drafted = ai._coerce_numbers(load("qcic_ai_draft.json"))
    monkeypatch.setattr(webapp, "ai_available", lambda: True)
    monkeypatch.setattr(ai, "draft", lambda form, ex: (drafted, ["Open item: current Justworks invoice"]))
    client = webapp.app.test_client()
    form = dict(load("qcic_form.json"))
    with open(PRICING, "rb") as f:
        form["pricing_illustration"] = (io.BytesIO(f.read()), "qcic.xlsm")
    res = client.post("/api/draft", data=form, content_type="multipart/form-data")
    body = res.get_json()
    assert res.status_code == 200 and body["ai_used"]
    p = body["proposal"]
    assert p["client"]["name"] == "QCIC, Inc." and len(p["medical"]["plans"]) == 3
    assert len(p["wc_suta"]["rows"]) == 9  # spreadsheet rows win over AI rows
    assert "Open item: current Justworks invoice" in body["warnings"]
    res = client.post("/api/pdf", json=p)
    assert res.status_code == 200 and res.data.startswith(b"%PDF")


def test_login_required_when_password_set(monkeypatch):
    import base64
    import app as webapp

    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    client = webapp.app.test_client()
    assert client.get("/").status_code == 401
    assert client.get("/healthz").status_code == 200
    bad = base64.b64encode(b"vensurehr:wrong").decode()
    assert client.get("/api/config", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"vensurehr:s3cret").decode()
    assert client.get("/api/config", headers={"Authorization": f"Basic {good}"}).status_code == 200


def test_open_when_no_password(monkeypatch):
    import app as webapp

    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert webapp.app.test_client().get("/api/config").status_code == 200
