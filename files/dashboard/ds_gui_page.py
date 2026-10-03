"""ds_gui_page：儀表板前端頁面字串 PAGE（HTML/CSS/JS），內容逐字不變。"""
# CODEMAP: 介面：今日 Input／Output、DS／Claude；無游標藍光，保留其他動畫。
# CODEMAP: 分析：快取率、平均 tokens、通過率、耗時、七日趨勢、任務排行。
# CODEMAP: 最近 40 筆、當地啟動日、覆蓋率；JS：usageSummary／updateAnalysis／updateStats。
PAGE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DS 派工儀表板</title>
<style>
:root{--bg:#f6f6f3;--panel:#fff;--ink:#1b1b19;--mute:#77776f;--line:#e7e6e0;--acc:#3d6af2;--ok:#1e9e68;--bad:#d54a3f;--warn:#c68a1c;--code:#f2f1ec;--shadow:0 1px 2px rgba(20,20,10,.04),0 6px 18px rgba(20,20,10,.05);--lift:0 10px 28px rgba(20,20,10,.09);--ease:cubic-bezier(.2,.8,.2,1)}
@media (prefers-color-scheme:dark){:root{--bg:#131313;--panel:#1d1d1c;--ink:#ecebe6;--mute:#8f8e87;--line:#2f2f2d;--acc:#7c9dff;--ok:#4cc790;--bad:#ff7b6e;--warn:#e2b04d;--code:#262625;--shadow:0 1px 2px rgba(0,0,0,.3),0 6px 18px rgba(0,0,0,.25);--lift:0 10px 28px rgba(0,0,0,.45)}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Segoe UI","Microsoft JhengHei",sans-serif;display:flex;flex-direction:column;position:relative}
header,main{position:relative;z-index:1}
header{display:flex;flex-wrap:wrap;gap:8px 26px;align-items:center;padding:13px 22px;border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--panel) 82%,transparent);backdrop-filter:blur(10px)}
header h1{font-size:16px;margin:0;font-weight:650;display:flex;align-items:center;gap:10px;letter-spacing:.01em}
.pulse{position:relative;width:8px;height:8px;border-radius:50%;background:var(--mute);transition:background .4s}
.pulse.on{background:var(--acc)}.pulse::after{content:"";position:absolute;inset:0;border-radius:50%;background:inherit;opacity:0}
.pulse.on::after{animation:ping 1.7s ease-out infinite}
@keyframes ping{0%{transform:scale(1);opacity:.55}100%{transform:scale(3);opacity:0}}
.stat{color:var(--mute);white-space:nowrap}.stat b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
main{flex:1;min-height:0;display:grid;grid-template-columns:350px 1fr}
@media (max-width:820px){main{grid-template-columns:1fr;grid-template-rows:auto 1fr}}
aside{overflow:auto;border-right:1px solid var(--line);padding:6px 14px 18px}
section.detail{overflow:auto;padding:18px 26px 40px;min-width:0}
.enter{opacity:0!important;transform:translateY(10px)!important}
.spot{position:relative;overflow:hidden}
.group{transition:opacity .5s var(--ease),transform .5s var(--ease)}
.ghead{display:flex;align-items:center;gap:8px;width:100%;background:none;border:0;border-bottom:1px solid var(--line);padding:14px 4px 8px;margin-top:4px;color:var(--ink);font:inherit;cursor:pointer;text-align:left}
.ghead .chev{width:14px;height:14px;position:relative;flex:none;transition:transform .35s var(--ease)}
.ghead .chev::before{content:"";position:absolute;left:3px;top:3px;width:6px;height:6px;border:solid var(--mute);border-width:0 1.6px 1.6px 0;transform:rotate(45deg);transition:border-color .2s}
.group.closed .chev{transform:rotate(-90deg)}
.ghead:hover .gname{color:var(--acc)}.ghead:hover .chev::before{border-color:var(--acc)}
.ghead .gname{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;transition:color .2s}
.ghead .gcount{margin-left:auto;color:var(--mute);font-size:12px;white-space:nowrap;transition:color .3s}
.ghead.busy .gcount{color:var(--acc)}
.gbody{display:grid;grid-template-rows:1fr;transition:grid-template-rows .45s var(--ease)}
.group.closed .gbody{grid-template-rows:0fr}
.ginner{overflow:hidden;min-height:0;padding-top:8px}
.tag{font-size:11px;color:var(--mute);border:1px solid var(--line);border-radius:5px;padding:0 6px;white-space:nowrap;line-height:17px}
.qhead{font-size:12px;color:var(--mute);margin:6px 4px 6px}
.card{position:relative;overflow:hidden;display:block;width:100%;text-align:left;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 13px 13px;margin-bottom:8px;cursor:pointer;color:inherit;font:inherit;box-shadow:var(--shadow);transition:opacity .45s ease,transform .4s var(--ease),border-color .25s,box-shadow .3s}
.card:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--acc) 50%,var(--line));box-shadow:var(--lift)}
.card:active{transform:scale(.985)}
.card.sel{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc),var(--shadow)}
.card.pending{opacity:.5;cursor:default}.card.pending:hover{transform:none;box-shadow:var(--shadow);border-color:var(--line)}
.card .t{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card .m{color:var(--mute);font-size:12px;margin-top:3px;display:flex;gap:4px 10px;flex-wrap:wrap;align-items:center}
.card .c2{margin-top:2px}
.card .bar{position:absolute;left:0;right:0;bottom:0;height:2px}
.card .bar i{display:block;height:100%;width:0;background:var(--acc);transition:width .9s var(--ease),background .4s}
.card .bar i.ind{width:34%;animation:slide 1.6s ease-in-out infinite}
.card[data-state=done] .bar i{width:100%;background:var(--ok)}
.card[data-state=failed] .bar i{width:100%;background:var(--bad)}
.card[data-state=interrupted] .bar i{width:100%;background:var(--warn)}
@keyframes slide{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}
.dot{position:relative;display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;background:var(--mute);vertical-align:middle;transition:background .4s}
.dot::after{content:"";position:absolute;inset:0;border-radius:50%;background:inherit;opacity:0}
[data-state=running]>.t>.dot,[data-state=running]>h2>.dot{background:var(--acc)}
[data-state=running]>.t>.dot::after,[data-state=running]>h2>.dot::after{animation:ping 1.6s ease-out infinite}
[data-state=done]>.t>.dot,[data-state=done]>h2>.dot{background:var(--ok)}
[data-state=failed]>.t>.dot,[data-state=failed]>h2>.dot{background:var(--bad)}
[data-state=interrupted]>.t>.dot,[data-state=interrupted]>h2>.dot{background:var(--warn)}
.chip{display:inline-block;padding:1px 10px;border-radius:99px;font-size:12px;border:1px solid var(--line);color:var(--mute);background:var(--panel);margin-left:10px;vertical-align:middle;transition:color .3s,border-color .3s}
.chip[data-state=running]{color:var(--acc);border-color:var(--acc)}.chip[data-state=done]{color:var(--ok);border-color:var(--ok)}
.chip[data-state=failed]{color:var(--bad);border-color:var(--bad)}.chip[data-state=interrupted]{color:var(--warn);border-color:var(--warn)}
.swap{animation:swap .55s var(--ease)}
@keyframes swap{from{opacity:0;transform:translateY(12px)}}
h2{font-size:19px;margin:0 0 4px;font-weight:650}.sub{color:var(--mute);word-break:break-all;font-size:13px}
.flow{position:sticky;top:10px;z-index:3;display:flex;align-items:flex-start;margin:18px 0 4px;padding:16px 20px 12px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow-x:auto}
.fn{display:flex;flex-direction:column;align-items:center;gap:7px;min-width:52px;font-size:12px;color:var(--mute);transition:color .4s,opacity .5s,transform .5s var(--ease)}
.fdot{position:relative;width:16px;height:16px;border-radius:50%;border:2px solid var(--line);background:var(--panel);transition:background .45s,border-color .45s,transform .5s cubic-bezier(.3,1.7,.5,1)}
.fdot::before{content:"";position:absolute;inset:0;margin:auto;color:#fff;text-align:center;font-size:11px;line-height:12px;font-weight:700}
.fn.active{color:var(--ink)}
.fn.active .fdot{border-color:var(--acc);background:var(--acc);transform:scale(1.18)}
.fn.active .fdot::after{content:"";position:absolute;inset:-2px;border-radius:50%;border:2px solid var(--acc);animation:ring 1.7s ease-out infinite}
@keyframes ring{0%{transform:scale(1);opacity:.7}100%{transform:scale(2.4);opacity:0}}
.fn.done .fdot{background:var(--ok);border-color:var(--ok)}
.fn.done .fdot::before{content:"";left:4px;top:1px;width:4px;height:8px;margin:0;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg) scale(0);animation:tick .45s .1s var(--ease) forwards}
@keyframes tick{to{transform:rotate(45deg) scale(1)}}
.fn.bad{color:var(--bad)}.fn.bad .fdot{background:var(--bad);border-color:var(--bad)}.fn.bad .fdot::before{content:"×"}
.fn.warn{color:var(--warn)}.fn.warn .fdot{background:var(--warn);border-color:var(--warn)}.fn.warn .fdot::before{content:"!"}
.fc{position:relative;flex:1;min-width:26px;height:2px;margin:7px 8px 0;background:var(--line);border-radius:2px;overflow:hidden}
.fc b{position:absolute;inset:0;width:0;background:var(--ok);transition:width .8s var(--ease)}
.fc.full b{width:100%}
.fc.go b{width:100%;background:linear-gradient(90deg,var(--ok),var(--acc))}
.fc.go::after{content:"";position:absolute;top:0;bottom:0;width:38%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.8),transparent);animation:sweep 1.4s linear infinite}
@keyframes sweep{from{transform:translateX(-100%)}to{transform:translateX(360%)}}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:14px 0}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px 11px;box-shadow:var(--shadow);transition:opacity .55s var(--ease),transform .55s var(--ease),border-color .25s,box-shadow .3s}
.tile:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--acc) 45%,var(--line));box-shadow:var(--lift)}
.tile small{display:block;color:var(--mute);font-size:12px}
.tile b{display:block;font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;transition:color .3s;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meter{display:block;height:3px;border-radius:3px;background:var(--line);margin-top:7px;overflow:hidden}
.meter i{display:block;height:100%;width:0;background:var(--ok);transition:width 1s var(--ease),background .4s}
.err{color:var(--bad)}
.tabs{position:relative;display:flex;gap:2px;border-bottom:1px solid var(--line);margin:20px 0 10px}
.tabs button{background:none;border:0;padding:8px 15px;color:var(--mute);cursor:pointer;font:inherit;transition:color .25s,transform .2s}
.tabs button:hover,.tabs button.on{color:var(--ink)}.tabs button:active{transform:scale(.94)}
.tabs .ink{position:absolute;bottom:-1px;left:0;width:0;height:2px;background:var(--acc);border-radius:2px;transition:left .4s var(--ease),width .4s var(--ease)}
.ev{padding:7px 4px;border-bottom:1px solid var(--line);font-size:13px;transition:opacity .5s ease,transform .5s var(--ease),background .25s}
.ev:hover{background:color-mix(in srgb,var(--panel) 70%,transparent)}
.ev .h{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.ev .ts{color:var(--mute);font-variant-numeric:tabular-nums;min-width:46px;font-size:12px}
.ev .tool{font-weight:600}.ev .arg{color:var(--mute);font-family:ui-monospace,Consolas,monospace;word-break:break-all;font-size:12px}
.ev pre,.doc{background:var(--code);border-radius:8px;padding:9px 12px;overflow:auto;max-height:300px;margin:6px 0;font:12px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.doc{max-height:none;transition:opacity .5s,transform .5s var(--ease)}
.ev.note{background:var(--code);border-radius:8px;padding:8px 12px;margin:5px 0;border:0}
.ev.round{padding:3px 4px;font-size:12px;color:var(--mute);border-bottom:0;margin-top:6px}.ev.round b{color:var(--ink)}
details summary{cursor:pointer;color:var(--mute);list-style:none;transition:color .2s}details summary:hover{color:var(--ink)}
details[open] pre{animation:drop .3s var(--ease)}
@keyframes drop{from{opacity:0;transform:translateY(-4px)}}
.chip.ph,.card .m .ph{color:var(--acc)}
.live{display:flex;gap:5px;padding:12px 6px}
.live i{width:5px;height:5px;border-radius:50%;background:var(--mute);animation:bob 1.2s ease-in-out infinite}
.live i:nth-child(2){animation-delay:.15s}.live i:nth-child(3){animation-delay:.3s}
@keyframes bob{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-4px);opacity:1}}
.empty{color:var(--mute);padding:56px 0;text-align:center;display:flex;flex-direction:column;align-items:center;gap:16px}
.empty .ring{width:22px;height:22px;border-radius:50%;border:2px solid var(--line);animation:breathe 2.6s ease-in-out infinite}
@keyframes breathe{0%,100%{transform:scale(.8);opacity:.5}50%{transform:scale(1.15);opacity:1;border-color:var(--acc)}}
.overview{position:relative;z-index:1;padding:18px 22px 14px;border-bottom:1px solid var(--line)}
.overview-heading{display:flex;align-items:baseline;justify-content:space-between;gap:8px 20px;flex-wrap:wrap;margin-bottom:12px}
.overview-heading h2{font-size:15px;margin:0}.scope{font-size:12px;color:var(--mute)}
.usage-grid{display:grid;grid-template-columns:1fr 1fr 1.1fr;gap:14px}
.usage-card{padding:16px 20px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);transition:opacity .55s var(--ease),transform .55s var(--ease),box-shadow .3s}
.usage-card:hover{box-shadow:var(--lift)}
.usage-label{display:flex;justify-content:space-between;align-items:center;color:var(--mute);font-size:12px;letter-spacing:.06em}
.usage-label strong{color:var(--acc);font-size:13px}.output .usage-label strong{color:var(--ok)}
.usage-value{display:block;font-size:clamp(30px,3.4vw,48px);font-weight:700;line-height:1.2;letter-spacing:-.045em;font-variant-numeric:tabular-nums;margin:10px 0 12px;overflow-wrap:anywhere}
.provider-line{display:flex;justify-content:space-between;gap:12px;color:var(--mute);font-size:12px;margin-top:4px}.provider-line b{color:var(--ink);font-variant-numeric:tabular-nums;font-weight:600}
.usage-note{font-size:11px;color:var(--mute);margin-top:9px}
.insight-card h3{font-size:13px;margin:0 0 10px}.metrics{display:grid;grid-template-columns:1fr 1fr;gap:12px 20px}
.metric small{display:block;font-size:11px;color:var(--mute)}.metric b{display:block;font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}.metric span{font-size:11px;color:var(--mute)}
.analysis{margin-top:12px}.analysis>summary{display:flex;align-items:center;gap:10px;font-size:12px;padding:5px 0}.analysis>summary::before{content:'＋';color:var(--acc)}.analysis[open]>summary::before{content:'−'}
.analysis-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:24px;padding:14px 0 2px}.analysis[open] .analysis-grid{animation:drop .3s var(--ease)}
.analysis h3{font-size:12px;margin:0 0 10px}.legend{display:flex;gap:14px;color:var(--mute);font-size:11px}.legend i{display:inline-block;width:7px;height:7px;margin-right:5px;background:var(--acc);border-radius:2px}.legend .out{background:var(--ok)}
.trend{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px;margin-top:8px}.day{min-width:0;text-align:center;color:var(--mute);font-size:11px}.day.today{color:var(--ink);font-weight:600}.day-total{font-size:10px;min-height:16px}
.bars{height:64px;display:flex;justify-content:center;align-items:flex-end;gap:4px;border-bottom:1px solid var(--line);margin:4px 0 6px}.bars i{width:20%;max-width:18px;background:var(--acc);border-radius:3px 3px 0 0;transition:height .8s var(--ease)}.bars .out{background:var(--ok)}
.rank-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 14px;margin-bottom:9px;font-size:12px}.rank-row button{padding:0;text-align:left;border:0;background:none;color:var(--ink);font:inherit;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}.rank-row button:hover{color:var(--acc)}.rank-row b{font-weight:600;font-variant-numeric:tabular-nums}.rank-row .meter{grid-column:1/-1;margin-top:0}.rank-row .meter i{background:var(--acc)}
button:focus-visible,summary:focus-visible{outline:2px solid var(--acc);outline-offset:3px}
main{min-height:360px}header .err{white-space:normal}
@media (max-width:1000px){.usage-grid{grid-template-columns:1fr 1fr}.insight-card{grid-column:1/-1}.metrics{grid-template-columns:repeat(4,1fr)}}
@media (max-width:820px){html,body{height:auto;min-height:100%}main{display:block}aside{max-height:320px;border-right:0;border-bottom:1px solid var(--line)}section.detail{padding:18px 16px 30px}.overview{padding:16px}.analysis-grid{grid-template-columns:1fr;gap:18px}}
@media (max-width:480px){.usage-grid{gap:10px}.usage-card{padding:13px 12px}.usage-value{font-size:30px}.provider-line{flex-wrap:wrap;gap:0 6px}.metrics{grid-template-columns:1fr 1fr}.scope{font-size:11px}.analysis>summary{flex-wrap:wrap}.trend{gap:5px}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
.diag{margin-left:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:5px 13px;color:var(--ink);font:inherit;cursor:pointer;transition:border-color .25s,color .25s,transform .2s}
.diag:hover{border-color:var(--acc);color:var(--acc)}.diag:active{transform:scale(.96)}
.scrim{position:fixed;inset:0;z-index:19;background:rgba(15,15,10,.3);opacity:0;pointer-events:none;transition:opacity .4s}
.scrim.on{opacity:1;pointer-events:auto}
.sheet{position:fixed;top:0;right:0;bottom:0;z-index:20;width:min(440px,94vw);padding:18px 20px 40px;background:var(--panel);border-left:1px solid var(--line);box-shadow:var(--lift);overflow:auto;transform:translateX(102%);transition:transform .42s var(--ease)}
.sheet.on{transform:none}
.sheet h3{font-size:13px;margin:20px 0 8px;color:var(--ink)}
.sheet .shead{display:flex;align-items:center;justify-content:space-between;gap:10px}
.sheet .shead h2{font-size:16px;margin:0}
.sheet .x{background:none;border:0;color:var(--mute);font-size:19px;line-height:1;padding:2px 7px;border-radius:6px;cursor:pointer}
.sheet .x:hover{color:var(--ink);background:var(--code)}
.prow{display:flex;justify-content:space-between;gap:10px;align-items:baseline;font-size:12px;color:var(--mute);margin-bottom:4px}
.prow b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.lv{display:inline-block;padding:0 7px;margin-right:6px;border-radius:99px;font-size:11px;font-weight:600;border:1px solid currentColor}.lv.low{color:var(--ok)}.lv.mid{color:var(--warn)}.lv.high{color:var(--bad)}
.rank-row.click{cursor:pointer}.rank-row.click:hover span{color:var(--acc)}
.irow{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:2px 10px;align-items:baseline;width:100%;text-align:left;background:none;border:0;font:inherit;color:var(--ink);padding:6px 2px;cursor:pointer;border-bottom:1px solid var(--line);transition:color .2s}
.irow:hover{color:var(--acc)}
.irow b{font-weight:600;color:var(--mute);font-variant-numeric:tabular-nums}
.sevtag{font-size:11px;border:1px solid var(--line);border-radius:5px;padding:0 6px;margin-left:8px;color:var(--mute);white-space:nowrap;line-height:17px}
.sevtag[data-sev=high]{color:var(--bad);border-color:var(--bad)}
.sevtag[data-sev=warn]{color:var(--warn);border-color:var(--warn)}
.fcard{position:relative;padding:9px 12px 10px 15px;border:1px solid var(--line);border-radius:10px;background:var(--panel);margin-bottom:8px;box-shadow:var(--shadow);transition:opacity .45s ease,transform .45s var(--ease)}
.fcard .sev{position:absolute;left:0;top:0;bottom:0;width:4px;border-radius:10px 0 0 10px;background:var(--mute)}
.fcard[data-sev=high] .sev{background:var(--bad)}.fcard[data-sev=warn] .sev{background:var(--warn)}
.fcard .ft{font-weight:650}.fcard .fd{margin-top:3px;font-size:12px}.fcard .fh{margin-top:5px;font-size:12px;color:var(--mute)}
.diag-empty{display:flex;align-items:center;gap:9px;color:var(--mute);padding:22px 0}
.diag-empty .ok{color:var(--ok);font-size:17px}
</style></head><body>
<header><h1><span class="pulse" id="pulse"></span>DS 派工儀表板</h1>
<span class="stat">執行中 <b id="s-run">0</b></span><span class="stat">今日任務 <b id="s-n">0</b></span>
<span class="stat err" id="s-conn"></span><button class="diag" id="diag-open">用量診斷</button></header>
<section class="overview" aria-label="用量總覽">
<div class="overview-heading"><h2>今日用量 <span class="scope" id="usage-date"></span></h2><span class="scope" id="usage-scope">今日啟動任務的累計用量 · 最近 40 筆紀錄範圍</span></div>
<div class="usage-grid">
<article class="usage-card spot"><div class="usage-label"><strong>INPUT · 輸入</strong><span>tokens</span></div><b class="usage-value" id="today-in">—</b>
<div class="provider-line"><span>DeepSeek</span><b id="ds-in">—</b></div><div class="provider-line"><span>Claude</span><b id="cc-in">—</b></div>
<div class="usage-note">含快取輸入 · 快取讀取 DS <b id="ds-hit">—</b> / Claude <b id="cc-hit">—</b></div></article>
<article class="usage-card spot output"><div class="usage-label"><strong>OUTPUT · 輸出</strong><span>tokens</span></div><b class="usage-value" id="today-out">—</b>
<div class="provider-line"><span>DeepSeek</span><b id="ds-out">—</b></div><div class="provider-line"><span>Claude</span><b id="cc-out">—</b></div>
<div class="usage-note">DeepSeek 輸出含推理 · <span id="usage-coverage">等待資料</span></div></article>
<article class="usage-card spot insight-card"><h3>今日分析</h3><div class="metrics">
<div class="metric"><small>快取命中率</small><b id="today-cache">—</b><span id="cache-note">命中 ÷ 總輸入</span></div>
<div class="metric"><small>每任務平均 tokens</small><b id="today-average">—</b><span>僅計有用量紀錄的任務</span></div>
<div class="metric"><small>已結束任務通過率</small><b id="today-success">—</b><span id="success-note">等待資料</span></div>
<div class="metric"><small>平均完成耗時</small><b id="today-duration">—</b><span>僅計通過的任務</span></div>
</div></article></div>
<details class="analysis"><summary>統計與趨勢 <span class="scope">近七日用量 · 今日任務排行</span></summary><div class="analysis-grid">
<div><h3>近七日輸入／輸出</h3><div class="legend"><span><i></i>Input</span><span><i class="out"></i>Output</span><span>依任務啟動日歸類</span></div><div class="trend" id="usage-trend"></div></div>
<div><h3>今日用量最高任務 <span class="scope">Input + Output</span></h3><div id="usage-ranking"></div></div>
</div></details></section>
<main><aside id="list"></aside><section class="detail" id="detail"><div class="empty"><i class="ring"></i>等待派工…</div></section></main>
<script>
const $=s=>document.querySelector(s);
const h=(tag,props,...kids)=>{const e=document.createElement(tag);for(const[k,v]of Object.entries(props||{})){if(k==='class')e.className=v;else if(k.startsWith('on'))e[k]=v;else if(v!==false&&v!=null)e.setAttribute(k,v)}for(const c of kids.flat()){if(c==null||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)))}return e};
const STATE_TXT={running:'執行中',done:'通過',failed:'失敗',interrupted:'中斷'};
const PH_TXT={spec:'規格',work:'實作',verify:'驗收',probe:'探測',review:'審查'};
const TILES={
  ds:[['turns','實作輪數'],['tools','工具呼叫'],['hit','輸入・命中快取'],['miss','輸入・未命中'],['out','輸出'],['rate','快取命中率'],['dur','耗時'],['verify','驗收'],['model','模型']],
  cc:[['type','類型'],['tools','工具呼叫'],['miss','輸入（未快取）'],['write','快取寫入'],['hit','快取讀取'],['out','輸出'],['rate','快取命中率'],['dur','耗時']]};
