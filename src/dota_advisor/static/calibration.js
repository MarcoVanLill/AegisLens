const $ = (selector) => document.querySelector(selector);
let regions = null;
let toastTimer = null;

function toast(message, error = false) {
  const element = $("#toast"); element.textContent = message; element.className = error ? "show error" : "show";
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { element.className = ""; }, 4000);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) { const body = await response.json(); throw new Error(body.detail || response.statusText); }
  return response.json();
}

function numberInput(name, coordinate, value) {
  return `<label>${coordinate}<input data-region="${name}" data-coordinate="${coordinate}" type="number" min="0" max="1" step="0.001" value="${value}" required></label>`;
}

function render(configuration) {
  regions = configuration;
  $("#layout-id").value = configuration.layout_id;
  $("#notes").value = configuration.notes;
  $("#layout-notes").textContent = `${configuration.reference_resolution.join("×")} reference · ${configuration.notes}`;
  $("#region-fields").innerHTML = Object.entries(configuration.regions).map(([name, region]) => `<fieldset class="region-editor"><legend>${name}</legend><div class="coordinate-grid">${numberInput(name, "x", region.x)}${numberInput(name, "y", region.y)}${numberInput(name, "width", region.width)}${numberInput(name, "height", region.height)}</div></fieldset>`).join("");
  document.querySelectorAll("[data-region]").forEach((input) => input.addEventListener("input", updatePreview));
  updatePreview();
}

function collect() {
  const next = {layout_id: $("#layout-id").value, reference_resolution: regions.reference_resolution, notes: $("#notes").value, regions: {}};
  document.querySelectorAll("[data-region]").forEach((input) => {
    next.regions[input.dataset.region] ||= {};
    next.regions[input.dataset.region][input.dataset.coordinate] = Number(input.value);
  });
  return next;
}

function updatePreview() {
  const current = collect();
  $("#frame-preview").innerHTML = Object.entries(current.regions).map(([name, region]) => `<div class="region-box" style="left:${region.x * 100}%;top:${region.y * 100}%;width:${region.width * 100}%;height:${region.height * 100}%">${name}</div>`).join("");
}

async function load() { try { render(await api("/api/v1/regions")); } catch (error) { toast(error.message, true); } }

document.addEventListener("DOMContentLoaded", () => {
  $("#regions-form").addEventListener("submit", async (event) => { event.preventDefault(); try { render(await api("/api/v1/regions", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(collect())})); toast("HUD regions saved. Change detection was reset."); } catch (error) { toast(error.message, true); } });
  $("#reload").addEventListener("click", load);
  load();
});

