/* Studio-Tool: Kernfunktionen (API, Router, Formatierung), Startseite und Sicherheit. Weitere Seiten: pages.js */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const App = { me: null, pages: {} };

/* ---------- API ---------- */
async function api(path, method = 'GET', body) {
  const opt = { method, headers: { 'X-Studio': '1' } };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch('/api/' + path, opt);
  if (r.status === 401) { location.href = '/login'; throw new Error('Nicht angemeldet'); }
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error((data && data.error) || 'Fehler ' + r.status);
  return data;
}

/* ---------- Formatierung: Euro aus Cent, Datum TT.MM.JJJJ ---------- */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function euro(cent) {
  const c = Math.round(Number(cent) || 0);
  const sign = c < 0 ? '-' : '';
  const abs = Math.abs(c);
  const e = Math.floor(abs / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return `${sign}${e},${String(abs % 100).padStart(2, '0')} €`;
}
function datum(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${m[3]}.${m[2]}.${m[1]}` : '';
}
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), 3000);
}

/* ---------- Navigation ---------- */
const TITLES = {
  start: 'Start', auftraege: 'Aufträge und Spiele', kunden: 'Kunden', zahlungen: 'Zahlungen', lieferung: 'Bildauslieferung',
  vertraege: 'Verträge und Dokumente', mail: 'Mail', kalender: 'Kalender', aufgaben: 'Aufgaben', einstellungen: 'Einstellungen',
  sicherheit: 'Sicherheit',
};
const ICONS = {
  start: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
  auftraege: '<rect x="3" y="7" width="18" height="13" rx="2"/><circle cx="12" cy="13.5" r="3.5"/><path d="M8 7l1.5-3h5L16 7"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
  kalender: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/>',
  aufgaben: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M3.5 6l1.5 1.5L7.5 5M3.5 12l1.5 1.5 2.5-2.5M3.5 18l1.5 1.5 2.5-2.5"/>',
  mehr: '<path d="M4 7h16M4 12h16M4 17h16"/>',
};
const TABS = ['start', 'auftraege', 'mail', 'kalender', 'aufgaben'];
const TAB_LABELS = { start: 'Start', auftraege: 'Aufträge', mail: 'Mail', kalender: 'Kalender', aufgaben: 'Aufgaben' };
const icon = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[k]}</svg>`;

function renderTabbar() {
  $('#tabbar').innerHTML = TABS.map(t => `<a href="#/${t === 'start' ? '' : t}" data-tab="${t}">${icon(t)}<span>${TAB_LABELS[t]}</span></a>`).join('')
    + `<button type="button" id="tabMore">${icon('mehr')}<span>Mehr</span></button>`;
  $('#tabMore').addEventListener('click', () => document.body.classList.toggle('nav-open'));
}

async function router() {
  const name = location.hash.replace(/^#\/?/, '').split('/')[0] || 'start';
  let page = App.pages[name] ? name : 'start';
  // Zwei-Faktor ist Pflicht, aber noch nicht eingerichtet: nur die Seite Sicherheit
  if (App.me.must_2fa && page !== 'sicherheit') { location.hash = '#/sicherheit'; return; }
  document.body.classList.remove('nav-open');
  $$('#nav a').forEach(a => a.classList.toggle('active', a.dataset.page === page));
  $$('#tabbar [data-tab]').forEach(a => a.classList.toggle('active', a.dataset.tab === page));
  $('#topTitle').textContent = TITLES[page];
  document.title = TITLES[page] + ' · Studio-Tool';
  const view = $('#view');
  view.innerHTML = '<p class="muted">Lädt ...</p>';
  try {
    await App.pages[page](view);
  } catch (e) {
    view.innerHTML = `<div class="card"><b>Fehler</b><p>${esc(e.message)}</p></div>`;
  }
  $('#main').scrollTop = 0;
}

function head(title, sub) {
  return `<div class="page-head"><h1>${esc(title)}${sub ? `<small>${esc(sub)}</small>` : ''}</h1></div>`;
}

/* Seiten, die in späteren Phasen gebaut werden */
const LATER = {
  zahlungen: [3, 'Zahlstatus, Zahler, Finom-Häkchen mit Rechnungsnummer, Umsatz und CSV-Export.'],
  lieferung: [4, 'Galerie-Links mit Ablaufdatum, Lieferfrist-Ampel und Nachrichtenvorlagen.'],
  vertraege: [5, 'Verträge mit Fristen, PDF-Upload und geschütztem Download.'],
  mail: [9, 'Postfach wie im Emden Tigers Hub, mit mehreren Konten.'],
  kalender: [6, 'Kalenderansicht und ICS-Abo, eigene Termine ab Phase 8.'],
  aufgaben: [8, 'Aufgaben mit Fälligkeit, Vorlagen je Paket und Erinnerungen.'],
};
Object.entries(LATER).forEach(([key, [phase, text]]) => {
  App.pages[key] = async (view) => {
    view.innerHTML = head(TITLES[key]) + `<div class="card empty"><span class="badge">Phase ${phase}</span><p>${esc(text)}</p>
      <p class="muted small">Dieser Bereich wird in Phase ${phase} gebaut.</p></div>`;
  };
});

App.pages.start = async (view) => {
  const [pakete, s] = await Promise.all([api('pakete'), api('einstellungen')]);
  const heute = new Date();
  const iso = `${heute.getFullYear()}-${String(heute.getMonth() + 1).padStart(2, '0')}-${String(heute.getDate()).padStart(2, '0')}`;
  view.innerHTML = head('Hallo ' + (App.me.display_name || App.me.username), 'Heute ist der ' + datum(iso))
    + `<div class="grid g2">
      <div class="card"><h2>Stand</h2>
        <p>Phase 2 ist eingerichtet: Kunden, Kontakte und Aufträge mit Preisberechnung.</p>
        <p class="muted small">Termine, Lieferungen, offene Zahlungen und Umsatz erscheinen hier ab Phase 6.</p></div>
      <div class="card"><h2>Pakete</h2>${paketTabelle(pakete)}
        <p class="muted small">Anfahrt: ${esc(s.anfahrt_frei_km)} km frei, danach ${euro(s.anfahrt_cent_je_km)} je km.</p></div>
    </div>`;
};

function paketTabelle(pakete) {
  if (!pakete.length) return '<p class="muted">Noch keine Pakete.</p>';
  return `<table class="tbl"><thead><tr><th>Paket</th><th class="num">Preis</th><th>Zusatz</th></tr></thead><tbody>`
    + pakete.map(p => `<tr${p.aktiv ? '' : ' class="muted"'}><td>${esc(p.name)}</td><td class="num">${euro(p.grundpreis_cent)}</td>
      <td class="small">${p.inkl_spieler ? `bis ${p.inkl_spieler} Spieler, jeder weitere ${euro(p.zusatzspieler_cent)}` : ''}</td></tr>`).join('')
    + '</tbody></table>';
}

/* ---------- Sicherheit: Zwei-Faktor-Anmeldung (wie im Hub) ---------- */
App.pages.sicherheit = async (view) => {
  view.innerHTML = head('Sicherheit', 'Anmeldung mit Passwort und Code aus der App') + '<div class="card" id="tfCard"></div>';
  await twofaCard($('#tfCard'));
};

function pwField() {
  return `<input type="text" autocomplete="username" value="${esc(App.me.username)}" hidden>
    <div class="field"><label for="tf_pw">Dein Passwort zur Bestätigung</label>
    <input class="input" type="password" id="tf_pw" autocomplete="current-password"></div>`;
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Kopiert'); } catch (e) { toast('Kopieren nicht möglich, bitte von Hand markieren'); }
}

async function twofaCard(box) {
  const st = await api('me/2fa');
  const showCodes = codes => {
    box.innerHTML = `<h2>Wiederherstellungscodes</h2>
      <p class="warnline">Speichere diese Codes jetzt, zum Beispiel im Passwort-Manager oder ausgedruckt. Sie werden nur dieses eine Mal angezeigt.
        Jeder Code funktioniert genau einmal, falls du dein Handy nicht zur Hand hast.</p>
      <pre class="codes">${codes.map(esc).join('\n')}</pre>
      <div class="btn-row"><button class="btn" id="tf_copy">Codes kopieren</button><button class="btn primary" id="tf_done">Gespeichert, weiter</button></div>`;
    $('#tf_copy', box).addEventListener('click', () => copyText(codes.join('\n')));
    $('#tf_done', box).addEventListener('click', async () => {
      App.me = (await api('me')).user;
      if (location.hash === '#/sicherheit') twofaCard(box); else location.hash = '#/sicherheit';
    });
  };
  if (!st.enabled) {
    box.innerHTML = `<h2>Zwei-Faktor-Anmeldung</h2>
      ${st.required ? '<p class="warnline"><b>Die Zwei-Faktor-Anmeldung ist Pflicht.</b> Bis sie eingerichtet ist, ist nur diese Seite erreichbar.</p>' : ''}
      <p class="muted">Schützt das Studio-Tool, auch wenn jemand dein Passwort kennt: Bei der Anmeldung kommt zusätzlich ein Code aus einer
        Authenticator-App dazu, zum Beispiel die Passwörter-App am iPhone, Google Authenticator, Microsoft Authenticator oder 2FAS.</p>
      <form id="tf_form">${pwField()}<button class="btn primary">Einrichten</button></form>`;
    $('#tf_form', box).addEventListener('submit', async (ev) => {
      ev.preventDefault();
      let s;
      try { s = await api('me/2fa/setup', 'POST', { password: $('#tf_pw', box).value }); } catch (e) { return toast(e.message); }
      const qr = window.qrSvg ? window.qrSvg(s.uri, 220) : null;
      const grouped = s.secret.match(/.{1,4}/g).join(' ');
      box.innerHTML = `<h2>Zwei-Faktor-Anmeldung einrichten</h2>
        <ol class="steps">
          <li>Authenticator-App auf dem Handy öffnen.</li>
          ${qr ? `<li>In der App "QR-Code scannen" wählen und diesen Code scannen:<div class="qr">${qr}</div>
            <span class="muted small">Der QR-Code entsteht hier im Browser und enthält deinen geheimen Schlüssel. Nicht abfotografieren oder weitergeben.</span></li>` : ''}
          <li>${qr ? 'Oder direkt am iPhone' : 'Am Handy'}: <a class="btn sm" href="${esc(s.uri)}">In der App öffnen</a><br>
            Sonst in der App "Schlüssel eingeben" wählen:<br>
            Konto: <b>${esc(s.issuer)} (${esc(s.account)})</b><br>
            Schlüssel: <code class="secret">${esc(grouped)}</code> <button type="button" class="btn sm" id="tf_cp">Kopieren</button><br>
            <span class="muted small">zeitbasiert, 6 Ziffern, 30 Sekunden</span></li>
          <li>Den 6-stelligen Code aus der App hier eingeben:</li>
        </ol>
        <form id="tf_form2"><div class="field"><label for="tf_code">Code aus der App</label>
          <input class="input" id="tf_code" inputmode="numeric" autocomplete="one-time-code" maxlength="7"></div>
          <div class="btn-row"><button type="button" class="btn" id="tf_cancel">Abbrechen</button><button class="btn primary">Bestätigen und einschalten</button></div></form>`;
      $('#tf_cp', box).addEventListener('click', () => copyText(s.secret));
      $('#tf_cancel', box).addEventListener('click', () => twofaCard(box));
      $('#tf_code', box).focus();
      $('#tf_form2', box).addEventListener('submit', async (ev2) => {
        ev2.preventDefault();
        try {
          const r = await api('me/2fa/enable', 'POST', { code: $('#tf_code', box).value });
          toast('Zwei-Faktor-Anmeldung ist eingeschaltet');
          showCodes(r.codes);
        } catch (e) { toast(e.message); }
      });
    });
    return;
  }
  const wenig = st.recovery_left <= 2;
  box.innerHTML = `<h2>Zwei-Faktor-Anmeldung <span class="badge ok">eingeschaltet</span></h2>
    <p class="muted">Bei der Anmeldung fragt das Studio-Tool nach dem Code aus deiner Authenticator-App.
      ${st.enabled_at ? 'Eingerichtet am ' + datum(st.enabled_at) + '.' : ''}</p>
    <p class="${wenig ? 'warnline' : 'muted small'}">Übrige Wiederherstellungscodes: <b>${st.recovery_left}</b>${wenig ? '. Erzeuge bitte neue.' : ''}</p>
    <form id="tf_form">${pwField()}<button class="btn">Neue Wiederherstellungscodes</button></form>
    <p class="muted small">Handy verloren und keine Codes mehr? Dann auf dem Server
      <code>python server.py 2fa-reset ${esc(App.me.username)}</code> ausführen (im Container), danach neu einrichten.</p>`;
  $('#tf_form', box).addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!confirm('Neue Wiederherstellungscodes erzeugen? Die bisherigen gelten danach nicht mehr.')) return;
    try { const r = await api('me/2fa/recovery', 'POST', { password: $('#tf_pw', box).value }); showCodes(r.codes); } catch (e) { toast(e.message); }
  });
}

/* ---------- Start ---------- */
async function boot() {
  try {
    const info = await api('me');
    App.me = info.user;
  } catch (e) { return; }
  $('#whoami').textContent = App.me.display_name || App.me.username;
  $('#logoutBtn').addEventListener('click', async () => {
    await fetch('/auth/logout', { method: 'POST', headers: { 'X-Studio': '1' } });
    location.href = '/login';
  });
  $('#navShade').addEventListener('click', () => document.body.classList.remove('nav-open'));
  renderTabbar();
  window.addEventListener('hashchange', router);
  router();
}
boot();
