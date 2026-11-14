/* Anmeldeseite: Schritt 1 Benutzername und Passwort, Schritt 2 (falls eingerichtet) Code aus der App.
   Alles als JSON mit dem Schutz-Header X-Studio. */
(function () {
  const form = document.getElementById('loginForm');
  const err = document.getElementById('err');
  let step = 1;
  let ticket = '';
  async function post(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Studio': '1' },
      body: JSON.stringify(body),
    });
    return { r, d: await r.json().catch(() => ({})) };
  }
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.textContent = '';
    const btn = document.getElementById(step === 1 ? 'loginBtn' : 'codeBtn');
    btn.disabled = true;
    try {
      if (step === 1) {
        const username = document.getElementById('u').value.trim();
        const password = document.getElementById('p').value;
        if (!username || !password) { err.textContent = 'Bitte Benutzername und Passwort eingeben.'; return; }
        const { r, d } = await post('/auth/login', { username, password });
        if (r.ok && d.need_2fa) {
          step = 2;
          ticket = d.ticket;
          document.getElementById('s1').hidden = true;
          document.getElementById('s2').hidden = false;
          const c = document.getElementById('c');
          c.disabled = false;
          c.focus();
          return;
        }
        if (r.ok) { location.href = d.next || '/'; return; }
        err.textContent = d.error || 'Anmeldung fehlgeschlagen.';
        document.getElementById('p').value = '';
      } else {
        const code = document.getElementById('c').value;
        if (!code.trim()) { err.textContent = 'Bitte den Code eingeben.'; return; }
        const { r, d } = await post('/auth/login2', { ticket, code });
        if (r.ok) { location.href = d.next || '/'; return; }
        err.textContent = d.error || 'Anmeldung fehlgeschlagen.';
        document.getElementById('c').value = '';
        if (d.restart) setTimeout(() => { location.href = '/login'; }, 2500);
      }
    } catch (x) {
      err.textContent = 'Keine Verbindung zum Server.';
    } finally {
      btn.disabled = false;
    }
  });
})();
