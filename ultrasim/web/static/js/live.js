/* Live-Telemetrie: Alpine-Komponente plus zwei Profil-Canvas.
 *
 * Der Client hält bewusst keinen eigenen Rennzustand und keine eigene
 * Uhr. Er zeigt, was der Playback-Server ihm schickt – dadurch kann er
 * gar nicht versehentlich in die Zukunft sehen (Abschnitt 8.2).
 */

import { ProfileView } from './profile.js';

const SPEEDS = [1, 10, 60, 300, 1000];

function hms(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function gap(seconds) {
  if (seconds === null || seconds === undefined) return '';
  const sign = seconds >= 0 ? '+' : '−';
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${sign}${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${sign}${m}:${String(s).padStart(2, '0')}`;
}

function raceLive(raceId) {
  return {
    raceId,
    token: null,
    route: null,
    startlist: [],
    frame: null,
    ticker: [],
    speeds: SPEEDS,
    filter: '',
    tooltip: null,
    error: null,
    overview: null,
    detail: null,
    source: null,

    get focus() { return this.frame ? this.frame.focus : null; },
    get board() { return this.frame ? this.frame.board : null; },
    get rows() { return this.board ? this.board.rows : []; },
    get filteredStart() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.startlist;
      return this.startlist.filter(
        (r) => r.name.toLowerCase().includes(q) || r.team.toLowerCase().includes(q) || String(r.bib) === q
      );
    },

    hms, gap,

    async init() {
      try {
        const [routeRes, listRes, sessionRes] = await Promise.all([
          fetch(`/api/race/${this.raceId}/route`),
          fetch(`/api/race/${this.raceId}/startlist`),
          fetch(`/api/race/${this.raceId}/session`, { method: 'POST' }),
        ]);
        this.route = await routeRes.json();
        this.startlist = (await listRes.json()).entries;
        this.token = (await sessionRes.json()).token;
      } catch (e) {
        this.error = 'Renndaten konnten nicht geladen werden.';
        return;
      }

      this.overview = new ProfileView(this.$refs.overview, { height: 90, showLabels: false });
      this.detail = new ProfileView(this.$refs.detail, { height: 190, windowM: 40000 });
      for (const view of [this.overview, this.detail]) {
        view.setRoute(this.route);
        view.onSeek = (dist) => this.control('distance', dist);
        view.onHover = (info) => this.showTooltip(info);
      }
      this.connect();
      await this.refresh();
    },

    connect() {
      if (this.source) this.source.close();
      this.source = new EventSource(`/api/playback/${this.token}/stream`);
      this.source.addEventListener('frame', (e) => this.apply(JSON.parse(e.data)));
      this.source.onerror = () => { this.error = 'Verbindung zum Playback-Server unterbrochen.'; };
    },

    async refresh() {
      const res = await fetch(`/api/playback/${this.token}/frame`);
      this.apply(await res.json());
    },

    apply(frame) {
      this.error = null;
      this.frame = frame;
      if (frame.ticker.length) {
        this.ticker = [...frame.ticker.slice().reverse(), ...this.ticker].slice(0, 120);
      }
      const neighbours = frame.board.rows.map((r) => r.entry_id);
      for (const view of [this.overview, this.detail]) {
        if (!view) continue;
        view.setFrame(
          frame.positions, frame.focus.entry_id, neighbours, frame.focus.conditions
        );
      }
      if (this.detail && this.overview) {
        this.detail._updateWindow();
        this.overview.detailRange = [this.detail.viewStart, this.detail.viewEnd];
      }
      this.overview && this.overview.draw();
      this.detail && this.detail.draw();
    },

    async control(action, value) {
      const res = await fetch(`/api/playback/${this.token}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
      if (res.ok) await this.refresh();
    },

    setFocus(entryId) { this.control('focus', entryId); },
    setSplit(idx) { this.control('split', Number(idx)); },
    setSpeed(v) { this.control('speed', Number(v)); },
    toggleMode() { this.control('mode', this.frame.mode === 'virtual' ? 'split' : 'virtual'); },
    seekFraction(f) { this.control('seek', f * this.frame.horizon_s); },

    showTooltip(info) {
      if (!info || !info.entry) { this.tooltip = null; return; }
      const [id, dist, kmh] = info.entry;
      const rider = this.startlist.find((r) => r.entry_id === id);
      if (!rider) { this.tooltip = null; return; }
      const row = this.rows.find((r) => r.entry_id === id);
      this.tooltip = {
        x: info.clientX + 12,
        y: info.clientY + 12,
        text: `#${rider.bib} ${rider.name}\n${rider.team}\nkm ${(dist / 1000).toFixed(1)} · ${kmh} km/h`
          + (row && row.rank ? `\nRang ${row.rank}` : ''),
      };
    },

    stateLabel(state) {
      return ['fährt', 'Stopp', 'im Ziel', 'DNF'][state] || '';
    },

    destroy() { if (this.source) this.source.close(); },
  };
}

document.addEventListener('alpine:init', () => {
  window.Alpine.data('raceLive', raceLive);
});
