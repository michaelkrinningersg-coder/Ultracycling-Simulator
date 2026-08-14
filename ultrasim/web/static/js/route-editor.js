/* Streckeneditor (Game-Design-Dokument, Abschnitt 10.3).
 *
 * "Splits und Servicepunkte per Drag verschiebbar" — und genau das ist
 * der Grund, warum die Marker hier nicht aus dem vorgerenderten
 * Profiluntergrund kommen: Beim Ziehen müssen sie sechzigmal pro Sekunde
 * an einer neuen Stelle stehen, das Profil darunter dagegen nie.
 *
 * Der Editor bewegt ausschließlich Marker. Höhenpunkte, Segmente und
 * Anstiege bleiben, wie der Import sie gefunden hat — sie sind Messwerte,
 * keine Gestaltung. Wer das Profil ändern will, ändert die GPX-Datei.
 */

import { ProfileView } from './profile.js';

/** Namen, die der Import selbst vergeben hat. Wer "km 40" auf km 57
 *  zieht, meint den Zeitmesspunkt – nicht einen Punkt, der weiterhin
 *  "km 40" heißt. Selbst getippte Namen bleiben dagegen unangetastet. */
const AUTO_NAME = /^km\s*\d+([.,]\d+)?$/i;

/** Fangradius in Pixeln. Kleiner und man trifft nichts, größer und man
 *  greift beim Anlegen eines neuen Markers versehentlich den Nachbarn. */
const GRAB_PX = 7;

