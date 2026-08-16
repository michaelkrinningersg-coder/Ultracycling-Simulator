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

const SPEEDS = [1, 5, 10, 30, 60, 300, 1000];

/* Ereignisgruppen des Tickers.
 *
 * Nicht nach Ereignistyp gefiltert, sondern nach Frage: Ein Zuschauer
 * will „nur die Entscheidungen" sehen oder „nur, wem es schlecht geht" –
 * nicht CONDITION_START von MECHANICAL trennen. Ein Typ, der hier nicht
 * vorkommt, läuft immer mit: Ein neuer Ereignistyp soll nicht dadurch
 * unsichtbar werden, dass jemand vergessen hat, ihn einzutragen.
 */
const TICKER_GROUPS = [
  { key: 'zeit', label: 'Zeiten', types: ['BEST_TIME', 'SPLIT_PASSED'] },
  { key: 'aus', label: 'Ausfälle', types: ['DNF', 'BONK'] },
  { key: 'panne', label: 'Zwischenfälle', types: ['INCIDENT', 'MECHANICAL', 'CONDITION_START', 'CONDITION_END'] },
  { key: 'pause', label: 'Stopps & Schlaf', types: ['SLEEP', 'STOP_START', 'STOP_END'] },
  { key: 'takt', label: 'Taktik', types: ['DECISION', 'BIKE_CHANGE'] },
  { key: 'ziel', label: 'Start & Ziel', types: ['START', 'FINISH'] },
];

const GROUP_OF_TYPE = new Map();
for (const group of TICKER_GROUPS) for (const t of group.types) GROUP_OF_TYPE.set(t, group.key);

/* Wählbare Spalten des Boards.
 *
 * Die feste Hälfte der Tabelle — Rang, Nummer, Fahrer, Team, Zeit,
 * Rückstand — beantwortet „wer liegt wo". Diese hier beantworten die
 * jeweils nächste Frage, und welche das ist, hängt vom Zuschauer ab:
 * In der ersten Nacht ist es der Schlafdruck, am Berg das Tempo, nach
 * 2000 km der Aufgabedruck. Alle gleichzeitig zu zeigen hieße, eine
 * Tabelle mit fünfzehn Zahlenspalten zu bauen, in der man keine liest.
 *
 * ``sort`` ist der Schlüssel, den der Server kennt (``SORT_FIELDS``).
 */
const BOARD_COLUMNS = [
  { key: 'km', label: 'km', hint: 'gefahrene Kilometer' },
  { key: 'biscp', label: 'bis CP', hint: 'Meter bis zur nächsten Zeitmessung' },
  { key: 'trend', label: '±', hint: 'Plätze gewonnen oder verloren seit dem Split davor' },
  { key: 'tempo', label: 'km/h', hint: 'Momentangeschwindigkeit' },
  { key: 'leistung', label: 'W', hint: 'Tretleistung' },
  { key: 'aufgabe', label: 'Aufgabe', hint: 'Aufgabedruck in Prozent der eigenen Grenze' },
  { key: 'form', label: 'Form', hint: 'Leistungsfähigkeit gegenüber frisch, in Prozent' },
  { key: 'wprime', label: 'W′', hint: 'anaerober Vorrat in Prozent' },
  { key: 'glyko', label: 'Glyk', hint: 'Glykogenspeicher in Prozent' },
  { key: 'schlaf', label: 'Schlaf', hint: 'Schlafdruck in Prozent' },
  { key: 'wasser', label: 'Wasser', hint: 'Flüssigkeitshaushalt in Prozent' },
];

