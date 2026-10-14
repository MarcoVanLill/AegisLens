const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = (await response.json()).detail || message; } catch (_) { /* no JSON */ }
    throw new Error(message);
  }
  return response.json();
}

function timeLabel(seconds) {
  const minutes = Math.floor((seconds || 0) / 60);
  return `${minutes}:${String((seconds || 0) % 60).padStart(2, "0")}`;
}

function renderState(state) {
  $("#match-state").textContent = state
    ? `${state.hero || "Unknown hero"} · ${state.role.replaceAll("_", " ")} · ${state.gold} gold · ${timeLabel(state.game_time_seconds)} · ${Math.round(state.extraction_confidence * 100)}% confidence`
    : "Waiting for match context…";
}

function renderRecommendations(recommendations) {
  const target = $("#recommendations");
  if (!recommendations.length) {
    target.innerHTML = '<div class="empty">Save match context in the dashboard to receive recommendations.</div>';
    $("#updated-at").textContent = "Not updated";
    return;
  }
  target.innerHTML = recommendations.slice(0, 3).map((recommendation, index) => {
    const component = recommendation.next_component
      ? `${recommendation.next_component} · ${recommendation.additional_gold_required > 0 ? `${recommendation.additional_gold_required} more gold` : "affordable now"}`
      : "No remaining component";
    const threats = recommendation.addressed_threats.length
      ? `Answers: ${recommendation.addressed_threats.join(", ")}`
      : "General build fit";
    return `<article class="recommendation"><span class="rank">#${index + 1}</span><h2>${escapeHtml(recommendation.item_name)}</h2><span class="score">${Math.round(recommendation.total_score * 100)}/100</span><p class="reason">${escapeHtml(recommendation.reason)}</p><p class="buy-next">Buy: ${escapeHtml(component)}</p><p class="threats">${escapeHtml(threats)}</p></article>`;
  }).join("");
  $("#updated-at").textContent = new Date(recommendations[0].generated_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
}

function renderCapture(status) {
  $("#capture-status").textContent = status.running
    ? `Capture active · ${status.analysis_count} analyzed`
    : "Capture stopped";
  const message = $("#message");
  message.hidden = !status.last_error;
  message.textContent = status.last_error || "";
}

async function poll() {
  const connection = $("#connection");
  try {
    const [state, recommendations, capture] = await Promise.all([
      api("/api/v1/state"),
      api("/api/v1/recommendations/latest"),
      api("/api/v1/capture/status")
    ]);
    connection.textContent = "Live";
    connection.className = "status online";
    renderState(state);
    renderRecommendations(recommendations);
    renderCapture(capture);
  } catch (error) {
    connection.textContent = "Offline";
    connection.className = "status offline";
    const message = $("#message");
    message.hidden = false;
    message.textContent = error.message;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#refresh").addEventListener("click", async () => {
    try { await api("/api/v1/recommendations", {method: "POST"}); } catch (error) {
      const message = $("#message"); message.hidden = false; message.textContent = error.message;
    }
    await poll();
  });
  poll();
  setInterval(poll, 2000);
});

