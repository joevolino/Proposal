/* VensureHR All-In Cost Proposal Builder - front end */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined) el.append(kid);
    return el;
  };

  const state = { files: {}, proposal: null, config: null, pdfUrl: null };

  const DZ_HINTS = {
    medical_rates: "Current plan rates, renewal, or rate comparison",
    aetna_rates: "VensureHR Aetna quote / rate sheet",
    ancillary: "MetLife dental, vision, life, STD/LTD… (.zip ok)",
    pricing_illustration: "The VensureHR Admin, WC & Taxes workbook",
    roi: "ROI or cost comparison workbook",
    transcripts: "Call transcripts, meeting notes, emails",
    incumbent: "PEO invoices, census, current benefit summary",
  };

  // ---------------------------------------------------------------- storage helpers
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  };

  // ---------------------------------------------------------------- formatting
  const money = (v) => (v === null || v === undefined || Number.isNaN(v)) ? "TBD"
    : (v < 0 ? "(" : "") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (v < 0 ? ")" : "");
  const parseNum = (s) => {
    if (s === null || s === undefined) return null;
    const t = String(s).replace(/[$,%\s]/g, "");
    if (t === "") return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  };

  // ---------------------------------------------------------------- init
  async function init() {
    try {
      state.config = await (await fetch("/api/config")).json();
    } catch { state.config = { ai_available: false, categories: [] }; }
    renderDropzones();
    const ai = state.config.ai_available;
    $("#useAi").checked = ai;
    $("#useAi").disabled = !ai;
    $("#aiStatus").textContent = ai ? `Model: ${state.config.model}`
      : "AI drafting unavailable (server has no ANTHROPIC_API_KEY). Numbers from the pricing illustration are still imported.";
    for (const el of $$("[data-remember]")) {
      const saved = store.get("vhr." + el.name);
      if (saved) el.value = saved;
      el.addEventListener("change", () => store.set("vhr." + el.name, el.value));
    }
    $("#intake").addEventListener("submit", onDraft);
    $$(".step").forEach((b) => b.addEventListener("click", () => (+b.dataset.step === 3 ? makePdf() : go(+b.dataset.step))));
    $("#pdfBtn").addEventListener("click", makePdf);
    $("#backBtn").addEventListener("click", () => go(1));
    $("#backToEdit").addEventListener("click", () => go(2));
    $("#saveJson").addEventListener("click", saveJson);
    $("#loadJson").addEventListener("change", loadJson);
    $("#loadJson1").addEventListener("change", loadJson);
  }

  function go(step) {
    [1, 2, 3].forEach((n) => $("#step" + n).classList.toggle("hidden", n !== step));
    $$(".step").forEach((b) => b.classList.toggle("active", +b.dataset.step === step));
    window.scrollTo({ top: 0 });
  }

  function busy(msg) {
    $("#busy").classList.toggle("hidden", !msg);
    if (msg) $("#busyMsg").textContent = msg;
  }

  // ---------------------------------------------------------------- dropzones
  function renderDropzones() {
    const wrap = $("#dropzones");
    wrap.innerHTML = "";
    for (const [key, label] of state.config.categories || []) {
      state.files[key] = state.files[key] || [];
      const input = h("input", { type: "file", multiple: true, hidden: true });
      const chips = h("div", { class: "chips" });
      const dz = h("div", { class: "dz", tabindex: "0", role: "button", "aria-label": "Upload " + label },
        h("h3", {}, label.split(" (")[0]), h("p", {}, DZ_HINTS[key] || ""), chips, input);
      const refresh = () => {
        chips.innerHTML = "";
        state.files[key].forEach((f, i) => chips.append(h("span", { class: "chip", title: f.name }, h("span", {}, f.name),
          h("button", { type: "button", "aria-label": "Remove " + f.name, onclick: (e) => { e.stopPropagation(); state.files[key].splice(i, 1); refresh(); } }, "×"))));
      };
      const add = (list) => { state.files[key].push(...list); refresh(); };
      dz.addEventListener("click", (e) => { if (e.target !== input && e.target.tagName !== "BUTTON") input.click(); });
      dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
      input.addEventListener("change", () => { add([...input.files]); input.value = ""; });
      dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
      dz.addEventListener("dragleave", () => dz.classList.remove("over"));
      dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); add([...e.dataTransfer.files]); });
      wrap.append(dz);
    }
  }

  // ---------------------------------------------------------------- draft
  async function onDraft(e) {
    e.preventDefault();
    const fd = new FormData($("#intake"));
    fd.set("use_ai", $("#useAi").checked ? "true" : "false");
    let n = 0;
    for (const [cat, list] of Object.entries(state.files)) for (const f of list) { fd.append(cat, f, f.name); n++; }
    busy($("#useAi").checked && n
      ? `Reading ${n} document${n === 1 ? "" : "s"} and drafting the proposal. This can take a few minutes for large rate packets…`
      : "Building the draft…");
    try {
      const res = await fetch("/api/draft", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      state.proposal = data.proposal;
      showWarnings(data);
      renderEditor();
      $$(".step").forEach((b) => (b.disabled = false));
      go(2);
    } catch (err) {
      alert("Could not build the draft: " + err.message);
    } finally { busy(null); }
  }

  function showWarnings(data) {
    const w = $("#warnings");
    w.innerHTML = "";
    const docs = data.documents || [];
    w.append(h("div", { class: "info" },
      `${data.ai_used ? "AI draft built" : "Draft built"} from ${docs.length} document${docs.length === 1 ? "" : "s"}` +
      (data.pricing_file ? `; WC, SUTA and admin pricing imported from ${data.pricing_file}` : "") +
      ". Review every section, then generate the PDF. Totals, savings and break-even are calculated automatically."));
    for (const msg of data.warnings || []) w.append(h("div", { class: "warn" }, msg));
  }

  // ---------------------------------------------------------------- path helpers
  const getPath = (obj, path) => path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
  const setPath = (obj, path, val) => {
    const ks = path.split(".");
    let o = obj;
    ks.slice(0, -1).forEach((k) => { if (o[k] == null || typeof o[k] !== "object") o[k] = {}; o = o[k]; });
    o[ks[ks.length - 1]] = val;
  };

  // ---------------------------------------------------------------- editor spec
  const NUM = "number";
  const SECTIONS = [
    { id: "client", title: "Client & consultant", fields: [
      { type: "grid", cols: 3, items: [
        ["client.name", "Company name"], ["client.industry", "Industry"], ["client.employee_count", "Employees", NUM],
        ["client.states", "States", "list"], ["client.effective_date", "Effective date", "date"], ["client.incumbent_name", "Current provider"],
        ["client.contact_name", "Primary contact"], ["client.contact_title", "Contact title"], ["client.address", "Client address"],
        ["consultant.name", "Consultant"], ["consultant.title", "Consultant title"], ["consultant.phone", "Phone"],
        ["consultant.email", "Email"], ["consultant.office_address", "Office address"], ["prepared_date", "Prepared date", "date"],
      ] },
    ] },
    { id: "recap", title: "Recap of the Problem", toggle: true, fields: [
      { path: "recap.intro", label: "Intro paragraph", type: "textarea" },
      { path: "recap.rows", label: "What we heard", type: "table", cols: [["heard", "What you told us", "textarea"], ["means", "What this means day to day", "textarea"], ["changes", "What changes with VensureHR", "textarea"]] },
      { path: "recap.commitment", label: "Commitment callout", type: "textarea" },
    ] },
    { id: "executive", title: "Executive Summary", toggle: true, fields: [
      { path: "executive.highlights", label: "KPI tiles (leave empty for automatic tiles; max 4)", type: "table", cols: [["value", "Value"], ["label", "Label"]] },
      { path: "executive.bottom_line", label: "Bottom line paragraph (leave empty to auto-write from the numbers)", type: "textarea" },
      { type: "grid", cols: 3, items: [["services.payroll", "Included: Payroll", "lines"], ["services.hr", "Included: HR & Compliance", "lines"], ["services.benefits", "Included: Benefits & Technology", "lines"]] },
    ] },
    { id: "medical", title: "Medical Comparison", toggle: true, fields: [
      { type: "grid", cols: 2, items: [["medical.current_carrier", "Current carrier"], ["medical.proposed_carrier", "Proposed carrier"]] },
      { path: "medical.intro", label: "Intro paragraph", type: "textarea" },
      { type: "plans" },
      { path: "medical.footnote", label: "Footnote", type: "textarea" },
    ] },
    { id: "ancillary", title: "Dental, Vision & Ancillary", toggle: true, fields: [
      { path: "dental.rows", label: "Dental plans (monthly rates)", type: "table", cols: [["plan", "Plan"], ["coinsurance", "Basic / Major"], ["annual_max", "Annual max"], ["ortho", "Ortho"], ["ee", "EE", NUM], ["es", "EE+Sp", NUM], ["ec", "EE+Ch", NUM], ["fam", "Family", NUM]] },
      { path: "dental.note", label: "Dental note", type: "text" },
      { path: "vision.rows", label: "Vision plans (monthly rates)", type: "table", cols: [["plan", "Plan"], ["exam_materials", "Exam / Materials"], ["frames", "Frames"], ["contacts", "Contacts"], ["ee", "EE", NUM], ["es", "EE+Sp", NUM], ["ec", "EE+Ch", NUM], ["fam", "Family", NUM]] },
      { path: "vision.note", label: "Vision note", type: "text" },
      { path: "ancillary_recommendation", label: "Recommendation callout", type: "textarea" },
      { path: "additional_coverage", label: "Additional coverage available", type: "table", cols: [["coverage", "Coverage"], ["options", "Options", "textarea"], ["rate", "Rate"]] },
      { path: "additional_note", label: "Additional coverage note", type: "textarea" },
    ] },
    { id: "wc_suta", title: "Workers' Comp, SUTA & Admin", toggle: true, fields: [
      { type: "grid", cols: 4, items: [["pricing.admin_pepm", "Admin fee PEPM ($)", NUM], ["pricing.admin_employee_count", "Billed employees (blank = client count)", NUM], ["pricing.setup_fee", "One-time setup fee ($)", NUM], ["pricing.epli", "EPLI"]] },
      { path: "wc_suta.rows", label: "State / class code rows (WC cost and SUTA are recalculated from the rates)", type: "table", cols: [["state", "State"], ["class_code", "Class"], ["ees", "EEs", NUM], ["payroll", "Est. annual payroll", NUM], ["taxable_wages", "SUTA taxable wages", NUM], ["wc_rate", "WC rate /$100", NUM], ["suta_rate", "SUTA rate %", NUM], ["suta_note", "SUTA note (e.g. Client Report)"]] },
      { path: "wc_suta.note", label: "Explanation note", type: "textarea" },
      { path: "addons", label: "Optional add-ons", type: "table", cols: [["name", "Add-on"], ["rate", "Rate"]] },
    ] },
    { id: "total", title: "Total Cost & Incumbent Comparison", toggle: true, fields: [
      { type: "grid", cols: 4, items: [["incumbent.medical_annual", "Current medical (annual $; blank = from plan rates)", NUM], ["incumbent.admin_annual", "Current PEO / admin fees (annual $)", NUM], ["incumbent.wc_annual", "Current workers' comp (annual $)", NUM], ["incumbent.suta_annual", "Current SUTA (annual $)", NUM], ["incumbent.ancillary_annual", "Current ancillary (annual $)", NUM], ["incumbent.other_annual", "Current other fees (annual $)", NUM], ["incumbent.other_label", "Other fees label"], ["proposed_ancillary_annual", "VensureHR elected ancillary (annual $)", NUM]] },
      { type: "note", text: "Enter the incumbent's admin, WC and SUTA to switch the proposal from a break-even test to a full side-by-side all-in comparison." },
      { path: "service_callout", label: "Service callout", type: "textarea" },
    ] },
    { id: "roi", title: "ROI Analysis", toggle: true, fields: [
      { path: "roi.title", label: "Section title", type: "text" },
      { path: "roi.intro", label: "Intro paragraph", type: "textarea" },
      { path: "roi.rows", label: "ROI rows", type: "table", cols: [["item", "Item"], ["current", "Current"], ["proposed", "VensureHR"], ["difference", "Difference"], ["note", "Notes", "textarea"]] },
      { path: "roi.takeaways", label: "Key takeaways (one per line)", type: "lines" },
    ] },
    { id: "rollout", title: "Rollout & Onboarding", toggle: true, fields: [
      { path: "rollout.intro", label: "Intro paragraph", type: "textarea" },
      { path: "rollout.phases", label: "Phases", type: "table", cols: [["phase", "Phase"], ["timing", "Timing"], ["what", "What happens", "textarea"], ["who", "Who"]] },
      { path: "rollout.things_to_know", label: "Things to know before switching (one per line)", type: "lines" },
      { path: "rollout.next_step", label: "Next step callout", type: "textarea" },
    ] },
  ];

  // ---------------------------------------------------------------- editor render
  function renderEditor() {
    const ed = $("#editor");
    const nav = $("#sectionNav");
    ed.innerHTML = "";
    nav.innerHTML = "";
    const p = state.proposal;
    p.sections = p.sections || {};
    for (const sec of SECTIONS) {
      const card = h("div", { class: "card", id: "sec-" + sec.id });
      const head = h("h2", {}, sec.title);
      const link = h("a", { href: "#sec-" + sec.id }, sec.title);
      if (sec.toggle) {
        const cb = h("input", { type: "checkbox" });
        cb.checked = p.sections[sec.id] !== false;
        const sync = () => { link.classList.toggle("off", !cb.checked); card.style.opacity = cb.checked ? 1 : 0.55; };
        cb.addEventListener("change", () => { p.sections[sec.id] = cb.checked; sync(); });
        head.append(h("label", { class: "include" }, cb, "Include in PDF"));
        sync();
      }
      card.append(head);
      for (const f of sec.fields) card.append(renderField(f));
      if (sec.id === "recap") {
        card.append(h("p", { class: "token-help" }, "Tip: narrative can use tokens that fill in from the calculated numbers, e.g. ",
          h("code", {}, "{medical_savings}"), " ", h("code", {}, "{medical_savings_pct}"), " ", h("code", {}, "{admin_annual}"), " ",
          h("code", {}, "{recurring_total}"), " ", h("code", {}, "{break_even}"), " ", h("code", {}, "{all_in_savings}"), "."));
      }
      ed.append(card);
      nav.append(link);
    }
    refreshSummary();
  }

  function renderField(f) {
    const p = state.proposal;
    if (f.type === "grid") {
      const g = h("div", { class: "fields cols" + f.cols });
      if (f.cols === 2) g.className = "fields";
      for (const [path, label, type] of f.items) g.append(renderField({ path, label, type: type || "text", inGrid: true }));
      return g;
    }
    if (f.type === "note") return h("p", { class: "hint", style: "margin:10px 0 0" }, f.text);
    if (f.type === "plans") return renderPlans();
    if (f.type === "table") {
      return h("div", {}, h("div", { class: "sub" }, f.label), renderTable(() => getPath(p, f.path) || [], (v) => setPath(p, f.path, v), f.cols));
    }
    let input;
    const val = getPath(p, f.path);
    if (f.type === "textarea") {
      input = h("textarea", { rows: 3 });
      input.value = val || "";
      input.addEventListener("input", () => setPath(p, f.path, input.value));
    } else if (f.type === "lines") {
      input = h("textarea", { rows: 5 });
      input.value = (val || []).join("\n");
      input.addEventListener("input", () => setPath(p, f.path, input.value.split("\n").map((s) => s.trim()).filter(Boolean)));
    } else if (f.type === "list") {
      input = h("input", {});
      input.value = (val || []).join(", ");
      input.addEventListener("input", () => setPath(p, f.path, input.value.split(/[,;\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean)));
    } else if (f.type === NUM) {
      input = h("input", { inputmode: "decimal" });
      input.value = val ?? "";
      input.addEventListener("input", () => { setPath(p, f.path, parseNum(input.value)); refreshSummary(); });
    } else {
      input = h("input", { type: f.type === "date" ? "date" : "text" });
      input.value = val || "";
      input.addEventListener("input", () => { setPath(p, f.path, input.value); if (f.path === "client.employee_count") refreshSummary(); });
    }
    return h("label", { class: !f.inGrid && (f.type === "textarea" || f.type === "text") ? "span-all" : "" }, f.label, input);
  }

  function renderTable(get, set, cols, onChange) {
    const wrap = h("div", {});
    const draw = () => {
      wrap.innerHTML = "";
      const rows = get();
      const tbody = h("tbody", {});
      rows.forEach((row, ri) => {
        const tr = h("tr", {});
        for (const [key, , type] of cols) {
          const isArea = type === "textarea";
          const inp = isArea ? h("textarea", { rows: 2 }) : h("input", type === NUM ? { inputmode: "decimal" } : {});
          inp.value = row[key] ?? "";
          inp.addEventListener("input", () => {
            row[key] = type === NUM ? parseNum(inp.value) : inp.value;
            refreshSummary();
            onChange && onChange();
          });
          tr.append(h("td", {}, inp));
        }
        tr.append(h("td", { class: "x" }, h("button", { type: "button", title: "Remove row", onclick: () => { rows.splice(ri, 1); set(rows); draw(); refreshSummary(); onChange && onChange(); } }, "×")));
        tbody.append(tr);
      });
      const table = h("table", { class: "edit" }, h("thead", {}, h("tr", {}, cols.map(([, label]) => h("th", {}, label)), h("th", {}))), tbody);
      wrap.append(h("div", { class: "tbl-wrap" }, table),
        h("div", { class: "row-actions" }, h("button", { type: "button", class: "btn small", onclick: () => {
          const r = {}; cols.forEach(([k, , t]) => (r[k] = t === NUM ? null : "")); rows.push(r); set(rows); draw();
        } }, "+ Add row")));
    };
    draw();
    return wrap;
  }

  function renderPlans() {
    const p = state.proposal;
    p.medical = p.medical || {};
    p.medical.plans = p.medical.plans || [];
    const wrap = h("div", {});
    const draw = () => {
      wrap.innerHTML = "";
      wrap.append(h("div", { class: "sub" }, "Plans (current vs. proposed)"));
      p.medical.plans.forEach((plan, i) => {
        plan.features = plan.features || [];
        plan.tiers = plan.tiers || [];
        const names = h("div", { class: "fields" });
        for (const [k, lbl] of [["current_name", "Current plan name"], ["proposed_name", "Proposed plan name"]]) {
          const inp = h("input", {}); inp.value = plan[k] || "";
          inp.addEventListener("input", () => (plan[k] = inp.value));
          names.append(h("label", {}, lbl, inp));
        }
        const calc = h("div", { class: "calc" });
        const upd = () => {
          let c = 0, pr = 0, hc = false, hp = false;
          for (const t of plan.tiers) {
            const n = parseNum(t.count) || 0;
            if (parseNum(t.current_rate) !== null) { c += n * parseNum(t.current_rate) * 12; hc = true; }
            if (parseNum(t.proposed_rate) !== null) { pr += n * parseNum(t.proposed_rate) * 12; hp = true; }
          }
          calc.innerHTML = "";
          calc.append(`Annual: current ${hc ? money(c) : "—"}, proposed ${hp ? money(pr) : "—"}`);
          if (hc && hp) calc.append(" · ", h("b", {}, `${c - pr >= 0 ? "save" : "add"} ${money(Math.abs(c - pr))}`));
        };
        wrap.append(h("div", { class: "plan" },
          h("div", { class: "plan-head" }, h("strong", {}, `Plan ${i + 1}`),
            h("button", { type: "button", class: "btn small danger", onclick: () => { p.medical.plans.splice(i, 1); draw(); refreshSummary(); } }, "Remove plan")),
          names,
          h("div", { class: "sub" }, "Plan design"),
          renderTable(() => plan.features, (v) => (plan.features = v), [["feature", "Feature"], ["current", "Current"], ["proposed", "Proposed"]]),
          h("div", { class: "sub" }, "Monthly rates & enrollment"),
          renderTable(() => plan.tiers, (v) => (plan.tiers = v), [["tier", "Tier"], ["count", "Enrolled", NUM], ["current_rate", "Current rate", NUM], ["proposed_rate", "Proposed rate", NUM]], upd),
          calc));
        upd();
      });
      wrap.append(h("button", { type: "button", class: "btn small", onclick: () => {
        p.medical.plans.push({ current_name: "", proposed_name: "", features: [
          { feature: "Deductible (Ind / Fam)", current: "", proposed: "" }, { feature: "Out-of-Pocket Max (Ind / Fam)", current: "", proposed: "" },
          { feature: "PCP / Specialist Copay", current: "", proposed: "" }, { feature: "Emergency Room", current: "", proposed: "" }],
          tiers: [{ tier: "Employee Only", count: null, current_rate: null, proposed_rate: null }, { tier: "Employee + Spouse", count: null, current_rate: null, proposed_rate: null },
            { tier: "Employee + Child(ren)", count: null, current_rate: null, proposed_rate: null }, { tier: "Family", count: null, current_rate: null, proposed_rate: null }] });
        draw();
      } }, "+ Add medical plan"));
    };
    draw();
    return wrap;
  }

  // ---------------------------------------------------------------- live summary
  let sumTimer = null;
  function refreshSummary() {
    clearTimeout(sumTimer);
    sumTimer = setTimeout(async () => {
      try {
        const r = await (await fetch("/api/compute", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.proposal) })).json();
        const m = r.medical;
        const rows = [];
        if (m.proposed !== null || m.current !== null) {
          rows.push(["Medical, current", money(m.current)], ["Medical, proposed", money(m.proposed)]);
          if (m.savings !== null) rows.push(["Medical savings", money(m.savings), m.savings >= 0 ? "good" : "bad"]);
        }
        rows.push(["Admin fee", money(r.admin_annual)], ["Workers' comp", money(r.wc_total)], ["SUTA", money(r.suta_total)]);
        if (r.ancillary_annual !== null) rows.push(["Ancillary", money(r.ancillary_annual)]);
        rows.push(["Recurring total", money(r.recurring), "", "total"], ["Year 1 total", money(r.year1)]);
        if (r.full_comparison) {
          rows.push(["Current all-in", money(r.current_total), "", "total"], ["All-in savings", money(r.all_in_savings), r.all_in_savings >= 0 ? "good" : "bad"]);
        } else {
          rows.push(["Break-even (incumbent fees)", money(r.break_even), "", "total"]);
        }
        const dl = h("dl", {});
        for (const [k, v, cls, t] of rows) dl.append(h("dt", { class: t || "" }, k), h("dd", { class: [cls, t].filter(Boolean).join(" ") }, v));
        const s = $("#summary");
        s.innerHTML = "";
        s.append(h("h3", {}, "Calculated totals (annual)"), dl);
      } catch { /* summary is best-effort */ }
    }, 250);
  }

  // ---------------------------------------------------------------- pdf + json
  async function makePdf() {
    busy("Rendering the PDF…");
    try {
      const res = await fetch("/api/pdf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.proposal) });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
      state.pdfUrl = URL.createObjectURL(blob);
      const name = ((state.proposal.client && state.proposal.client.name) || "Client").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "");
      $("#pdfFrame").src = state.pdfUrl;
      const a = $("#downloadPdf");
      a.href = state.pdfUrl;
      a.download = `${name}_VensureHR_All-In_Cost_Proposal.pdf`;
      go(3);
    } catch (err) {
      alert("PDF generation failed: " + err.message.slice(0, 400));
    } finally { busy(null); }
  }

  function saveJson() {
    const blob = new Blob([JSON.stringify(state.proposal, null, 2)], { type: "application/json" });
    const name = ((state.proposal.client && state.proposal.client.name) || "proposal").replace(/[^A-Za-z0-9]+/g, "_");
    const a = h("a", { href: URL.createObjectURL(blob), download: `${name}_proposal_draft.json` });
    document.body.append(a); a.click(); a.remove();
  }

  async function loadJson(e) {
    const f = e.target.files[0];
    if (!f) return;
    try {
      state.proposal = JSON.parse(await f.text());
      $("#warnings").innerHTML = "";
      $("#warnings").append(h("div", { class: "info" }, `Loaded draft ${f.name}.`));
      renderEditor();
      $$(".step").forEach((b) => (b.disabled = false));
      go(2);
    } catch (err) { alert("That file isn't a valid proposal draft: " + err.message); }
    e.target.value = "";
  }

  init();
})();
