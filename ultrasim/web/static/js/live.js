/* Live-Telemetrie: Alpine-Komponente plus zwei Profil-Canvas.
 *
 * Der Client hält bewusst keinen eigenen Rennzustand. Er zeigt, was der
 * Playback-Server ihm schickt – dadurch kann er gar nicht versehentlich
 * in die Zukunft sehen (Abschnitt 8.2).
 *
 * Eine eng begrenzte Ausnahme gibt es: die *Anzeige* der Uhren. Der
 * Server schickt bei hohem Zeitraffer nur einen Frame je Sekunde, und
 * dann sprang die gefahrene Zeit in Blöcken von bis zu tausend Sekunden.
 * Zwischen zwei Frames zählt der Client die Zeit deshalb selbst weiter –
 * mit dem Zeitraffer, den ihm der Server nennt, und gedeckelt auf den
 * Wert des nächsten Frames. Er *rechnet* damit nichts: Positionen,
 * Rangfolge und Ereignisse kommen unverändert vom Server. Nur die
 * Ziffern laufen flüssig, statt zu springen.
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
    //: Stand der letzten Serverzeit und wann sie eintraf – daraus
    //: interpoliert der Client zwischen zwei Frames.
    clockBase: 0,
    clockStamp: 0,
    tickNow: 0,
    raf: null,

    get focus() { return this.frame ? this.frame.focus : null; },

    //: Wanduhr des Rennens, zwischen zwei Frames selbst weitergezählt.
    get liveWall() {
      if (!this.frame) return 0;
      if (!this.frame.playing) return this.frame.t_wall;
      const speed = this.frame.speed;
      // Frame-Abstand des Servers, hier gespiegelt. Weiter als bis kurz
      // hinter den nächsten erwarteten Frame darf die Anzeige nicht
      // vorlaufen — sonst korrigiert sie sich sichtbar rückwärts.
      const interval = speed <= 10 ? 0.25 : speed <= 60 ? 0.5 : 1.0;
      const ahead = Math.max((this.tickNow - this.clockStamp) / 1000, 0) * speed;
      return Math.min(
        this.clockBase + Math.min(ahead, interval * 1.2 * speed),
        this.frame.horizon_s
      );
    },
    //: Um so viel ist die Anzeige dem letzten Frame voraus.
    get liveDelta() {
      return this.frame ? this.liveWall - this.frame.t_wall : 0;
    },
    get liveOwnTime() {
      if (!this.focus) return null;
      if (this.focus.own_time_s === null || this.focus.own_time_s === undefined) return null;
      // Nur mitzählen, solange der Fahrer wirklich unterwegs ist: Wer
      // noch nicht gestartet ist, steht bei 0 – seine Uhr läuft nicht,
      // und mitzuzählen hieße, ihm Zeit anzudichten, die es nicht gibt.
      const riding = this.focus.started && (this.focus.state === 0 || this.focus.state === 1);
      return this.focus.own_time_s + (riding ? this.liveDelta : 0);
    },
    get latest() { return this.ticker.slice(0, 10); },
    //: Der Faktor, der gerade am meisten kostet — die Kurzfassung des
    //: Warum-Panels für die zugeklappte Zeile.
    get worstFactor() {
      const rows = this.focus && this.focus.factors ? this.focus.factors.rows : null;
      return rows && rows.length && rows[0].pct < 99.5 ? rows[0] : null;
    },
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

    //: Laufende Uhren zählen zwischen zwei Frames mit, gemessene
    //: Splitzeiten stehen fest.
    rowTime(row) {
      return row.running ? row.t_s + this.liveDelta : row.t_s;
    },

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
        await this.restore();
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
      this.tick();
    },

    //: Ein Bildschirmtakt reicht: Die Ziffern sollen laufen, nicht
    //: springen. Ohne laufendes Rennen schläft die Schleife.
    tick() {
      this.tickNow = performance.now();
      this.raf = requestAnimationFrame(() => this.tick());
    },

    //: Wohin der Betrachter zuletzt geschaut hat. Ohne das beginnt das
    //: Playback nach jedem Ausflug ins Fahrerdetail wieder von vorn — und
    //: bei halbstündigem Startabstand bedeutet "von vorn" Stunden vor dem
    //: Moment, den man gerade sehen wollte.
    get memoryKey() { return `ultrasim:playback:${this.raceId}`; },

    async restore() {
      let saved = null;
      try { saved = JSON.parse(sessionStorage.getItem(this.memoryKey) || 'null'); } catch (e) { saved = null; }
      if (!saved || typeof saved.t !== 'number') return;
      // Die Sitzung ist neu; ihr Zustand wird hier nachgezogen. Reihenfolge
      // zählt: erst Fahrer und Split, dann die Uhr — sonst springt das
      // Board beim Fokuswechsel wieder auf den zuletzt passierten Split.
      const send = (action, value) =>
        fetch(`/api/playback/${this.token}/control`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, value }),
        });
      if (Number.isInteger(saved.focus)) await send('focus', saved.focus);
      if (saved.mode === 'virtual') await send('mode', 'virtual');
      if (Number.isInteger(saved.split)) await send('split', saved.split);
      if (saved.speed) await send('speed', saved.speed);
      await send('seek', saved.t);
      if (saved.playing) await send('play', true);
    },

    remember() {
      if (!this.frame) return;
      try {
        sessionStorage.setItem(this.memoryKey, JSON.stringify({
          t: this.frame.t_wall,
          speed: this.frame.speed,
          focus: this.frame.focus.entry_id,
          mode: this.frame.mode,
          split: this.frame.board && this.frame.board.split ? this.frame.board.split.idx : null,
          playing: this.frame.playing,
        }));
      } catch (e) { /* privater Modus: dann eben ohne Gedächtnis */ }
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
      // Uhr am Serverwert neu verankern.
      this.clockBase = frame.t_wall;
      this.clockStamp = performance.now();
      this.tickNow = this.clockStamp;
      if (frame.ticker.length) {
        // Stabiler Schlüssel statt laufender Nummer: Der erste Abruf und
        // der erste Frame des Ereignisstroms überlappen sich um ein paar
        // Sekunden, und ohne Schlüssel stünde jeder Start doppelt im
        // Ticker.
        const seen = new Set(this.ticker.map((e) => e.key));
        const fresh = frame.ticker
          .map((e) => ({ ...e, key: `${e.entry_id}|${e.type}|${e.t_s}` }))
          .filter((e) => !seen.has(e.key));
        if (fresh.length) this.ticker = [...fresh.reverse(), ...this.ticker].slice(0, 120);
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
      this.remember();
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

    destroy() {
      if (this.source) this.source.close();
      if (this.raf) cancelAnimationFrame(this.raf);
    },
  };
}

document.addEventListener('alpine:init', () => {
  window.Alpine.data('raceLive', raceLive);
});
