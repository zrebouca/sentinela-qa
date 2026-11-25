// Service worker: recebe o push mesmo com a tela em segundo plano
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('push', e => {
  let d = {titulo: 'Nova mensagem', texto: ''};
  try { d = {...d, ...e.data.json()}; } catch (_) { /* conteúdo inválido: usa o padrão */ }
  e.waitUntil(self.registration.showNotification(d.titulo, {body: d.texto, tag: 'chat'}));
});
