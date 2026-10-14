const $ = (selector) => document.querySelector(selector);
let config = null;
let toastTimer = null;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = error ? "show error" : "show";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { element.className = ""; }, 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch (_) { /* no JSON body */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function selectedValues(selector) {
  return Array.from($(selector).selectedOptions).map((option) => option.value);
}

function parseGameTime(value) {
  if (/^\d+$/.test(value.trim())) return Number(value);
  const match = value.trim().match(/^(\d+):(\d{1,2})$/);
  if (!match || Number(match[2]) > 59) throw new Error("Game time must be MM:SS or seconds.");
  return Number(match[1]) * 60 + Number(match[2]);
}

function formatTime(seconds) {
  const minutes = Math.floor((seconds || 0) / 60);
  return `${minutes}:${String((seconds || 0) % 60).padStart(2, "0")}`;
}

async function loadCatalog() {
  config = await api("/api/v1/catalog");
  const heroes = config.heroes.map((hero) => `<option>${escapeHtml(hero.name)}</option>`).join("");
  $("#hero").innerHTML = heroes;
  $("#enemies").innerHTML = heroes;
  $("#role").innerHTML = config.roles.map((role) => `<option value="${escapeHtml(role)}">${escapeHtml(role.replaceAll("_", " "))}</option>`).join("");
  $("#inventory").innerHTML = config.items.map((item) => `<option>${escapeHtml(item.name)}</option>`).join("");
  $("#interval").value = config.capture_interval_seconds;
}

async function loadMonitors() {
  try {
    const monitors = await api("/api/v1/monitors");
    $("#monitor").innerHTML = monitors.map((monitor) => `<option value="${monitor.index}">Monitor ${monitor.index} · ${monitor.width}×${monitor.height}${monitor.primary ? " · primary" : ""}</option>`).join("");
  } catch (error) {
    $("#monitor").innerHTML = "<option value='1'>Monitor 1</option>";
    toast(error.message, true);
  }
}

function manualPayload() {
  const extras = $("#inventory-extra").value.split(",").map((name) => name.trim()).filter(Boolean);
  const levelValue = $("#level").value;
  return {
    hero: $("#hero").value,
    role: $("#role").value,
    game_time_seconds: parseGameTime($("#game-time").value),
    gold: Number($("#gold").value),
    level: levelValue ? Number(levelValue) : null,
    inventory: [...new Set([...selectedValues("#inventory"), ...extras])],
    enemy_heroes: selectedValues("#enemies")
  };
}

async function saveAndRecommend(event) {
  event.preventDefault();
  try {
    await api("/api/v1/state/manual", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(manualPayload())});
    await api("/api/v1/recommendations", {method: "POST"});
    toast("Context saved and recommendations refreshed.");
    await poll();
  } catch (error) { toast(error.message, true); }
}

function showWarnings(warnings) {
  const box = $("#warnings");
  box.hidden = !warnings?.length;
  box.innerHTML = (warnings || []).map((warning) => `<p>${escapeHtml(warning)}</p>`).join("");
}

function renderState(state) {
  if (!state) return;
  const fields = [
    ["Hero", state.hero || "—"], ["Role", state.role.replaceAll("_", " ")],
    ["Gold", state.gold], ["Game time", formatTime(state.game_time_seconds)],
    ["Level", state.level ?? "—"], ["Source", state.source],
    ["Inventory", state.inventory.join(", ") || "Empty"],
    ["Enemies", state.enemy_heroes.join(", ") || "None selected"],
    ["Confidence", `${Math.round(state.extraction_confidence * 100)}%`]
  ];
  $("#state").className = "state-grid";
  $("#state").innerHTML = fields.map(([label, value]) => `<div class="state-value"><small>${escapeHtml(label)}</small><span class="${label === "Confidence" ? "confidence" : ""}">${escapeHtml(value)}</span></div>`).join("");
  $("#last-update").textContent = new Date(state.detected_at).toLocaleString();
  const low = Object.entries(state.field_confidence || {}).filter(([, value]) => value < (config?.confidence_threshold ?? .65)).map(([field, value]) => `${field.replaceAll("_", " ")}: ${Math.round(value * 100)}% confidence; trusted value retained when available.`);
  if (low.length) showWarnings(low);
}

