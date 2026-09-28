"""Draft the proposal narrative and extract rate tables from the uploaded documents with Claude."""

from __future__ import annotations

import base64
import json
import os

import anthropic

from .extract import CATEGORIES, Extraction
from .model import num

MODEL = os.environ.get("PROPOSAL_MODEL", "claude-opus-5")
EFFORT = os.environ.get("PROPOSAL_EFFORT", "high")

MAX_PDF_BYTES = 20 * 1024 * 1024  # raw PDF bytes sent as documents (base64 adds ~33%; request cap is 32 MB)
MAX_PDF_PAGES = 500

# Tokens the model may use in narrative; the renderer replaces them with computed values so
# the words always agree with the tables.
TOKENS = {
    "medical_savings": "annual medical savings ($)",
    "medical_savings_pct": "medical savings as a percent of current premium",
    "medical_current": "current annual medical premium ($)",
    "medical_proposed": "proposed annual medical premium ($)",
    "admin_annual": "annual VensureHR admin fee ($)",
    "admin_pepm": "admin fee per employee per month ($)",
    "wc_total": "estimated annual workers' comp ($)",
    "suta_total": "estimated annual SUTA ($)",
    "nonmedical_total": "VensureHR recurring non-medical cost ($)",
    "recurring_total": "VensureHR recurring annual total ($)",
    "year1_total": "estimated Year 1 total incl. setup ($)",
    "setup_fee": "one-time setup fee ($)",
    "break_even": "incumbent non-medical cost at which VensureHR breaks even ($)",
    "all_in_savings": "annual all-in savings vs incumbent ($; only when incumbent costs are known)",
    "all_in_savings_pct": "all-in savings percent",
    "employee_count": "employee count",
}


def _s():
    return {"type": "string"}


def _n():
    # Numbers travel as strings ("" when unknown) to keep the schema free of union types;
    # _coerce_numbers() converts them back after the response is parsed.
    return {"type": "string", "description": "plain number such as 1317.99, or empty string if unknown"}


NUMERIC_KEYS = {
    "employee_count", "admin_pepm", "setup_fee", "count", "current_rate", "proposed_rate", "ee", "es", "ec",
    "fam", "ees", "payroll", "taxable_wages", "wc_rate", "wc_cost", "suta_rate", "suta_cost", "medical_annual",
    "admin_annual", "wc_annual", "suta_annual", "ancillary_annual", "other_annual", "proposed_ancillary_annual",
}


def _coerce_numbers(obj):
    if isinstance(obj, list):
        return [_coerce_numbers(x) for x in obj]
    if isinstance(obj, dict):
        return {k: (num(v) if k in NUMERIC_KEYS and not isinstance(v, (dict, list)) else _coerce_numbers(v))
                for k, v in obj.items()}
    return obj


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


SCHEMA = _obj({
    "client": _obj({"name": _s(), "industry": _s(), "employee_count": _n(), "states": _arr(_s()),
                    "incumbent_name": _s(), "contact_name": _s(), "contact_title": _s()}),
    "pricing": _obj({"admin_pepm": _n(), "setup_fee": _n()}),
    "recap": _obj({
        "intro": _s(),
        "rows": _arr(_obj({"heard": _s(), "means": _s(), "changes": _s()})),
        "commitment": _s(),
    }),
    "executive": _obj({"bottom_line": _s()}),
    "medical": _obj({
        "current_carrier": _s(), "proposed_carrier": _s(), "intro": _s(), "footnote": _s(),
        "plans": _arr(_obj({
            "current_name": _s(), "proposed_name": _s(),
            "features": _arr(_obj({"feature": _s(), "current": _s(), "proposed": _s()})),
            "tiers": _arr(_obj({"tier": _s(), "count": _n(), "current_rate": _n(), "proposed_rate": _n()})),
        })),
    }),
    "dental": _obj({
        "rows": _arr(_obj({"plan": _s(), "coinsurance": _s(), "annual_max": _s(), "ortho": _s(),
                           "ee": _n(), "es": _n(), "ec": _n(), "fam": _n()})),
        "note": _s(),
    }),
    "vision": _obj({
        "rows": _arr(_obj({"plan": _s(), "exam_materials": _s(), "frames": _s(), "contacts": _s(),
                           "ee": _n(), "es": _n(), "ec": _n(), "fam": _n()})),
        "note": _s(),
    }),
    "ancillary_recommendation": _s(),
    "additional_coverage": _arr(_obj({"coverage": _s(), "options": _s(), "rate": _s()})),
    "additional_note": _s(),
    "wc_suta": _obj({
        "rows": _arr(_obj({"state": _s(), "class_code": _s(), "ees": _n(), "payroll": _n(), "taxable_wages": _n(),
                           "wc_rate": _n(), "wc_cost": _n(), "suta_rate": _n(), "suta_cost": _n(),
                           "suta_note": _s()})),
        "note": _s(),
    }),
    "incumbent": _obj({"medical_annual": _n(), "admin_annual": _n(), "wc_annual": _n(), "suta_annual": _n(),
                       "ancillary_annual": _n(), "other_annual": _n(), "other_label": _s()}),
    "proposed_ancillary_annual": _n(),
    "roi": _obj({
        "title": _s(), "intro": _s(),
        "rows": _arr(_obj({"item": _s(), "current": _s(), "proposed": _s(), "difference": _s(), "note": _s()})),
        "takeaways": _arr(_s()),
    }),
    "rollout": _obj({
        "intro": _s(),
        "phases": _arr(_obj({"phase": _s(), "timing": _s(), "what": _s(), "who": _s()})),
        "things_to_know": _arr(_s()),
        "next_step": _s(),
    }),
    "service_callout": _s(),
    "open_questions": _arr(_s()),
})