//: Was ohne eigene Wahl steht — dieselben zwei Spalten wie bisher.
const DEFAULT_COLUMNS = ['km', 'biscp'];

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
    tickerGroups: TICKER_GROUPS,
    //: Abgewählte Gruppen. Als Liste statt als Set, damit Alpine die
    //: Änderung sieht — Reaktivität geht über Set-Methoden verloren.
    tickerOff: [],
    focusOnly: false,
    allColumns: BOARD_COLUMNS,
    columns: [...DEFAULT_COLUMNS],
    showColumnPicker: false,
    filter: '',
    groupBy: 'keine',
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
    get latest() { return this.visibleTicker.slice(0, 10); },
    get visibleTicker() {
      return this.ticker.filter((e) => {
        if (this.focusOnly && !e.focus) return false;
        const group = GROUP_OF_TYPE.get(e.type);
        return !group || !this.tickerOff.includes(group);
      });
    },
    //: Wie viele Meldungen die Filter gerade wegnehmen — ohne das wirkt
    //: ein leerer Ticker wie ein hängengebliebener Server.
    get tickerHidden() { return this.ticker.length - this.visibleTicker.length; },
    groupOn(key) { return !this.tickerOff.includes(key); },
    toggleGroup(key) {
      this.tickerOff = this.groupOn(key)
        ? [...this.tickerOff, key]
        : this.tickerOff.filter((k) => k !== key);
      this.rememberFilter();
    },
    showAllGroups() { this.tickerOff = []; this.focusOnly = false; this.rememberFilter(); },
    toggleFocusOnly() { this.focusOnly = !this.focusOnly; this.rememberFilter(); },
    //: Der Faktor, der gerade am meisten kostet — die Kurzfassung des
    //: Warum-Panels für die zugeklappte Zeile.
    get worstFactor() {
      const rows = this.focus && this.focus.factors ? this.focus.factors.rows : null;
      return rows && rows.length && rows[0].pct < 99.5 ? rows[0] : null;
    },
    get board() { return this.frame ? this.frame.board : null; },
    get rows() { return this.board ? this.board.rows : []; },
    get pinnedRows() { return this.board && this.board.pinned ? this.board.pinned : []; },
    //: Der Abstand zwischen den beiden angehefteten Fahrern — das
    //: einzige, was ein Duell wirklich ausmacht.
    get pinnedGap() {
      const [a, b] = this.pinnedRows;
      if (!a || !b || a.t_s === null || b.t_s === null) return null;
      return this.rowTime(b) - this.rowTime(a);
    },
    get visibleColumns() {
      return BOARD_COLUMNS.filter((c) => this.columns.includes(c.key));
    },
    //: Die Kopfzeile hat drei feste Spalten links, zwei rechts und
    //: dazwischen die gewählten — plus Zustandschips und Nadel.
    get colSpan() { return 6 + this.visibleColumns.length + 1; },
    get filteredStart() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.startlist;
      return this.startlist.filter(
        (r) => r.name.toLowerCase().includes(q) || r.team.toLowerCase().includes(q) || String(r.bib) === q
      );
    },
    //: Die Startliste gefaltet.
    //:
    //: Dreihundert flache Zeilen mit Textsuche sind kein Verzeichnis,
    //: sondern eine Schriftrolle: Man findet darin nur, wovon man den
    //: Namen schon weiß. Nach Team oder Nation gruppiert beantwortet
    //: sie auch „wer fährt eigentlich für Ortlieb–Cube".
    get startGroups() {
      const rows = this.filteredStart;
      if (this.groupBy === 'keine') return [{ key: '', label: '', rows }];
      const buckets = new Map();
      for (const r of rows) {
        const key = this.groupBy === 'team' ? r.team : r.nation;
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(r);
      }
      return [...buckets.entries()]
        .sort((a, b) => a[0].localeCompare(b[0], 'de'))
        .map(([key, group]) => ({ key, label: key || '—', rows: group }));
    },
    get collapsedGroups() { return this._collapsed || []; },
    groupOpen(key) { return !(this._collapsed || []).includes(key); },
    toggleGroupFold(key) {
      const now = this._collapsed || [];
      this._collapsed = now.includes(key) ? now.filter((k) => k !== key) : [...now, key];
    },
    setGroupBy(mode) { this.groupBy = mode; this._collapsed = []; this.rememberFilter(); },
    _collapsed: [],

    hms, gap,

    //: Laufende Uhren zählen zwischen zwei Frames mit, gemessene
    //: Splitzeiten stehen fest.
    rowTime(row) {
      return row.running ? row.t_s + this.liveDelta : row.t_s;
    },

    //: Meter bis zur nächsten Zeitmessung.
    //:
    //: Unter 10 km in Metern, darüber in Kilometern — 47 000 m liest
    //: niemand, 800 m dagegen genau dann, wenn es darauf ankommt. Wer
    //: im Ziel oder ausgeschieden ist, bekommt einen Strich: Eine 0
    //: wäre in beiden Fällen falsch.
    toNext(row) {
      const m = row && row.to_next_m;
      if (m === null || m === undefined) return '–';
      // Ohne Tausenderpunkt: "1.386 m" ist nach deutscher Schreibweise
      // zwar richtig, liest sich in einer Zahlenspalte neben "25.0 km"
      // aber wie 1,386 Meter. "1386 m" kann man nicht falsch verstehen.
      return m < 10000 ? `${m} m` : `${(m / 1000).toFixed(1)} km`;
    },

    //: Inhalt einer wählbaren Spalte.
    //:
    //: Ein Strich statt einer Null, wo es keinen Wert gibt: „0 %"
    //: behauptet einen Messwert, „–" sagt, dass keiner vorliegt.
    cell(key, row) {
      switch (key) {
        case 'km': return row.dist_km.toFixed(1);
        case 'biscp': return this.toNext(row);
        case 'trend':
          return row.trend > 0 ? `▲${row.trend}` : row.trend < 0 ? `▼${-row.trend}` : '–';
        case 'tempo': return row.v_kmh.toFixed(1);
        case 'leistung': return row.power_w;
        case 'aufgabe': return row.giveup_pct === null ? '–' : `${row.giveup_pct} %`;
        case 'form': return `${row.form_pct} %`;
        case 'wprime': return `${row.wprime_pct} %`;
        case 'glyko': return `${row.glyco_pct} %`;
        case 'schlaf': return `${row.sleep_pct} %`;
        case 'wasser': return `${row.hydration_pct} %`;
        default: return '';
      }
    },

    //: Wann eine Zelle warnt. Dieselben Schwellen wie im Fokuspanel —
    //: eine Zahl darf nicht in zwei Anzeigen unterschiedlich alarmieren.
    cellClass(key, row) {
      switch (key) {
        case 'trend': return row.trend > 0 ? 'neg' : row.trend < 0 ? 'pos' : 'faint';
        case 'aufgabe':
          if (row.giveup_pct === null) return 'faint';
          return row.giveup_pct > 70 ? 'bad' : row.giveup_pct > 40 ? 'warn' : '';
        case 'glyko': return row.glyco_pct < 15 ? 'bad' : row.glyco_pct < 30 ? 'warn' : '';
        case 'schlaf': return row.sleep_pct > 120 ? 'bad' : row.sleep_pct > 60 ? 'warn' : '';
        case 'wasser': return row.hydration_pct < 30 ? 'bad' : row.hydration_pct < 60 ? 'warn' : '';
        default: return '';
      }
    },

    toggleColumn(key) {
      this.columns = this.columns.includes(key)
        ? this.columns.filter((k) => k !== key)
        : [...this.columns, key];
      this.rememberFilter();
    },
    resetColumns() { this.columns = [...DEFAULT_COLUMNS]; this.rememberFilter(); },

    sortBy(key) { this.control('sort', key); },
    sortMark(key) {
      if (!this.frame || this.frame.sort !== key) return '';
      return this.frame.sort_desc ? ' ▾' : ' ▴';
    },
    isPinned(entryId) {
      return !!(this.frame && this.frame.pinned && this.frame.pinned.includes(entryId));
    },
    togglePin(entryId) { this.control('pin', entryId); },

    //: Der Rückstand muss mitzählen wie die Uhr, sonst springt er.
    //:
    //: Er kommt als ``t_s − Bestzeit`` vom Server, und die Bestzeit ist
    //: eine gemessene Splitzeit — sie steht zwischen zwei Frames fest.
    //: Also wächst der Rückstand eines noch fahrenden Verfolgers genau
    //: um dieselbe Sekundenzahl wie seine Uhr, und die steht hier schon
    //: als ``liveDelta``. Ohne das sprang die Spalte im Takt der Frames:
    //: bei 60× einmal je halbe Sekunde um eine halbe Minute.
    rowGap(row) {
      if (row.gap_s === null || row.gap_s === undefined) return null;
      return row.running ? row.gap_s + this.liveDelta : row.gap_s;
    },

    async init() {
      this.restoreFilter();
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
      this.detail = new ProfileView(this.$refs.detail, {
        height: 190, windowM: 40000, eleAxis: true,
      });
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
    //: Die Anzeigefilter gehören dem Betrachter, nicht dem Rennen —
    //: deshalb rennübergreifend und in ``localStorage``: Wer den Ticker
    //: einmal auf „nur Ausfälle" gestellt hat, will das beim nächsten
    //: Rennen wieder so vorfinden.
    filterKey: 'ultrasim:ticker',

    restoreFilter() {
      try {
        const saved = JSON.parse(localStorage.getItem(this.filterKey) || 'null');
        if (!saved) return;
        if (Array.isArray(saved.off)) this.tickerOff = saved.off;
        if (Array.isArray(saved.columns)) {
          // Gegen die bekannten Spalten filtern: Ein gespeicherter
          // Schlüssel, den es nicht mehr gibt, würde sonst eine leere
          // Spalte in die Tabelle setzen.
          this.columns = saved.columns.filter((k) => BOARD_COLUMNS.some((c) => c.key === k));
        }
        if (typeof saved.groupBy === 'string') this.groupBy = saved.groupBy;
        this.focusOnly = !!saved.focusOnly;
      } catch (e) { /* dann eben ungefiltert */ }
    },

    rememberFilter() {
      try {
        localStorage.setItem(this.filterKey, JSON.stringify({
          off: this.tickerOff,
          focusOnly: this.focusOnly,
          columns: this.columns,
          groupBy: this.groupBy,
        }));
      } catch (e) { /* privater Modus */ }
    },

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

    send(action, value) {
      return fetch(`/api/playback/${this.token}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
    },

    async control(action, value) {
      const res = await this.send(action, value);
      if (res.ok) await this.refresh();
    },

    //: Klick auf eine Tickermeldung: hinschauen, wo sie passiert ist.
    //:
    //: Erst der Fahrer, dann die Uhr — in der anderen Reihenfolge zöge
    //: das Board beim Fokuswechsel wieder auf den zuletzt passierten
    //: Split des neuen Fahrers. Und angehalten wird dabei: Bei 1000×
    //: wäre der Moment, zu dem man springt, im nächsten Bild schon eine
    //: Viertelstunde her.
    async jumpTo(event) {
      const rider = this.startlist.find((r) => r.entry_id === event.entry_id);
      if (!rider) return;
      await this.send('focus', event.entry_id);
      await this.send('pause');
      await this.control('seek', rider.start_offset_s + event.t_s);
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