function renderRecommendations(recommendations) {
  const target = $("#recommendations");
  if (!recommendations.length) { target.className = "recommendations empty-state"; target.textContent = "No recommendations yet."; return; }
  target.className = "recommendations";
  target.innerHTML = recommendations.map((recommendation, index) => {
    const rows = Object.entries(recommendation.score_breakdown).map(([name, value]) => `<tr><td>${escapeHtml(name.replaceAll("_", " "))}</td><td>${Number(value).toFixed(2)}</td></tr>`).join("");
    const threats = recommendation.addressed_threats.length ? recommendation.addressed_threats.map((threat) => `<span class="tag">${escapeHtml(threat)}</span>`).join("") : "<span class='tag'>general build fit</span>";
    const component = recommendation.next_component ? `${escapeHtml(recommendation.next_component)} (${recommendation.next_component_cost} gold; ${recommendation.additional_gold_required} more needed)` : "Build complete or no component data";
    const citations = recommendation.retrieved_sources.length ? recommendation.retrieved_sources.map(escapeHtml).join(", ") : "No matching note";
    return `<article class="recommendation"><span class="rank">#${index + 1}</span><h3>${escapeHtml(recommendation.item_name)}</h3><div class="score">${Math.round(recommendation.total_score * 100)}<small>/100</small></div><p>${escapeHtml(recommendation.reason)}</p><div class="threats">${threats}</div><p><strong>Next component:</strong> ${component}</p><p class="source-id">Sources: ${citations}</p><details><summary>Score breakdown</summary><table class="score-table">${rows}</table></details></article>`;
  }).join("");
}

function renderRetrieval(passages) {
  const target = $("#retrieval");
  if (!passages.length) { target.className = "passages empty-state"; target.textContent = "No passages retrieved yet."; return; }
  target.className = "passages";
  target.innerHTML = passages.map((passage) => `<details class="passage"><summary><strong>${escapeHtml(passage.title)}</strong> · ${Math.round(passage.relevance_score * 100)}% relevance</summary><p>${escapeHtml(passage.content)}</p><div class="threats">${passage.threat_tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div><span class="source-id">${escapeHtml(passage.source_id)} · ${escapeHtml(passage.patch_version)}</span></details>`).join("");
}

function renderStatus(status) {
  const pill = $("#capture-pill");
  pill.textContent = status.running ? "Running" : "Stopped";
  pill.className = status.running ? "status-pill running" : "status-pill";
  $("#capture-meta").textContent = `Captured ${status.capture_count} · analyzed ${status.analysis_count} · unchanged ${status.skipped_unchanged_count}${status.last_error ? ` · ${status.last_error}` : ""}`;
  $("#debug-crops").innerHTML = Object.entries(status.debug_crops || {}).map(([name, url]) => `<figure><img src="${escapeHtml(url)}?t=${Date.now()}" alt="${escapeHtml(name)} crop"><figcaption>${escapeHtml(name)}</figcaption></figure>`).join("");
}

async function poll() {
  try {
    const [status, state, recommendations, passages] = await Promise.all([
      api("/api/v1/capture/status"), api("/api/v1/state"), api("/api/v1/recommendations/latest"), api("/api/v1/retrieval/latest")
    ]);
    renderStatus(status); renderState(state); renderRecommendations(recommendations); renderRetrieval(passages);
  } catch (error) { console.error(error); }
}

async function captureAction(action) {
  try {
    const monitor = Number($("#monitor").value || 1);
    if (action === "start") await api("/api/v1/capture/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({monitor_index: monitor, interval_seconds: Number($("#interval").value)})});
    if (action === "stop") await api("/api/v1/capture/stop", {method: "POST"});
    if (action === "once") {
      const result = await api(`/api/v1/capture/once?monitor_index=${monitor}`, {method: "POST"});
      showWarnings(result.warnings);
    }
    await poll();
  } catch (error) { toast(error.message, true); }
}

async function uploadScreenshot(event) {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData(); form.append("screenshot", file);
  try {
    const result = await api("/api/v1/screenshots/analyze?force=true", {method: "POST", body: form});
    showWarnings(result.warnings); toast("Screenshot analyzed."); await poll();
  } catch (error) { toast(error.message, true); }
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#manual-form").addEventListener("submit", saveAndRecommend);
  $("#capture-start").addEventListener("click", () => captureAction("start"));
  $("#capture-stop").addEventListener("click", () => captureAction("stop"));
  $("#capture-once").addEventListener("click", () => captureAction("once"));
  $("#recommend").addEventListener("click", async () => { try { await api("/api/v1/recommendations", {method: "POST"}); await poll(); } catch (error) { toast(error.message, true); } });
  $("#screenshot").addEventListener("change", uploadScreenshot);
  try { await Promise.all([loadCatalog(), loadMonitors()]); await poll(); } catch (error) { toast(error.message, true); }
  setInterval(poll, 2000);
});

