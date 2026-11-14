/* Studio-Tool: Service Worker für die App auf dem Home-Bildschirm (nach dem Vorbild des Emden Tigers Hub).
   Speichert bewusst nichts zwischen (keine Kundendaten auf dem Handy), zeigt ohne Netz nur einen Hinweis. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<title>Keine Verbindung</title><body><h2>Keine Verbindung</h2><p>Das Studio-Tool braucht Internet. Bitte später erneut versuchen.</p>' +
    '<p><a href="/">Erneut laden</a></p></body></html>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});

/* Push: Inhalt kommt Ende-zu-Ende verschlüsselt vom Server, gespeichert wird nichts */
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data ? e.data.text() : '' }; }
  const setBadge = () => {   // Zahl am App-Symbol (iPhone ab iOS 16.4 als App)
    const nav = self.navigator;
    if (typeof d.badge !== 'number' || !nav || !('setAppBadge' in nav)) return Promise.resolve();
    return (d.badge > 0 ? nav.setAppBadge(d.badge) : nav.clearAppBadge()).catch(() => {});
  };
  const tag = d.tag || 'studio';
  const show = self.registration.showNotification(d.title || 'Studio-Tool', {
    body: d.body || '', icon: '/static/icon-192.png', badge: '/static/icon-192.png', tag, renotify: d.type !== 'done', silent: d.type === 'done',
    data: { url: (typeof d.url === 'string' && d.url.startsWith('/')) ? d.url : '/' },
  });
  // "Erledigt": ersetzt die alte Meldung mit gleichem Tag und schließt sich nach ein paar Sekunden selbst
  const closeLater = d.type === 'done'
    ? show.then(() => new Promise(r => setTimeout(r, 4000))).then(() => self.registration.getNotifications({ tag })).then(list => list.forEach(n => n.close()))
    : show;
  e.waitUntil(Promise.all([closeLater, setBadge()]));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const open = list[0];
    if (open) { open.navigate(url).catch(() => {}); return open.focus(); }
    return self.clients.openWindow(url);
  }));
});
