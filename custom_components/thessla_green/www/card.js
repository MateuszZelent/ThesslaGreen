/* global customElements */

const CARD_TAG = "thessla-green-card";
const EDITOR_TAG = "thessla-green-card-editor";
const REQUEST_TYPE = "thessla-green-request";
const RESPONSE_TYPE = "thessla-green-response";
const DEFAULT_HEIGHT = 1200;

const API_SUFFIXES = {
  "/api/v1/state": "state",
  "/api/v1/control/options": "control/options",
  "/api/v1/discovery/serial-ports": "discovery/serial-ports",
  "/api/v1/commands": "commands",
};

class ThesslaGreenCard extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._entry = null;
    this._frame = null;
    this._loadingConfig = false;
    this._shadow = this.attachShadow({ mode: "open" });
    this._handleMessage = this._handleMessage.bind(this);
  }

  static getStubConfig() {
    return { height: DEFAULT_HEIGHT };
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._entry = null;
    this._render();
    this._ensureEntry();
  }

  set hass(value) {
    this._hass = value;
    this._ensureEntry();
  }

  connectedCallback() {
    window.addEventListener("message", this._handleMessage);
    this._render();
    this._ensureEntry();
  }

  disconnectedCallback() {
    window.removeEventListener("message", this._handleMessage);
  }

  getCardSize() {
    return Math.ceil(this._height() / 50);
  }

  _height() {
    const configured = Number(this._config.height);
    return Number.isFinite(configured)
      ? Math.min(1600, Math.max(620, Math.round(configured)))
      : DEFAULT_HEIGHT;
  }

  async _ensureEntry() {
    if (!this.isConnected || !this._hass?.callApi || this._entry || this._loadingConfig) return;
    this._loadingConfig = true;
    try {
      const response = await this._hass.callApi("GET", "thessla_green/config");
      const entries = Array.isArray(response?.entries) ? response.entries : [];
      const requested = String(this._config.entry_id || "");
      this._entry = entries.find((entry) => entry.entry_id === requested) || entries[0] || null;
    } catch (error) {
      this._entry = { error: String(error?.message || "Nie można pobrać konfiguracji") };
    } finally {
      this._loadingConfig = false;
      this._render();
    }
  }

  _uiUrl() {
    if (!this._entry || this._entry.error) return "";
    if (this._entry.connection_type === "direct") {
      const entryId = encodeURIComponent(String(this._entry.entry_id || ""));
      return entryId
        ? `/api/thessla_green/frontend/direct/index.html?entry_id=${entryId}&view=card`
        : "";
    }
    const configured = String(this._entry.gateway_url || "").trim();
    if (!configured) return "";
    try {
      const url = new URL(configured, window.location.origin);
      url.pathname = `${url.pathname.replace(/\/+$/, "")}/ui/`;
      url.search = "view=card";
      url.hash = "";
      return url.toString();
    } catch (_error) {
      return "";
    }
  }

  async _handleMessage(event) {
    if (
      event.origin !== window.location.origin
      || event.source !== this._frame?.contentWindow
      || this._entry?.connection_type !== "direct"
    ) return;
    const message = event.data || {};
    if (message.type !== REQUEST_TYPE || message.entryId !== this._entry.entry_id) return;
    const suffix = API_SUFFIXES[message.path];
    if (!suffix || !this._hass?.callApi) return;
    try {
      const body = await this._hass.callApi(
        String(message.method || "GET").toUpperCase(),
        `thessla_green/${encodeURIComponent(this._entry.entry_id)}/${suffix}`,
        message.body || undefined,
      );
      event.source.postMessage({
        type: RESPONSE_TYPE,
        requestId: message.requestId,
        ok: true,
        body,
      }, event.origin);
    } catch (error) {
      event.source.postMessage({
        type: RESPONSE_TYPE,
        requestId: message.requestId,
        ok: false,
        status: Number(error?.status_code || error?.status || 500),
        detail: String(error?.body?.message || error?.message || "Błąd Home Assistanta"),
      }, event.origin);
    }
  }

  _render() {
    const url = this._uiUrl();
    const height = this._height();
    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; }
      ha-card {
        overflow: hidden;
        min-height: ${height}px;
        border: 1px solid rgba(92, 153, 221, .28);
        background: #07111f;
      }
      iframe {
        display: block;
        width: 100%;
        height: ${height}px;
        border: 0;
        background: #07111f;
      }
      .message {
        display: grid;
        min-height: 240px;
        place-items: center;
        padding: 28px;
        box-sizing: border-box;
        color: var(--secondary-text-color);
        text-align: center;
      }
      .message strong { display: block; margin-bottom: 8px; color: var(--primary-text-color); }
    `;
    const card = document.createElement("ha-card");
    if (url) {
      const frame = document.createElement("iframe");
      frame.src = url;
      frame.title = "Thessla Green — przepływ i sterowanie";
      frame.loading = "eager";
      frame.referrerPolicy = "no-referrer";
      this._frame = frame;
      card.appendChild(frame);
    } else {
      this._frame = null;
      const message = document.createElement("div");
      message.className = "message";
      const error = this._entry?.error;
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = "Thessla Green";
      content.append(title, document.createTextNode(
        error || "Ładowanie skonfigurowanej centrali…",
      ));
      message.appendChild(content);
      card.appendChild(message);
    }
    this._shadow.replaceChildren(style, card);
  }
}

class ThesslaGreenCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(value) {
    this._hass = value;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    this.innerHTML = `
      <div style="display:grid;gap:16px;padding:8px 0">
        <label>
          Wysokość karty (620–1600 px)
          <input type="number" min="620" max="1600" step="10"
            value="${Number(this._config?.height) || DEFAULT_HEIGHT}"
            style="display:block;width:100%;margin-top:6px;padding:10px;box-sizing:border-box">
        </label>
        <small>Przy jednej centrali karta wybierze ją automatycznie.</small>
      </div>`;
    this.querySelector("input")?.addEventListener("change", (event) => {
      const height = Math.min(1600, Math.max(620, Number(event.target.value) || DEFAULT_HEIGHT));
      this.dispatchEvent(new CustomEvent("config-changed", {
        detail: { config: { ...(this._config || {}), height } },
        bubbles: true,
        composed: true,
      }));
    });
  }
}

if (!customElements.get(EDITOR_TAG)) customElements.define(EDITOR_TAG, ThesslaGreenCardEditor);
if (!customElements.get(CARD_TAG)) customElements.define(CARD_TAG, ThesslaGreenCard);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: "Thessla Green AirPack",
    description: "Animowany przepływ powietrza i pełne sterowanie rekuperatorem.",
    preview: true,
    documentationURL: "https://github.com/MateuszZelent/ThesslaGreen",
  });
}