const TAB_DEFS=[['events','活動'],['brief','簡報'],['spec','規格'],['report','報告'],['diag','診斷']];
const now=()=>Date.now()/1000;
const isCC=r=>r.source==='claude';
const fmtDur=s=>{s=Math.max(0,Math.round(s));return s<60?s+'秒':Math.floor(s/60)+'分'+String(s%60).padStart(2,'0')+'秒'};
const fmtTok=n=>n==null?'—':n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':String(n);
const clip=(s,n)=>{s=String(s??'');return s.length>n?s.slice(0,n-1)+'…':s};
const ease=t=>1-Math.pow(1-t,3);
const tokIn=r=>r.tokens?r.tokens.in:null,tokOut=r=>r.tokens?r.tokens.out:null;
const elapsed=r=>(r.state==='running'?now():(r.t1||now()))-r.t0;
const enter=el=>{el.classList.add('enter');requestAnimationFrame(()=>requestAnimationFrame(()=>el.classList.remove('enter')));return el};
const place=(c,ns)=>{const cur=c.children;if(cur.length===ns.length&&ns.every((n,i)=>cur[i]===n))return;c.replaceChildren(...ns)};
function tween(el,to,fmt=fmtTok){
  if(to==null){if(el._raf)cancelAnimationFrame(el._raf);el._v=null;el.textContent='—';return}
  const from=el._v==null?0:el._v;el._v=to;
  if(el._raf)cancelAnimationFrame(el._raf);
  if(matchMedia('(prefers-reduced-motion: reduce)').matches){el.textContent=fmt(to);return}
  if(from===to){el.textContent=fmt(to);return}
  const t0=performance.now(),dur=650;
  const step=t=>{const k=Math.min(1,(t-t0)/dur);el.textContent=fmt(Math.round(from+(to-from)*ease(k)));if(k<1)el._raf=requestAnimationFrame(step)};
  el._raf=requestAnimationFrame(step)}
