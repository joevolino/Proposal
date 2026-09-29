# VensureHR All-In Cost Proposal Builder

A web tool for VensureHR Business Consultants. Enter the client's details, upload the supporting documents, review the draft, and download a VensureHR-branded **All-In Cost Proposal** as a portrait (US Letter) PDF. The layout follows the QCIC, Inc. sample proposal in this repo.

## What it does

1. **Intake:** you enter client information (company, industry, employees, states, effective date, current PEO/provider, contact), your own details (remembered on your device), optional pricing overrides, and any known incumbent costs.
2. **Uploads by category:**
   | Category | Examples |
   |---|---|
   | Medical Rates | current plan rates, renewal, rate comparison |
   | Aetna Rates | VensureHR Aetna quote / rate sheet |
   | Ancillary Offerings | MetLife dental, vision, life, STD/LTD packets (a `.zip` is fine) |
   | Pricing Illustration | `VensureHR Pricing Illustration (Admin, WC, Taxes)` workbook (.xlsm/.xlsx) |
   | Excel ROI Analysis | ROI / cost-comparison workbooks |
   | Meeting Transcripts & Notes | call transcripts, notes, emails (.txt, .docx, .vtt, .pdf…) |
   | Incumbent Data | PEO invoices, census, current benefit summaries |

   Accepted formats: PDF, XLSX/XLSM, DOCX, CSV, TXT/MD/VTT/SRT, PNG/JPG, and ZIP archives of any of these.
3. **Drafting:**
   - The **pricing illustration** is parsed directly, not by AI. State/class rows, WC cost, SUTA, admin PEPM, setup fee, EPLI and add-ons come straight from the workbook, using the template's own formulas (WC = rate% × payroll, SUTA = rate% × EEs × state wage base).
   - With an `ANTHROPIC_API_KEY`, Claude reads every document and drafts the rest: the problem recap from transcripts, current vs. proposed medical plans with rates and enrollment, dental/vision/ancillary tables, incumbent costs from invoices, the ROI summary, and a tailored rollout. Claude is told to use only figures that appear in the documents and to list missing items rather than guess. Those items show up as "Open item" warnings on the review screen.
4. **Review & edit:** every section is editable (text, tables, medical plans), and each section can be switched on or off. A live panel recalculates the totals as you edit.
5. **PDF:** cover page, then Recap → Executive Summary → Medical Comparison → Dental, Vision & Ancillary → Workers' Comp, SUTA & Admin → Total Program Cost → ROI Analysis → Rollout & Onboarding. Sections without data are left out and the rest are renumbered.

### How the numbers work

The program calculates every total, savings figure and break-even; the AI never does this arithmetic.

- Medical annual = Σ(enrolled × monthly rate × 12), per plan and in total.
- Admin annual = PEPM × employees × 12.
- **Comparison mode:** when the incumbent's admin, WC and SUTA costs are known (typed on the form or found in an invoice), the proposal shows a full side-by-side all-in comparison with savings.
- **Break-even mode:** when they aren't known, it shows the break-even test from the sample, e.g. "VensureHR is the lower cost if you currently pay more than $X/year for PEO fees + WC + SUTA", and marks the missing items "Please provide invoice".
- Narrative can contain tokens such as `{medical_savings}`, `{medical_savings_pct}`, `{admin_annual}`, `{recurring_total}`, `{break_even}`, `{all_in_savings}`. These are filled in from the calculated numbers when the PDF is rendered, so the text always matches the tables.

## Run it

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...     # optional: enables AI drafting
python app.py                            # http://127.0.0.1:5000
```

Without an API key the tool still works. It imports the pricing illustration, and you enter the medical, ancillary and narrative content in the editor.

| Environment variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Enables AI drafting |
| `PROPOSAL_MODEL` | `claude-opus-5` | Claude model used for drafting |
| `PROPOSAL_EFFORT` | `high` | Model effort (`low`, `medium`, `high`, `xhigh`, `max`) |
| `PROPOSAL_MAX_UPLOAD_MB` | `80` | Upload size limit per request |
| `APP_PASSWORD` | none | When set, the site requires a login (use this on any public deployment) |
| `APP_USERNAME` | `vensurehr` | Login username when `APP_PASSWORD` is set |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Bind address |

AI drafting uses Claude's server-side refusal fallback (`fallbacks: "default"`). If the primary model declines a request, the API retries it on a fallback model in the same call.

A draft with large rate packets can take a few minutes. If you deploy behind a WSGI server, raise the request timeout, for example `gunicorn -w 2 --timeout 600 app:app`.

## Deploy on Render (get a shareable link)

The repo includes a Render Blueprint (`render.yaml`) that runs the app with gunicorn.

1. Merge the pull request so `render.yaml` is on `main`, or pick this branch when Render asks for one.
2. Sign in at [dashboard.render.com](https://dashboard.render.com) and connect your GitHub account when prompted.
3. Choose **New → Blueprint**, select the `joevolino/Proposal` repository, and click **Apply**.
4. When Render asks for the secret values, enter:
   - `ANTHROPIC_API_KEY`: your Anthropic API key (from console.anthropic.com)
   - `APP_PASSWORD`: a password for your team. The username is `vensurehr` (change it with `APP_USERNAME`).
5. Wait for the first build (a few minutes). Your link will look like `https://vensurehr-proposal-builder.onrender.com`.

Notes:
- **Plan:** the Blueprint uses Render's **free** plan. It sleeps after 15 idle minutes, so the first visit afterwards takes about a minute to load. For an always-on site, change `plan: free` to `plan: starter` in `render.yaml` (a paid Render plan).
- **Updates:** every push to the deployed branch redeploys the site automatically.
- **Login:** whenever `APP_PASSWORD` is set, the whole site asks for a username and password. Leave it set on any public URL, because the site handles client documents and uses your API credit.
- **Custom address:** you can attach a domain such as `proposals.yourdomain.com` under the service's **Settings → Custom Domains**.

**Branding:** colors match the sample proposal (navy `#0E1E3A`, orange `#F26522`, teal `#00A9C0`). To replace the built-in wordmark, drop a white/transparent `logo.png` into `assets/`.

**Drafts:** use *Save draft (.json)* on the review screen to keep work in progress, and *Open a saved draft* to pick it up later.

## Project layout

```
app.py                     Flask server (/api/draft, /api/compute, /api/pdf)
proposal_tool/extract.py   Reads PDF, Excel, Word, CSV, text, image and ZIP uploads
proposal_tool/pricing.py   Parses the VensureHR Pricing Illustration workbook
proposal_tool/ai.py        Claude drafting: prompt, JSON schema, document handling
proposal_tool/model.py     Proposal data model, defaults, rollout timeline, all calculations
proposal_tool/pdf.py       ReportLab renderer for the branded portrait PDF
proposal_tool/brand.py     Brand colors and standard copy (included services, add-ons, disclaimers)
static/                    Browser UI (intake, uploads, editor, PDF preview)
tests/                     Tests that reproduce the QCIC sample's numbers
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The tests rebuild the QCIC sample from `tests/fixtures/` and check that the tool reproduces its figures exactly: $2,150.70 WC, $9,024.64 SUTA, $9,890.76 (4.66%) medical savings, $25,284.58 break-even, and $239,052.58 Year 1 total. They also check the rollout dates, PDF rendering, file extraction, and the draft endpoint with the AI step stubbed out.

All rates are estimates for comparison and subject to final underwriting; carrier documents prevail.
