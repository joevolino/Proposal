"""Render a proposal JSON into a VensureHR-branded, portrait (US Letter) PDF."""

from __future__ import annotations

import io
import os
import re
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from . import brand as B
from .model import compute, fill_tokens, long_date, num, parse_date, short_date, token_values

W, H = letter
MX = 46  # side margin
HEADER_H = 52
CONTENT_W = W - 2 * MX
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

# ---------------------------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------------------------


def md(text) -> str:
    """Escape text for ReportLab and support **bold**, *italic* and line breaks."""
    s = escape("" if text is None else str(text))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return s.replace("\n", "<br/>")


def money(v, cents=True, parens=True) -> str:
    n = num(v)
    if n is None:
        return "TBD"
    s = f"${abs(n):,.2f}" if cents else f"${abs(round(n)):,.0f}"
    if n < 0 and round(abs(n), 2) > 0:
        return f"({s})" if parens else f"-{s}"
    return s


def rate_str(v, pct=False, places=4) -> str:
    n = num(v)
    if n is None:
        return "" if v in (None, "") else str(v)
    if pct:
        return f"{n:.2f}%"
    return f"{n:.{places}f}"


def count_str(v) -> str:
    n = num(v)
    if n is None:
        return ""
    return f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"


def rate_cell(v) -> str:
    n = num(v)
    if n is None:
        return "" if v in (None, "") else str(v)
    return money(n)


# ---------------------------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------------------------

def _style(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=B.INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


S = {
    "body": _style("body", alignment=TA_JUSTIFY, spaceAfter=6),
    "body_left": _style("body_left", spaceAfter=4),
    "subtitle": _style("subtitle", fontName="Helvetica-Oblique", textColor=B.MUTED, fontSize=9.5, spaceAfter=10),
    "h2": _style("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=B.NAVY,
                 spaceBefore=12, spaceAfter=5),
    "small": _style("small", fontSize=7.5, leading=10, textColor=B.MUTED, spaceBefore=4, spaceAfter=4),
    "cell": _style("cell", fontSize=8, leading=10.2, alignment=TA_CENTER),
    "cell_l": _style("cell_l", fontSize=8, leading=10.2),
    "cell_r": _style("cell_r", fontSize=8, leading=10.2, alignment=TA_RIGHT),
    "cell_b": _style("cell_b", fontName="Helvetica-Bold", fontSize=8, leading=10.2, textColor=B.NAVY),
    "th": _style("th", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=B.WHITE),
    "th_c": _style("th_c", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=B.WHITE, alignment=TA_CENTER),
    "kpi_v": _style("kpi_v", fontName="Helvetica-Bold", fontSize=19, leading=23, alignment=TA_CENTER),
    "kpi_l": _style("kpi_l", fontSize=8, leading=10.5, alignment=TA_CENTER, textColor=B.MUTED),
    "callout": _style("callout", fontSize=9, leading=13, textColor=B.INK),
    "bullet": _style("bullet", fontSize=9, leading=12.5, leftIndent=12, bulletIndent=2, spaceAfter=3),
}


def P(text, style="body"):
    return Paragraph(md(text), S[style] if isinstance(style, str) else style)


# ---------------------------------------------------------------------------------------------
# Flowables
# ---------------------------------------------------------------------------------------------


class SectionHeader(Flowable):
    def __init__(self, number, title):
        super().__init__()
        self.number, self.title = number, title
        self.height = 34

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(B.ORANGE)
        c.rect(0, 2, 28, 28, stroke=0, fill=1)
        c.setFillColor(B.WHITE)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(14, 11.5, str(self.number))
        c.setFillColor(B.NAVY)
        c.setFont("Helvetica-Bold", 19)
        c.drawString(40, 9, self.title)


def section(story, number, title, subtitle=""):
    story.append(SectionHeader(number, title))
    if subtitle:
        story.append(P(subtitle, "subtitle"))
    else:
        story.append(Spacer(1, 8))


def table(header, rows, widths, align=None, first_bold=True, highlight=(), shade=(), header_color=B.NAVY,
          header_align=None, font_rows=()):
    """Build a branded table. rows contain str or Paragraph cells."""
    ncol = len(widths)
    align = align or (["L"] + ["C"] * (ncol - 1))
    header_align = header_align or ["L"] * ncol
    data = []
    if header:
        data.append([Paragraph(md(h), S["th_c"] if header_align[i] == "C" else S["th"]) for i, h in enumerate(header)])
    off = 1 if header else 0
    for ri, row in enumerate(rows):
        cells = []
        for i, v in enumerate(row):
            if isinstance(v, Flowable):
                cells.append(v)
                continue
            if i == 0 and first_bold:
                st = S["cell_b"]
            else:
                st = {"L": S["cell_l"], "C": S["cell"], "R": S["cell_r"]}[align[i]]
            txt = md(v)
            if ri in highlight or ri in font_rows:
                txt = f"<b>{txt}</b>"
            cells.append(Paragraph(txt, st))
        data.append(cells)
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, off), (-1, -1), 0.5, B.RULE),
        ("BOX", (0, 0), (-1, -1), 0.5, B.RULE),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, B.RULE),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), header_color), ("TOPPADDING", (0, 0), (-1, 0), 5),
                 ("BOTTOMPADDING", (0, 0), (-1, 0), 5)]
    for ri in range(len(rows)):
        if ri % 2 == 1:
            cmds.append(("BACKGROUND", (0, ri + off), (-1, ri + off), B.LIGHT))
    for ri in shade:
        cmds.append(("BACKGROUND", (0, ri + off), (-1, ri + off), colors_e0()))
    for ri in highlight:
        cmds.append(("BACKGROUND", (0, ri + off), (-1, ri + off), B.PEACH))
    t.setStyle(TableStyle(cmds))
    return t


