(() => {
  "use strict";
  const state = { accounts: [], selected: new Set(), page: 0, pageSize: 50, dialogAccount: null };
  const $ = (selector) => document.querySelector(selector);

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function showError(error) {
    const banner = $("#error-banner");
    banner.hidden = false;
    banner.textContent = error instanceof Error ? error.message : String(error);
  }
  function clearError() {
    $("#error-banner").hidden = true;
    $("#error-banner").textContent = "";
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
    });
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try { message = (await response.json()).error || message; } catch (_) { /* Use HTTP status. */ }
      throw new Error(message);
    }
    return response;
  }
  function setOptions(select, values, firstLabel) {
    const previous = select.value;
    select.replaceChildren(new Option(firstLabel, ""));
    for (const value of values) select.add(new Option(value, value));
    if (values.includes(previous)) select.value = previous;
  }
  function dateLabel(value, empty = "No observation date") {
    if (!value) return empty;
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? "Unknown date" :
      new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(date);
  }
  function metric(label, value, note, symbol, tone) {
    const card = el("article", "stat-card");
    card.dataset.tone = tone;
    const top = el("div", "stat-top");
    const mark = el("span", "stat-mark", symbol);
    mark.setAttribute("aria-hidden", "true");
    top.append(el("span", "", label), mark);
    card.append(top, el("div", "stat-number", value), el("div", "stat-foot", note));
    return card;
  }
  function updateDashboard(meta) {
    const eligible = state.accounts.filter((account) => account.eligible);
    const review = eligible.filter((account) => account.priority === "Review now");
    const uniqueWithSignals = eligible.filter((account) => account.signals.length);
    const held = state.accounts.filter((account) => !account.eligible);
    const grid = $("#stat-grid");
    grid.replaceChildren(
      metric("Candidate accounts", eligible.length.toLocaleString(), "Single-domain candidates · ownership unverified", "◫", "teal"),
      metric("Corroborate first", review.length.toLocaleString(), "Higher-weight evidence · validate before contacting", "◎", "lime"),
      metric("Signal leads", uniqueWithSignals.length.toLocaleString(), "At least one candidate evidence type", "↗", "violet"),
      metric("Attribution holds", held.length.toLocaleString(), "Provider / ambiguous · excluded by default", "◇", "amber"),
    );
    const imported = Number(meta.records_imported || 0);
    const snapshotTimestamp = String(meta.source_name || "").match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
    $("#source-date").textContent = dateLabel(snapshotTimestamp ? snapshotTimestamp[0] : meta.imported_at, "Local dataset");
    $("#sample-note").textContent =
      `${imported.toLocaleString()} sanitized rows · ${Number(meta.accounts_count || 0).toLocaleString()} account/provider groups`;
    $("#source-link").href = meta.source_url || "#";
    $("#source-link").textContent = meta.source_name || "snapshot";
    $("#mode-label").textContent = meta.mode === "live" ? "Live AI · budget limited" : "Offline rules · no LLM";
  }
  function getFiltered() {
    const query = $("#search").value.trim().toLowerCase();
    const country = $("#country").value;
    const segment = $("#segment").value;
    const priority = $("#priority").value;
    const includeHold = $("#include-hold").checked;
    const accounts = state.accounts.filter((account) => {
      if (!account.eligible && !includeHold) return false;
      if (query && !`${account.name} ${account.domain} ${account.provider}`.toLowerCase().includes(query)) return false;
      if (country && !account.countries.includes(country)) return false;
      if (segment && account.segment !== segment) return false;
      if (priority && account.priority !== priority) return false;
      return true;
    });
    const sort = $("#sort").value;
    accounts.sort((a, b) => sort === "name" ? a.name.localeCompare(b.name) :
      sort === "freshness" ? (b.latest_seen || "").localeCompare(a.latest_seen || "") || b.score - a.score :
        b.score - a.score || (b.latest_seen || "").localeCompare(a.latest_seen || "") || a.name.localeCompare(b.name));
    return accounts;
  }
  function scoreCell(account) {
    const cell = el("td", "score-cell");
    const line = el("div", "score-line");
    line.append(el("span", "score-value", account.score));
    const track = el("span", "score-track");
    const fill = el("span", "score-fill");
    fill.style.width = `${Math.max(0, Math.min(100, account.score))}%`;
    track.append(fill);
    line.append(track);
    cell.setAttribute("aria-label", `Research evidence score ${account.score} out of 100`);
    cell.append(line);
    return cell;
  }
  function priorityClass(value) {
    return value === "Review now" ? "review" : value === "Research" ? "research" :
      value === "Hold" ? "hold" : "monitor";
  }
  function signalPills(account) {
    const cell = el("td", "");
    const pills = el("div", "signal-pills");
    const signals = account.signals.filter((signal) => signal.evidence_ids.length).slice(0, 3);
    if (!signals.length) pills.append(el("span", "signal-empty", "No ranked signal"));
    for (const signal of signals) {
      const pill = el("span", `signal-pill${signal.weight < 25 ? " weak" : ""}`,
        signal.kind === "data-service" ? "Data service" :
          signal.kind === "remote-access" ? "Remote access" :
            signal.kind === "expired-cert" ? "Certificate" :
              signal.kind === "legacy-tls" ? "Legacy TLS" :
                signal.kind === "verified-cve" ? "Source CVE flag" : "Unverified CVE");
      pill.title = signal.label;
      pills.append(pill);
    }
    cell.append(pills);
    return cell;
  }
  function renderAccounts() {
    const filtered = getFiltered();
    const count = filtered.length;
    const pageCount = Math.max(1, Math.ceil(count / state.pageSize));
    state.page = Math.max(0, Math.min(pageCount - 1, state.page));
    const visible = filtered.slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);
    const body = $("#account-rows");
    body.replaceChildren();
    for (const account of visible) {
      const row = document.createElement("tr");
      const checkboxCell = el("td", "select-col");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selected.has(account.id);
      checkbox.setAttribute("aria-label", `Shortlist ${account.name}`);
      checkbox.addEventListener("change", () => {
        checkbox.checked ? state.selected.add(account.id) : state.selected.delete(account.id);
        updateSelectionButtons();
      });
      checkboxCell.append(checkbox);
      row.append(checkboxCell);

      const accountCell = el("td", "");
      const open = el("button", "account-open");
      open.type = "button";
      const avatar = el("span", "account-avatar", account.name.charAt(0).toUpperCase());
      avatar.setAttribute("aria-hidden", "true");
      const identity = el("span", "account-identity");
      identity.append(el("span", "account-name", account.name),
        el("span", "account-sub", account.eligible ? account.domain : `${account.provider} · attribution hold`));
      open.append(avatar, identity);
      open.addEventListener("click", () => openDetails(account.id));
      accountCell.append(open);
      row.append(accountCell);

      const countryCell = el("td", "location-cell");
      countryCell.append(el("span", "country-tag", account.country || "Unknown"));
      row.append(countryCell, signalPills(account));
      const observedCell = el("td", "observed-cell");
      observedCell.append(el("span", "observed-date", dateLabel(account.latest_seen, "Unknown")),
        el("span", "account-sub", account.age_days === null ? "Recency unavailable" : `${account.age_days} days ago`));
      row.append(observedCell, scoreCell(account));
      const priority = el("span", `priority ${priorityClass(account.priority)}`, account.priority);
      const priorityCell = el("td", "");
      priorityCell.append(priority);
      row.append(priorityCell);
      body.append(row);
    }
    $("#result-count").textContent = count.toLocaleString();
    $("#empty-state").hidden = Boolean(count);
    $("#select-visible").checked = visible.length > 0 && visible.every((item) => state.selected.has(item.id));
    $("#select-visible").indeterminate = visible.some((item) => state.selected.has(item.id)) && !$("#select-visible").checked;
    $("#page-indicator").textContent = count ? `${state.page + 1} / ${pageCount}` : "0 results";
    $("#previous-page").disabled = state.page <= 0;
    $("#next-page").disabled = state.page >= pageCount - 1;
    updateSelectionButtons();
  }
  function updateSelectionButtons() {
    $("#export-selected").disabled = state.selected.size === 0;
    $("#export-selected").lastElementChild.textContent =
      state.selected.size ? `Export shortlist (${state.selected.size})` : "Export shortlist";
  }
  function appendSection(container, heading, content) {
    const section = el("section", "detail-section");
    section.append(el("h3", "", heading), content);
    container.append(section);
  }
  function detailParagraph(text) {
    return el("p", "", text);
  }
  function showToast(message) {
    const toast = $("#toast");
    toast.textContent = message;
    toast.classList.add("show");
    window.setTimeout(() => toast.classList.remove("show"), 2300);
  }
  function makeBriefBox(brief) {
    const box = el("section", "brief-box");
    const heading = el("h3", "", brief.mode === "live" ? "AI research suggestion · human review required" :
      "Rule-based research suggestion · no LLM used");
    const decision = el("div", "priority " + priorityClass(brief.decision), brief.decision);
    const rationale = el("p", "", brief.rationale);
    const draft = el("p", "", brief.draft?.body || "");
    draft.style.marginTop = "10px";
    const citations = el("div", "brief-cite", `Evidence IDs: ${brief.evidence_ids.join(", ") || "none"} · trace ${brief.trace_id} · $${Number(brief.cost_usd || 0).toFixed(6)}`);
    const tools = el("div", "brief-tools");
    const copy = el("button", "copy-button", "Copy draft");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(`${brief.draft.subject}\n\n${brief.draft.body}`); showToast("Draft copied. Review before sending."); }
      catch (_) { showToast("Clipboard unavailable. Select and copy the draft text."); }
    });
    tools.append(decision, copy);
    box.append(heading, rationale, draft, citations, tools);
    return box;
  }
  function openDetails(accountId) {
    const account = state.accounts.find((item) => item.id === accountId);
    if (!account) return;
    state.dialogAccount = account;
    const dialog = $("#detail-dialog");
    $("#detail-title").textContent = account.name;
    $("#detail-domain").textContent = account.eligible
      ? `${account.domain} · ${account.segment}`
      : `${account.provider} · provider / ambiguous observation`;
    const content = $("#detail-content");
    content.replaceChildren();

    const metrics = el("div", "detail-grid");
    for (const [label, value] of [["Evidence score", `${account.score}/100`],
      ["Recency", account.age_days === null ? "Unknown" : `${account.age_days} days`],
      ["Priority", account.priority],
      ["Fit component", `${account.fit_score}/20`],
      ["Signal component", `${account.signal_score}/60`],
      ["Freshness component", `${account.freshness_score}/20`]]) {
      const item = el("div", "detail-metric");
      item.append(el("span", "", label), el("strong", "", value));
      metrics.append(item);
    }
    content.append(metrics);
    appendSection(content, "Attribution & use", detailParagraph(account.attribution));
    appendSection(content, "Observed countries (not headquarters)", detailParagraph(account.countries.join(", ") || "Unknown"));
    const evidence = el("ul", "evidence-list");
    for (const item of account.evidence) {
      const row = el("li", "evidence-item");
      const title = el("div", "evidence-title");
      title.append(el("span", "", `${item.transport.toUpperCase()} · service port ${item.port}`),
        el("span", "country-tag", item.country));
      const signalLabels = item.flags.map((flag) => {
        const signal = account.signals.find((candidate) => candidate.id === flag);
        return signal ? signal.label : flag;
      });
      row.append(title,
        el("div", "evidence-meta", `${dateLabel(item.observed_at)}${item.product ? ` · product: ${item.product}` : ""}`),
        el("div", "evidence-meta", signalLabels.join(" · ") || "No derived signal for this observation"));
      evidence.append(row);
    }
    appendSection(content, `Evidence · ${account.evidence.length} passive observations`, evidence);
    const signalContent = el("div", "");
    if (account.signals.length) {
      for (const signal of account.signals) {
        const row = el("div", "evidence-item");
        const label = el("div", "evidence-title");
        label.append(el("span", "", signal.label), el("span", "country-tag", `+${signal.weight}`));
        row.append(label, el("div", "evidence-meta", `${signal.evidence_ids.length} linked observation(s) · score weight is freshness-gated`));
        signalContent.append(row);
      }
    } else signalContent.append(detailParagraph("No current ranked exposure signal."));
    appendSection(content, "Derived signals · unverified clues", signalContent);

    const statusRow = el("div", "field-row");
    statusRow.append(el("label", "", "Disposition"));
    const status = document.createElement("select");
    status.setAttribute("aria-label", "Account disposition");
    for (const value of ["New", "Shortlisted", "Contacted", "Disqualified"]) status.add(new Option(value, value));
    status.value = account.status;
    statusRow.append(status);
    const notesLabel = el("label", "notes-field");
    notesLabel.append(el("span", "", "Research notes (stored in this local workspace)"));
    const notes = document.createElement("textarea");
    notes.maxLength = 4000;
    notes.value = account.notes || "";
    notesLabel.append(notes);
    const controls = el("div", "detail-actions");
    const save = el("button", "button secondary", "Save disposition");
    save.type = "button";
    save.addEventListener("click", async () => {
      try {
        const response = await api(`/api/accounts/${encodeURIComponent(account.id)}/state`, {
          method: "POST", body: JSON.stringify({ status: status.value, notes: notes.value }),
        });
        const updated = await response.json();
        account.status = updated.status;
        account.notes = updated.notes;
        showToast("Research status saved locally.");
        await loadActivity();
      } catch (error) { showError(error); }
    });
    const briefButton = el("button", "button primary", "Generate research brief");
    briefButton.type = "button";
    briefButton.addEventListener("click", async () => {
      clearError();
      briefButton.disabled = true;
      briefButton.textContent = "Reviewing evidence…";
      try {
        const response = await api(`/api/accounts/${encodeURIComponent(account.id)}/brief`, {
          method: "POST", body: JSON.stringify({ version: "v2" }),
        });
        const brief = await response.json();
        const previous = content.querySelector(".brief-box");
        if (previous) previous.remove();
        content.append(makeBriefBox(brief));
        await loadActivity();
        content.querySelector(".brief-box")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (error) { showError(error); }
      finally {
        briefButton.disabled = false;
        briefButton.textContent = "Generate research brief";
      }
    });
    controls.append(save, briefButton);
    content.append(statusRow, notesLabel, controls);
    try { dialog.showModal(); } catch (_) { dialog.setAttribute("open", ""); }
  }
  async function exportSelected() {
    try {
      const response = await api("/api/export", {
        method: "POST", body: JSON.stringify({ ids: Array.from(state.selected) }),
      });
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "signaldesk-shortlist.csv";
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      showToast("Shortlist exported. Validate attribution before outreach.");
    } catch (error) { showError(error); }
  }
  async function loadActivity() {
    const response = await api("/api/activity");
    const data = await response.json();
    const activityRows = $("#activity-rows");
    activityRows.replaceChildren();
    for (const item of data.activity) {
      const row = document.createElement("tr");
      row.append(el("td", "", item.name), el("td", "", item.status),
        el("td", "", dateLabel(item.updated_at)), el("td", "", item.notes));
      activityRows.append(row);
    }
    $("#activity-empty").hidden = data.activity.length > 0;
    const traceRows = $("#trace-rows");
    traceRows.replaceChildren();
    for (const trace of data.traces) {
      const row = document.createElement("tr");
      row.append(el("td", "", dateLabel(trace.created_at)),
        el("td", "", `${trace.mode} · ${trace.model}`),
        el("td", "", trace.prompt_version), el("td", "", trace.decision || "—"),
        el("td", "", `${trace.latency_ms} ms`),
        el("td", "", `$${Number(trace.cost_usd).toFixed(6)}`),
        el("td", "", trace.status));
      traceRows.append(row);
    }
    $("#trace-empty").hidden = data.traces.length > 0;
  }
  async function setView(view) {
    clearError();
    $("#overview-view").hidden = view !== "overview";
    $("#activity-view").hidden = view !== "activity";
    for (const button of document.querySelectorAll(".nav-link")) {
      const active = button.dataset.view === view;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    }
    if (view === "activity") {
      try { await loadActivity(); } catch (error) { showError(error); }
    }
  }
  async function initialize() {
    try {
      const response = await api("/api/accounts");
      const data = await response.json();
      state.accounts = data.accounts;
      updateDashboard({ ...data.meta, ...data.ai });
      setOptions($("#country"), [...new Set(state.accounts.flatMap((item) => item.countries))].sort(), "All observed countries");
      setOptions($("#segment"), [...new Set(state.accounts.map((item) => item.segment))].sort(), "All service segments");
      renderAccounts();
    } catch (error) { showError(error); }

    for (const selector of ["#country", "#segment", "#priority", "#include-hold", "#sort"]) {
      $(selector).addEventListener("change", () => { state.page = 0; renderAccounts(); });
    }
    $("#search").addEventListener("input", () => { state.page = 0; renderAccounts(); });
    $("#select-visible").addEventListener("change", () => {
      const visible = getFiltered().slice(state.page * state.pageSize, (state.page + 1) * state.pageSize);
      for (const account of visible) {
        if ($("#select-visible").checked) state.selected.add(account.id);
        else state.selected.delete(account.id);
      }
      renderAccounts();
    });
    $("#previous-page").addEventListener("click", () => { state.page -= 1; renderAccounts(); });
    $("#next-page").addEventListener("click", () => { state.page += 1; renderAccounts(); });
    $("#export-selected").addEventListener("click", exportSelected);
    for (const button of document.querySelectorAll(".nav-link")) {
      button.addEventListener("click", () => setView(button.dataset.view));
    }
    $("#close-dialog").addEventListener("click", () => $("#detail-dialog").close());
    $("#detail-dialog").addEventListener("click", (event) => {
      if (event.target === $("#detail-dialog")) $("#detail-dialog").close();
    });
    $("#detail-dialog").addEventListener("close", clearError);
  }
  document.addEventListener("DOMContentLoaded", initialize, { once: true });
})();