export function routeEditor(payload, options) {
  return {
    route: payload,
    routeId: options.routeId || null,
    draftToken: options.draftToken || null,
    name: payload.name,
    slug: options.suggestedId,
    minGapM: options.minGapM || 200,
    splits: [],
    services: [],
    dragging: null,   // { list, index }
    hover: null,
    saving: false,
    message: '',
    error: '',
    dirty: false,

    init() {
      // Kopien: Das Original bleibt unangetastet, damit "Verwerfen"
      // wirklich verwirft und nicht nur die Anzeige zurücksetzt.
      this.splits = payload.splits.map((s) => ({ ...s }));
      this.services = payload.service_points.map((s) => ({ ...s }));

      const canvas = this.$refs.canvas;
      this.view = new ProfileView(canvas, { height: 230, showMarkers: false });
      this.view.setRoute(payload);
      this.view.draw();
      this._paint();

      canvas.addEventListener('pointerdown', (e) => this._down(e));
      canvas.addEventListener('pointermove', (e) => this._move(e));
      window.addEventListener('pointerup', () => this._up());
      window.addEventListener('resize', () => { this.view.invalidate(); this._paint(); });
      window.addEventListener('beforeunload', (e) => {
        if (!this.dirty) return;
        e.preventDefault();
        e.returnValue = '';
      });
    },

    // ---------------------------------------------------------------
    // Zeichnen
    // ---------------------------------------------------------------
    _paint() {
      this.view.draw();
      const ctx = this.view.ctx;
      const size = this.view._size;
      const baseY = size.h - this.view.padBottom;
      ctx.save();
      ctx.font = '9px ui-monospace, monospace';

      for (const [i, split] of this.splits.entries()) {
        const x = this.view.x(split.dist_m);
        const active = this._isActive('splits', i);
        ctx.beginPath();
        ctx.moveTo(x, this.view.padTop);
        ctx.lineTo(x, baseY);
        ctx.strokeStyle = split.kind === 'finish' ? '#4ade80'
          : split.kind === 'summit' ? '#ffc247' : 'rgba(120,140,180,.45)';
        ctx.lineWidth = active ? 2.2 : split.kind === 'interval' ? 1 : 1.5;
        ctx.stroke();
        // Der Griff sitzt oben, damit er die Servicepunkte unten nicht
        // überdeckt – die beiden Sorten liegen oft am selben Kilometer.
        this._handle(ctx, x, this.view.padTop + 4, active,
          split.kind === 'finish' ? '#4ade80' : '#ffc247');
      }

      for (const [i, sp] of this.services.entries()) {
        const x = this.view.x(sp.dist_m);
        const active = this._isActive('services', i);
        ctx.beginPath();
        ctx.moveTo(x, baseY - 14);
        ctx.lineTo(x, baseY);
        ctx.strokeStyle = '#47b4ff';
        ctx.lineWidth = active ? 2.2 : 1.2;
        ctx.stroke();
        this._handle(ctx, x, baseY - 14, active, '#47b4ff');
      }
      ctx.restore();
    },

    _handle(ctx, x, y, active, color) {
      ctx.beginPath();
      ctx.arc(x, y, active ? 5.5 : 4, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      if (active) {
        ctx.strokeStyle = 'rgba(255,255,255,.8)';
        ctx.lineWidth = 1.2;
        ctx.stroke();
      }
    },

    _isActive(list, index) {
      const target = this.dragging || this.hover;
      return !!target && target.list === list && target.index === index;
    },

    // ---------------------------------------------------------------
    // Ziehen
    // ---------------------------------------------------------------
    _pick(e) {
      const rect = this.$refs.canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const baseY = this.view._size.h - this.view.padBottom;
      let best = null;
      let bestD = GRAB_PX;

      const consider = (list, index, dist, y) => {
        const dx = Math.abs(this.view.x(dist) - px);
        // Senkrecht großzügig, waagerecht genau: Man zielt auf einen
        // Kilometer, nicht auf eine Höhe.
        if (dx < bestD && Math.abs(py - y) < 26) { best = { list, index }; bestD = dx; }
      };
      this.splits.forEach((s, i) => {
        if (s.kind !== 'finish') consider('splits', i, s.dist_m, this.view.padTop + 4);
      });
      this.services.forEach((s, i) => consider('services', i, s.dist_m, baseY - 14));
      return best;
    },

    _down(e) {
      const hit = this._pick(e);
      if (!hit) return;
      this.dragging = hit;
      this.$refs.canvas.setPointerCapture(e.pointerId);
      this._paint();
    },

    _move(e) {
      if (this.dragging) {
        const rect = this.$refs.canvas.getBoundingClientRect();
        const dist = this.view.distAt(e.clientX - rect.left);
        const list = this.dragging.list === 'splits' ? this.splits : this.services;
        const marker = list[this.dragging.index];
        marker.dist_m = this._clamp(dist);
        if (AUTO_NAME.test(marker.name)) marker.name = `km ${(marker.dist_m / 1000).toFixed(0)}`;
        this.dirty = true;
        this._paint();
        return;
      }
      const hit = this._pick(e);
      const changed = JSON.stringify(hit) !== JSON.stringify(this.hover);
      this.hover = hit;
      this.$refs.canvas.style.cursor = hit ? 'ew-resize' : 'crosshair';
      if (changed) this._paint();
    },

    _up() {
      if (!this.dragging) return;
      this.dragging = null;
      this._sort();
      this._paint();
    },

    _clamp(dist) {
      const max = this.route.distance_m - this.minGapM;
      return Math.round(Math.min(Math.max(dist, this.minGapM), max) / 10) * 10;
    },

    /** Nach jedem Zug neu ordnen – die Tabelle liest sich sonst wirr. */
    _sort() {
      this.splits.sort((a, b) => a.dist_m - b.dist_m);
      this.services.sort((a, b) => a.dist_m - b.dist_m);
    },

    // ---------------------------------------------------------------
    // Tabelle
    // ---------------------------------------------------------------
    setDist(list, index, value) {
      const target = list === 'splits' ? this.splits : this.services;
      const marker = target[index];
      marker.dist_m = this._clamp(parseFloat(value) * 1000 || 0);
      if (AUTO_NAME.test(marker.name)) marker.name = `km ${(marker.dist_m / 1000).toFixed(0)}`;
      this.dirty = true;
      this._sort();
      this._paint();
    },

    addSplit() {
      const at = this._freeSpot();
      this.splits.push({ dist_m: at, name: `km ${(at / 1000).toFixed(0)}`, kind: 'control' });
      this.dirty = true;
      this._sort();
      this._paint();
    },

    addService() {
      const at = this._freeSpot();
      this.services.push({ dist_m: at, name: `SP ${this.services.length + 1}` });
      this.dirty = true;
      this._sort();
      this._paint();
    },

    /** Die größte Lücke zwischen zwei Splits – dort stört ein neuer am
     *  wenigsten und ist sofort sichtbar. */
    _freeSpot() {
      const marks = [0, ...this.splits.map((s) => s.dist_m)].sort((a, b) => a - b);
      let best = this.route.distance_m / 2;
      let bestGap = -1;
      for (let i = 0; i < marks.length - 1; i++) {
        const gap = marks[i + 1] - marks[i];
        if (gap > bestGap) { bestGap = gap; best = marks[i] + gap / 2; }
      }
      return this._clamp(best);
    },

    remove(list, index) {
      const target = list === 'splits' ? this.splits : this.services;
      if (list === 'splits' && target[index].kind === 'finish') return;
      target.splice(index, 1);
      this.dirty = true;
      this._paint();
    },

    resetMarkers() {
      this.splits = this.route.splits.map((s) => ({ ...s }));
      this.services = this.route.service_points.map((s) => ({ ...s }));
      this.dirty = true;
      this._paint();
    },

    km(dist) { return (dist / 1000).toFixed(2); },

    gapBefore(index) {
      if (index === 0) return this.splits[0].dist_m;
      return this.splits[index].dist_m - this.splits[index - 1].dist_m;
    },

    // ---------------------------------------------------------------
    // Speichern
    // ---------------------------------------------------------------
    async save() {
      this.saving = true;
      this.error = '';
      this.message = '';
      try {
        const res = await fetch('/api/route/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            route_id: this.routeId,
            draft_token: this.draftToken,
            id: this.routeId || this.slug,
            name: this.name,
            splits: this.splits,
            service_points: this.services,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Speichern fehlgeschlagen');
        this.dirty = false;
        window.location.href = data.url;
      } catch (err) {
        this.error = String(err.message || err);
      } finally {
        this.saving = false;
      }
    },
  };
}

document.addEventListener('alpine:init', () => window.Alpine.data('routeEditor', routeEditor));