def colors_e0():
    from reportlab.lib import colors
    return colors.HexColor("#E6E9EE")


def callout(text, bg=B.PEACH_2, bar=B.ORANGE):
    t = Table([[Paragraph(md(text), S["callout"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 4, bar),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def kpi_tiles(tiles):
    tiles = tiles[:4]
    palette = [B.GREEN, B.TEAL, B.ORANGE, B.NAVY]
    n = len(tiles)
    gap = 4
    w = (CONTENT_W - gap * (n - 1)) / n
    cells, widths, cmds = [], [], []
    for i, tl in enumerate(tiles):
        col = palette[i % 4]
        v = ParagraphStyle(f"kv{i}", parent=S["kpi_v"], textColor=col)
        cells.append([Paragraph(md(tl.get("value", "")), v), Paragraph(md(tl.get("label", "")), S["kpi_l"])])
        widths.append(w)
        if i < n - 1:
            cells.append("")
            widths.append(gap)
    t = Table([cells], colWidths=widths)
    for i in range(n):
        ci = i * 2
        cmds += [("BACKGROUND", (ci, 0), (ci, 0), B.LIGHT),
                 ("LINEABOVE", (ci, 0), (ci, 0), 3.5, palette[i % 4])]
    cmds += [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 12),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 12), ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    t.setStyle(TableStyle(cmds))
    return t


def bullets(items):
    return [Paragraph(md(x), S["bullet"], bulletText="■") for x in items if str(x).strip()]


def diff_cell(cur, pro):
    """Proposed minus current: savings in green parentheses, increases in red."""
    c, p = num(cur), num(pro)
    if c is None or p is None:
        return "TBD"
    d = p - c
    color = "#1E8E5A" if d < 0 else ("#C0392B" if d > 0 else "#2B3140")
    return Paragraph(f'<font color="{color}">{money(d)}</font>', S["cell"])


# ---------------------------------------------------------------------------------------------
# Page decoration
# ---------------------------------------------------------------------------------------------


def draw_logo(c, x, y, size=1.0):
    """VensureHR wordmark for dark backgrounds. Uses assets/logo.png when provided."""
    path = os.path.join(ASSETS, "logo.png")
    if os.path.exists(path):
        from reportlab.lib.utils import ImageReader
        img = ImageReader(path)
        iw, ih = img.getSize()
        h = 26 * size
        c.drawImage(img, x, y - 4 * size, width=h * iw / ih, height=h, mask="auto")
        return
    s = size
    c.saveState()
    # swoosh mark
    c.setStrokeColor(B.WHITE)
    c.setLineWidth(2.6 * s)
    c.setLineCap(1)
    p = c.beginPath()
    p.moveTo(x + 1 * s, y + 3 * s)
    p.curveTo(x + 8 * s, y - 3 * s, x + 18 * s, y + 2 * s, x + 21 * s, y + 13 * s)
    c.drawPath(p, stroke=1, fill=0)
    p = c.beginPath()
    p.moveTo(x + 4 * s, y + 17 * s)
    p.curveTo(x + 10 * s, y + 13 * s, x + 14 * s, y + 6 * s, x + 12 * s, y - 2 * s)
    c.drawPath(p, stroke=1, fill=0)
    c.setFillColor(B.ORANGE)
    c.circle(x + 9 * s, y + 20 * s, 3.2 * s, stroke=0, fill=1)
    # word mark
    c.setFillColor(B.WHITE)
    c.setFont("Helvetica", 21 * s)
    c.drawString(x + 22 * s, y, "Vensure")
    tw = c.stringWidth("Vensure", "Helvetica", 21 * s)
    c.setFillColor(B.ORANGE)
    c.setFont("Helvetica-Bold", 21 * s)
    c.drawString(x + 22 * s + tw, y, "HR")
    c.restoreState()


class Doc(BaseDocTemplate):
    def __init__(self, buf, proposal):
        super().__init__(buf, pagesize=letter, leftMargin=MX, rightMargin=MX, topMargin=HEADER_H + 30,
                         bottomMargin=56, title=f"{proposal['client'].get('name') or 'Client'} - VensureHR All-In "
                         "Cost Proposal", author=proposal["consultant"].get("name") or "VensureHR",
                         subject="All-In Cost Proposal", creator="VensureHR Proposal Builder")
        self.p = proposal
        cover = Frame(0, 0, W, H, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        body = Frame(MX, 56, CONTENT_W, H - HEADER_H - 30 - 56, id="body", leftPadding=0, rightPadding=0,
                     topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover], onPage=self.draw_cover),
            PageTemplate(id="body", frames=[body], onPage=self.draw_page),
        ])

    # -- cover --------------------------------------------------------------------------------
    def draw_cover(self, c, doc):
        p = self.p
        cl, k = p["client"], p["consultant"]
        eff = parse_date(cl.get("effective_date"))
        c.saveState()
        c.setFillColor(B.NAVY)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        # brand arcs
        c.setLineCap(0)
        for (cx, cy, r, width, col, a0, a1) in ((167, 249, 591, 12, B.TEAL, 25, 85),
                                                (-95, 54, 809, 25, B.ORANGE, 15, 80)):
            c.setStrokeColor(col)
            c.setLineWidth(width)
            path = c.beginPath()
            path.arc(cx - r, cy - r, cx + r, cy + r, startAng=a0, extent=a1 - a0)
            c.drawPath(path, stroke=1, fill=0)
        draw_logo(c, 58, 505, 1.35)
        c.setFillColor(B.ORANGE)
        c.rect(58, 440, 80, 4, stroke=0, fill=1)
        c.setFillColor(B.WHITE)
        c.setFont("Helvetica-Bold", 29)
        c.drawString(58, 395, "All-In Cost Proposal")
        c.setFont("Helvetica", 14)
        c.drawString(58, 367, "Full-Service PEO  |  Benefits  |  Payroll  |  HR")
        c.setFillColor(B.ORANGE)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(58, 316, cl.get("name") or "Client Name")
        c.setFillColor(B.WHITE)
        c.setFont("Helvetica", 10)
        bits = []
        if cl.get("industry"):
            bits.append(cl["industry"])
        r = compute(p)
        ees = num(cl.get("employee_count")) or r.get("admin_ees")
        if ees:
            bits.append(f"~{count_str(ees)} Employees")
        states = cl.get("states") or []
        if states:
            bits.append(f"{len(states)} State{'s' if len(states) != 1 else ''}" if len(states) > 3
                        else ", ".join(states))
        y = 294
        if bits:
            c.drawString(58, y, "  |  ".join(bits))
            y -= 17
        c.drawString(58, y, f"Proposed Effective Date: {long_date(eff)}")
        if cl.get("contact_name"):
            y -= 17
            who = cl["contact_name"] + (f", {cl['contact_title']}" if cl.get("contact_title") else "")
            c.drawString(58, y, f"Prepared for: {who}")
        # footer band
        c.setFillColor(B.NAVY_2)
        c.rect(0, 0, W, 92, stroke=0, fill=1)
        c.setFillColor(B.ORANGE)
        c.rect(0, 92, W, 3, stroke=0, fill=1)
        c.setFillColor(B.WHITE)
        c.setFont("Helvetica-Bold", 9)
        prep = k.get("name") or "VensureHR"
        c.drawString(58, 58, f"Prepared by: {prep}, VensureHR" if k.get("name") else "Prepared by: VensureHR")
        c.setFont("Helvetica", 8.5)
        contact = [x for x in (f"C: {k['phone']}" if k.get("phone") else "", k.get("email", ""),
                               k.get("office_address", "")) if x]
        if contact:
            c.drawString(58, 43, "  |  ".join(contact))
        if k.get("title"):
            c.setFillColor(colors_lightgray())
            c.drawString(58, 28, k["title"])
        prepared = parse_date(p.get("prepared_date"))
        c.setFillColor(B.WHITE)
        c.setFont("Helvetica", 8.5)
        if prepared:
            c.drawRightString(W - 58, 58, f"{prepared:%B %Y}")
        c.drawRightString(W - 58, 43, "Confidential")
        c.restoreState()

    # -- body pages ---------------------------------------------------------------------------
    def draw_page(self, c, doc):
        p = self.p
        cl = p["client"]
        eff = parse_date(cl.get("effective_date"))
        c.saveState()
        c.setFillColor(B.NAVY)
        c.rect(0, H - HEADER_H, W, HEADER_H, stroke=0, fill=1)
        c.setFillColor(B.ORANGE)
        c.rect(0, H - HEADER_H - 3, W, 3, stroke=0, fill=1)
        draw_logo(c, MX, H - 34, 0.78)
        c.setFillColor(B.WHITE)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawRightString(W - MX, H - 24, f"{cl.get('name') or 'Client'}  |  All-In Cost Proposal")
        c.setFillColor(colors_lightgray())
        c.setFont("Helvetica", 7.5)
        c.drawRightString(W - MX, H - 36, f"Proposed Effective Date {short_date(eff)}")
        # footer
        c.setStrokeColor(B.RULE)
        c.setLineWidth(0.6)
        c.line(MX, 40, W - MX, 40)
        c.setFillColor(B.MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(MX, 27, f"VensureHR  |  {B.DISCLAIMER}")
        c.setFillColor(B.ORANGE)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(W - MX, 27, str(doc.page))
        c.restoreState()


def colors_lightgray():
    from reportlab.lib import colors
    return colors.HexColor("#B8C0CE")


# ---------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------


def build_pdf(p: dict) -> bytes:
    r = compute(p)
    p = fill_tokens(p, token_values(r, p))
    story = [NextPageTemplate("body"), PageBreak()]
    builders = [
        ("recap", _recap), ("executive", _executive), ("medical", _medical), ("ancillary", _ancillary),
        ("wc_suta", _wc_suta), ("total", _total), ("roi", _roi), ("rollout", _rollout),
    ]
    n = 0
    sections = p.get("sections") or {}
    for key, fn in builders:
        if not sections.get(key, True) or not _has(key, p, r):
            continue
        n += 1
        if n > 1:
            story.append(PageBreak())
        fn(story, n, p, r)
    if n == 0:
        story.append(P("No proposal content yet. Add client details and supporting documents, then regenerate."))
    buf = io.BytesIO()
    Doc(buf, p).build(story)
    return buf.getvalue()


def _has(key, p, r) -> bool:
    if key == "recap":
        return bool(p["recap"].get("intro") or p["recap"].get("rows"))
    if key == "medical":
        return bool(p["medical"].get("plans"))
    if key == "ancillary":
        return bool(p["dental"].get("rows") or p["vision"].get("rows") or p.get("additional_coverage"))
    if key == "wc_suta":
        return bool(p["wc_suta"].get("rows") or r["admin_annual"] is not None)
    if key == "roi":
        return bool(p["roi"].get("rows") or p["roi"].get("intro"))
    if key in ("executive", "total"):
        return any(v is not None for v in (r["admin_annual"], r["wc_total"], r["suta_total"],
                                          r["medical"]["proposed"], r["medical"]["current"]))
    return True


def _names(p):
    cl = p["client"]
    return cl.get("name") or "the client", cl.get("incumbent_name") or "Current Provider"


def _recap(story, n, p, r):
    name, _ = _names(p)
    rc = p["recap"]
    section(story, n, "Recap of the Problem", f"What we heard from {name}, and how this proposal answers it.")
    if rc.get("intro"):
        story.append(P(rc["intro"]))
    rows = [[x.get("heard", ""), x.get("means", ""), x.get("changes", "")] for x in rc.get("rows", [])]
    if rows:
        story.append(Spacer(1, 4))
        story.append(table(["What you told us", "What this means day to day", "What changes with VensureHR"], rows,
                           [CONTENT_W * 0.24, CONTENT_W * 0.36, CONTENT_W * 0.40], align=["L", "L", "L"]))
    if rc.get("commitment"):
        story.append(Spacer(1, 12))
        story.append(callout(rc["commitment"]))


def _executive(story, n, p, r):
    name, inc = _names(p)
    med = r["medical"]
    section(story, n, "Executive Summary", "The key numbers at a glance.")
    tiles = [t for t in p["executive"].get("highlights", []) if t.get("value")]
    if not tiles:
        tiles = _default_tiles(p, r)
    if tiles:
        story.append(kpi_tiles(tiles))
        story.append(Spacer(1, 12))

    ask = "Please provide invoice"
    rows, hl = [], []
    if med["proposed"] is not None or med["current"] is not None:
        label = f"Medical premiums ({count_str(med['enrolled'])} enrolled)" if med["enrolled"] else "Medical premiums"
        rows.append([label, money(med["current"]) if med["current"] is not None else ask, money(med["proposed"]),
                     diff_cell(med["current"], med["proposed"])])
    cur = r["current"]
    admin_detail = money(r["admin_annual"])
    if r["admin_pepm"] is not None and r["admin_ees"]:
        admin_detail += f"\n({money(r['admin_pepm'], cents=False)} PEPM x {count_str(r['admin_ees'])})"
    rows.append(["PEO / admin fee", money(cur["admin"]) if cur["admin"] is not None else ask, admin_detail,
                 diff_cell(cur["admin"], r["admin_annual"])])
    rows.append(["Workers' compensation", money(cur["wc"]) if cur["wc"] is not None else ask, money(r["wc_total"]),
                 diff_cell(cur["wc"], r["wc_total"])])
    rows.append(["State unemployment (SUTA)", money(cur["suta"]) if cur["suta"] is not None else ask,
                 money(r["suta_total"]), diff_cell(cur["suta"], r["suta_total"])])
    if cur["ancillary"] is not None or r["ancillary_annual"] is not None:
        rows.append(["Ancillary benefits", money(cur["ancillary"]) if cur["ancillary"] is not None else ask,
                     money(r["ancillary_annual"]), diff_cell(cur["ancillary"], r["ancillary_annual"])])
    if cur["other"] is not None:
        rows.append([p["incumbent"].get("other_label") or "Other fees", money(cur["other"]), "Included",
                     diff_cell(cur["other"], 0)])
    if r["full_comparison"]:
        rows.append(["Estimated annual all-in cost", money(r["current_total"]), money(r["recurring"]),
                     diff_cell(r["current_total"], r["recurring"])])
        hl.append(len(rows) - 1)
    rows.append(["One-time setup fee", "N/A", money(r["setup_fee"]) if r["setup_fee"] is not None else "TBD",
                 "One time"])
    story.append(table(["Cost Area", f"Current ({inc})", "VensureHR Proposed", "Difference"], rows,
                       [CONTENT_W * 0.34, CONTENT_W * 0.22, CONTENT_W * 0.24, CONTENT_W * 0.20], highlight=hl))

    story.append(P("How to read the bottom line", "h2"))
    story.append(P(p["executive"].get("bottom_line") or _bottom_line(p, r)))

    sv = p.get("services") or B.DEFAULT_SERVICES
    cols = [sv.get("payroll", []), sv.get("hr", []), sv.get("benefits", [])]
    if any(cols):
        title = "What is included"
        if r["admin_pepm"] is not None:
            title += f" in the {money(r['admin_pepm'], cents=False)} PEPM"
        block = [P(title, "h2")]
        cells = [[Paragraph("<br/>".join(md(x) for x in col), S["cell_l"] if i == 0 else S["cell"])
                  for i, col in enumerate(cols)]]
        t = table(["Payroll", "HR & Compliance", "Benefits & Technology"], cells, [CONTENT_W / 3] * 3,
                  header_color=B.ORANGE, first_bold=False)
        block.append(t)
        story.append(KeepTogether(block))


def _default_tiles(p, r):
    med = r["medical"]
    tiles = []
    if r["full_comparison"] and r["all_in_savings"] is not None and r["all_in_savings"] > 0:
        pct = r["all_in_savings"] / r["current_total"] * 100 if r["current_total"] else None
        tiles.append({"value": money(r["all_in_savings"], cents=False),
                      "label": "Est. annual all-in savings" + (f"\n({pct:.1f}% lower)" if pct else "")})
    if med["savings"] is not None and med["savings"] > 0:
        tiles.append({"value": money(med["savings"], cents=False),
                      "label": "Est. annual medical savings" + (f"\n({med['pct']:.2f}% lower)" if med["pct"] else "")})
    carrier = p["medical"].get("proposed_carrier")
    if carrier and len(tiles) < 2:
        tiles.append({"value": carrier[:14], "label": "Proposed medical carrier"})
    if r["admin_pepm"] is not None:
        tiles.append({"value": money(r["admin_pepm"], cents=False), "label": "VensureHR admin fee\nper employee per month"})
    epli = p["pricing"].get("epli") or "Included"
    tiles.append({"value": epli if len(epli) < 12 else "Included", "label": "Employment Practices\nLiability (EPLI)"})
    return tiles[:4]


def _bottom_line(p, r) -> str:
    name, inc = _names(p)
    med = r["medical"]
    if r["full_comparison"]:
        s = r["all_in_savings"]
        pct = (s / r["current_total"] * 100) if r["current_total"] else 0
        if s >= 0:
            txt = (f"Based on current {inc} costs, VensureHR lowers {name}'s estimated recurring all-in cost by "
                   f"**{money(s)} per year** ({pct:.1f}%). After the one-time setup fee, year-one savings are "
                   f"**{money(r['all_in_savings_y1'])}**.")
        else:
            txt = (f"Based on current {inc} costs, VensureHR's estimated recurring all-in cost is "
                   f"**{money(-s)} per year** higher ({-pct:.1f}%). That difference buys named service contacts, "
                   "multi-state compliance and the benefits described in this proposal.")
        return txt + " All figures are estimates until final underwriting."
    parts = []
    if med["savings"] is not None:
        parts.append(f"The medical savings of **{money(med['savings'])}** come directly from the carrier rates in "
                     "this proposal.")
    parts.append(f"To complete the side-by-side, we need {name}'s current {inc} invoice (admin fees, workers' comp "
                 f"and SUTA). Until then, here is a simple test: VensureHR's recurring non-medical costs are "
                 f"**{money(r['nonmedical'])}** per year.")
    if med["savings"] is not None:
        be = f"**{money(r['break_even'])}**"
        if r["break_even_pepm"]:
            be += f" per year (about **{money(r['break_even_pepm'])}** per employee per month)"
        parts.append(f"After the {money(med['savings'])} medical savings, VensureHR is the lower all-in cost if "
                     f"{name} currently pays more than {be} for PEO fees, workers' comp and SUTA combined.")
    else:
        parts.append(f"VensureHR is the lower all-in cost if {name} currently pays more than that for PEO fees, "
                     "workers' comp and SUTA combined.")
    return " ".join(parts)


def _medical(story, n, p, r):
    m = p["medical"]
    eff = parse_date(p["client"].get("effective_date"))
    cur_c, pro_c = m.get("current_carrier") or "Current", m.get("proposed_carrier") or "VensureHR"
    section(story, n, "Medical Comparison",
            f"{cur_c} current plans vs. VensureHR proposed {pro_c} plans, effective {short_date(eff)}.")
    if m.get("intro"):
        story.append(P(m["intro"]))
    for plan, calc in zip(m.get("plans", []), r["medical"]["plans"]):
        has_cur = bool(plan.get("current_name")) or calc["current_annual"] is not None
        rows, hl = [], []
        for f in plan.get("features", []):
            rows.append([f.get("feature", ""), f.get("current", ""), f.get("proposed", "")] if has_cur
                        else [f.get("feature", ""), f.get("proposed", "")])
        for t in plan.get("tiers", []):
            label = f"{t.get('tier', '')} (x{count_str(t.get('count')) or 0}) monthly"
            rows.append([label, rate_cell(t.get("current_rate")), rate_cell(t.get("proposed_rate"))] if has_cur
                        else [label, rate_cell(t.get("proposed_rate"))])
        if has_cur:
            pro = money(calc["proposed_annual"])
            if calc["savings"] is not None:
                pro += f" ({'save' if calc['savings'] >= 0 else 'add'} {money(abs(calc['savings']))})"
            rows.append(["Annual Total", money(calc["current_annual"]), pro])
            hdr = ["Plan Feature", f"Current: {plan.get('current_name', '')}", f"Proposed: {plan.get('proposed_name', '')}"]
            widths = [CONTENT_W * 0.30, CONTENT_W * 0.35, CONTENT_W * 0.35]
        else:
            rows.append(["Annual Total", money(calc["proposed_annual"])])
            hdr = ["Plan Feature", f"Proposed: {plan.get('proposed_name', '')}"]
            widths = [CONTENT_W * 0.40, CONTENT_W * 0.60]
        hl.append(len(rows) - 1)
        story.append(KeepTogether([table(hdr, rows, widths, highlight=hl), Spacer(1, 10)]))
    med = r["medical"]
    if len(m.get("plans", [])) > 0:
        sav = money(med["savings"]) if med["savings"] is not None else "TBD"
        if med["pct"] is not None:
            sav += f" ({med['pct']:.2f}%)"
        story.append(KeepTogether([table(
            ["Medical Summary", "Enrolled", "Current Annual", "Proposed Annual", "Savings"],
            [["All plans", count_str(med["enrolled"]), money(med["current"]), money(med["proposed"]), sav]],
            [CONTENT_W * 0.22, CONTENT_W * 0.12, CONTENT_W * 0.21, CONTENT_W * 0.21, CONTENT_W * 0.24],
            highlight=[0])]))
    if m.get("footnote"):
        story.append(P(m["footnote"], "small"))


def _ancillary(story, n, p, r):
    section(story, n, "Dental, Vision & Ancillary", "Plan-year rates. Monthly premiums shown.")
    d = p["dental"].get("rows", [])
    if d:
        rows = [[x.get("plan", ""), x.get("coinsurance", ""), x.get("annual_max", ""), x.get("ortho", ""),
                 rate_cell(x.get("ee")), rate_cell(x.get("es")), rate_cell(x.get("ec")), rate_cell(x.get("fam"))]
                for x in d]
        w = CONTENT_W
        story.append(table(["Dental Plan", "Basic / Major", "Annual Max", "Ortho (child)", "EE", "EE+Sp", "EE+Ch",
                            "Family"], rows,
                           [w * .20, w * .12, w * .10, w * .14, w * .11, w * .11, w * .11, w * .11]))
        if p["dental"].get("note"):
            story.append(P(p["dental"]["note"], "small"))
        story.append(Spacer(1, 8))
    v = p["vision"].get("rows", [])
    if v:
        rows = [[x.get("plan", ""), x.get("exam_materials", ""), x.get("frames", ""), x.get("contacts", ""),
                 rate_cell(x.get("ee")), rate_cell(x.get("es")), rate_cell(x.get("ec")), rate_cell(x.get("fam"))]
                for x in v]
        w = CONTENT_W
        story.append(table(["Vision Plan", "Exam / Materials", "Frames", "Contacts", "EE", "EE+Sp", "EE+Ch",
                            "Family"], rows,
                           [w * .18, w * .13, w * .13, w * .12, w * .11, w * .11, w * .11, w * .11]))
        if p["vision"].get("note"):
            story.append(P(p["vision"]["note"], "small"))
        story.append(Spacer(1, 8))
    if p.get("ancillary_recommendation"):
        story.append(callout(p["ancillary_recommendation"]))
    add = p.get("additional_coverage") or []
    if add:
        story.append(P("Additional coverage available", "h2"))
        story.append(table(["Coverage", "Options", "Rate"],
                           [[x.get("coverage", ""), x.get("options", ""), x.get("rate", "")] for x in add],
                           [CONTENT_W * .26, CONTENT_W * .44, CONTENT_W * .30]))
    if p.get("additional_note"):
        story.append(P(p["additional_note"], "small"))


def _wc_suta(story, n, p, r):
    name, _ = _names(p)
    section(story, n, "Workers' Comp, SUTA & Admin", f"Estimated from {name}'s payroll by state and class code.")
    rows_in = r["wc_rows"]
    if rows_in:
        rows = []
        for x in rows_in:
            suta_rate = rate_str(x.get("suta_rate"), pct=True) if num(x.get("suta_rate")) is not None else (
                x.get("suta_note") or "Client Report")
            suta_cost = money(x.get("suta_cost")) if num(x.get("suta_cost")) is not None else (
                x.get("suta_note") or "Client Report")
            rows.append([x.get("state", ""), str(x.get("class_code", "")), count_str(x.get("ees")),
                         money(x.get("payroll")), money(x.get("taxable_wages")), rate_str(x.get("wc_rate")),
                         money(x.get("wc_cost")), suta_rate, suta_cost])
        rows.append(["Total", "", count_str(r["wc_ees"]), money(r["payroll_total"]), "", "", money(r["wc_total"]),
                     "", money(r["suta_total"])])
        w = CONTENT_W
        story.append(table(["State", "Class", "EEs", "Est. Annual Payroll", "SUTA Taxable Wages", "WC Rate",
                            "WC Cost", "SUTA Rate", "Est. SUTA"], rows,
                           [w * .07, w * .08, w * .06, w * .15, w * .14, w * .10, w * .12, w * .13, w * .15],
                           shade=[len(rows) - 1], font_rows=[len(rows) - 1]))
        if p["wc_suta"].get("note"):
            story.append(Spacer(1, 6))
            story.append(P(p["wc_suta"]["note"], "small"))

    fees = []
    if r["admin_pepm"] is not None:
        rate = f"{money(r['admin_pepm'], cents=False)} PEPM"
        if r["admin_annual"] is not None:
            rate += f" ({money(r['admin_annual'] / 12)} / month)"
        label = "VensureHR Admin Fee" + (f" ({count_str(r['admin_ees'])} employees)" if r["admin_ees"] else "")
        fees.append([label, rate, money(r["admin_annual"])])
    fees.append(["Employment Practices Liability (EPLI)", p["pricing"].get("epli") or "Included",
                 "$0.00" if (p["pricing"].get("epli") or "Included").lower().startswith("incl") else "TBD"])
    if r["setup_fee"] is not None:
        fees.append(["One-Time Setup Fee", "One time", money(r["setup_fee"])])
    story.append(KeepTogether([P("VensureHR fees", "h2"),
                               table(["Item", "Rate", "Annual Estimate"], fees,
                                     [CONTENT_W * .42, CONTENT_W * .33, CONTENT_W * .25])]))
    addons = p.get("addons") or []
    if addons:
        pairs = []
        for i in range(0, len(addons), 2):
            a = addons[i]
            b = addons[i + 1] if i + 1 < len(addons) else {"name": "", "rate": ""}
            pairs.append([a.get("name", ""), a.get("rate", ""), b.get("name", ""), b.get("rate", "")])
        t = table(["Add-On", "Rate", "Add-On", "Rate"], pairs,
                  [CONTENT_W * .27, CONTENT_W * .23, CONTENT_W * .27, CONTENT_W * .23], first_bold=False,
                  align=["L", "L", "L", "L"])
        story.append(KeepTogether([P(f"Optional add-ons (only if {name} wants them)", "h2"), t]))


def _total(story, n, p, r):
    name, inc = _names(p)
    med = r["medical"]
    carrier = p["medical"].get("proposed_carrier")
    section(story, n, "Total Program Cost Summary", "Estimated first-year cost with VensureHR.")
    rows = []

    def m12(v):
        return money(v / 12) if num(v) is not None else "TBD"

    if med["proposed"] is not None:
        rows.append([f"Medical premiums ({carrier})" if carrier else "Medical premiums", m12(med["proposed"]),
                     money(med["proposed"]), "Total premium; employer/employee split set by client"])
    admin_note = (f"{money(r['admin_pepm'], cents=False)} PEPM x {count_str(r['admin_ees'])} employees"
                  if r["admin_pepm"] is not None and r["admin_ees"] else "")
    rows.append(["VensureHR Admin Fee", m12(r["admin_annual"]), money(r["admin_annual"]), admin_note])
    rows.append(["Workers' compensation", m12(r["wc_total"]), money(r["wc_total"]),
                 "Pending risk questionnaire & loss runs"])
    rows.append(["SUTA (estimated)", m12(r["suta_total"]), money(r["suta_total"]), "Owed with any provider"])
    if r["ancillary_annual"] is not None:
        rows.append(["Ancillary benefits (elected)", m12(r["ancillary_annual"]), money(r["ancillary_annual"]), ""])
    rows.append(["EPLI", "Included", "Included", ""])
    rows.append(["Recurring annual total", money(r["recurring"] / 12), money(r["recurring"]), ""])
    shade = [len(rows) - 1]
    rows.append(["One-time setup fee", "", money(r["setup_fee"]) if r["setup_fee"] is not None else "TBD",
                 "Year 1 only"])
    note = "" if r["ancillary_annual"] is not None else "Dental, vision & ancillary added once elected"
    rows.append(["Estimated Year 1 total", "", money(r["year1"]), note])
    hl = [len(rows) - 1]
    story.append(table(["Component", "Monthly", "Annual", "Notes"], rows,
                       [CONTENT_W * .30, CONTENT_W * .18, CONTENT_W * .20, CONTENT_W * .32], shade=shade,
                       highlight=hl, font_rows=shade))

    if r["full_comparison"]:
        story.append(P(f"All-in comparison against {inc}", "h2"))
        crow = [["Recurring annual cost", money(r["current_total"]), money(r["recurring"]),
                 diff_cell(r["current_total"], r["recurring"])],
                ["Year 1 (incl. one-time setup)", money(r["current_total"]),
                 money(r["year1"]), diff_cell(r["current_total"], r["year1"])]]
        story.append(table(["", f"Current ({inc})", "VensureHR", "Difference"], crow,
                           [CONTENT_W * .34, CONTENT_W * .22, CONTENT_W * .22, CONTENT_W * .22], highlight=[0]))
        s = r["all_in_savings"]
        if s >= 0:
            story.append(Spacer(1, 6))
            story.append(P(f"Switching to VensureHR is estimated to save {name} **{money(s)} per year** on a "
                           f"recurring basis and **{money(r['all_in_savings_y1'])}** in year one, on top of the "
                           "service improvements described in this proposal."))
        else:
            story.append(Spacer(1, 6))
            story.append(P(f"VensureHR is estimated at **{money(-s)} per year** more than {inc} on a recurring basis. "
                           "The service model, compliance coverage and benefit options in this proposal are what that "
                           "difference buys."))
    else:
        story.append(P(f"Break-even check against {inc}", "h2"))
        be_rows = [[f"VensureHR recurring non-medical cost (admin + WC + SUTA"
                    f"{' + ancillary' if r['ancillary_annual'] is not None else ''})", money(r["nonmedical"])]]
        if med["savings"] is not None:
            be_rows.append(["Less: confirmed annual medical savings", money(-med["savings"])])
        be_rows.append([f"Break-even: current {inc} fees + WC + SUTA per year", money(r["break_even"])])
        hl = [len(be_rows) - 1]
        if r["setup_fee"]:
            be_rows.append(["Break-even including the one-time setup fee (Year 1)", money(r["break_even_y1"])])
        story.append(table(["", "Amount"], be_rows, [CONTENT_W * .72, CONTENT_W * .28], align=["L", "R"],
                           highlight=hl))
        story.append(Spacer(1, 6))
        story.append(P(f"If {name}'s current {inc} invoices show more than **{money(r['break_even'])}** per year for "
                       "PEO fees, workers' comp and SUTA combined, VensureHR costs less in total, on top of the "
                       f"service changes in this proposal. Send us one recent {inc} invoice detail report and we will "
                       "replace every \"TBD\" with exact figures."))
    if p.get("service_callout"):
        story.append(Spacer(1, 10))
        story.append(callout(p["service_callout"]))


def _roi(story, n, p, r):
    roi = p["roi"]
    section(story, n, roi.get("title") or "ROI Analysis", "Findings from the ROI analysis provided.")
    if roi.get("intro"):
        story.append(P(roi["intro"]))
    rows_in = roi.get("rows", [])
    if rows_in:
        keys = [k for k in ("current", "proposed", "difference", "note") if any(str(x.get(k) or "").strip()
                                                                              for x in rows_in)]
        heads = {"current": "Current", "proposed": "VensureHR", "difference": "Difference", "note": "Notes"}
        rest = CONTENT_W * 0.66
        widths = [CONTENT_W * 0.34] + [rest / max(len(keys), 1)] * len(keys)
        rows = []
        for x in rows_in:
            row = [x.get("item", "")]
            for k in keys:
                val = x.get(k, "")
                row.append(money(val) if (k != "note" and num(val) is not None and not str(val).strip().endswith("%"))
                           else str(val or ""))
            rows.append(row)
        story.append(table(["Item"] + [heads[k] for k in keys], rows, widths))
    if roi.get("takeaways"):
        story.append(P("Key takeaways", "h2"))
        story.extend(bullets(roi["takeaways"]))


def _rollout(story, n, p, r):
    name, inc = _names(p)
    ro = p["rollout"]
    eff = parse_date(p["client"].get("effective_date"))
    section(story, n, "Rollout & Onboarding Plan",
            f"A realistic path to a {long_date(eff)} go-live." if eff else "A realistic path to go-live.")
    if ro.get("intro"):
        story.append(P(ro["intro"]))
    phases = ro.get("phases", [])
    if phases:
        rows = [[Paragraph(f"<b>{md(x.get('phase', ''))}</b><br/>{md(x.get('timing', ''))}", S["cell_b"]),
                 x.get("what", ""), x.get("who", "")] for x in phases]
        story.append(table(["Phase & Timing", "What happens", "Who"], rows,
                           [CONTENT_W * .22, CONTENT_W * .56, CONTENT_W * .22], align=["L", "L", "C"]))
    if ro.get("things_to_know"):
        story.append(CondPageBreak(90))
        story.append(P("Things to know before switching", "h2"))
        story.extend(bullets(ro["things_to_know"]))
    if ro.get("next_step"):
        story.append(Spacer(1, 8))
        story.append(callout(ro["next_step"]))
    k = p["consultant"]
    if k.get("name"):
        story.append(Spacer(1, 10))
        bits = [f"<b>{md(k['name'])}, VensureHR</b>"]
        if k.get("title"):
            bits.append(md(k["title"]))
        if k.get("phone"):
            bits.append(f"C: {md(k['phone'])}")
        if k.get("email"):
            bits.append(md(k["email"]))
        story.append(Paragraph("  |  ".join(bits), S["body_left"]))