SYSTEM = """You are a senior PEO Business Consultant at VensureHR. You turn a prospect's supporting documents \
into the data and narrative for a VensureHR-branded All-In Cost Proposal. A separate program lays out the PDF \
and computes every total, so your job is accurate extraction plus clear, persuasive writing.

Accuracy rules (these matter more than anything else):
- Use only figures that appear in the uploaded documents or the consultant's intake form. Never estimate, \
round, or invent a rate, enrollment count, fee or incumbent cost. If a value is not in the material, use null \
(numbers are written as plain strings like \"1317.99\"; use \"\" when unknown) or an empty string/list, and list what is missing in open_questions.
- Rates are MONTHLY per-tier premiums. Tier counts are enrolled employees per tier (from a census, incumbent \
bill, or rate comparison). If the documents give a rate but no enrollment, set count to null.
- "Medical Rates" and "Incumbent Data" documents describe what the client pays today (current). "Aetna Rates" \
describes the proposed VensureHR medical plans. Match each current plan to the proposed plan with the closest \
design (deductible, out-of-pocket max, copays) and list the design features side by side, calling out real \
differences. If there are no current medical rates, return proposed plans with current_rate null.
- Ancillary packets can have several banded rate sheets. Pick the band that fits the group size when the \
documents say how bands are assigned; otherwise present the first band and say so in the note. Keep the dental \
table to at most six plans and the vision table to at most three, and put life, disability, accident, critical \
illness and hospital indemnity in additional_coverage.
- Workers' comp / SUTA rows: if the deterministic pricing-illustration data below already has rows, return an \
empty wc_suta.rows (the program uses the spreadsheet's numbers); only extract rows when no pricing illustration \
was parsed. WC rate is per $100 of payroll; SUTA rate is a percent.
- incumbent.*_annual are what the client pays their current provider per year for each cost area, only when a \
document (invoice, bill, ROI analysis) states it. Annualize a monthly or per-payroll figure only when the \
frequency is explicit, and mention that you did so in open_questions.
- proposed_ancillary_annual is the employer's annual cost of ancillary coverage the client has elected; leave \
null unless elections and rates are both in the documents.
- ROI section: summarize the uploaded Excel ROI analysis (if any) as rows of item / current / proposed / \
difference / note, using the workbook's own numbers as text (e.g. "$12,400.00"). Leave empty if no ROI file.

Writing rules:
- Voice: warm, direct, plain English a busy owner can skim. Short sentences. Speak to the client as "you". \
No filler, no hype words, no emojis.
- The recap section uses the meeting transcripts and notes: 3-6 rows of what the client told us (in their \
words), what it means day to day, and what changes with VensureHR. The intro paragraph restates their situation \
and priorities. commitment starts with "**Our commitment:**" and explains that numbers come only from the \
documents provided and that missing items are marked rather than guessed.
- You may use **bold** for emphasis. Do not use other markdown.
- When a narrative sentence needs a computed total, write a token instead of a number so the words always \
match the tables. Available tokens: {tokens}. Example: "an estimated {{medical_savings}} saved per year \
({{medical_savings_pct}})". Only use a token when the inputs for it exist.
- executive.bottom_line: leave empty to let the program write its standard bottom-line paragraph, unless the \
documents give you something more specific to say.
- rollout: leave phases empty to use VensureHR's standard seven-phase timeline back-scheduled from the \
effective date, unless the transcripts set specific dates or steps. things_to_know and next_step should reflect \
this client's situation (their incumbent's name, COBRA, termination notice, open items).
- service_callout: one or two sentences, starting with a bold lead-in, tying VensureHR's named service team to \
the client's stated pain points.
- Leave client/pricing fields empty or null when the intake form already provides them."""


