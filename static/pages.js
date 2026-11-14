/* Studio-Tool: Seiten ab Phase 2 (Kunden, Aufträge, Einstellungen) und der Bearbeiten-Dialog (wie editRecord im Hub) */

/* ---------- Geld eingeben: "67,20" <-> 6720 Cent ---------- */
function centVon(text) {
  const t = String(text ?? '').replace(/[\s€]/g, '');
  if (t === '') return '';
  const m = /^(\d{1,7})(?:[.,](\d{1,2}))?$/.exec(t);
  if (!m) throw new Error('Betrag bitte in der Form 12,34 eingeben.');
  return Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0'));
}
function euroEingabe(cent) {
  return cent === '' || cent == null ? '' : euro(cent).replace(' €', '').replace(/\./g, '');
}

/* ---------- Formularfelder ----------
   Feld: { key, label, type: text|number|euro|date|time|email|select|textarea|check, options: [[wert, text]], required, full, list, def } */
function fieldHtml(f, val) {
  const id = 'f_' + f.key;
  const req = f.required ? ' required' : '';
  const v = val ?? '';
  if (f.type === 'check') {
    return `<div class="field${f.full ? ' full' : ''}"><label class="check"><input type="checkbox" id="${id}" name="${f.key}"${Number(v) ? ' checked' : ''}> ${esc(f.label)}</label></div>`;
  }
  let input;
  if (f.type === 'select') {
    input = `<select class="input" id="${id}" name="${f.key}"${req}>` + f.options.map(([w, t]) =>
      `<option value="${esc(w)}"${String(w) === String(v) ? ' selected' : ''}>${esc(t)}</option>`).join('') + '</select>';
  } else if (f.type === 'textarea') {
    input = `<textarea class="input" id="${id}" name="${f.key}" rows="3">${esc(v)}</textarea>`;
  } else if (f.type === 'euro') {
    input = `<input class="input" id="${id}" name="${f.key}" inputmode="decimal" value="${esc(euroEingabe(v))}" placeholder="0,00"${req}>`;
  } else if (f.type === 'number') {
    input = `<input class="input" id="${id}" name="${f.key}" type="number" min="0" step="1" inputmode="numeric" value="${esc(v)}"${req}>`;
  } else {
    const list = f.list ? ` list="${id}_l"` : '';
    input = `<input class="input" id="${id}" name="${f.key}" type="${f.type || 'text'}" value="${esc(v)}"${list}${req}>`
      + (f.list ? `<datalist id="${id}_l">${f.list.map(x => `<option value="${esc(x)}">`).join('')}</datalist>` : '');
  }
  return `<div class="field${f.full ? ' full' : ''}"><label for="${id}">${esc(f.label)}</label>${input}</div>`;
}

function readForm(form, fields) {
  const out = {};
  for (const f of fields) {
    const el = form.elements[f.key];
    out[f.key] = f.type === 'check' ? (el.checked ? 1 : 0) : f.type === 'euro' ? centVon(el.value) : el.value.trim();
  }
  return out;
}

/* Dialog zum Anlegen und Bearbeiten. opts: fix (feste Werte), extra (HTML unter den Feldern), bind(form) */
function editRecord(table, title, fields, rec = {}, opts = {}) {
  const dlg = $('#modal');
  const archivierbar = rec.id && 'archiviert' in rec;
  dlg.innerHTML = `<form class="modal-box"><h2>${esc(title)}</h2>
    <div class="form-grid">${fields.map(f => fieldHtml(f, rec[f.key] ?? f.def)).join('')}</div>${opts.extra || ''}
    <div class="modal-foot"><span class="btn-row">
      ${rec.id ? '<button type="button" class="btn danger" data-act="del">Löschen</button>' : ''}
      ${archivierbar ? `<button type="button" class="btn" data-act="arch">${rec.archiviert ? 'Wiederherstellen' : 'Archivieren'}</button>` : ''}
    </span><span class="btn-row"><button type="button" class="btn" data-act="close">Abbrechen</button>
      <button class="btn primary">Speichern</button></span></div></form>`;
  const form = $('form', dlg);
  const fertig = (msg) => { dlg.close(); toast(msg); router(); };
  const url = table + (rec.id ? '/' + rec.id : '');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await api(url, rec.id ? 'PUT' : 'POST', { ...readForm(form, fields), ...(opts.fix || {}) });
      fertig('Gespeichert');
    } catch (e) { toast(e.message); }
  });
  form.addEventListener('click', async (ev) => {
    const act = ev.target.dataset.act;
    if (act === 'close') return dlg.close();
    try {
      if (act === 'arch') { await api(url, 'PUT', { archiviert: rec.archiviert ? 0 : 1 }); fertig(rec.archiviert ? 'Wiederhergestellt' : 'Archiviert'); }
      if (act === 'del' && confirm('Diesen Eintrag endgültig löschen? Das lässt sich nicht rückgängig machen.')) {
        await api(url, 'DELETE');
        fertig('Gelöscht');
      }
    } catch (e) { toast(e.message); }
  });
  if (opts.bind) opts.bind(form);
  dlg.showModal();
}

