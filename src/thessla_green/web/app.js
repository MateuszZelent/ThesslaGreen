const state = {
  snapshot: null,
  options: { modes: {}, special_modes: {} },
  token: localStorage.getItem("thessla-green-api-token") || "",
  busy: false,
};

const MODE_DESCRIPTIONS = {
  automatic: "Automatyczny: centrala pracuje według harmonogramu skonfigurowanego w Air++.",
  manual: "Ręczny: wybrana intensywność działa bez limitu czasu, aż zmienisz tryb.",
  temporary: "Chwilowy: wybrana intensywność działa przez czas skonfigurowany w Air++, potem centrala wraca do automatu.",
};

const $ = (id) => document.getElementById(id);

function headers() {
  const result = { Accept: "application/json", "Content-Type": "application/json" };
  if (state.token) result.Authorization = `Bearer ${state.token}`;
  return result;
}

async function request(path, init = {}) {
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

function format(value, suffix = "") {
  return value === null || value === undefined ? "—" : `${value}${suffix}`;
}

function modeName(value) {
  const modes = state.options.modes || {};
  const found = Object.entries(modes).find(([, code]) => Number(code) === Number(value));
  return found ? found[0] : "nieznany";
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
  const active = mode === 2 ? values.temporary_fan_speed : values.manual_fan_speed;
  $("identity").textContent = snapshot.identity
    ? `${snapshot.identity.model} · firmware ${snapshot.identity.firmware || "—"} · unit ${snapshot.identity.unit_id}`
    : "Brak potwierdzonej tożsamości";
  setConnection(Boolean(snapshot.online), snapshot.online ? "Połączono" : "Urządzenie offline");
  $("active-speed").textContent = format(active, "%");
  $("active-mode").textContent = `tryb ${modeName(mode)}`;
  $("supply-airflow").textContent = format(values.supply_airflow);
  $("extract-airflow").textContent = format(values.extract_airflow);
  $("outdoor-temperature").textContent = format(values.outdoor_temperature, " °C");
  $("revision").textContent = `revision ${snapshot.revision ?? "—"}`;
  const selectedMode = modeName(mode);
  $("mode").value = selectedMode;
  updateModeControls(selectedMode);
  const selectedSpeed = mode === 2 ? values.temporary_fan_speed : values.manual_fan_speed;
  if (selectedSpeed !== null && selectedSpeed !== undefined) {
    $("speed").value = selectedSpeed;
    $("speed-value").textContent = `${selectedSpeed}%`;
  }
  $("power").textContent = values.power ? "Wyłącz centralę" : "Włącz centralę";
  $("raw-state").textContent = JSON.stringify(snapshot, null, 2);
}

function renderOptions(options) {
  state.options = options || state.options;
  const special = $("special-mode");
  special.replaceChildren();
  Object.keys(state.options.special_modes || {}).forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name.replaceAll("_", " ");
    special.append(option);
  });
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
  $("run-discovery").addEventListener("click", () => runAction({
    disabled: $("run-discovery"),
    handler: runDiscovery,
  }));
  $("speed").addEventListener("input", (event) => {
    $("speed-value").textContent = `${event.target.value}%`;
  });
  $("save-token").addEventListener("click", () => {
    state.token = $("api-token").value.trim();
    localStorage.setItem("thessla-green-api-token", state.token);
    toast("Token zapisany lokalnie w tej przeglądarce.");
    refresh();
  });
  $("api-token").value = state.token;
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
    handler: () => sendCommand("set_special_mode", { mode: $("special-mode").value }),
  }));
  $("power").addEventListener("click", () => runAction({
    disabled: $("power"),
    refreshBeforeCommand: true,
    refreshOnConflict: true,
    handler: () => sendCommand("set_power", { enabled: !Boolean(state.snapshot?.values?.power) }),
  }));
}

bind();
refresh();
window.setInterval(refresh, 5000);