let data={runs:[],queues:[]},sel=null,tab='events',D={id:null},busy=false;
let closed=new Set();try{closed=new Set(JSON.parse(localStorage.getItem('ds_closed')||'[]'))}catch(e){}
const saveClosed=()=>{try{localStorage.setItem('ds_closed',JSON.stringify([...closed]))}catch(e){}};
const cards=new Map(),groups=new Map(),misc=new Map();
const emptyList=h('div',{class:'empty'},h('i',{class:'ring'}),'還沒有派工紀錄');

function usageLevel(r){if(!r.tokens)return null;const t=r.tokens.in+r.tokens.out;return t<20000?['低','low']:t<100000?['中','mid']:['高','high']}
function levelTag(r){const l=usageLevel(r);return l?h('span',{class:'lv '+l[1],title:'用量等級（Input+Output：低 <2 萬、中 <10 萬、高 ≥10 萬 tokens）'},'用量'+l[0]):null}
function timeSpan(r){return h('span',{class:'tm','data-t0':r.t0,'data-run':r.state==='running'?'1':'0'},fmtDur(elapsed(r)))}
function makeCard(id){
  const el=h('button',{class:'card spot'},h('span',{class:'bar'},h('i')),
    h('div',{class:'t'},h('span',{class:'dot'}),h('span',{class:'tt'})),h('div',{class:'m'}),h('div',{class:'m c2'}));
  el.onclick=()=>select(id);
  return enter(el)}
