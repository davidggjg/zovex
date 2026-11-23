/* ZOVEX · טאב "🛡 אבטחה": אימות אפליקציות (מצב, דרישות, סודות, סשנים פעילים, חסימה). */
(function(){
  if (window.__zvTok) return; window.__zvTok = true;
  const tabs=document.querySelector(".tabs"); if(!tabs) return;
  const st=document.createElement("style"); st.textContent=`
  .zvt-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}
  .zvt-box{background:rgba(255,255,255,.55);border-radius:14px;padding:10px;text-align:center}
  .zvt-box b{display:block;font-size:20px}
  .zvt-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 4px;border-bottom:1px solid var(--hair,#eee);font-size:13px}
  .zvt-row code{direction:ltr;font-size:12px;overflow-wrap:anywhere}
  .zvt-sec{direction:ltr;font-family:ui-monospace,Menlo,monospace;font-size:12px;overflow-wrap:anywhere;background:rgba(0,0,0,.04);padding:6px 8px;border-radius:8px;flex:1 1 220px}
  .zvt-mode button.on{background:var(--ink,#18171c)!important;color:#fff!important}
  .zvt-bad{color:var(--red,#e2483d)} .zvt-ok{color:var(--green,#2fae6a)}`;
  document.head.appendChild(st);
  const tb=document.createElement("button"); tb.id="tab-tokens"; tb.textContent="🛡 אבטחה"; tabs.appendChild(tb);
  const pane=document.createElement("div"); pane.id="pane-tokens"; pane.className="hidden";
  document.querySelector('[id^="pane-"]').parentElement.appendChild(pane);
  const PL={web:"אתר",android:"אנדרואיד",pc:"מחשב"}, ATT={none:"ללא",app:"סוד אפליקציה",turnstile:"Turnstile",integrity:"Play Integrity"};
  async function call(extra){
    const r=await fetch("/admin/tokens",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:PASS,...(extra||{})})});
    const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.detail||("שגיאה "+r.status)); return d;
  }
  const ago=t=>{ if(!t) return "—"; const s=Math.round(Date.now()/1000-t); return s<60?`${s}ש׳`:s<3600?`${Math.round(s/60)}ד׳`:`${Math.round(s/3600)}ש`; };
  async function render(extra){
    pane.innerHTML='<div class="card">טוען…</div>';
    let d; try{ d=await call(extra); }catch(e){ pane.innerHTML=`<div class="card"><span class="err">${esc(e.message)}</span></div>`; return; }
    const c=d.cfg, s=d.stats;
    const sel=p=>`<select data-req="${p}">${(p==="web"?["none","turnstile"]:p==="android"?["none","app","integrity"]:["none","app"]).map(v=>`<option value="${v}" ${c.require[p]===v?"selected":""}>${ATT[v]}</option>`).join("")}</select>`;
    pane.innerHTML=`
    <div class="card"><h2>🛡 אימות אפליקציות</h2>
      <div class="muted">רק האתר והאפליקציות שלך מקבלים גישה לקטלוג, לתמיכה ולהיסטוריה. כל בקשה נחתמת במפתח שנשמר במכשיר ופג אחרי 24 שעות.</div>
      <div class="zvt-mode row" style="margin-top:10px;gap:6px">
        <button class="mini ${c.mode==="off"?"on":"gray"}" data-mode="off">כבוי</button>
        <button class="mini ${c.mode==="monitor"?"on":"gray"}" data-mode="monitor">👁 מעקב בלבד</button>
        <button class="mini ${c.mode==="enforce"?"on":"gray"}" data-mode="enforce">🔒 אכיפה</button></div>
      <div class="muted" style="margin-top:6px">${c.mode==="enforce"?'<b class="zvt-bad">אכיפה פעילה:</b> בקשה לא חתומה נדחית.':c.mode==="monitor"?"מעקב: הכל עובר, רק נרשם. הפעל אכיפה רק כשרוב הבקשות ✓.":"כבוי לגמרי."}</div>
      <div class="zvt-grid">
        <div class="zvt-box"><b class="zvt-ok">${s.ok||0}</b>חתומות ✓</div>
        <div class="zvt-box"><b class="zvt-bad">${s.no_token||0}</b>בלי טוקן</div>
        <div class="zvt-box"><b class="zvt-bad">${(s.bad_sig||0)+(s.replay||0)}</b>חתימה מזויפת/משוכפלת</div>
        <div class="zvt-box"><b>${s.expired||0}</b>פג תוקף</div>
        <div class="zvt-box"><b class="zvt-bad">${d.blocked}</b>סשנים חסומים</div>
        <div class="zvt-box"><b>${d.active}</b>סשנים פעילים</div></div>
      <div class="muted">מאז ${new Date(s.since*1000).toLocaleString("he-IL")} · ${Object.entries(d.by).map(([k,v])=>{const[p,a]=k.split("/");return `${PL[p]||p}/${ATT[a]||a}: ${v}`}).join(" · ")||"אין"}</div>
    </div>
    <div class="card"><h2>דרישת אימות לכל פלטפורמה</h2>
      <div class="row" style="gap:10px;flex-wrap:wrap"><label>אתר ${sel("web")}</label><label>אנדרואיד ${sel("android")}</label><label>מחשב ${sel("pc")}</label></div>
      <div class="muted">${c.turnstile_secret_set?'<span class="zvt-ok">✓ Turnstile מוגדר</span>':'<span class="zvt-bad">Turnstile לא מוגדר</span> (האתר עובד בלי בדיקת רובוט)'} · ${c.play_ready?'<span class="zvt-ok">✓ Play Integrity מוגדר</span>':'<span class="zvt-bad">Play Integrity לא מוגדר</span> (אנדרואיד נבדק בסוד אפליקציה)'}</div>
      <div style="margin-top:10px"><label>Turnstile site key</label><input id="zvtSk" value="${esc(c.turnstile_sitekey||"")}" style="direction:ltr">
      <label>Turnstile secret key ${c.turnstile_secret_set?"(מוגדר — השאר ריק כדי לא לשנות)":""}</label><input id="zvtSs" type="password" style="direction:ltr">
      <label>שם חבילת אנדרואיד (Play Integrity)</label><input id="zvtPkg" value="${esc(c.android_package||"")}" placeholder="com.example.app" style="direction:ltr">
      <button class="mini" id="zvtSave" style="margin-top:8px">שמור הגדרות</button></div>
    </div>
    <div class="card"><h2>🔑 סודות אפליקציה</h2>
      <div class="muted">את הסוד מכניסים לבנייה של האפליקציה. החלפה מנתקת מיד כל גרסה עם הסוד הישן — עשה זאת רק כשגרסה חדשה כבר בחוץ, או כשהסוד דלף.</div>
      ${["android","pc"].map(p=>`<div class="zvt-row"><b style="min-width:70px">${PL[p]}</b><span class="zvt-sec">${esc(c.app_secrets[p]||"")}</span>
        <button class="mini gray" data-copy="${esc(c.app_secrets[p]||"")}">העתק</button><button class="mini" style="background:#b4532a" data-rot="${p}">החלף</button></div>`).join("")}
    </div>
    <div class="card"><h2>סשנים פעילים (${d.active})</h2>
      <div class="muted">חסומים קודם, אחר כך הכי פעילים. חסימה אוטומטית: מעל ${d.rules.catalog} משיכות קטלוג או ${d.rules.fb_send} הודעות תמיכה לשעה.</div>
      ${d.rows.map(r=>`<div class="zvt-row"><span class="pill">${PL[r.plat]||r.plat}</span><span class="pill">${ATT[r.att]||r.att}${r.weak?" ⚠":""}</span>
        <code>${esc(r.ip||"")}</code><span>${r.n} בקשות · לפני ${ago(r.last)}</span>
        ${r.blocked?`<span class="zvt-bad">⛔ ${esc(r.blocked)}</span><button class="mini gray" data-unb="${esc(r.sid)}" style="margin-inline-start:auto">שחרר</button>`
                   :`<button class="mini gray" data-blk="${esc(r.sid)}" style="margin-inline-start:auto">חסום</button>`}
        <div class="muted" style="flex-basis:100%;font-size:11px;overflow-wrap:anywhere">${esc(r.ua||"")}</div></div>`).join("")||'<div class="muted">אין</div>'}
    </div>`;
    pane.querySelectorAll("[data-mode]").forEach(b=>b.onclick=()=>{ const m=b.dataset.mode;
      if(m==="enforce"&&!confirm("להפעיל אכיפה? אפליקציות שעוד לא עודכנו יפסיקו לקבל תוכן.")) return; render({mode:m}); });
    pane.querySelectorAll("[data-req]").forEach(x=>x.onchange=()=>render({require:{[x.dataset.req]:x.value}}));
    pane.querySelectorAll("[data-rot]").forEach(b=>b.onclick=()=>{ if(confirm(`להחליף את הסוד של ${PL[b.dataset.rot]}? גרסאות עם הסוד הישן יאבדו גישה (במצב אכיפה).`)) render({rotate:b.dataset.rot}); });
    pane.querySelectorAll("[data-copy]").forEach(b=>b.onclick=()=>{ navigator.clipboard&&navigator.clipboard.writeText(b.dataset.copy); b.textContent="✓ הועתק"; });
    pane.querySelectorAll("[data-blk]").forEach(b=>b.onclick=()=>render({sid:b.dataset.blk}));
    pane.querySelectorAll("[data-unb]").forEach(b=>b.onclick=()=>render({sid:b.dataset.unb,unblock:true}));
    pane.querySelector("#zvtSave").onclick=()=>{ const x={turnstile_sitekey:pane.querySelector("#zvtSk").value, android_package:pane.querySelector("#zvtPkg").value};
      const ss=pane.querySelector("#zvtSs").value; if(ss) x.turnstile_secret=ss; render(x); };
  }
  const origShow=window.showTab;
  window.showTab=function(n){
    pane.classList.add("hidden"); tb.classList.remove("active");
    if (n!=="tokens") return origShow.apply(this,arguments);
    document.querySelectorAll('[id^="pane-"]').forEach(p=>p.classList.add("hidden"));
    document.querySelectorAll(".tabs button").forEach(b=>b.classList.remove("active"));
    pane.classList.remove("hidden"); tb.classList.add("active"); render();
  };
  tb.onclick=()=>showTab("tokens");
})();
