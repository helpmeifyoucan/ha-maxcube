const DAY_KEYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
];

const DAY_LABELS = {
  monday: "Mo",
  tuesday: "Di",
  wednesday: "Mi",
  thursday: "Do",
  friday: "Fr",
  saturday: "Sa",
  sunday: "So",
};

function toMin(hhmm) {
  if (hhmm === "24:00") return 1440;
  const [h, m] = String(hhmm).split(":").map(Number);
  return h * 60 + m;
}

function tempColor(t) {
  if (t == null) return "#9e9e9e";
  // 8 °C -> deep blue, 30 °C -> warm red.
  const p = Math.max(0, Math.min(1, (t - 8) / (30 - 8)));
  const r = Math.round(60 + p * 195);
  const g = Math.round(130 - p * 70);
  const b = Math.round(225 - p * 185);
  return `rgb(${r}, ${g}, ${b})`;
}

class MaxCubeScheduleCard extends HTMLElement {
  constructor() {
    super();
    this._tab = 0;
    this._config = null;
    this._hass = null;
  }

  static getStubConfig() {
    return { entities: [] };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") {
      throw new Error("Invalid configuration");
    }
    if (config.entities !== undefined && !Array.isArray(config.entities)) {
      throw new Error("'entities' must be a list of weekly_schedule entity_ids");
    }
    this._config = config;
    this._tab = 0;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  get hass() {
    return this._hass;
  }

  // Explicit list wins; otherwise every sensor carrying a schedule attribute.
  _entities() {
    if (this._config && Array.isArray(this._config.entities) && this._config.entities.length) {
      return this._config.entities;
    }
    if (!this._hass) return [];
    return Object.keys(this._hass.states)
      .filter((id) => id.startsWith("sensor."))
      .filter((id) => {
        const a = this._hass.states[id].attributes;
        return a && a.schedule;
      })
      .sort();
  }

  _name(id) {
    const st = this._hass && this._hass.states[id];
    return st ? st.attributes.friendly_name || id : id;
  }

  _day(day, ranges) {
    const label = DAY_LABELS[day] || day;
    if (!ranges.length) {
      return `<div class="day"><span class="label">${label}</span><div class="track"></div></div>`;
    }
    const segs = ranges
      .map((r) => {
        const w = Math.max(0, ((toMin(r.to) - toMin(r.from)) / 1440) * 100);
        const t = r.data ? r.data.temp : null;
        return `<div class="seg" style="width:${w}%;background:${tempColor(
          t
        )}" title="${r.from}–${r.to}: ${t} °C"><span>${t != null ? t + "°" : ""}</span></div>`;
      })
      .join("");
    return `<div class="day"><span class="label">${label}</span><div class="track">${segs}</div></div>`;
  }

  _render() {
    if (!this._config) return;

    const ids = this._entities();
    if (!ids.length) {
      this.innerHTML = `<ha-card><div class="pad">Keine Weekly-Schedule-Sensoren gefunden.</div></ha-card>`;
      return;
    }
    if (this._tab >= ids.length) this._tab = 0;
    const activeId = ids[this._tab];

    const tabs = ids
      .map(
        (id, i) =>
          `<button class="tab${i === this._tab ? " active" : ""}" data-i="${i}">${this._name(
            id
          )}</button>`
      )
      .join("");

    const st = this._hass ? this._hass.states[activeId] : null;
    let body;
    if (st && st.attributes && st.attributes.schedule) {
      const sched = st.attributes.schedule;
      body =
        DAY_KEYS.map((day) => this._day(day, sched[day] || [])).join("") +
        `<div class="now">Aktuell: <b>${
          st.state === "unknown" || st.state === "unavailable" ? "–" : st.state + " °C"
        }</b></div>`;
    } else {
      body = `<div class="pad">Keine Schedule-Daten für ${activeId}.</div>`;
    }

    this.innerHTML = `
      <style>
        :host { display: block; }
        .pad { padding: 12px; }
        .tabs { display: flex; overflow-x: auto; gap: 2px; padding: 4px 4px 0; }
        .tab {
          flex: 0 0 auto; border: none; cursor: pointer; padding: 6px 12px;
          border-radius: 8px 8px 0 0; font: inherit; font-size: 13px;
          background: var(--secondary-background-color, #f1f1f1);
          color: var(--primary-text-color, #212121);
        }
        .tab.active {
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          font-weight: 600;
        }
        .rows { padding: 8px 12px 12px; }
        .day { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
        .label { width: 26px; font-size: 12px; color: var(--secondary-text-color, #727272); }
        .track {
          flex: 1; display: flex; height: 22px; border-radius: 4px;
          overflow: hidden; background: #e0e0e0;
        }
        .seg {
          display: flex; align-items: center; justify-content: center;
          font-size: 10px; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,.45);
          white-space: nowrap; overflow: hidden;
        }
        .now { margin-top: 10px; font-size: 13px; }
      </style>
      <ha-card>
        <div class="tabs">${tabs}</div>
        <div class="rows">${body}</div>
      </ha-card>
    `;

    this.querySelectorAll(".tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._tab = Number(btn.dataset.i);
        this._render();
      });
    });
  }

  getCardSize() {
    return 8;
  }
}

customElements.define("maxcube-schedule-card", MaxCubeScheduleCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "maxcube-schedule-card",
  name: "MAX! Cube Schedule Card",
  description: "Zeigt die Wochenprogramme der MAX! Cube Thermostate als Tabs.",
});