function fillCard(el,r,showChat){
  el.dataset.state=r.state;
  el.classList.toggle('sel',sel===r.id);
  el.querySelector('.tt').textContent=(r.task?r.task+' · ':'')+r.title;
  el.querySelector('.m').replaceChildren(...[
    h('span',null,STATE_TXT[r.state]),h('span',{class:'tag'},isCC(r)?'Claude':'DeepSeek'),
    r.state==='running'&&r.active.length?h('span',{class:'ph'},r.active.map(p=>PH_TXT[p]).join('＋')):null,
    isCC(r)?h('span',null,r.tool_calls+' 次工具'):h('span',null,'第 '+r.turns+' 輪'),
    h('span',null,'入 '+fmtTok(tokIn(r))+' / 出 '+fmtTok(tokOut(r))),levelTag(r),timeSpan(r)].filter(Boolean));
  const c2=el.querySelector('.c2');c2.textContent=showChat&&r.session_title?'對話：'+r.session_title:'';c2.hidden=!c2.textContent;
  const i=el.querySelector('.bar i');
  if(r.state==='running'&&(isCC(r)||!r.max_turns)){i.classList.add('ind');i.style.width=''}
  else{i.classList.remove('ind');i.style.width=r.state==='running'?Math.min(100,r.turns/r.max_turns*100)+'%':''}
  return el}
function cardFor(r,showChat){
  let el=cards.get(r.id);
  if(!el){el=makeCard(r.id);cards.set(r.id,el)}
  return fillCard(el,r,showChat)}
