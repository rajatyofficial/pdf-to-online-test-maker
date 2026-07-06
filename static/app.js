const SECTIONS = ["Reasoning", "GK", "Maths", "English"];
const SECTION_LIMIT = 15 * 60;
const MODEL_PRESETS = [
  {value: "gemma", label: "Fast - gemma"},
  {value: "qwen2.5vl:3b", label: "Vision - qwen2.5vl:3b"},
  {value: "granite3.2-vision:2b", label: "Document OCR - granite3.2-vision:2b"},
  {value: "gemma3:4b", label: "Lightweight - gemma3:4b"},
  {value: "minicpm-v", label: "Experimental - minicpm-v"},
  {value: "llava-llama3:8b", label: "Experimental - llava-llama3:8b"},
];
const app = document.querySelector("#app");
const navButtons = [...document.querySelectorAll(".nav-button")];
const llmStatus = document.querySelector("#llmStatus");

const state = {
  tests: [],
  history: [],
  attempt: null,
  result: null,
  preferredModel: localStorage.getItem("preferredModel") || "gemma",
};

document.addEventListener("click", (event) => {
  const routeButton = event.target.closest("[data-route]");
  if (routeButton) {
    navigate(routeButton.dataset.route);
  }
});

window.addEventListener("hashchange", route);
boot();

async function boot() {
  await checkHealth();
  await loadTests();
  await loadHistory();
  route();
}

function navigate(routeName) {
  location.hash = routeName;
}

function route() {
  const routeName = (location.hash || "#home").slice(1);
  navButtons.forEach((button) => button.classList.toggle("active", button.dataset.route === routeName));
  if (routeName === "import") return renderImport();
  if (routeName === "tests") return renderTests();
  if (routeName === "history") return renderHistory();
  if (routeName === "settings") return renderSettings();
  if (routeName === "attempt" && state.attempt) return renderAttempt();
  if (routeName === "result" && state.result) return renderResult();
  return renderHome();
}

async function checkHealth() {
  try {
    const health = await api("/api/health");
    const parts = [];
    if (health.gemini?.available) parts.push("Gemini ready");
    if (health.ollama?.available) parts.push("Local model ready");
    llmStatus.textContent = parts.length ? parts.join(" | ") : "Parser ready, model optional";
    llmStatus.title = `Ollama: ${health.ollama?.message || ''}\nGemini: ${health.gemini?.message || ''}`;
  } catch {
    llmStatus.textContent = "Parser ready";
  }
}

async function loadTests() {
  const data = await api("/api/tests");
  state.tests = data.tests;
}

async function loadHistory() {
  const data = await api("/api/history");
  state.history = data.history;
}