def _document_blocks(ex: Extraction) -> tuple[list[dict], list[str]]:
    blocks, notes = [], []
    pdf_bytes = pdf_pages = 0
    for i, d in enumerate(ex.docs, 1):
        label = f"Document {i} | Category: {CATEGORIES.get(d.category, d.category)} | File: {d.name}"
        if d.kind == "pdf" and pdf_bytes + len(d.data) <= MAX_PDF_BYTES and pdf_pages + d.pages <= MAX_PDF_PAGES:
            pdf_bytes += len(d.data)
            pdf_pages += d.pages
            blocks.append({"type": "text", "text": label})
            blocks.append({"type": "document", "title": d.name[:200],
                           "source": {"type": "base64", "media_type": "application/pdf",
                                      "data": base64.standard_b64encode(d.data).decode()}})
        elif d.kind == "image":
            blocks.append({"type": "text", "text": label})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": d.media_type,
                                                        "data": base64.standard_b64encode(d.data).decode()}})
        else:
            if d.kind == "pdf":
                notes.append(f"{d.name}: sent as extracted text (PDF size/page budget reached).")
            blocks.append({"type": "text", "text": f"{label}\n<document_text>\n{d.text}\n</document_text>"})
    return blocks, notes


def draft(form: dict, ex: Extraction) -> tuple[dict, list[str]]:
    """Return (ai_proposal_fields, warnings)."""
    client = anthropic.Anthropic()
    blocks, notes = _document_blocks(ex)
    intake = {k: v for k, v in form.items() if str(v).strip()}
    pricing = ex.pricing or "No pricing illustration was uploaded or recognized."
    intro = (
        "Draft the All-In Cost Proposal data for this prospect.\n\n"
        f"<intake_form>\n{json.dumps(intake, indent=1)}\n</intake_form>\n\n"
        f"<pricing_illustration_parsed>\n{json.dumps(pricing, indent=1, default=str)}\n"
        "</pricing_illustration_parsed>\n\n"
        f"The consultant uploaded {len(ex.docs)} document(s); they follow. "
        "Consultant notes in the intake form take priority over documents when they conflict."
    )
    content = [{"type": "text", "text": intro}] + blocks
    if not ex.docs:
        content.append({"type": "text", "text": "No documents were uploaded; work from the intake form only."})
    system = SYSTEM.format(tokens=", ".join("{" + k + "}" for k in TOKENS))

    params = dict(
        model=MODEL,
        max_tokens=64000,
        system=system,
        thinking={"type": "adaptive"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )
    try:
        msg = _run(client, params, {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}})
    except anthropic.BadRequestError as exc:
        if "schema" not in str(exc).lower():
            raise
        # Structured-output schema rejected: ask for the same JSON in plain text instead.
        params["system"] = system + "\n\nReturn only one JSON object matching this JSON Schema, with no other " \
            "text:\n" + json.dumps(SCHEMA)
        msg = _run(client, params, {"effort": EFFORT})

    if msg.stop_reason == "refusal":
        raise RuntimeError("The model declined to draft this proposal. Review the uploaded files and try again.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("The draft was cut off before it finished. Try uploading fewer or smaller files.")
    text = "".join(b.text for b in msg.content if b.type == "text")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("The model's reply did not contain proposal data.")
    data = _coerce_numbers(json.loads(text[start:end + 1]))
    warnings = notes + [f"Open item: {q}" for q in data.pop("open_questions", []) if q]
    return data, warnings


def _run(client, params: dict, output_config: dict):
    with client.beta.messages.stream(output_config=output_config, **params) as stream:
        return stream.get_final_message()