function makeGroup(key){
  const head=h('button',{class:'ghead'},h('span',{class:'chev'}),h('span',{class:'gname'}),h('span',{class:'tag'}),h('span',{class:'gcount'}));
  const inner=h('div',{class:'ginner'});
  const root=h('div',{class:'group'},head,h('div',{class:'gbody'},inner));
  head.onclick=()=>{const c=root.classList.toggle('closed');c?closed.add(key):closed.delete(key);saveClosed()};
  enter(root);
  return{root,head,inner}}
function miscNode(key,make){let n=misc.get(key);if(!n){n=make();misc.set(key,n)}return n}
function renderList(){
  const gm=new Map();
  const grp=g=>{if(!gm.has(g.key))gm.set(g.key,{g,runs:[],queues:[],last:0});return gm.get(g.key)};
  data.runs.forEach(r=>{const o=grp(r.group);o.runs.push(r);o.last=Math.max(o.last,r.t0)});
  data.queues.forEach(q=>{const o=grp(q.group);o.queues.push(q);o.last=Math.max(o.last,q.t0||0)});
  const roots=[];
  [...gm.values()].sort((a,b)=>b.last-a.last).forEach(o=>{
    const key=o.g.key;
    let G=groups.get(key);
    if(!G){G=makeGroup(key);groups.set(key,G)}
    G.root.classList.toggle('closed',closed.has(key));
    G.head.title=o.g.path||'';
    G.head.querySelector('.gname').textContent=o.g.label;
    G.head.querySelector('.tag').textContent=o.g.kind==='project'?'專案':'對話';
    const running=o.runs.filter(r=>r.state==='running').length;
    G.head.querySelector('.gcount').textContent=(running?running+' 執行中 · ':'')+o.runs.length+' 個';
    G.head.classList.toggle('busy',running>0);
    const chats=new Set(o.runs.map(r=>r.session)).size,nodes=[],inQ=new Set();
    o.queues.forEach(q=>{
      const runs=data.runs.filter(r=>r.queue===q.out_dir);runs.forEach(r=>inQ.add(r.id));
      const done=runs.filter(r=>r.state==='done').length;
      const qh=miscNode('q:'+q.out_dir,()=>h('div',{class:'qhead'}));
      qh.textContent='佇列 '+q.label+'　'+done+'/'+q.tasks.length+' 完成'+(q.state!=='running'?(q.ok?'　✔ 全部通過':'　✘ '+q.state):'');
      nodes.push(qh);
      q.tasks.forEach(t=>{
        const r=runs.find(x=>x.task===t.id);
        if(r){nodes.push(cardFor(r,false));return}
        const p=miscNode('p:'+q.out_dir+':'+t.id,()=>enter(h('div',{class:'card pending'},h('div',{class:'t'},h('span',{class:'dot'}),t.id),h('div',{class:'m'}))));
        p.querySelector('.m').textContent='等待中'+(t.after.length?'（依賴 '+t.after.join(', ')+'）':'');
        nodes.push(p)})});
    o.runs.filter(r=>!inQ.has(r.id)).forEach(r=>nodes.push(cardFor(r,chats>1)));
    place(G.inner,nodes);
    roots.push(G.root)});
  for(const k of [...groups.keys()])if(!gm.has(k))groups.delete(k);
  for(const id of [...cards.keys()])if(!data.runs.some(r=>r.id===id))cards.delete(id);
  place($('#list'),roots.length?roots:[emptyList])}
function select(id){
  if(sel===id)return;
  sel=id;
  cards.forEach((el,k)=>el.classList.toggle('sel',k===id));
  syncDetail();pollDetail()}

function newEv(){return{next:0,el:null,live:null,last:{},first:true}}
function moveInk(){
  if(!D.tabs)return;
  const b=D.tabs.querySelector('button.on'),ink=D.tabs.querySelector('.ink');
  if(b&&ink){ink.style.left=b.offsetLeft+'px';ink.style.width=b.offsetWidth+'px'}}
function setTab(k){
  if(tab===k)return;
  tab=k;D.ev=newEv();D.doc=null;D.body.replaceChildren();
  D.tabs.querySelectorAll('button').forEach((b,i)=>b.classList.toggle('on',TAB_DEFS[i][0]===k));
  moveInk();pollDetail()}
function buildDetail(r){
  const kind=isCC(r)?'cc':'ds',tiles={};
  const kv=h('div',{class:'kv'});
  TILES[kind].forEach(([k,l],i)=>{
    const s=h('small',null,l),b=h('b',null,'—');
    const t=h('div',{class:'tile spot'},s,b,k==='rate'?h('span',{class:'meter'},h('i')):null);
    t.style.transitionDelay=i*50+'ms';enter(t);
    setTimeout(()=>{t.style.transitionDelay=''},1000);
    tiles[k]={t,s,b};kv.append(t)});
  const head=h('div',{class:'dhead'},h('h2',null,h('span',{class:'dot'}),h('span',{class:'dtitle'}),h('span',{class:'chip st'})),h('div',{class:'sub'}));
  const flow=h('div',{class:'flow'});
  const tabs=h('div',{class:'tabs'},...TAB_DEFS.map(([k,n])=>h('button',{class:tab===k?'on':'',onclick:()=>setTab(k)},n)),h('span',{class:'ink'}));
  const body=h('div',{class:'dbody'});
  $('#detail').replaceChildren(h('div',{class:'swap'},head,flow,kv,tabs,body));
  D={id:r.id,kind,tiles,head,flow,tabs,body,fnodes:new Map(),fsig:'',ev:newEv(),doc:null};
  requestAnimationFrame(moveInk)}
function flowSync(r){
  const seen=k=>r.phases.includes(k),cc=isCC(r),running=r.state==='running';
  const steps=cc?['work','end']:[...(r.intent||seen('spec')?['spec']:[]),'work',...(r.verify_cmd||seen('verify')?['verify']:[]),...['probe','review'].filter(seen),'end'];
  const lastSeen=[...r.phases].filter(p=>steps.includes(p)).pop()||'work';
  let act=new Set(running?r.active:[]);
  if(running&&r.last==='verify')act=new Set(['verify']);
  if(running&&!act.size)act.add(lastSeen);
  const idx=[...act].map(k=>steps.indexOf(k)).filter(i=>i>=0);
  const first=idx.length?Math.min(...idx):steps.length;
  const failKey=r.state==='failed'&&r.verify_runs.length&&r.verify_runs[r.verify_runs.length-1]!==0&&steps.includes('verify')?'verify':lastSeen;
  const stop=steps.indexOf(failKey);
  const st={};
  steps.forEach((k,i)=>{
    if(k==='end'){st[k]=running?'pending':r.state==='done'?'done':r.state==='failed'?'bad':'warn';return}
    if(running){st[k]=act.has(k)?'active':i<first?'done':'pending';return}
    if(r.state==='done'){st[k]='done';return}
    st[k]=i<stop?'done':i===stop?(r.state==='failed'?'bad':'warn'):'pending'});
  const sig=steps.join(',');
  const node=k=>{let n=D.fnodes.get(k);if(!n){n=enter(h('div',{class:'fn'},h('i',{class:'fdot'}),h('span',null)));D.fnodes.set(k,n)}return n};
  const conn=k=>{let n=D.fnodes.get('c:'+k);if(!n){n=h('div',{class:'fc'},h('b'));D.fnodes.set('c:'+k,n)}return n};
  if(sig!==D.fsig){
    D.fsig=sig;
    const list=[];
    steps.forEach((k,i)=>{if(i)list.push(conn(k));list.push(node(k))});
    D.flow.replaceChildren(...list)}
  steps.forEach((k,i)=>{
    const n=node(k);
    n.className='fn '+st[k];
    n.querySelector('span').textContent=k==='end'?(running?'完成':STATE_TXT[r.state]):(cc&&k==='work'?'執行':PH_TXT[k]);
    if(i){
      const prev=st[steps[i-1]];
      conn(k).className='fc'+(prev==='done'?(st[k]==='active'?' go':st[k]==='pending'?'':' full'):'')}})}
