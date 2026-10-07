/* Network-only worker: never cache account data, chapters, or an old app shell. */
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()))
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate') return
  event.respondWith(fetch(event.request).catch(() => new Response(`<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f8fafc"><title>LegadoHub · 暂时离线</title>
<style>body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#f8fafc;color:#1e293b;font:16px/1.8 system-ui}main{max-width:28rem;padding:32px}a{color:#247a58}</style>
<main><h1>暂时无法连接</h1><p>联网后即可打开书架和继续阅读。已保存的 TXT 可在文件应用中查看。</p><a href="/console/library">重新连接</a></main></html>`, {
    status: 503,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
  })))
})