async function renderSettings() {
  const data = await api("/api/settings");
  const hasKey = data.settings.has_gemini_key;
  const maskedKey = data.settings.gemini_api_key;
  
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h2 class="page-title">Settings</h2>
        <p class="page-subtitle">Configure application preferences</p>
      </div>
    </div>
    <section class="card" style="max-width: 600px;">
      <h3>Gemini API Configuration</h3>
      <p class="muted" style="margin-bottom:16px;">Using Gemini Flash significantly speeds up question parsing compared to local Ollama models.</p>
      
      <form id="settingsForm">
        <div class="form-row">
          <label for="gemini_api_key">Google AI Studio API Key</label>
          <input class="file-input" type="password" id="gemini_api_key" name="gemini_api_key" 
                 placeholder="${hasKey ? '••••••••' + maskedKey.slice(-4) : 'AIzaSy...'}" />
          ${hasKey ? '<small style="color:var(--success);margin-top:4px;display:block;">✓ API Key is currently saved</small>' : ''}
        </div>
        
        <div class="actions" style="margin-top:20px; display:flex; gap:12px;">
          <button class="button primary" type="submit">Save Key</button>
          <button class="button" type="button" id="removeKeyBtn">Remove Key</button>
        </div>
      </form>
    </section>
  `;

  document.getElementById("settingsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const key = document.getElementById("gemini_api_key").value.trim();
    if (!key) return;
    
    const btn = e.target.querySelector('button[type="submit"]');
    btn.textContent = "Saving...";
    btn.disabled = true;
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify({ gemini_api_key: key }) });
      await checkHealth();
      location.reload();
    } catch (err) {
      alert("Failed to save settings: " + err.message);
      btn.textContent = "Save Key";
      btn.disabled = false;
    }
  });

  document.getElementById("removeKeyBtn").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.textContent = "Removing...";
    btn.disabled = true;
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify({ gemini_api_key: "" }) });
      await checkHealth();
      location.reload();
    } catch (err) {
      alert("Failed to remove key: " + err.message);
      btn.textContent = "Remove Key";
      btn.disabled = false;
    }
  });
}

function renderHome() {
  const dashboard = buildDashboardData();
  const totalAttempts = state.history.length;
  const bestScore = state.history.reduce((best, item) => Math.max(best, item.score), 0);
  const latestRating = dashboard.ratingPoints.at(-1)?.rating || 1500;
  const avgAccuracy = totalAttempts
    ? state.history.reduce((total, item) => total + item.accuracy, 0) / totalAttempts
    : 0;
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h2 class="page-title">Dashboard</h2>
        <p class="page-subtitle">Performance trends across tests and sections</p>
      </div>
      <div class="actions">
        <button class="button" id="homeImport">Create New Test</button>
        <button class="button secondary" id="homeTests">Existing Tests</button>
      </div>
    </div>
    <div class="grid four">
      <section class="card metric"><span>Saved tests</span><strong>${state.tests.length}</strong></section>
      <section class="card metric"><span>Attempts</span><strong>${totalAttempts}</strong></section>
      <section class="card metric"><span>Current rating</span><strong>${latestRating}</strong></section>
      <section class="card metric"><span>Avg accuracy</span><strong>${formatScore(avgAccuracy)}%</strong></section>
    </div>
    <section class="card chart-panel" style="margin-top:16px">
      <div class="section-head">
        <div>
          <h3>Rating Trend</h3>
          <p class="muted">A local rating-style score graph based on completed attempts</p>
        </div>
        <span class="badge">${formatScore(bestScore)} best score</span>
      </div>
      ${renderRatingChart(dashboard.ratingPoints)}
    </section>
    <section class="card" style="margin-top:16px">
      <div class="section-head">
        <div>
          <h3>Subject Dashboard</h3>
          <p class="muted">Score percentage, accuracy, and attempts by section</p>
        </div>
      </div>
      ${renderSubjectDashboard(dashboard.subjects)}
    </section>
    <section class="card" style="margin-top:16px">
      <div class="section-head">
        <div>
          <h3>Test Wise Subjects</h3>
          <p class="muted">Each test broken down by subject performance</p>
        </div>
      </div>
      ${renderTestSubjectDashboard(dashboard.testSubjects)}
    </section>
    <div class="grid two" style="margin-top:16px">
      <section class="card">
        <h3>Recent Tests</h3>
        ${state.tests.slice(0, 5).map(testRow).join("") || `<p class="muted">No tests imported yet.</p>`}
      </section>
      <section class="card">
        <h3>Recent Attempts</h3>
        ${state.history.slice(0, 5).map(historyMiniRow).join("") || `<p class="muted">No attempts yet.</p>`}
      </section>
    </div>
  `;
  document.querySelector("#homeImport").addEventListener("click", () => navigate("import"));
  document.querySelector("#homeTests").addEventListener("click", () => navigate("tests"));
  wireTestButtons();
  wireDeleteButtons();
}

function buildDashboardData() {
  const attemptsAsc = [...state.history].sort((a, b) => new Date(a.completed_at) - new Date(b.completed_at));
  let rating = 1500;
  const ratingPoints = attemptsAsc.map((attempt, index) => {
    const scorePercent = attempt.max_score ? (attempt.score / attempt.max_score) * 100 : 0;
    const normalized = Math.max(0, Math.min(100, scorePercent));
    rating = Math.max(300, Math.round(rating + (normalized - 50) * 1.4));
    return {
      index: index + 1,
      rating,
      scorePercent,
      testName: attempt.test_name,
      label: attempt.label,
      completedAt: attempt.completed_at,
    };
  });

  const subjects = Object.fromEntries(SECTIONS.map((section) => [section, newSubjectAggregate()]));
  const testSubjects = state.tests.map((test) => ({
    test,
    subjects: Object.fromEntries(SECTIONS.map((section) => [section, newSubjectAggregate()])),
  }));
  const testSubjectById = new Map(testSubjects.map((entry) => [entry.test.id, entry.subjects]));

  state.history.forEach((attempt) => {
    Object.entries(attempt.section_metrics || {}).forEach(([section, metrics]) => {
      if (!subjects[section]) return;
      addSubjectMetrics(subjects[section], metrics);
      const bySection = testSubjectById.get(attempt.test_id);
      if (bySection?.[section]) addSubjectMetrics(bySection[section], metrics);
    });
  });

  Object.values(subjects).forEach(finalizeSubjectAggregate);
  testSubjects.forEach((entry) => Object.values(entry.subjects).forEach(finalizeSubjectAggregate));
  return {ratingPoints, subjects, testSubjects};
}

function newSubjectAggregate() {
  return {
    attempts: 0,
    total: 0,
    correct: 0,
    wrong: 0,
    skipped: 0,
    score: 0,
    maxScore: 0,
    timeSpentSeconds: 0,
    scorePercent: 0,
    accuracy: 0,
  };
}