function updateDetail(r){
  const {head,tiles}=D,t=r.tokens;
  head.dataset.state=r.state;
  head.querySelector('.dtitle').textContent=r.title;
  const chip=head.querySelector('.st');chip.textContent=STATE_TXT[r.state];chip.dataset.state=r.state;
  head.querySelector('.sub').textContent=[r.workspace,r.verify_cmd?'驗收：'+r.verify_cmd:null,isCC(r)?'Claude 內建 · '+(r.agent_type||''):null,r.escalated?'已升級 Pro':null].filter(Boolean).join('　');
  flowSync(r);
  const set=(k,v,f)=>tiles[k]&&tween(tiles[k].b,v,f);
  set('tools',r.tool_calls,n=>n+(r.errors?'（'+r.errors+' 錯）':''));
  if(D.kind==='ds'){
    set('turns',r.turns,n=>n+(r.max_turns?' / '+r.max_turns:''));
    set('hit',t?t.hit:null);set('miss',t?t.miss:null);set('out',t?t.out:null);
    tiles.out.s.textContent='輸出'+(t&&t.think?'（含思考 '+fmtTok(t.think)+'）':'');
    tiles.verify.b.textContent=r.verify_runs.length?r.verify_runs.map(x=>x===0?'✔':'✘'+x).join(' '):'—';
    tiles.model.b.textContent=r.model||'—'}
  else{
    tiles.type.b.textContent=r.agent_type||'—';
    set('miss',t?t.miss-t.write:null);set('write',t?t.write:null);set('hit',t?t.hit:null);set('out',t?t.out:null)}
  const pct=t&&t.in?Math.round(t.hit/t.in*100):null,low=pct!=null&&pct<50&&t.in>2000;
  set('rate',pct,n=>n+'%');
  tiles.rate.b.classList.toggle('err',low);
  const m=tiles.rate.t.querySelector('.meter i');m.style.width=(pct||0)+'%';m.style.background=low?'var(--bad)':'';
  const d=tiles.dur.b;d.classList.add('tm');d.dataset.t0=r.t0;d.dataset.run=r.state==='running'?'1':'0';d.textContent=fmtDur(elapsed(r))}
function syncDetail(){
  const r=data.runs.find(x=>x.id===sel);
  if(!r)return;
  if(D.id!==r.id)buildDetail(r);
  updateDetail(r)}

function evNode(e,t0,animate,ev){
  const ts=h('span',{class:'ts'},e.t?'+'+fmtDur(e.t-t0):'');
  const ph=h('span',{class:'tag'},PH_TXT[e.phase]||e.phase);
  let node;
  if(e.kind==='round'){
    const c=e.call,pct=c.in?Math.round(c.hit/c.in*100):0,prev=ev.last[e.conv];ev.last[e.conv]=c.in;
    const grow=prev!=null&&c.in>prev*1.5&&c.in>3000,dl=prev==null?null:c.in-prev;
    node=h('div',{class:'ev round'},h('div',{class:'h'},ts,ph,h('b',null,'第 '+e.turn+' 輪'),h('span',null,'輸入 '+fmtTok(c.in)),
      dl==null?null:h('span',{class:grow?'err':''},'（比上輪 '+(dl>=0?'+':'−')+fmtTok(Math.abs(dl))+(grow?'，明顯變大':'')+'）'),
      h('span',{class:pct<50&&c.in>2000?'err':''},'快取命中 '+pct+'%'),
      h('span',null,'輸出 '+fmtTok(c.out)+(c.think?'（含思考 '+fmtTok(c.think)+'）':''))))}
  else if(e.kind==='tool'){
    const bad=String(e.result).startsWith('ERROR');
    const a=e.args||{},k=a.path||a.file_path||a.file||a.pattern||a.command||a.cmd||a.url||a.description,j=JSON.stringify(a);
    node=h('div',{class:'ev'},h('div',{class:'h'},ts,ph,h('span',{class:'tool'},e.tool),h('span',{class:'arg'},k?clip(k,160):j==='{}'?'':clip(j,160))),
      e.result?h('details',null,h('summary',{class:bad?'err':''},clip(String(e.result).replace(/\s+/g,' '),120)),h('pre',null,String(e.result))):null)}
  else{
    const d=e.data||{};let txt='';
    if(e.event==='verify')txt='驗收 exit='+d.exit;
    else if(e.event==='escalate_to_pro')txt='Flash 修不好 → 改由 Pro 接手（第 '+d.turn+' 輪）';
    else if(e.event==='retry')txt='API 重試第 '+d.attempt+' 次';
    else if(e.event==='truncated')txt='輸出被截斷（第 '+d.turn+' 輪）';
    else if(e.event==='start')txt='開始　'+(d.mode||'')+'　模型 '+(d.model||'');
    else if(e.event==='end')txt=(d.ok?'完成 通過':'結束 失敗')+'　狀態 '+d.status+'　入 '+fmtTok(d.tokens&&d.tokens.in)+' / 出 '+fmtTok(d.tokens&&d.tokens.out)+(d.min!=null?'　'+d.min+' 分':'');
    else if(e.event==='spec')txt='規格完成：'+(d.rules??'?')+' 條規則（'+d.status+'）';
    else if(e.event==='review')txt='審查：'+((d.problems||[]).length)+' 個問題、'+((d.escalate||[]).length)+' 個升級（'+d.status+'）';
    else if(e.event==='probe')txt='探測：'+((d.issues||[]).length)+' 項違反（'+d.status+'）';
    else txt=e.event;
    const bad=(e.event==='verify'&&d.exit!==0)||e.event==='truncated'||(e.event==='end'&&!d.ok);
    const ok=(e.event==='verify'&&d.exit===0)||(e.event==='end'&&d.ok);
    const extra=e.event==='verify'&&d.tail?h('pre',null,d.tail):(e.event==='end'&&(d.files||[]).length?h('pre',null,d.files.join('\n')+(d.commit_msg?'\n\n提交訊息：'+d.commit_msg:'')):
      (['review','probe'].includes(e.event)&&((d.problems||d.issues||[]).length)?h('pre',null,(d.problems||d.issues).join('\n')):null));
    node=h('div',{class:'ev note'},h('div',{class:'h'},ts,ph,h('b',{class:bad?'err':'',style:ok?'color:var(--ok)':null},txt)),extra)}
  return animate?enter(node):node}
