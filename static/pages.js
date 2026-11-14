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
  if (f.type === 'file') {
    return `<div class="field${f.full ? ' full' : ''}"><label for="${id}">${esc(f.label)}</label>
      <input class="input" id="${id}" name="${f.key}" type="file" accept="${esc(f.accept || '')}">${v ? `<span class="muted small">Vorhanden: ${esc(v)}. Eine neue Datei ersetzt sie.</span>` : ''}</div>`;
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
    if (f.type === 'file') continue;   // Dateien lädt editRecord nach dem Speichern hoch
    const el = form.elements[f.key];
    out[f.key] = f.type === 'check' ? (el.checked ? 1 : 0) : f.type === 'euro' ? centVon(el.value) : el.value.trim();
  }
  return out;
}

/* Dialog zum Anlegen und Bearbeiten. opts: fix (feste Werte), extra (HTML unter den Feldern), bind(form),
   danach(was, gespeichert) statt Neuzeichnen der Seite. was: 'save' | 'arch' | 'del'. ohneLoeschen: kein Löschknopf.
   umwandeln(daten): Daten vor dem Senden umbauen, ein Fehler erscheint als Meldung */
function editRecord(table, title, fields, rec = {}, opts = {}) {
  const dlg = $('#modal');
  const archivierbar = rec.id && 'archiviert' in rec;
  dlg.innerHTML = `<form class="modal-box"><h2>${esc(title)}</h2>
    <div class="form-grid">${fields.map(f => fieldHtml(f, rec[f.key] ?? f.def)).join('')}</div>${opts.extra || ''}
    <div class="modal-foot"><span class="btn-row">
      ${rec.id && !opts.ohneLoeschen ? '<button type="button" class="btn danger" data-act="del">Löschen</button>' : ''}
      ${archivierbar ? `<button type="button" class="btn" data-act="arch">${rec.archiviert ? 'Wiederherstellen' : 'Archivieren'}</button>` : ''}
    </span><span class="btn-row"><button type="button" class="btn" data-act="close">Abbrechen</button>
      <button class="btn primary">Speichern</button></span></div></form>`;
  const form = $('form', dlg);
  const fertig = (msg, was, r) => { dlg.close(); toast(msg); (opts.danach || router)(was, r); };
  const url = table + (rec.id ? '/' + rec.id : '');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      let body = { ...readForm(form, fields), ...(opts.fix || {}) };
      if (opts.umwandeln) body = opts.umwandeln(body);
      const r = await api(url, rec.id ? 'PUT' : 'POST', body);
      try {
        for (const f of fields.filter(x => x.type === 'file')) {
          const file = form.elements[f.key].files[0];
          if (file) await dateiHochladen(table, r.id, file);
        }
      } catch (e) {   // der Eintrag ist schon gespeichert: Dialog schließen, sonst legt ein zweiter Versuch ihn doppelt an
        return fertig('Gespeichert, aber ohne Datei: ' + e.message, 'save', r);
      }
      const ue = (r && r.ueberschneidungen) || [];
      fertig(ue.length ? 'Gespeichert. Achtung, zur selben Zeit: ' + ue.map(x => x.titel).join(', ') : 'Gespeichert', 'save', r);
    } catch (e) { toast(e.message); }
  });
  form.addEventListener('click', async (ev) => {
    const act = ev.target.dataset.act;
    if (act === 'close') return dlg.close();
    try {
      if (act === 'arch') { await api(url, 'PUT', { archiviert: rec.archiviert ? 0 : 1 }); fertig(rec.archiviert ? 'Wiederhergestellt' : 'Archiviert', 'arch'); }
      if (act === 'del' && confirm('Diesen Eintrag endgültig löschen? Das lässt sich nicht rückgängig machen.')) {
        await api(url, 'DELETE');
        fertig('Gelöscht', 'del');
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
/* Dialog für einen Auftrag. d: { auftraege, kunden, pakete }, opts wie bei editRecord */
function auftragDialog(a, d, opts = {}) {
  const sportarten = [...new Set(d.auftraege.map(x => x.sportart).filter(Boolean))].sort();
  const felder = [
    { key: 'kunde_id', label: 'Kunde', type: 'select', required: true,
      options: [['', 'bitte wählen']].concat(d.kunden.filter(k => !k.archiviert || k.id === a.kunde_id).map(k => [k.id, k.name])) },
    { key: 'paket_id', label: 'Paket', type: 'select', required: true,
      options: [['', 'bitte wählen']].concat(d.pakete.filter(p => p.aktiv || p.id === a.paket_id).map(p => [p.id, `${p.name} (${euro(p.grundpreis_cent)})`])) },
    { key: 'datum', label: 'Datum', type: 'date', required: true },
    { key: 'uhrzeit', label: 'Uhrzeit', type: 'time' },
    { key: 'begegnung', label: 'Begegnung oder Anlass', full: true },
    { key: 'ort', label: 'Ort' },
    { key: 'sportart', label: 'Sportart', list: sportarten },
    { key: 'spieler', label: 'Anzahl Spieler (für Spielershooting)', type: 'number' },
    { key: 'km', label: 'Kilometer, einfache Strecke ab Emden', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', options: STATUS_AUFTRAG.map(x => [x, x]), def: 'Angefragt' },
    { key: 'betrag_manuell', label: 'Betrag von Hand festlegen', type: 'check' },
    { key: 'betrag_cent', label: 'Betrag in Euro', type: 'euro' },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  // Preis im Formular: rechnet der Server (eine Stelle für die Preislogik), gespeichert wird dabei nichts
  const bind = (form) => {
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
  editRecord('auftraege', opts.titel || (a.id ? 'Auftrag bearbeiten' : 'Auftrag anlegen'), felder, a,
    { ...opts, bind, extra: '<p class="preisbox" id="preisBox" role="status"></p>' });
}

App.pages.auftraege = async (view) => {
  const [auftraege, kunden, pakete] = await Promise.all([api('auftraege'), api('kunden'), api('pakete')]);
  view.innerHTML = head('Aufträge und Spiele')
    + `<div class="toolbar"><button class="btn primary" id="aNeu">Auftrag anlegen</button><button class="btn" id="aSerie">Serie anlegen</button>
      <select class="input" id="aKunde" aria-label="Kunde"><option value="">Alle Kunden</option>${kunden.map(k => `<option value="${k.id}"${String(k.id) === Filter.aKunde ? ' selected' : ''}>${esc(k.name)}</option>`).join('')}</select>
      <select class="input" id="aStatus" aria-label="Status"><option value="">Jeder Status</option>${STATUS_AUFTRAG.map(x => `<option${x === Filter.aStatus ? ' selected' : ''}>${x}</option>`).join('')}</select>
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
    const summe = liste.filter(a => a.status !== 'Abgesagt').reduce((sum, a) => sum + a.betrag_cent, 0);
    // auf dem Handy wird jede Zeile zur Karte (style.css: .tbl.karten)
    $('#aListe').innerHTML = `<table class="tbl karten"><thead><tr><th>Datum</th><th>Begegnung</th><th>Kunde</th><th>Paket</th><th>Status</th><th class="num">Betrag</th></tr></thead><tbody>`
      + liste.map(a => `<tr${a.archiviert || a.status === 'Abgesagt' ? ' class="muted"' : ''}>
        <td class="k-datum nowrap">${ampelPunkt(a)}${datum(a.datum)}${a.uhrzeit ? ` <span class="muted small">${esc(a.uhrzeit)} Uhr</span>` : ''}</td>
        <td class="k-titel"><a class="linkbtn" href="#/auftrag/${a.id}"><b>${esc(a.begegnung || 'ohne Titel')}</b></a>
          ${a.ort || a.sportart ? `<br><span class="muted small">${[a.sportart, a.ort].filter(Boolean).map(esc).join(' · ')}</span>` : ''}</td>
        <td class="k-kunde">${esc(byId(kunden, a.kunde_id)?.name || '')}</td><td class="k-paket">${esc(byId(pakete, a.paket_id)?.name || '')}</td>
        <td class="k-status"><select class="input sm" data-status="${a.id}" aria-label="Status ändern">${STATUS_AUFTRAG.map(x => `<option${x === a.status ? ' selected' : ''}>${x}</option>`).join('')}</select></td>
        <td class="k-betrag num">${euro(a.betrag_cent)}${a.betrag_manuell ? ' <span class="muted small">von Hand</span>' : ''}</td></tr>`).join('')
      + `</tbody></table><p class="muted small">${liste.length} ${liste.length === 1 ? 'Auftrag' : 'Aufträge'}, Summe ohne abgesagte: <b>${euro(summe)}</b></p>`;
  };
  draw();
  $('#aNeu').addEventListener('click', () => auftragDialog({}, { auftraege, kunden, pakete },
    { danach: (was, r) => { location.hash = '#/auftrag/' + r.id; } }));
  $('#aSerie').addEventListener('click', () => serieDialog(kunden, pakete, auftraege));
  ['aKunde', 'aStatus', 'aVon', 'aBis'].forEach(key =>
    $('#' + key).addEventListener('change', (ev) => { Filter[key] = ev.target.value; draw(); }));
  $('#aArchiv').addEventListener('change', (ev) => { Filter.aArchiv = ev.target.checked; draw(); });
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

/* ---------- Ein Auftrag: alles an einer Stelle (#/auftrag/<id>) ---------- */
App.pages.auftrag = async (view, id) => {
  const [a, auftraege, kunden, pakete, kontakte, alleZahlungen, alleLinks, vorlagen] = await Promise.all(
    [api('auftraege/' + Number(id)), api('auftraege'), api('kunden'), api('pakete'), api('kontakte'), api('zahlungen'),
      api('lieferlinks'), api('vorlagen')]);
  const links = alleLinks.filter(l => l.auftrag_id === a.id);
  const aufgaben = (await api('aufgaben')).filter(x => x.auftrag_id === a.id);
  const zs = alleZahlungen.filter(z => z.auftrag_id === a.id);
  const zSumme = zs.reduce((sum, z) => sum + z.betrag_cent, 0);
  const kunde = byId(kunden, a.kunde_id) || {};
  const zusatzN = a.inkl_spieler ? Math.max(0, (a.spieler || 0) - a.inkl_spieler) : 0;
  const kmN = Math.max(0, (a.km || 0) - a.anfahrt_frei_km);
  const berechnet = a.grundpreis_cent + a.zusatzspieler_cent + a.anfahrt_cent;
  const zeile = (k, v) => v ? `<tr><td class="muted">${k}</td><td>${v}</td></tr>` : '';
  const ks = kontakte.filter(c => c.kunde_id === a.kunde_id);
  view.innerHTML = head(a.begegnung || 'Auftrag ohne Titel', `${datum(a.datum)}${a.uhrzeit ? ', ' + a.uhrzeit + ' Uhr' : ''} · ${kunde.name || ''}`)
    + `<div class="toolbar"><a class="btn" href="#/auftraege">Zur Liste</a>
      <button class="btn primary" id="aEdit">Bearbeiten</button><button class="btn" id="aDup">Duplizieren</button>
      <select class="input" id="aStat" aria-label="Status ändern">${STATUS_AUFTRAG.map(x => `<option${x === a.status ? ' selected' : ''}>${x}</option>`).join('')}</select>
      ${a.archiviert ? '<span class="badge warn">archiviert</span>' : ''}</div>
    <div class="grid g2">
      <div class="card"><h2>Auftrag</h2><table class="tbl"><tbody>
        ${zeile('Kunde', esc(kunde.name))}${zeile('Paket', esc(byId(pakete, a.paket_id)?.name))}
        ${zeile('Datum', datum(a.datum) + (a.uhrzeit ? ', ' + esc(a.uhrzeit) + ' Uhr' : ''))}${zeile('Ort', esc(a.ort))}${zeile('Sportart', esc(a.sportart))}
        ${zeile('Spieler', a.spieler)}${zeile('Kilometer', a.km ? a.km + ' km einfache Strecke' : '')}
        ${zeile('Lieferfrist', datum(a.lieferfrist) + ' ' + ampelText(a))}</tbody></table>
        ${a.notizen ? `<p class="small pre">${esc(a.notizen)}</p>` : ''}</div>
      <div class="card"><h2>Preis</h2><table class="tbl"><tbody>
        <tr><td>Paket</td><td class="num">${euro(a.grundpreis_cent)}</td></tr>
        ${zusatzN ? `<tr><td>${zusatzN} Zusatzspieler zu je ${euro(a.zusatz_je_spieler_cent)}</td><td class="num">${euro(a.zusatzspieler_cent)}</td></tr>` : ''}
        ${a.anfahrt_cent ? `<tr><td>Anfahrt: ${kmN} km zu je ${euro(a.anfahrt_cent_je_km)} (${a.anfahrt_frei_km} km frei)</td><td class="num">${euro(a.anfahrt_cent)}</td></tr>` : ''}
        <tr><td><b>Betrag</b></td><td class="num"><b>${euro(a.betrag_cent)}</b></td></tr></tbody></table>
        ${a.betrag_manuell ? `<p class="muted small">Von Hand festgelegt. Berechnet wären ${euro(berechnet)}.</p>` : ''}</div>
      <div class="card"><h2>Ansprechpersonen</h2>${ks.length ? `<ul class="kontakte">${ks.map(c => `<li><b>${esc(c.name)}</b>
        <span class="muted small">${esc(c.rolle || '')}</span><br>${[c.telefon && `<a href="tel:${esc(c.telefon)}">${esc(c.telefon)}</a>`,
          c.email && `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>`, esc(c.instagram || '')].filter(Boolean).join(' · ')}</li>`).join('')}</ul>`
        : '<p class="muted">Bei diesem Kunden ist noch kein Kontakt hinterlegt.</p>'}</div>
      <div class="card"><h2>Zahlung</h2><div id="zListe">${zs.map(z => zahlungZeile(z, kontakte)).join('')}</div>
        ${zSumme !== a.betrag_cent && a.status !== 'Abgesagt' ? `<p class="warnline small">Die Zahlungen ergeben ${euro(zSumme)}, der Auftrag ${euro(a.betrag_cent)}.
          Bezahlte und erlassene Beträge passen sich nicht mehr an. Bitte prüfen.</p>` : ''}
        ${zs.some(z => z.art === 'Anzahlung') ? '' : '<button type="button" class="btn sm" id="anzNeu">Anzahlung hinzufügen</button>'}</div>
      <div class="card"><h2>Bilder</h2><div id="lListe">${links.map(linkZeile).join('') || '<p class="muted">Noch kein Galerie-Link.</p>'}</div>
        <button type="button" class="btn sm" id="lNeu">Link hinzufügen</button></div>
      <div class="card"><h2>Aufgaben</h2><div id="tListe">${aufgabenListe(aufgaben)}</div>
        <button type="button" class="btn sm" id="tNeu">Aufgabe hinzufügen</button></div>
    </div>`;
  const d = { auftraege, kunden, pakete };
  aufgabenBinden($('#tListe'), aufgaben, kunden, auftraege);
  $('#tNeu').addEventListener('click', () => aufgabeDialog({ auftrag_id: a.id, kunde_id: a.kunde_id }, kunden, auftraege));
  $('#aEdit').addEventListener('click', () => auftragDialog(a, d, { danach: (was) => { if (was === 'del') location.hash = '#/auftraege'; else router(); } }));
  // Kopie ohne Datum, Status und Betrag: die Preise kommen neu aus dem Paket
  $('#aDup').addEventListener('click', () => auftragDialog(
    Object.fromEntries(['kunde_id', 'paket_id', 'uhrzeit', 'begegnung', 'ort', 'sportart', 'spieler', 'km', 'notizen'].map(k => [k, a[k]])), d,
    { titel: 'Auftrag duplizieren', danach: (was, r) => { location.hash = '#/auftrag/' + r.id; } }));
  $('#aStat').addEventListener('change', async (ev) => {
    try { await api('auftraege/' + a.id, 'PUT', { status: ev.target.value }); toast('Status: ' + ev.target.value); } catch (e) { toast(e.message); }
  });
  $('#zListe').addEventListener('click', (ev) => {
    const zid = ev.target.closest('button')?.dataset.zahlung;
    if (zid) zahlungDialog(byId(zs, zid), kontakte, kunden, a.kunde_id);
  });
  $('#anzNeu')?.addEventListener('click', () => zahlungDialog({ art: 'Anzahlung', status: 'Offen' }, kontakte, kunden, a.kunde_id,
    { fix: { auftrag_id: a.id, art: 'Anzahlung' } }));
  $('#lNeu').addEventListener('click', () => linkDialog({}, a, ks));
  $('#lListe').addEventListener('click', (ev) => {
    const b = ev.target.closest('button')?.dataset || {};
    if (b.link) linkDialog(byId(links, b.link), a, ks);
    if (b.nachricht) nachrichtDialog(byId(links, b.nachricht), a, ks, vorlagen);
  });
};

/* ---------- Bildauslieferung: Bausteine ---------- */
const AMPEL = { rot: 'überfällig', gelb: 'fällig', gruen: 'geliefert', keine: '' };
const ampelPunkt = a => a.ampel && a.ampel !== 'keine'
  ? `<span class="ampel ${a.ampel}" role="img" aria-label="Lieferung ${AMPEL[a.ampel]}" title="Lieferung ${AMPEL[a.ampel]}"></span>` : '';
const ampelText = a => a.ampel && a.ampel !== 'keine'
  ? `<span class="badge ${{ rot: 'bad', gelb: 'warn', gruen: 'ok' }[a.ampel]}">${AMPEL[a.ampel]}</span>` : '';

function tageBis(iso) {
  const h = new Date(); h.setHours(0, 0, 0, 0);
  const [y, m, t] = iso.split('-').map(Number);
  return Math.round((new Date(y, m - 1, t) - h) / 86400000);
}
function ablaufText(iso) {
  if (!iso) return '';
  const n = tageBis(iso);
  const cls = n < 0 ? 'bad' : n <= 7 ? 'warn' : 'plain';
  const txt = n < 0 ? `abgelaufen am ${datum(iso)}` : n === 0 ? 'läuft heute ab' : `läuft ab am ${datum(iso)}`;
  return `<span class="badge ${cls}">${txt}</span>`;
}

function linkZeile(l) {
  return `<div class="link-zeile"><div class="row-head"><b>${esc(l.typ)}</b>${ablaufText(l.laeuft_ab_am)}</div>
    <a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer" class="url">${esc(l.url)}</a>
    <span class="muted small">${[l.empfaenger && 'für ' + l.empfaenger, l.hinweis].filter(Boolean).map(esc).join(' · ')}</span>
    <div class="btn-row"><button type="button" class="btn sm" data-nachricht="${l.id}">Nachricht</button>
      <button type="button" class="btn sm" data-link="${l.id}">Bearbeiten</button></div></div>`;
}

function linkDialog(l, a, ks) {
  const felder = [
    { key: 'typ', label: 'Typ', type: 'select', options: [['Picdrop', 'Picdrop'], ['pCloud', 'pCloud'], ['Sonstiges', 'Sonstiges']], def: 'Picdrop' },
    { key: 'laeuft_ab_am', label: 'Läuft ab am (leer bei Picdrop: Laufzeit aus den Einstellungen)', type: 'date' },
    { key: 'url', label: 'Link (https://...)', type: 'url', required: true, full: true },
    { key: 'empfaenger', label: 'Empfänger', list: ks.map(c => c.name) },
    { key: 'hinweis', label: 'Hinweis (zum Beispiel mit Wasserzeichen, für Spieler)' },
  ];
  editRecord('lieferlinks', l.id ? 'Link bearbeiten' : 'Galerie-Link hinzufügen', felder, l, {
    fix: l.id ? {} : { auftrag_id: a.id },
    extra: l.id ? '' : '<p class="muted small">Mit dem ersten Link gilt der Auftrag als geliefert. Steht er noch davor, wechselt der Status auf Geliefert.</p>',
  });
}

/* Platzhalter: {name} {spiel} {datum} {link} {ablauf} */
function vorlageFuellen(text, l, a, ks) {
  const w = { name: l.empfaenger || ks[0]?.name || '', spiel: a.begegnung || '', datum: datum(a.datum), link: l.url, ablauf: datum(l.laeuft_ab_am) };
  return text.replace(/\{(name|spiel|datum|link|ablauf)\}/g, (m, k) => w[k]);
}

function nachrichtDialog(l, a, ks, vorlagen) {
  const dlg = $('#modal');
  if (!vorlagen.length) return toast('Noch keine Vorlage. Lege eine unter Bildauslieferung an.');
  dlg.innerHTML = `<div class="modal-box"><h2>Nachricht zum Link</h2>
    <div class="field"><label for="n_vorlage">Vorlage</label><select class="input" id="n_vorlage">${vorlagen.map(v => `<option value="${v.id}">${esc(v.name)}</option>`).join('')}</select></div>
    <div class="field"><label for="n_text">Text (hier noch anpassbar)</label><textarea class="input" id="n_text" rows="9"></textarea></div>
    <div class="modal-foot"><span></span><span class="btn-row"><button type="button" class="btn" id="n_zu">Schließen</button>
      <button type="button" class="btn primary" id="n_copy">Text kopieren</button></span></div></div>`;
  const fuellen = () => { $('#n_text').value = vorlageFuellen(byId(vorlagen, $('#n_vorlage').value).text, l, a, ks); };
  $('#n_vorlage').addEventListener('change', fuellen);
  $('#n_zu').addEventListener('click', () => dlg.close());
  $('#n_copy').addEventListener('click', () => copyText($('#n_text').value));
  fuellen();
  dlg.showModal();
}

/* ---------- Bildauslieferung: Fristen, Abläufe, Vorlagen ---------- */
App.pages.lieferung = async (view) => {
  const [u, vorlagen] = await Promise.all([api('lieferung'), api('vorlagen')]);
  const auftragZeile = a => `<tr><td class="nowrap">${ampelPunkt(a)}${datum(a.datum)}</td>
    <td><a class="linkbtn" href="#/auftrag/${a.id}"><b>${esc(a.begegnung || 'ohne Titel')}</b></a><br><span class="muted small">${esc(a.kunde)}</span></td>
    <td class="num">bis ${datum(a.lieferfrist)}</td></tr>`;
  const linkTabelle = list => `<table class="tbl"><tbody>${list.map(l => `<tr>
    <td><a class="linkbtn" href="#/auftrag/${l.auftrag_id}"><b>${esc(l.begegnung || 'ohne Titel')}</b></a>
      <br><span class="muted small">${esc(l.kunde)} · ${esc(l.typ)}${l.empfaenger ? ' für ' + esc(l.empfaenger) : ''}</span></td>
    <td class="num">${ablaufText(l.laeuft_ab_am)}</td></tr>`).join('')}</tbody></table>`;
  const vorlageFelder = [
    { key: 'name', label: 'Name', required: true, full: true },
    { key: 'text', label: 'Text. Platzhalter: {name} {spiel} {datum} {link} {ablauf}', type: 'textarea', full: true },
    { key: 'sort', label: 'Reihenfolge', type: 'number' },
  ];
  view.innerHTML = head('Bildauslieferung', 'Lieferfristen, Galerie-Links und Nachrichtenvorlagen')
    + `<div class="grid g2">
      <div class="card"><h2>Überfällig</h2>${u.ueberfaellig.length ? `<table class="tbl"><tbody>${u.ueberfaellig.map(auftragZeile).join('')}</tbody></table>`
        : '<p class="muted">Nichts überfällig.</p>'}</div>
      <div class="card"><h2>Fällig</h2>${u.faellig.length ? `<table class="tbl"><tbody>${u.faellig.map(auftragZeile).join('')}</tbody></table>`
        : '<p class="muted">Keine Galerie fällig.</p>'}</div>
      <div class="card"><h2>Links laufen in 7 Tagen ab</h2>${u.laeuft_ab.length ? linkTabelle(u.laeuft_ab) : '<p class="muted">Kein Link läuft bald ab.</p>'}</div>
      <div class="card"><h2>Abgelaufen (letzte 30 Tage)</h2>${u.abgelaufen.length ? linkTabelle(u.abgelaufen) : '<p class="muted">Kein Link abgelaufen.</p>'}</div>
      <div class="card"><h2>Nachrichtenvorlagen</h2>
        <ul class="kontakte">${vorlagen.map(v => `<li><button type="button" class="linkbtn" data-vorlage="${v.id}"><b>${esc(v.name)}</b></button>
          <p class="muted small pre">${esc(v.text)}</p></li>`).join('')}</ul>
        <button type="button" class="btn sm" id="vNeu">Vorlage hinzufügen</button>
        <p class="muted small">Die Nachricht zu einem Link erstellst du auf der Seite des Auftrags, Knopf "Nachricht".</p></div>
    </div>`;
  $('#vNeu').addEventListener('click', () => editRecord('vorlagen', 'Vorlage hinzufügen', vorlageFelder));
  // an die Inhaltsfläche dieser Seite hängen, nicht an #view: der bleibt für alle Seiten und sammelte sonst Handler
  $('.grid', view).addEventListener('click', (ev) => {
    const id = ev.target.closest('button')?.dataset.vorlage;
    if (id) editRecord('vorlagen', 'Vorlage bearbeiten', vorlageFelder, byId(vorlagen, id));
  });
};

/* ---------- Zahlungen: Bausteine ---------- */
const STATUS_ZAHLUNG = ['Offen', 'Bezahlt', 'Erlassen'];
const ZAHLARTEN = ['Bar', 'Überweisung', 'PayPal'];
const zahlBadge = st => `<span class="badge ${st === 'Bezahlt' ? 'ok' : st === 'Offen' ? 'warn' : 'plain'}">${esc(st)}</span>`;

function zahlungZeile(z, kontakte) {
  const zahler = z.zahler_id ? byId(kontakte, z.zahler_id)?.name : '';
  const info = [z.status === 'Bezahlt' && z.zahldatum ? 'am ' + datum(z.zahldatum) : '', z.zahlart, zahler ? 'von ' + zahler : '',
    z.finom_abgerechnet ? 'Finom' + (z.finom_rechnungsnr ? ' ' + z.finom_rechnungsnr : '') : ''].filter(Boolean);
  return `<div class="zahl-zeile"><div><b>${esc(z.art)}</b> ${zahlBadge(z.status)}<br>
    <span class="muted small">${info.map(esc).join(' · ') || 'noch nichts erfasst'}</span></div>
    <div class="num"><b>${euro(z.betrag_cent)}</b><br><button type="button" class="btn sm" data-zahlung="${z.id}">Erfassen</button></div></div>`;
}

/* Dialog für Zahlung oder Anzahlung. Zahler: zuerst die Kontakte des Kunden, dann alle anderen (bei der HSG zahlt oft ein Spieler). */
function zahlungDialog(z, kontakte, kunden, kundeId, opts = {}) {
  const eigene = kontakte.filter(c => c.kunde_id === kundeId);
  const andere = kontakte.filter(c => c.kunde_id !== kundeId).map(c => [c.id, `${c.name} (${byId(kunden, c.kunde_id)?.name || ''})`]);
  const felder = [
    ...(z.art === 'Anzahlung' ? [{ key: 'betrag_cent', label: 'Betrag der Anzahlung in Euro', type: 'euro', required: true }] : []),
    { key: 'status', label: 'Status', type: 'select', options: STATUS_ZAHLUNG.map(x => [x, x]) },
    { key: 'zahldatum', label: 'Zahldatum (leer: heute, wenn bezahlt)', type: 'date' },
    { key: 'zahlart', label: 'Zahlart', type: 'select', options: [['', 'noch offen']].concat(ZAHLARTEN.map(x => [x, x])) },
    { key: 'zahler_id', label: 'Zahler', type: 'select', options: [['', 'nicht festgelegt']].concat(eigene.map(c => [c.id, c.name]), andere) },
    { key: 'finom_abgerechnet', label: 'In Finom abgerechnet', type: 'check' },
    { key: 'finom_rechnungsnr', label: 'Finom-Rechnungsnummer' },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  const titel = z.id ? `${z.art} erfassen (${euro(z.betrag_cent)})` : 'Anzahlung hinzufügen';
  editRecord('zahlungen', titel, felder, z, { ...opts, ohneLoeschen: z.art !== 'Anzahlung',
    extra: z.art === 'Zahlung' ? '<p class="muted small">Der Betrag kommt aus dem Auftrag, abzüglich einer Anzahlung. Ändern lässt er sich im Auftrag.</p>' : '' });
}

/* ---------- Zahlungen: offen, noch abzurechnen, Umsatz ---------- */
App.pages.zahlungen = async (view) => {
  const jahr = Filter.uJahr || new Date().getFullYear();
  const [zahlungen, auftraege, kunden, kontakte, abr, u] = await Promise.all(
    [api('zahlungen'), api('auftraege'), api('kunden'), api('kontakte'), api('abrechnen'), api('umsatz?jahr=' + jahr)]);
  const auftrag = id => byId(auftraege, id) || {};
  const offen = zahlungen.filter(z => z.status === 'Offen' && auftrag(z.auftrag_id).status !== 'Abgesagt')
    .sort((x, y) => (auftrag(x.auftrag_id).datum || '').localeCompare(auftrag(y.auftrag_id).datum || ''));
  const titel = a => `<a class="linkbtn" href="#/auftrag/${a.id}"><b>${esc(a.begegnung || 'ohne Titel')}</b></a>`;
  const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];
  const anteil = u.grenze ? Math.round(u.summe / u.grenze * 100) : null;

  view.innerHTML = head('Zahlungen', 'Offene Beträge, Abrechnung in Finom und Umsatz')
    + `<div class="grid g2">
      <div class="card"><h2>Offen: ${euro(offen.reduce((sum, z) => sum + z.betrag_cent, 0))}</h2>
        ${offen.length ? `<table class="tbl"><tbody>${offen.map(z => { const a = auftrag(z.auftrag_id); return `<tr>
          <td class="nowrap">${datum(a.datum)}</td><td>${titel(a)}<br><span class="muted small">${esc(byId(kunden, a.kunde_id)?.name || '')}${z.art === 'Anzahlung' ? ' · Anzahlung' : ''}</span></td>
          <td class="num">${euro(z.betrag_cent)}<br><button type="button" class="btn sm" data-zahlung="${z.id}">Erfassen</button></td></tr>`; }).join('')}</tbody></table>`
          : '<p class="muted">Keine offenen Zahlungen.</p>'}</div>
      <div class="card"><h2>Noch in Finom abzurechnen</h2>
        ${abr.length ? abr.map(x => `<div class="abrechnen">
          <div class="row-head"><b>${esc(x.kunde)}</b><span class="muted small">${esc(x.art)}, bezahlt am ${datum(x.zahldatum)}${x.zahler ? ', von ' + esc(x.zahler) : ''}</span>
            <span class="num"><b>${euro(x.betrag_cent)}</b></span></div>
          <pre class="leistung">${esc(x.text)}</pre>
          <form class="btn-row" data-finom="${x.id}"><button type="button" class="btn sm" data-copy="${x.id}">Text kopieren</button>
            <input class="input sm" name="nr" placeholder="Rechnungsnummer" aria-label="Finom-Rechnungsnummer">
            <button class="btn sm primary">Abgerechnet</button></form></div>`).join('')
          : '<p class="muted">Alles abgerechnet. Hier erscheinen bezahlte Zahlungen ohne Finom-Häkchen.</p>'}</div>
      <div class="card"><h2>Umsatz ${jahr}</h2>
        <div class="toolbar"><select class="input sm" id="uJahr" aria-label="Jahr">${u.jahre.map(j => `<option${j === jahr ? ' selected' : ''}>${j}</option>`).join('')}</select>
          <a class="btn sm" href="/api/umsatz/csv?jahr=${jahr}" download>CSV herunterladen</a></div>
        <p>Bezahlt im Jahr ${jahr}: <b>${euro(u.summe)}</b></p>
        ${anteil === null ? '<p class="muted small">Umsatzgrenze ist noch nicht festgelegt (Einstellungen).</p>'
          : `<div class="balken${anteil >= 80 ? ' warn' : ''}"><span></span></div>
            <p class="muted small">${anteil} % der Grenze von ${euro(u.grenze)} aus den Einstellungen. Welche Regel für dich gilt, klärst du mit der Steuerberatung.</p>`}
        <table class="tbl"><thead><tr><th>Monat</th><th class="num">Betrag</th></tr></thead><tbody>
          ${u.monate.map((c, i) => `<tr${c ? '' : ' class="muted"'}><td>${MONATE[i]}</td><td class="num">${euro(c)}</td></tr>`).join('')}</tbody></table>
        <p class="muted small">Gezählt wird nach Zahldatum, nur bezahlte Zahlungen.</p></div>
      <div class="card"><h2>Umsatz ${jahr} je Kunde</h2>
        ${u.kunden.length ? `<table class="tbl"><tbody>${u.kunden.map(([k, c]) => `<tr><td>${esc(k)}</td><td class="num">${euro(c)}</td></tr>`).join('')}</tbody></table>`
          : '<p class="muted">Noch kein Umsatz in diesem Jahr.</p>'}</div>
    </div>`;
  // Breite des Balkens per JS: die CSP erlaubt keine style-Attribute im HTML
  $$('.balken span', view).forEach(el => { el.style.width = Math.min(100, anteil) + '%'; });
  $('#uJahr').addEventListener('change', (ev) => { Filter.uJahr = Number(ev.target.value); router(); });
  // an die Inhaltsfläche dieser Seite hängen, nicht an #view: der bleibt für alle Seiten und sammelte sonst Handler
  $('.grid', view).addEventListener('click', async (ev) => {
    const d = ev.target.closest('button')?.dataset || {};
    if (d.zahlung) { const z = byId(zahlungen, d.zahlung); zahlungDialog(z, kontakte, kunden, auftrag(z.auftrag_id).kunde_id); }
    if (d.copy) copyText(byId(abr, d.copy).text);
  });
  $('.grid', view).addEventListener('submit', async (ev) => {
    const id = ev.target.dataset.finom;
    if (!id) return;
    ev.preventDefault();
    try {
      await api('zahlungen/' + id, 'PUT', { finom_abgerechnet: 1, finom_rechnungsnr: ev.target.elements.nr.value.trim() });
      toast('Als abgerechnet markiert');
      router();
    } catch (e) { toast(e.message); }
  });
};

/* ---------- Protokoll: wer hat wann was geändert ---------- */
App.pages.protokoll = async (view) => {
  const rows = await api('protokoll');
  const details = (text) => {
    try {
      return Object.entries(JSON.parse(text)).map(([k, v]) => Array.isArray(v) ? `${k}: ${v[0] ?? ''} → ${v[1] ?? ''}` : `${k}: ${v}`).join(', ');
    } catch (e) { return text || ''; }
  };
  view.innerHTML = head('Protokoll', 'Die letzten 300 Einträge: Anmeldungen und jede Änderung')
    + `<div class="card"><table class="tbl karten proto"><thead><tr><th>Zeit</th><th>Aktion</th><th>Eintrag</th><th>Einzelheiten</th></tr></thead><tbody>`
    + rows.map(r => `<tr><td class="k-datum nowrap">${datum(r.time)} ${esc((r.time || '').slice(11, 16))}</td>
      <td class="k-titel"><b>${esc(r.action)}</b> <span class="muted small">${esc(r.user_name)}</span></td>
      <td class="k-kunde">${esc([r.table_name, r.label].filter(Boolean).join(': '))}</td>
      <td class="k-rest small">${esc(details(r.details))}</td></tr>`).join('')
    + '</tbody></table></div>';
};

/* ---------- Einstellungen: Pakete und Werte ---------- */
App.pages.einstellungen = async (view) => {
  const [pakete, s, sich] = await Promise.all([api('pakete'), api('einstellungen'), api('sicherungen')]);
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
      <div class="card"><h2>Sicherung</h2>
        <p>${sich.length ? `Letzte Sicherung: <b>${datum(sich[0].zeit)}, ${esc(sich[0].zeit.slice(11, 16))} Uhr</b> (${sich.length} vorhanden)` : 'Noch keine Sicherung vorhanden.'}</p>
        <p class="muted small">Jede Nacht entsteht automatisch eine Kopie der Datenbank im Ordner data/backups. Behalten werden 14 Tagesstände und 6 Monatsstände.
          Die Kopien liegen auf demselben Rechner wie das Tool, die Ablage außerhalb folgt in Phase 6.</p>
        <button type="button" class="btn sm" id="sichNeu">Jetzt sichern</button></div>
      <div class="card" id="pushCard"></div>
      <div class="card" id="avCard"></div>
    </div>`;
  pushKarte($('#pushCard'));
  vorlagenKarte($('#avCard'), pakete);
  $('#sichNeu').addEventListener('click', async () => {
    try { await api('sicherungen', 'POST', {}); toast('Sicherung erstellt'); router(); } catch (e) { toast(e.message); }
  });
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

/* ---------- Dateien ---------- */
const DATEI_MAX_MB = 15;
async function dateiHochladen(table, id, file) {
  if (file.size > DATEI_MAX_MB * 1024 * 1024) throw new Error(`Die Datei ist größer als ${DATEI_MAX_MB} MB.`);
  const data = await new Promise((ok, fehler) => {
    const fr = new FileReader();
    fr.onload = () => ok(fr.result);
    fr.onerror = () => fehler(new Error('Die Datei ließ sich nicht lesen.'));
    fr.readAsDataURL(file);
  });
  return api(`datei/${table}/${id}`, 'POST', { name: file.name, data });
}
const dateiKnoepfe = (table, x) => x.datei ? `<a class="btn sm" href="/api/datei/${table}/${x.id}" target="_blank" rel="noopener">Ansehen</a>
  <a class="btn sm" href="/api/datei/${table}/${x.id}?download=1">Herunterladen</a>` : '<span class="muted small">keine Datei</span>';
const groesse = n => n > 1048576 ? (n / 1048576).toFixed(1).replace('.', ',') + ' MB' : Math.max(1, Math.round((n || 0) / 1024)) + ' KB';

/* ---------- Verträge und Dokumente ---------- */
const VERTRAG_ARTEN = ['Saisonvertrag', 'Einwilligungs- und Nutzungsvereinbarung', 'Sponsoring'];
function fristBadge(v) {
  if (!v.kuendigen_bis) return '';
  const n = tageBis(v.kuendigen_bis);
  if (n < 0) return `<span class="badge plain">Frist war ${datum(v.kuendigen_bis)}</span>`;
  return `<span class="badge ${n <= 14 ? 'bad' : n <= 60 ? 'warn' : 'plain'}">kündigen bis ${datum(v.kuendigen_bis)}</span>`;
}

App.pages.vertraege = async (view) => {
  const [vertraege, dokumente, kunden] = await Promise.all([api('vertraege'), api('dokumente'), api('kunden')]);
  const kname = id => byId(kunden, id)?.name || '';
  const kundenOpt = (id) => [['', 'bitte wählen']].concat(kunden.filter(k => !k.archiviert || k.id === id).map(k => [k.id, k.name]));
  const vertragFelder = v => [
    { key: 'kunde_id', label: 'Kunde', type: 'select', required: true, options: kundenOpt(v.kunde_id) },
    { key: 'art', label: 'Art', type: 'select', required: true, options: [['', 'bitte wählen']].concat(VERTRAG_ARTEN.map(x => [x, x])) },
    { key: 'beginn', label: 'Beginn', type: 'date', required: true },
    { key: 'mindestlaufzeit_monate', label: 'Mindestlaufzeit (Monate)', type: 'number' },
    { key: 'kuendigungsfrist_wert', label: 'Kündigungsfrist', type: 'number' },
    { key: 'kuendigungsfrist_einheit', label: 'Einheit der Frist', type: 'select', options: [['Monate', 'Monate'], ['Wochen', 'Wochen'], ['Tage', 'Tage']], def: 'Monate' },
    { key: 'verlaengerung_monate', label: 'Verlängert sich automatisch um (Monate, leer: endet)', type: 'number' },
    { key: 'ende', label: 'Festes Ende (optional, sonst aus der Mindestlaufzeit)', type: 'date' },
    { key: 'datei', label: 'Unterschriebener Vertrag (PDF)', type: 'file', accept: 'application/pdf,.pdf', full: true },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  const dokFelder = d => [
    { key: 'kunde_id', label: 'Kunde', type: 'select', required: true, options: kundenOpt(d.kunde_id) },
    { key: 'titel', label: 'Titel (zum Beispiel Akkreditierung 2026)', required: true },
    { key: 'datei', label: 'Datei (PDF)', type: 'file', accept: 'application/pdf,.pdf', full: true },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  const aktiv = vertraege.filter(v => !v.archiviert);
  view.innerHTML = head('Verträge und Dokumente', 'Fristen werden berechnet, ohne Gewähr: maßgeblich ist der Vertrag')
    + `<div class="toolbar"><button class="btn primary" id="vNeu">Vertrag anlegen</button><button class="btn" id="dNeu">Dokument hochladen</button></div>
    <div class="grid">
      <div class="card" id="vListe"><h2>Verträge</h2>${aktiv.length ? `<table class="tbl karten"><thead><tr><th>Kunde</th><th>Art</th><th>Laufzeit</th><th>Frist</th><th>Datei</th></tr></thead><tbody>
        ${aktiv.map(v => `<tr><td class="k-titel"><button type="button" class="linkbtn" data-vertrag="${v.id}"><b>${esc(kname(v.kunde_id))}</b></button></td>
          <td class="k-kunde">${esc(v.art)}</td>
          <td class="k-datum">ab ${datum(v.beginn)}${v.laufzeit_ende ? ` bis ${datum(v.laufzeit_ende)}` : ''}<br><span class="muted small">${esc(v.vertrag_status)}</span></td>
          <td class="k-status">${fristBadge(v)}</td><td class="k-rest">${dateiKnoepfe('vertraege', v)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="muted">Noch keine Verträge.</p>'}
        ${vertraege.length > aktiv.length ? `<p class="muted small">${vertraege.length - aktiv.length} archiviert, über Bearbeiten wiederherstellbar.</p>` : ''}</div>
      <div class="card" id="dListe"><h2>Dokumente</h2>${dokumente.length ? `<table class="tbl karten"><thead><tr><th>Kunde</th><th>Titel</th><th>Hochgeladen</th><th>Datei</th></tr></thead><tbody>
        ${dokumente.map(d => `<tr><td class="k-kunde">${esc(kname(d.kunde_id))}</td>
          <td class="k-titel"><button type="button" class="linkbtn" data-dok="${d.id}"><b>${esc(d.titel)}</b></button>${d.datei_name ? `<br><span class="muted small">${esc(d.datei_name)}, ${groesse(d.groesse)}</span>` : ''}</td>
          <td class="k-datum">${datum(d.hochgeladen_am)}</td><td class="k-rest">${dateiKnoepfe('dokumente', d)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="muted">Noch keine Dokumente.</p>'}</div>
    </div>`;
  $('#vNeu').addEventListener('click', () => editRecord('vertraege', 'Vertrag anlegen', vertragFelder({})));
  $('#dNeu').addEventListener('click', () => editRecord('dokumente', 'Dokument hochladen', dokFelder({})));
  $('#vListe').addEventListener('click', (ev) => {
    const id = ev.target.closest('button')?.dataset.vertrag;
    if (id) { const v = byId(vertraege, id); editRecord('vertraege', 'Vertrag bearbeiten', vertragFelder(v), { ...v, datei: v.datei_name }); }
  });
  $('#dListe').addEventListener('click', (ev) => {
    const id = ev.target.closest('button')?.dataset.dok;
    if (id) { const d = byId(dokumente, id); editRecord('dokumente', 'Dokument bearbeiten', dokFelder(d), { ...d, datei: d.datei_name }); }
  });
};

/* ---------- Serie: mehrere Spieltage eines Kunden auf einmal ---------- */
/* Eine Zeile je Termin: "TT.MM.JJJJ HH:MM Begegnung", Uhrzeit und Begegnung sind freiwillig */
function serieZeilen(text) {
  const zeilen = String(text || '').split('\n').map(z => z.trim()).filter(Boolean);
  if (!zeilen.length) throw new Error('Bitte mindestens einen Termin eintragen.');
  return zeilen.map((z, i) => {
    const m = /^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})(?:\s+(\d{1,2}):(\d{2}))?(?:\s+(.*))?$/.exec(z);
    if (!m) throw new Error(`Zeile ${i + 1}: bitte als TT.MM.JJJJ, optional mit Uhrzeit und Begegnung.`);
    const jahr = m[3].length === 2 ? '20' + m[3] : m[3];
    return { datum: `${jahr}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`, uhrzeit: m[4] ? `${m[4].padStart(2, '0')}:${m[5]}` : '',
      begegnung: (m[6] || '').trim() };
  });
}

function serieDialog(kunden, pakete, auftraege) {
  const sportarten = [...new Set(auftraege.map(x => x.sportart).filter(Boolean))].sort();
  const felder = [
    { key: 'kunde_id', label: 'Kunde', type: 'select', required: true, options: [['', 'bitte wählen']].concat(kunden.filter(k => !k.archiviert).map(k => [k.id, k.name])) },
    { key: 'paket_id', label: 'Paket', type: 'select', required: true, options: [['', 'bitte wählen']].concat(pakete.filter(p => p.aktiv).map(p => [p.id, `${p.name} (${euro(p.grundpreis_cent)})`])) },
    { key: 'ort', label: 'Ort (für alle gleich)' },
    { key: 'sportart', label: 'Sportart', list: sportarten },
    { key: 'km', label: 'Kilometer, einfache Strecke ab Emden', type: 'number' },
    { key: 'status', label: 'Status', type: 'select', options: STATUS_AUFTRAG.map(x => [x, x]), def: 'Bestätigt' },
    { key: 'termine_text', label: 'Termine, einer je Zeile: TT.MM.JJJJ HH:MM Begegnung', type: 'textarea', full: true, required: true },
  ];
  editRecord('auftraege/serie', 'Serie anlegen', felder, {}, {
    extra: '<p class="muted small">Beispiel: <code>07.03.2027 19:30 HSG Emden gegen TuS</code>. Jeder Termin wird ein eigener Auftrag mit eigener Zahlung.</p>',
    umwandeln: (d) => { const { termine_text: t, ...rest } = d; return { ...rest, termine: serieZeilen(t) }; },
    danach: (was, r) => { toast(`${r.length} Aufträge angelegt`); router(); },
  });
}

/* ---------- Datum ---------- */
const isoTag = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const MONATSNAMEN = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember'];

/* ---------- Startseite ---------- */
App.pages.start = async (view) => {
  const d = await api('dashboard');
  const liste = (rows, zeile, leer) => rows.length ? `<table class="tbl"><tbody>${rows.map(zeile).join('')}</tbody></table>` : `<p class="muted">${leer}</p>`;
  const auftragLink = a => `<a class="linkbtn" href="#/auftrag/${a.auftrag_id || a.id}"><b>${esc(a.begegnung || 'ohne Titel')}</b></a>`;
  const anteil = d.umsatz_grenze ? Math.round(d.umsatz_jahr / d.umsatz_grenze * 100) : null;
  view.innerHTML = head('Hallo ' + (App.me.display_name || App.me.username), 'Heute ist der ' + datum(d.heute))
    + `<div class="grid g2">
      <div class="card"><h2>Nächste 14 Tage</h2>${liste([...d.termine, ...d.eigene_termine].sort((x, y) => (x.datum + (x.uhrzeit || '99')).localeCompare(y.datum + (y.uhrzeit || '99'))),
        a => a.art === 'termin' ? `<tr><td class="nowrap">${datum(a.datum)}${a.uhrzeit ? `<br><span class="muted small">${esc(a.uhrzeit)} Uhr</span>` : ''}</td>
          <td><a class="linkbtn" href="#/kalender/termin/${a.id}"><b>${esc(a.titel)}</b></a><br><span class="muted small">${esc(a.ort || '')}</span></td><td><span class="kal-chip termin">Termin</span></td></tr>`
        : `<tr><td class="nowrap">${ampelPunkt(a)}${datum(a.datum)}${a.uhrzeit ? `<br><span class="muted small">${esc(a.uhrzeit)} Uhr</span>` : ''}</td>
        <td>${auftragLink(a)}<br><span class="muted small">${esc([a.kunde, a.ort].filter(Boolean).join(' · '))}</span></td><td>${esc(a.status)}</td></tr>`, 'Keine Termine in den nächsten 14 Tagen.')}</div>
      <div class="card"><h2>Aufgaben heute und überfällig</h2><div id="startAufgaben">${aufgabenListe(d.aufgaben, true)}</div></div>
      <div class="card"><h2>Überfällige Lieferungen</h2>${liste(d.ueberfaellig, a => `<tr><td class="nowrap">${ampelPunkt(a)}${datum(a.datum)}</td>
        <td>${auftragLink(a)}<br><span class="muted small">${esc(a.kunde)}</span></td><td class="num">Frist ${datum(a.lieferfrist)}</td></tr>`, 'Nichts überfällig.')}</div>
      <div class="card"><h2>Offene Zahlungen: ${euro(d.offen_summe)}</h2>${liste(d.offen.slice(0, 6), z => `<tr><td class="nowrap">${datum(z.datum)}</td>
        <td>${auftragLink(z)}<br><span class="muted small">${esc(z.kunde || '')}${z.art === 'Anzahlung' ? ' · Anzahlung' : ''}</span></td><td class="num">${euro(z.betrag_cent)}</td></tr>`, 'Keine offenen Zahlungen.')}
        ${d.offen.length > 6 ? `<a class="small" href="#/zahlungen">Alle ${d.offen.length} offenen Zahlungen</a>` : ''}</div>
      <div class="card"><h2>Umsatz ${d.jahr}</h2><p class="gross">${euro(d.umsatz_jahr)}</p>
        ${anteil === null ? '<p class="muted small">Umsatzgrenze noch nicht festgelegt.</p>' : `<div class="balken${anteil >= 80 ? ' warn' : ''}"><span></span></div>
        <p class="muted small">${anteil} % der Grenze von ${euro(d.umsatz_grenze)}</p>`}</div>
      <div class="card"><h2>Links laufen in 7 Tagen ab</h2>${liste(d.links_ablauf, l => `<tr><td>${auftragLink(l)}<br><span class="muted small">${esc(l.kunde)} · ${esc(l.typ)}</span></td>
        <td class="num">${ablaufText(l.laeuft_ab_am)}</td></tr>`, 'Kein Link läuft bald ab.')}</div>
      <div class="card"><h2>Vertragsfristen (60 Tage)</h2>${liste(d.vertraege, v => `<tr><td><a class="linkbtn" href="#/vertraege"><b>${esc(v.kunde || '')}</b></a><br>
        <span class="muted small">${esc(v.art)}</span></td><td class="num">${fristBadge(v)}</td></tr>`, 'Keine Kündigungsfrist in den nächsten 60 Tagen.')}</div>
    </div>`;
  $$('.balken span', view).forEach(el => { el.style.width = Math.min(100, anteil) + '%'; });
  aufgabenBinden($('#startAufgaben'), d.aufgaben, [], []);
};

/* ---------- Kalender ---------- */
const KAL_ARTEN = { auftrag: 'Aufträge', termin: 'Termine', aufgabe: 'Aufgaben', lieferfrist: 'Lieferfristen', vertrag: 'Vertragsfristen',
  ablauf: 'Link-Abläufe', extern: 'Fremder Kalender' };
const kalLink = e => e.art === 'vertrag' ? '#/vertraege' : e.art === 'aufgabe' ? '#/aufgaben' : e.art === 'termin' ? `#/kalender/termin/${e.id}`
  : e.art === 'extern' ? '' : `#/auftrag/${e.id}`;
function kalChip(e) {
  const txt = `${e.uhrzeit ? esc(e.uhrzeit) + (e.bis ? ' bis ' + esc(e.bis) : '') + ' ' : ''}${esc(e.titel)}${e.ort && e.art !== 'auftrag' ? ', ' + esc(e.ort) : ''}`;
  const href = kalLink(e);
  return href ? `<a class="kal-chip ${e.art}${e.status === 'Abgesagt' ? ' abgesagt' : ''}" href="${href}">${txt}</a>` : `<span class="kal-chip ${e.art}">${txt}</span>`;
}
const TERMIN_ARTEN = ['Besprechung', 'Shooting-Vorbereitung', 'Privat geblockt', 'Sonstiges'];
const ERINNERUNGEN = [['', 'keine'], ['0', 'zu Beginn'], ['15', '15 Minuten vorher'], ['30', '30 Minuten vorher'], ['60', '1 Stunde vorher'],
  ['120', '2 Stunden vorher'], ['1440', '1 Tag vorher']];
const WIEDERHOLUNG_OPT = [['', 'keine'], ['täglich', 'täglich'], ['wöchentlich', 'wöchentlich'], ['monatlich', 'monatlich'], ['jährlich', 'jährlich']];

function terminDialog(t, kunden, danach) {
  const felder = [
    { key: 'titel', label: 'Titel', required: true, full: true },
    { key: 'tag', label: 'Datum', type: 'date', required: true },
    { key: 'ganztaegig', label: 'Ganztägig', type: 'check' },
    { key: 'von', label: 'Von', type: 'time' },
    { key: 'bis', label: 'Bis', type: 'time' },
    { key: 'ort', label: 'Ort' },
    { key: 'art', label: 'Art', type: 'select', options: [['', 'ohne']].concat(TERMIN_ARTEN.map(x => [x, x])) },
    { key: 'wiederholung', label: 'Wiederholung', type: 'select', options: WIEDERHOLUNG_OPT },
    { key: 'wiederholung_bis', label: 'Wiederholen bis (leer: ohne Ende)', type: 'date' },
    { key: 'erinnerung_min', label: 'Erinnerung per Push', type: 'select', options: ERINNERUNGEN },
    { key: 'kunde_id', label: 'Kunde (optional)', type: 'select', options: [['', 'ohne']].concat(kunden.filter(k => !k.archiviert || k.id === t.kunde_id).map(k => [k.id, k.name])) },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  const rec = { ...t, tag: (t.beginn || '').slice(0, 10), von: (t.beginn || '').slice(11, 16), bis: (t.ende || '').slice(11, 16),
    erinnerung_min: t.erinnerung_min ?? '' };
  editRecord('termine', t.id ? 'Termin bearbeiten' : 'Termin anlegen', felder, rec, {
    umwandeln: (d) => {
      const { tag, von, bis, ...rest } = d;
      if (!d.ganztaegig && !von) throw new Error('Bitte eine Uhrzeit angeben oder "Ganztägig" wählen.');
      return { ...rest, beginn: d.ganztaegig ? tag : `${tag}T${von}`, ende: d.ganztaegig ? '' : (bis ? `${tag}T${bis}` : '') };
    },
    danach: danach || (() => { location.hash = '#/kalender'; }),
  });
}

App.pages.kalender = async (view, ...rest) => {
  if (!Filter.kArten) Filter.kArten = Object.keys(KAL_ARTEN);
  if (!Filter.kAnsicht) Filter.kAnsicht = matchMedia('(max-width: 700px)').matches ? 'liste' : 'monat';
  const t0 = new Date((Filter.kDatum || isoTag(new Date())) + 'T12:00');
  const y = t0.getFullYear(), mo = t0.getMonth() + 1;
  let start, ende, titel;
  if (Filter.kAnsicht === 'woche') {
    start = new Date(t0); start.setDate(t0.getDate() - (t0.getDay() + 6) % 7);
    ende = new Date(start); ende.setDate(start.getDate() + 6);
    titel = `Woche vom ${datum(isoTag(start))} bis ${datum(isoTag(ende))}`;
  } else if (Filter.kAnsicht === 'tag') {
    start = new Date(t0); ende = new Date(t0);
    titel = `${WOCHENTAGE[(t0.getDay() + 6) % 7]}, ${datum(isoTag(t0))}`;
  } else {
    const erster = new Date(y, mo - 1, 1), letzter = new Date(y, mo, 0);
    start = Filter.kAnsicht === 'monat' ? new Date(y, mo - 1, 1 - (erster.getDay() + 6) % 7) : erster;
    ende = Filter.kAnsicht === 'monat' ? new Date(y, mo - 1, letzter.getDate() + 6 - (letzter.getDay() + 6) % 7) : letzter;
    titel = `${MONATSNAMEN[mo - 1]} ${y}`;
  }
  const [alle, abo, fremd, kunden] = await Promise.all([api(`kalender?von=${isoTag(start)}&bis=${isoTag(ende)}`), api('kalender/abo'),
    api('kalender/fremd'), api('kunden')]);
  const eintraege = alle.filter(e => Filter.kArten.includes(e.art));
  const amTag = {};
  eintraege.forEach(e => (amTag[e.datum] = amTag[e.datum] || []).push(e));
  const heute = isoTag(new Date());
  const tagesListe = t => { const d = new Date(t + 'T12:00'); return `<div class="kal-agenda${t === heute ? ' heute' : ''}">
    <div class="kal-datum"><b>${WOCHENTAGE[(d.getDay() + 6) % 7]}, ${datum(t)}</b> <button type="button" class="linkbtn small muted" data-neu="${t}">+ Termin</button></div>
    ${(amTag[t] || []).map(kalChip).join('') || '<span class="muted small">frei</span>'}</div>`; };

  let inhalt;
  if (Filter.kAnsicht === 'monat') {
    let zellen = '';
    for (let d = new Date(start); d <= ende; d.setDate(d.getDate() + 1)) {
      const t = isoTag(d);
      zellen += `<div class="kal-tag${d.getMonth() !== mo - 1 ? ' fremd' : ''}${t === heute ? ' heute' : ''}">
        <button type="button" class="kal-nr linkbtn" data-tag="${t}" aria-label="${datum(t)} anzeigen">${d.getDate()}</button>${(amTag[t] || []).map(kalChip).join('')}</div>`;
    }
    inhalt = `<div class="kal-monat">${WOCHENTAGE.map(w => `<div class="kal-kopf">${w}</div>`).join('')}${zellen}</div>`;
  } else if (Filter.kAnsicht === 'woche' || Filter.kAnsicht === 'tag') {
    const tage = [];
    for (let d = new Date(start); d <= ende; d.setDate(d.getDate() + 1)) tage.push(isoTag(d));
    inhalt = `<div class="kal-woche">${tage.map(tagesListe).join('')}</div>`;
  } else {
    const tage = Object.keys(amTag).sort();
    inhalt = tage.length ? tage.map(tagesListe).join('') : '<p class="muted">In diesem Monat steht nichts an.</p>';
  }

  view.innerHTML = head('Kalender', titel)
    + `<div class="toolbar"><button class="btn sm" data-schritt="-1" aria-label="Zurück">‹</button><button class="btn sm" data-schritt="0">Heute</button>
      <button class="btn sm" data-schritt="1" aria-label="Weiter">›</button>
      <select class="input sm" id="kAnsicht" aria-label="Ansicht">${[['monat', 'Monat'], ['woche', 'Woche'], ['tag', 'Tag'], ['liste', 'Liste']].map(([k, t]) =>
        `<option value="${k}"${Filter.kAnsicht === k ? ' selected' : ''}>${t}</option>`).join('')}</select>
      <button class="btn sm primary" id="tNeuKal">Termin anlegen</button></div>
    <div class="toolbar kal-filter">${Object.entries(KAL_ARTEN).map(([k, t]) => `<label class="check"><input type="checkbox" data-art="${k}"${Filter.kArten.includes(k) ? ' checked' : ''}> <span class="kal-chip ${k}">${t}</span></label>`).join('')}</div>
    <div class="card" id="kalInhalt">${inhalt}</div>
    <div class="grid g2 kal-unten">
    <div class="card" id="aboCard"><h2>Kalender-Abo fürs iPhone</h2>
      <p class="muted small">Ein geheimer Link, den der iPhone-Kalender regelmäßig abruft: Einstellungen, Kalender, Accounts, Account hinzufügen, Andere,
        Kalenderabo hinzufügen. Er zeigt Aufträge und eigene Termine, nur Zeit, Ort und Titel, keine Beträge und keine Kontaktdaten. Klappt erst auf dem Server.</p>
      <p>${abo.aktiv ? '<span class="badge ok">eingerichtet</span>' : '<span class="badge plain">nicht eingerichtet</span>'}</p>
      <div id="aboLink"></div>
      <div class="btn-row"><button type="button" class="btn sm" id="aboNeu">${abo.aktiv ? 'Neuen Link erstellen (alter gilt dann nicht mehr)' : 'Link erstellen'}</button>
        ${abo.aktiv ? '<button type="button" class="btn sm danger" id="aboAus">Abschalten</button>' : ''}</div></div>
    <div class="card" id="fremdCard"><h2>Fremder Kalender einblenden</h2>
      <p class="muted small">ICS-Link eines anderen Kalenders, zum Beispiel Dienstplan oder privater Kalender. Die Termine erscheinen nur hier im Kalender,
        nie im Kalender-Abo. Abgerufen wird alle 30 Minuten. Der Link wird geschützt gespeichert und nicht wieder angezeigt.</p>
      ${fremd.aktiv ? `<p><span class="badge ${fremd.fehler ? 'bad' : 'ok'}">${fremd.fehler ? 'Fehler beim Abruf' : 'eingebunden'}</span> ${esc(fremd.host)}
        ${fremd.zeit ? `<br><span class="muted small">Zuletzt abgerufen ${datum(fremd.zeit)}, ${esc(fremd.zeit.slice(11, 16))} Uhr, ${fremd.anzahl} Termine.</span>` : ''}
        ${fremd.fehler ? `<br><span class="small">${esc(fremd.fehler)}</span>` : ''}</p>` : ''}
      <form class="btn-row" id="fremdForm"><input class="input" type="url" name="url" placeholder="https:// oder webcal://" aria-label="ICS-Link" required>
        <button class="btn sm primary">${fremd.aktiv ? 'Ersetzen' : 'Einbinden'}</button></form>
      ${fremd.aktiv ? '<div class="btn-row"><button type="button" class="btn sm" id="fremdAbruf">Jetzt abrufen</button><button type="button" class="btn sm danger" id="fremdAus">Entfernen</button></div>' : ''}</div>
    </div>`;

  const schieben = n => {
    const d = new Date(t0);
    if (n === 0) return isoTag(new Date());
    if (Filter.kAnsicht === 'woche') d.setDate(d.getDate() + 7 * n);
    else if (Filter.kAnsicht === 'tag') d.setDate(d.getDate() + n);
    else { d.setDate(1); d.setMonth(d.getMonth() + n); }
    return isoTag(d);
  };
  $('.toolbar', view).addEventListener('click', (ev) => {
    const n = ev.target.closest('button')?.dataset.schritt;
    if (n === undefined) return;
    Filter.kDatum = schieben(Number(n));
    router();
  });
  $('#kAnsicht').addEventListener('change', (ev) => { Filter.kAnsicht = ev.target.value; router(); });
  $$('[data-art]', view).forEach(cb => cb.addEventListener('change', () => {
    Filter.kArten = $$('[data-art]', view).filter(x => x.checked).map(x => x.dataset.art);
    router();
  }));
  $('#kalInhalt').addEventListener('click', (ev) => {
    const b = ev.target.closest('button')?.dataset || {};
    if (b.tag) { Filter.kDatum = b.tag; Filter.kAnsicht = 'tag'; router(); }
    if (b.neu) terminDialog({ beginn: b.neu }, kunden, () => router());
  });
  $('#tNeuKal').addEventListener('click', () => terminDialog({ beginn: Filter.kAnsicht === 'tag' ? isoTag(t0) : isoTag(new Date()) }, kunden, () => router()));
  $('#aboNeu').addEventListener('click', async () => {
    if (abo.aktiv && !confirm('Neuen Link erstellen? Der bisherige Link funktioniert danach nicht mehr.')) return;
    try {
      const r = await api('kalender/abo', 'POST', {});
      $('#aboLink').innerHTML = `<p class="warnline small">Diesen Link jetzt kopieren und im iPhone eintragen. Er wird nur dieses eine Mal angezeigt.</p>
        <div class="btn-row"><input class="input" id="aboUrl" readonly value="${esc(r.link)}" aria-label="Kalender-Link"><button type="button" class="btn sm" id="aboCopy">Kopieren</button></div>`;
      $('#aboCopy').addEventListener('click', () => copyText(r.link));
      $('#aboNeu').textContent = 'Neuen Link erstellen (alter gilt dann nicht mehr)';
      abo.aktiv = true;
    } catch (e) { toast(e.message); }
  });
  $('#aboAus')?.addEventListener('click', async () => {
    if (!confirm('Kalender-Abo abschalten? Der iPhone-Kalender bekommt danach keine Termine mehr.')) return;
    try { await api('kalender/abo', 'DELETE'); toast('Abgeschaltet'); router(); } catch (e) { toast(e.message); }
  });
  $('#fremdForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { const r = await api('kalender/fremd', 'PUT', { url: ev.target.elements.url.value.trim() }); toast(r.fehler ? 'Gespeichert, aber: ' + r.fehler : `${r.anzahl} Termine eingelesen`); router(); }
    catch (e) { toast(e.message); }
  });
  $('#fremdAbruf')?.addEventListener('click', async () => { const r = await api('kalender/fremd/abrufen', 'POST', {}); toast(r.fehler || `${r.anzahl} Termine eingelesen`); router(); });
  $('#fremdAus')?.addEventListener('click', async () => {
    if (!confirm('Fremden Kalender entfernen?')) return;
    await api('kalender/fremd', 'DELETE'); toast('Entfernt'); router();
  });
  if (rest[0] === 'termin' && rest[1]) {   // #/kalender/termin/<id>: Termin direkt bearbeiten
    try { terminDialog(await api('termine/' + Number(rest[1])), kunden); } catch (e) { toast(e.message); }
  }
};

/* ---------- Aufgaben ---------- */
const PRIO_KLASSE = { Hoch: 'bad', Mittel: 'plain', Niedrig: 'plain' };
function aufgabenListe(liste, kurz) {
  if (!liste.length) return '<p class="muted">Keine Aufgaben.</p>';
  const heute = isoTag(new Date());
  return `<ul class="aufgaben">${liste.map(x => `<li class="${x.status === 'Erledigt' ? 'erledigt' : ''}">
    <input type="checkbox" data-erledigt="${x.id}" aria-label="${esc(x.titel)} erledigt"${x.status === 'Erledigt' ? ' checked' : ''}>
    <div><button type="button" class="linkbtn" data-aufgabe="${x.id}"><b>${esc(x.titel)}</b></button>
      ${x.prioritaet === 'Hoch' ? `<span class="badge ${PRIO_KLASSE.Hoch}">hoch</span>` : ''}${x.status === 'In Arbeit' ? '<span class="badge warn">in Arbeit</span>' : ''}
      ${x.wiederholung ? `<span class="muted small">(${esc(x.wiederholung)})</span>` : ''}
      <br><span class="small ${x.faellig && x.faellig < heute && x.status !== 'Erledigt' ? 'rot' : 'muted'}">${x.faellig ? 'fällig ' + datum(x.faellig) : 'ohne Datum'}</span>
      ${!kurz && x.auftrag_id ? ` <a class="small" href="#/auftrag/${x.auftrag_id}">zum Auftrag</a>` : ''}</div></li>`).join('')}</ul>`;
}
function aufgabenBinden(box, liste, kunden, auftraege) {
  box.addEventListener('change', async (ev) => {
    const id = ev.target.dataset.erledigt;
    if (!id) return;
    try {
      await api('aufgaben/' + id, 'PUT', { status: ev.target.checked ? 'Erledigt' : 'Offen' });
      toast(ev.target.checked ? 'Erledigt' : 'Wieder offen');
      ev.target.closest('li').classList.toggle('erledigt', ev.target.checked);
      badgeSync();
    } catch (e) { toast(e.message); ev.target.checked = !ev.target.checked; }
  });
  box.addEventListener('click', async (ev) => {
    const id = ev.target.closest('button')?.dataset.aufgabe;
    if (!id) return;
    const [k, a] = kunden.length ? [kunden, auftraege] : await Promise.all([api('kunden'), api('auftraege')]);
    aufgabeDialog(byId(liste, id), k, a);
  });
}
function aufgabeDialog(x, kunden, auftraege) {
  const felder = [
    { key: 'titel', label: 'Titel', required: true, full: true },
    { key: 'faellig', label: 'Fällig am', type: 'date' },
    { key: 'prioritaet', label: 'Priorität', type: 'select', options: [['Mittel', 'Mittel'], ['Hoch', 'Hoch'], ['Niedrig', 'Niedrig']] },
    { key: 'status', label: 'Status', type: 'select', options: [['Offen', 'Offen'], ['In Arbeit', 'In Arbeit'], ['Erledigt', 'Erledigt']] },
    { key: 'wiederholung', label: 'Wiederholen (neue Aufgabe beim Erledigen)', type: 'select', options: WIEDERHOLUNG_OPT },
    { key: 'kunde_id', label: 'Kunde', type: 'select', options: [['', 'ohne']].concat(kunden.filter(k => !k.archiviert || k.id === x.kunde_id).map(k => [k.id, k.name])) },
    { key: 'auftrag_id', label: 'Auftrag', type: 'select', options: [['', 'ohne']].concat(auftraege.filter(a => !a.archiviert || a.id === x.auftrag_id).slice(-200)
      .map(a => [a.id, `${datum(a.datum)} ${a.begegnung || ''}`])) },
    { key: 'notizen', label: 'Notizen', type: 'textarea', full: true },
  ];
  editRecord('aufgaben', x.id ? 'Aufgabe bearbeiten' : 'Aufgabe anlegen', felder, x, { danach: () => { badgeSync(); router(); } });
}

App.pages.aufgaben = async (view) => {
  const [alle, kunden, auftraege] = await Promise.all([api('aufgaben'), api('kunden'), api('auftraege')]);
  const heute = isoTag(new Date());
  const w = new Date(); w.setDate(w.getDate() + 6 - (w.getDay() + 6) % 7);
  const sonntag = isoTag(w);
  const offen = alle.filter(x => x.status !== 'Erledigt');
  const ANSICHTEN = {
    heute: ['Heute', offen.filter(x => x.faellig && x.faellig <= heute)],
    woche: ['Diese Woche', offen.filter(x => x.faellig && x.faellig <= sonntag)],
    ueberfaellig: ['Überfällig', offen.filter(x => x.faellig && x.faellig < heute)],
    alle: ['Alle offenen', offen],
    erledigt: ['Erledigt', alle.filter(x => x.status === 'Erledigt').sort((a, b) => (b.erledigt_am || '').localeCompare(a.erledigt_am || '')).slice(0, 100)],
  };
  const an = Filter.tAnsicht || 'heute';
  view.innerHTML = head('Aufgaben')
    + `<form class="toolbar" id="tSchnell"><input class="input" name="titel" placeholder="Neue Aufgabe" aria-label="Neue Aufgabe" required>
      <input class="input" type="date" name="faellig" value="${heute}" aria-label="Fällig am"><button class="btn primary">Hinzufügen</button></form>
    <div class="toolbar tabs">${Object.entries(ANSICHTEN).map(([k, [t, l]]) => `<button type="button" class="btn sm${k === an ? ' primary' : ''}" data-ansicht="${k}">${t} (${l.length})</button>`).join('')}</div>
    <div class="card" id="tListe">${aufgabenListe(ANSICHTEN[an][1])}</div>`;
  $('.tabs', view).addEventListener('click', (ev) => { const k = ev.target.closest('button')?.dataset.ansicht; if (k) { Filter.tAnsicht = k; router(); } });
  $('#tSchnell').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await api('aufgaben', 'POST', { titel: ev.target.elements.titel.value.trim(), faellig: ev.target.elements.faellig.value }); toast('Angelegt'); badgeSync(); router(); }
    catch (e) { toast(e.message); }
  });
  aufgabenBinden($('#tListe'), alle, kunden, auftraege);
};

/* ---------- Einstellungen: Aufgaben-Vorlagen je Paket ---------- */
async function vorlagenKarte(box, pakete) {
  const vorlagen = await api('aufgaben_vorlagen');
  const felder = [
    { key: 'paket_id', label: 'Paket', type: 'select', required: true, options: pakete.map(p => [p.id, p.name]) },
    { key: 'titel', label: 'Aufgabe', required: true },
    { key: 'tage_offset', label: 'Fällig: Tage nach dem Auftrag (negativ: davor)', type: 'text' },
    { key: 'prioritaet', label: 'Priorität', type: 'select', options: [['Mittel', 'Mittel'], ['Hoch', 'Hoch'], ['Niedrig', 'Niedrig']] },
    { key: 'sort', label: 'Reihenfolge', type: 'number' },
  ];
  const tage = n => n === 0 ? 'am Tag des Auftrags' : n > 0 ? `${n} ${n === 1 ? 'Tag' : 'Tage'} danach` : `${-n} ${n === -1 ? 'Tag' : 'Tage'} vorher`;
  box.innerHTML = `<h2>Aufgaben je Paket</h2><p class="muted small">Diese Aufgaben entstehen automatisch beim Anlegen eines Auftrags.</p>
    ${pakete.map(p => { const v = vorlagen.filter(x => x.paket_id === p.id); return `<details><summary><b>${esc(p.name)}</b> <span class="muted small">(${v.length})</span></summary>
      <ul class="kontakte">${v.map(x => `<li><button type="button" class="linkbtn" data-av="${x.id}">${esc(x.titel)}</button> <span class="muted small">${tage(x.tage_offset || 0)}</span></li>`).join('')}</ul>
      <button type="button" class="btn sm" data-avneu="${p.id}">Aufgabe hinzufügen</button></details>`; }).join('')}`;
  box.addEventListener('click', (ev) => {
    const b = ev.target.closest('button')?.dataset || {};
    if (b.av) editRecord('aufgaben_vorlagen', 'Vorlage bearbeiten', felder, byId(vorlagen, b.av));
    if (b.avneu) editRecord('aufgaben_vorlagen', 'Vorlage hinzufügen', felder, { paket_id: Number(b.avneu), tage_offset: 0 });
  });
}

/* ---------- App auf dem Home-Bildschirm und Push (nach dem Vorbild des Hubs) ---------- */
/* iPhone: Push geht nur, wenn das Tool als App auf dem Home-Bildschirm liegt (ab iOS 16.4) */
const istApp = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const istIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
const pushMoeglich = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
async function swReg() { return navigator.serviceWorker.getRegistration('/') || navigator.serviceWorker.register('/sw.js', { scope: '/' }); }
async function pushAbo() { try { const r = await swReg(); return r ? await r.pushManager.getSubscription() : null; } catch { return null; } }
async function pushEin() {
  if (!pushMoeglich()) throw new Error(istIOS() && !istApp() ? 'Auf dem iPhone gehen Mitteilungen nur, wenn das Studio-Tool als App auf dem Home-Bildschirm liegt: in Safari "Teilen", dann "Zum Home-Bildschirm", und das Tool von dort öffnen.' : 'Dieser Browser unterstützt keine Push-Mitteilungen.');
  if (await Notification.requestPermission() !== 'granted') throw new Error('Mitteilungen wurden nicht erlaubt. Das lässt sich in den Einstellungen des Handys oder Browsers ändern.');
  const { key } = await api('push/key');
  const raw = Uint8Array.from(atob(key.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - key.length % 4) % 4)), c => c.charCodeAt(0));
  const reg = await swReg(); await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription() || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: raw });
  await api('push/subscribe', 'POST', sub.toJSON());
}
async function pushAus() {
  const sub = await pushAbo(); if (!sub) return;
  try { await api('push/unsubscribe', 'POST', { endpoint: sub.endpoint }); } catch { /* trotzdem abmelden */ }
  await sub.unsubscribe();
}
async function pushKarte(box) {
  const aktiv = pushMoeglich() && !!(await pushAbo());
  box.innerHTML = `<h2>Mitteilungen auf diesem Gerät</h2>
    <p>${aktiv ? '<span class="badge ok">eingeschaltet</span>' : '<span class="badge plain">aus</span>'}</p>
    <p class="muted small">Push für neue Mails, Termine und fällige Aufgaben. Inhalt nur Titel und kurzer Text.
      ${istIOS() && !istApp() ? 'Am iPhone zuerst in Safari "Teilen", "Zum Home-Bildschirm" und das Tool von dort öffnen.' : ''}
      Klappt nur über HTTPS, also erst auf dem Server.</p>
    <div class="btn-row">${aktiv ? '<button type="button" class="btn sm" id="pushTest">Test senden</button><button type="button" class="btn sm" id="pushAus">Ausschalten</button>'
      : '<button type="button" class="btn sm primary" id="pushEin">Einschalten</button>'}</div>`;
  $('#pushEin', box)?.addEventListener('click', async () => { try { await pushEin(); toast('Mitteilungen eingeschaltet'); pushKarte(box); } catch (e) { alert(e.message); } });
  $('#pushAus', box)?.addEventListener('click', async () => { await pushAus(); toast('Mitteilungen ausgeschaltet'); pushKarte(box); });
  $('#pushTest', box)?.addEventListener('click', async () => {
    try { const r = await api('push/test', 'POST', {}); toast(r.ok ? 'Test gesendet' : 'Nicht zugestellt. Ist das Gerät noch angemeldet?'); } catch (e) { toast(e.message); }
  });
}

/* Zahl am App-Symbol: überfällige Aufgaben und neue Mails, jede Minute und beim Zurückkehren in die App */
async function badgeSync() {
  try {
    const { badge } = await api('badge');
    if ('setAppBadge' in navigator) badge > 0 ? navigator.setAppBadge(badge) : navigator.clearAppBadge();
    App.badge = badge;
    if (App.nachBadge) App.nachBadge(badge);
  } catch { /* offline oder nicht unterstützt */ }
}

/* Hinweis "Als App installieren" auf dem Handy, höchstens alle 30 Tage */
let installEvent = null;
addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); installEvent = e; });
function installHinweis() {
  const handy = istIOS() || /Android/.test(navigator.userAgent);
  let spaeter = 0;
  try { spaeter = Number(localStorage.getItem('studio_install_spaeter') || 0); } catch { /* ohne Speicher */ }
  if (istApp() || !handy || Date.now() - spaeter < 30 * 864e5 || !App.me) return;
  const text = installEvent ? 'Studio-Tool als App installieren, dann liegt es mit einem Tipp auf dem Home-Bildschirm.'
    : istIOS() ? 'Als App: unten auf <b>Teilen</b> tippen, dann <b>Zum Home-Bildschirm</b>.' : 'Als App: oben rechts im Menü <b>App installieren</b> wählen.';
  document.body.insertAdjacentHTML('beforeend', `<div id="installHint" class="install-hint" role="dialog" aria-label="App installieren">
    <img src="/static/icon-192.png" alt="" width="44" height="44"><div class="ih-text">${text}</div>
    <div class="ih-btns">${installEvent ? '<button class="btn primary sm" id="ihJa">Installieren</button>' : ''}<button class="btn sm" id="ihSpaeter">${installEvent ? 'Später' : 'OK'}</button></div></div>`);
  $('#ihSpaeter').addEventListener('click', () => { try { localStorage.setItem('studio_install_spaeter', String(Date.now())); } catch { /* egal */ } $('#installHint').remove(); });
  $('#ihJa')?.addEventListener('click', async () => { const ev = installEvent; installEvent = null; $('#installHint').remove(); try { ev.prompt(); await ev.userChoice; } catch { /* abgelehnt */ } });
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
setTimeout(installHinweis, 4000);
setTimeout(badgeSync, 1500);
setInterval(badgeSync, 60000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') badgeSync(); });
