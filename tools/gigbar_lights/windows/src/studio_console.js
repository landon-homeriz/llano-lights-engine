/* Llano Lights: the Light studio console (1.20.0, Llano PM #23195).

   ONE file, no framework, drawn by every screen: the laptop window (studio.html), the phone over the
   room's Wi-Fi (remote.html) and the phone app at llano.app/lights. His rule, 2026-11-12: the same
   buttons everywhere, and what one path truly cannot do stays in place, GRAYED, with the reason on
   it. So nothing here is hidden per screen: a screen hands in a `caps` map of reasons instead.

   LlanoStudio.mount(host, {
     transport: {                       how this screen reaches the laptop
       state()  -> Promise<state>         studio.Studio.public() + catalog + what runs (App.studio_state)
       send(cmd)-> Promise<{ok, error?, studio?}>   one studio command (studio.Studio.command)
       stop()   -> Promise<{ok, error?}>  Stop the show
       run?(mode), peek?(key), ack?()     laptop window only
       settings?() -> Promise<{settings}>   the saved show settings (settings_contract), and
       change?(ops) -> Promise<{ok, settings?, error?}>   a change to them: [{path, value}]. With both,
                                          the console draws the Settings panel (tonight's lights,
                                          strobe, drops, colors), so they work on every path
     },
     caps: {steer, drag, hover, peek, run, setup, hits, slow} or a function returning it.
           "" = works; a sentence = grayed with that reason; hits: "latch" = tap on, tap off;
           drag: a sentence = a tap on the floor still sends the spot there, dragging it says why not;
           slow: true = a press takes a second or two to show (the internet path), so the button
           pressed pulses until the laptop answers and a second tap on it is not sent twice
     layout: "wide" | "phone",
     stageFrame: "/preview?embed=1&stage=1"   the room picture to steer on (laptop); without it the
                                              console draws its own floor plan
     keys: true,                        the keyboard drives it (laptop)
     screen: "laptop" | "phone",        which kind of screen this is: its View from is kept per venue
     links: {setup, shows},             where Set up and Shows open
     link: () => "Wi-Fi" | "Internet",  which path a phone is on, shown in the top strip
     lostText: "...",                  what the screen says when the laptop stops answering (5 s with no answer:
                                        every control but STOP dims and takes no taps until it answers again)
     lostLink: {href, text},            a way out shown under that message (the phone: the internet path)
     pollMs, onState(state), onLost(failures)
   }) -> {destroy(), refresh()}

   A page that has bars of its own (llano.app) sets two CSS variables on the host so the phone's
   floating STOP and the messages clear them: --lls-stop-top and --lls-toast-bottom (lengths).

   A byte-identical copy lives in the Llano repo (llano-ui/public/lights/studio_console.js); the
   sha of this file is pinned in both repos' tests, like settings_contract.py. */