async function pollDetail(){
  const r=data.runs.find(x=>x.id===sel),my=D;
  if(!r||!my.id||my.id!==r.id)return;
  if(tab==='events'){
    const j=await (await fetch('/api/run?id='+encodeURIComponent(r.id)+'&since='+my.ev.next)).json();
    if(D!==my||tab!=='events')return;
    const ev=my.ev,box=$('#detail'),wasFirst=ev.first;
    if(!ev.el){ev.el=h('div');ev.live=h('div',{class:'live'},h('i'),h('i'),h('i'));my.body.replaceChildren(ev.el,ev.live)}
    const near=box.scrollHeight-box.scrollTop-box.clientHeight<160;
    j.events.forEach(e=>ev.el.append(evNode(e,r.t0,!wasFirst,ev)));
    ev.next=j.total;ev.first=false;
    ev.live.style.display=r.state==='running'?'':'none';
    if(!wasFirst&&j.events.length&&near)requestAnimationFrame(()=>box.scrollTo({top:box.scrollHeight,behavior:'smooth'}))}
  else if(tab==='diag'){await renderDiag(my,r)}
  else{
    const j=await (await fetch('/api/doc?id='+encodeURIComponent(r.id)+'&kind='+tab)).json();
    if(D!==my||tab==='events')return;
    const text=j.text||(tab==='report'?'報告在派工結束後才會出現':tab==='spec'?'這個派工沒有規格階段':'（空）');
    if(my.doc!==text){my.doc=text;my.body.replaceChildren(enter(h('pre',{class:'doc'},text)))}}}
const exactTok=n=>n.toLocaleString('zh-TW');
const sumUsage=(rs,k)=>!rs.length?0:rs.some(r=>r.tokens)?rs.reduce((a,r)=>a+(r.tokens?r.tokens[k]||0:0),0):null;
function usageSummary(runs,date=new Date()){
  const day=new Date(date);day.setHours(0,0,0,0);
  const next=new Date(day);next.setDate(next.getDate()+1);
  const today=runs.filter(r=>r.t0>=day/1000&&r.t0<next/1000),measured=today.filter(r=>r.tokens);
  const input=sumUsage(today,'in'),output=sumUsage(today,'out'),hit=sumUsage(today,'hit');
  const ended=today.filter(r=>['done','failed','interrupted'].includes(r.state)),done=ended.filter(r=>r.state==='done');
  const timed=done.filter(r=>Number.isFinite(r.t1)&&r.t1>=r.t0);
  const days=Array.from({length:7},(_,i)=>{
    const start=new Date(day);start.setDate(start.getDate()+i-6);
    const end=new Date(start);end.setDate(end.getDate()+1);
    const rs=runs.filter(r=>r.t0>=start/1000&&r.t0<end/1000);
    return{date:start,runs:rs.length,measured:rs.filter(r=>r.tokens).length,input:sumUsage(rs,'in'),output:sumUsage(rs,'out')}});
  return{day,today,measured,input,output,hit,ended,done,days,
    cache:input>0?hit/input*100:null,
    average:measured.length?(input+output)/measured.length:null,
    success:ended.length?done.length/ended.length*100:null,
    duration:timed.length?timed.reduce((a,r)=>a+r.t1-r.t0,0)/timed.length:null,
    ranking:[...measured].sort((a,b)=>(b.tokens.in+b.tokens.out)-(a.tokens.in+a.tokens.out)).slice(0,3)};
}
const trendNodes=[],rankNodes=new Map();
function updateAnalysis(s){
  if(!trendNodes.length){
    s.days.forEach((_,i)=>{
      const input=h('i'),output=h('i',{class:'out'}),value=h('div',{class:'day-total'}),label=h('span');
      const root=h('div',{class:'day'+(i===6?' today':''),role:'img'},value,h('div',{class:'bars','aria-hidden':'true'},input,output),label);
      trendNodes.push({root,input,output,value,label});$('#usage-trend').append(root)});
  }
  const max=Math.max(1,...s.days.flatMap(d=>[d.input||0,d.output||0]));
  s.days.forEach((d,i)=>{
    const n=trendNodes[i],label=(d.date.getMonth()+1)+'/'+d.date.getDate();
    n.label.textContent=i===6?'今日':label;
    n.value.textContent=d.input==null?'—':fmtTok(d.input+d.output);
    n.input.style.height=((d.input||0)/max*100)+'%';n.output.style.height=((d.output||0)/max*100)+'%';
    const text=label+' · Input '+(d.input==null?'無用量紀錄':exactTok(d.input))+' / Output '+(d.output==null?'無用量紀錄':exactTok(d.output))+' · '+d.measured+'/'+d.runs+' 筆有用量';
    n.root.title=text;n.root.setAttribute('aria-label',text)});
  const top=s.ranking.length?s.ranking[0].tokens.in+s.ranking[0].tokens.out:0;
  const rows=s.ranking.map((r,i)=>{
    let n=rankNodes.get(r.id);
    if(!n){const button=h('button',{onclick:()=>select(r.id)}),value=h('b'),bar=h('i');
      const root=enter(h('div',{class:'rank-row'},button,value,h('span',{class:'meter'},bar)));
      root.style.transition='opacity .5s,transform .5s var(--ease)';n={root,button,value,bar};rankNodes.set(r.id,n)}
    const total=r.tokens.in+r.tokens.out;
    n.button.textContent=(i+1)+'. '+(isCC(r)?'Claude':'DeepSeek')+' · '+r.title;
    n.button.title=r.title+' · 查看任務詳情';n.value.replaceChildren(levelTag(r),fmtTok(total));n.value.title=exactTok(total)+' tokens';
    n.bar.style.width=(top?total/top*100:0)+'%';return n.root});
  for(const id of rankNodes.keys())if(!s.ranking.some(r=>r.id===id))rankNodes.delete(id);
  place($('#usage-ranking'),rows.length?rows:[miscNode('usage-empty',()=>h('div',{class:'scope'},'今日尚無可分析的用量紀錄'))]);
}
function updateStats(){
  const s=usageSummary(data.runs),today=s.today,run=data.runs.filter(r=>r.state==='running').length;
  const ds=today.filter(r=>!isCC(r)),cc=today.filter(isCC);
  const sum=sumUsage;
  tween($('#s-run'),run,String);tween($('#s-n'),today.length,String);
  tween($('#ds-in'),sum(ds,'in'));tween($('#ds-hit'),sum(ds,'hit'));tween($('#ds-out'),sum(ds,'out'));
  tween($('#cc-in'),sum(cc,'in'));tween($('#cc-hit'),sum(cc,'hit'));tween($('#cc-out'),sum(cc,'out'));
  tween($('#today-in'),s.input,exactTok);tween($('#today-out'),s.output,exactTok);
  tween($('#today-cache'),s.cache,n=>Math.round(n)+'%');tween($('#today-average'),s.average,n=>fmtTok(Math.round(n)));
  tween($('#today-success'),s.success,n=>Math.round(n)+'%');tween($('#today-duration'),s.duration,fmtDur);
  $('#usage-date').textContent=s.day.toLocaleDateString('zh-TW',{month:'long',day:'numeric'});
  $('#usage-scope').textContent='今日啟動任務的累計用量 · 瀏覽器當地日期 · 最近 '+data.runs.length+' 筆紀錄（最多 40）';
  $('#usage-coverage').textContent=s.measured.length+'/'+today.length+' 筆任務有用量'+(s.measured.length<today.length?'，統計未涵蓋全部任務':'');
  $('#cache-note').textContent=s.input>0?'命中 '+fmtTok(s.hit)+' / 輸入 '+fmtTok(s.input):'尚無可計算的輸入';
  $('#success-note').textContent=s.done.length+'/'+s.ended.length+' 筆已結束 · 含失敗與中斷';
  updateAnalysis(s);
  $('#pulse').classList.toggle('on',run>0);
  document.title=(run?'('+run+') ':'')+'DS 派工儀表板'}
