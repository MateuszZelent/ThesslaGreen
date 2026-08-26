const HA_ENTRY_ID = new URLSearchParams(window.location.search).get("entry_id") || "";
const IS_HOME_ASSISTANT = Boolean(HA_ENTRY_ID && window.parent !== window);
const pendingHomeAssistantRequests = new Map();

window.addEventListener("message", (event) => {
  if (!IS_HOME_ASSISTANT || event.origin !== window.location.origin || event.source !== window.parent) return;
  const message = event.data || {};
  if (message.type !== "thessla-green-response") return;
  const pending = pendingHomeAssistantRequests.get(message.requestId);
  if (!pending) return;
  pendingHomeAssistantRequests.delete(message.requestId);
  if (message.ok) {
    pending.resolve(message.body);
    return;
  }
  const error = new Error(`${message.status || 500}: ${message.detail || "Błąd Home Assistanta"}`);
  error.status = message.status || 500;
  error.detail = message.detail || "Błąd Home Assistanta";
  pending.reject(error);
});

const state = {
  snapshot: null,
  options: { modes: {}, special_modes: {} },
  token: IS_HOME_ASSISTANT ? "" : (localStorage.getItem("thessla-green-api-token") || ""),
  busy: false,
  selectedSpecialMode: null,
  confirmedSpecialMode: null,
  previewSpecialMode: null,
  specialSelectionDirty: false,
};

const MODE_DESCRIPTIONS = {
  automatic: "Automatyczny: centrala pracuje według harmonogramu skonfigurowanego w Air++.",
  manual: "Ręczny: wybrana intensywność działa bez limitu czasu, aż zmienisz tryb.",
  temporary: "Chwilowy: wybrana intensywność działa przez czas skonfigurowany w Air++, potem centrala wraca do automatu.",
};

const MODE_LABELS = {
  automatic: "Automatyczny",
  manual: "Ręczny",
  temporary: "Chwilowy",
};

const SPECIAL_MODE_DETAILS = {
  none: {
    label: "Brak",
    icon: "○",
    description: "Wyłącza ręcznie wymuszoną funkcję specjalną. Centrala wraca do pracy wynikającej z bieżącego trybu: automatycznego, ręcznego albo chwilowego.",
  },
  hood: {
    label: "Okap",
    icon: "⌁",
    description: "Aktywuje profil OKAP. Centrala zastosuje balans nawiewu i wywiewu skonfigurowany dla okapu w sterowniku Air++; dokładne intensywności zależą od tych ustawień.",
  },
  fireplace: {
    label: "Kominek",
    icon: "♨",
    description: "Aktywuje profil KOMINEK. Centrala zmienia bilans wentylacji zgodnie z konfiguracją Air++, aby wspierać pracę kominka. Używaj wyłącznie przy właściwie przygotowanej instalacji.",
  },
  airing_manual: {
    label: "Wietrzenie",
    icon: "↔",
    description: "Ręcznie uruchamia funkcję WIETRZENIE. Intensywność i zachowanie funkcji wynikają z ustawień zapisanych w sterowniku Air++.",
  },
  open_windows: {
    label: "Otwarte okna",
    icon: "▱",
    description: "Włącza profil OTWARTE OKNA. Centrala zastosuje zaprogramowane ustawienia wentylacji przeznaczone dla domu wietrzonego przez otwarte okna.",
  },
  empty_house: {
    label: "Pusty dom",
    icon: "⌂",
    description: "Włącza profil PUSTY DOM przeznaczony na czas nieobecności mieszkańców. Poziom wentylacji jest określony w konfiguracji sterownika Air++.",
  },
};

const SPECIAL_MODE_STATE_LABELS = {
  0: "Brak", 1: "Okap", 2: "Kominek", 3: "Wietrzenie — przycisk",
  4: "Wietrzenie — przełącznik", 5: "Wietrzenie — wilgotność",
  6: "Wietrzenie — jakość powietrza", 7: "Wietrzenie ręczne",
  8: "Wietrzenie automatyczne", 9: "Wietrzenie według harmonogramu",
  10: "Otwarte okna", 11: "Pusty dom",
};