function addSubjectMetrics(target, metrics) {
  if (!metrics || !metrics.total) return;
  target.attempts += 1;
  target.total += metrics.total;
  target.correct += metrics.correct || 0;
  target.wrong += metrics.wrong || 0;
  target.skipped += metrics.skipped || 0;
  target.score += metrics.score || 0;
  target.maxScore += (metrics.total || 0) * 2;
  target.timeSpentSeconds += metrics.time_spent_seconds || 0;
}

function finalizeSubjectAggregate(target) {
  const attempted = target.correct + target.wrong;
  target.scorePercent = target.maxScore ? (target.score / target.maxScore) * 100 : 0;
  target.accuracy = attempted ? (target.correct / attempted) * 100 : 0;
}

function renderRatingChart(points) {
  if (!points.length) {
    return `<div class="empty-chart">Complete attempts to build your rating curve.</div>`;
  }
  const chartPoints = [
    {index: 0, rating: 1500, testName: "Start", label: "Baseline", completedAt: ""},
    ...points,
  ];
  const width = 900;
  const height = 260;
  const left = 50;
  const right = 20;
  const top = 22;
  const bottom = 42;
  const ratings = chartPoints.map((point) => point.rating);
  const minRating = Math.min(...ratings, 1500) - 60;
  const maxRating = Math.max(...ratings, 1500) + 60;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const xFor = (index) => left + (index / (chartPoints.length - 1)) * plotWidth;
  const yFor = (value) => top + ((maxRating - value) / (maxRating - minRating)) * plotHeight;
  const coords = chartPoints.map((point, index) => ({...point, x: xFor(index), y: yFor(point.rating)}));
  const line = coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  const area = `${line} L ${coords.at(-1).x.toFixed(1)} ${height - bottom} L ${coords[0].x.toFixed(1)} ${height - bottom} Z`;
  return `
    <div class="rating-chart-wrap">
      <svg class="rating-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Rating trend">
        <line class="chart-axis" x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}"></line>
        <line class="chart-axis" x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}"></line>
        <text class="chart-label" x="8" y="${yFor(maxRating - 60).toFixed(1)}">${Math.round(maxRating - 60)}</text>
        <text class="chart-label" x="8" y="${yFor(minRating + 60).toFixed(1)}">${Math.round(minRating + 60)}</text>
        <path class="chart-area" d="${area}"></path>
        <path class="chart-line" d="${line}"></path>
        ${coords.map((point) => `
          <g>
            <title>${escapeHtml(point.testName)} - ${escapeHtml(point.label)} - Rating ${point.rating}</title>
            <circle class="chart-dot" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="5"></circle>
          </g>
        `).join("")}
      </svg>
      <div class="chart-caption">
        <span>Start 1500</span>
        <span>Latest ${points.at(-1).rating}</span>
      </div>
    </div>
  `;
}