const SEV_TXT={high:'高',warn:'注意',info:'提示'};
const SEV_KEYS=['high','warn','info'];
const cardSev=s=>SEV_KEYS.includes(s)?s:'info';
function findCard(f){
  const sev=cardSev(f.severity);
  return h('div',{class:'fcard','data-sev':sev},h('span',{class:'sev'}),
    h('div',{class:'ft'},f.title||'',h('span',{class:'sevtag','data-sev':sev},SEV_TXT[sev])),
    f.detail?h('div',{class:'fd'},f.detail):null,
    f.hint?h('div',{class:'fh'},'建議：'+f.hint):null)}
async function renderDiag(my,r){
  const j=await (await fetch('/api/analyze?id='+encodeURIComponent(r.id))).json();
  if(D!==my||tab!=='diag')return;
  const fs=j.findings||[],sig=JSON.stringify(fs);
  if(my.dsig===sig)return;
  my.dsig=sig;
  if(!fs.length){my.body.replaceChildren(enter(h('div',{class:'diag-empty'},h('span',{class:'ok'},'✓'),h('span',null,'沒有發現用量問題'))));return}
  my.body.replaceChildren(...fs.map((f,i)=>{
    const c=findCard(f);
    c.style.transitionDelay=(i*70)+'ms';
    setTimeout(()=>{c.style.transitionDelay=''},1000+i*70);
    return enter(c)}))}
function pbar(value,max){const i=h('i');i.style.width=(max>0?Math.min(100,value/max*100):0)+'%';return h('span',{class:'meter'},i)}
function barRow(name,value,bar,onclick){
  return h('div',{class:'rank-row'+(onclick?' click':''),onclick:onclick||null},h('span',null,name),h('b',null,value),bar)}
function buildPanel(){
  const close=h('button',{class:'x',onclick:()=>closePanel(),'aria-label':'關閉'},'×');
  const today=h('div'),top=h('div'),groups=h('div'),issues=h('div'),session=h('div');
  const root=h('aside',{class:'sheet',role:'dialog','aria-label':'用量診斷'},
    h('div',{class:'shead'},h('h2',null,'用量診斷'),close),
    h('h3',null,'今日總覽'),today,h('h3',null,'用量最高的任務'),top,
    h('h3',null,'各專案用量'),groups,h('h3',null,'常見問題'),issues,
    h('h3',null,'目前對話'),session);
  return{root,today,top,groups,issues,session}}
const panel=buildPanel();
const scrim=h('div',{class:'scrim',onclick:()=>closePanel()});
document.body.append(scrim,panel.root);
let panelOn=false;
function openPanel(){panelOn=true;scrim.classList.add('on');panel.root.classList.add('on');fillOverview();fillSession()}
function closePanel(){panelOn=false;scrim.classList.remove('on');panel.root.classList.remove('on')}
function issueRow(x){
  const sev=cardSev(x.severity);
  return h('button',{class:'irow',onclick:()=>{const id=(x.run_ids||[])[0];if(id)select(id);setTab('diag');closePanel()}},
    h('span',null,x.title||x.id),h('span',{class:'sevtag','data-sev':sev},SEV_TXT[sev]),h('b',null,x.count+' 次'))}
async function fillOverview(){
  let j={};
  try{j=await (await fetch('/api/analyze/overview')).json()}catch(e){}
  if(!panelOn)return;
  const t=j.totals||{},ds=t.ds||{},cc=t.claude||{};
  const row=(n,o)=>h('div',{class:'prow'},h('span',null,n),h('b',null,'入 '+fmtTok(o.in)+'　命中 '+fmtTok(o.hit)+'　出 '+fmtTok(o.out)));
  panel.today.replaceChildren(row('DeepSeek',ds),row('Claude',cc));
  const tops=j.top||[],smax=Math.max(0.001,...tops.map(x=>x.share||0));
  panel.top.replaceChildren(...(tops.length?tops.map(x=>barRow((x.source==='claude'?'Claude':'DeepSeek')+' · '+(x.title||x.id),
    fmtTok(x.in)+'　'+Math.round((x.share||0)*1000)/10+'%',pbar(x.share||0,smax),
    ()=>{select(x.id);closePanel()})):[h('div',{class:'scope'},'尚無用量紀錄')]));
  const gs=j.groups||[],gmax=Math.max(1,...gs.map(g=>g.in||0));
  panel.groups.replaceChildren(...(gs.length?gs.map(g=>barRow((g.label||g.key)+'（'+g.runs+' 個）',fmtTok(g.in),pbar(g.in,gmax))):[h('div',{class:'scope'},'尚無專案資料')]));
  const list=j.issues||[];
  panel.issues.replaceChildren(...(list.length?list.map(issueRow):[h('div',{class:'scope'},'目前沒有常見問題')]))}
async function fillSession(){
  panel.session.replaceChildren(h('div',{class:'scope'},'載入中…'));
  const r=data.runs.find(x=>x.id===sel);
  if(!r||!r.session){panel.session.replaceChildren(h('div',{class:'scope'},'選中的任務沒有對話紀錄'));return}
  let j={error:'讀不到對話紀錄'};
  try{j=await (await fetch('/api/analyze/session?id='+encodeURIComponent(r.session))).json()}catch(e){}
  if(!panelOn)return;
  if(j.error||j.turns==null){panel.session.replaceChildren(h('div',{class:'scope'},j.error||'讀不到對話紀錄'));return}
  const big=(j.big_results||[])[0];
  const grid=h('div',null,
    h('div',{class:'prow'},h('span',null,'輪數'),h('b',null,fmtTok(j.turns))),
    h('div',{class:'prow'},h('span',null,'尖峰上下文'),h('b',null,fmtTok(j.peak_context))),
    h('div',{class:'prow'},h('span',null,'累計處理量'),h('b',null,fmtTok(j.processed))),
    h('div',{class:'prow'},h('span',null,'截圖'),h('b',null,fmtTok(j.images))),
    h('div',{class:'prow'},h('span',null,'最大工具輸出'),h('b',null,big?fmtTok(big.chars)+' 字（'+big.tool+'）':'—')));
  const fs=j.findings||[];
  if(!fs.length){panel.session.replaceChildren(grid,h('div',{class:'diag-empty'},h('span',{class:'ok'},'✓'),h('span',null,'目前對話沒有用量問題')));return}
  panel.session.replaceChildren(grid,...fs.map(findCard))}
$('#diag-open').onclick=openPanel;
addEventListener('keydown',e=>{if(e.key==='Escape'&&panelOn)closePanel()});
async function poll(){
  if(busy)return;
  busy=true;
  try{
    data=await (await fetch('/api/runs')).json();
    $('#s-conn').textContent='';
    updateStats();
    if(!sel||!data.runs.some(r=>r.id===sel)){const r=data.runs.find(x=>x.state==='running')||data.runs[0];sel=r?r.id:null}
    renderList();syncDetail();await pollDetail()}
  catch(e){$('#s-conn').textContent='連不上儀表板伺服器'}
  busy=false}

addEventListener('resize',moveInk);
document.querySelectorAll('.usage-card').forEach(enter);
setInterval(()=>{document.querySelectorAll('.tm[data-run="1"]').forEach(e=>{e.textContent=fmtDur(now()-e.dataset.t0)})},1000);
poll();setInterval(poll,2000);
</script></body></html>
"""