const PARAMETER_DEFINITIONS = [
  { key: "firmware", label: "Wersja firmware" },
  { key: "serial_number", label: "Numer seryjny" },
  { key: "outdoor_temperature", label: "Temperatura zewnętrzna", unit: "°C" },
  { key: "supply_temperature", label: "Temperatura nawiewu", unit: "°C" },
  { key: "extract_temperature", label: "Temperatura powietrza usuwanego z domu (TP)", unit: "°C" },
  { key: "fpx_temperature", label: "Temperatura powietrza za nagrzewnicą FPX (TZ2)", unit: "°C" },
  { key: "duct_supply_temperature", label: "Temperatura kanału nawiewnego", unit: "°C" },
  { key: "gwc_temperature", label: "Temperatura GWC", unit: "°C" },
  { key: "ambient_temperature", label: "Temperatura otoczenia centrali / strychu (TO)", unit: "°C" },
  { key: "supply_flowrate", label: "Zadany strumień nawiewu — panel Air++", unit: "m³/h" },
  { key: "extract_flowrate", label: "Zadany strumień wywiewu — panel Air++", unit: "m³/h" },
  { key: "supply_airflow", label: "Chwilowy pomiar CF — nawiew", unit: "m³/h" },
  { key: "extract_airflow", label: "Chwilowy pomiar CF — wywiew", unit: "m³/h" },
  { key: "constant_flow_active", label: "System Constant Flow", values: { true: "Aktywny", false: "Nieaktywny" } },
  { key: "constant_flow_available", label: "Chwilowy pomiar Constant Flow", values: { true: "Dostępny", false: "Niedostępny" } },
  { key: "supply_percentage", label: "Aktualna intensywność nawiewu", unit: "%" },
  { key: "extract_percentage", label: "Aktualna intensywność wywiewu", unit: "%" },
  {
    key: "fpx_system_active",
    label: "System przeciwzamrożeniowy FPX",
    values: { true: "Aktywny", false: "Nieaktywny" },
  },
  { key: "fpx_stage", label: "Stopień systemu FPX", values: { 0: "OFF", 1: "FPX1", 2: "FPX2" } },
  {
    key: "erv_post_heater_active",
    label: "Wbudowana nagrzewnica wtórna ERV",
    values: { true: "Włączona", false: "Wyłączona" },
  },
  {
    key: "erv_post_heater_mode",
    label: "Konfiguracja nagrzewnicy wtórnej ERV",
    values: { 0: "Wyłączona", 1: "Tryb 1", 2: "Tryb 2" },
  },
  { key: "mode", label: "Tryb pracy", values: { 0: "Automatyczny", 1: "Ręczny", 2: "Chwilowy" } },
  { key: "season", label: "Sezon", values: { 0: "Lato", 1: "Zima" } },
  { key: "manual_fan_speed", label: "Nastawa ręczna", unit: "%" },
  { key: "temporary_fan_speed", label: "Nastawa chwilowa", unit: "%" },
  {
    key: "special_mode",
    label: "Tryb specjalny",
    values: {
      0: "Brak", 1: "Okap", 2: "Kominek", 3: "Wietrzenie — przycisk",
      4: "Wietrzenie — przełącznik", 5: "Wietrzenie — wilgotność",
      6: "Wietrzenie — jakość powietrza", 7: "Wietrzenie ręczne",
      8: "Wietrzenie automatyczne", 9: "Wietrzenie według harmonogramu",
      10: "Otwarte okna", 11: "Pusty dom",
    },
  },
  { key: "comfort_mode_panel", label: "Tryb komfortu na panelu", values: { 0: "EKO", 1: "KOMFORT" } },
  { key: "comfort_mode", label: "Aktywny tryb komfortu", values: { 0: "Nieaktywny", 1: "Grzanie", 2: "Chłodzenie" } },
  { key: "bypass_off", label: "Bypass", values: { 0: "Aktywny", 1: "Nieaktywny" } },
  { key: "bypass_mode", label: "Tryb bypassu", values: { 0: "Nieaktywny", 1: "Grzanie", 2: "Chłodzenie" } },
  { key: "bypass_actuator_open", label: "Siłownik klapy bypassu", values: { true: "Otwarty", false: "Zamknięty" } },
  { key: "power", label: "Zasilanie centrali", values: { 0: "Wyłączona", 1: "Włączona" } },
];

const $ = (id) => document.getElementById(id);
const NUMBER_FORMAT = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 1 });

function headers() {
  const result = { Accept: "application/json", "Content-Type": "application/json" };
  if (state.token) result.Authorization = `Bearer ${state.token}`;
  return result;
}

async function request(path, init = {}) {
  if (IS_HOME_ASSISTANT) {
    const requestId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    const body = typeof init.body === "string" ? JSON.parse(init.body) : (init.body || null);
    const response = new Promise((resolve, reject) => {
      pendingHomeAssistantRequests.set(requestId, { resolve, reject });
      window.setTimeout(() => {
        const pending = pendingHomeAssistantRequests.get(requestId);
        if (!pending) return;
        pendingHomeAssistantRequests.delete(requestId);
        reject(new Error("Przekroczono czas odpowiedzi Home Assistanta"));
      }, 15000);
    });
    window.parent.postMessage({
      type: "thessla-green-request",
      requestId,
      entryId: HA_ENTRY_ID,
      path,
      method: init.method || "GET",
      body,
    }, window.location.origin);
    return response;
  }
  const response = await fetch(path, {
    ...init,
    headers: { ...headers(), ...(init.headers || {}) },
  });
  let body = null;
  try { body = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) {
    const detail = body && (body.detail || body.message) ? body.detail || body.message : response.statusText;
    const error = new Error(`${response.status}: ${detail}`);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }
  return body;
}

function formatNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  const normalized = Math.abs(value) < 1e-9 ? 0 : value;
  return NUMBER_FORMAT.format(normalized);
}

