/* Llano Lights' window service worker (Llano BL #12377).

   His 11-14 report: mid-show he pressed Update, the app stopped answering, and the window showed Edge's
   "Hmmm... can't reach this page, 127.0.0.1 refused to connect". 127.0.0.1 is the laptop itself: the
   app's own engine was not answering when the window loaded a page. Edge keeps this worker in the
   window's profile, so even with the engine down (and no internet) a page load in the window gets
   Llano Lights' own plain screen instead: what happened, Try again, and Start Llano Lights. It checks
   by itself and goes back to the app as soon as the engine answers.

   Only page loads are touched; every other request goes straight to the engine as before, and nothing
   is cached (each page carries its run's token, so an old copy must never be served). */
"use strict";

const PAGE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Llano Lights · not running</title>
<style>
  html, body { height:100%; margin:0; background:#07080b; color:#eceef5; font:15px/1.5 "Segoe UI", system-ui, sans-serif; }
  main { min-height:100%; display:flex; align-items:center; justify-content:center; text-align:center; padding:24px; box-sizing:border-box; }
  .box { max-width:460px; }
  h1 { font-size:20px; margin:0 0 10px; font-weight:600; }
  p { color:#9aa1b5; margin:8px 0; }
  .row { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; margin:20px 0 10px; }
  a.btn, button { font:inherit; color:#eceef5; background:#232a3d; border:1px solid #3a4258; border-radius:10px; padding:9px 18px;
                  cursor:pointer; text-decoration:none; }
  a.btn.go { background:#1f5c46; border-color:#2b6b52; }
  #state { color:#c5cbd8; min-height:1.5em; }
  body.small h1 { font-size:15px; } body.small p, body.small .row { display:none; } body.small #state { display:block; }
</style>
</head>
<body>
<main><div class="box">
  <h1>Llano Lights isn't running right now</h1>
  <p>This is your laptop's own Llano Lights, not the internet: it needs no Wi-Fi.</p>
  <p>If you just pressed Update, the new version opens by itself in about a minute.</p>
  <div class="row">
    <a class="btn go" href="llano-lights:start" id="start">Start Llano Lights</a>
    <button id="again" type="button">Try again</button>
  </div>
  <p>Or open Llano Lights from its icon on the desktop or the Start menu.</p>
  <p id="state" role="status" aria-live="polite">Checking every few seconds…</p>
</div></main>
<script>
"use strict";
if (window.top !== window) document.body.classList.add("small");   // the Live screen's stage picture
const say = (t) => { document.getElementById("state").textContent = t; };
// The engine answers on this window's port, or (a restart can take the next free one) on another of
// its ports 8765 to 8784: "" for here, the other address, or null when it isn't up anywhere.
const PORTS = Array.from({length: 20}, (_, i) => 8765 + i);
async function alive(base) {
  try {
    const r = await fetch(base + "/api/alive", {cache: "no-store"});
    return r.ok && (await r.json()).product === "llano-lights";
  } catch (e) { return false; }
}
async function where() {
  if (await alive("")) return "";
  const host = location.hostname === "localhost" ? "localhost" : "127.0.0.1";
  const found = await Promise.all(PORTS.filter(p => String(p) !== location.port)
    .map(p => alive("http://" + host + ":" + p).then(ok => ok ? "http://" + host + ":" + p + "/" : null)));
  return found.find(Boolean) || null;
}
let back = 0;
// Back: the starting copy closes this window and opens its own; if this one is still here a few
// seconds later (the app runs without its own window), it goes back to the app here.
async function check(now) {
  const at = await where();
  if (at !== null) {
    if (now || (back && Date.now() - back > 4000)) {
      say("Llano Lights is back. Opening it…");
      if (at) location.replace(at); else location.reload();
      return true;
    }
    if (!back) { back = Date.now(); say("Llano Lights is back. Opening it…"); }
  } else {
    back = 0;
    if (now) say("Still not answering. Press Start Llano Lights, or wait a moment if it is updating.");
  }
  return false;
}
document.getElementById("again").addEventListener("click", () => { say("Checking…"); check(true); });
document.getElementById("start").addEventListener("click", () => say("Starting Llano Lights… If Windows asks, choose Open."));
(async function loop() { if (!(await check(false))) setTimeout(loop, 2000); })();
</script>
</body>
</html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;   // the engine's API, pictures and sound: untouched
  e.respondWith(fetch(e.request).catch(() => new Response(PAGE, {
    status: 503, headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
  })));
});