(function () {
"use strict";

// The moving heads' real color wheel as dots in rainbow order: [name, color, wheel slot] (the slot
// order is what the units really show, Llano BL #12147; rig.py HEAD_WHEEL), and the colors a look can take.
var WHEEL = [["White", "#ffffff", 0], ["Red", "#ff3030", 3], ["Orange", "#ff9020", 2], ["Yellow", "#ffe030", 5],
             ["Green", "#30ff60", 6], ["Light blue", "#40c8ff", 4], ["Dark blue", "#2040ff", 1], ["Purple", "#a040ff", 7]];
var COLORS = [["", "As designed"], ["#ffd9a3", "Warm white"], ["#ffffff", "White"], ["#ff9ac0", "Rose"],
              ["#ff5a5a", "Red"], ["#ffb454", "Amber"], ["#7cf0c8", "Mint"], ["#6cb8ff", "Blue"], ["#a395ff", "Violet"]];
var TAGS = {still: "Nothing moves", fade: "Slow fade", music: "With the music", move: "Heads move", quiet: "Ignores music"};
// One keyboard row per page, so every pad is one key away whichever page is showing.
var PAD_KEYS = {simple: "123456789", wedding: "qwertyui", party: "zxcvnm"};
var ZONE_SHORT = {main: "Everything", wash: "Color wash", sticks: "Freedom Sticks", heads: "Moving heads", fx: "Derby, laser, strobe"};
var SPEED_NAMES = {"0.5": "Half", "1": "Normal", "2": "Double"};
var PACE_NAMES = {slow: "Slow", walk: "Walking", fast: "Fast"};
var MOTION_NAMES = {"": "As designed", still: "Still", slow: "Slow"};
var HIT_NAMES = {whiteout: "White-out", strobe: "Strobe", burst: "Color burst"};

var CSS = [
".lls{--bg:#07080b;--panel:#0e1016;--raise:#161a25;--line:#262b3a;--text:#eceef5;--dim:#9aa1b5;--faint:#646b80;--mint:#7cf0c8;--amber:#ffb454;--red:#ff6b6b;--violet:#a395ff;--blue:#6cb8ff;",
"  background:var(--bg);color:var(--text);font:14px/1.35 'Segoe UI',system-ui,-apple-system,sans-serif;position:relative;-webkit-tap-highlight-color:transparent}",
".lls *{box-sizing:border-box}",
".lls [hidden]{display:none!important}",
".lls button{font:inherit;color:inherit;background:none;border:0;padding:0;margin:0;cursor:pointer;text-align:inherit}",
".lls h3{margin:0 0 8px;font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--dim);font-weight:700}",
".lls kbd{font:600 10.5px Consolas,monospace;color:var(--dim);border:1px solid var(--line);border-radius:4px;padding:1px 5px;background:#0b0d13;text-transform:uppercase}",
".lls .off{opacity:.42;cursor:not-allowed}",
".lls .why{font-size:11.5px;color:var(--amber);line-height:1.3}",
".lls .wait{animation:lls-wait .7s ease-in-out infinite alternate;cursor:progress}",
"@keyframes lls-wait{from{opacity:.5}to{opacity:.95}}",
"@media (prefers-reduced-motion:reduce){.lls .wait{animation:none;opacity:.6}}",
".lls-tag{display:inline-block;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;font-weight:700;padding:2px 5px;border-radius:4px;background:#1d2231;color:var(--dim);white-space:nowrap}",
".lls-tag.still,.lls-tag.quiet{color:#bfe9ff;background:#12283a}.lls-tag.music{color:#ffd9a3;background:#3a2a10}.lls-tag.move{color:#d9d2ff;background:#231f45}.lls-tag.fade{color:#bff5df;background:#103327}",
/* top strip */
".lls-top{display:flex;align-items:stretch;gap:10px;padding:9px 14px;border-bottom:1px solid var(--line);background:#090b10}",
".lls-brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;padding-right:6px;white-space:nowrap}",
".lls-brand i{width:11px;height:11px;border-radius:50%;background:var(--faint)}",
".lls-brand i.beat{background:var(--mint);box-shadow:0 0 14px 2px #7cf0c866}",
".lls-chip{flex:1;min-width:0;line-height:1.22;overflow:hidden;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:5px 11px;display:flex;flex-direction:column;justify-content:center}",
".lls-chip small{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;color:var(--faint)}",
".lls-chip b{font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}",
".lls-chip span{font-size:11.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".lls-chip .row{display:flex;align-items:center;gap:8px;min-width:0}",
".lls-chip.show{flex:2.8;border-color:#7cf0c855}.lls-chip.show small{color:var(--mint)}",
".lls-chip.held{flex:1.6}.lls-chip.held.on{border-color:var(--amber);background:#1d1508;box-shadow:0 0 18px -6px var(--amber)}.lls-chip.held.on small{color:var(--amber)}",
".lls-chip.spot{flex:1.1}.lls-chip.spot span{white-space:normal;line-height:1.2}.lls-chip.spot.on{border-color:var(--blue);background:#0b1826}.lls-chip.spot.on small{color:var(--blue)}",
".lls-chip.next small{color:var(--violet)}",
".lls-chip.dimmed{opacity:.6}",
".lls .lls-rel{margin-left:auto;flex:none;font-size:11px;font-weight:700;color:#1a1200;background:var(--amber);border-radius:6px;padding:3px 8px}",
".lls-tags{display:flex;align-items:center;gap:4px;margin-top:2px;min-width:0}.lls-tags:empty{display:none}",
".lls-tags em{font-style:normal;font-size:11.5px;color:var(--text);font-weight:600;white-space:nowrap;margin-right:2px}",
".lls .lls-tags .lls-mini{padding:1px 7px;color:var(--dim)}.lls .lls-tags .lls-mini.on{color:var(--text);border-color:var(--mint);background:#0d2219}",
".lls .lls-mini{flex:none;font-size:11px;font-weight:700;border:1px solid var(--line);border-radius:6px;padding:2px 8px;color:var(--text);background:var(--raise)}",
".lls .lls-mini.go{margin-left:auto;border-color:#7cf0c877;color:var(--mint)}",
".lls-health{display:flex;flex-direction:column;justify-content:center;gap:3px;font-size:11px;color:var(--dim);white-space:nowrap}",
".lls-health i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--faint);margin-right:5px}",
".lls-health .ok i{background:var(--mint)}.lls-health .bad i{background:var(--red)}.lls-health .bad{color:#ffb3b3}",
".lls .lls-stop{align-self:center;border:1.5px solid var(--red);color:var(--red);font-weight:700;border-radius:10px;padding:10px 16px;font-size:13px;white-space:nowrap}",
".lls .lls-stop:active{background:var(--red);color:#1a0505}",
".lls .lls-lock,.lls .lls-link{align-self:center;border:1px solid var(--line);color:var(--dim);border-radius:10px;padding:10px 11px;font-size:12px;white-space:nowrap;text-decoration:none}",
".lls .lls-lock.on{border-color:var(--amber);color:var(--amber);background:#1d1508}",
".lls-banner{display:flex;gap:12px;align-items:center;padding:8px 14px;background:#1d150a;border-bottom:1px solid var(--line);font-size:13px}",
".lls-banner[hidden]{display:none}.lls-banner span{flex:1}",
".lls-banner button{border:1px solid var(--line);border-radius:8px;padding:5px 12px;background:var(--raise)}",
/* middle */
".lls-col{padding:12px;overflow:auto;min-height:0}",
".lls .lls-step{display:flex;width:100%;gap:9px;align-items:center;padding:6px 8px;border-radius:8px;font-size:12.5px;color:var(--dim);border:1px solid transparent}",
".lls-step i{flex:none;width:8px;height:8px;border-radius:50%;border:1.5px solid var(--faint)}",
".lls-step span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".lls-step em{margin-left:auto;font-style:normal;font-size:10.5px;color:var(--faint);white-space:nowrap}",
".lls .lls-step{flex-wrap:wrap}.lls-step em.stopq{flex-basis:100%;margin:1px 0 0 17px;white-space:normal;color:var(--amber)}",
".lls-steppress{margin:2px 0 6px 25px;font-size:12px;color:var(--text);line-height:1.35}",
".lls .lls-steppress button{display:inline-block;margin-top:6px;border:1px solid #7cf0c877;color:var(--mint);border-radius:8px;padding:6px 12px;font-weight:700}",
/* Now: what Mixxx is doing at this step and what to press to move on, always in full (BL #11473) */
".lls-nowbox{margin-top:9px;border:1px solid #7cf0c855;background:#0d1a16;border-radius:10px;padding:9px 11px;font-size:12.5px;line-height:1.38;flex:none}",
".lls-nowbox small{display:block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;color:var(--mint)}",
".lls-nowbox b{display:block;font-size:14px;margin:1px 0 3px;overflow-wrap:anywhere}.lls-nowbox p{margin:0 0 4px;color:var(--dim);overflow-wrap:anywhere}",
".lls-nowbox p.press{margin:0 0 4px;color:var(--text);font-weight:600}.lls-nowbox p.wait{margin:0}.lls-nowbox p.press span{color:var(--mint)}",
/* the laptop stopped answering: everything dims and takes no taps, one message says why */
/* (each part dimmed by itself: opacity on the top strip would trap the fixed STOP under the bar) */
/* STOP always takes a press (a guess from the clock must never swallow it), and the dots that say why stay bright */
".lls.lls-lost .lls-top>*:not(.lls-stop):not(.lls-health),.lls.lls-lost .lls-mid>*,.lls.lls-lost>.lls-banner,.lls.lls-lost>.lls-bot{opacity:.3;pointer-events:none}",
".lls-lostmsg{position:fixed;left:12px;right:12px;top:calc(var(--lls-stop-top,0px) + 74px + env(safe-area-inset-top,0px));z-index:45;max-width:560px;margin:0 auto;background:#2a0f12;border:1px solid var(--red);color:#ffd6d6;border-radius:12px;padding:12px 14px;font-size:14px;line-height:1.4;box-shadow:0 10px 40px #000c}",
".lls-wide .lls-lostmsg{top:calc(var(--lls-toph,92px) + 8px)}.lls-lostmsg a{display:inline-flex;align-items:center;margin-top:8px;color:#fff;min-height:44px}",
".lls-said{font-size:12.5px}",
".lls-step.done{opacity:.5}.lls-step.done i{background:var(--faint)}",
".lls .lls-step.now{background:#0d1a16;color:var(--text);border-color:#7cf0c855;font-weight:600}.lls-step.now i{background:var(--mint);border-color:var(--mint);box-shadow:0 0 10px var(--mint)}",
".lls .lls-step.next{color:var(--text);border:1px dashed #a395ff88}.lls-step.next i{border-color:var(--violet)}",
".lls .lls-nextbtn{display:block;margin-top:9px;width:100%;text-align:center;background:var(--violet);color:#0b0820;font-weight:700;font-size:14px;border-radius:10px;padding:11px 8px;box-shadow:0 0 22px -6px var(--violet)}",
".lls-nextbtn small{display:block;font-weight:600;font-size:11px;opacity:.75}",
".lls .lls-follow{display:block;width:100%;margin-top:7px;text-align:center;border:1px solid var(--line);border-radius:10px;padding:7px;font-size:12px;color:var(--dim)}",
".lls-night .note{font-size:11.5px;color:var(--faint);margin:8px 2px 0;line-height:1.35}.lls-wide .lls-night .note{display:none}",
/* cocktail hour and dinner's mood (BL #12340): one color or a slow fade, the same two choices as the Shows page */
".lls-moods{margin:10px 2px 0}.lls-mood{margin:0 0 8px}.lls-mood b{display:block;font-size:12px;margin:0 0 4px}",
".lls-mood .k{display:flex;gap:4px;margin:0 0 4px}.lls-mood .k button{flex:1;font-size:11.5px;padding:4px 6px}",
".lls-mood .k button.on{outline:2px solid var(--accent)}.lls-mood .sw{display:flex;gap:5px;flex-wrap:wrap}",
".lls-mood .sw button{width:24px;height:24px;border-radius:50%;border:1px solid var(--line);padding:0}",
".lls-mood .sw button.on{outline:2px solid var(--text);outline-offset:1px}",
".lls-stage{position:relative;padding:10px 12px 8px;display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden}",
".lls-stagebox{flex:1 1 0;min-height:150px;position:relative;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:radial-gradient(ellipse at 50% 30%,#121624 0%,#090b11 70%)}",
".lls-stagebox iframe,.lls-stagebox canvas{position:absolute;inset:0;width:100%;height:100%;border:0;display:block;touch-action:none}",
".lls-stagebox .cover{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:16px;color:var(--dim);font-size:13px;pointer-events:none}",
".lls-stagebar{display:flex;align-items:center;gap:7px;margin-top:8px;font-size:12px;color:var(--dim);flex-wrap:wrap;flex:none}",
".lls-stagebar .sp{flex:1}",
".lls-heads{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);background:var(--panel);color:var(--text);white-space:nowrap}",
".lls-heads b{font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint)}",
".lls-heads i{width:8px;height:8px;border-radius:50%;background:var(--mint)}.lls-heads.stop i{background:var(--red)}.lls-heads.yours i{background:var(--violet)}",
".lls-view{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}",
".lls .lls-stagebar .lls-seg button{padding:4px 11px}",
".lls-stagehelp{margin-top:6px;font-size:12px;color:var(--dim);flex:none;min-height:1.3em}",
".lls .lls-pill{border:1px solid var(--line);border-radius:999px;padding:4px 11px;background:var(--panel);color:var(--text);font-size:12px;white-space:nowrap;display:inline-flex;align-items:center;gap:6px}",
".lls .lls-pill.on{background:var(--blue);color:#06131f;border-color:var(--blue);font-weight:700}",
".lls .lls-pill.mk{border-color:#6cb8ff66}",
".lls .lls-pill .x{color:var(--faint);font-weight:700;padding:0 2px}",
".lls-ptabs{display:flex;gap:2px;margin-bottom:10px}",
".lls .lls-ptabs button{flex:1 1 auto;min-width:0;white-space:nowrap;text-align:center;font-size:10.5px;letter-spacing:.02em;text-transform:uppercase;font-weight:700;color:var(--dim);padding:5px 4px;border-radius:999px;border:1px solid transparent}",
".lls .lls-ptabs button.on{color:var(--text);background:var(--raise);border-color:var(--line)}",
".lls-mst{margin-bottom:9px}",
".lls-mst .l{display:flex;justify-content:space-between;font-size:12px;margin-bottom:2px}.lls-mst .l b{font-weight:600}.lls-mst .l span{color:var(--dim);font-variant-numeric:tabular-nums}",
".lls input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:22px;background:none;margin:0;display:block;touch-action:pan-y}",
".lls input[type=range]::-webkit-slider-runnable-track{height:9px;border-radius:5px;background:linear-gradient(90deg,var(--mint) var(--v,100%),#1b2030 var(--v,100%))}",
".lls input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:19px;height:19px;border-radius:50%;background:#fff;margin-top:-5px;box-shadow:0 1px 4px #000}",
".lls input[type=range]::-moz-range-track{height:9px;border-radius:5px;background:#1b2030}",
".lls input[type=range]::-moz-range-progress{height:9px;border-radius:5px;background:var(--mint)}",
".lls input[type=range]::-moz-range-thumb{width:19px;height:19px;border:0;border-radius:50%;background:#fff}",
".lls-seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;font-size:11.5px}",
".lls .lls-seg button{flex:1;text-align:center;padding:6px 2px;color:var(--dim);border-right:1px solid var(--line)}.lls .lls-seg button:last-child{border-right:0}",
".lls .lls-seg button.on{background:var(--raise);color:var(--text);font-weight:700}",
".lls-side h3{margin-top:12px}.lls-side h3:first-child{margin-top:0}",
".lls-dots{display:flex;gap:7px;align-items:center;flex-wrap:wrap}",
".lls .lls-dot{width:20px;height:20px;border-radius:50%;border:2px solid #0000;box-shadow:inset 0 0 0 1px #ffffff22}",
".lls .lls-dot.on{border-color:#fff}",
".lls .lls-dot.none{background:repeating-linear-gradient(45deg,#2a3042 0 4px,#161a25 4px 8px)}",
".lls-note{font-size:12px;color:var(--dim);line-height:1.35}",
".lls-music{display:block;margin-top:4px;font-size:11.5px}",  // Llano BL #12410: who plays the music, said once, always
/* saved settings: tonight's lights, strobe, drops, colors */
".lls-row{display:flex;align-items:center;gap:8px;font-size:12.5px;margin-bottom:7px}.lls-row>span:first-child{flex:1;min-width:0}",
".lls-count{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:8px;overflow:hidden}",
".lls .lls-count button{width:30px;text-align:center;padding:5px 0;font-weight:700;background:var(--panel)}.lls-count b{min-width:26px;text-align:center;font-variant-numeric:tabular-nums}",
".lls .lls-count button:disabled{opacity:.35;cursor:default}",
".lls select{font:inherit;font-size:12px;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 6px;max-width:112px}",
".lls-sw{display:inline-flex;gap:2px;flex:none}.lls-sw i{width:9px;height:14px;border-radius:2px;display:block}",
".lls input[type=range].lls-hue::-webkit-slider-runnable-track{background:linear-gradient(90deg,#f33,#fb0,#ff3,#3f6,#3ff,#37f,#a3f,#f3d,#f33)}",
".lls input[type=range].lls-hue::-moz-range-track{background:linear-gradient(90deg,#f33,#fb0,#ff3,#3f6,#3ff,#37f,#a3f,#f3d,#f33)}",
".lls input[type=range].lls-hue::-moz-range-progress{background:none}",
".lls-pair{display:grid;grid-template-columns:18px 1fr 1fr;gap:6px;align-items:center;margin-bottom:2px}.lls-pair i{width:18px;height:18px;border-radius:5px}",
".lls-lights{display:grid;grid-template-columns:1fr 1fr;gap:6px}",
".lls .lls-light{border:1px solid var(--line);border-radius:8px;padding:6px 8px;font-size:12px;background:var(--panel);display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden}",
".lls .lls-light.on{border-color:var(--blue);background:#0b1826}",
".lls-light i{flex:none;width:8px;height:8px;border-radius:50%;background:#2b3040}.lls-light.touch i{background:var(--amber)}.lls-light.pin i{background:var(--violet)}",
".lls-btns{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}",
/* the cue timeline (Llano PM #23787) */
".lls-tl svg{display:block;width:100%;border-radius:8px;background:#0b0d13;border:1px solid var(--line);touch-action:manipulation;cursor:pointer}",
".lls-tl .lls-tlhead{display:flex;align-items:baseline;gap:8px;margin-bottom:6px}.lls-tl .lls-tlhead b{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
".lls-tl .lls-tltime{font:600 13px Consolas,monospace;color:var(--mint)}",
".lls-tl .lls-tlsel{margin-top:8px;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--raise)}",
".lls-tl .lls-sw{width:26px;height:26px;border-radius:50%;border:2px solid #0008}",
".lls-tl .lls-tllist button{display:block;width:100%;padding:4px 6px;border-radius:6px;font-size:12px}.lls-tl .lls-tllist button.on{background:var(--raise);color:var(--mint)}",
".lls .lls-btn{border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:12px;background:var(--panel)}",
".lls .lls-btn.on{border-color:var(--amber);color:var(--amber)}",
/* bottom */
".lls-bot{border-top:1px solid var(--line);background:#090b10;padding:9px 14px 10px;display:flex;flex-direction:column;gap:7px;min-height:0}",
".lls-tabs{display:flex;align-items:center;gap:6px;min-width:0;flex-wrap:wrap}",
".lls .lls-tabs .t{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;color:var(--dim);padding:4px 11px;border-radius:999px;border:1px solid transparent;white-space:nowrap}",
".lls .lls-tabs .t.on{color:var(--text);background:var(--raise);border-color:var(--line)}",
".lls-tabs .t i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--amber);margin-left:5px}",
".lls-tweak{display:flex;gap:6px;align-items:center;font-size:11.5px;color:var(--dim);margin-left:10px;white-space:nowrap}",
".lls-tweak .lls-seg{font-size:11px}.lls .lls-tweak .lls-seg button{padding:3px 8px}",
".lls-tabs .hint{margin-left:auto;font-size:11.5px;color:var(--faint);min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
".lls-pads{display:grid;grid-template-columns:repeat(var(--n,6),minmax(0,1fr));gap:8px;min-height:0}",
".lls .lls-pad{border:1px solid var(--line);border-radius:11px;background:var(--panel);padding:9px 10px 7px;display:flex;flex-direction:column;gap:3px;position:relative;overflow:hidden;min-height:96px;text-align:left}",
".lls-pad .sw{position:absolute;left:0;right:0;top:0;height:4px}",
".lls-pad b{font-size:14px;font-weight:650;margin-top:2px;display:flex;align-items:center;gap:6px}.lls-pad b kbd{margin-left:auto}",
".lls-pad p{margin:0;font-size:11.5px;color:var(--dim);line-height:1.3;flex:1}",
".lls-pad .tg{display:flex;gap:4px;flex-wrap:wrap}",
".lls .lls-pad.on{border-color:var(--amber);background:#1d1508;box-shadow:0 0 26px -8px var(--amber),inset 0 0 0 1px var(--amber)}",
".lls-pad.on .tg::after{content:'HELD · tap to release';margin-left:auto;font-size:9.5px;font-weight:800;letter-spacing:.06em;color:var(--amber)}",
".lls-pad .del{position:absolute;right:7px;top:10px;font-size:10.5px;color:var(--faint);border:1px solid var(--line);border-radius:6px;padding:1px 6px;background:#0b0d13}",
".lls-pads .empty{grid-column:1/-1;color:var(--dim);font-size:12.5px;padding:18px 4px}",
".lls-hits{display:flex;gap:8px;align-items:center;flex-wrap:wrap}",
".lls .lls-hit{border:1px solid var(--line);border-radius:999px;padding:7px 14px;font-size:12.5px;font-weight:600;background:var(--panel);white-space:nowrap;user-select:none;-webkit-user-select:none;touch-action:manipulation}",
".lls-hit small{color:var(--faint);font-weight:600;margin-left:6px;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase}",
".lls .lls-hit.w{border-color:#ffffff66}.lls .lls-hit.r{border-color:#ff6b6b88;color:#ffc2c2}",
".lls .lls-hit.on{background:#fff;color:#07080b;border-color:#fff}.lls .lls-hit.r.on{background:var(--red);border-color:var(--red);color:#1a0505}.lls .lls-hit.f.on{background:var(--amber);border-color:var(--amber);color:#1a1200}",
".lls .lls-hit:disabled{opacity:.4;cursor:default}",
".lls-hits .sp{flex:1}",
".lls-toast{position:fixed;left:50%;bottom:var(--lls-toast-bottom,22px);transform:translateX(-50%);max-width:min(560px,calc(100vw - 24px));background:#1b2030;border:1px solid var(--line);border-radius:12px;padding:10px 14px;font-size:13px;box-shadow:0 10px 40px #000a;z-index:50;display:flex;gap:10px;align-items:center;pointer-events:none}",
".lls-toast.ask{pointer-events:auto}",
".lls-toast[hidden]{display:none}",
".lls-toast input{font:inherit;color:var(--text);background:#0b0d13;border:1px solid var(--line);border-radius:8px;padding:6px 9px;min-width:0;flex:1}",
".lls-toast button{border:1px solid var(--line);border-radius:8px;padding:6px 11px;background:var(--raise);white-space:nowrap}",
".lls-toast button.go{background:var(--mint);border-color:var(--mint);color:#06120d;font-weight:700}",
/* the laptop: one screen, nothing scrolls */
".lls-wide{height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;grid-template-columns:minmax(0,1fr);overflow:hidden}",
".lls-wide>.lls-top{grid-row:1}.lls-wide>.lls-banner{grid-row:2}.lls-wide>.lls-mid{grid-row:3}.lls-wide>.lls-bot{grid-row:4}",
".lls-wide .lls-mid{display:grid;grid-template-columns:226px minmax(0,1fr) 244px;min-height:0;overflow:hidden}",
".lls-wide .lls-night{display:flex;flex-direction:column}.lls-wide .lls-night>*{flex:none}.lls-wide .lls-night>.lls-steps{flex:0 1 auto;min-height:max(44px,calc(100vh - 656px));overflow:auto}.lls-wide .lls-nowbox{font-size:11.5px;padding:8px 9px}.lls-wide .lls-nowbox p.wait{font-size:10.5px;line-height:1.3}.lls-wide .lls-nowbox b{font-size:13px}",
".lls-wide .lls-night{border-right:1px solid var(--line)}.lls-wide .lls-side{border-left:1px solid var(--line)}",
".lls-wide [data-panel]{display:none}.lls-wide [data-panel].on{display:block}",
".lls-wide .lls-tabs{flex-wrap:nowrap}.lls-wide .lls-tabs .hint{flex:1;text-align:right}",
/* a laptop window under ~1,300 px wraps the cards' words onto a second line instead of cutting them off (BL #12460) */
".lls-wide .lls-chip>span,.lls-wide .lls-chip b,.lls-wide .lls-tabs .hint{white-space:normal;line-height:1.2;overflow-wrap:anywhere}",
"@media (max-height:720px){.lls-wide .lls-pad{min-height:78px}.lls-wide .lls-pad p{font-size:11px;line-height:1.25}}",
/* a short AND narrow laptop (1024x700): eight pads a row; the whole line still shows, a size smaller, so the room picture never shrinks */
"@media (max-height:720px) and (max-width:1100px){.lls-wide .lls-pad{padding:7px 8px 6px;gap:2px}.lls-wide .lls-pad b{font-size:13px}.lls-wide .lls-pad p{font-size:10px;line-height:1.2}.lls-wide .lls-pad .tg{gap:3px}.lls-wide .lls-pad .lls-tag{font-size:8.5px;padding:1px 4px}}",
/* at 1024 wide: the brand keeps only its dot and the hit buttons fit one row, so the Now box has room */
"@media (max-width:1100px){.lls-wide .lls-hits{gap:6px;flex-wrap:nowrap}.lls-wide .lls-hit{padding:6px 9px;font-size:12px}.lls-wide .lls-hit small{margin-left:4px}.lls-wide .lls-hits>.lls-tag{white-space:normal;max-width:76px;line-height:1.15}.lls-wide .lls-brand span{display:none}.lls-wide .lls-lock,.lls-wide .lls-link{padding:10px 9px}.lls-wide .lls-health{display:none}.lls-wide .lls-mid{grid-template-columns:206px minmax(0,1fr) 214px}}",
/* the phone: one column, thumbs */
".lls-phone{min-height:100%;padding:64px 0 28px;display:flex;flex-direction:column}",
".lls-bar{display:none}.lls-phone .lls-bar{display:block;position:fixed;left:0;right:0;top:var(--lls-stop-top,0px);height:calc(64px + env(safe-area-inset-top,0px));z-index:39;background:#07080b;border-bottom:1px solid var(--line)}",
".lls-phone .lls-brand{position:fixed;left:14px;top:calc(var(--lls-stop-top,0px) + 8px + env(safe-area-inset-top,0px));height:48px;z-index:40}",
/* the phone's order, top to bottom: what is on, Next, the pads and hold buttons, then spots, levels, lights */
".lls-phone>.lls-top{order:0}.lls-phone>.lls-banner{order:1}.lls-phone .lls-mid{display:contents}",
".lls-phone .lls-night{order:2;display:flex;flex-direction:column}.lls-phone>.lls-bot{order:3}.lls-phone .lls-stage{order:4}.lls-phone .lls-side{order:5}",
".lls-phone .lls-night .lls-nextbtn{order:-2;margin:0 0 8px}.lls-phone .lls-night .lls-follow{order:-1;margin:0 0 10px}",
".lls-phone .lls-top{flex-wrap:wrap;padding:10px 12px}",
/* STOP floats in the corner so it is always under a thumb, wherever the page is scrolled */
".lls-phone .lls-stop{position:fixed;top:calc(var(--lls-stop-top,0px) + 8px + env(safe-area-inset-top,0px));right:12px;z-index:40;background:#07080b;height:48px;min-width:96px;display:flex;align-items:center;justify-content:center;font-size:15px}",
".lls-phone .lls-top .lls-chip{flex:1 1 100%;padding:8px 12px}.lls-phone .lls-chip b{font-size:15px}.lls-phone .lls-chip span{font-size:12.5px;white-space:normal}",
".lls-phone .lls-chip.spot,.lls-phone .lls-chip.next,.lls-phone .lls-lock{display:none}",
".lls-phone .lls-health{flex-direction:row;gap:10px;flex-wrap:wrap}",

".lls-phone .lls-col,.lls-phone .lls-stage{padding:12px;overflow:visible}",

".lls-phone .lls-nextbtn{font-size:16px;padding:14px}",
".lls-phone .lls-steps{max-height:150px;overflow:auto;border:1px solid var(--line);border-radius:10px;padding:4px}",
".lls-phone .lls-chip b{white-space:normal}",

".lls-phone .lls-stagebox{flex:none;height:min(72vw,330px)}",
".lls-phone .lls-ptabs{display:none}.lls-phone [data-panel]{margin-bottom:18px}",
".lls-phone .lls-side{display:flex;flex-direction:column}.lls-phone [data-panel=spot]{order:-1}",
".lls-phone .lls-bot{border-top:0;border-bottom:1px solid var(--line);padding:12px}",
".lls-phone .lls-pads{grid-template-columns:1fr 1fr;gap:9px}.lls-phone .lls-pad b{font-size:15px}.lls-phone .lls-pad kbd{display:none}",
".lls-phone .lls-hit{flex:1;text-align:center;padding:13px 8px;border-radius:14px}.lls-phone .lls-hits .sp{display:none}",
".lls-phone .lls-tabs .hint,.lls-phone kbd{display:none}.lls-phone .lls-tweak{margin-left:0;flex-basis:100%;flex-wrap:wrap}",
".lls-phone .lls-pill{padding:9px 13px;font-size:13px}.lls-phone .lls-btn{padding:10px 12px;font-size:13px}",
".lls-phone .lls-seg button{padding:10px 2px;font-size:12.5px}.lls-phone .lls-dot{width:28px;height:28px}",
".lls-phone .lls-light{padding:10px 8px}",
/* Tap sizes in a dark room (BL #11473): on the phone every button, chip, swatch, tab and row is at
   least 44 px tall and wide, with at least 8 px between neighbours */
".lls-phone .lls-mini,.lls-phone .lls-rel{min-height:44px;min-width:44px;display:inline-flex;align-items:center;justify-content:center;padding:0 14px;font-size:13px}",
".lls-phone .lls-chip .row{flex-wrap:wrap;gap:8px}.lls-phone .lls-tags{flex-wrap:wrap;gap:8px}",
".lls-phone .lls-step{min-height:44px;padding:8px 10px;margin-bottom:8px;font-size:14px}",
".lls-phone .lls-step em.stopq{flex-basis:auto;margin:0 0 0 auto}.lls-phone .lls-step span{white-space:normal;overflow-wrap:anywhere}",
/* the list shows whole rows only: each row snaps to the top of the box */
".lls-phone .lls-steps{scroll-snap-type:y mandatory;scroll-padding:4px}.lls-phone .lls-step{scroll-snap-align:start}",
".lls-phone .lls-steppress button,.lls-phone .lls-follow{min-height:44px}.lls-phone .lls-steppress{scroll-snap-align:end;padding-bottom:4px}",
".lls-phone .lls-btn,.lls-phone .lls-pill,.lls-phone .lls-seg button,.lls-phone .lls-tabs .t,.lls-phone .lls-light,.lls-phone select{min-height:44px;min-width:44px}",
".lls-phone .lls-pill,.lls-phone .lls-tabs .t{display:inline-flex;align-items:center;justify-content:center}",
".lls-phone .lls-tabs{gap:8px}.lls-phone .lls-tabs .t{padding:0 14px}",
".lls-phone .lls-mood .k{gap:8px}.lls-phone .lls-mood .sw{gap:8px}.lls-phone .lls-mood .sw button{width:44px;height:44px}",
".lls-phone .lls-dots{gap:8px}.lls-phone .lls-dot{width:44px;height:44px}",
".lls-phone .lls-seg{border:0;gap:8px;overflow:visible;flex-wrap:wrap}.lls-phone .lls-seg button{flex:1 0 auto;padding:0 12px;white-space:nowrap;border:1px solid var(--line);border-radius:8px}.lls-phone .lls-tweak{white-space:normal}.lls-phone .lls-tweak .lls-seg{flex:1}.lls-phone .lls-seg button:last-child{border-right:1px solid var(--line)}",
".lls-phone .lls-stagebar{gap:8px}.lls-phone .lls-view{flex-wrap:wrap;gap:8px}",
".lls .lls-markx{color:var(--faint);font-weight:700;padding:4px 10px}.lls .lls-markx.arm{color:#1a0505;background:var(--red);border-color:var(--red)}",
".lls-phone .lls-count{border:0;gap:8px;overflow:visible}.lls-phone .lls-count button{width:44px;height:44px;border:1px solid var(--line);border-radius:8px}",
".lls-phone .lls-btns,.lls-phone .lls-hits{gap:8px}.lls-phone .lls-lights{gap:8px}.lls-phone .lls-pads{gap:10px}",
".lls-phone .lls-hit{min-height:48px}",
".lls-phone input[type=range]{height:44px}",
".lls-phone .lls-toast button{min-height:44px;min-width:64px}.lls-phone .lls-toast input{min-height:44px}",
/* a saved look's Delete: its own row at the foot of the pad, a full-size target */
".lls-phone .lls-pad .del{position:static;align-self:flex-end;min-height:44px;min-width:80px;display:inline-flex;align-items:center;justify-content:center;margin-top:6px;font-size:13px}",
/* nothing a button says is cut off (BL #11473) */
".lls .lls-light{white-space:normal;line-height:1.2}",
".lls-phone .lls-heads{min-height:44px}",
/* Show settings sit in a fold, shut by default: change these at home, not during the party */
".lls-fold,.lls-livefold{border:1px solid var(--line);border-radius:10px;background:var(--panel)}",
".lls-fold>summary,.lls-livefold>summary{min-height:48px;display:flex;align-items:center;padding:10px 14px;font-weight:700;font-size:14px;cursor:pointer;list-style:none}",
".lls-fold>summary::-webkit-details-marker,.lls-livefold>summary::-webkit-details-marker{display:none}.lls-fold>summary::before,.lls-livefold>summary::before{content:'\\25B8';margin-right:9px;color:var(--dim)}.lls-fold[open]>summary::before,.lls-livefold[open]>summary::before{content:'\\25BE'}",
".lls-fold>div{padding:4px 14px 14px}.lls-fold:not([open])>div{display:none}",
/* The phone's Live screen is the party first (Llano BL #12419): the heads, the levels and touch-a-light
   sit in folds under the pads, each title saying what it is set to now, so a shut fold hides no state */
".lls-folds{display:none}.lls-phone .lls-folds{order:4;display:flex;flex-direction:column;gap:10px;padding:12px}",
".lls-livefold>summary{justify-content:space-between;gap:10px}.lls-livefold>summary>span:first-child{flex:1}",
".lls-foldnow{font-weight:500;font-size:12.5px;color:var(--dim);text-align:right}.lls-foldnow.warn{color:var(--amber,#ffb454)}",
".lls-livefold:not([open])>div{display:none}.lls-livefold>div{padding:0 0 6px}.lls-livefold [data-panel]{padding:0 12px}",
/* a warning from the laptop (lights not connected...) sits in the top bar in place of the name,
   so nothing under a finger moves when it comes and goes; a tap shows all of it */
".lls-phone .lls-banner{position:fixed;left:12px;right:120px;top:calc(var(--lls-stop-top,0px) + 8px + env(safe-area-inset-top,0px));height:48px;z-index:41;padding:4px 10px;border:1px solid #ffb45466;border-radius:10px;background:#1d150a;font-size:12px;line-height:1.25;overflow:hidden;cursor:pointer;gap:6px}",
".lls-phone .lls-banner span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}",
".lls-phone .lls-banner button{display:none}",
".lls-phone.lls-warned .lls-brand{visibility:hidden}",
/* on the laptop it lies over the top of the room picture instead of pushing every control down */
".lls-wide>.lls-banner{position:absolute;left:50%;transform:translateX(-50%);top:calc(var(--lls-toph,92px) + 8px);z-index:30;max-width:min(640px,calc(100% - 520px));border:1px solid #ffb45466;border-radius:10px;box-shadow:0 8px 30px #000a}",
/* what this path cannot do stays in place, grayed, with its reason as words beside it (his rule, 2026-11-12): a phone has no hover */
".lls-whynote{flex-basis:100%;margin:-2px 0 2px}",
/* the name box opens near the top, never where the keyboard or the pads are */
".lls-toast.ask{top:calc(var(--lls-stop-top,0px) + 74px + env(safe-area-inset-top,0px));bottom:auto;flex-wrap:wrap;z-index:46}",
".lls-toast.ask span{flex-basis:100%}.lls-wide .lls-toast.ask{top:calc(var(--lls-toph,92px) + 8px)}",
".lls-lbl{font-size:11.5px;color:var(--faint);white-space:nowrap}"
].join("\n");

function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
function cmdAttr(cmd) { return "data-cmd=\"" + esc(JSON.stringify(cmd)) + "\""; }
function pct(v) { return Math.round((v || 0) * 100); }
function mmss(s) { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }

function injectCss(doc) {
  if (doc.getElementById("lls-css")) return;
  var st = doc.createElement("style"); st.id = "lls-css"; st.textContent = CSS; doc.head.appendChild(st);
}

function mount(host, opts) {
  var T = opts.transport, wide = opts.layout === "wide", doc = host.ownerDocument, win = doc.defaultView;
  var S = null, got = 0, page = "simple", panel = "levels", locked = false, light = "", alive = true, fails = 0;
  var busy = {}, soon = {}, cache = {}, arrows = {}, basePace = "walk", pollT = 0, rafT = 0, toastT = 0;
  var dragging = false, moved = false, downAt = null, hovering = false, peekKey = "", peekT = 0, peekIv = 0, frame = null, plan = null;
  var asking = null, delArm = "", delT = 0, refusedN = null, waits = [], waitT = 0, waitRev = null;
  // openStep: the Tonight row tapped open, showing its press line and Go here now (a tap never jumps
  // the night by itself). stopped: STOP was pressed here and nothing has lit the room since.
  // lost: no answer from the laptop for LOST_MS, so every control dims and takes no taps.
  var openStep = -1, stopped = false, stopAt = 0, lost = false, lostT = 0, okAt = Date.now(), tickAt = Date.now(), LOST_MS = 5000, ASK_MS = 4500;
  var markArm = "", markT = 0;   // a saved place armed to be forgotten (a second tap within 3 s)
  var tabbed = false;   // focus last moved by Tab (keyboard), not by a click or a tap
  var quietHits = {};   // hits on (or under a finger) when the laptop went quiet: sent off when it answers again
  var screen = opts.screen || (wide ? "laptop" : "phone");
  // View from (his ask, 2026-11-13): which way this screen looks at the room. From the DJ booth
  // looking out (the default) the booth is at the bottom, so his left is the picture's left; from the
  // floor it is the other way up; a quarter turn covers an odd venue. Steering follows the view.
  function view() { var v = st() && st().spots.views && st().spots.views[screen]; return v || {from: "booth", turn: 0}; }
  function rot() { var v = view(); return ((v.from === "booth" ? 2 : 0) + (v.turn || 0)) % 4; }
  function caps() { return (typeof opts.caps === "function" ? opts.caps() : opts.caps) || {}; }
  function q(sel) { return host.querySelector(sel); }
  function qa(sel) { return Array.prototype.slice.call(host.querySelectorAll(sel)); }
  function st() { return S && S.studio; }

  injectCss(doc);
  host.classList.add("lls", wide ? "lls-wide" : "lls-phone");
  host.innerHTML =
    '<div class="lls-bar"></div>' +
    '<div class="lls-top">' +
      '<div class="lls-brand" title="Llano Lights"><i data-t="beat"></i><span>Llano Lights</span></div>' +
      '<div class="lls-chip show"><small>The show</small><div class="row"><b data-t="show"></b><span data-t="gobtns" style="display:contents"></span></div><span data-t="showsub"></span><div class="lls-tags" data-t="songtag"></div><span class="lls-note lls-music" data-t="musicnote">Music plays in Mixxx. Llano Lights follows it.</span></div>' +
      '<div class="lls-chip held" data-t="heldchip"><small>Held look</small><div class="row"><b data-t="held"></b><button class="lls-rel" ' + cmdAttr({op: "release"}) + ' data-t="rel">Release</button></div><span data-t="heldsub"></span></div>' +
      '<div class="lls-chip spot" data-t="spotchip"><small>Spots</small><b data-t="spot"></b><span data-t="spotsub"></span></div>' +
      '<div class="lls-chip next" data-t="nextchip"><small>Next</small><b data-t="next"></b><span data-t="nextsub"></span></div>' +
      '<div class="lls-health" data-t="health"></div>' +
      '<button class="lls-lock" data-act="lock" title="Lock the keyboard so a bumped key changes nothing (L). The mouse still works.">Lock keys</button>' +
      '<a class="lls-link" data-t="setup" title="The lights, the room, the rig and updates">Set up</a>' +
      '<a class="lls-link" data-t="shows" title="Your saved shows: build the night, pick its songs and moments">Shows</a>' +
      '<button class="lls-stop" data-act="stop" title="Stop the lights">STOP</button>' +
    '</div>' +
    '<div class="lls-banner" data-t="banner" hidden></div>' +
    '<div class="lls-mid">' +
      '<div class="lls-col lls-night"><h3 data-t="nighttitle">Tonight</h3><div class="lls-steps" data-t="steps"></div>' +
        '<div class="lls-nowbox" data-t="nowbox" aria-live="polite"></div>' +
        '<button class="lls-nextbtn" data-act="next" data-t="nextbtn"></button>' +
        '<button class="lls-follow" ' + cmdAttr({op: "follow_music"}) + ' data-t="follow" hidden>Back to where the music is</button>' +
        '<p class="note" data-t="nightnote"></p><div class="lls-moods" data-t="moods"></div></div>' +
      '<div class="lls-stage"><div class="lls-stagebox" data-t="stagebox"></div><div class="lls-stagebar" data-t="stagebar"></div><div class="lls-stagehelp" data-t="stagehelp"></div></div>' +
      '<div class="lls-col lls-side">' +
        '<div class="lls-ptabs"><button data-panelbtn="levels">Levels</button><button data-panelbtn="spot">Spot</button><button data-panelbtn="lights">Lights</button>' +
          '<button data-panelbtn="timeline">Cues</button>' + (T.settings && T.change ? '<button data-panelbtn="settings">Saved</button>' : "") + '</div>' +
        '<div data-panel="levels"></div><div data-panel="spot"></div><div data-panel="lights"></div><div data-panel="timeline" class="lls-tl"></div><div data-panel="settings"></div>' +
      '</div>' +
    '</div>' +
    '<div class="lls-bot"><div class="lls-tabs" data-t="tabs"></div><div class="lls-pads" data-t="pads"></div><div class="lls-hits" data-t="hits"></div></div>' +
    '<div class="lls-toast" data-t="toast" hidden></div>' +
    '<div class="lls-lostmsg" data-t="lostmsg" role="alert" hidden></div>';
  var E = {};
  qa("[data-t]").forEach(function (n) { E[n.getAttribute("data-t")] = n; });
  var P = {};
  qa("[data-panel]").forEach(function (n) { P[n.getAttribute("data-panel")] = n; });
  // The phone's show settings sit in a fold, shut by default (BL #11473): shut, its controls are not
  // drawn on screen, so no stray tap during the party changes the saved show. The laptop has a tab.
  var SB = P.settings;
  if (!wide && T.settings && T.change) { P.settings.innerHTML = '<details class="lls-fold"><summary>Show settings: change these at home, not during the party</summary><div></div></details>'; SB = P.settings.querySelector(".lls-fold>div"); }
  // The phone's Live screen is the party first (Llano BL #12419, 2026-11-14: the phone layout was
  // inefficient, with a lot of scrolling): what is on, Next, Tonight, the pads and STOP stay open; the moving
  // heads with their picture, the levels and touch-a-light each sit in a fold, shut until he opens it.
  // A spot turning on opens the heads fold, so the picture he steers on is never shut away. They come
  // after Show settings in the page (that fold stays the first) and show before it.
  var FOLD = {};
  if (!wide) {
    var folds = doc.createElement("div"); folds.className = "lls-folds";
    [["heads", "Moving heads"], ["levels", "Brightness and speed"], ["lights", "Touch a light"], ["timeline", "Cue timeline"]].forEach(function (f) {
      var d = doc.createElement("details"); d.className = "lls-livefold"; d.setAttribute("data-fold", f[0]);
      d.innerHTML = '<summary><span>' + f[1] + '</span><span class="lls-foldnow"></span></summary><div></div>';
      folds.appendChild(d); FOLD[f[0]] = d;
    });
    FOLD.heads.lastChild.appendChild(q(".lls-stage")); FOLD.heads.lastChild.appendChild(P.spot);
    FOLD.levels.lastChild.appendChild(P.levels); FOLD.lights.lastChild.appendChild(P.lights);
    FOLD.timeline.lastChild.appendChild(P.timeline);
    q(".lls-mid").appendChild(folds);
    // the picture is not drawn while its fold is shut (it has no size): opening it draws it now
    FOLD.heads.addEventListener("toggle", function () { if (FOLD.heads.open && S && S.studio) draw(); });
  }
  function foldNow(k, text, warn) {
    var n = FOLD[k] && FOLD[k].querySelector(".lls-foldnow");
    if (n && n.textContent !== text) { n.textContent = text; n.classList.toggle("warn", !!warn); }
  }
  function drawFolds() {
    if (wide) return;
    var s = st(), hd = s.heads || {mode: "auto"}, sp = s.spots || {};
    foldNow("heads", ({auto: "Auto", stop: "Stopped", yours: "Yours"}[hd.mode] || hd.mode) + (sp.on ? " · spot on" : ""), hd.mode !== "auto");
    var main = s.masters && s.masters.main != null ? Math.round(s.masters.main * 100) + "%" : "";
    foldNow("levels", [main, SPEED_NAMES[String(s.speed)] || (s.speed != null ? s.speed + "x" : ""), s.fade_s ? (+(+s.fade_s).toFixed(1)) + " s" : "Snap"].filter(Boolean).join(" · "),
      s.masters && s.masters.main != null && s.masters.main < 0.999);
    var by = Object.keys(s.touch || {}).length + Object.keys(s.pins || {}).length;
    foldNow("lights", by ? by + " changed by hand" : "", by > 0);
  }
  if (opts.links && opts.links.setup) E.setup.href = opts.links.setup; else E.setup.style.display = "none";
  if (opts.links && opts.links.shows) E.shows.href = opts.links.shows; else E.shows.style.display = "none";
  if (!opts.keys) q(".lls-lock").style.display = "none";
  var topRO = null;
  if (wide && win.ResizeObserver) { topRO = new win.ResizeObserver(function () { host.style.setProperty("--lls-toph", q(".lls-top").offsetHeight + "px"); }); topRO.observe(q(".lls-top")); }   // no keyboard drives this screen: nothing to lock

  // --- talking to the laptop -------------------------------------------------------------------
  function toast(text, ms) {
    if (asking) return;
    E.toast.textContent = text; E.toast.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { E.toast.hidden = true; }, ms || 3800);
  }
  function ask(label, placeholder, done) {   // a name for a saved look or place
    asking = done; clearTimeout(toastT); E.toast.classList.add("ask");
    E.toast.innerHTML = '<span>' + esc(label) + '</span><input maxlength="40" placeholder="' + esc(placeholder) + '"><button class="go" data-act="ask-ok">Save</button><button data-act="ask-no">Cancel</button>';
    E.toast.hidden = false;
    var inp = E.toast.querySelector("input"); inp.focus();
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") askDone(true); else if (e.key === "Escape") askDone(false); e.stopPropagation(); });
  }
  // A yes or no question, in the same box as a name. The SAFE answer (no) comes first, highlighted
  // and focused; the risky one (yes, which runs done) second and plain. Esc answers no.
  function confirmAsk(label, yes, no, done) {
    asking = function () { done(); }; clearTimeout(toastT); E.toast.classList.add("ask");
    E.toast.innerHTML = '<span>' + esc(label) + '</span><button class="go" data-act="ask-no">' + esc(no) + '</button><button data-act="ask-ok">' + esc(yes) + '</button>';
    E.toast.hidden = false;
    var safe = E.toast.querySelector('[data-act="ask-no"]'); if (safe && safe.focus) safe.focus();
  }
  // The laptop's warning in full, as the banner words it, with OK where the screen can clear it
  function warnBox(w) {
    asking = function () {}; clearTimeout(toastT); E.toast.classList.add("ask");
    E.toast.innerHTML = '<span>' + (w.level === "bad" ? "<b>Not started.</b> " : "") + esc(w.text) + '</span>' +
      (T.ack ? '<button class="go" data-act="warn-ok">OK</button><button data-act="ask-no">Close</button>' : '<button class="go" data-act="ask-no">Close</button>');
    E.toast.hidden = false;
  }
  function askDone(ok) {
    var done = asking, inp = E.toast.querySelector("input"), name = inp ? inp.value.trim() : "";
    asking = null; E.toast.hidden = true; E.toast.classList.remove("ask");
    if (ok && done) { if (!inp) done(); else if (name) done(name); else toast("It needs a name."); }
  }
  function took(r) { if (r && r.studio && S) { S.studio = r.studio; draw(); } return r; }
  // On a slow path the button pressed pulses until the laptop's answer shows (or 4 seconds), and a
  // second tap on it meanwhile is not sent: two taps on Blackout or Next would undo or double it.
  function waitOn(n) {
    if (!caps().slow || !n || !n.classList) return;
    n.classList.add("wait"); waits.push(n);
    clearTimeout(waitT); waitT = setTimeout(waitOver, 4000);
  }
  function waitOver() { clearTimeout(waitT); waits.forEach(function (n) { n.classList.remove("wait"); }); waits = []; }
  function send(cmd, quiet) {
    return Promise.resolve().then(function () { return T.send(cmd); }).then(function (r) {
      if (r && r.error && !quiet) toast(r.error);
      return took(r);
    }).catch(function () { if (!quiet) toast("That didn't reach the laptop. Check the connection and press it again."); return null; });
  }
  // A slider being dragged or a pointer being followed sends its newest value, at most every `ms`.
  function sendSoon(key, cmd, ms) {
    var s = soon[key] || (soon[key] = {at: 0, timer: 0, cmd: null});
    s.cmd = cmd;
    if (s.timer) return;
    var wait = Math.max(0, (ms || 70) - (Date.now() - s.at));
    s.timer = setTimeout(function () { s.timer = 0; s.at = Date.now(); var c = s.cmd; s.cmd = null; if (c) send(c, true); }, wait);
  }
  // One poll loop, ever: poll0 (a press, a wake) starts a new generation; an older poll still out
  // neither applies its answer nor schedules another, so a wake never stacks a second loop.
  var pollGen = 0;
  function poll() {
    if (!alive) return;
    var gen = pollGen;
    // a transport that never answers must not stop the polling: after ASK_MS it counts as no answer
    var asked = new Promise(function (ok, no) { var t = setTimeout(function () { no(new Error("no answer")); }, ASK_MS);
      Promise.resolve().then(function () { return T.state(); }).then(function (v) { clearTimeout(t); ok(v); }, function (e) { clearTimeout(t); no(e); }); });
    asked.then(function (s) {
      if (!alive || gen !== pollGen) return;
      if (s && s.studio) {
        S = s; got = okAt = Date.now(); fails = 0; setLost(false); if (opts.onState) opts.onState(s);
        var wr = s.studio.rev + "|" + (s.refused ? s.refused.n : "");
        if (wr !== waitRev) { waitRev = wr; if (waits.length) waitOver(); }
        // a press that went by way of Llano and was refused on the laptop: said here, once
        if (s.refused && s.refused.n !== refusedN) { if (refusedN !== null && s.refused.error) toast(s.refused.error, 6000); refusedN = s.refused.n; }
        else if (!s.refused && refusedN === null) refusedN = 0;
        draw();
      }
      else throw new Error("no state");
    }).catch(function () { if (gen !== pollGen) return; fails++; if (opts.onLost) opts.onLost(fails); })
      .then(function () { if (alive && gen === pollGen) pollT = setTimeout(poll, fails ? 1000 : (opts.pollMs || 250)); });
  }

  // Not answering: judged by time since the last answer, not by failures counted, because a request
  // to a laptop that left the Wi-Fi can hang instead of failing. Comes back by itself on an answer.
  function setLost(on) {
    if (on === lost) return;
    lost = on; host.classList.toggle("lls-lost", on);
    E.lostmsg.hidden = !on;
    if (on) {
      E.lostmsg.textContent = opts.lostText || "Llano Lights on the laptop is not answering. Check that it is still open. This screen comes back by itself.";
      if (opts.lostLink) { var a = doc.createElement("a"); a.href = opts.lostLink.href; a.textContent = opts.lostLink.text; E.lostmsg.appendChild(doc.createElement("br")); E.lostmsg.appendChild(a); }
      if (asking) askDone(false); clearTimeout(toastT); E.toast.hidden = true;
      // a hit held when the laptop went quiet must not stay on: the laptop drops one only on an off
      quietHits = {};
      Object.keys(holding).forEach(function (k) { quietHits[holding[k]] = 1; });
      ((S && S.studio && S.studio.hits) || []).forEach(function (h) { quietHits[h] = 1; });
    } else if (caps().hits !== "latch") {
      var fingers = {}; Object.keys(holding).forEach(function (k) { fingers[holding[k]] = 1; });
      Object.keys(quietHits).forEach(function (h) { if (!fingers[h]) hitSend({op: "hit", name: h, on: false}); });
      quietHits = {};
    }
    if (S && S.studio) draw();
  }
  // A phone waking from a locked screen (or a laptop from sleep) has not heard the laptop for as long
  // as it slept: that is not the laptop going quiet. A gap in this timer, a hidden page, focus or the
  // page showing again resets the clock and asks at once, before anything is judged.
  function wake() { okAt = tickAt = Date.now(); releaseHolds(); if (alive) poll0(); }
  function watchLost() {
    if (!alive) return;
    var now = Date.now();
    if (doc.hidden || now - tickAt > 2000) okAt = now;   // asleep, or the timer itself was frozen
    else if (now - okAt > LOST_MS) setLost(true);
    tickAt = now; lostT = setTimeout(watchLost, 500);
  }
  function onVisible() { if (doc.hidden) releaseHolds(); else wake(); }

  // --- drawing ------------------------------------------------------------------------------------
  function put(key, node, html) { if (cache[key] !== html) { cache[key] = html; node.innerHTML = html; } }
  function text(node, t) { if (node.textContent !== t) node.textContent = t; }
  function gate(html, reason) { return reason ? html.replace("<button ", '<button data-why="' + esc(reason) + '" ').replace('class="', 'class="off ') : html; }
  function seg(items, on, mk) {   // items: [[value, label]]
    return '<div class="lls-seg">' + items.map(function (it) {
      return '<button class="' + (it[0] === on ? "on" : "") + '" ' + cmdAttr(mk(it[0])) + '>' + esc(it[1]) + '</button>'; }).join("") + '</div>';
  }
  function slider(key, label, value, cls) {
    return '<div class="lls-mst ' + (cls || "") + '"><div class="l"><b>' + esc(label) + '</b><span data-val="' + key + '">' + pct(value) + '%</span></div>' +
      '<input type="range" min="0" max="100" step="1" value="' + pct(value) + '" data-slide="' + key + '" style="--v:' + pct(value) + '%" aria-label="' + esc(label) + '"></div>';
  }
  function syncSliders(rootNode, values) {
    Array.prototype.forEach.call(rootNode.querySelectorAll("[data-slide]"), function (inp) {
      var k = inp.getAttribute("data-slide");
      if (busy[k] && busy[k] > Date.now()) return;   // his hand is on it
      var v = pct(values[k]);
      if (+inp.value !== v) { inp.value = v; }
      inp.style.setProperty("--v", v + "%");
      var lab = rootNode.querySelector('[data-val="' + k + '"]'); if (lab) text(lab, v + "%");
    });
  }

  function padKeys() {   // key -> pad key, and pad key -> key label, from the pages as the laptop lists them
    var map = {}, label = {};
    ((S && S.catalog && S.catalog.pages) || []).forEach(function (pg) {
      var row = PAD_KEYS[pg.key] || "";
      pg.pads.forEach(function (p, i) { if (row[i]) { map[row[i]] = [pg.key, p.key]; label[p.key] = row[i]; } });
    });
    return {map: map, label: label};
  }

  function drawTop() {
    var s = st(), lv = S.live, np = S.now_playing, look = s.look, sp = s.spots, night = s.night, c = caps();
    var title, sub;
    // STOP takes a moment to land: "Stopping..." until a poll shows the room dark, then Stopped; still
    // lit after 3 seconds, it says so. The message clears once the room was dark and is lit again.
    var dark = !S.running && !look && !s.frozen;
    if ((stopped === 1 || stopped === 3 || stopped === 4) && dark) stopped = 2;
    else if (stopped === 1 && Date.now() - stopAt > 3000) { stopped = 3; stopAt = Date.now(); }
    else if ((stopped === 3 || stopped === 4) && Date.now() - stopAt > 20000) stopped = false;   // never for the rest of the night
    else if (stopped === 2 && !dark) stopped = false;
    if (stopped === 1) { title = "Stopping..."; sub = ""; }
    else if (stopped === 2) { title = "Stopped. The lights are off."; sub = "Press Live show to start again."; }
    else if (stopped === 3) { title = "STOP was sent but the lights are still on."; sub = "Press STOP again, or use Stop on the laptop."; }
    else if (stopped === 4) { title = "STOP did not reach the laptop."; sub = "Press STOP again, or use Stop on the laptop."; }
    else if (!S.running) { title = "Nothing running"; sub = "Press a pad to light the room, or start the live show"; }
    else {
      var song = np && (np.title || np.artist) ? [np.artist, np.title].filter(Boolean).join(" - ") : "";
      title = song ? song : (S.running_label || "Running");
      sub = (song ? (S.running_label || "") + " · " : "") + (lv && lv.bpm > 0 ? Math.round(lv.bpm) + " BPM" : "") +
        (look ? " · underneath, comes back on Release" : "");
      if (!song && lv && !lv.playing && (S.running === "live" || S.running === "preview")) sub = "Waiting for music: start a song in Mixxx, Spotify or YouTube Music";
    }
    text(E.show, title); text(E.showsub, sub.replace(/^ · /, ""));
    // The playing song's part of the night and, for a Dancing song, its Hype, Dance or Slow tag: one
    // tap changes it, saved into the show the Live show follows (Llano BL #12341).
    var tg = S.running ? S.song_tag : null, th = "";
    if (tg && tg.part_title) {
      th = '<em>' + esc(tg.part_title + (tg.tag_title ? " · " + tg.tag_title : "")) + '</em>';
      if (tg.can_tag) th += [["hype", "Hype"], ["dance", "Dance"], ["slow", "Slow"]].map(function (x) {
        return '<button class="lls-mini' + (tg.tag === x[0] ? " on" : "") + '" ' + cmdAttr({op: "song_tag", i: tg.i, tag: x[0]}) +
          ' title="' + x[1] + ' for this song: ' + (x[0] === "hype" ? "the peak look" : x[0] === "dance" ? "the groove look" : "the slow-dance look") + '. Saved into the show.">' + x[1] + '</button>';
      }).join("");
    }
    put("songtag", E.songtag, th);
    var go = "";
    if (T.run && S.running !== "live" && S.running !== "preview")
      go = gate('<button class="lls-mini go" data-act="run" data-mode="live" title="The lights follow Mixxx, Spotify or YouTube Music. What you hold stays held.">Live show</button>', c.run) +
           gate('<button class="lls-mini" data-act="run" data-mode="preview" title="The same, with nothing sent to the lights: watch the picture">No lights</button>', c.run);
    else if (!T.run && c.run && !S.running) go = '<span class="why">' + esc(c.run) + '</span>';
    put("go", E.gobtns, go);
    // Blackout wins over a held look: the card never claims a look is showing while the room is dark
    E.heldchip.classList.toggle("on", !!look || !!s.blackout);
    text(E.held, s.blackout ? "Blackout is on." : look ? look.name : s.frozen ? "Frozen" : "Nothing held");
    E.rel.style.display = (look || s.frozen) && !s.blackout ? "" : "none";
    var colorNote = s.color || s.motion ? " · your color and motion apply" : "";
    text(E.heldsub, s.blackout ? "Press Blackout again to bring the lights back." : look ? "Held " + mmss(heldFor(look)) + " · stays until you release it" :
      s.frozen ? "The lights are frozen as they were. Release lets them move again." : "The lights follow the music" + colorNote);
    E.spotchip.classList.toggle("on", !!sp.on); E.spotchip.classList.toggle("dimmed", !sp.on);
    // short words, so the card never cuts them off at 1024 wide; the long reason is in its title (BL #11473)
    text(E.spot, !sp.on ? "Off" : sp.count === 2 ? "2 spots" : "1 spot");
    text(E.spotsub, !sp.on ? (opts.keys ? "Press F to follow someone" : "Turn on Spots to follow someone") :
      sp.why ? "Not lined up here yet" : sp.hover ? "Following the pointer" :
      (sp.count === 2 ? ["Steering spot A", "Steering spot B", "Steering both"][sp.sel] : "Steering all heads"));
    E.spotchip.title = sp.on && sp.why ? "Not lined up here yet: it follows the picture's best guess" : sp.on && opts.keys ? "Steer with the arrow keys" : "";
    var nx = night && night.next;
    E.nextchip.classList.toggle("dimmed", !nx);
    text(E.next, nx ? nx.name : "End of the night");
    text(E.nextsub, !nx ? "" : night.follows ? "By itself when Mixxx gets there" + (opts.keys ? ", or Enter" : "") : opts.keys ? "Press Enter, or the Next button" : "Press Next");
    var h = "", conn = S.conn || {};
    function dot(ok, label, tip) { return '<span class="' + (ok === true ? "ok" : ok === false ? "bad" : "") + '" title="' + esc(tip || "") + '"><i></i>' + esc(label) + '</span>'; }
    if (conn.enttec) h += dot(conn.enttec.ok, "Lights box", conn.enttec.detail);
    if (conn.mixxx) h += dot(conn.mixxx.ok, "Mixxx", conn.mixxx.detail);
    if (opts.link) h += dot(!lost, opts.link(), lost ? "The laptop is not answering" : "How this phone reaches the laptop");
    else if (typeof S.phone === "boolean") h += dot(S.phone, "Phone", S.phone ? "Phone control is on" : "Phone control is off (Set up)");
    put("health", E.health, h);
    E.banner.hidden = !S.warning; host.classList.toggle("lls-warned", !!S.warning);   // the laptop not answering is the lost state (setLost), not this banner
    put("banner", E.banner, S.warning ? '<span>' + (S.warning.level === "bad" ? "<b>Not started.</b> " : "") + esc(S.warning.text) + '</span>' + (T.ack ? '<button data-act="ack">OK</button>' : "") : "");
    var lock = q(".lls-lock"); lock.classList.toggle("on", locked); text(lock, locked ? "Keys locked (L)" : "Lock keys");
  }
  function heldFor(look) { return S.now ? (S.now - look.since) + (Date.now() - got) / 1000 : 0; }

  function drawNight() {
    var night = st().night;
    if (!night || !night.steps || !night.steps.length) {
      put("steps", E.steps, '<p class="lls-note">No night is loaded.</p>'); E.nextbtn.style.display = "none"; E.follow.hidden = true;
      E.steps.style.maxHeight = ""; cache.measured = "";
      put("nowbox", E.nowbox, '<small>Now</small><p>No night is loaded. Build one on the Shows page on the laptop.</p>'); text(E.nightnote, ""); return;
    }
    text(E.nighttitle, night.title ? "Tonight · " + night.title : "Tonight");
    if (openStep >= night.steps.length) openStep = -1;
    put("steps", E.steps, night.steps.map(function (sx, i) {
      // a hold stops the music until he presses Fade Now in Mixxx: the tag says so (BL #11473)
      var stop = sx.kind === "hold", tag = sx.state === "now" ? "now" : sx.state === "next" ? "next" : stop ? "Stop: waits for Fade Now" : sx.held ? "held" : "music";
      var row = '<button class="lls-step ' + sx.state + '" data-step="' + i + '" aria-expanded="' + (openStep === i) + '"><i></i><span>' + esc(sx.name) + '</span>' +
        '<em' + (stop && sx.state !== "now" && sx.state !== "next" ? ' class="stopq"' : "") + '>' + esc(tag) + '</em></button>';
      if (openStep === i) row += '<div class="lls-steppress">' + (sx.press ? "Then press: " + esc(sx.press) : "Nothing to press here.") +
        (sx.say ? "<br>Say: " + esc(sx.say) : "") + '<br><button ' + cmdAttr({op: "goto", i: i}) + '>Go here now</button></div>';
      return row;
    }).join(""));
    if (!wide && cache.measured !== cache.steps) {   // the phone's list shows whole rows only (BL #11473);
      cache.measured = cache.steps;                   // measured only when the rows or the open row change
      var rows = E.steps.querySelectorAll(".lls-step"), pad = 4, block = E.steps.querySelector(".lls-steppress");
      var hh = rows.length > 4 ? rows[4].offsetTop - rows[0].offsetTop - (block && +block.previousSibling.getAttribute("data-step") < 4 ? block.offsetHeight : 0) + pad : 0;
      if (hh > 0 && block) hh += block.offsetHeight + 8;   // an open row shows its press line and Go here now in full
      var mh = hh > 0 ? hh + "px" : "none";
      if (E.steps.style.maxHeight !== mh) E.steps.style.maxHeight = mh;
      if (block) { var top = block.previousSibling.offsetTop - E.steps.offsetTop - pad; if (E.steps.scrollTop > top || E.steps.scrollTop + E.steps.clientHeight < block.offsetTop - E.steps.offsetTop + block.offsetHeight) E.steps.scrollTop = top; }
    }
    var nx = night.next, fade = st().fade_s;
    E.nextbtn.style.display = nx ? "" : "none";
    put("nextbtn", E.nextbtn, nx ? "Next: " + esc(nx.name) + "<small>" + (opts.keys ? "Enter · " : "") + (fade > 0 ? "fades over " + (+fade.toFixed(1)) + " seconds" : "changes at once") + "</small>" : "");
    E.follow.hidden = night.ahead === null || night.ahead === undefined;
    drawNow(night);
    // the laptop's own words first: the list can be a saved show's night, not yet built (Llano BL #12387)
    text(E.nightnote, night.note ? night.note : night.follows ? "The lights change by themselves as Mixxx reaches each step. Next is your override." :
      "No night is built yet, so this is the usual wedding order and you step it yourself. Build the night on the laptop's Shows page and it follows Mixxx.");
    if (cache.nowstep !== night.at + "|" + night.ahead) {   // keep Now in view
      cache.nowstep = night.at + "|" + night.ahead;
      var now = E.steps.querySelector(".now"); if (now && now.scrollIntoView) now.scrollIntoView({block: "nearest"});
    }
  }
  // Now: the step the night is on, what Mixxx is doing there and what to press to move on, in full
  // (BL #11473). Before Mixxx has been seen, how to start it.
  function drawNow(night) {
    var cur = night.ahead !== null && night.ahead !== undefined ? night.ahead : night.at, sx = night.steps[cur], h = '<small>Now</small>';
    if (!sx) h += night.follows ? '<p class="press">Mixxx plays the music. Start it there: click <span>Auto DJ</span> in Mixxx\'s list on the left, then the first button at the top of that page. This list then follows along.</p>'
      : '<b>Not started</b><p class="press">Mixxx plays the music. When the first part begins, press <span>Next</span> and this list moves along with you.</p>';
    else h += '<b>' + esc(sx.name) + '</b>' +   // the line he acts on first, then what Mixxx is doing
      '<p class="press">' + (sx.press ? "Press: " + esc(sx.press) : "Nothing to press here.") + '</p>' +   // the line of the step it names
      (sx.wait ? '<p class="wait">' + esc(sx.wait) + '</p>' : "");
    if (wide && night.note) h += '<p class="wait">' + esc(night.note) + '</p>';   // the laptop's own words, never cut at the column's foot
    put("nowbox", E.nowbox, h);
  }

  // Cocktail hour and dinner's mood (BL #12340): each button carries the whole new mood, so a tap
  // is one command and the laptop clamps it (settings_contract.part_mood).
  var MOOD_SW = [["warm white", "#ffe4c4"], ["amber", "#ffb347"], ["blush", "#f4b6c2"], ["gold", "#f2c14e"],
                 ["lavender", "#c3b1e1"], ["soft blue", "#9ec9f0"]];
  function drawMoods() {
    var night = st().night, moods = night && night.moods;
    if (!moods) { put("moods", E.moods, ""); return; }
    put("moods", E.moods, [["cocktail", "Cocktail hour"], ["dinner", "Dinner"]].map(function (pp) {
      var part = pp[0], m = moods[part], fade = m.kind === "fade", on = night.mood_part === part;
      function cmd(mood) { return cmdAttr({op: "mood", part: part, mood: Object.assign({}, m, mood)}); }
      var sw = MOOD_SW.map(function (s) {
        var has = m.colors.indexOf(s[1]) >= 0, cols;
        if (!fade) cols = [s[1]];
        else if (has) cols = m.colors.length > 2 ? m.colors.filter(function (c) { return c !== s[1]; }) : m.colors;
        else cols = m.colors.length < 4 ? m.colors.concat([s[1]]) : m.colors;
        return '<button class="' + (has ? "on" : "") + '" style="background:' + s[1] + '" title="' + s[0] + '" ' + cmd({colors: cols}) + '></button>';
      }).join("");
      var more = MOOD_SW.map(function (s) { return s[1]; }).filter(function (c) { return m.colors.indexOf(c) < 0; });
      return '<div class="lls-mood"><b>' + pp[1] + ' mood' + (on ? " · now" : "") + '</b><div class="k">' +
        '<button class="lls-btn' + (fade ? "" : " on") + '" ' + cmd({kind: "color", colors: [m.colors[0]]}) + '>One color</button>' +
        '<button class="lls-btn' + (fade ? " on" : "") + '" ' + cmd({kind: "fade", colors: m.colors.length > 1 ? m.colors : m.colors.concat(more.slice(0, 1))}) + '>Slow fade</button>' +
        '</div><div class="sw">' + sw + '</div></div>';
    }).join(""));
  }

  function drawPads() {
    var s = st(), cat = S.catalog || {pages: []}, keys = padKeys(), heldKey = s.look ? s.look.key : "", spotsOn = s.spots.on;
    var heldPage = "";
    cat.pages.forEach(function (pg) { if (pg.pads.some(function (p) { return p.key === heldKey; })) heldPage = pg.key; });
    var tabs = cat.pages.map(function (pg) {
      return '<button class="t ' + (pg.key === page ? "on" : "") + '" data-page="' + pg.key + '">' + esc(pg.name) + (pg.key === heldPage && pg.key !== page ? "<i></i>" : "") + '</button>'; }).join("");
    tabs += '<span class="lls-tweak">Color <span class="lls-dots">' + COLORS.map(function (cx) {
      return '<button class="lls-dot ' + (cx[0] ? "" : "none ") + (s.color === cx[0] ? "on" : "") + '" style="' + (cx[0] ? "background:" + cx[0] : "") + '" title="' + esc(cx[1]) + '" ' + cmdAttr({op: "color", color: cx[0]}) + '></button>'; }).join("") + '</span></span>';
    tabs += '<span class="lls-tweak">Motion ' + seg(["", "still", "slow"].map(function (m) { return [m, MOTION_NAMES[m]]; }), s.motion, function (m) { return {op: "motion", motion: m}; }) + '</span>';
    tabs += '<span class="hint">One look at a time. It holds until you release it.' + (T.peek && !caps().peek ? " Rest the pointer on a pad to preview it in the picture." : "") + '</span>';
    put("tabs", E.tabs, tabs);
    var pg = cat.pages.filter(function (x) { return x.key === page; })[0] || cat.pages[0];
    if (!pg) { put("pads", E.pads, ""); return; }
    E.pads.style.setProperty("--n", String(Math.max(6, Math.min(8, pg.pads.length))));
    put("pads", E.pads, pg.pads.length ? pg.pads.map(function (p) {
      var k = keys.label[p.key], dimKey = spotsOn && /\d/.test(k || "");
      return '<button class="lls-pad ' + (p.key === heldKey ? "on" : "") + '" data-pad="' + esc(p.key) + '"><i class="sw" style="background:' + (/^#[0-9a-fA-F]{6}$/.test(p.color || "") ? p.color : "linear-gradient(90deg,#ff7eb6,#a395ff,#6cb8ff,#7cf0c8)") + '"></i>' +
        '<b>' + esc(p.name) + (k && !dimKey ? "<kbd>" + esc(k) + "</kbd>" : "") + '</b><p>' + esc(p.line) + '</p>' +
        '<div class="tg">' + (p.tags || []).map(function (t) { return '<span class="lls-tag ' + t + '">' + esc(TAGS[t] || t) + '</span>'; }).join("") + '</div>' +
        (p.mine ? '<span class="del" data-del="' + esc(p.name) + '">' + (delArm === p.name ? "Delete?" : "Delete") + '</span>' : "") + '</button>';
    }).join("") : '<div class="empty">Nothing saved yet. Hold a look, set its color and motion the way you like, then press Save this look.</div>');
  }

  function drawHits() {
    var s = st(), latch = caps().hits === "latch";
    var h = '<span class="lls-tag">' + (latch ? "Tap on, tap off" : "Hold while pressed") + '</span>';
    ["whiteout", "strobe", "burst"].forEach(function (n) {
      h += '<button class="lls-hit ' + (n === "whiteout" ? "w " : "") + (s.hits.indexOf(n) >= 0 ? "on" : "") + '" data-hit="' + n + '">' + HIT_NAMES[n] + '<small>' + (latch ? "tap" : "hold") + '</small></button>';
    });
    h += '<button class="lls-hit f ' + (s.frozen ? "on" : "") + '" ' + cmdAttr({op: "freeze"}) + ' title="Stop every light exactly as it is now, until you press it again">Freeze this look</button>';
    h += '<button class="lls-hit" data-act="save-look" title="Keep the held look, with its color and motion, as a pad of your own on the Mine page"' + (s.look ? "" : " disabled") + '>Save this look</button>';
    h += '<span class="sp"></span>';
    h += '<button class="lls-hit" ' + cmdAttr({op: "undo"}) + (s.can_undo ? "" : " disabled") + ' title="Back to what was live before the last press' + (opts.keys ? " (Ctrl+Z)" : "") + '">Undo last</button>';
    h += '<button class="lls-hit r ' + (s.blackout ? "on" : "") + '" ' + cmdAttr({op: "blackout"}) + '>Blackout' + (opts.keys ? "<small>B</small>" : "") + '</button>';
    put("hits", E.hits, h);
  }

  function drawLevels() {
    var s = st(), cat = S.catalog || {}, lv = S.live;
    if (T.settings && T.change && !sdoc) loadDoc(false);
    var key = JSON.stringify([cat.zones, s.speed, s.fade_s, !!S.show, lv && lv.offset_ms, syncValue(), tap.phase, tap.n, tap.result, caps().sync]);
    if (cache.levels !== key) {
      cache.levels = key;
      var fades = (cat.fades || [0, 1, 3, 8]).slice();
      if (fades.indexOf(s.fade_s) < 0) { fades.push(s.fade_s); fades.sort(function (a, b) { return a - b; }); }
      var off = lv ? Math.round(lv.offset_ms || 0) : 0;
      P.levels.innerHTML = '<h3>Brightness</h3>' + (cat.zones || []).map(function (z) { return slider("m:" + z.key, ZONE_SHORT[z.key] || z.name, s.masters[z.key], z.key === "main" ? "main" : ""); }).join("") +
        '<h3>Speed</h3>' + seg((cat.speeds || [0.5, 1, 2]).map(function (v) { return [v, SPEED_NAMES[String(v)] || v + "x"]; }), s.speed, function (v) { return {op: "speed", value: v}; }) +
        '<h3>Changes take</h3>' + seg(fades.map(function (v) { return [v, v ? (+v.toFixed(1)) + " s" : "Snap"]; }), s.fade_s, function (v) { return {op: "fade", seconds: v}; }) +
        '<h3>The beat</h3><div class="lls-btns" style="margin-top:0">' +
          '<button class="lls-btn" ' + cmdAttr({op: "tap"}) + ' title="Tap along to set the tempo when no music is feeding the beat">Tap tempo</button>' +
          '<button class="lls-btn" ' + cmdAttr({op: "timing", d: -1}) + '>Earlier</button><button class="lls-btn" ' + cmdAttr({op: "timing", d: 1}) + '>Later</button>' +
          '<button class="lls-btn" ' + cmdAttr({op: "timing", d: 0}) + '>Reset</button></div>' +
        '<p class="lls-note" style="margin-top:6px">' + (off ? "Lights " + Math.abs(off) + " ms " + (off > 0 ? "later" : "earlier") + " than the music." : "Lights on the music's own timing.") + '</p>' +
        syncHtml();
    }
    var vals = {}; Object.keys(s.masters).forEach(function (k) { vals["m:" + k] = s.masters[k]; });
    syncSliders(P.levels, vals);
  }

  // Speaker sync (rig.sync_ms, Llano PM #23787): how long the speakers play after the laptop sends the
  // sound. His Bluetooth speaker ran 0.98 s behind Mixxx (his 11-15 video of I Gotta Feeling), so every
  // drop lit a second early. Set once by tapping along to a click that comes out of the rig's speakers:
  // a low click every 0.6 s and a high one every 4th; he taps each HIGH click he hears. Delays up to
  // 2.1 s read without doubt (the high click repeats every 2.4 s). Saved with the rig, so every screen
  // and every song uses it; Earlier and Later stay tonight's fine touch.
  var TAP_BEAT = 0.6, TAP_CYCLE = 2.4, TAP_NEED = 6, TAP_CYCLES = 12;
  var tap = {phase: "", n: 0, result: null, taps: [], hi0: 0, ctx: null, endT: null};
  function syncValue() { return sdoc && sdoc.rig && typeof sdoc.rig.sync_ms === "number" ? sdoc.rig.sync_ms : null; }
  function syncHtml() {
    if (!T.settings || !T.change) return "";
    var v = syncValue(), why = caps().sync || (opts.screen === "phone" ? "Tap along on the laptop: the click has to come out of the rig's own speakers." : "");
    var h = '<h3>Speaker sync</h3>';
    if (tap.phase === "playing") {
      return h + '<button class="lls-btn on" data-act="sync-tap" style="width:100%;padding:18px 0;font-size:18px">Tap on each HIGH click' + (opts.keys ? " (Space)" : "") + '</button>' +
        '<p class="lls-note" style="margin-top:6px">' + (tap.n ? tap.n + " tap" + (tap.n > 1 ? "s" : "") + " so far." : "Listen for the high click, then tap with it.") + ' Keep going until it says done.</p>' +
        '<div class="lls-btns"><button class="lls-btn" data-act="sync-cancel">Cancel</button></div>';
    }
    if (tap.phase === "done") {
      var r = tap.result;
      return h + (r.error ? '<p class="lls-note">' + esc(r.error) + '</p><div class="lls-btns"><button class="lls-btn" data-act="sync-start">Try again</button><button class="lls-btn" data-act="sync-cancel">Close</button></div>'
        : '<p class="lls-note">Your speakers play <b>' + (r.ms / 1000).toFixed(2) + ' s</b> after the laptop.</p><div class="lls-btns">' +
          '<button class="lls-btn on" ' + opsAttr([{path: "rig.sync_ms", value: r.ms}]) + ' data-syncsave="1">Save ' + r.ms + ' ms</button><button class="lls-btn" data-act="sync-start">Try again</button><button class="lls-btn" data-act="sync-cancel">Cancel</button></div>');
    }
    h += '<div class="lls-row"><span>' + (v == null ? "Reading it from the laptop..." : v ? "The lights wait <b>" + v + " ms</b> for the speakers" : "Not set: the lights don't wait for the speakers") + '</span></div>' +
      '<div class="lls-btns" style="margin-top:4px">' + gate('<button class="lls-btn" data-act="sync-start" title="Plays a click through the speakers; tap along with it to measure their delay">Tap along to set</button>', why) +
      '<button class="lls-btn" ' + opsAttr([{path: "rig.sync_ms", value: Math.max(0, (v || 0) - 50)}]) + (v ? "" : " disabled") + '>&minus; 50 ms</button>' +
      '<button class="lls-btn" ' + opsAttr([{path: "rig.sync_ms", value: Math.min(3000, (v || 0) + 50)}]) + (v == null ? " disabled" : "") + '>+ 50 ms</button></div>' +
      '<p class="lls-note" style="margin-top:6px">Set it once with the speakers you play the party on, at the volume you use. A Bluetooth speaker is often half a second to a second late.</p>';
    return h;
  }
  function syncRedraw() { cache.levels = ""; drawLevels(); }
  function syncStart() {
    var AC = win.AudioContext || win.webkitAudioContext;
    if (!AC) { toast("This screen can't play the click."); return; }
    syncStop();
    var ctx = new AC(), t0 = ctx.currentTime + 0.4, perf = win.performance.now();
    for (var i = 0; i < TAP_CYCLES * 4; i++) {
      var at = t0 + i * TAP_BEAT, hi = i % 4 === 0, o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = hi ? 1760 : 880; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(hi ? 0.9 : 0.35, at + 0.003); g.gain.exponentialRampToValueAtTime(0.001, at + 0.06);
      o.start(at); o.stop(at + 0.08);
    }
    // the clock the taps are read on: when the laptop SENDS each high click (what Mixxx's beat is to the lights)
    tap = {phase: "playing", n: 0, result: null, taps: [], ctx: ctx, hi0: perf + (t0 - ctx.currentTime) * 1000,
           endT: win.setTimeout(function () { syncFinish(); }, (0.4 + TAP_CYCLES * TAP_CYCLE + 1) * 1000)};
    syncRedraw();
  }
  function syncStop() { if (tap.ctx) { try { tap.ctx.close(); } catch (x) {} } if (tap.endT) win.clearTimeout(tap.endT); tap.ctx = null; tap.endT = null; }
  function syncTap() {
    if (tap.phase !== "playing") return;
    var d = win.performance.now() - tap.hi0;
    if (d < -300) return;   // before the first high click could be heard
    d = ((d % (TAP_CYCLE * 1000)) + TAP_CYCLE * 1000) % (TAP_CYCLE * 1000);
    if (d > TAP_CYCLE * 1000 - 300) d -= TAP_CYCLE * 1000;   // a hair early on a speaker with no delay
    tap.taps.push(d); tap.n = tap.taps.length;
    if (tap.n >= TAP_NEED + 2) syncFinish(); else syncRedraw();
  }
  function syncMeasure(taps) {
    if (taps.length < TAP_NEED) return {error: "Only " + taps.length + " taps came in. Tap on each high click, about 8 times."};
    var sorted = taps.slice().sort(function (a, b) { return a - b; }), mid = sorted[Math.floor(sorted.length / 2)];
    var kept = taps.filter(function (d) { return Math.abs(d - mid) <= 120; });   // a stray tap (a low click) is dropped
    if (kept.length < TAP_NEED) return {error: "The taps were uneven, so this didn't measure. Tap only on the HIGH click, every time."};
    var mean = kept.reduce(function (a, b) { return a + b; }, 0) / kept.length;
    return {ms: Math.max(0, Math.min(3000, Math.round(mean / 10) * 10))};
  }
  function syncFinish() { if (tap.phase !== "playing") return; syncStop(); tap.phase = "done"; tap.result = syncMeasure(tap.taps); syncRedraw(); }
  function syncCancel() { syncStop(); tap = {phase: "", n: 0, result: null, taps: [], hi0: 0, ctx: null, endT: null}; syncRedraw(); }

  // --- the cue timeline (Llano PM #23787, asked 2026-11-15: push cues forward and back, pause and
  // see them, dead simple) -----------------------------------------------------------------------
  // The song Mixxx plays, as the lights know it (Show.timeline): its sections, his cues and where it is.
  // He plays and pauses in Mixxx; here he drops a cue where it stands and nudges it. Cues are saved
  // in the settings (`cues`, by song) in the original recording's seconds, so they land on the same
  // note in a night's cut; the time shown is Mixxx's (original + zero). An edit reaches the lights on
  // their next frame, on every screen, through the same change path as every saved setting.
  var TL_KINDS = [["intro", "Intro"], ["verse", "Verse"], ["build", "Build"], ["drop", "Drop"], ["main", "Main"], ["breakdown", "Breakdown"], ["outro", "Outro"]];
  var TL_KIND_COLOR = {intro: "#2a3550", verse: "#24425a", build: "#5a4a1c", drop: "#6a2440", main: "#5a2a52", breakdown: "#1f3a3a", outro: "#2a2f40"};
  var TL_ZOOM_S = 6;   // the close-up shows this many seconds each side of the playhead
  var tlSel = -1, tlSelKey = "", tlMine = null, tlMineAt = 0, tlWhy = "";
  var TL_DOS = ["hit", "section", "feel"];   // the laptop's order for cues at one instant (settings_contract.song_cues)
  function tlSort(list) { return list.slice().sort(function (a, b) { return a.at - b.at || TL_DOS.indexOf(a.do) - TL_DOS.indexOf(b.do); }); }
  function tlHere(tl) {   // where the song is now: a playing song has moved on since the laptop said
    if (tl.secs == null) return null;
    var lv = S && S.live, ago = tl.playing && lv && typeof lv.at === "number" ? Date.now() / 1000 - lv.at : 0;
    return tl.secs + Math.max(0, Math.min(1, ago));
  }   // the cue picked; his last edit, shown until the laptop has it
  function tlData() { return S && S.live && S.live.timeline; }
  function tlCues(tl) { return tlMine && tlMine.key === tl.key && Date.now() - tlMineAt < 3000 ? tlMine.cues : (tl.cues || []); }
  function tlClock(s) { var neg = s < 0; s = Math.abs(s); var m = Math.floor(s / 60), r = s - 60 * m; return (neg ? "-" : "") + m + ":" + (r < 10 ? "0" : "") + r.toFixed(1); }
  function tlName(c) {
    if (c.do === "hit") return c.size === 2 ? "Big hit" : "White hit";
    if (c.do === "section") return (TL_KINDS.filter(function (k) { return k[0] === c.kind; })[0] || ["", c.kind])[1] + " starts";
    var col = COLORS.filter(function (x) { return x[0] === c.color; })[0];
    return [c.feel === "bigger" ? "Bigger" : c.feel === "softer" ? "Softer" : "", col ? col[1] : ""].filter(Boolean).join(", ");
  }
  function tlSave(tl, list, sel) {
    list = tlSort(list);
    tlMine = {key: tl.key, cues: list}; tlMineAt = Date.now();
    tlSel = sel ? list.indexOf(sel) : -1; tlSelKey = tl.key;
    cache.timeline = ""; drawTimeline();
    change([{path: "cues." + tl.key, value: list.length ? list : null}]);
  }
  function tlAct(a, e) {
    var tl = tlData(); if (!tl) return;
    var list = tlCues(tl).map(function (c) { return Object.assign({}, c); }), here = tlHere(tl), c;
    if (tlSelKey !== tl.key) tlSel = -1;
    if (a.pick != null) { tlSel = tlSel === a.pick ? -1 : a.pick; tlSelKey = tl.key; cache.timeline = ""; drawTimeline(); return; }
    if (a.at === "bar") {   // a tap on the picture: pick the nearest cue to it
      var svg = e.target.closest("svg"), box = svg.getBoundingClientRect(), x = (e.clientX - box.left) / box.width;
      var t0 = +svg.getAttribute("data-t0"), t1 = +svg.getAttribute("data-t1"), at = t0 + x * (t1 - t0), best = -1, gap = (t1 - t0) * 0.04;
      list.forEach(function (q, i) { var d = Math.abs(q.at - at); if (d < gap) { gap = d; best = i; } });
      tlSel = best; tlSelKey = tl.key; cache.timeline = ""; drawTimeline(); return;
    }
    if (a.add) {
      if (here == null) { toast("Play the song in Mixxx first: the cue goes where it is."); return; }
      c = Object.assign({at: Math.round(here * 100) / 100, do: a.add}, a.with || {});
      if (list.length >= 48) { toast("A song holds 48 cues. Remove one first."); return; }
      list.push(c);
      var mine = list.some(function (q) { return q !== c && q.do === "section"; });
      if (a.add === "section" && !mine) {   // his first section: the ones Llano found come with it, to nudge;
        // the one he just placed moves Llano's nearest of its kind (within 8 s) rather than adding a second
        var near = null;
        (tl.sections || []).forEach(function (sx) { if (sx.kind === c.kind && Math.abs(sx.start - c.at) < 8 && (!near || Math.abs(sx.start - c.at) < Math.abs(near.start - c.at))) near = sx; });
        (tl.sections || []).forEach(function (sx) { if (sx !== near && Math.abs(sx.start - c.at) > 0.5) list.push({at: Math.max(0, sx.start), do: "section", kind: sx.kind}); });
        toast("Your sections now replace Llano's. Llano's are copied in so you can nudge them.", 6000);
      }
      if (list.length > 48) { toast("That would be more than 48 cues on this song. Remove some first."); return; }
      tlSave(tl, list, c); return;
    }
    if (a.copy) {   // Edit these sections: Llano's, as his to nudge
      (tl.sections || []).forEach(function (sx) { list.push({at: Math.max(0, sx.start), do: "section", kind: sx.kind}); });
      if (list.length > 48) { toast("Llano's sections would take this song past 48 cues. Remove some first."); return; }
      tlSave(tl, list, null); toast("Llano's sections are yours now: pick one and nudge it.", 5000); return;
    }
    if (a.clearSecs) { tlSave(tl, list.filter(function (q) { return q.do !== "section"; }), null); toast("Back to Llano's sections.", 4000); return; }
    c = list[tlSel]; if (!c) return;
    if (a.nudge) c.at = Math.max(0, Math.round((c.at + a.nudge * (a.beats ? tl.beat_s : 1)) * 100) / 100);
    else if (a.to === "here") { if (here == null) return; c.at = Math.round(here * 100) / 100; }
    else if (a.del) { list.splice(tlSel, 1); tlSave(tl, list, null); return; }
    else if (a.set) Object.assign(c, a.set);
    tlSave(tl, list, c);
  }
  // an edit needs the change path (T.change); without it the button stays, grayed with the reason (tlWhy)
  function tlBtn(a, label, extra) { return gate('<button class="lls-btn" data-tl="' + esc(JSON.stringify(a)) + '"' + (extra || "") + '>' + label + '</button>', tlWhy); }
  function tlPicture(tl, list, t0, t1, h, big) {
    var W = 1000, x = function (t) { return ((t - t0) / (t1 - t0)) * W; }, out = [];
    (tl.sections || []).forEach(function (sx) {
      if (sx.end < t0 || sx.start > t1) return;
      var a = Math.max(0, x(sx.start)), b = Math.min(W, x(sx.end));
      out.push('<rect x="' + a.toFixed(1) + '" y="0" width="' + Math.max(1, b - a).toFixed(1) + '" height="' + h + '" fill="' + (TL_KIND_COLOR[sx.kind] || "#222") + '"/>');
    });
    if (big && tl.beat_s > 0.2) {   // beat ticks, so a nudge of one beat reads
      var b0 = tl.beat0 || 0, first = Math.ceil((t0 - b0) / tl.beat_s);
      for (var k = first; b0 + k * tl.beat_s <= t1; k++) { var bx = x(b0 + k * tl.beat_s).toFixed(1); out.push('<line x1="' + bx + '" x2="' + bx + '" y1="' + (h - (k % 4 ? 6 : 12)) + '" y2="' + h + '" stroke="#ffffff' + (k % 4 ? "33" : "77") + '"/>'); }
    }
    list.forEach(function (c, i) {
      if (c.at < t0 || c.at > t1) return;
      var cx = x(c.at).toFixed(1), on = i === tlSel, col = c.do === "hit" ? "#ffffff" : c.do === "section" ? "#7cf0c8" : (c.color || (c.feel === "softer" ? "#6cb8ff" : "#ffb454"));
      out.push('<line x1="' + cx + '" x2="' + cx + '" y1="' + (c.do === "hit" ? 0 : 14) + '" y2="' + h + '" stroke="' + col + '" stroke-width="' + (on ? 5 : c.size === 2 ? 4 : 2.5) + '"/>');
      if (on) out.push('<circle cx="' + cx + '" cy="' + (h - 6) + '" r="6" fill="' + col + '"/>');
    });
    out.push('<line class="lls-ph" x1="-9" x2="-9" y1="0" y2="' + h + '" stroke="#ff6b6b" stroke-width="3"/>');
    return '<svg viewBox="0 0 ' + W + ' ' + h + '" preserveAspectRatio="none" style="height:' + h + 'px" data-t0="' + t0 + '" data-t1="' + t1 + '" data-tl="' + esc(JSON.stringify({at: "bar"})) + '">' + out.join("") + '</svg>';
  }
  function drawTimeline() {
    if (!P.timeline) return;
    var tl = tlData();
    tlWhy = T.change ? "" : (caps().cues || "Add and move cues on the laptop, or on the phone over the laptop's Wi-Fi.");
    if (!tl) {
      cache.timelineKey = "";
      put("timeline", P.timeline, '<h3>Cue timeline</h3><p class="lls-note">Play a song in Mixxx with the live show on: its timeline shows here. ' +
        'Pause where you want a white hit or a change, and add it. Every cue plays on the same note in the night\'s cut.</p>');
      return;
    }
    var list = tlCues(tl), z = tl.zero || 0, here = tlHere(tl), len = tl.length || 0;
    if (tlSelKey !== tl.key || tlSel >= list.length) tlSel = -1;
    var t0 = -z, t1 = (len || Math.max(here || 0, 60)) - z;   // the whole file, in the original's seconds
    // the close-up pages along in 10 s steps, so the panel is rebuilt only when something he sees
    // changes (a rebuild under a finger swallows the tap); the red line and the clock move in place
    var page = here == null ? 0 : Math.floor((here + 1) / 10), c0 = page * 10 - 1 - 2, c1 = c0 + 2 * TL_ZOOM_S + 2;
    var key = JSON.stringify([tl.key, page, here == null, tl.playing, list, tl.sections, tlSel, tl.mine, tlWhy, len, z]);
    if (cache.timelineKey === key) { tlMove(here, z); return; }
    cache.timelineKey = key;
    var sel = list[tlSel], h = '<div class="lls-tlhead"><b title="' + esc(tl.title) + '">' + esc(tl.title) + '</b><span class="lls-tltime">--</span><span class="lls-note">' + (tl.playing ? "playing" : "paused") + '</span></div>';
    h += tlPicture(tl, list, t0, t1, 34, false);
    h += '<div style="height:6px"></div>' + tlPicture(tl, list, c0, c1, 56, true);
    var cur = null, nxt = null;
    (tl.sections || []).forEach(function (sx) { if (here != null && sx.start <= here && here < sx.end) cur = sx; else if (here != null && sx.start > here && !nxt) nxt = sx; });
    var kn = function (k) { return (TL_KINDS.filter(function (x) { return x[0] === k; })[0] || ["", k])[1]; };
    h += '<p class="lls-note" style="margin-top:4px">' + (cur ? "Now: <b>" + esc(kn(cur.kind)) + "</b>" : "") + (nxt ? (cur ? " &middot; " : "") + esc(kn(nxt.kind)) + " at " + tlClock(nxt.start + z) : "") +
      (cur || nxt ? "<br>" : "") + 'Play and pause in Mixxx; the red line is where the song is. Times are Mixxx\'s.</p>';
    if (sel) {
      h += '<div class="lls-tlsel"><div class="lls-row"><span><b>' + esc(tlName(sel)) + '</b> at ' + tlClock(sel.at + z) + '</span></div><div class="lls-btns" style="margin-top:0">' +
        tlBtn({nudge: -1, beats: 1}, "&minus; 1 beat") + tlBtn({nudge: -0.1}, "&minus; 0.1 s") + tlBtn({nudge: 0.1}, "+ 0.1 s") + tlBtn({nudge: 1, beats: 1}, "+ 1 beat") +
        tlBtn({to: "here"}, "Move to the red line", here == null ? " disabled" : "") + tlBtn({del: 1}, "Remove") + '</div>';
      if (sel.do === "hit") h += '<div class="lls-btns">' + tlBtn({set: {size: 1}}, "White hit", sel.size !== 2 ? ' style="outline:1px solid var(--mint)"' : "") + tlBtn({set: {size: 2}}, "Big hit (with strobe)", sel.size === 2 ? ' style="outline:1px solid var(--mint)"' : "") + '</div>';
      if (sel.do === "section") h += '<div class="lls-btns">' + TL_KINDS.map(function (k) { return tlBtn({set: {kind: k[0]}}, k[1], sel.kind === k[0] ? ' style="outline:1px solid var(--mint)"' : ""); }).join("") + '</div>';
      h += '</div>';
    }
    var off = here == null ? " disabled" : "";
    h += '<h3 style="margin-top:12px">Add at the red line</h3><div class="lls-btns" style="margin-top:0">' +
      tlBtn({add: "hit", with: {size: 1}}, "White hit", off) + tlBtn({add: "hit", with: {size: 2}}, "Big hit", off) +
      tlBtn({add: "feel", with: {feel: "bigger", color: ""}}, "Bigger (this section)", off) + tlBtn({add: "feel", with: {feel: "softer", color: ""}}, "Softer (this section)", off) + '</div>' +
      '<div class="lls-btns">' + COLORS.filter(function (x) { return x[0]; }).map(function (x) {
        return gate('<button class="lls-sw" title="' + esc(x[1]) + ' for this section" style="background:' + x[0] + '" data-tl="' + esc(JSON.stringify({add: "feel", with: {feel: "", color: x[0]}})) + '"' + off + '></button>', tlWhy); }).join("") + '</div>' +
      '<p class="lls-note" style="margin-top:4px">Bigger, Softer and a color play for the whole section they sit in.</p>' +
      '<h3 style="margin-top:12px">A section starts at the red line</h3><div class="lls-btns" style="margin-top:0">' + TL_KINDS.map(function (k) { return tlBtn({add: "section", with: {kind: k[0]}}, k[1], off); }).join("") + '</div>' +
      '<div class="lls-btns">' + (list.some(function (q) { return q.do === "section"; }) ? tlBtn({clearSecs: 1}, "Back to Llano's sections") : tlBtn({copy: 1}, "Edit these sections", (tl.sections || []).length ? "" : " disabled")) + '</div>';
    if (list.length) h += '<h3 style="margin-top:12px">This song\'s cues</h3><div class="lls-tllist">' + list.map(function (c, i) {
      return '<button class="' + (i === tlSel ? "on" : "") + '" data-tl="' + esc(JSON.stringify({pick: i})) + '">' + tlClock(c.at + z) + ' &middot; ' + esc(tlName(c)) + '</button>'; }).join("") + '</div>';
    put("timeline", P.timeline, h);
    tlMove(here, z);
  }
  function tlMove(here, z) {   // the red line and the clock, moved in place (no rebuild)
    var tm = P.timeline.querySelector(".lls-tltime"); if (tm) text(tm, here == null ? "--" : tlClock(here + z));
    Array.prototype.forEach.call(P.timeline.querySelectorAll("svg"), function (g) {
      var a = +g.getAttribute("data-t0"), b = +g.getAttribute("data-t1"), ln = g.querySelector(".lls-ph");
      var px = here == null || here < a || here > b ? -9 : ((here - a) / (b - a)) * 1000;
      if (ln) { ln.setAttribute("x1", px.toFixed(1)); ln.setAttribute("x2", px.toFixed(1)); }
    });
  }

  function drawSpot() {
    var s = st(), sp = s.spots, c = caps();
    var key = JSON.stringify([sp.on, sp.pace, sp.color, sp.gobo, sp.dark_jump, sp.why, c.steer]);
    if (cache.spot !== key) {
      cache.spot = key;
      P.spot.innerHTML = !sp.on ? '<h3>The spot</h3><p class="lls-note">The moving heads leave the look and light one place on the floor that you steer, to follow the couple or pick out a table.</p>' +
          '<div class="lls-btns"><button class="lls-btn" ' + cmdAttr({op: "spots", on: true}) + '>Follow someone' + (opts.keys ? " <kbd>F</kbd>" : "") + '</button></div>' :
        '<h3>The spot</h3>' + slider("s:dim", "Spot brightness", sp.dim, "main") + slider("s:room", "Room around it", sp.room) +
        '<h3>Steering speed</h3>' + seg(["slow", "walk", "fast"].map(function (p) { return [p, PACE_NAMES[p]]; }), sp.pace, function (p) { return {op: "spots", pace: p}; })
          .replace('class="lls-seg"', c.steer ? 'class="lls-seg off" data-why="' + esc(c.steer) + '"' : 'class="lls-seg"') +
        '<h3>Color</h3><div class="lls-dots">' + WHEEL.map(function (w) {
          return '<button class="lls-dot ' + (sp.color === w[2] ? "on" : "") + '" style="background:' + w[1] + '" title="' + w[0] + '" ' + cmdAttr({op: "spots", color: w[2]}) + '></button>'; }).join("") + '</div>' +
        '<h3>Shape</h3>' + seg([0, 1, 2, 3, 4, 5, 6, 7].map(function (g) { return [g, g ? String(g) : "Round"]; }), sp.gobo, function (g) { return {op: "spots", gobo: g}; }) +
        '<h3>Long jumps</h3>' + seg([[false, "Glide there"], [true, "Go dark, then appear"]], sp.dark_jump, function (v) { return {op: "spots", dark_jump: v}; }) +
        '<p class="lls-note" style="margin-top:9px">The spot stays where you leave it. Spots off gives the heads back to the look.</p>' +
        (sp.why ? '<p class="why" style="margin-top:8px">' + esc(sp.why) + '</p>' : "");
    }
    if (sp.on) syncSliders(P.spot, {"s:dim": sp.dim, "s:room": sp.room});
  }

  function drawLights() {
    var s = st(), list = (S.catalog && S.catalog.lights) || [];
    var cur = light && (s.touch[light] || s.pins[light]) || null, pinned = !!(light && s.pins[light]);
    var key = JSON.stringify([list.length, light, s.touch, s.pins]);
    if (cache.lights === key) { if (light && cur) syncSliders(P.lights, {"l:dim": cur.off ? 0 : cur.dim}); return; }
    cache.lights = key;
    var h = '<h3>Touch a light</h3><p class="lls-note" style="margin-bottom:8px">Pick one light' + (wide && opts.stageFrame ? " here or in the picture" : "") + " and change it by hand. It keeps your change until you give it back.</p>" +
      '<div class="lls-lights">' + list.map(function (l) {
        return '<button class="lls-light ' + (l.id === light ? "on " : "") + (s.pins[l.id] ? "pin" : s.touch[l.id] ? "touch" : "") + '" data-light="' + l.id + '"><i></i>' + esc(l.name) + '</button>'; }).join("") + '</div>';
    if (light) {
      var name = (list.filter(function (l) { return l.id === light; })[0] || {}).name || light, op = pinned ? "pin" : "touch";
      var val = cur || {color: "#ffffff", dim: 1};
      h += '<h3 style="margin-top:12px">' + esc(name) + (pinned ? " · kept for tonight" : cur ? " · changed by hand" : "") + '</h3>' +
        '<div class="lls-dots">' + COLORS.slice(1).map(function (cx) {
          return '<button class="lls-dot ' + (cur && !cur.off && val.color === cx[0] ? "on" : "") + '" style="background:' + cx[0] + '" title="' + esc(cx[1]) + '" ' + cmdAttr({op: op, id: light, color: cx[0]}) + '></button>'; }).join("") + '</div>' +
        '<div style="margin-top:8px">' + slider("l:dim", "Brightness", val.off ? 0 : val.dim) + '</div>' +
        '<div class="lls-btns">' +
          '<button class="lls-btn" ' + cmdAttr({op: "find", id: light}) + ' title="Blinks this light for 3 seconds so you can see which one it is">Find it</button>' +
          '<button class="lls-btn ' + (cur && cur.off ? "on" : "") + '" ' + cmdAttr({op: op, id: light, off: !(cur && cur.off)}) + '>Off</button>' +
          (pinned ? '<button class="lls-btn on" ' + cmdAttr({op: "unpin", id: light}) + ' title="Let the look have this light again">Stop keeping it</button>'
                  : '<button class="lls-btn" ' + cmdAttr({op: "pin", id: light}) + ' title="Keep this light this way for tonight, through every look, Stop and a restart. It is let go by itself tomorrow.">Keep for tonight</button>') +
          (cur && !pinned ? '<button class="lls-btn" ' + cmdAttr({op: "give_back", id: light}) + '>Give it back</button>' : "") + '</div>';
    }
    if (Object.keys(s.touch).length > 1) h += '<div class="lls-btns"><button class="lls-btn" ' + cmdAttr({op: "give_back"}) + '>Give every light back</button></div>';
    P.lights.innerHTML = h;
  }

  // --- the saved settings (settings_contract): tonight's lights, strobe, drops, colors. The same
  // panel on every path, so a change at a venue with no internet is made on the laptop at once and
  // reaches Llano when the internet is back (his rule, 2026-11-12: settings must work over Wi-Fi too).
  var sdoc = null, docAt = 0, docBusy = false, palShown = "";
  var MOST = {bars: 2, tetras: 6, sticks: 4}, KIND = {bars: "GigBARs", tetras: "Tetras", sticks: "Freedom Sticks"};
  function hueCss(h) { return "hsl(" + Math.round(((h % 1) + 1) % 1 * 360) + " 85% 55%)"; }
  function loadDoc(force) {
    if (!T.settings || docBusy || (!force && Date.now() - docAt < 15000)) return;
    docBusy = true; docAt = Date.now();
    Promise.resolve().then(function () { return T.settings(); }).then(function (r) { if (r && r.settings) { sdoc = r.settings; cache.settings = ""; drawSettings(); } })
      .catch(function () {}).then(function () { docBusy = false; });
  }
  function change(ops) {
    return Promise.resolve().then(function () { return T.change(ops); }).then(function (r) {
      if (r && r.settings) { sdoc = r.settings; docAt = Date.now(); cache.settings = ""; drawSettings(); }
      else { if (r && r.error) toast(r.error, 6000); loadDoc(true); }
      return r;
    }).catch(function () { toast("That change didn't reach the laptop. Nothing was changed."); });
  }
  function opsAttr(ops) { return "data-ops=\"" + esc(JSON.stringify(ops)) + "\""; }
  function toggle(label, path, on, tip) { return '<button class="lls-btn ' + (on ? "on" : "") + '" title="' + esc(tip || "") + '" ' + opsAttr([{path: path, value: !on}]) + '>' + esc(label) + (on ? " · on" : " · off") + '</button>'; }
  function drawSettings() {
    if (!P.settings || !T.settings || !T.change) return;
    if (!sdoc) { put("settings", SB, '<h3>Saved settings</h3><p class="lls-note">Reading them from the laptop...</p>'); return; }
    var key = JSON.stringify([sdoc.rig && sdoc.rig.counts, sdoc.master, sdoc.strobe, sdoc.drop, sdoc.crowd_safe, sdoc.section_palette, sdoc.palettes, palShown]);
    if (cache.settingsKey === key && cache.settings) { syncSaved(); return; }
    cache.settingsKey = key;
    var counts = (sdoc.rig && sdoc.rig.counts) || {}, names = Object.keys(sdoc.palettes || {});
    if (names.indexOf(palShown) < 0) palShown = names[0] || "";
    var h = '<h3>Tonight\'s lights</h3>' + ["bars", "tetras", "sticks"].map(function (k) {
      var n = counts[k] == null ? MOST[k] : counts[k];
      return '<div class="lls-row"><span>' + KIND[k] + '</span><span class="lls-count"><button aria-label="One fewer" ' + opsAttr([{path: "rig.counts." + k, value: Math.max(0, n - 1)}]) + (n <= 0 ? " disabled" : "") + '>−</button><b>' + n + '</b>' +
        '<button aria-label="One more" ' + opsAttr([{path: "rig.counts." + k, value: Math.min(MOST[k], n + 1)}]) + (n >= MOST[k] ? " disabled" : "") + '>+</button></span></div>'; }).join("") +
      '<h3>The saved show</h3>' + slider("d:master", "Brightness", sdoc.master) +
      '<h3>Strobe</h3>' + slider("d:strobe.intensity", "How bright", sdoc.strobe.intensity) + slider("d:strobe.speed", "How fast", sdoc.strobe.speed) +
      '<div class="lls-btns" style="margin-top:0">' + toggle("Crowd-safe", "crowd_safe", sdoc.crowd_safe !== false, "Every strobe stays at the slow end, about 3 flashes a second, whatever a look asks") +
        toggle("In builds", "strobe.build_ramp", !!sdoc.strobe.build_ramp, "The strobe ramps in over a build's last quarter") +
        toggle("On short loops", "strobe.loop_auto", !!sdoc.strobe.loop_auto, "A DJ loop of half a beat or less strobes white while held") + '</div>' +
      '<h3>Drops</h3>' + slider("d:drop.intensity", "How hard they hit", sdoc.drop.intensity) +
      '<div class="lls-btns" style="margin-top:0">' + toggle("White burst", "drop.burst", !!sdoc.drop.burst, "A white strobe burst and the full rig on a drop's first beat") + '</div>' +
      '<h3>Colors, by part of the song</h3>' + Object.keys(sdoc.section_palette || {}).map(function (sec) {
        var cur = sdoc.section_palette[sec], pairs = sdoc.palettes[cur] || [];
        return '<div class="lls-row"><span>' + esc(sec.charAt(0).toUpperCase() + sec.slice(1)) + '</span><span class="lls-sw">' + pairs.slice(0, 5).map(function (p) { return '<i style="background:' + hueCss(p[0]) + '"></i>'; }).join("") + '</span>' +
          '<select data-secpal="' + esc(sec) + '" aria-label="Colors for ' + esc(sec) + '">' + names.map(function (n) { return '<option' + (n === cur ? " selected" : "") + '>' + esc(n) + '</option>'; }).join("") + '</select></div>'; }).join("") +
      '<h3>Change a set of colors</h3>' + seg(names.map(function (n) { return [n, n]; }), palShown, function (n) { return {pal: n}; }) +
      '<div style="margin-top:8px">' + ((sdoc.palettes[palShown] || []).map(function (p, i) {
        return '<div class="lls-pair"><i style="background:linear-gradient(135deg,' + hueCss(p[0]) + ' 50%,' + hueCss(p[1]) + ' 50%)"></i>' +
          '<input type="range" class="lls-hue" min="0" max="100" value="' + Math.round(p[0] * 100) + '" data-hue="' + i + ':0" aria-label="Color ' + (i + 1) + ', main">' +
          '<input type="range" class="lls-hue" min="0" max="100" value="' + Math.round(p[1] * 100) + '" data-hue="' + i + ':1" aria-label="Color ' + (i + 1) + ', second"></div>'; }).join("")) + '</div>' +
      '<p class="lls-note" style="margin-top:9px">A change here is saved on the laptop at once and plays from the next beat. Llano gets it when the laptop is online.</p>';
    cache.settings = h; SB.innerHTML = h;
  }
  function syncSaved() { if (sdoc) syncSliders(SB, {"d:master": sdoc.master, "d:strobe.intensity": sdoc.strobe.intensity, "d:strobe.speed": sdoc.strobe.speed, "d:drop.intensity": sdoc.drop.intensity}); }

  // The moving heads' one control (Llano BL #12339, his ask 2026-11-14): they move by themselves in
  // the dances; Stop heads darkens them until Resume; Take over is Follow someone or a Spotlight pad;
  // Back to auto lets all of that go.
  function headsBar(s) {
    var hd = s.heads || {mode: "auto", line: ""}, m = hd.mode, sp = s.spots;
    var h = '<span class="lls-heads ' + esc(m) + '" title="' + esc(hd.line) + '" data-t-heads="' + esc(m) + '"><i></i><b>Heads</b>' +
      ({auto: "Auto", stop: "Stopped", yours: "Yours"}[m] || esc(m)) + '</span>';
    h += m === "stop" ? '<button class="lls-pill on" ' + cmdAttr({op: "heads", do: "resume"}) + ' title="The heads light and move again">Resume heads</button>'
      : '<button class="lls-pill" ' + cmdAttr({op: "heads", do: "stop"}) + ' title="Every moving head dark and still until you resume them">Stop heads</button>';
    if (!sp.on) {
      h += '<span class="lls-lbl" title="Steer the heads yourself instead of the show">Take over:</span>' +
        '<button class="lls-pill" ' + cmdAttr({op: "spots", on: true}) + '>Follow someone' + (opts.keys ? " <kbd>F</kbd>" : "") + '</button>' +
        '<button class="lls-pill ' + (s.look && s.look.key === "moment:spotlight" ? "on" : "") + '" ' + cmdAttr({op: "look", key: "moment:spotlight"}) + ' title="Every head on one spot roaming the dance floor">Spotlight</button>' +
        '<button class="lls-pill ' + (s.look && s.look.key === "moment:two-spotlights" ? "on" : "") + '" ' + cmdAttr({op: "look", key: "moment:two-spotlights"}) + ' title="One spot per GigBAR, mirrored across the floor">Two spotlights</button>';
    }
    if (m !== "auto") h += '<button class="lls-pill" ' + cmdAttr({op: "heads", do: "auto"}) + ' title="Spots off, Spotlight pads let go, and the show moves the heads again">Back to auto</button>';
    return h;
  }

  function drawStageBar() {
    var s = st(), sp = s.spots, c = caps(), h;
    if (!sp.on) {
      h = headsBar(s) +
          '<button class="lls-pill" data-panelbtn="lights">Touch a light</button><span class="sp"></span><span>' + esc(S.running ? "" : (S.last_run || "")) + '</span>';
    } else {
      h = headsBar(s) + '<button class="lls-pill ' + (sp.count === 1 ? "on" : "") + '" ' + cmdAttr({op: "spots", count: 1}) + '>1 spot</button>' +
          '<button class="lls-pill ' + (sp.count === 2 ? "on" : "") + '" ' + cmdAttr({op: "spots", count: 2}) + '>2 spots</button>';
      if (sp.count === 2) h += seg([[0, "A"], [1, "B"], [2, "Both"]], sp.sel, function (v) { return {op: "spots", sel: v}; });
      h += gate('<button class="lls-pill lls-hoverbtn ' + (sp.hover ? "on" : "") + '" ' + cmdAttr({op: "spots", hover: !sp.hover}) + ' title="The spot follows the pointer over the picture, with no click and no drag. It holds still when the pointer leaves.">Hover follow' + (opts.keys ? " <kbd>H</kbd>" : "") + '</button>', c.hover) +
        (c.hover && !wide ? '<span class="why lls-whynote">' + esc(c.hover) + '</span>' : "");
      sp.marks.forEach(function (m, i) {
        h += '<button class="lls-pill mk" ' + cmdAttr({op: "mark_go", name: m.name}) + '>' + (opts.keys && i < 9 ? "<kbd>" + (i + 1) + "</kbd>" : "") + esc(m.name) + '</button>' +
          // forgetting a place is its own button, beside it, and takes two taps (like Delete on a look)
          '<button class="lls-pill lls-markx' + (markArm === m.name ? " arm" : "") + '" data-delmark="' + esc(m.name) + '" aria-label="Forget ' + esc(m.name) + '" title="Forget this place">' + (markArm === m.name ? "Forget?" : "×") + '</button>';
      });
      h += '<button class="lls-pill" data-act="save-mark">+ Save this place</button><span class="sp"></span>' +
           '<button class="lls-pill" ' + cmdAttr({op: "spots", on: false}) + '>Spots off' + (opts.keys ? " <kbd>F</kbd>" : "") + '</button>';
    }
    var v = view();
    h += '<span class="lls-view" title="Which way you are looking at the room. Steering follows it: left is your left.">View from ' +
      seg([["booth", "DJ booth"], ["floor", "The floor"]], v.from, function (f) { return {op: "view", screen: screen, from: f}; }) +
      '<button class="lls-pill" ' + cmdAttr({op: "view", screen: screen, turn: ((v.turn || 0) + 1) % 4}) + ' title="Turn the picture a quarter turn, for a venue set up sideways">Turn ↻</button></span>';
    put("stagebar", E.stagebar, h);
    var help = "";
    if (sp.on) help = c.steer ? '<span class="why">' + esc(c.steer) + '</span>' :
      opts.keys ? '<kbd>←</kbd> <kbd>↑</kbd> <kbd>↓</kbd> <kbd>→</kbd> hold to move, it eases in and out · <kbd>Shift</kbd> slow · <kbd>Ctrl</kbd> fast · click the floor to send it there' + (sp.count === 2 ? ' · <kbd>Tab</kbd> next spot' : "")
                : c.drag ? "Tap a place on the floor to send the spot there." : "Drag on the floor to move the spot, or tap a place to send it there.";
    else if (wide) help = "This picture is what the lights are doing right now.";
    put("stagehelp", E.stagehelp, help);
  }

  function drawPanels() {
    qa("[data-panelbtn]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-panelbtn") === panel); });
    Object.keys(P).forEach(function (k) { P[k].classList.toggle("on", k === panel); });
    drawLevels(); drawSpot(); drawLights();
    if (panel === "timeline" || !wide) drawTimeline();
    if (T.settings && T.change && (panel === "settings" || !wide)) { loadDoc(false); drawSettings(); }
  }

  var lastSpotsOn = null;
  function draw() {
    if (!S || !S.studio) return;
    var on = S.studio.spots.on;
    if (lastSpotsOn !== null && on !== lastSpotsOn) panel = on ? "spot" : (panel === "spot" ? "levels" : panel);
    if (on && lastSpotsOn !== true && FOLD.heads) FOLD.heads.open = true;   // the picture he steers on is never shut away
    lastSpotsOn = on;
    drawTop(); drawNight(); drawMoods(); drawPads(); drawHits(); drawStageBar(); drawPanels(); drawPlan(); drawFolds();
  }

  // --- the stage: the room picture (laptop) or a floor plan drawn here ---------------------------
  // Hover follow follows the pointer only over the DANCE FLOOR (Llano BL #12383, his words 2026-11-15:
  // "when I come off ... that area quickly to type somewhere else I don't want to keep following my
  // mouse cuz it looks silly"). Off the floor, or off the picture, the spot holds where he was
  // following: the quick stroke that carried the pointer out is trimmed, so the beam never sweeps
  // to the edge after it. Back on the floor it follows again once the pointer has been there a
  // moment, so brushing past the floor does not jerk the beam.
  var HOVER_SETTLE_MS = 120, EXIT_FAST = 4, EXIT_BACK_MS = 400, QUICK_WAIT_MS = 80, QUICK_MAX_MS = 250;   // EXIT_FAST: meters a second
  var hoverIn = 0, hoverTrail = [], settleT = 0, quickT = 0, quickSince = 0;
  function onDanceFloor(x, y) {
    var pl = st().spots.plan, f = pl && pl.floor;
    if (!f) return true;   // a layout with no floor to say: the whole picture, as before
    return x >= f[0] && x <= f[0] + f[2] && y >= f[1] && y <= f[1] + f[3];
  }
  function fastTo(i) {   // the pointer arrived at hoverTrail[i] in a quick stroke
    var a = hoverTrail[i - 1], b = hoverTrail[i];
    if (!a || !b) return false;
    // a pointer reports every frame while it moves, so a long gap before a sample means it sat
    // still and then jumped: the jump took one frame, not the whole gap
    var dt = Math.min(40, Math.max(8, b.t - a.t)) / 1000;
    return Math.hypot(b.x - a.x, b.y - a.y) / dt >= EXIT_FAST;
  }
  function hoverRest() {   // where the pointer last rested on the floor, before any quick stroke out
    var t = hoverTrail, i = t.length - 1, end;
    if (i < 0) return null;
    end = t[i].t;
    while (i > 0 && end - t[i].t <= EXIT_BACK_MS && fastTo(i)) i--;   // back over a stroke up to EXIT_BACK_MS long
    return t[i];
  }
  function hoverExit() {
    var g = soon.goal;
    if (g && g.cmd && g.cmd.hover) { clearTimeout(g.timer); g.timer = 0; g.cmd = null; }   // the newest pointer place is not sent
    clearTimeout(settleT); settleT = 0; clearTimeout(quickT); quickT = 0; quickSince = 0; hoverIn = 0;
    if (!hovering) { hoverTrail = []; return; }
    var p = hoverRest(); hovering = false; hoverTrail = [];
    send(p ? {op: "spot_goal", x: p.x, y: p.y, hover: true} : {op: "spot_hold"}, true);
  }
  function hoverFollow(x, y) {
    hovering = true; sendSoon("goal", {op: "spot_goal", x: x, y: y, hover: true}, 45);
  }
  function stagePointer(kind, x, y, info) {
    var s = st(); if (!s) return;
    var sp = s.spots, c = caps();
    if (kind === "leave") { dragging = false; hoverExit(); return; }
    if (!sp.on) { if (kind === "down" && info && info.light) pickLight(info.light); return; }
    if (kind === "hover") {
      if (!sp.hover || c.hover || c.steer || dragging) return;
      var rx = info && typeof info.rx === "number" ? info.rx : x, ry = info && typeof info.ry === "number" ? info.ry : y;
      if (!(info && typeof info.floor === "boolean" ? info.floor : onDanceFloor(rx, ry))) { hoverExit(); return; }   // the room picture says, or the plan
      var now = Date.now();
      hoverTrail.push({x: x, y: y, t: now});
      while (hoverTrail.length > 2 && now - hoverTrail[1].t > EXIT_BACK_MS + 200) hoverTrail.shift();   // keeps the rest before a stroke
      if (hovering) {
        // a quick stroke is held back until the pointer slows or stops: it may be on its way off
        // the floor, and then the beam must not have started after it
        // (a sweep longer than QUICK_MAX_MS is him chasing someone across the floor: it follows)
        clearTimeout(quickT); quickT = 0;
        if (!fastTo(hoverTrail.length - 1)) { quickSince = 0; hoverFollow(x, y); return; }
        if (!quickSince) quickSince = now;
        if (now - quickSince >= QUICK_MAX_MS) { hoverFollow(x, y); return; }
        quickT = setTimeout(function () { quickT = 0; quickSince = 0; if (hovering && alive) hoverFollow(x, y); }, QUICK_WAIT_MS);
        return;
      }
      if (!hoverIn) {
        hoverIn = now;
        settleT = setTimeout(function () {   // still on the floor after the settle: follow from where it is
          settleT = 0; var q = hoverTrail[hoverTrail.length - 1];
          if (hoverIn && q && alive) hoverFollow(q.x, q.y);
        }, HOVER_SETTLE_MS);
      } else if (now - hoverIn >= HOVER_SETTLE_MS) { clearTimeout(settleT); settleT = 0; hoverFollow(x, y); }
      return;
    }
    if (c.steer) { if (kind === "down") toast(c.steer); return; }
    if (kind === "down") { dragging = true; moved = false; downAt = [x, y]; }
    else if (kind === "drag" && dragging) {
      if (!moved && Math.hypot(x - downAt[0], y - downAt[1]) < 0.12) return;
      if (c.drag) { if (!moved) toast(c.drag, 5000); moved = true; return; }   // a tap still sends it there
      moved = true; sendSoon("goal", {op: "spot_goal", x: x, y: y, drag: true}, 45);
    } else if (kind === "up" && dragging) {
      dragging = false;
      if (!moved && !sp.hover) send({op: "spot_goal", x: downAt[0], y: downAt[1]});   // a click: it travels (or goes dark and appears)
    }
  }
  function pickLight(id) { light = id; panel = "lights"; draw(); }
  function onFrameMessage(e) {
    if (!frame || e.source !== frame.contentWindow || e.origin !== win.location.origin || !e.data) return;
    var m = e.data.llanoStage, k = e.data.llanoStageKey;
    if (m) stagePointer(m.kind, m.x, m.y, m);
    if (k) onKey(k.type, k);
  }
  function planMetrics() {
    var pl = st() && st().spots.plan; if (!pl || !plan) return null;
    var w = plan.clientWidth, h = plan.clientHeight, pad = 14, r = rot(), odd = r % 2, RW = odd ? pl.room[1] : pl.room[0], RD = odd ? pl.room[0] : pl.room[1];
    return {pl: pl, w: w, h: h, k: Math.min((w - 2 * pad) / RW, (h - 2 * pad) / RD), rot: r, cx: w / 2, cy: h / 2};
  }
  function planPt(m, x, y) {   // a place in the room -> where it is drawn, through the view's turn
    var a = (x - m.pl.room[0] / 2) * m.k, b = (y - m.pl.room[1] / 2) * m.k, i, t;
    for (i = 0; i < m.rot; i++) { t = a; a = -b; b = t; }
    return [m.cx + a, m.cy + b];
  }
  function planRoom(m, px, py) {   // and back: where a finger is -> the place in the room
    var a = px - m.cx, b = py - m.cy, i, t;
    for (i = 0; i < m.rot; i++) { t = a; a = b; b = -t; }
    return [a / m.k + m.pl.room[0] / 2, b / m.k + m.pl.room[1] / 2];
  }
  // The floor plan a phone steers on, drawn the way the laptop's stage draws the room (the design
  // he approved): a dark blue stage, soft pools of each light's color, beams that glow from the head
  // to where they land. The laptop works the light out from the real frame (stage_glow.py, state.glow).
  function rgbaHex(hex, a) { var n = parseInt(hex, 16); return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")"; }
  function rr(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
  function glowPool(g, x, y, r, hex, a) {
    if (a <= 0.01 || !(r > 0)) return;
    var gr = g.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, rgbaHex(hex, a)); gr.addColorStop(0.45, rgbaHex(hex, a * 0.45)); gr.addColorStop(1, rgbaHex(hex, 0));
    g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
  }
  function drawPlan() {
    if (!plan || !st()) return;
    var cover = E.stagebox.querySelector(".cover"), m = planMetrics(), sp = st().spots, glow = S.glow;
    cover.textContent = m ? "" : "The floor shows here once the laptop answers.";
    var dpr = win.devicePixelRatio || 1, w = plan.clientWidth, h = plan.clientHeight;
    if (!w || !h) return;   // shut away in the phone's heads fold: drawn when it opens
    if (plan.width !== Math.round(w * dpr) || plan.height !== Math.round(h * dpr)) { plan.width = Math.round(w * dpr); plan.height = Math.round(h * dpr); }
    var g = plan.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    if (!m) return;
    var k = m.k, pl = m.pl, words = [];
    function X(x) { return x * k; } function Y(y) { return y * k; }
    function say(t, x, y, dx, dy, color, font) { words.push([t, planPt(m, x, y), dx, dy, color, font]); }   // drawn upright, after the turn
    g.textAlign = "center";
    g.save(); g.translate(m.cx, m.cy); g.rotate(m.rot * Math.PI / 2); g.translate(-pl.room[0] * k / 2, -pl.room[1] * k / 2);
    rr(g, X(0), Y(0), pl.room[0] * k, pl.room[1] * k, 10); g.fillStyle = "rgba(10,12,19,.55)"; g.fill(); g.strokeStyle = "#2b3145"; g.lineWidth = 1.5; g.stroke();
    rr(g, X(pl.floor[0]), Y(pl.floor[1]), pl.floor[2] * k, pl.floor[3] * k, 6); g.fillStyle = "rgba(255,255,255,.028)"; g.fill();
    g.strokeStyle = "#3a4260"; g.lineWidth = 1; g.setLineDash([5, 5]); g.stroke(); g.setLineDash([]);
    say("dance floor", pl.floor[0] + pl.floor[2] / 2, pl.floor[1] + pl.floor[3] / 2, 0, 4, "#69708a", "11px Segoe UI, sans-serif");
    if (glow) {
      g.save(); rr(g, X(0), Y(0), pl.room[0] * k, pl.room[1] * k, 10); g.clip(); g.globalCompositeOperation = "lighter";
      glow.pools.forEach(function (p) { glowPool(g, X(p[0]), Y(p[1]), p[2] * k, p[3], 0.62 * p[4]); });
      glow.beams.forEach(function (b) {
        var ax = X(b[0]), ay = Y(b[1]), bx = X(b[2]), by = Y(b[3]), len = Math.hypot(bx - ax, by - ay) || 1, nx = -(by - ay) / len, ny = (bx - ax) / len, wd = 0.42 * k;
        var gr = g.createLinearGradient(ax, ay, bx, by); gr.addColorStop(0, rgbaHex(b[4], 0.5 * b[5])); gr.addColorStop(1, rgbaHex(b[4], 0.1 * b[5]));
        g.fillStyle = gr; g.beginPath(); g.moveTo(ax + nx * 2.5, ay + ny * 2.5); g.lineTo(bx + nx * wd, by + ny * wd); g.lineTo(bx - nx * wd, by - ny * wd); g.lineTo(ax - nx * 2.5, ay - ny * 2.5); g.closePath(); g.fill();
        glowPool(g, bx, by, 0.95 * k, "ffffff", 0.5 * b[5]); glowPool(g, bx, by, 1.25 * k, b[4], 0.75 * b[5]);
      });
      g.globalCompositeOperation = "source-over"; g.restore();
    }
    rr(g, X(pl.booth[0]), Y(pl.booth[1]), pl.booth[2] * k, pl.booth[3] * k, 6); g.fillStyle = "#141826"; g.fill(); g.strokeStyle = "#30374d"; g.lineWidth = 1; g.stroke();
    say("DJ booth", pl.booth[0] + pl.booth[2] / 2, pl.booth[1] + pl.booth[3] / 2, 0, 4, "#8a91a6", "12px Segoe UI, sans-serif");
    var barDy = m.rot === 2 ? 22 : -13;
    if (glow) {
      glow.lamps.forEach(function (l) {
        if (l[2] === "t") rr(g, X(l[0]) - 9, Y(l[1]) - 4, 18, 8, 2); else rr(g, X(l[0]) - 4.5, Y(l[1]) - 4.5, 9, 9, 2);
        g.fillStyle = l[4] > 0.02 ? rgbaHex(l[3], 0.55 + 0.45 * l[4]) : "#2b3040"; g.fill();
      });
      glow.bars.forEach(function (b, i) {
        g.lineCap = "round"; g.strokeStyle = "#3b4360"; g.lineWidth = 13; g.beginPath(); g.moveTo(X(b[0]), Y(b[1])); g.lineTo(X(b[2]), Y(b[3])); g.stroke();
        g.strokeStyle = "#1a1f30"; g.lineWidth = 10.5; g.stroke(); g.lineCap = "butt";
        [[b[0], b[1]], [b[2], b[3]]].forEach(function (hd) {
          var lit = glow.beams.some(function (bm) { return bm[0] === hd[0] && bm[1] === hd[1]; });
          g.fillStyle = lit ? "#eaf4ff" : "#59617a"; g.strokeStyle = lit ? "#6cb8ff" : "#3b4360"; g.lineWidth = 1.5; g.beginPath(); g.arc(X(hd[0]), Y(hd[1]), 5.5, 0, 7); g.fill(); g.stroke();
        });
        say("GigBAR " + (i + 1), (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 0, barDy, "#8a91a6", "11px Segoe UI, sans-serif");
      });
    } else pl.bars.forEach(function (b, i) { g.fillStyle = "#3b4360"; rr(g, X(b[0]) - 18, Y(b[1]) - 5, 36, 10, 5); g.fill(); say("GigBAR " + (i + 1), b[0], b[1], 0, barDy, "#8a91a6", "11px Segoe UI, sans-serif"); });
    g.restore();
    words.forEach(function (wd) { g.fillStyle = wd[4]; g.font = wd[5]; g.fillText(wd[0], wd[1][0] + wd[2], wd[1][1] + wd[3]); });
    g.fillStyle = "#69708a"; g.font = "11px Segoe UI, sans-serif"; g.textAlign = "left";
    g.fillText(view().from === "booth" ? "From the DJ booth, looking out" : "From the floor, facing the booth", 10, 16); g.textAlign = "center";
    if (!sp.on) return;
    sp.marks.forEach(function (mk, i) {
      var q = planPt(m, mk.x, mk.y);
      g.fillStyle = "#0b1826"; g.strokeStyle = "#6cb8ff"; g.lineWidth = 1.5; g.beginPath(); g.arc(q[0], q[1], 9, 0, 7); g.fill(); g.stroke();
      g.fillStyle = "#bfe0ff"; g.font = "700 11px Segoe UI, sans-serif"; g.fillText(String(i + 1), q[0], q[1] + 4);
      g.fillStyle = "#8fa4bf"; g.font = "11px Segoe UI, sans-serif"; g.textAlign = "left"; g.fillText(mk.name, q[0] + 13, q[1] + 4); g.textAlign = "center";
    });
    sp.at.forEach(function (p, i) {
      var mine = sp.count === 1 || sp.sel === 2 || sp.sel === i, q0 = planPt(m, p[0], p[1]), x = q0[0], y = q0[1], go = sp.going && sp.going[i];
      if (go) { var q1 = planPt(m, go[0], go[1]); g.strokeStyle = "#6cb8ff"; g.setLineDash([3, 5]); g.lineWidth = 1.5; g.beginPath(); g.moveTo(x, y); g.lineTo(q1[0], q1[1]); g.stroke(); g.setLineDash([]); }
      g.strokeStyle = mine ? "#6cb8ff" : "#52607a"; g.lineWidth = mine ? 2.5 : 1.5; g.beginPath(); g.arc(x, y, 20, 0, 7); g.stroke();
      if (mine) { g.strokeStyle = "rgba(108,184,255,.22)"; g.lineWidth = 7; g.beginPath(); g.arc(x, y, 20, 0, 7); g.stroke(); }
      g.fillStyle = "#bfe0ff"; g.font = "700 12px Segoe UI, sans-serif"; g.fillText(sp.count === 2 ? "Spot " + "AB"[i] : "Spot", x, y - 27);
      if (sp.dark[i]) { g.fillStyle = "#8fa4bf"; g.font = "11px Segoe UI, sans-serif"; g.fillText("dark, moving", x, y + 36); }
    });
  }
  function planPoint(ev) {
    var m = planMetrics(); if (!m) return null;
    var r = plan.getBoundingClientRect(), q = planRoom(m, ev.clientX - r.left, ev.clientY - r.top);
    return [Math.max(0, Math.min(m.pl.room[0], q[0])), Math.max(0, Math.min(m.pl.room[1], q[1])), q[0], q[1]];
  }
  if (opts.stageFrame) {
    frame = doc.createElement("iframe"); frame.title = "The room, and what the lights are doing"; frame.src = opts.stageFrame;
    E.stagebox.appendChild(frame);
    win.addEventListener("message", onFrameMessage);
    frame.addEventListener("pointerleave", function () { stagePointer("leave"); });   // a flick out of the picture faster than it says so
  } else {
    plan = doc.createElement("canvas"); E.stagebox.appendChild(plan);
    var cov = doc.createElement("div"); cov.className = "cover"; E.stagebox.appendChild(cov);
    plan.addEventListener("pointerdown", function (ev) { var p = planPoint(ev); if (!p) return; try { plan.setPointerCapture(ev.pointerId); } catch (x) {} ev.preventDefault(); stagePointer("down", p[0], p[1]); });
    plan.addEventListener("pointermove", function (ev) { var p = planPoint(ev); if (!p) return; stagePointer(dragging ? "drag" : "hover", p[0], p[1], {rx: p[2], ry: p[3]}); });
    plan.addEventListener("pointerup", function (ev) { var p = planPoint(ev) || downAt || [0, 0]; stagePointer("up", p[0], p[1]); });
    plan.addEventListener("pointercancel", function () { dragging = false; });
    plan.addEventListener("pointerleave", function () { stagePointer("leave"); });
  }

  // --- presses --------------------------------------------------------------------------------------
  function pressPad(key) {
    var s = st(); if (!s) return;
    if (stopped === 3 || stopped === 4) stopped = false;   // he lit the room on purpose
    endPeek();
    send(s.look && s.look.key === key ? {op: "release"} : {op: "look", key: key});
  }
  function act(name, el) {
    if (name === "stop") { var wasLost = lost; stopped = 1; stopAt = Date.now();
      // refused or never answered (not lost): one story, straight away, never a later "STOP was sent"
      var failed = function () { if (!wasLost) { stopped = 4; stopAt = Date.now(); E.toast.hidden = true; if (S && S.studio) draw(); } };
      // sent first, before anything is drawn: a drawing error must never swallow STOP (Llano BL #12419)
      var going; try { going = T.stop(); } catch (x) { going = Promise.reject(x); }
      Promise.resolve(going).then(function (r) { if (!r || r.error || r.ok === false) failed(); poll0(); }, function () { failed(); poll0(); });
      if (wasLost) toast("STOP was sent. If the lights are still on, press Stop on the laptop.", 8000);
      if (S && S.studio) draw(); }
    else if (name === "lock") { locked = !locked; arrows = {}; draw(); }
    else if (name === "next") { if (stopped === 3 || stopped === 4) stopped = false; send({op: "next"}); }
    else if (name === "ack") { if (T.ack) Promise.resolve(T.ack()).then(poll0); }
    else if (name === "run") { if (stopped) stopped = false; toast(el.getAttribute("data-mode") === "live" ? "Starting the live show..." : "Starting with no lights...", 2500);
      Promise.resolve().then(function () { return T.run(el.getAttribute("data-mode")); }).then(function (r) { if (r && r.error && !r.warned) toast(r.error, 7000); else if (r && r.error) E.toast.hidden = true; poll0(); }).catch(function () { toast("That didn't reach the laptop."); }); }
    else if (name === "save-look") ask("Name this look", "like Our first dance", function (n) { send({op: "pad_save", name: n}).then(function (r) { if (r && r.ok) { page = "mine"; draw(); toast("Saved on the Mine page."); } }); });
    else if (name === "save-mark") ask("Name this place", "like Cake table", function (n) { send({op: "mark_save", name: n}); });
    else if (name === "sync-start") syncStart();
    else if (name === "sync-tap") syncTap();
    else if (name === "sync-cancel") syncCancel();
    else if (name === "ask-ok") askDone(true);
    else if (name === "ask-no") askDone(false);
    else if (name === "warn-ok") { askDone(false); if (T.ack) Promise.resolve(T.ack()).then(poll0); }
  }
  function poll0() { clearTimeout(pollT); pollGen++; poll(); }
  function onFocus(e) {   // a Tonight row reached with the keyboard shows its press line too
    var n = e.target.closest && e.target.closest("[data-step]");
    if (n && n.matches(":focus-visible") && openStep !== +n.getAttribute("data-step")) { openStep = +n.getAttribute("data-step"); draw(); var f = E.steps.querySelector('[data-step="' + openStep + '"]'); if (f) f.focus(); }
  }
  function onClick(e) {
    // lost: nothing but STOP (always sent: the laptop may be slow, not gone) and the way out under the message
    if (lost && !e.target.closest(".lls-stop") && !e.target.closest(".lls-lostmsg")) { e.preventDefault(); e.stopPropagation(); return; }
    var n, t = e.target, off = t.closest(".off[data-why]");
    if (asking && !E.toast.contains(t)) askDone(false);   // he moved on: the name box closes, nothing is saved
    if ((n = t.closest(".lls-banner")) && !wide && S && S.warning) { warnBox(S.warning); return; }
    if (off && host.contains(off)) { toast(off.getAttribute("data-why"), 5000); e.preventDefault(); return; }
    n = t.closest(".wait");
    if (n && host.contains(n)) { e.preventDefault(); return; }   // already on its way to the laptop
    if ((n = t.closest("[data-del]"))) {   // delete a saved look: a second press within 3 s confirms
      var nm = n.getAttribute("data-del"); e.stopPropagation();
      if (delArm === nm) { delArm = ""; send({op: "pad_del", name: nm}); }
      else { delArm = nm; clearTimeout(delT); delT = setTimeout(function () { delArm = ""; cache.pads = ""; draw(); }, 3000); cache.pads = ""; draw(); }
      return;
    }
    if ((n = t.closest("[data-step]"))) { var si = +n.getAttribute("data-step"); openStep = openStep === si ? -1 : si; draw(); return; }
    if ((n = t.closest("[data-delmark]"))) {   // a second tap within 3 s forgets the place
      var mn = n.getAttribute("data-delmark"); clearTimeout(markT);
      if (markArm === mn) { markArm = ""; send({op: "mark_del", name: mn}); }
      else { markArm = mn; toast("Tap again to forget " + mn, 3000); markT = setTimeout(function () { markArm = ""; if (S && S.studio) draw(); }, 3000); draw(); }
      return;
    }
    if ((n = t.closest("[data-pad]"))) { waitOn(n); pressPad(n.getAttribute("data-pad")); return; }
    if ((n = t.closest("[data-page]"))) { page = n.getAttribute("data-page"); try { win.localStorage.setItem("lls-page", page); } catch (x) {} draw(); return; }
    if ((n = t.closest("[data-panelbtn]"))) { panel = n.getAttribute("data-panelbtn"); draw(); if (!wide) { var fd = P[panel].closest("details"); if (fd) fd.open = true; P[panel].scrollIntoView({block: "start", behavior: "smooth"}); } return; }
    if ((n = t.closest("[data-light]"))) { light = light === n.getAttribute("data-light") ? "" : n.getAttribute("data-light"); draw(); return; }
    if ((n = t.closest("[data-hit]"))) { if (caps().hits === "latch") { var nm2 = n.getAttribute("data-hit"); waitOn(n); send({op: "hit", name: nm2, on: st().hits.indexOf(nm2) < 0}); } return; }
    if ((n = t.closest("[data-act]"))) { if (/^(next|run)$/.test(n.getAttribute("data-act"))) waitOn(n);   /* never STOP: it must always take a press */ act(n.getAttribute("data-act"), n); return; }
    if ((n = t.closest("[data-tl]"))) { if (!n.disabled) tlAct(JSON.parse(n.getAttribute("data-tl")), e); return; }
    if ((n = t.closest("[data-ops]"))) {
      if (n.disabled) return;
      var ops = JSON.parse(n.getAttribute("data-ops"));
      // Crowd-safe off is the one setting that can hurt someone: it asks once before it goes
      if (ops.some(function (o) { return o.path === "crowd_safe" && o.value === false; }))
        confirmAsk("Turn Crowd-safe off? Strobes can then flash faster and brighter.", "Turn it off", "Keep it on", function () { change(ops); });
      else change(ops);
      if (n.getAttribute("data-syncsave")) syncCancel();
      return;
    }
    if ((n = t.closest("[data-cmd]"))) { if (n.disabled) return; var cmd = JSON.parse(n.getAttribute("data-cmd"));
      if (cmd.pal) { palShown = cmd.pal; cache.settingsKey = ""; drawSettings(); return; }   /* which set of colors the editor shows */
      if (cmd.op === "spots" && cmd.pace) basePace = cmd.pace;
      if (cmd.op !== "tap" && cmd.op !== "timing") waitOn(n);   // tapping a tempo is many presses on purpose
      send(cmd); }
  }
  // White-out, strobe and color burst are on only while a finger or the mouse holds them.
  var holding = {};
  // A quick tap sends on and off a few ms apart; sent side by side, the laptop's threads could take
  // off first and leave a strobe flashing (3 in 30 quick taps on the phone). So each hit's presses
  // go one after another: off is sent only once on has been answered (BL #11473).
  var hitChain = Promise.resolve();
  // each send in the chain has a time limit: one stalled request never holds back every later hit and off
  function limited(cmd) { return Promise.race([send(cmd), new Promise(function (ok) { setTimeout(ok, ASK_MS); })]); }
  function hitSend(cmd) { hitChain = hitChain.then(function () { return limited(cmd); }, function () { return limited(cmd); }); return hitChain; }
  // C: a hold whose pointer-up never came (the screen locked or the page hid with a finger down) is let go
  function releaseHolds() {
    Object.keys(holding).forEach(function (k) { var nm = holding[k]; hitSend({op: "hit", name: nm, on: false});
      var b = host.querySelector('[data-hit="' + nm + '"]'); if (b) b.classList.remove("on"); if (lost) quietHits[nm] = 1; });
    holding = {};
  }
  function hitDown(e) {
    tabbed = false;   // any press with a pointer: Enter is Next again
    var n = e.target.closest("[data-hit]"); if (!n || lost || caps().hits === "latch") return;
    var name = n.getAttribute("data-hit"); e.preventDefault();
    try { n.setPointerCapture(e.pointerId); } catch (x) {}
    holding[e.pointerId] = name; n.classList.add("on"); hitSend({op: "hit", name: name, on: true});
  }
  function hitUp(e) {
    var name = holding[e.pointerId]; if (!name) return;
    delete holding[e.pointerId]; hitSend({op: "hit", name: name, on: false});   // lost or not: the off always goes
    if (lost) quietHits[name] = 1;   // and goes again once the laptop answers
  }
  function onInput(e) {
    if (lost) return;
    var inp = e.target, k = inp.getAttribute && inp.getAttribute("data-slide"); if (!k) return;
    var v = +inp.value / 100; busy[k] = Date.now() + 900; inp.style.setProperty("--v", inp.value + "%");
    var lab = inp.parentNode.querySelector("[data-val]"); if (lab) lab.textContent = inp.value + "%";
    if (k.slice(0, 2) === "d:") return;   // a saved setting: sent when he lets go (onChange), not on every step
    var cmd = k.slice(0, 2) === "m:" ? {op: "master", zone: k.slice(2), value: v} : k === "s:dim" ? {op: "spots", dim: v} : k === "s:room" ? {op: "spots", room: v} :
      k === "l:dim" && light ? {op: st().pins[light] ? "pin" : "touch", id: light, dim: v, off: false} : null;
    if (cmd) sendSoon(k, cmd, 70);
  }
  function onChange(e) {
    var tg = e.target, k = tg.getAttribute && tg.getAttribute("data-slide");
    if (k && tg.blur) tg.blur();   // the arrow keys stay the spot's
    if (k && k.slice(0, 2) === "d:") { change([{path: k.slice(2), value: Math.max(k === "d:master" ? 0.1 : k === "d:drop.intensity" ? 0.2 : k === "d:strobe.speed" ? 0.1 : 0, +tg.value / 100)}]); return; }
    if (tg.getAttribute && tg.getAttribute("data-secpal")) { change([{path: "section_palette." + tg.getAttribute("data-secpal"), value: tg.value}]); return; }
    var hue = tg.getAttribute && tg.getAttribute("data-hue");
    if (hue && sdoc && sdoc.palettes[palShown]) {
      var at = hue.split(":"), pairs = sdoc.palettes[palShown].map(function (p) { return [p[0], p[1]]; });
      pairs[+at[0]][+at[1]] = Math.min(0.99, +tg.value / 100);
      change([{path: "palettes." + palShown, value: pairs}]);
    }
  }
  // Look before you press (laptop): resting the pointer on a pad plays it in the picture only.
  function endPeek() { clearTimeout(peekT); clearInterval(peekIv); peekIv = 0; if (peekKey) { peekKey = ""; if (T.peek) Promise.resolve(T.peek("")).catch(function () {}); } }
  function onOver(e) {
    if (!T.peek || caps().peek) return;
    var n = e.target.closest && e.target.closest("[data-pad]"), key = n ? n.getAttribute("data-pad") : "";
    if (key === (peekKey || cache.peekWant || "")) return;
    cache.peekWant = key; clearTimeout(peekT);
    if (!key) { endPeek(); return; }
    peekT = setTimeout(function () {
      if (st() && st().look && st().look.key === key) return;   // it is already live
      peekKey = key; var ping = function () { Promise.resolve(T.peek(key)).catch(function () {}); };
      ping(); clearInterval(peekIv); peekIv = setInterval(ping, 1000);
    }, 350);
  }
  function onLeaveHost() { cache.peekWant = ""; endPeek(); }

  // --- the keyboard (laptop) -----------------------------------------------------------------------------
  function steer(mod) {
    var dx = (arrows.ArrowRight ? 1 : 0) - (arrows.ArrowLeft ? 1 : 0), dy = (arrows.ArrowDown ? 1 : 0) - (arrows.ArrowUp ? 1 : 0), i, t;
    for (i = 0; i < rot(); i++) { t = dx; dx = dy; dy = -t; }   // left is HIS left: the keys turn with the view
    send({op: "spot_key", dx: dx, dy: dy, pace: mod.shiftKey ? "slow" : mod.ctrlKey ? "fast" : basePace}, true);
  }
  function onKey(type, e) {   // true = the key was the studio's
    if (!opts.keys || !st()) return false;
    if (tap.phase === "playing" && e.key === " ") { if (type === "keydown" && !e.repeat) syncTap(); return true; }
    var key = e.key || "", low = key.length === 1 ? key.toLowerCase() : key, s = st(), sp = s.spots;
    if (type === "keyup") {
      if (arrows[key]) { delete arrows[key]; if (sp.on) steer(e); return true; }
      if ((key === "Shift" || key === "Control") && sp.on && Object.keys(arrows).length) { steer(e); return true; }
      return false;
    }
    if (e.altKey || e.metaKey) return false;
    if (low === "l" && !e.ctrlKey) { if (!e.repeat) act("lock"); return true; }
    if (locked) return key.length === 1 || /^Arrow|Enter|Tab/.test(key);   // swallowed: a bumped key changes nothing
    if (/^Arrow/.test(key)) {
      if (!sp.on) return false;
      if (caps().steer) { if (!e.repeat) toast(caps().steer); return true; }
      if (!arrows[key]) { arrows[key] = true; steer(e); }
      return true;
    }
    if ((key === "Shift" || key === "Control") && sp.on && Object.keys(arrows).length) { if (!e.repeat) steer(e); return true; }
    if (e.repeat) return key.length === 1 && !e.ctrlKey;
    if (e.ctrlKey) { if (low === "z") { send({op: "undo"}); return true; } return false; }
    if (key === "Enter") { if (stopped === 3 || stopped === 4) stopped = false; send({op: "next"}); return true; }
    if (key === "Tab") { if (sp.on && sp.count === 2) { send({op: "spots", sel: (sp.sel + 1) % 3}); return true; } return sp.on; }
    if (low === "b") { send({op: "blackout"}); return true; }
    if (low === "f") { send({op: "spots", on: !sp.on}); return true; }
    if (low === "h") { if (sp.on) { if (caps().hover) toast(caps().hover); else send({op: "spots", hover: !sp.hover}); } else toast("Hover follow steers a spot: press F to turn the spots on first."); return true; }
    if (sp.on && /^[1-9]$/.test(key)) { var mk = sp.marks[+key - 1]; if (mk) send({op: "mark_go", name: mk.name}); return true; }
    var hit = padKeys().map[low];
    if (hit) { page = hit[0]; pressPad(hit[1]); return true; }
    return false;
  }
  function onKeyDown(e) { var tg = e.target; if (tg && (/TEXTAREA|SELECT/.test(tg.tagName) || (tg.tagName === "INPUT" && tg.type !== "range"))) return;
    // a question is open: no console key acts under it (Enter, B...); Esc answers the safe way
    if (asking) { if (e.key === "Escape") { askDone(false); e.preventDefault(); } return; }
    // Enter or Space on a Tonight row or its Go here now presses THAT button, never Next
    if ((e.key === "Enter" || e.key === " ") && tg && tg.closest && tg.closest("[data-step], .lls-steppress button")) return;
    // a button he TABBED to takes Enter itself; after a mouse click Enter is still Next. (:focus-visible
    // cannot tell: Chrome turns it on for any key pressed on a focused button, so Tab is tracked here)
    if (e.key === "Tab") tabbed = true;
    if ((e.key === "Enter" || e.key === " ") && tabbed && tg && /^(BUTTON|A|SUMMARY)$/.test(tg.tagName || "") && host.contains(tg)) return; if (onKey("keydown", e)) e.preventDefault(); }
  function onKeyUp(e) { onKey("keyup", e); }
  function onBlur() { if (Object.keys(arrows).length) { arrows = {}; if (st() && st().spots.on) send({op: "spot_key", dx: 0, dy: 0}, true); } }

  function tick() {   // the beat light and the held clock run between polls
    if (!alive) return;
    if (S && S.studio) {
      var lv = S.live, on = false;
      if (lv && lv.playing && lv.bpm > 0) { var beat = lv.beat + (Date.now() / 1000 - lv.at) * lv.bpm / 60; on = beat - Math.floor(beat) < 0.3; }
      E.beat.classList.toggle("beat", on || (!!S.running && !(lv && lv.bpm > 0)));
      var look = S.studio.look;
      if (look && !S.studio.blackout) text(E.heldsub, "Held " + mmss(heldFor(look)) + " · stays until you release it");
    }
    rafT = win.requestAnimationFrame(tick);
  }

  try { var saved = win.localStorage.getItem("lls-page"); if (saved) page = saved; } catch (x) {}
  host.addEventListener("click", onClick);
  host.addEventListener("focusin", onFocus);
  doc.addEventListener("visibilitychange", onVisible);
  win.addEventListener("focus", wake);
  host.addEventListener("pointerdown", hitDown);
  host.addEventListener("pointerup", hitUp);
  host.addEventListener("pointercancel", hitUp);
  host.addEventListener("input", onInput);
  host.addEventListener("change", onChange);
  host.addEventListener("pointerover", onOver);
  host.addEventListener("pointerleave", onLeaveHost);
  if (opts.keys) { doc.addEventListener("keydown", onKeyDown); doc.addEventListener("keyup", onKeyUp); win.addEventListener("blur", onBlur); }
  win.addEventListener("resize", drawPlan);
  poll(); watchLost(); rafT = win.requestAnimationFrame(tick);

  return {
    refresh: poll0,
    destroy: function () {
      alive = false; clearTimeout(pollT); clearTimeout(lostT); if (topRO) topRO.disconnect(); clearTimeout(waitT); clearTimeout(settleT); clearTimeout(quickT); win.cancelAnimationFrame(rafT); endPeek();
      host.removeEventListener("click", onClick); host.removeEventListener("focusin", onFocus); doc.removeEventListener("visibilitychange", onVisible); win.removeEventListener("focus", wake); host.removeEventListener("pointerdown", hitDown); host.removeEventListener("pointerup", hitUp);
      host.removeEventListener("pointercancel", hitUp); host.removeEventListener("input", onInput); host.removeEventListener("change", onChange);
      host.removeEventListener("pointerover", onOver); host.removeEventListener("pointerleave", onLeaveHost);
      doc.removeEventListener("keydown", onKeyDown); doc.removeEventListener("keyup", onKeyUp); win.removeEventListener("blur", onBlur);
      win.removeEventListener("message", onFrameMessage); win.removeEventListener("resize", drawPlan);
      host.classList.remove("lls", "lls-wide", "lls-phone", "lls-lost"); host.innerHTML = "";
    }
  };
}

var api = {mount: mount, version: 1};
if (typeof window !== "undefined") window.LlanoStudio = api;
if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