function format(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${formatNumber(value)}${suffix}`;
}

function modeName(value) {
  const modes = state.options.modes || {};
  const found = Object.entries(modes).find(([, code]) => Number(code) === Number(value));
  return found ? found[0] : "nieznany";
}

function specialModeName(value) {
  const specialModes = state.options.special_modes || {};
  const found = Object.entries(specialModes).find(([, code]) => Number(code) === Number(value));
  return found ? found[0] : null;
}

function showSpecialModeDescription(name, preview = false) {
  const detail = SPECIAL_MODE_DETAILS[name];
  if (!detail) return;
  document.querySelector(".special-description-kicker").textContent = preview
    ? "PODGLĄD TRYBU"
    : name === state.confirmedSpecialMode
      ? "AKTYWNY TRYB"
      : "WYBRANY TRYB";
  $("special-description-title").textContent = detail.label;
  $("special-description-text").textContent = detail.description;
}

function updateSpecialModeButtons() {
  document.querySelectorAll(".special-mode-button").forEach((button) => {
    const selected = button.dataset.mode === state.selectedSpecialMode;
    const confirmed = button.dataset.mode === state.confirmedSpecialMode;
    button.classList.toggle("selected", selected);
    button.classList.toggle("confirmed", confirmed);
    button.setAttribute("aria-pressed", String(selected));
  });
  $("apply-special").disabled = !state.selectedSpecialMode;
}

function restoreSpecialModeDescription() {
  state.previewSpecialMode = null;
  const name = state.selectedSpecialMode || state.confirmedSpecialMode;
  if (name) showSpecialModeDescription(name);
}

function renderSpecialModeState(value) {
  const confirmedName = specialModeName(value);
  state.confirmedSpecialMode = confirmedName;
  if (!state.specialSelectionDirty) state.selectedSpecialMode = confirmedName;
  updateSpecialModeButtons();
  if (state.previewSpecialMode) return;
  if (state.selectedSpecialMode) {
    showSpecialModeDescription(state.selectedSpecialMode);
    return;
  }
  $("special-description-title").textContent = SPECIAL_MODE_STATE_LABELS[Number(value)] || "Nieznany";
  $("special-description-text").textContent =
    "Ten stan został aktywowany przez sterownik lub wejście zewnętrzne i nie jest dostępny jako ręczny przycisk.";
  document.querySelector(".special-description-kicker").textContent = "AKTYWNY STAN";
}

function activeSettingDescription(mode, values) {
  if (mode === 1) return `Nastawa ręczna: ${format(values.manual_fan_speed, "%")}`;
  if (mode === 2) return `Nastawa chwilowa: ${format(values.temporary_fan_speed, "%")}`;
  return "Sterowanie według harmonogramu Air++";
}

function diagramTemperature(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "— °C";
  return `${formatNumber(Number(value))} °C`;
}

function diagramPerformance(percentage, airflow) {
  const percentageText = format(percentage, "%");
  const airflowText = format(airflow, " m³/h");
  return `${percentageText} · ${airflowText}`;
}

function animationDuration(percentage) {
  const normalized = Math.max(0, Math.min(150, Number(percentage) || 0));
  return `${Math.max(.65, 3.1 - normalized * .02).toFixed(2)}s`;
}

function fanAnimationDuration(percentage) {
  const normalized = Math.max(0, Math.min(150, Number(percentage) || 0));
  return `${Math.max(.9, 3.4 - normalized * .018).toFixed(2)}s`;
}

function renderHeaterTelemetry(values) {
  const fpxStage = values.fpx_stage == null ? null : Number(values.fpx_stage);
  const fpxSystemActive = values.fpx_system_active;
  const fpxState = fpxStage == null
    ? "unknown"
    : fpxStage > 0
      ? "active"
      : "inactive";
  $("diagram-fpx-heater").dataset.state = fpxState;
  $("diagram-fpx-heater-status").textContent = fpxStage == null
    ? "BRAK ODCZYTU"
    : fpxStage > 0
      ? `SYSTEM FPX${fpxStage}`
      : "SYSTEM OFF";
  $("diagram-fpx-heater-temperatures").textContent =
    `TZ1 ${diagramTemperature(values.outdoor_temperature)} → ` +
    `TZ2 ${diagramTemperature(values.fpx_temperature)}`;
  $("diagram-fpx-heater-detail").textContent = fpxSystemActive == null
    ? "Stan i moc grzałki: niedostępne w Modbus"
    : `System ${fpxSystemActive ? "aktywny" : "nieaktywny"} · moc grzałki: brak rejestru`;

  const ervActive = values.erv_post_heater_active;
  const ervState = ervActive == null ? "unknown" : ervActive ? "active" : "inactive";
  const ervMode = values.erv_post_heater_mode == null
    ? "tryb —"
    : Number(values.erv_post_heater_mode) === 0
      ? "konfiguracja wyłączona"
      : `tryb ERV ${formatNumber(Number(values.erv_post_heater_mode))}`;
  $("diagram-erv-heater").dataset.state = ervState;
  $("diagram-erv-heater-status").textContent = ervActive == null
    ? "BRAK ODCZYTU"
    : ervActive
      ? "WŁĄCZONA"
      : "WYŁĄCZONA";
  $("diagram-erv-heater-temperature").textContent =
    `Nawiew TN1 ${diagramTemperature(values.supply_temperature)}`;
  $("diagram-erv-heater-detail").textContent = `${ervMode} · moc: brak rejestru Modbus`;

  return {
    fpx: fpxStage == null ? "brak odczytu" : fpxStage > 0 ? `system FPX${fpxStage}` : "system OFF",
    erv: ervActive == null ? "brak odczytu" : ervActive ? "włączona" : "wyłączona",
  };
}

function renderAirflowDiagram(snapshot) {
  const values = snapshot?.values || {};
  const panel = $("airflow-visualization");
  const mode = modeName(Number(values.mode));
  const season = Number(values.season) === 0 ? "Lato" : Number(values.season) === 1 ? "Zima" : "—";
  const bypassModeValue = Number(values.bypass_mode);
  const bypassMode = { 0: "nieaktywny", 1: "freeheating", 2: "freecooling" }[bypassModeValue];
  const bypassEnabled = Number(values.bypass_off) === 0;
  const bypassRequested = bypassEnabled && [1, 2].includes(bypassModeValue);
  const bypassActive = values.bypass_actuator_open === true
    || (values.bypass_actuator_open == null && bypassRequested);
  const bypassPending = bypassRequested && values.bypass_actuator_open === false;
  const powered = Number(values.power) === 1;
  const supplyPercentage = Number(values.supply_percentage) || 0;
  const extractPercentage = Number(values.extract_percentage) || 0;

  $("diagram-mode").textContent = `Tryb: ${MODE_LABELS[mode] || "—"}`;
  $("diagram-season").textContent = `Sezon: ${season}`;
  const bypassPill = $("diagram-bypass");
  const bypassState = bypassActive
    ? "active"
    : bypassPending
      ? "pending"
      : bypassEnabled
        ? "ready"
        : "disabled";
  bypassPill.textContent = bypassActive
    ? `BP aktywny: ${bypassMode}`
    : bypassPending
      ? `BP żądany: ${bypassMode}, klapa zamknięta`
    : bypassEnabled
      ? "BP gotowy: klapa zamknięta"
      : "BP wyłączony";
  bypassPill.classList.toggle("bypass-active", bypassActive);
  bypassPill.classList.toggle("bypass-disabled", !bypassEnabled);
  $("diagram-bp-state").dataset.state = bypassState;
  $("diagram-bp-state-label").textContent = bypassActive
    ? "BP WŁĄCZONY"
    : bypassPending
      ? "BP OCZEKUJE"
    : bypassEnabled
      ? "BP NIEAKTYWNY"
      : "BP WYŁĄCZONY";
  $("diagram-bp-state-detail").textContent = bypassActive
    ? bypassMode.toUpperCase()
    : bypassPending
      ? `${bypassMode.toUpperCase()} · KLAPA ZAMKNIĘTA`
    : bypassEnabled
      ? "KLAPA ZAMKNIĘTA"
      : "FUNKCJA ZABLOKOWANA";
  $("diagram-unit-caption").textContent = bypassActive
    ? "BYPASS · WYMIENNIK OMIJANY"
    : "ODZYSK CIEPŁA";
  $("diagram-outdoor-temperature").textContent = diagramTemperature(values.outdoor_temperature);
  $("diagram-fpx-temperature").textContent = `FPX ${diagramTemperature(values.fpx_temperature)}`;
  $("diagram-supply-temperature").textContent = diagramTemperature(values.supply_temperature);
  $("diagram-extract-temperature").textContent = diagramTemperature(values.extract_temperature);
  $("diagram-ambient-temperature").textContent = diagramTemperature(values.ambient_temperature);
  $("diagram-supply-performance").textContent = diagramPerformance(
    values.supply_percentage,
    values.supply_flowrate,
  );
  $("diagram-extract-performance").textContent = diagramPerformance(
    values.extract_percentage,
    values.extract_flowrate,
  );
  const heaterStatus = renderHeaterTelemetry(values);

  const supplyDuration = animationDuration(supplyPercentage);
  const extractDuration = animationDuration(extractPercentage);
  $("flow-outdoor").style.setProperty("--flow-speed", supplyDuration);
  $("flow-supply").style.setProperty("--flow-speed", supplyDuration);
  $("flow-bypass-outdoor").style.setProperty("--flow-speed", supplyDuration);
  $("flow-bypass-supply").style.setProperty("--flow-speed", supplyDuration);
  $("flow-extract").style.setProperty("--flow-speed", extractDuration);
  $("flow-exhaust").style.setProperty("--flow-speed", extractDuration);
  document.querySelector(".fan-supply").style.setProperty(
    "--fan-speed",
    fanAnimationDuration(supplyPercentage),
  );
  document.querySelector(".fan-extract").style.setProperty(
    "--fan-speed",
    fanAnimationDuration(extractPercentage),
  );

  panel.classList.toggle("is-offline", snapshot?.online !== true);
  panel.classList.toggle("is-powered-off", !powered);
  panel.classList.toggle("no-supply-flow", supplyPercentage <= 0);
  panel.classList.toggle("no-extract-flow", extractPercentage <= 0);
  panel.classList.toggle("is-bypass-enabled", bypassEnabled);
  panel.classList.toggle("is-bypass-active", bypassActive);
  panel.classList.toggle("is-bypass-pending", bypassPending);
  $("airflow-svg-description").textContent =
    `Nawiew ${diagramPerformance(values.supply_percentage, values.supply_flowrate)}, ` +
    `wywiew ${diagramPerformance(values.extract_percentage, values.extract_flowrate)}. ` +
    `Temperatura zewnętrzna ${diagramTemperature(values.outdoor_temperature)}, ` +
    `nawiewu ${diagramTemperature(values.supply_temperature)} i powietrza usuwanego z domu ` +
    `${diagramTemperature(values.extract_temperature)}. ` +
    `${bypassActive ? "Bypass aktywny, nawiew omija wymiennik." : bypassPending ? "Bypass żądany, ale klapa nie jest jeszcze otwarta." : "Nawiew przechodzi przez wymiennik."} ` +
    `Nagrzewnica wstępna: ${heaterStatus.fpx}; nagrzewnica wtórna ERV: ${heaterStatus.erv}. ` +
    `Wyrzutnia nie ma czujnika temperatury. Temperatura otoczenia centrali ` +
    `${diagramTemperature(values.ambient_temperature)}.`;
}

function parameterDefinitions(values) {
  const known = new Set(PARAMETER_DEFINITIONS.map((definition) => definition.key));
  const additional = Object.keys(values)
    .filter((key) => !known.has(key))
    .sort((left, right) => left.localeCompare(right, "pl"))
    .map((key) => ({ key, label: key.replaceAll("_", " ") }));
  return [...PARAMETER_DEFINITIONS, ...additional];
}

function formattedParameterValue(definition, value) {
  if (value === null || value === undefined) return { text: "Brak pomiaru", available: false };
  const mapped = definition.values?.[String(value)];
  if (mapped !== undefined) return { text: `${mapped} (${formatNumber(value)})`, available: true };
  if (typeof value === "boolean") return { text: value ? "Tak" : "Nie", available: true };
  if (typeof value === "object") return { text: JSON.stringify(value), available: true };
  return { text: formatNumber(value), available: true };
}

function renderParameters(snapshot) {
  const values = snapshot?.values || {};
  const query = ($("parameter-filter")?.value || "").trim().toLocaleLowerCase("pl");
  const definitions = parameterDefinitions(values).filter((definition) =>
    `${definition.label} ${definition.key}`.toLocaleLowerCase("pl").includes(query)
  );
  const body = $("parameter-table-body");
  body.replaceChildren();

  definitions.forEach((definition) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    const valueCell = document.createElement("td");
    const unit = document.createElement("td");
    const key = document.createElement("td");
    const formatted = formattedParameterValue(definition, values[definition.key]);

    name.className = "parameter-name";
    name.textContent = definition.label;
    valueCell.className = formatted.available ? "parameter-value" : "value-unavailable";
    valueCell.textContent = formatted.text;
    unit.className = "parameter-unit";
    unit.textContent = definition.unit || "—";
    key.className = "parameter-key";
    key.textContent = definition.key;
    row.append(name, valueCell, unit, key);
    body.append(row);
  });

  if (definitions.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "empty-table";
    cell.textContent = "Brak parametrów pasujących do filtra.";
    row.append(cell);
    body.append(row);
  }

  const available = Object.values(values).filter((value) => value !== null && value !== undefined).length;
  $("parameters-summary").textContent = `${available} z ${Object.keys(values).length} parametrów ma aktualną wartość`;
  const capturedAt = snapshot?.captured_at ? new Date(snapshot.captured_at) : null;
  $("parameters-updated").textContent = capturedAt && !Number.isNaN(capturedAt.getTime())
    ? `odczyt ${capturedAt.toLocaleTimeString("pl-PL")}`
    : "czas odczytu —";
}

function selectTab(name, moveFocus = false) {
  const selected = name === "parameters" ? "parameters" : "control";
  document.querySelectorAll('[role="tab"][data-tab]').forEach((tab) => {
    const active = tab.dataset.tab === selected;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && moveFocus) tab.focus();
  });
  $("panel-control").hidden = selected !== "control";
  $("panel-parameters").hidden = selected !== "parameters";
  const hash = selected === "parameters" ? "#parametry" : "#sterowanie";
  window.history.replaceState(null, "", hash);
}

function updateModeControls(mode) {
  const normalized = MODE_DESCRIPTIONS[mode] ? mode : "automatic";
  const temporary = normalized === "temporary";
  const automatic = normalized === "automatic";
  $("mode-description").textContent = MODE_DESCRIPTIONS[normalized];
  $("speed-label").textContent = temporary ? "Nastawa tymczasowa" : "Nastawa manualna";
  $("apply-speed").textContent = temporary
    ? "Ustaw nastawę tymczasową"
    : automatic
      ? "Ustaw i przełącz na manualny"
      : "Ustaw nastawę manualną";
  $("speed-help").textContent = temporary
    ? "Zastosowanie nastawy atomowo uruchamia tryb chwilowy; publiczny Modbus nie udostępnia ustawienia jego czasu."
    : automatic
      ? "Zapisanie wartości najpierw przełączy centralę na tryb manualny."
      : "Suwak zapisuje nastawę manualną dla trybu manualnego.";
}

function setConnection(online, message) {
  const element = $("connection");
  element.className = `status ${online ? "status-online" : "status-offline"}`;
  element.textContent = message || (online ? "Połączono" : "Offline");
}

function showDiscovery(visible, message) {
  const panel = $("discovery-panel");
  panel.hidden = !visible;
  if (message) $("discovery-message").textContent = message;
}

function renderDiscoveryResults(results) {
  const container = $("discovery-results");
  container.replaceChildren();
  if (!Array.isArray(results) || results.length === 0) {
    $("discovery-message").textContent = "Nie znaleziono kandydatów. Sprawdź port, grupę dialout/uucp i konfigurację sieci.";
    return;
  }
  results.forEach((result) => {
    const endpoint = result.endpoint || {};
    const identity = result.identity || {};
    const selectable = result.is_selectable === true;
    const card = document.createElement("article");
    card.className = `discovery-result ${selectable ? "discovery-result-selectable" : "discovery-result-error"}`;
    const title = document.createElement("strong");
    title.textContent = `${endpoint.key || endpoint.address || "nieznany endpoint"} · unit ${result.unit_id ?? "—"}`;
    const badge = document.createElement("span");
    badge.className = "discovery-badge";
    badge.textContent = selectable ? "AirPack potwierdzony" : (result.status || "błąd");
    const detail = document.createElement("small");
    detail.textContent = selectable
      ? `${identity.model || "AirPack"} · firmware ${identity.firmware || "—"} · serial ${identity.serial_number || "—"}`
      : (result.error || "Brak potwierdzonego fingerprintu");
    card.append(title, badge, detail);
    if (selectable && endpoint.kind === "serial") {
      const config = document.createElement("code");
      config.textContent = `THESSLA_SERIAL_PORT=${endpoint.address}`;
      card.append(config);
    }
    container.append(card);
  });
  $("discovery-message").textContent = "Wybierz potwierdzony endpoint i zapisz go jawnie w .env. Panel nie przejmuje magistrali automatycznie.";
}

async function loadDiscoveryPorts() {
  const body = await request("/api/v1/discovery/serial-ports");
  const ports = Array.isArray(body?.ports) ? body.ports : [];
  if (ports.length > 0) {
    const details = ports.map((port) => port.device || "").filter(Boolean).join(", ");
    $("discovery-message").textContent = `Znalezione porty lokalne: ${details}. Uruchom skanowanie read-only.`;
  }
}

async function runDiscovery() {
  const button = $("run-discovery");
  button.disabled = true;
  try {
    const body = await request("/api/v1/discovery", { method: "POST" });
    renderDiscoveryResults(body?.results || []);
  } catch (error) {
    toast(error.message);
    if (error.status === 409) {
      $("discovery-message").textContent = "Zatrzymaj aktywny gateway przed skanowaniem jego magistrali.";
    }
  } finally {
    button.disabled = false;
  }
}

function render(snapshot) {
  if (!snapshot) return;
  showDiscovery(false);
  state.snapshot = snapshot;
  const values = snapshot.values || {};
  const mode = Number(values.mode);
  $("identity").textContent = snapshot.identity
    ? `${snapshot.identity.model} · firmware ${snapshot.identity.firmware || "—"} · unit ${snapshot.identity.unit_id}`
    : "Brak potwierdzonej tożsamości";
  setConnection(Boolean(snapshot.online), snapshot.online ? "Połączono" : "Urządzenie offline");
  const activeMode = modeName(mode);
  $("active-speed").textContent = MODE_LABELS[activeMode] || "Nieznany";
  $("active-mode").textContent = activeSettingDescription(mode, values);
  $("supply-airflow").textContent = values.supply_flowrate == null
    ? "Brak pomiaru"
    : format(values.supply_flowrate, " m³/h");
  $("extract-airflow").textContent = values.extract_flowrate == null
    ? "Brak pomiaru"
    : format(values.extract_flowrate, " m³/h");
  const constantFlowAvailable = values.constant_flow_available === true;
  const supplyCf = constantFlowAvailable ? ` · CF ${format(values.supply_airflow, " m³/h")}` : "";
  const extractCf = constantFlowAvailable ? ` · CF ${format(values.extract_airflow, " m³/h")}` : "";
  $("supply-airflow-note").textContent = `${format(values.supply_percentage, "%")} zadane${supplyCf}`;
  $("extract-airflow-note").textContent = `${format(values.extract_percentage, "%")} zadane${extractCf}`;
  $("outdoor-temperature").textContent = format(values.outdoor_temperature);
  $("revision").textContent = `revision ${snapshot.revision ?? "—"}`;
  const selectedMode = modeName(mode);
  $("mode").value = selectedMode;
  updateModeControls(selectedMode);
  const selectedSpeed = mode === 2 ? values.temporary_fan_speed : values.manual_fan_speed;
  if (selectedSpeed !== null && selectedSpeed !== undefined) {
    $("speed").value = selectedSpeed;
    $("speed-value").textContent = format(selectedSpeed, "%");
  }
  renderSpecialModeState(values.special_mode);
  $("power").textContent = values.power ? "Wyłącz centralę" : "Włącz centralę";
  $("raw-state").textContent = JSON.stringify(snapshot, null, 2);
  renderAirflowDiagram(snapshot);
  renderParameters(snapshot);
}

function renderOptions(options) {
  state.options = options || state.options;
  const container = $("special-mode-buttons");
  const names = Object.keys(state.options.special_modes || {});
  const signature = names.join("|");
  if (container.dataset.signature === signature) {
    updateSpecialModeButtons();
    return;
  }
  container.dataset.signature = signature;
  container.replaceChildren();
  names.forEach((name) => {
    const detail = SPECIAL_MODE_DETAILS[name] || {
      label: name.replaceAll("_", " "),
      icon: "•",
      description: "Tryb udostępniony przez gateway.",
    };
    const button = document.createElement("button");
    const icon = document.createElement("span");
    const label = document.createElement("span");
    button.type = "button";
    button.className = "special-mode-button";
    button.dataset.mode = name;
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-label", detail.label);
    icon.className = "special-mode-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = detail.icon;
    label.className = "special-mode-label";
    label.textContent = detail.label;
    button.append(icon, label);

    const preview = () => {
      state.previewSpecialMode = name;
      showSpecialModeDescription(name, true);
    };
    const stopPreview = () => {
      if (state.previewSpecialMode === name) restoreSpecialModeDescription();
    };
    button.addEventListener("mouseenter", preview);
    button.addEventListener("mouseleave", stopPreview);
    button.addEventListener("focus", preview);
    button.addEventListener("blur", stopPreview);
    button.addEventListener("pointerdown", preview);
    button.addEventListener("pointerup", stopPreview);
    button.addEventListener("pointercancel", stopPreview);
    button.addEventListener("click", () => {
      state.previewSpecialMode = null;
      state.selectedSpecialMode = name;
      state.specialSelectionDirty = true;
      updateSpecialModeButtons();
      showSpecialModeDescription(name);
    });
    container.append(button);
  });
  if (!state.selectedSpecialMode && names.includes("none")) state.selectedSpecialMode = "none";
  updateSpecialModeButtons();
}

function renderConfirmation(result, replayed = false) {
  if (!result) return;
  const confirmed = result.confirmed === true;
  $("confirmed-icon").classList.toggle("error", !confirmed);
  $("confirmed-icon").textContent = confirmed ? "✓" : "!";
  let message = confirmed
    ? `${replayed ? "Powtórzono bez kolejnego zapisu" : "Zapis wykonany i odczytany ponownie"}.`
    : "Read-back nie potwierdził wartości.";
  const airflow = result.airflow_observation || {};
  if (confirmed && airflow.available === true) {
    const supply = format(airflow.after_supply_airflow_m3h, " m³/h");
    const extract = format(airflow.after_extract_airflow_m3h, " m³/h");
    message += ` Próbka przepływu: nawiew ${supply}, wywiew ${extract}.`;
    if (airflow.supply_changed === true || airflow.extract_changed === true) {
      message += " Przepływ zmienił się po komendzie.";
    } else {
      message += " Ta próbka nie wykazała jeszcze zmiany przepływu.";
    }
  }
  $("confirmation-message").textContent = message;
  $("last-command").textContent = result.command || "—";
  $("requested-value").textContent = format(result.requested_value);
  $("confirmed-value").textContent = format(result.confirmed_value);
  $("audit-sequence").textContent = format(result.audit_sequence);
}

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 6000);
}

async function sendCommand(type, parameters) {
  if (!state.snapshot) throw new Error("Brak aktualnego snapshotu");
  const body = await request("/api/v1/commands", {
    method: "POST",
    body: JSON.stringify({
      type,
      parameters,
      request_id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
      expected_revision: state.snapshot.revision,
    }),
  });
  render(body.state);
  renderConfirmation(body.result, body.replayed);
  return body;
}

async function refresh() {
  try {
    const [snapshot, options] = await Promise.all([
      request("/api/v1/state"),
      request("/api/v1/control/options"),
    ]);
    renderOptions(options);
    render(snapshot);
  } catch (error) {
    setConnection(false, error.status === 503 ? "Gateway nie skonfigurowany" : "Błąd połączenia");
    if (error.status === 503) {
      showDiscovery(true);
      try { await loadDiscoveryPorts(); } catch (_) { /* panel remains useful offline */ }
    } else {
      toast(error.message);
    }
  }
}

async function refreshAfterConflict() {
  try {
    const snapshot = await request("/api/v1/state");
    render(snapshot);
    return true;
  } catch (_) {
    return false;
  }
}

async function refreshSnapshotForCommand() {
  // Keep optimistic concurrency protection, but do not base a click on a
  // revision that became stale during the five-second telemetry poll. The
  // form values are intentionally left untouched until the command returns.
  const snapshot = await request("/api/v1/state");
  state.snapshot = snapshot;
}

async function runAction(action) {
  if (state.busy) return;
  state.busy = true;
  action.disabled = true;
  try {
    if (action.refreshBeforeCommand === true) await refreshSnapshotForCommand();
    await action.handler();
  } catch (error) {
    if (typeof action.onError === "function") action.onError(error);
    if (error.status === 409 && action.refreshOnConflict === true) {
      const refreshed = await refreshAfterConflict();
      const detail = typeof error.detail === "string" ? error.detail : error.message;
      const revisionConflict = detail.startsWith("expected state revision");
      toast(refreshed
        ? revisionConflict
          ? "Stan centrali zmienił się równolegle. Odświeżono potwierdzone wartości — ponów polecenie."
          : `Gateway odrzucił polecenie: ${detail}`
        : error.message);
    } else {
      toast(error.message);
    }
  } finally {
    state.busy = false;
    action.disabled = false;
  }
}

function bind() {
  const tabs = [...document.querySelectorAll('[role="tab"][data-tab]')];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab.dataset.tab));
    tab.addEventListener("keydown", (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(index + offset + tabs.length) % tabs.length];
      selectTab(next.dataset.tab, true);
    });
  });
  $("parameter-filter").addEventListener("input", () => {
    if (state.snapshot) renderParameters(state.snapshot);
  });
  $("run-discovery").addEventListener("click", () => runAction({
    disabled: $("run-discovery"),
    handler: runDiscovery,
  }));
  $("speed").addEventListener("input", (event) => {
    $("speed-value").textContent = `${event.target.value}%`;
  });
  const tokenField = document.querySelector(".token-field");
  if (IS_HOME_ASSISTANT) {
    tokenField.hidden = true;
  } else {
    $("save-token").addEventListener("click", () => {
      state.token = $("api-token").value.trim();
      localStorage.setItem("thessla-green-api-token", state.token);
      toast("Token zapisany lokalnie w tej przeglądarce.");
      refresh();
    });
    $("api-token").value = state.token;
  }
  $("mode").addEventListener("change", (event) => runAction({
    disabled: event.target,
    refreshBeforeCommand: true,
    refreshOnConflict: true,
    handler: () => event.target.value === "temporary"
      ? sendCommand("activate_temporary_mode", { percentage: Number($("speed").value) })
      : sendCommand("set_mode", { mode: event.target.value }),
    onError: () => {
      if (!state.snapshot) return;
      const confirmedMode = modeName(state.snapshot.values?.mode);
      $("mode").value = confirmedMode;
      updateModeControls(confirmedMode);
    },
  }));
  $("apply-speed").addEventListener("click", () => runAction({
    disabled: $("apply-speed"),
    refreshBeforeCommand: true,
    refreshOnConflict: true,
    handler: async () => {
      const percentage = Number($("speed").value);
      const mode = Number(state.snapshot?.values?.mode);
      if (mode === 2) {
        await sendCommand("activate_temporary_mode", { percentage });
      } else {
        if (mode !== 1) await sendCommand("set_mode", { mode: "manual" });
        await sendCommand("set_fan_speed", { percentage });
      }
    },
  }));
  $("apply-special").addEventListener("click", () => runAction({
    disabled: $("apply-special"),
    refreshBeforeCommand: true,
    refreshOnConflict: true,
    handler: async () => {
      const mode = state.selectedSpecialMode;
      if (!mode) throw new Error("Wybierz tryb specjalny");
      state.specialSelectionDirty = false;
      await sendCommand("set_special_mode", { mode });
    },
    onError: () => {
      state.specialSelectionDirty = false;
      if (state.snapshot) renderSpecialModeState(state.snapshot.values?.special_mode);
    },
  }));
  $("power").addEventListener("click", () => runAction({
    disabled: $("power"),
    refreshBeforeCommand: true,
    refreshOnConflict: true,
    handler: () => sendCommand("set_power", { enabled: !Boolean(state.snapshot?.values?.power) }),
  }));
}

bind();
selectTab(window.location.hash === "#parametry" ? "parameters" : "control");
refresh();
window.setInterval(refresh, 5000);
