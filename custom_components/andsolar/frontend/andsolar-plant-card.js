/**
 * AndSolar Plant Layout Card for Home Assistant
 *
 * Renders solar panels from /api/openapi/module/getViewListNoData polygons with
 * live HA entity values, heatmap shading, status dots, hover tooltips, zoom/pan,
 * and configurable YAML / visual editor options.
 */

const CARD_VERSION = "1.1.0-beta.2";

const ADDITIVE_METRICS = new Set(["daily_energy", "total_energy", "power"]);
const SHARED_DEVICE_MODES = new Set(["average", "primary", "raw"]);

const METRIC_DEFS = {
  daily_energy: {
    key: "daily_energy",
    label: "Today Yield (kWh)",
    shortLabel: "Today Yield",
    unit: "kWh",
    decimals: 2,
    palette: ["#4f7fd9", "#1e3a8a"],
    agg: "sum",
  },
  power: {
    key: "power",
    label: "Power (W)",
    shortLabel: "Power",
    unit: "W",
    decimals: 0,
    palette: ["#3b82f6", "#1d4ed8"],
    agg: "sum",
  },
  current: {
    key: "current",
    label: "Current (A)",
    shortLabel: "Current",
    unit: "A",
    decimals: 2,
    palette: ["#06b6d4", "#0e7490"],
    agg: "avg",
  },
  voltage: {
    key: "voltage",
    label: "Voltage (V)",
    shortLabel: "Voltage",
    unit: "V",
    decimals: 1,
    palette: ["#6366f1", "#3730a3"],
    agg: "avg",
  },
  temperature: {
    key: "temperature",
    label: "Temperature (°C)",
    shortLabel: "Temperature",
    unit: "°C",
    decimals: 1,
    palette: ["#38bdf8", "#ea580c"],
    agg: "avg",
  },
  total_energy: {
    key: "total_energy",
    label: "Cumulative Yield (kWh)",
    shortLabel: "Cumulative Yield",
    unit: "kWh",
    decimals: 1,
    palette: ["#3b82f6", "#1e3a8a"],
    agg: "sum",
  },
};

const ALL_METRIC_KEYS = Object.keys(METRIC_DEFS);

const STATUS_META = {
  on: { dot: "#22c55e", label: "On" },
  off: { dot: "#ef4444", label: "Off" },
  warning: { dot: "#f59e0b", label: "Warning" },
  offline: { dot: "#64748b", label: "Offline" },
  unknown: { dot: "#94a3b8", label: "Unknown" },
};