/* Filter bleiben beim Neuzeichnen einer Seite erhalten */
const Filter = { kSuche: '', kArchiv: false, aKunde: '', aStatus: '', aVon: '', aBis: '', aArchiv: false };
const STATUS_AUFTRAG = ['Angefragt', 'Bestätigt', 'Fotografiert', 'Geliefert', 'Abgeschlossen', 'Abgesagt'];
const KUNDEN_TYPEN = ['Verein', 'Sparte', 'Einzelperson'];
const byId = (list, id) => list.find(x => x.id == id);

/* ---------- Kunden ---------- */
App.pages.kunden = async (view) => {
  const [kunden, kontakte, auftraege] = await Promise.all([api('kunden'), api('kontakte'), api('auftraege')]);
  const kundeFelder = (k) => [
    { key: 'name', label: 'Name', required: true, full: true },
    { key: 'typ', label: 'Typ', type: 'select', options: KUNDEN_TYPEN.map(t => [t, t]), def: 'Verein' },
    { key: 'parent_id', label: 'Gehört zu (bei Sparten)', type: 'select',
      options: [['', 'niemandem']].concat(kunden.filter(x => !x.parent_id && x.id !== k.id).map(x => [x.id, x.name])) },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  const kontaktFelder = [
    { key: 'name', label: 'Name', required: true },
    { key: 'rolle', label: 'Rolle (zum Beispiel Trainer, Zahler)' },
    { key: 'telefon', label: 'Telefon', type: 'tel' },
    { key: 'email', label: 'E-Mail', type: 'email' },
    { key: 'instagram', label: 'Instagram' },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  view.innerHTML = head('Kunden', 'Vereine, Sparten und Einzelpersonen mit Ansprechpersonen')
    + `<div class="toolbar"><button class="btn primary" id="kNeu">Kunde anlegen</button>
      <input class="input" id="kSuche" type="search" placeholder="Suchen" aria-label="Kunden suchen" value="${esc(Filter.kSuche)}">
      <label class="check"><input type="checkbox" id="kArchiv"${Filter.kArchiv ? ' checked' : ''}> Archivierte zeigen</label></div>
      <div class="grid" id="kListe"></div>`;
  const draw = () => {
    const q = Filter.kSuche.toLowerCase();
    const passt = k => (Filter.kArchiv || !k.archiviert) && (!q || k.name.toLowerCase().includes(q)
      || kontakte.some(c => c.kunde_id === k.id && (c.name || '').toLowerCase().includes(q)));
    const liste = kunden.filter(passt);
    $('#kListe').innerHTML = liste.length ? liste.map(k => {
      const eltern = k.parent_id ? byId(kunden, k.parent_id) : null;
      const n = auftraege.filter(a => a.kunde_id === k.id).length;
      const ks = kontakte.filter(c => c.kunde_id === k.id);
      return `<div class="card${k.archiviert ? ' muted' : ''}">
        <div class="row-head"><button type="button" class="linkbtn" data-kunde="${k.id}"><b>${esc(k.name)}</b></button>
          <span class="badge plain">${esc(k.typ)}</span>${k.archiviert ? '<span class="badge warn">archiviert</span>' : ''}
          <span class="muted small">${eltern ? 'gehört zu ' + esc(eltern.name) + ' · ' : ''}${n} ${n === 1 ? 'Auftrag' : 'Aufträge'}</span></div>
        ${k.notizen ? `<p class="small pre">${esc(k.notizen)}</p>` : ''}
        <ul class="kontakte">${ks.map(c => `<li><button type="button" class="linkbtn" data-kontakt="${c.id}">${esc(c.name)}</button>
          <span class="muted small">${[c.rolle, c.telefon, c.email, c.instagram].filter(Boolean).map(esc).join(' · ')}</span></li>`).join('')}</ul>
        <button type="button" class="btn sm" data-kontakt-neu="${k.id}">Kontakt hinzufügen</button></div>`;
    }).join('') : `<div class="card"><p class="muted">${kunden.length ? 'Kein Kunde passt zur Suche.' : 'Noch keine Kunden. Lege den ersten an.'}</p></div>`;
  };
  draw();
  $('#kNeu').addEventListener('click', () => editRecord('kunden', 'Kunde anlegen', kundeFelder({})));
  $('#kSuche').addEventListener('input', (ev) => { Filter.kSuche = ev.target.value; draw(); });
  $('#kArchiv').addEventListener('change', (ev) => { Filter.kArchiv = ev.target.checked; draw(); });
  $('#kListe').addEventListener('click', (ev) => {
    const d = ev.target.closest('button')?.dataset || {};
    if (d.kunde) { const k = byId(kunden, d.kunde); editRecord('kunden', 'Kunde bearbeiten', kundeFelder(k), k); }
    if (d.kontakt) editRecord('kontakte', 'Kontakt bearbeiten', kontaktFelder, byId(kontakte, d.kontakt));
    if (d.kontaktNeu) editRecord('kontakte', 'Kontakt für ' + byId(kunden, d.kontaktNeu).name, kontaktFelder, {}, { fix: { kunde_id: Number(d.kontaktNeu) } });
  });
};

/* ---------- Aufträge ---------- */
App.pages.auftraege = async (view) => {
  const [auftraege, kunden, pakete] = await Promise.all([api('auftraege'), api('kunden'), api('pakete')]);
  const sportarten = [...new Set(auftraege.map(a => a.sportart).filter(Boolean))].sort();

  const felder = (a) => [
    { key: 'kunde_id', label: 'Kunde', type: 'select', required: true,
      options: [['', 'bitte wählen']].concat(kunden.filter(k => !k.archiviert || k.id === a.kunde_id).map(k => [k.id, k.name])) },
    { key: 'paket_id', label: 'Paket', type: 'select', required: true,
      options: [['', 'bitte wählen']].concat(pakete.filter(p => p.aktiv || p.id === a.paket_id).map(p => [p.id, `${p.name} (${euro(p.grundpreis_cent)})`])) },
    { key: 'datum', label: 'Datum', type: 'date', required: true },
    { key: 'uhrzeit', label: 'Uhrzeit', type: 'time' },
    { key: 'begegnung', label: 'Begegnung oder Anlass', full: true },
    { key: 'ort', label: 'Ort' },
    { key: 'sportart', label: 'Sportart', list: sportarten },
    { key: 'spieler', label: 'Anzahl Spieler (für Spielershooting)', type: 'number' },
    { key: 'km', label: 'Kilometer, einfache Strecke ab Emden', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', options: STATUS_AUFTRAG.map(s => [s, s]), def: 'Angefragt' },
    { key: 'betrag_manuell', label: 'Betrag von Hand festlegen', type: 'check' },
    { key: 'betrag_cent', label: 'Betrag in Euro', type: 'euro' },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];

  // Preis im Formular: rechnet der Server (eine Stelle für die Preislogik), gespeichert wird dabei nichts
  const preisBinden = (a) => (form) => {
    const box = $('#preisBox', form);
    const el = form.elements;
    let timer;
    const rechnen = async () => {
      el.betrag_cent.disabled = !el.betrag_manuell.checked;
      if (!el.paket_id.value) { box.textContent = 'Wähle ein Paket, dann erscheint hier der Preis.'; return; }
      try {
        const p = await api('auftraege/vorschau', 'POST', { id: a.id, paket_id: el.paket_id.value, spieler: el.spieler.value, km: el.km.value });
        const teile = ['Paket ' + euro(p.grundpreis_cent)];
        if (p.zusatzspieler_cent) teile.push(`Zusatzspieler ${euro(p.zusatzspieler_cent)}`);
        if (p.anfahrt_cent) teile.push(`Anfahrt ${euro(p.anfahrt_cent)}`);
        box.textContent = (el.betrag_manuell.checked ? 'Berechnet wären: ' : 'Betrag: ') + teile.join(' + ') + ' = ' + euro(p.berechnet_cent);
        if (!el.betrag_manuell.checked) el.betrag_cent.value = euroEingabe(p.berechnet_cent);
      } catch (e) { box.textContent = e.message; }
    };
    ['paket_id', 'spieler', 'km', 'betrag_manuell'].forEach(k => el[k].addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(rechnen, 250); }));
    rechnen();
  };
  const oeffnen = (a) => editRecord('auftraege', a.id ? 'Auftrag bearbeiten' : 'Auftrag anlegen', felder(a), a,
    { extra: `<p class="preisbox" id="preisBox" role="status"></p>${a.lieferfrist ? `<p class="muted small">Lieferfrist: ${datum(a.lieferfrist)}</p>` : ''}`, bind: preisBinden(a) });

  view.innerHTML = head('Aufträge und Spiele')
    + `<div class="toolbar"><button class="btn primary" id="aNeu">Auftrag anlegen</button>
      <select class="input" id="aKunde" aria-label="Kunde"><option value="">Alle Kunden</option>${kunden.map(k => `<option value="${k.id}"${String(k.id) === Filter.aKunde ? ' selected' : ''}>${esc(k.name)}</option>`).join('')}</select>
      <select class="input" id="aStatus" aria-label="Status"><option value="">Jeder Status</option>${STATUS_AUFTRAG.map(s => `<option${s === Filter.aStatus ? ' selected' : ''}>${s}</option>`).join('')}</select>
      <label class="check">von <input class="input" type="date" id="aVon" value="${esc(Filter.aVon)}"></label>
      <label class="check">bis <input class="input" type="date" id="aBis" value="${esc(Filter.aBis)}"></label>
      <label class="check"><input type="checkbox" id="aArchiv"${Filter.aArchiv ? ' checked' : ''}> Archivierte zeigen</label></div>
      <div class="card" id="aListe"></div>`;
  const draw = () => {
    const liste = auftraege.filter(a => (Filter.aArchiv || !a.archiviert) && (!Filter.aKunde || String(a.kunde_id) === Filter.aKunde)
      && (!Filter.aStatus || a.status === Filter.aStatus) && (!Filter.aVon || a.datum >= Filter.aVon) && (!Filter.aBis || a.datum <= Filter.aBis));
    if (!liste.length) {
      $('#aListe').innerHTML = `<p class="muted">${auftraege.length ? 'Kein Auftrag passt zum Filter.' : 'Noch keine Aufträge. Lege zuerst einen Kunden an, dann den ersten Auftrag.'}</p>`;
      return;
    }
    const summe = liste.filter(a => a.status !== 'Abgesagt').reduce((s, a) => s + a.betrag_cent, 0);
    $('#aListe').innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Datum</th><th>Begegnung</th><th>Kunde</th><th>Paket</th><th>Status</th><th class="num">Betrag</th></tr></thead><tbody>`
      + liste.map(a => `<tr${a.archiviert || a.status === 'Abgesagt' ? ' class="muted"' : ''}>
        <td class="nowrap">${datum(a.datum)}${a.uhrzeit ? `<br><span class="muted small">${esc(a.uhrzeit)} Uhr</span>` : ''}</td>
        <td><button type="button" class="linkbtn" data-auftrag="${a.id}"><b>${esc(a.begegnung || 'ohne Titel')}</b></button>
          ${a.ort || a.sportart ? `<br><span class="muted small">${[a.sportart, a.ort].filter(Boolean).map(esc).join(' · ')}</span>` : ''}</td>
        <td>${esc(byId(kunden, a.kunde_id)?.name || '')}</td><td>${esc(byId(pakete, a.paket_id)?.name || '')}</td>
        <td><select class="input sm" data-status="${a.id}" aria-label="Status ändern">${STATUS_AUFTRAG.map(s => `<option${s === a.status ? ' selected' : ''}>${s}</option>`).join('')}</select></td>
        <td class="num">${euro(a.betrag_cent)}${a.betrag_manuell ? '<br><span class="muted small">von Hand</span>' : ''}</td></tr>`).join('')
      + `</tbody></table></div><p class="muted small">${liste.length} ${liste.length === 1 ? 'Auftrag' : 'Aufträge'}, Summe ohne abgesagte: <b>${euro(summe)}</b></p>`;
  };
  draw();
  $('#aNeu').addEventListener('click', () => oeffnen({}));
  [['aKunde', 'aKunde'], ['aStatus', 'aStatus'], ['aVon', 'aVon'], ['aBis', 'aBis']].forEach(([id, key]) =>
    $('#' + id).addEventListener('change', (ev) => { Filter[key] = ev.target.value; draw(); }));
  $('#aArchiv').addEventListener('change', (ev) => { Filter.aArchiv = ev.target.checked; draw(); });
  $('#aListe').addEventListener('click', (ev) => {
    const id = ev.target.closest('button')?.dataset.auftrag;
    if (id) oeffnen(byId(auftraege, id));
  });
  $('#aListe').addEventListener('change', async (ev) => {
    const id = ev.target.dataset.status;
    if (!id) return;
    try {
      Object.assign(byId(auftraege, id), await api('auftraege/' + id, 'PUT', { status: ev.target.value }));
      toast('Status: ' + ev.target.value);
    } catch (e) { toast(e.message); }
    draw();
  });
};

/* ---------- Einstellungen: Pakete und Werte ---------- */
App.pages.einstellungen = async (view) => {
  const [pakete, s] = await Promise.all([api('pakete'), api('einstellungen')]);
  const paketFelder = [
    { key: 'name', label: 'Name', required: true, full: true },
    { key: 'grundpreis_cent', label: 'Grundpreis in Euro', type: 'euro', required: true },
    { key: 'sort', label: 'Reihenfolge', type: 'number' },
    { key: 'inkl_spieler', label: 'Spieler inklusive (0 = ohne Staffel)', type: 'number' },
    { key: 'zusatzspieler_cent', label: 'Preis je weiterem Spieler in Euro', type: 'euro' },
    { key: 'finom_text', label: 'Leistungstext für die Rechnung in Finom', type: 'textarea', full: true },
    { key: 'aktiv', label: 'Aktiv (für neue Aufträge wählbar)', type: 'check', def: 1 },
  ];
  const werte = [
    { key: 'anfahrt_frei_km', label: 'Anfahrt frei bis (km)', type: 'number', required: true },
    { key: 'anfahrt_cent_je_km', label: 'Preis je weiterem km in Euro', type: 'euro', required: true },
    { key: 'lieferfrist_tage', label: 'Lieferfrist nach dem Spiel (Tage)', type: 'number', required: true },
    { key: 'picdrop_tage', label: 'Picdrop-Laufzeit (Tage)', type: 'number', required: true },
    { key: 'umsatzgrenze_cent', label: 'Umsatzgrenze in Euro (leer = noch offen)', type: 'euro' },
  ];
  view.innerHTML = head('Einstellungen', 'Preisänderungen gelten nur für neue Aufträge, bestehende behalten ihre Preise')
    + `<div class="grid g2">
      <div class="card"><h2>Pakete</h2><table class="tbl" id="pListe"><thead><tr><th>Paket</th><th class="num">Preis</th><th>Zusatz</th></tr></thead><tbody>
        ${pakete.map(p => `<tr${p.aktiv ? '' : ' class="muted"'}><td><button type="button" class="linkbtn" data-paket="${p.id}"><b>${esc(p.name)}</b></button>${p.aktiv ? '' : ' (inaktiv)'}</td>
          <td class="num">${euro(p.grundpreis_cent)}</td>
          <td class="small">${p.inkl_spieler ? `bis ${p.inkl_spieler} Spieler, jeder weitere ${euro(p.zusatzspieler_cent)}` : ''}</td></tr>`).join('')}
        </tbody></table><button type="button" class="btn sm" id="pNeu">Paket hinzufügen</button></div>
      <div class="card"><h2>Werte</h2><form id="werteForm">${werte.map(f => fieldHtml(f, s[f.key])).join('')}
        <button class="btn primary">Speichern</button></form></div>
    </div>`;
  $('#pNeu').addEventListener('click', () => editRecord('pakete', 'Paket hinzufügen', paketFelder));
  $('#pListe').addEventListener('click', (ev) => {
    const id = ev.target.closest('button')?.dataset.paket;
    if (id) editRecord('pakete', 'Paket bearbeiten', paketFelder, byId(pakete, id));
  });
  $('#werteForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await api('einstellungen', 'PUT', readForm(ev.target, werte));
      toast('Gespeichert');
    } catch (e) { toast(e.message); }
  });
};
