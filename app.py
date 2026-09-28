"""VensureHR All-In Cost Proposal Builder - web server.

Run:  python app.py   (then open http://localhost:5000)
Set ANTHROPIC_API_KEY to enable AI drafting from uploaded documents.
Set APP_PASSWORD (and optionally APP_USERNAME) to require a login, which any public deployment should do.
"""

from __future__ import annotations

import hmac
import os
import re
import traceback

from flask import Flask, jsonify, request, send_from_directory, Response

from proposal_tool import model
from proposal_tool.extract import CATEGORIES, extract_files
from proposal_tool.pdf import build_pdf

ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(ROOT, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("PROPOSAL_MAX_UPLOAD_MB", "80")) * 1024 * 1024


@app.before_request
def require_login():
    """HTTP Basic auth when APP_PASSWORD is set. /healthz stays open for the host's health checks."""
    password = os.environ.get("APP_PASSWORD")
    if not password or request.path == "/healthz":
        return None
    auth = request.authorization
    user_ok = auth is not None and hmac.compare_digest((auth.username or "").encode(),
                                                       os.environ.get("APP_USERNAME", "vensurehr").encode())
    pass_ok = auth is not None and hmac.compare_digest((auth.password or "").encode(), password.encode())
    if user_ok and pass_ok:
        return None
    return Response("Login required.", 401, {"WWW-Authenticate": 'Basic realm="VensureHR Proposal Builder"'})


@app.get("/healthz")
def healthz():
    return "ok"


def ai_available() -> bool:
    if os.environ.get("PROPOSAL_DISABLE_AI"):
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("PROPOSAL_ENABLE_AI"))


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    from proposal_tool.ai import MODEL
    return jsonify({"ai_available": ai_available(), "model": MODEL,
                    "categories": [[k, v] for k, v in CATEGORIES.items()]})


@app.post("/api/draft")
def draft():
    form = {k: v for k, v in request.form.items() if k != "use_ai"}
    use_ai = request.form.get("use_ai", "true").lower() != "false" and ai_available()
    files = []
    for category in CATEGORIES:
        for f in request.files.getlist(category):
            if f and f.filename:
                files.append((category, f.filename, f.read()))

    ex = extract_files(files)
    warnings = list(ex.warnings)
    proposal = model.from_form(form, ex.pricing)
    if ex.pricing is None and any(c == "pricing_illustration" for c, _, _ in files):
        warnings.append("The file under Pricing Illustration wasn't recognized as the VensureHR template; "
                        "WC/SUTA figures were not parsed from it.")
    elif ex.pricing is not None and not ex.pricing["rows"]:
        warnings.append("The pricing illustration has no state/class rows filled in, so WC and SUTA are blank.")

    ai_used = False
    if use_ai:
        try:
            from proposal_tool import ai
            drafted, ai_warnings = ai.draft(form, ex)
            proposal = model.merge_ai(proposal, drafted)
            warnings.extend(ai_warnings)
            ai_used = True
        except Exception as exc:  # keep the deterministic draft usable if the AI call fails
            traceback.print_exc()
            warnings.append(f"AI drafting failed ({type(exc).__name__}: {exc}). The proposal below uses the "
                            "form and pricing illustration only; fill in the remaining sections by hand.")
    elif files and not ai_available():
        warnings.append("AI drafting is off (no ANTHROPIC_API_KEY on the server). Pricing-illustration numbers "
                        "were imported; medical, ancillary and narrative sections need to be entered by hand.")

    return jsonify({
        "proposal": proposal,
        "warnings": warnings,
        "ai_used": ai_used,
        "pricing_file": (ex.pricing or {}).get("file"),
        "documents": [{"name": d.name, "category": d.category, "kind": d.kind} for d in ex.docs],
    })


@app.post("/api/compute")
def compute():
    p = request.get_json(force=True)
    return jsonify(model.compute(p))


@app.post("/api/pdf")
def pdf():
    p = request.get_json(force=True)
    data = build_pdf(p)
    name = re.sub(r"[^A-Za-z0-9]+", "_", p.get("client", {}).get("name") or "Client").strip("_")
    fname = f"{name}_VensureHR_All-In_Cost_Proposal.pdf"
    disp = "attachment" if request.args.get("download") else "inline"
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'{disp}; filename="{fname}"'})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Upload too large. Reduce file sizes or set PROPOSAL_MAX_UPLOAD_MB."}), 413


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
