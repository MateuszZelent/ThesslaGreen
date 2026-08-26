/* global customElements */

/**
 * Sidebar panel for the Home Assistant adapter.
 *
 * The gateway remains the single Modbus owner.  This panel deliberately embeds
 * the same local-first UI served by the gateway, so its animation and controls
 * stay identical to the standalone dashboard and do not duplicate API logic.
 */
(function registerThesslaGreenPanel() {
  const TAG_NAME = "thessla-green-panel";

  if (customElements.get(TAG_NAME)) {
    return;
  }

  class ThesslaGreenPanel extends HTMLElement {
    constructor() {
      super();
      this._panel = null;
      this._frameUrl = null;
      this._shadow = this.attachShadow({ mode: "open" });
    }

    /** Home Assistant's custom-panel loader uses this method when available. */
    setProperties(properties) {
      this._panel = properties?.panel || this._panel;
      this._render();
    }

    set panel(value) {
      this._panel = value;
      this._render();
    }

    connectedCallback() {
      this._render();
    }

    _config() {
      return this._panel?.config?._panel_custom?.config || {};
    }

    _gatewayUiUrl() {
      const configured = String(this._config().gateway_url || "").trim();
      if (!configured) {
        return "";
      }
      try {
        const url = new URL(configured, window.location.origin);
        url.pathname = `${url.pathname.replace(/\/+$/, "")}/ui/`;
        url.search = "";
        url.hash = "";
        return url.toString();
      } catch (_error) {
        return "";
      }
    }

    _render() {
      const url = this._gatewayUiUrl();
      if (url === this._frameUrl && this._shadow.childElementCount) {
        return;
      }
      this._frameUrl = url;

      const style = document.createElement("style");
      style.textContent = `
        :host {
          display: block;
          min-height: 100%;
          color: #e8f1ff;
          background: #07111f;
          font-family: var(--ha-font-family-body, Inter, system-ui, sans-serif);
        }
        .shell {
          display: flex;
          flex-direction: column;
          min-height: 100vh;
          background:
            radial-gradient(circle at 12% 0%, rgba(41, 111, 194, .24), transparent 34%),
            linear-gradient(145deg, #0c1b30, #050b16 68%);
        }
        header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          min-height: 56px;
          padding: 10px 20px;
          box-sizing: border-box;
          border-bottom: 1px solid rgba(125, 175, 232, .2);
          background: rgba(8, 19, 35, .9);
        }
        .title {
          display: flex;
          align-items: center;
          gap: 11px;
          min-width: 0;
        }
        .mark {
          display: grid;
          place-items: center;
          width: 32px;
          height: 32px;
          border: 1px solid rgba(94, 184, 255, .65);
          border-radius: 10px;
          color: #75c9ff;
          background: linear-gradient(145deg, #153b67, #0b1b31);
          box-shadow: 0 0 20px rgba(50, 153, 244, .18);
          font-size: 18px;
          font-weight: 800;
        }
        .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 750; }
        .sub { color: #93a9c5; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
        a {
          flex: 0 0 auto;
          padding: 8px 12px;
          border: 1px solid rgba(125, 175, 232, .25);
          border-radius: 999px;
          color: #a8d9ff;
          background: rgba(35, 80, 130, .25);
          font-size: 12px;
          text-decoration: none;
        }
        a:hover, a:focus-visible { border-color: #65bfff; background: rgba(35, 106, 172, .45); outline: none; }
        iframe { display: block; flex: 1 1 auto; width: 100%; min-height: calc(100vh - 56px); border: 0; background: #07111f; }
        .empty { max-width: 620px; margin: 12vh auto; padding: 28px; color: #a7bad3; text-align: center; }
        .empty strong { display: block; margin-bottom: 8px; color: #e8f1ff; font-size: 20px; }
        @media (max-width: 600px) {
          header { padding: 9px 12px; }
          .sub { display: none; }
          iframe { min-height: calc(100vh - 51px); }
        }
      `;

      const shell = document.createElement("div");
      shell.className = "shell";
      const header = document.createElement("header");
      const title = document.createElement("div");
      title.className = "title";
      const mark = document.createElement("span");
      mark.className = "mark";
      mark.textContent = "TG";
      const copy = document.createElement("div");
      const name = document.createElement("div");
      name.className = "name";
      name.textContent = this._config().title || "Thessla Green";
      const sub = document.createElement("div");
      sub.className = "sub";
      sub.textContent = "panel gatewaya · lokalne sterowanie";
      copy.append(name, sub);
      title.append(mark, copy);
      header.appendChild(title);

      if (url) {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Otwórz osobno";
        header.appendChild(link);
      }
      shell.appendChild(header);

      if (!url) {
        const empty = document.createElement("div");
        empty.className = "empty";
        const strong = document.createElement("strong");
        strong.textContent = "Brak adresu panelu gatewaya";
        empty.append(strong, document.createTextNode("Otwórz konfigurację integracji i ustaw poprawny adres FastAPI."));
        shell.appendChild(empty);
      } else {
        const frame = document.createElement("iframe");
        frame.title = "Thessla Green — panel sterowania";
        frame.src = url;
        frame.loading = "eager";
        frame.referrerPolicy = "no-referrer";
        frame.allow = "fullscreen";
        shell.appendChild(frame);
      }
      this._shadow.replaceChildren(style, shell);
    }
  }

  customElements.define(TAG_NAME, ThesslaGreenPanel);
})();