function renderSubjectDashboard(subjects) {
  if (!state.history.length) return `<p class="muted">No attempts yet.</p>`;
  return `
    <div class="subject-grid">
      ${SECTIONS.map((section) => {
        const item = subjects[section];
        return `
          <div class="subject-card">
            <div class="subject-title">
              <strong>${escapeHtml(section)}</strong>
              <span>${item.attempts} attempt${item.attempts === 1 ? "" : "s"}</span>
            </div>
            <div class="progress-track">
              <div class="progress-fill" style="width:${clampPercent(item.scorePercent)}%"></div>
            </div>
            <div class="subject-stats">
              <span>Score ${formatScore(item.score)} / ${formatScore(item.maxScore)}</span>
              <span>Accuracy ${formatScore(item.accuracy)}%</span>
            </div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderTestSubjectDashboard(testSubjects) {
  if (!state.tests.length) return `<p class="muted">No tests imported yet.</p>`;
  return `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Test</th>
            ${SECTIONS.map((section) => `<th>${escapeHtml(section)}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${testSubjects.map(({test, subjects}) => `
            <tr>
              <td><strong>${escapeHtml(test.name)}</strong><br><span class="muted">${test.attempt_count || 0} attempts</span></td>
              ${SECTIONS.map((section) => `<td>${renderSubjectCell(subjects[section])}</td>`).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderSubjectCell(item) {
  if (!item.attempts) return `<span class="muted">No data</span>`;
  return `
    <div class="subject-cell">
      <strong>${formatScore(item.scorePercent)}%</strong>
      <span>${formatScore(item.score)} / ${formatScore(item.maxScore)}</span>
      <span>${formatScore(item.accuracy)}% accuracy</span>
    </div>
  `;
}

function renderImport() {
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h2 class="page-title">Create New Test</h2>
        <p class="page-subtitle">Import one 100-question SSC PDF</p>
      </div>
    </div>
    <section class="card">
      <form id="importForm">
        <div class="form-row">
          <label for="pdf">PDF file</label>
          <input class="file-input" id="pdf" name="pdf" type="file" accept="application/pdf" required />
        </div>
        <div class="form-row">
          <label>Parsing Engine</label>
          <div style="display:flex; gap:16px; align-items:center;">
            <label style="display:flex; align-items:center; gap:8px;">
              <input type="radio" name="engine" value="gemini" checked /> Gemini (Online, Faster)
            </label>
            <label style="display:flex; align-items:center; gap:8px;">
              <input type="radio" name="engine" value="ollama" /> Ollama (Local)
            </label>
          </div>
        </div>
        <div class="form-row" id="ollamaModelRow" style="display:none;">
          <label for="model">Ollama model</label>
          ${renderModelSelector("model", "ollama_model", state.preferredModel)}
        </div>
        <label class="check-row" style="margin-top:8px;">
          <input type="checkbox" name="use_llm" checked />
          <span>Use VLM; Maths & Reasoning questions always use image crops for extraction</span>
        </label>
        <div class="actions" style="margin-top:20px;">
          <button class="button primary" type="submit" id="importButton">Import PDF</button>
        </div>
      </form>
    </section>
    <div id="importResult" style="margin-top:16px"></div>
  `;
  
  const form = document.getElementById("importForm");
  const engineRadios = form.querySelectorAll('input[name="engine"]');
  const ollamaRow = document.getElementById("ollamaModelRow");
  
  engineRadios.forEach(radio => {
    radio.addEventListener("change", () => {
      ollamaRow.style.display = form.engine.value === "ollama" ? "block" : "none";
    });
  });

  form.addEventListener("submit", importPdf);
}

function renderModelSelector(id, name, selected) {
  const options = MODEL_PRESETS.map((model) => `
    <option value="${escapeHtml(model.value)}" ${model.value === selected ? "selected" : ""}>${escapeHtml(model.label)}</option>
  `).join("");
  return `
    <select class="select-input" id="${escapeHtml(id)}" name="${escapeHtml(name)}">
      ${options}
    </select>
  `;
}

async function importPdf(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#importButton");
  const result = document.querySelector("#importResult");
  const formData = new FormData(form);
  formData.set("use_llm", form.querySelector("[name='use_llm']").checked ? "true" : "false");
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span> Importing`;
  result.innerHTML = `<div class="notice">Parsing PDF and saving the test...</div>`;
  try {
    const payload = await api("/api/tests/import", { method: "POST", body: formData });
    state.preferredModel = formData.get("ollama_model") || state.preferredModel;
    localStorage.setItem("preferredModel", state.preferredModel);
    await loadTests();
    result.innerHTML = renderImportReport(payload.report, payload.test);
    wireTestButtons();
  } catch (error) {
    result.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  } finally {
    button.disabled = false;
    button.textContent = "Import PDF";
  }
}

function renderImportReport(report, test) {
  const warnings = report.warnings?.length
    ? `<div class="error">${report.warnings.map(escapeHtml).join("<br>")}</div>`
    : `<div class="notice">Import completed.</div>`;
  return `
    ${warnings}
    <section class="card" style="margin-top:12px">
      <h3>${escapeHtml(test.name)}</h3>
      <div class="grid three">
        <div class="metric"><span>Questions</span><strong>${report.question_count}</strong></div>
        <div class="metric"><span>Answers</span><strong>${report.answer_count}</strong></div>
        <div class="metric"><span>Question images</span><strong>${report.asset_count}</strong></div>
      </div>
      <div class="grid two" style="margin-top:14px">
        <div>
          <strong>Sections</strong>
          <p class="muted">${Object.entries(report.sections).map(([key, value]) => `${key}: ${value}`).join(" - ")}</p>
        </div>
        <div>
          <strong>LLM</strong>
          <p class="muted">${escapeHtml(report.llm.status)} - Used ${report.llm.used} time(s), ${report.llm.succeeded || 0} full, ${report.llm.partial || 0} partial, ${report.llm.rejected || 0} rejected, ${report.llm.failed || 0} failed</p>
        </div>
      </div>
      <div class="actions" style="margin-top:16px">
        <button class="button" data-start-test="${test.id}" data-mode="test">Start Test</button>
        <button class="button secondary" data-route="tests">Existing Tests</button>
      </div>
    </section>
  `;
}

function renderTests() {
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h2 class="page-title">Existing Tests</h2>
        <p class="page-subtitle">${state.tests.length} saved test${state.tests.length === 1 ? "" : "s"}</p>
      </div>
      <button class="button" data-route="import">Create New Test</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Test</th>
            <th>Questions</th>
            <th>Imported</th>
            <th>Attempts</th>
            <th>Parser</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${state.tests.map(testTableRow).join("") || `<tr><td colspan="6">No tests imported yet.</td></tr>`}
        </tbody>
      </table>
    </div>
    <div id="sprintPanel"></div>
  `;
  wireTestButtons();
  wireDeleteButtons();
}

function testTableRow(test) {
  const report = test.import_report || {};
  const warningClass = report.manual_review_count ? "warn" : "";
  const parserText = report.manual_review_count
    ? `${report.manual_review_count} review`
    : `${report.llm?.used || 0} LLM / ${(report.llm?.succeeded || 0) + (report.llm?.partial || 0)} ok / ${report.llm?.rejected || 0} rejected`;
  return `
    <tr>
      <td><strong>${escapeHtml(test.name)}</strong><br><span class="muted">${escapeHtml(test.source_filename)}</span></td>
      <td>${test.question_count}</td>
      <td>${formatDate(test.imported_at)}</td>
      <td>${test.attempt_count || 0}</td>
      <td><span class="badge ${warningClass}">${escapeHtml(parserText)}</span></td>
      <td>
        <div class="actions">
          <button class="button" data-start-test="${test.id}" data-mode="test">Full Test</button>
          <button class="button secondary" data-start-test="${test.id}" data-mode="practice">Practice</button>
          <button class="button secondary" data-sprint="${test.id}">Sprint</button>
          <button class="button warn" data-rebuild-maths="${test.id}">Rebuild Maths LaTeX</button>
          <button class="button danger" data-delete-test="${test.id}">Delete</button>
        </div>
      </td>
    </tr>
  `;
}

function renderHistory() {
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h2 class="page-title">Test History</h2>
        <p class="page-subtitle">${state.history.length} saved attempt${state.history.length === 1 ? "" : "s"}</p>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Test</th>
            <th>Attempt</th>
            <th>Mode</th>
            <th>Score</th>
            <th>Correct</th>
            <th>Wrong</th>
            <th>Skipped</th>
            <th>Accuracy</th>
            <th>Completed</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          ${state.history.map(historyRow).join("") || `<tr><td colspan="10">No attempt history yet.</td></tr>`}
        </tbody>
      </table>
    </div>
  `;
  wireTestButtons();
  wireDeleteButtons();
}

function wireTestButtons() {
  document.querySelectorAll("[data-start-test]").forEach((button) => {
    button.addEventListener("click", () => startAttempt(Number(button.dataset.startTest), button.dataset.mode));
  });
  document.querySelectorAll("[data-sprint]").forEach((button) => {
    button.addEventListener("click", () => renderSprintPanel(Number(button.dataset.sprint)));
  });
  document.querySelectorAll("[data-rebuild-maths]").forEach((button) => {
    button.addEventListener("click", () => rebuildMathsLatex(Number(button.dataset.rebuildMaths), button));
  });
}

function wireDeleteButtons() {
  document.querySelectorAll("[data-delete-test]").forEach((button) => {
    button.addEventListener("click", () => deleteTest(Number(button.dataset.deleteTest)));
  });
  document.querySelectorAll("[data-delete-attempt]").forEach((button) => {
    button.addEventListener("click", () => deleteAttempt(Number(button.dataset.deleteAttempt)));
  });
}

async function deleteTest(testId) {
  const test = state.tests.find((item) => item.id === testId);
  const name = test?.name || "this test";
  if (!confirm(`Delete "${name}" and all its attempts? This cannot be undone.`)) return;
  await api(`/api/tests/${testId}`, {method: "DELETE"});
  await loadTests();
  await loadHistory();
  state.result = null;
  route();
}

async function deleteAttempt(attemptId) {
  const attempt = state.history.find((item) => item.id === attemptId);
  const name = attempt ? `${attempt.test_name} - ${attempt.label}` : "this attempt";
  if (!confirm(`Remove "${name}" from history? This cannot be undone.`)) return;
  await api(`/api/attempts/${attemptId}`, {method: "DELETE"});
  await loadTests();
  await loadHistory();
  if (state.result?.id === attemptId) state.result = null;
  route();
}

async function rebuildMathsLatex(testId, button) {
  const test = state.tests.find((item) => item.id === testId);
  const name = test?.name || "this test";
  const model = prompt("Ollama model for Maths rebuild:", state.preferredModel || "gemma");
  if (!model) return;
  state.preferredModel = model.trim();
  localStorage.setItem("preferredModel", state.preferredModel);
  if (!confirm(`Rebuild Maths LaTeX for "${name}" using ${state.preferredModel}? This can take a few minutes.`)) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span> Rebuilding`;
  try {
    const payload = await api(`/api/tests/${testId}/rebuild-maths`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ollama_model: state.preferredModel}),
    });
    await loadTests();
    await loadHistory();
    alert(`Updated ${payload.updated} Maths questions. LLM used ${payload.report.llm.used} time(s), ${payload.report.llm.succeeded || 0} full, ${payload.report.llm.partial || 0} partial, ${payload.report.llm.rejected || 0} rejected, ${payload.report.llm.failed || 0} failed.`);
    route();
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function renderSprintPanel(testId) {
  const panel = document.querySelector("#sprintPanel") || app;
  panel.innerHTML = `
    <section class="card" style="margin-top:16px">
      <h3>Section Sprint</h3>
      <div class="section-picker">
        ${SECTIONS.map((section) => `
          <label class="section-tile">
            <input type="checkbox" name="sprintSection" value="${section}" checked />
            ${section}
          </label>
        `).join("")}
      </div>
      <div class="actions">
        <button class="button" id="startSprint">Start Sprint</button>
      </div>
    </section>
  `;
  document.querySelector("#startSprint").addEventListener("click", () => {
    const selected = [...document.querySelectorAll("[name='sprintSection']:checked")].map((input) => input.value);
    if (!selected.length) return alert("Select at least one section.");
    startAttempt(testId, "section_sprint", selected);
  });
}

async function startAttempt(testId, mode, selectedSections = SECTIONS) {
  const test = await api(`/api/tests/${testId}`);
  const questions = test.questions.filter((question) => selectedSections.includes(question.section));
  state.attempt = {
    test,
    mode,
    selectedSections,
    questions,
    sectionIndex: 0,
    questionIndexBySection: Object.fromEntries(selectedSections.map((section) => [section, 0])),
    answers: {},
    flagged: {},
    timings: {},
    startedAt: new Date(),
    remainingBySection: Object.fromEntries(selectedSections.map((section) => [section, SECTION_LIMIT])),
    paused: false,
    interval: null,
  };
  location.hash = "attempt";
  renderAttempt();
  state.attempt.interval = setInterval(tickAttempt, 1000);
}

function renderAttempt() {
  const attempt = state.attempt;
  if (!attempt) return renderTests();
  const section = attempt.selectedSections[attempt.sectionIndex];
  const sectionQuestions = questionsForCurrentSection();
  const currentIndex = attempt.questionIndexBySection[section] || 0;
  const question = sectionQuestions[currentIndex];
  app.innerHTML = `
    <div class="attempt-topbar">
      <div class="page-head">
        <div>
          <h2 class="page-title">${escapeHtml(attempt.test.name)}</h2>
          <p class="page-subtitle">${labelForMode(attempt.mode)} - ${escapeHtml(section)}</p>
        </div>
        <div class="actions">
          ${attempt.mode === "practice" ? `<button class="button secondary" id="pauseAttempt">${attempt.paused ? "Resume" : "Pause"}</button>` : ""}
          <button class="button danger" id="finishAttempt">Submit</button>
        </div>
      </div>
      <div class="timer-strip">
        ${attempt.selectedSections.map((item) => `
          <div class="timer-pill ${item === section ? "active" : ""}">
            <span>${item}</span>
            <strong data-section-time="${item}">${formatTimer(attempt.remainingBySection[item])}</strong>
          </div>
        `).join("")}
      </div>
    </div>
    <div class="attempt-layout">
      <section class="card question-card">
        ${renderQuestion(question, currentIndex, sectionQuestions.length)}
      </section>
      <aside class="side-panel">
        <section class="card">
          <h3>${escapeHtml(section)}</h3>
          <div class="question-grid">
            ${sectionQuestions.map((item, index) => questionNavButton(item, index, currentIndex)).join("")}
          </div>
        </section>
        <section class="card">
          <div class="actions">
            <button class="button secondary" id="prevQuestion">Previous</button>
            <button class="button secondary" id="nextQuestion">Next</button>
            <button class="button warn" id="flagQuestion">${attempt.flagged[question.id] ? "Unmark" : "Mark"}</button>
          </div>
        </section>
      </aside>
    </div>
  `;
  wireAttemptEvents(question);
  renderMath();
}

function renderQuestion(question, index, total) {
  return `
    <div class="question-meta">
      <span>Q${question.number} - ${escapeHtml(question.section)}</span>
      <span>${index + 1} of ${total}</span>
    </div>
    <div class="question-text math-text">${escapeHtml(question.display_text)}</div>
    ${question.assets?.length ? `
      <div class="asset-list">
        ${question.assets.map((asset) => `<img src="${asset.url}" alt="Question image ${question.number}" />`).join("")}
      </div>
    ` : ""}
    <div class="options">
      ${["a", "b", "c", "d"].map((key) => renderOption(question, key)).join("")}
    </div>
  `;
}

function renderOption(question, key) {
  const selected = state.attempt.answers[question.id] === key;
  return `
    <label class="option ${selected ? "selected" : ""}">
      <input type="radio" name="option" value="${key}" ${selected ? "checked" : ""} />
      <span class="option-text math-text"><strong>(${key})</strong> ${escapeHtml(question.options[key])}</span>
    </label>
  `;
}

function wireAttemptEvents(question) {
  document.querySelectorAll("[name='option']").forEach((input) => {
    input.addEventListener("change", () => {
      state.attempt.answers[question.id] = input.value;
      renderAttempt();
    });
  });
  document.querySelectorAll(".q-nav").forEach((button) => {
    button.addEventListener("click", () => {
      const section = state.attempt.selectedSections[state.attempt.sectionIndex];
      state.attempt.questionIndexBySection[section] = Number(button.dataset.index);
      renderAttempt();
    });
  });
  document.querySelector("#prevQuestion").addEventListener("click", previousQuestion);
  document.querySelector("#nextQuestion").addEventListener("click", nextQuestion);
  document.querySelector("#flagQuestion").addEventListener("click", () => {
    state.attempt.flagged[question.id] = !state.attempt.flagged[question.id];
    renderAttempt();
  });
  document.querySelector("#finishAttempt").addEventListener("click", finishAttempt);
  const pause = document.querySelector("#pauseAttempt");
  if (pause) {
    pause.addEventListener("click", () => {
      state.attempt.paused = !state.attempt.paused;
      renderAttempt();
    });
  }
}

function tickAttempt() {
  const attempt = state.attempt;
  if (!attempt || attempt.paused) return;
  const section = attempt.selectedSections[attempt.sectionIndex];
  const question = currentQuestion();
  if (question) {
    attempt.timings[question.id] = (attempt.timings[question.id] || 0) + 1;
  }
  attempt.remainingBySection[section] -= 1;
  const timeNode = document.querySelector(`[data-section-time="${section}"]`);
  if (timeNode) timeNode.textContent = formatTimer(attempt.remainingBySection[section]);
  if (attempt.mode !== "practice" && attempt.remainingBySection[section] <= 0) {
    moveToNextSectionOrFinish();
  }
}

function previousQuestion() {
  const attempt = state.attempt;
  const section = attempt.selectedSections[attempt.sectionIndex];
  const current = attempt.questionIndexBySection[section] || 0;
  if (current > 0) {
    attempt.questionIndexBySection[section] = current - 1;
  } else if (attempt.sectionIndex > 0) {
    attempt.sectionIndex -= 1;
  }
  renderAttempt();
}

function nextQuestion() {
  const attempt = state.attempt;
  const section = attempt.selectedSections[attempt.sectionIndex];
  const current = attempt.questionIndexBySection[section] || 0;
  const total = questionsForCurrentSection().length;
  if (current < total - 1) {
    attempt.questionIndexBySection[section] = current + 1;
  } else if (attempt.sectionIndex < attempt.selectedSections.length - 1) {
    attempt.sectionIndex += 1;
  }
  renderAttempt();
}

function moveToNextSectionOrFinish() {
  const attempt = state.attempt;
  if (attempt.sectionIndex < attempt.selectedSections.length - 1) {
    attempt.sectionIndex += 1;
    renderAttempt();
  } else {
    finishAttempt();
  }
}

async function finishAttempt() {
  const attempt = state.attempt;
  if (!attempt) return;
  clearInterval(attempt.interval);
  const completedAt = new Date();
  const responses = attempt.questions.map((question) => ({
    question_id: question.id,
    selected_option: attempt.answers[question.id] || null,
    time_spent_seconds: attempt.timings[question.id] || 0,
    flagged: Boolean(attempt.flagged[question.id]),
  }));
  const payload = {
    test_id: attempt.test.id,
    mode: attempt.mode,
    selected_sections: attempt.selectedSections,
    started_at: attempt.startedAt.toISOString(),
    completed_at: completedAt.toISOString(),
    duration_seconds: Math.round((completedAt - attempt.startedAt) / 1000),
    responses,
  };
  state.result = await api("/api/attempts/submit", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  state.attempt = null;
  await loadTests();
  await loadHistory();
  location.hash = "result";
  renderResult();
}

function renderResult() {
  const result = state.result;
  if (!result) return renderHistory();
  app.innerHTML = `
    <div class="page-head">
      <div>
        <h2 class="page-title">Result</h2>
        <p class="page-subtitle">${escapeHtml(result.test_name)} - ${escapeHtml(result.label)}</p>
      </div>
      <div class="actions">
        <button class="button" data-start-test="${result.test_id}" data-mode="test">Reattempt</button>
        <button class="button secondary" data-route="history">History</button>
      </div>
    </div>
    <section class="card">
      <div class="result-score">
        <div class="metric"><span>Score</span><strong>${formatScore(result.score)} / ${formatScore(result.max_score)}</strong></div>
        <div class="metric"><span>Correct</span><strong>${result.correct_count}</strong></div>
        <div class="metric"><span>Wrong</span><strong>${result.wrong_count}</strong></div>
        <div class="metric"><span>Skipped</span><strong>${result.skipped_count}</strong></div>
      </div>
    </section>
    <section class="card" style="margin-top:16px">
      <h3>Section Metrics</h3>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Section</th><th>Score</th><th>Correct</th><th>Wrong</th><th>Skipped</th><th>Time</th></tr></thead>
          <tbody>
            ${Object.entries(result.section_metrics).map(([section, item]) => `
              <tr>
                <td>${escapeHtml(section)}</td>
                <td>${formatScore(item.score)}</td>
                <td>${item.correct}</td>
                <td>${item.wrong}</td>
                <td>${item.skipped}</td>
                <td>${formatDuration(item.time_spent_seconds)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    </section>
  `;
  wireTestButtons();
}

function questionsForCurrentSection() {
  const attempt = state.attempt;
  const section = attempt.selectedSections[attempt.sectionIndex];
  return attempt.questions.filter((question) => question.section === section);
}

function currentQuestion() {
  const attempt = state.attempt;
  const section = attempt.selectedSections[attempt.sectionIndex];
  return questionsForCurrentSection()[attempt.questionIndexBySection[section] || 0];
}

function questionNavButton(question, index, currentIndex) {
  const attempt = state.attempt;
  const classes = ["q-nav"];
  if (index === currentIndex) classes.push("current");
  if (attempt.answers[question.id]) classes.push("answered");
  if (attempt.flagged[question.id]) classes.push("flagged");
  return `<button class="${classes.join(" ")}" data-index="${index}">${question.number}</button>`;
}

function testRow(test) {
  return `
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;border-top:1px solid var(--line);padding:10px 0">
      <div><strong>${escapeHtml(test.name)}</strong><br><span class="muted">${test.question_count} questions</span></div>
      <button class="button secondary" data-start-test="${test.id}" data-mode="test">Start</button>
    </div>
  `;
}

function historyMiniRow(item) {
  return `
    <div style="border-top:1px solid var(--line);padding:10px 0">
      <strong>${escapeHtml(item.test_name)}</strong>
      <div class="muted">${escapeHtml(item.label)} - ${formatScore(item.score)} - ${formatDate(item.completed_at)}</div>
    </div>
  `;
}

function historyRow(item) {
  return `
    <tr>
      <td><strong>${escapeHtml(item.test_name)}</strong></td>
      <td>${escapeHtml(item.label)}</td>
      <td>${escapeHtml(labelForMode(item.mode))}</td>
      <td>${formatScore(item.score)} / ${formatScore(item.max_score)}</td>
      <td>${item.correct_count}</td>
      <td>${item.wrong_count}</td>
      <td>${item.skipped_count}</td>
      <td>${item.accuracy}%</td>
      <td>${formatDate(item.completed_at)}</td>
      <td>
        <div class="actions">
          <button class="button secondary" data-start-test="${item.test_id}" data-mode="test">Reattempt</button>
          <button class="button danger" data-delete-attempt="${item.id}">Remove</button>
        </div>
      </td>
    </tr>
  `;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(data.error || data || `Request failed: ${response.status}`);
  }
  return data;
}

function renderMath() {
  if (!window.renderMathInElement) return;
  document.querySelectorAll(".math-text").forEach((node) => {
    window.renderMathInElement(node, {
      delimiters: [
        {left: "$$", right: "$$", display: true},
        {left: "$", right: "$", display: false},
      ],
      throwOnError: false,
    });
  });
}

function formatTimer(seconds) {
  const sign = seconds < 0 ? "-" : "";
  const absolute = Math.abs(seconds);
  const minutes = Math.floor(absolute / 60).toString().padStart(2, "0");
  const secs = Math.floor(absolute % 60).toString().padStart(2, "0");
  return `${sign}${minutes}:${secs}`;
}

function formatDuration(seconds) {
  return formatTimer(Math.max(0, Math.round(seconds)));
}

function formatDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleString();
}

function formatScore(value) {
  return Number(value || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function labelForMode(mode) {
  if (mode === "section_sprint") return "Section Sprint";
  if (mode === "practice") return "Practice";
  return "Full Test";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