const DEFAULT_CONFIG = {
  plant_id: undefined,
  title: "",
  show_title: false,
  default_metric: "daily_energy",
  shared_device_mode: "average",
  metrics: undefined,
  show_header: true,
  show_metric_selector: true,
  show_summary: true,
  show_legend: true,
  show_scale: true,
  show_compass: true,
  show_grid: true,
  show_cell_pattern: true,
  show_values: true,
  show_unit_on_panel: false,
  show_sn: false,
  show_status_dot: true,
  show_tooltip: true,
  show_detail_bar: true,
  show_switch_control: true,
  enable_zoom_pan: true,
  show_zoom_controls: true,
  min_zoom: 0.5,
  max_zoom: 6,
  rotation: 0,
  height: 320,
  tap_action: "select",
  background_image: "",
  background_opacity: 0.35,
};

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function hexToRgb(hex) {
  const clean = hex.replace("#", "");
  const num = parseInt(clean, 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function lerpColor(hexA, hexB, t) {
  const a = hexToRgb(hexA);
  const b = hexToRgb(hexB);
  const clamped = clamp(t, 0, 1);
  const r = Math.round(a[0] + (b[0] - a[0]) * clamped);
  const g = Math.round(a[1] + (b[1] - a[1]) * clamped);
  const bl = Math.round(a[2] + (b[2] - a[2]) * clamped);
  return `rgb(${r}, ${g}, ${bl})`;
}

function formatNumber(val, decimals) {
  if (val === null || val === undefined || Number.isNaN(val)) return "—";
  return Number(val).toFixed(decimals);
}

function median(values) {
  if (!values.length) return 1.1;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

class AndSolarPlantCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = { ...DEFAULT_CONFIG };
    this._hass = null;
    this._layout = null;
    this._loading = false;
    this._fetchSeq = 0;
    this._error = null;
    this._currentMetric = DEFAULT_CONFIG.default_metric;
    this._selectedPanelKey = null;
    this._stateFingerprint = null;
    this._switchBusy = false;

    // Geometry & viewBox state
    this._geometry = null;
    this._baseVb = { x: 0, y: 0, w: 600, h: 300 };
    this._vb = { x: 0, y: 0, w: 600, h: 300 };

    // Pointer / zoom-pan interaction state
    this._pointers = new Map();
    this._panStart = null;
    this._pinchStart = null;
    this._didDrag = false;
    this._renderedShell = false;
  }

  static getStubConfig() {
    return {
      default_metric: "daily_energy",
      shared_device_mode: "average",
      show_zoom_controls: true,
      enable_zoom_pan: true,
      show_legend: true,
      show_summary: true,
      show_scale: true,
      show_detail_bar: true,
    };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "plant_id", selector: { number: { mode: "box" } } },
        { name: "title", selector: { text: {} } },
        { name: "show_title", selector: { boolean: {} } },
        {
          name: "default_metric",
          selector: {
            select: {
              mode: "dropdown",
              options: ALL_METRIC_KEYS.map((key) => ({
                value: key,
                label: METRIC_DEFS[key].label,
              })),
            },
          },
        },
        {
          name: "shared_device_mode",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "average", label: "Average per panel (÷ 2 for 1:2 optimizer)" },
                { value: "primary", label: "Actual value on first panel only" },
                { value: "raw", label: "Raw device value on every panel" },
              ],
            },
          },
        },
        {
          name: "tap_action",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "select", label: "Show detail bar" },
                { value: "more-info", label: "Open entity More Info" },
                { value: "none", label: "None" },
              ],
            },
          },
        },
        {
          type: "grid",
          name: "",
          schema: [
            {
              name: "height",
              selector: {
                number: { min: 160, max: 1200, unit_of_measurement: "px", mode: "box" },
              },
            },
            {
              name: "rotation",
              selector: {
                number: { min: -180, max: 180, unit_of_measurement: "°", mode: "box" },
              },
            },
          ],
        },
        {
          type: "expandable",
          title: "Display options",
          schema: [
            { name: "show_header", selector: { boolean: {} } },
            { name: "show_metric_selector", selector: { boolean: {} } },
            { name: "show_summary", selector: { boolean: {} } },
            { name: "show_legend", selector: { boolean: {} } },
            { name: "show_scale", selector: { boolean: {} } },
            { name: "show_compass", selector: { boolean: {} } },
            { name: "show_grid", selector: { boolean: {} } },
            { name: "show_cell_pattern", selector: { boolean: {} } },
            { name: "show_values", selector: { boolean: {} } },
            { name: "show_unit_on_panel", selector: { boolean: {} } },
            { name: "show_sn", selector: { boolean: {} } },
            { name: "show_status_dot", selector: { boolean: {} } },
            { name: "show_tooltip", selector: { boolean: {} } },
            { name: "show_detail_bar", selector: { boolean: {} } },
            { name: "show_switch_control", selector: { boolean: {} } },
          ],
        },
        {
          type: "expandable",
          title: "Zoom & Pan",
          schema: [
            { name: "enable_zoom_pan", selector: { boolean: {} } },
            { name: "show_zoom_controls", selector: { boolean: {} } },
            {
              name: "min_zoom",
              selector: { number: { min: 0.2, max: 1, step: 0.1, mode: "box" } },
            },
            {
              name: "max_zoom",
              selector: { number: { min: 1, max: 15, step: 0.5, mode: "box" } },
            },
          ],
        },
        {
          type: "expandable",
          title: "Background image",
          schema: [
            { name: "background_image", selector: { text: {} } },
            {
              name: "background_opacity",
              selector: { number: { min: 0, max: 1, step: 0.05, mode: "slider" } },
            },
          ],
        },
      ],
      computeLabel: (schema) => {
        const labels = {
          plant_id: "Plant ID (optional — auto-detects if empty)",
          title: "Card title",
          show_title: "Show card title",
          default_metric: "Default metric",
          shared_device_mode: "1:2 / shared optimizer display",
          tap_action: "Panel tap action",
          height: "Canvas height",
          rotation: "Layout rotation",
          show_header: "Show top toolbar",
          show_metric_selector: "Show metric dropdown",
          show_summary: "Show total / average badge",
          show_legend: "Show status legend",
          show_scale: "Show color scale bar",
          show_compass: "Show North compass",
          show_grid: "Show background dot grid",
          show_cell_pattern: "Show solar cell texture",
          show_values: "Show values on panels",
          show_unit_on_panel: "Show unit on panels",
          show_sn: "Show device SN on panels",
          show_status_dot: "Show status indicator dot",
          show_tooltip: "Show hover tooltip",
          show_detail_bar: "Show panel detail bar",
          show_switch_control: "Allow MOS switch toggle in detail bar",
          enable_zoom_pan: "Enable mouse wheel / drag / pinch zoom & pan",
          show_zoom_controls: "Show zoom control buttons (+ / - / Reset)",
          min_zoom: "Minimum zoom",
          max_zoom: "Maximum zoom",
          background_image: "Background image URL (e.g. /local/roof.jpg)",
          background_opacity: "Background image opacity",
        };
        return labels[schema.name] || schema.name;
      },
    };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") {
      throw new Error("Invalid configuration");
    }

    const prevPlantId = this._config?.plant_id;
    const prevRotation = this._config?.rotation;

    const merged = { ...DEFAULT_CONFIG, ...config };
    const allowedMetrics = Array.isArray(merged.metrics)
      ? merged.metrics.filter((m) => Boolean(METRIC_DEFS[m]))
      : ALL_METRIC_KEYS;

    merged._allowedMetrics = allowedMetrics.length ? allowedMetrics : ALL_METRIC_KEYS;
    if (!merged._allowedMetrics.includes(merged.default_metric)) {
      merged.default_metric = merged._allowedMetrics[0];
    }
    if (!SHARED_DEVICE_MODES.has(merged.shared_device_mode)) {
      merged.shared_device_mode = DEFAULT_CONFIG.shared_device_mode;
    }

    merged.height = clamp(Number(merged.height) || DEFAULT_CONFIG.height, 140, 1400);
    merged.min_zoom = clamp(Number(merged.min_zoom) || DEFAULT_CONFIG.min_zoom, 0.2, 1);
    merged.max_zoom = clamp(Number(merged.max_zoom) || DEFAULT_CONFIG.max_zoom, 1, 20);
    merged.rotation = Number(merged.rotation) || 0;
    merged.background_opacity = clamp(
      merged.background_opacity !== undefined
        ? Number(merged.background_opacity)
        : DEFAULT_CONFIG.background_opacity,
      0,
      1
    );

    if (merged.plant_id === "" || merged.plant_id === null) {
      merged.plant_id = undefined;
    }

    this._config = merged;
    this._currentMetric = merged.default_metric;

    const plantChanged = prevPlantId !== merged.plant_id;
    const rotationChanged = prevRotation !== merged.rotation;

    if (plantChanged) {
      this._layout = null;
      this._geometry = null;
      this._selectedPanelKey = null;
      this._stateFingerprint = null;
      if (this._hass) {
        this._fetchLayout();
      }
    } else if (rotationChanged && this._layout) {
      this._buildGeometry();
    }

    this._renderFull();
  }

  getCardSize() {
    const h = this._config?.height || 320;
    return Math.max(4, Math.ceil((h + 110) / 50));
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._layout && !this._loading && !this._error) {
      this._fetchLayout();
      return;
    }
    if (!this._layout) return;

    const fp = this._computeStateFingerprint();
    if (fp !== this._stateFingerprint) {
      this._stateFingerprint = fp;
      this._updateDynamicView();
    }
  }

  connectedCallback() {
    if (!this._renderedShell) {
      this._renderFull();
    }
    if (this._hass && !this._layout && !this._loading) {
      this._fetchLayout();
    }
  }

  async _fetchLayout() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._error = null;
    this._renderFull();

    try {
      const msg = { type: "andsolar/get_plant_layout" };
      if (this._config.plant_id !== undefined) {
        msg.plant_id = Number(this._config.plant_id);
      }
      const result = await this._hass.callWS(msg);
      this._layout = result;
      this._error = null;
      this._buildGeometry();
      this._stateFingerprint = this._computeStateFingerprint();
    } catch (err) {
      this._layout = null;
      this._geometry = null;
      this._error = err?.message || "Failed to load AndSolar plant layout.";
    } finally {
      this._loading = false;
      this._renderFull();
    }
  }

  _panelKey(panel) {
    return `${panel.sn}_${panel.branch}_${panel.id ?? ""}`;
  }

  _computeStateFingerprint() {
    if (!this._hass || !this._layout) return "";
    const parts = [];
    for (const panel of this._layout.panels || []) {
      const entities = panel.entities || {};
      for (const key of Object.keys(entities)) {
        const eid = entities[key];
        if (!eid) continue;
        const st = this._hass.states[eid];
        parts.push(st ? `${eid}:${st.state}:${st.last_updated}` : `${eid}:-`);
      }
    }
    return parts.join("|");
  }

  _resolvePanelLive(panel) {
    const states = this._hass?.states || {};
    const entities = panel.entities || {};
    const values = {};

    for (const metricKey of ALL_METRIC_KEYS) {
      const eid = entities[metricKey];
      if (eid && Object.prototype.hasOwnProperty.call(states, eid)) {
        const st = states[eid];
        if (st && st.state !== "unavailable" && st.state !== "unknown" && st.state !== "") {
          const parsed = Number(st.state);
          values[metricKey] = Number.isFinite(parsed) ? parsed : null;
        } else {
          values[metricKey] = null;
        }
      } else {
        const fallback = panel.values ? panel.values[metricKey] : null;
        values[metricKey] = fallback !== undefined ? fallback : null;
      }
    }

    const statusEid = entities.status;
    const switchEid = entities.switch;
    const statusObj = statusEid ? states[statusEid] : null;
    const switchObj = switchEid ? states[switchEid] : null;

    const statusState = statusObj ? String(statusObj.state).toLowerCase() : null;
    const switchState = switchObj ? String(switchObj.state).toLowerCase() : null;
    const isRapid = panel.device_type === "rapidShutdown";

    let status = panel.status || "unknown";
    if (statusObj) {
      if (statusState === "offline" || statusState === "unavailable") {
        status = "offline";
      } else if (statusState === "warning" || statusState === "accident") {
        status = "warning";
      } else if (isRapid && switchState === "off") {
        status = "off";
      } else if (statusState === "healthy" || (isRapid && switchState === "on")) {
        status = "on";
      } else if (statusState === "unknown") {
        status = panel.status || "unknown";
      }
    } else if (isRapid && switchObj) {
      if (switchState === "unavailable") {
        status = "offline";
      } else if (switchState === "off") {
        status = "off";
      } else if (switchState === "on") {
        status = "on";
      }
    }

    const mosOn =
      switchState === "on"
        ? true
        : switchState === "off"
          ? false
          : panel.mos;

    const sharedCount = Math.max(1, Number(panel.shared_count) || 1);
    const sharedIndex = Number(panel.shared_index) || 0;
    const mode = this._config.shared_device_mode || "average";
    const displayValues = {};

    for (const metricKey of ALL_METRIC_KEYS) {
      const rawVal = values[metricKey];
      if (
        rawVal !== null &&
        rawVal !== undefined &&
        Number.isFinite(rawVal) &&
        mode === "average" &&
        sharedCount > 1 &&
        ADDITIVE_METRICS.has(metricKey)
      ) {
        displayValues[metricKey] = rawVal / sharedCount;
      } else {
        displayValues[metricKey] = rawVal;
      }
    }

    const hidePanelValue =
      mode === "primary" && sharedCount > 1 && sharedIndex > 0;

    return {
      rawValues: values,
      values: displayValues,
      status,
      mosOn,
      switchEid,
      sharedCount,
      sharedIndex,
      hidePanelValue,
    };
  }

  _buildGeometry() {
    const panels = this._layout?.panels || [];
    if (!panels.length) {
      this._geometry = null;
      return;
    }

    // Fallback shared-source grouping if payload lacks shared_count/shared_index
    const sourceGroups = new Map();
    for (const panel of panels) {
      const sourceKey = `${panel.sn}:${panel.branch_key || "branchOne"}`;
      if (!sourceGroups.has(sourceKey)) sourceGroups.set(sourceKey, []);
      sourceGroups.get(sourceKey).push(panel);
    }
    for (const members of sourceGroups.values()) {
      members.sort(
        (a, b) =>
          (Number(a.branch) || 1) - (Number(b.branch) || 1) ||
          (Number(a.id) || 0) - (Number(b.id) || 0)
      );
      members.forEach((member, idx) => {
        if (member.shared_count === undefined) member.shared_count = members.length;
        if (member.shared_index === undefined) member.shared_index = idx;
      });
    }

    const bounds = this._layout.bounds || { width: 0, height: 0 };
    const originX = (bounds.width || 0) / 2;
    const originY = (bounds.height || 0) / 2;
    const rad = ((this._config.rotation || 0) * Math.PI) / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);

    // Measure median panel shortest edge in meters to normalize SVG sizing cleanly
    const shortEdges = [];
    for (const panel of panels) {
      const pts = panel.points || [];
      if (pts.length < 3) continue;
      let minEdge = Infinity;
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i];
        const b = pts[(i + 1) % pts.length];
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len > 0.05 && len < minEdge) minEdge = len;
      }
      if (Number.isFinite(minEdge)) shortEdges.push(minEdge);
    }

    const unitMeters = Math.max(median(shortEdges), 0.25);
    const svgScale = 64 / unitMeters;

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    const transformed = panels.map((panel) => {
      const pts = (panel.points || []).map(([px, py]) => {
        const dx = px - originX;
        const dy = py - originY;
        const rx = (dx * cos - dy * sin + originX) * svgScale;
        const ry = (dx * sin + dy * cos + originY) * svgScale;
        if (rx < minX) minX = rx;
        if (ry < minY) minY = ry;
        if (rx > maxX) maxX = rx;
        if (ry > maxY) maxY = ry;
        return [rx, ry];
      });
      return { panel, pts };
    });

    if (!Number.isFinite(minX)) {
      this._geometry = null;
      return;
    }

    const rawW = Math.max(maxX - minX, 64);
    const rawH = Math.max(maxY - minY, 64);
    const pad = Math.max(28, Math.min(rawW, rawH) * 0.08);

    const shapes = transformed.map(({ panel, pts }) => {
      const n = pts.length || 1;
      let cx = 0;
      let cy = 0;
      let pMinX = Infinity;
      let pMaxX = -Infinity;
      let pMinY = Infinity;
      let pMaxY = -Infinity;

      for (const [x, y] of pts) {
        cx += x;
        cy += y;
        if (x < pMinX) pMinX = x;
        if (x > pMaxX) pMaxX = x;
        if (y < pMinY) pMinY = y;
        if (y > pMaxY) pMaxY = y;
      }
      cx /= n;
      cy /= n;

      // Find top-rightmost vertex (max x - y) for consistent status dot placement
      let bestVertex = pts[0] || [cx, cy];
      let bestScore = -Infinity;
      for (const pt of pts) {
        const score = pt[0] - pt[1];
        if (score > bestScore) {
          bestScore = score;
          bestVertex = pt;
        }
      }
      const dotX = bestVertex[0] + (cx - bestVertex[0]) * 0.24;
      const dotY = bestVertex[1] + (cy - bestVertex[1]) * 0.24;

      const spanW = pMaxX - pMinX;
      const spanH = pMaxY - pMinY;
      const minSpan = Math.max(20, Math.min(spanW, spanH));
      const fontSize = clamp(minSpan * 0.24, 10, 17);
      const snFontSize = clamp(minSpan * 0.145, 7.5, 11);
      const dotR = clamp(minSpan * 0.085, 3.8, 6.2);

      return {
        key: this._panelKey(panel),
        sourceKey: `${panel.sn}:${panel.branch_key || "branchOne"}`,
        sharedCount: Math.max(1, Number(panel.shared_count) || 1),
        sharedIndex: Number(panel.shared_index) || 0,
        panel,
        pts,
        pointsAttr: pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" "),
        cx,
        cy,
        dotX,
        dotY,
        dotR,
        fontSize,
        snFontSize,
        spanW,
        spanH,
      };
    });

    this._geometry = {
      shapes,
      contentBounds: { x: minX, y: minY, w: rawW, h: rawH },
    };

    this._baseVb = {
      x: minX - pad,
      y: minY - pad,
      w: rawW + pad * 2,
      h: rawH + pad * 2,
    };
    this._vb = { ...this._baseVb };
  }

  _currentZoom() {
    if (!this._vb.w || !this._baseVb.w) return 1;
    return this._baseVb.w / this._vb.w;
  }

  _applyViewBox() {
    const svg = this.shadowRoot?.getElementById("roofSvg");
    if (svg) {
      svg.setAttribute(
        "viewBox",
        `${this._vb.x.toFixed(2)} ${this._vb.y.toFixed(2)} ${this._vb.w.toFixed(2)} ${this._vb.h.toFixed(2)}`
      );
    }
    const badge = this.shadowRoot?.getElementById("zoomBadge");
    if (badge) {
      badge.textContent = `${Math.round(this._currentZoom() * 100)}%`;
    }
  }

  _zoomAt(factor, clientX, clientY) {
    const svg = this.shadowRoot?.getElementById("roofSvg");
    if (!svg) return;

    const currentZoom = this._currentZoom();
    const targetZoom = clamp(
      currentZoom * factor,
      this._config.min_zoom,
      this._config.max_zoom
    );
    if (Math.abs(targetZoom - currentZoom) < 0.001) return;

    let anchorX = this._vb.x + this._vb.w / 2;
    let anchorY = this._vb.y + this._vb.h / 2;

    if (clientX !== undefined && clientY !== undefined) {
      const pt = this._clientToSvg(svg, clientX, clientY);
      if (pt) {
        anchorX = pt.x;
        anchorY = pt.y;
      }
    }

    const newW = this._baseVb.w / targetZoom;
    const newH = this._baseVb.h / targetZoom;
    const rx = (anchorX - this._vb.x) / this._vb.w;
    const ry = (anchorY - this._vb.y) / this._vb.h;

    this._vb = {
      x: anchorX - rx * newW,
      y: anchorY - ry * newH,
      w: newW,
      h: newH,
    };
    this._applyViewBox();
  }

  _resetZoom() {
    this._vb = { ...this._baseVb };
    this._applyViewBox();
  }

  _clientToSvg(svg, clientX, clientY) {
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    return pt.matrixTransform(ctm.inverse());
  }

  _bindInteractions() {
    const root = this.shadowRoot;
    if (!root) return;

    const metricSelect = root.getElementById("metricSelect");
    if (metricSelect) {
      metricSelect.addEventListener("change", (e) => {
        this._currentMetric = e.target.value;
        this._updateDynamicView();
      });
    }

    const zoomInBtn = root.getElementById("zoomInBtn");
    const zoomOutBtn = root.getElementById("zoomOutBtn");
    const zoomResetBtn = root.getElementById("zoomResetBtn");
    if (zoomInBtn) zoomInBtn.addEventListener("click", () => this._zoomAt(1.25));
    if (zoomOutBtn) zoomOutBtn.addEventListener("click", () => this._zoomAt(0.8));
    if (zoomResetBtn) zoomResetBtn.addEventListener("click", () => this._resetZoom());

    const retryBtn = root.getElementById("retryBtn");
    if (retryBtn) retryBtn.addEventListener("click", () => this._fetchLayout());

    const svg = root.getElementById("roofSvg");
    if (!svg || !this._config.enable_zoom_pan) return;

    svg.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        this._zoomAt(factor, e.clientX, e.clientY);
      },
      { passive: false }
    );

    svg.addEventListener("dblclick", (e) => {
      if (e.target.closest?.(".panel-group")) return;
      this._resetZoom();
    });

    svg.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this._didDrag = false;

      if (this._pointers.size === 1) {
        this._panStart = {
          clientX: e.clientX,
          clientY: e.clientY,
          vbX: this._vb.x,
          vbY: this._vb.y,
        };
        this._pinchStart = null;
      } else if (this._pointers.size === 2) {
        try {
          svg.setPointerCapture(e.pointerId);
        } catch {
          // ignore if pointer cannot be captured
        }
        const pts = Array.from(this._pointers.values());
        this._pinchStart = {
          dist: Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y) || 1,
          midX: (pts[0].x + pts[1].x) / 2,
          midY: (pts[0].y + pts[1].y) / 2,
          vb: { ...this._vb },
        };
        this._panStart = null;
      }
    });

    svg.addEventListener("pointermove", (e) => {
      if (!this._pointers.has(e.pointerId)) return;
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (this._pointers.size === 1 && this._panStart) {
        const dxPx = e.clientX - this._panStart.clientX;
        const dyPx = e.clientY - this._panStart.clientY;
        if (!this._didDrag && Math.hypot(dxPx, dyPx) > 4) {
          this._didDrag = true;
          this._hideTooltip();
          svg.classList.add("grabbing");
          try {
            svg.setPointerCapture(e.pointerId);
          } catch {
            // ignore if pointer cannot be captured
          }
        }
        if (!this._didDrag) return;
        const rect = svg.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          const scale = Math.max(this._vb.w / rect.width, this._vb.h / rect.height);
          this._vb.x = this._panStart.vbX - dxPx * scale;
          this._vb.y = this._panStart.vbY - dyPx * scale;
          this._applyViewBox();
        }
      } else if (this._pointers.size === 2 && this._pinchStart) {
        this._didDrag = true;
        this._hideTooltip();
        const pts = Array.from(this._pointers.values());
        const dist = Math.hypot(pts[1].x - pts[0].x, pts[1].y - pts[0].y) || 1;
        const midX = (pts[0].x + pts[1].x) / 2;
        const midY = (pts[0].y + pts[1].y) / 2;

        const baseZoom = this._baseVb.w / this._pinchStart.vb.w;
        const nextZoom = clamp(
          baseZoom * (dist / this._pinchStart.dist),
          this._config.min_zoom,
          this._config.max_zoom
        );
        const newW = this._baseVb.w / nextZoom;
        const newH = this._baseVb.h / nextZoom;

        const rect = svg.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          const rx = clamp((midX - rect.left) / rect.width, 0, 1);
          const ry = clamp((midY - rect.top) / rect.height, 0, 1);
          const anchorX = this._pinchStart.vb.x + rx * this._pinchStart.vb.w;
          const anchorY = this._pinchStart.vb.y + ry * this._pinchStart.vb.h;
          this._vb = {
            x: anchorX - rx * newW,
            y: anchorY - ry * newH,
            w: newW,
            h: newH,
          };
          this._applyViewBox();
        }
      }
    });

    const endPointer = (e) => {
      this._pointers.delete(e.pointerId);
      if (this._pointers.size === 0) {
        this._panStart = null;
        this._pinchStart = null;
        svg.classList.remove("grabbing");
      } else if (this._pointers.size === 1) {
        const remaining = Array.from(this._pointers.values())[0];
        this._panStart = {
          clientX: remaining.x,
          clientY: remaining.y,
          vbX: this._vb.x,
          vbY: this._vb.y,
        };
        this._pinchStart = null;
      }
    };

    svg.addEventListener("pointerup", endPointer);
    svg.addEventListener("pointercancel", endPointer);
  }

  _fireMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      })
    );
  }

  async _togglePanelSwitch(switchEid, turnOn) {
    if (!this._hass || !switchEid || this._switchBusy) return;
    this._switchBusy = true;
    this._renderDetailBar();
    try {
      await this._hass.callService("switch", turnOn ? "turn_on" : "turn_off", {
        entity_id: switchEid,
      });
    } catch (err) {
      // Surface error gracefully in console; HA toast handles service errors
      // eslint-disable-next-line no-console
      console.error("AndSolar switch toggle failed:", err);
    } finally {
      this._switchBusy = false;
      this._renderDetailBar();
    }
  }

  _handlePanelTap(shape) {
    if (this._didDrag) return;
    const action = this._config.tap_action || "select";
    if (action === "none") return;

    if (action === "more-info") {
      const entities = shape.panel.entities || {};
      const target =
        entities[this._currentMetric] ||
        entities.power ||
        entities.daily_energy ||
        entities.status ||
        entities.switch;
      this._fireMoreInfo(target);
      return;
    }

    this._selectedPanelKey =
      this._selectedPanelKey === shape.key ? null : shape.key;
    this._updateDynamicView();
  }

  _setPartnerHover(sourceKey, active) {
    const layer = this.shadowRoot?.getElementById("panelsLayer");
    if (!layer || !sourceKey) return;
    for (const node of layer.children) {
      if (node.dataset?.sourceKey === sourceKey) {
        node.classList.toggle("partner-hover", active);
      }
    }
  }

  _showTooltip(shape, live, event) {
    if (!this._config.show_tooltip || this._didDrag || this._pointers.size > 0) return;
    const tip = this.shadowRoot?.getElementById("tooltip");
    const stage = this.shadowRoot?.getElementById("stage");
    if (!tip || !stage) return;

    const p = shape.panel;
    const stMeta = STATUS_META[live.status] || STATUS_META.unknown;
    const v = live.values;
    const raw = live.rawValues || v;
    const mode = this._config.shared_device_mode || "average";
    const isShared = live.sharedCount > 1;
    const branchTxt =
      p.device_type === "rapidShutdown"
        ? ` B${p.branch}`
        : isShared
          ? ` 1:${live.sharedCount} (#${live.sharedIndex + 1})`
          : "";

    const ratedSingle = p.rated_power ? Math.round(p.rated_power) : null;
    const ratedTxt = ratedSingle
      ? mode === "average"
        ? ` / ${ratedSingle} W`
        : isShared
          ? ` / ${ratedSingle * live.sharedCount} W`
          : ` / ${ratedSingle} W`
      : "";

    const fmtAdditive = (key, unit, dec) => {
      const disp = formatNumber(v[key], dec);
      if (isShared && mode === "average" && raw[key] !== null && raw[key] !== undefined) {
        return `${disp} ${unit} <span class="tip-muted">(${formatNumber(raw[key], dec)} total)</span>`;
      }
      return `${disp} ${unit}`;
    };

    const sharedNote = isShared
      ? `<div class="tip-note">${
          mode === "average"
            ? `Shared 1:${live.sharedCount} optimizer · per-panel avg (÷${live.sharedCount})`
            : mode === "primary"
              ? `Shared 1:${live.sharedCount} optimizer · combined total (${live.sharedCount} panels)`
              : `Shared 1:${live.sharedCount} optimizer · raw device reading`
        }</div>`
      : "";

    tip.innerHTML = `
      <div class="tip-head">
        <span class="tip-sn">${esc(p.sn)}<span class="tip-muted">${esc(branchTxt)}</span></span>
        <span class="status-dot-inline" style="background:${stMeta.dot}"></span>
      </div>
      <div class="tip-grid">
        <span>Status</span><span class="tip-val">${esc(stMeta.label)}</span>
        <span>Power</span><span class="tip-val">${fmtAdditive("power", "W", 0)}${mode === "average" ? esc(ratedTxt) : ""}</span>
        <span>Today</span><span class="tip-val">${fmtAdditive("daily_energy", "kWh", 2)}</span>
        <span>Voltage</span><span class="tip-val">${formatNumber(v.voltage, 1)} V</span>
        <span>Current</span><span class="tip-val">${formatNumber(v.current, 2)} A</span>
        <span>Temp</span><span class="tip-val">${formatNumber(v.temperature, 1)} °C</span>
        <span>Total</span><span class="tip-val">${fmtAdditive("total_energy", "kWh", 1)}</span>
      </div>
      ${sharedNote}
    `;
    tip.classList.remove("hidden");
    this._moveTooltip(event);
  }

  _moveTooltip(event) {
    const tip = this.shadowRoot?.getElementById("tooltip");
    const stage = this.shadowRoot?.getElementById("stage");
    if (!tip || !stage || tip.classList.contains("hidden")) return;

    const stageRect = stage.getBoundingClientRect();
    const tipW = tip.offsetWidth || 185;
    const tipH = tip.offsetHeight || 145;
    let left = event.clientX - stageRect.left + 14;
    let top = event.clientY - stageRect.top + 14;
    if (left + tipW + 8 > stageRect.width) {
      left = event.clientX - stageRect.left - tipW - 14;
    }
    if (top + tipH + 8 > stageRect.height) {
      top = event.clientY - stageRect.top - tipH - 14;
    }
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }

  _hideTooltip() {
    const tip = this.shadowRoot?.getElementById("tooltip");
    if (tip) tip.classList.add("hidden");
  }

  _renderDetailBar() {
    const bar = this.shadowRoot?.getElementById("detailBar");
    if (!bar) return;

    if (!this._selectedPanelKey || !this._geometry) {
      bar.innerHTML = `<span class="detail-hint">Click a panel to inspect live metrics${
        this._config.show_switch_control ? " or control output" : ""
      }.</span>`;
      return;
    }

    const shape = this._geometry.shapes.find((s) => s.key === this._selectedPanelKey);
    if (!shape) {
      this._selectedPanelKey = null;
      bar.innerHTML = "";
      return;
    }

    const p = shape.panel;
    const live = this._resolvePanelLive(p);
    const stMeta = STATUS_META[live.status] || STATUS_META.unknown;
    const v = live.values;
    const isShared = live.sharedCount > 1;
    const mode = this._config.shared_device_mode || "average";
    const branchLabel =
      p.device_type === "rapidShutdown" ? ` · Branch ${p.branch}` : "";
    const sharedPill = isShared
      ? `<span class="detail-pill">1:${live.sharedCount}${
          mode === "average" ? ` (÷${live.sharedCount})` : " combined"
        }</span>`
      : "";
    const stringLabel =
      p.inverter || p.string ? ` · Inv ${p.inverter ?? "?"}/Str ${p.string ?? "?"}` : "";

    const entities = p.entities || {};
    const moreInfoEntity =
      entities[this._currentMetric] ||
      entities.power ||
      entities.daily_energy ||
      entities.status ||
      entities.switch;

    const canSwitch =
      this._config.show_switch_control &&
      Boolean(live.switchEid) &&
      live.status !== "offline";
    const isOff = live.mosOn === false || live.status === "off";

    bar.innerHTML = `
      <div class="detail-left">
        <span class="detail-sn">${esc(p.sn)}${esc(branchLabel)}</span>
        <span class="detail-pill">
          <span class="status-dot-inline" style="background:${stMeta.dot}"></span>
          ${esc(stMeta.label)}
        </span>
        ${sharedPill}
        <span class="detail-metrics">
          ${formatNumber(v.power, 0)} W · ${formatNumber(v.daily_energy, 2)} kWh · ${formatNumber(v.voltage, 1)} V · ${formatNumber(v.temperature, 1)} °C${esc(stringLabel)}
        </span>
      </div>
      <div class="detail-actions">
        ${
          moreInfoEntity
            ? `<button id="moreInfoBtn" class="btn" type="button">History</button>`
            : ""
        }
        ${
          canSwitch
            ? `<button id="toggleSwitchBtn" class="btn ${isOff ? "btn-on" : "btn-off"}" type="button" ${
                this._switchBusy ? "disabled" : ""
              }>${this._switchBusy ? "Sending…" : isOff ? "Turn On" : "Turn Off"}</button>`
            : ""
        }
      </div>
    `;

    const moreBtn = bar.querySelector("#moreInfoBtn");
    if (moreBtn && moreInfoEntity) {
      moreBtn.addEventListener("click", () => this._fireMoreInfo(moreInfoEntity));
    }

    const toggleBtn = bar.querySelector("#toggleSwitchBtn");
    if (toggleBtn && live.switchEid) {
      toggleBtn.addEventListener("click", () =>
        this._togglePanelSwitch(live.switchEid, isOff)
      );
    }
  }

  _updateDynamicView() {
    const root = this.shadowRoot;
    if (!root || !this._geometry) return;

    const metric = METRIC_DEFS[this._currentMetric] || METRIC_DEFS.daily_energy;
    const shapes = this._geometry.shapes;
    const resolved = shapes.map((shape) => ({
      shape,
      live: this._resolvePanelLive(shape.panel),
    }));

    const displayNumeric = resolved
      .map(({ live }) => live.values[metric.key])
      .filter((v) => v !== null && v !== undefined && Number.isFinite(v));

    const minVal = displayNumeric.length ? Math.min(...displayNumeric) : 0;
    const maxVal = displayNumeric.length ? Math.max(...displayNumeric) : 0;

    // Deduplicate by measurement source so 1:2 / 1:N optimizers are never double-counted
    const uniqueSourceValues = [];
    const seenSources = new Set();
    for (const { shape, live } of resolved) {
      if (seenSources.has(shape.sourceKey)) continue;
      const rawVal = live.rawValues[metric.key];
      if (rawVal !== null && rawVal !== undefined && Number.isFinite(rawVal)) {
        seenSources.add(shape.sourceKey);
        uniqueSourceValues.push(rawVal);
      }
    }

    // Update summary badge
    const summaryBadge = root.getElementById("summaryBadge");
    if (summaryBadge) {
      if (uniqueSourceValues.length) {
        const sum = uniqueSourceValues.reduce((a, b) => a + b, 0);
        const aggVal =
          metric.agg === "sum" ? sum : sum / uniqueSourceValues.length;
        const aggPrefix = metric.agg === "sum" ? "Total" : "Avg";
        summaryBadge.textContent = `${aggPrefix}: ${formatNumber(aggVal, metric.decimals)} ${metric.unit}`;
      } else {
        summaryBadge.textContent = `— ${metric.unit}`;
      }
    }

    // Update color scale bar
    const scaleMin = root.getElementById("scaleMin");
    const scaleMax = root.getElementById("scaleMax");
    const scaleGrad = root.getElementById("scaleGradient");
    if (scaleMin) scaleMin.textContent = formatNumber(minVal, metric.decimals);
    if (scaleMax) scaleMax.textContent = `${formatNumber(maxVal, metric.decimals)} ${metric.unit}`;
    if (scaleGrad) {
      scaleGrad.style.background = `linear-gradient(90deg, ${metric.palette[0]}, ${metric.palette[1]})`;
    }

    // Determine selected sourceKey for highlighting linked 1:2 partner panel
    const selectedShape = this._selectedPanelKey
      ? shapes.find((s) => s.key === this._selectedPanelKey)
      : null;
    const selectedSourceKey =
      selectedShape && selectedShape.sharedCount > 1
        ? selectedShape.sourceKey
        : null;

    // Render SVG polygons
    const layer = root.getElementById("panelsLayer");
    if (!layer) return;
    layer.innerHTML = "";

    const ns = "http://www.w3.org/2000/svg";
    const cfg = this._config;

    for (const { shape, live } of resolved) {
      const val = live.values[metric.key];
      const hasVal = val !== null && val !== undefined && Number.isFinite(val);
      const t =
        !hasVal || maxVal === minVal
          ? 0.5
          : (val - minVal) / (maxVal - minVal);

      let fill;
      if (live.status === "offline") {
        fill = "#334155";
      } else if (live.status === "off") {
        fill = "#475569";
      } else if (!hasVal) {
        fill = "#475569";
      } else {
        fill = lerpColor(metric.palette[0], metric.palette[1], t);
      }

      const stMeta = STATUS_META[live.status] || STATUS_META.unknown;
      const isSelected = this._selectedPanelKey === shape.key;
      const isPartnerSelected =
        !isSelected &&
        selectedSourceKey !== null &&
        shape.sourceKey === selectedSourceKey;

      const g = document.createElementNS(ns, "g");
      const cls = [
        "panel-group",
        isSelected ? "selected" : "",
        isPartnerSelected ? "partner-selected" : "",
      ]
        .filter(Boolean)
        .join(" ");
      g.setAttribute("class", cls);
      g.dataset.sourceKey = shape.sourceKey;

      const poly = document.createElementNS(ns, "polygon");
      poly.setAttribute("points", shape.pointsAttr);
      poly.setAttribute("fill", fill);
      poly.setAttribute("filter", "url(#panelShadow)");
      poly.setAttribute("class", "panel-poly");
      g.appendChild(poly);

      if (cfg.show_cell_pattern) {
        const cells = document.createElementNS(ns, "polygon");
        cells.setAttribute("points", shape.pointsAttr);
        cells.setAttribute("fill", "url(#cellLines)");
        cells.setAttribute("pointer-events", "none");
        g.appendChild(cells);
      }

      const outline = document.createElementNS(ns, "polygon");
      outline.setAttribute("points", shape.pointsAttr);
      outline.setAttribute("fill", "none");
      outline.setAttribute(
        "stroke",
        isSelected
          ? "#38bdf8"
          : isPartnerSelected
            ? "rgba(56, 189, 248, 0.8)"
            : "rgba(255,255,255,0.88)"
      );
      outline.setAttribute("stroke-width", isSelected ? "3" : isPartnerSelected ? "2.2" : "1.5");
      if (isPartnerSelected) {
        outline.setAttribute("stroke-dasharray", "5 3");
      }
      outline.setAttribute("stroke-linejoin", "round");
      outline.setAttribute("class", "panel-outline");
      outline.setAttribute("pointer-events", "none");
      g.appendChild(outline);

      const showValueOnThisPanel = cfg.show_values && !live.hidePanelValue;
      if (showValueOnThisPanel) {
        const text = document.createElementNS(ns, "text");
        text.setAttribute("x", shape.cx.toFixed(1));
        text.setAttribute(
          "y",
          (cfg.show_sn ? shape.cy - shape.snFontSize * 0.25 : shape.cy + shape.fontSize * 0.34).toFixed(1)
        );
        text.setAttribute("text-anchor", "middle");
        text.setAttribute("fill", "#ffffff");
        text.setAttribute("font-size", shape.fontSize.toFixed(1));
        text.setAttribute("font-weight", "600");
        text.setAttribute("class", "panel-value");
        text.setAttribute("pointer-events", "none");

        if (live.status === "off") {
          text.textContent = "OFF";
        } else if (live.status === "offline" && !hasVal) {
          text.textContent = "—";
        } else {
          const numTxt = formatNumber(val, metric.decimals);
          text.textContent =
            cfg.show_unit_on_panel && hasVal ? `${numTxt} ${metric.unit}` : numTxt;
        }
        g.appendChild(text);
      }

      if (cfg.show_sn) {
        const snText = document.createElementNS(ns, "text");
        snText.setAttribute("x", shape.cx.toFixed(1));
        snText.setAttribute(
          "y",
          (showValueOnThisPanel ? shape.cy + shape.fontSize * 0.85 : shape.cy + shape.snFontSize * 0.35).toFixed(1)
        );
        snText.setAttribute("text-anchor", "middle");
        snText.setAttribute("fill", "rgba(255,255,255,0.82)");
        snText.setAttribute("font-size", shape.snFontSize.toFixed(1));
        snText.setAttribute("class", "panel-sn");
        snText.setAttribute("pointer-events", "none");
        const tail = shape.panel.sn.slice(-5);
        const br = shape.panel.device_type === "rapidShutdown" ? `·B${shape.panel.branch}` : "";
        snText.textContent = `${tail}${br}`;
        g.appendChild(snText);
      }

      if (cfg.show_status_dot) {
        const dot = document.createElementNS(ns, "circle");
        dot.setAttribute("cx", shape.dotX.toFixed(1));
        dot.setAttribute("cy", shape.dotY.toFixed(1));
        dot.setAttribute("r", shape.dotR.toFixed(1));
        dot.setAttribute("fill", stMeta.dot);
        dot.setAttribute("stroke", "rgba(0,0,0,0.45)");
        dot.setAttribute("stroke-width", "1.1");
        dot.setAttribute("pointer-events", "none");
        g.appendChild(dot);
      }

      g.addEventListener("mouseenter", (e) => {
        if (shape.sharedCount > 1) this._setPartnerHover(shape.sourceKey, true);
        this._showTooltip(shape, live, e);
      });
      g.addEventListener("mousemove", (e) => this._moveTooltip(e));
      g.addEventListener("mouseleave", () => {
        if (shape.sharedCount > 1) this._setPartnerHover(shape.sourceKey, false);
        this._hideTooltip();
      });
      g.addEventListener("click", (e) => {
        e.stopPropagation();
        this._handlePanelTap(shape);
      });

      layer.appendChild(g);
    }

    if (cfg.show_detail_bar) {
      this._renderDetailBar();
    }
  }

  _renderFull() {
    this._renderedShell = true;
    const cfg = this._config;
    const plantName = this._layout?.plant?.name || "AndSolar Plant Layout";
    const cardTitle = cfg.title || plantName;
    const allowedMetrics = cfg._allowedMetrics || ALL_METRIC_KEYS;

    const headerVisible =
      cfg.show_header &&
      (cfg.show_metric_selector || cfg.show_summary || cfg.show_legend);

    let bodyHtml = "";
    if (this._loading) {
      bodyHtml = `<div class="state-box">Loading plant layout…</div>`;
    } else if (this._error) {
      bodyHtml = `
        <div class="state-box error">
          <div>${esc(this._error)}</div>
          <button id="retryBtn" class="btn" type="button">Retry</button>
        </div>
      `;
    } else if (!this._geometry || !this._geometry.shapes.length) {
      bodyHtml = `
        <div class="state-box">
          No panel layout geometry found for <strong>${esc(plantName)}</strong>.
          Configure module positions in AndCloud and reload the AndSolar integration.
        </div>
      `;
    } else {
      const cb = this._geometry.contentBounds;
      const bgImgHtml = cfg.background_image
        ? `<image href="${esc(cfg.background_image)}" x="${cb.x.toFixed(1)}" y="${cb.y.toFixed(1)}" width="${cb.w.toFixed(1)}" height="${cb.h.toFixed(1)}" preserveAspectRatio="xMidYMid slice" opacity="${cfg.background_opacity}" pointer-events="none" />`
        : "";

      bodyHtml = `
        ${
          headerVisible
            ? `
          <div class="toolbar">
            <div class="toolbar-left">
              ${
                cfg.show_metric_selector
                  ? `
                <select id="metricSelect" class="metric-select" aria-label="Metric">
                  ${allowedMetrics
                    .map((k) => {
                      const m = METRIC_DEFS[k];
                      return `<option value="${k}" ${k === this._currentMetric ? "selected" : ""}>${esc(m.label)}</option>`;
                    })
                    .join("")}
                </select>
              `
                  : ""
              }
              ${cfg.show_summary ? `<span id="summaryBadge" class="summary-badge">—</span>` : ""}
            </div>
            ${
              cfg.show_legend
                ? `
              <div class="legend">
                <span class="legend-item"><span class="status-dot-inline" style="background:${STATUS_META.on.dot}"></span>On</span>
                <span class="legend-item"><span class="status-dot-inline" style="background:${STATUS_META.off.dot}"></span>Off</span>
                <span class="legend-item"><span class="status-dot-inline" style="background:${STATUS_META.warning.dot}"></span>Warning</span>
                <span class="legend-item"><span class="status-dot-inline" style="background:${STATUS_META.offline.dot}"></span>Offline</span>
              </div>
            `
                : ""
            }
          </div>
        `
            : ""
        }

        <div id="stage" class="stage ${cfg.show_grid ? "with-grid" : ""}" style="height:${cfg.height}px">
          <svg
            id="roofSvg"
            class="roof-svg ${cfg.enable_zoom_pan ? "pannable" : ""}"
            viewBox="${this._vb.x.toFixed(2)} ${this._vb.y.toFixed(2)} ${this._vb.w.toFixed(2)} ${this._vb.h.toFixed(2)}"
            preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label="${esc(plantName)}"
          >
            <defs>
              <pattern id="cellLines" width="16" height="16" patternUnits="userSpaceOnUse">
                <path d="M 16 0 L 0 0 0 16" fill="none" stroke="#ffffff" stroke-width="0.65" opacity="0.16" />
              </pattern>
              <filter id="panelShadow" x="-12%" y="-12%" width="128%" height="128%">
                <feDropShadow dx="0" dy="2.5" stdDeviation="2.2" flood-color="#000000" flood-opacity="0.24" />
              </filter>
            </defs>
            ${bgImgHtml}
            <g id="panelsLayer"></g>
          </svg>

          ${
            cfg.show_zoom_controls
              ? `
            <div class="zoom-controls" aria-label="Zoom controls">
              <button id="zoomInBtn" class="zoom-btn" type="button" title="Zoom in">+</button>
              <button id="zoomOutBtn" class="zoom-btn" type="button" title="Zoom out">−</button>
              <button id="zoomResetBtn" class="zoom-btn zoom-reset" type="button" title="Reset view">
                <span id="zoomBadge">${Math.round(this._currentZoom() * 100)}%</span>
              </button>
            </div>
          `
              : ""
          }

          ${
            cfg.show_scale
              ? `
            <div class="scale-bar">
              <span id="scaleMin" class="mono">0</span>
              <div id="scaleGradient" class="scale-gradient"></div>
              <span id="scaleMax" class="mono">0</span>
            </div>
          `
              : ""
          }

          ${
            cfg.show_compass
              ? `
            <div class="compass" title="North" style="transform:rotate(${cfg.rotation}deg)">
              <svg width="26" height="26" viewBox="-14 -14 28 28">
                <circle cx="0" cy="0" r="12" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.55" />
                <path d="M 0 -9 L 3.4 1.5 L 0 -0.5 L -3.4 1.5 Z" fill="currentColor" />
                <text x="0" y="9.5" text-anchor="middle" font-size="7.5" font-weight="700" fill="currentColor">N</text>
              </svg>
            </div>
          `
              : ""
          }

          <div id="tooltip" class="tooltip hidden"></div>
        </div>

        ${cfg.show_detail_bar ? `<div id="detailBar" class="detail-bar"></div>` : ""}
      `;
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          overflow: hidden;
          color: var(--primary-text-color);
          background: var(--ha-card-background, var(--card-background-color, #fff));
        }
        .card-header-title {
          padding: 14px 16px 4px 16px;
          font-size: 16px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .card-body {
          padding: 12px 14px 14px 14px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .toolbar {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding-bottom: 8px;
          border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.2));
        }
        .toolbar-left {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 8px;
        }
        .metric-select {
          background: var(--secondary-background-color, rgba(127,127,127,0.1));
          color: var(--primary-text-color);
          border: 1px solid var(--divider-color, rgba(127,127,127,0.28));
          border-radius: 8px;
          padding: 5px 10px;
          font-size: 12.5px;
          font-weight: 500;
          cursor: pointer;
          outline: none;
        }
        .metric-select:focus {
          border-color: var(--primary-color, #03a9f4);
        }
        .summary-badge {
          font-size: 12px;
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-variant-numeric: tabular-nums;
          padding: 4px 8px;
          border-radius: 6px;
          background: var(--secondary-background-color, rgba(127,127,127,0.1));
          border: 1px solid var(--divider-color, rgba(127,127,127,0.2));
          color: var(--secondary-text-color);
        }
        .legend {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 10px;
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .legend-item {
          display: inline-flex;
          align-items: center;
          gap: 5px;
        }
        .status-dot-inline {
          width: 8px;
          height: 8px;
          border-radius: 999px;
          display: inline-block;
          flex-shrink: 0;
        }
        .stage {
          position: relative;
          width: 100%;
          border-radius: 10px;
          border: 1px solid var(--divider-color, rgba(127,127,127,0.2));
          background-color: var(--secondary-background-color, rgba(127,127,127,0.06));
          overflow: hidden;
          touch-action: none;
          user-select: none;
        }
        .stage.with-grid {
          background-image: radial-gradient(
            circle,
            rgba(127, 127, 127, 0.22) 1px,
            transparent 1px
          );
          background-size: 18px 18px;
        }
        .roof-svg {
          width: 100%;
          height: 100%;
          display: block;
        }
        .roof-svg.pannable {
          cursor: grab;
        }
        .roof-svg.pannable.grabbing {
          cursor: grabbing;
        }
        .panel-poly {
          cursor: pointer;
          transition: filter 0.14s ease, fill 0.22s ease;
        }
        .panel-group:hover .panel-poly,
        .panel-group.partner-hover .panel-poly {
          filter: brightness(1.14) url(#panelShadow);
        }
        .panel-group.partner-hover .panel-outline {
          stroke: rgba(56, 189, 248, 0.9);
          stroke-width: 2.2;
        }
        .panel-value {
          font-variant-numeric: tabular-nums;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55);
        }
        .panel-sn {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55);
        }
        .zoom-controls {
          position: absolute;
          top: 10px;
          right: 10px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          z-index: 4;
        }
        .zoom-btn {
          min-width: 30px;
          height: 28px;
          padding: 0 6px;
          border-radius: 7px;
          border: 1px solid var(--divider-color, rgba(127,127,127,0.32));
          background: var(--ha-card-background, var(--card-background-color, rgba(30,30,30,0.9)));
          color: var(--primary-text-color);
          font-size: 14px;
          font-weight: 600;
          line-height: 1;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 1px 4px rgba(0, 0, 0, 0.16);
          opacity: 0.94;
        }
        .zoom-btn:hover {
          border-color: var(--primary-color, #03a9f4);
          opacity: 1;
        }
        .zoom-btn.zoom-reset {
          font-size: 10.5px;
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          height: 24px;
        }
        .scale-bar {
          position: absolute;
          left: 10px;
          bottom: 10px;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 11px;
          color: var(--secondary-text-color);
          background: var(--ha-card-background, var(--card-background-color, rgba(30,30,30,0.88)));
          border: 1px solid var(--divider-color, rgba(127,127,127,0.28));
          border-radius: 6px;
          padding: 3px 8px;
          opacity: 0.94;
          pointer-events: none;
        }
        .scale-gradient {
          width: 60px;
          height: 7px;
          border-radius: 999px;
        }
        .compass {
          position: absolute;
          right: 10px;
          bottom: 10px;
          color: var(--secondary-text-color);
          opacity: 0.7;
          pointer-events: none;
          transition: transform 0.2s ease;
        }
        .mono {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-variant-numeric: tabular-nums;
        }
        .tooltip {
          position: absolute;
          z-index: 10;
          pointer-events: none;
          min-width: 175px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, rgba(127,127,127,0.35));
          background: var(--ha-card-background, var(--card-background-color, #1f2937));
          color: var(--primary-text-color);
          padding: 8px 10px;
          box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28);
          font-size: 12px;
        }
        .tooltip.hidden {
          display: none;
        }
        .tip-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding-bottom: 5px;
          margin-bottom: 5px;
          border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.22));
        }
        .tip-sn {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-weight: 600;
        }
        .tip-muted {
          color: var(--secondary-text-color);
          font-weight: 500;
        }
        .tip-grid {
          display: grid;
          grid-template-columns: auto 1fr;
          gap: 2px 12px;
          color: var(--secondary-text-color);
        }
        .tip-val {
          text-align: right;
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-variant-numeric: tabular-nums;
          color: var(--primary-text-color);
        }
        .tip-note {
          margin-top: 6px;
          padding-top: 5px;
          border-top: 1px solid var(--divider-color, rgba(127,127,127,0.2));
          font-size: 11px;
          color: var(--secondary-text-color);
        }
        .detail-bar {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          padding: 8px 10px;
          border-radius: 8px;
          border: 1px solid var(--divider-color, rgba(127,127,127,0.2));
          background: var(--secondary-background-color, rgba(127,127,127,0.08));
          font-size: 12px;
        }
        .detail-hint {
          color: var(--secondary-text-color);
        }
        .detail-left {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 8px;
        }
        .detail-sn {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-weight: 600;
        }
        .detail-pill {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 2px 7px;
          border-radius: 999px;
          border: 1px solid var(--divider-color, rgba(127,127,127,0.25));
          background: var(--ha-card-background, var(--card-background-color, transparent));
        }
        .detail-metrics {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          color: var(--secondary-text-color);
        }
        .detail-actions {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .btn {
          padding: 5px 10px;
          border-radius: 6px;
          border: 1px solid var(--divider-color, rgba(127,127,127,0.35));
          background: var(--ha-card-background, var(--card-background-color, transparent));
          color: var(--primary-text-color);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
        }
        .btn:hover:not(:disabled) {
          border-color: var(--primary-color, #03a9f4);
        }
        .btn:disabled {
          opacity: 0.55;
          cursor: wait;
        }
        .btn-off {
          border-color: rgba(239, 68, 68, 0.5);
        }
        .btn-on {
          border-color: rgba(34, 197, 94, 0.55);
        }
        .state-box {
          padding: 28px 16px;
          text-align: center;
          color: var(--secondary-text-color);
          font-size: 13px;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 10px;
        }
        .state-box.error {
          color: var(--error-color, #ef4444);
        }
      </style>
      <ha-card>
        ${cfg.show_title ? `<div class="card-header-title">${esc(cardTitle)}</div>` : ""}
        <div class="card-body">
          ${bodyHtml}
        </div>
      </ha-card>
    `;

    this._bindInteractions();
    if (this._geometry) {
      this._updateDynamicView();
    }
  }
}

if (!customElements.get("andsolar-plant-card")) {
  customElements.define("andsolar-plant-card", AndSolarPlantCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "andsolar-plant-card")) {
  window.customCards.push({
    type: "andsolar-plant-card",
    name: "AndSolar Plant Layout",
    description:
      "Interactive solar panel polygon layout with live metrics, heatmap shading, status dots, and zoom/pan.",
    preview: true,
    documentationURL: "https://github.com/armyjam/andsolar-ha#plant-layout-card",
  });
}

// eslint-disable-next-line no-console
console.info(
  `%c ANDSOLAR-PLANT-CARD %c v${CARD_VERSION} `,
  "color: white; background: #1e3a8a; font-weight: 700; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #1e3a8a; background: #dbeafe; font-weight: 700; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
