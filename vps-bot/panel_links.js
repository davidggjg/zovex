/* ZOVEX · טאב "קישורים": סדרות/סרטים/ערוצים עם כתובת חסרה או לא תקינה.
   סדרה = שורה אחת, כתובת אחת לכל הפרקים. כלל: a-z, 0-9, מקף (Google: מקפים, לא קו תחתון). */
(function(){
  if (window.__zvLinks) return; window.__zvLinks = true;
  // טעינת תוכן עמידה: 3 ניסיונות עם timeout; תשובה שגויה לא מוחקת את הרשימה הקיימת
  window.loadContent = async function(){
    let lastErr=null;
    for (let a=0;a<3;a++){
      try{
        const ctl=new AbortController(), to=setTimeout(()=>ctl.abort(),25000);
        const r=await fetch("/content?t="+Date.now(),{signal:ctl.signal,cache:"no-store"}); clearTimeout(to);
        if(!r.ok) throw new Error("שגיאה "+r.status);
        const d=await r.json(); if(!Array.isArray(d)) throw new Error("תשובה לא תקינה");
        contentVersion=r.headers.get("X-Content-Version"); movies=d; refreshDerived(); return;
      }catch(e){ lastErr=e; await new Promise(res=>setTimeout(res,800*(a+1))); }
    }
    if(!Array.isArray(movies)||!movies.length) alert("טעינת תוכן נכשלה: "+(lastErr&&lastErr.message||"")+" — נסה שוב");
  };
  const RESERVED = new Set(["search","live","admin","panel","stream","watch","api","content","cast","fs","vh","vt",
    "hls-relay","zovex","sitemap","robots","assets","vendor","uploads","feedback","speedtest","ping","media-auth","debug","index"]);
  const HE = {"א":"a","ב":"b","ג":"g","ד":"d","ה":"h","ו":"v","ז":"z","ח":"ch","ט":"t","י":"y","כ":"k","ך":"k","ל":"l","מ":"m","ם":"m",
    "נ":"n","ן":"n","ס":"s","ע":"a","פ":"p","ף":"f","צ":"tz","ץ":"tz","ק":"k","ר":"r","ש":"sh","ת":"t"};

  // נרמול: אותיות קטנות; רווח/מקף ארוך/קו תחתון/נקודתיים/נקודה/לוכסן → מקף
  function normSlug(v){ return String(v||"").toLowerCase().trim().replace(/[\s–—_:.,/\\|+]+/g,"-").replace(/-+/g,"-").replace(/^-|-$/g,""); }
  function suggest(name, en){
    let base = en && /[a-z]/i.test(en) ? en : [...String(name||"")].map(c=>HE[c]??c).join("");
    base = normSlug(base.replace(/['"`׳״?!()[\]{}&#@%*=;,]/g," ")).replace(/[^a-z0-9-]/g,"").replace(/-+/g,"-").replace(/^-|-$/g,"");
    return base.slice(0,60).replace(/-$/,"") || "item";
  }
  function validate(v, ownKey, taken, live){
    if (!v) return "חסרה כתובת";
    const bad=[...new Set(v.replace(/[a-z0-9-]/g,""))];
    if (bad.length) return `לא ניתן להשתמש ב: ${bad.map(c=>c===" "?"רווח":c).join(" ")} — החלף באות באנגלית, מספר או מקף`;
    if (v.length<2) return "קצר מדי (לפחות 2 תווים)";
    if (v.length>60) return "ארוך מדי (עד 60 תווים)";
    if (/^-|-$|--/.test(v)) return "מקף לא יכול להיות בהתחלה, בסוף, או פעמיים ברצף";
    if (!live && RESERVED.has(v)) return `"${v}" שמורה לאתר עצמו — בחר שם אחר`;
    const owner=taken.get(v); if (owner && owner.key!==ownKey) return {taken:owner.name};
    return "";
  }
  function freeSlug(v, ownKey, taken){ for(let i=2;i<200;i++){ const c=`${v}-${i}`; const o=taken.get(c); if(!o||o.key===ownKey) return c; } return v+"-"+Date.now()%1000; }

  function entities(){
    const out=[], series={};
    for (const m of movies){
      if (m.series_name){ (series[m.series_name] ||= []).push(m); continue; }
      const live = m.category==="שידורים חיים" || m.is_live;
      out.push({key:(live?"l:":"m:")+m.id, kind:live?"live":"movie", name:m.title||"—", slug:m.custom_slug||"",
        en:m.en_title||"", poster:m.thumbnail_url||"", ids:[m.id]});
    }
    for (const [sn,eps] of Object.entries(series)){
      const f=eps.find(e=>e.custom_slug)||eps.find(e=>e.thumbnail_url)||eps[0];
      const slugs=[...new Set(eps.map(e=>e.custom_slug||""))];
      out.push({key:"s:"+sn, kind:"series", name:sn, slug:f.custom_slug||"", mixed:slugs.length>1,
        en:(eps.find(e=>e.en_title)||{}).en_title||"", poster:(eps.find(e=>e.thumbnail_url)||{}).thumbnail_url||"", ids:eps.map(e=>e.id), count:eps.length});
    }
    return out;
  }
  // בעלים של כתובת: סדרה קודמת לסרט (באתר הניתוב בודק סדרה ראשונה, כך שסרט באותה כתובת
  // לא נגיש), ובאותו סוג — הראשון ברשימה.
  function takenMap(list, live){ const t=new Map();
    for(const e of list){ if((e.kind==="live")!==live) continue; const s=normSlug(e.slug); if(!s) continue;
      const cur=t.get(s); if(!cur || (cur.kind!=="series" && e.kind==="series")) t.set(s,e); }
    return t; }
  function isBad(e, list, maps){
    const live=e.kind==="live", s=e.slug;
    if (!s || e.mixed) return true;
    if (s!==normSlug(s) || /[^a-z0-9-]/.test(s)) return true;
    const owner=(maps?maps[live?1:0]:takenMap(list, live)).get(s);
    if (owner && owner.key!==e.key) return true;          // כפילות — רק מי שאינו הבעלים
    return !!validate(s, e.key, new Map(), live);
  }

  const st=document.createElement("style"); st.textContent=`
  .zvl-row{display:flex;gap:12px;align-items:flex-start;padding:12px 6px;border-bottom:1px solid var(--hair,#eee);flex-wrap:wrap}
  .zvl-row img,.zvl-row .ph{width:44px;height:64px;border-radius:9px;object-fit:cover;background:rgba(60,45,80,.08);flex:none}
  .zvl-main{flex:1 1 240px;min-width:0}
  .zvl-name{font-weight:650;font-size:14.5px;overflow-wrap:anywhere}
  .zvl-cur{font-size:12px;color:var(--text-2,#666);direction:ltr;text-align:right;overflow-wrap:anywhere}
  .zvl-edit{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:6px}
  .zvl-edit input{flex:1 1 200px;margin:0;direction:ltr;text-align:left;font-family:ui-monospace,Menlo,monospace}
  .zvl-msg{font-size:12.5px;margin-top:4px;min-height:16px;overflow-wrap:anywhere}
  .zvl-msg.bad{color:var(--red,#e2483d)} .zvl-msg.ok{color:var(--green,#2fae6a)}
  .zvl-prev{font-size:12px;color:var(--text-2,#666);direction:ltr;text-align:right;overflow-wrap:anywhere}
  .zvl-chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
  .zvl-chips button.on{background:var(--ink,#18171c)!important;color:#fff!important}
  .zvl-row{cursor:pointer} .zvl-row .zvl-body{display:none} .zvl-row.open .zvl-body{display:block}
  .zvl-row.open{background:rgba(255,255,255,.5);border-radius:16px;cursor:default}
  .zvl-chev{margin-inline-start:auto;color:var(--text-2,#666);font-size:13px;flex:none}
  .zvl-row.open .zvl-chev{transform:rotate(180deg)}
  .zvl-ok{color:var(--green,#2fae6a)} .zvl-warn{color:var(--red,#e2483d)}`;
  document.head.appendChild(st);

  // ── טאב + חלונית
  const tabs=document.querySelector(".tabs"); if(!tabs) return;
  const tb=document.createElement("button"); tb.id="tab-links"; tb.textContent="🔗 קישורים"; tabs.appendChild(tb);
  const pane=document.createElement("div"); pane.id="pane-links"; pane.className="hidden";
  pane.innerHTML=`<div class="card"><div class="toprow"><h2>קישורים לא תקינים <span id="zvlCount" class="pill"></span></h2></div>
    <div class="muted">כתובת = אותיות באנגלית קטנות, ספרות ומקפים בלבד (לפי Google: מקפים, לא קו תחתון). לסדרה — כתובת אחת לכל הפרקים.
    דוגמה: <code>zovex.duckdns.org/rings-of-power</code></div>
    <div class="zvl-chips"><button class="mini gray on" data-f="all">הכל</button><button class="mini gray" data-f="series">סדרות</button>
      <button class="mini gray" data-f="movie">סרטים</button><button class="mini gray" data-f="live">ערוצים</button>
      <span style="flex:1"></span><button class="mini gray on" data-s="bad">רק בעייתיים</button><button class="mini gray" data-s="all">הכל</button></div>
    <input id="zvlQ" placeholder="חיפוש לפי שם…"><div id="zvlList"></div></div>`;
  const anyPane=document.querySelector('[id^="pane-"]'); anyPane.parentElement.appendChild(pane);
  let filter="all", scope="bad";
  pane.querySelectorAll(".zvl-chips button[data-f]").forEach(b=>b.onclick=()=>{ filter=b.dataset.f;
    pane.querySelectorAll(".zvl-chips button[data-f]").forEach(x=>x.classList.toggle("on",x===b)); render(); });
  pane.querySelectorAll(".zvl-chips button[data-s]").forEach(b=>b.onclick=()=>{ scope=b.dataset.s;
    pane.querySelectorAll(".zvl-chips button[data-s]").forEach(x=>x.classList.toggle("on",x===b)); render(); });
  let qT=0; pane.querySelector("#zvlQ").oninput=()=>{ clearTimeout(qT); qT=setTimeout(render,250); };

  function render(){ try{ render0(); }catch(err){ console.error(err);
    const el=document.getElementById("zvlList"); if(el) el.innerHTML='<div class="err" style="padding:14px">שגיאה בטאב הקישורים: '+esc(err.message)+'</div>'; } }
  function render0(){
    const list=entities(), q=(document.getElementById("zvlQ").value||"").trim().toLowerCase();
    const maps=[takenMap(list,false), takenMap(list,true)];
    const badSet=new Set(list.filter(e=>isBad(e,list,maps)).map(e=>e.key));
    document.getElementById("zvlCount").textContent=badSet.size;
    let bad=(scope==="bad"?list.filter(e=>badSet.has(e.key)):list.slice().sort((a,b)=>a.name.localeCompare(b.name,"he")))
      .filter(e=>(filter==="all"||e.kind===filter)&&(!q||e.name.toLowerCase().includes(q)||(e.slug||"").includes(q)));
    const KIND={series:"סדרה",movie:"סרט",live:"ערוץ חי"};
    const el=document.getElementById("zvlList");
    el.innerHTML=bad.slice(0,150).map((e,i)=>`<div class="zvl-row" data-k="${esc(e.key)}">
      ${e.poster?`<img src="${esc(e.poster)}" alt="" loading="lazy">`:'<div class="ph"></div>'}
      <div class="zvl-main"><div class="zvl-name">${esc(e.name)} <span class="pill">${KIND[e.kind]}${e.count?` · ${e.count} פרקים`:""}</span></div>
        <div class="zvl-cur">${e.slug?((badSet.has(e.key)?'<span class="zvl-warn">⚠ </span>':'<span class="zvl-ok">✓ </span>')+"/"+esc(e.slug)+(e.mixed?" (שונה בין הפרקים)":"")):'<span class="zvl-warn">⚠ אין כתובת</span>'}</div>
        <div class="zvl-body"><div class="zvl-edit"><input value="${esc(normSlug(e.slug)&&!/[^a-z0-9-]/.test(normSlug(e.slug))?normSlug(e.slug):suggest(e.name,e.en))}" spellcheck="false" autocapitalize="off">
          <button class="mini zvl-save">שמור</button>${e.slug?'<button class="mini gray zvl-del" title="מחק כתובת">🗑 מחק כתובת</button>':""}</div>
        <div class="zvl-prev"></div><div class="zvl-msg"></div></div></div><span class="zvl-chev">▾</span></div>`).join("")
      || '<div class="muted" style="padding:14px">✨ כל הקישורים תקינים</div>';
    if (bad.length>150) el.insertAdjacentHTML("beforeend",`<div class="muted" style="padding:8px">מוצגים 150 מתוך ${bad.length} — צמצם בחיפוש</div>`);
    el.querySelectorAll(".zvl-row").forEach(row=>{
      const e=list.find(x=>x.key===row.dataset.k), live=e.kind==="live";
      const inp=row.querySelector("input"), msg=row.querySelector(".zvl-msg"), prev=row.querySelector(".zvl-prev"), btn=row.querySelector(".zvl-save");
      const check=()=>{
        const raw=inp.value, v=normSlug(raw), t=maps[live?1:0];
        const r=validate(v,e.key,t,live);
        prev.textContent = v ? `https://zovex.duckdns.org/${live?"live/":""}${v}` : "";
        if (r && r.taken){ const alt=freeSlug(v,e.key,t);
          msg.className="zvl-msg bad"; msg.innerHTML=`הכתובת תפוסה ע״י «${esc(r.taken)}» · <button class="mini sec zvl-alt" type="button">השתמש ב-${esc(alt)}</button>`;
          msg.querySelector(".zvl-alt").onclick=ev=>{ ev.stopPropagation(); inp.value=alt; check(); }; btn.disabled=true; return null; }
        if (r){ msg.className="zvl-msg bad"; msg.textContent=r; btn.disabled=true; return null; }
        msg.className="zvl-msg ok"; msg.textContent= v!==raw ? `✓ תקין (נורמל ל-${v})` : "✓ תקין"; btn.disabled=false; return v;
      };
      inp.oninput=check; let checked=false;
      // composedPath ולא target.closest: כפתור שמוחלף תוך כדי הלחיצה (כמו "השתמש ב-x-2") כבר מנותק
      // מהעץ כשהאירוע מגיע לשורה, ו-closest היה חושב שלחצו מחוץ לאזור העריכה וסוגר אותה.
      row.addEventListener("click",ev=>{ if(ev.composedPath().some(n=>n.classList&&n.classList.contains("zvl-body"))) return;
        const open=!row.classList.contains("open"); el.querySelectorAll(".zvl-row.open").forEach(r=>r.classList.remove("open"));
        if(open){ row.classList.add("open"); if(!checked){ checked=true; check(); } inp.focus(); inp.select(); } });
      const del=row.querySelector(".zvl-del");
      if(del) del.onclick=async()=>{ if(!confirm(`למחוק את הכתובת /${e.slug} מ«${e.name}»${e.count?` (${e.count} פרקים)`:""}?`)) return;
        del.disabled=true; const ok=await mutate({upsert:e.ids.map(id=>({id, custom_slug:null}))}); if(ok) render(); else del.disabled=false; };
      btn.onclick=async()=>{ const v=check(); if(!v) return; btn.disabled=true; msg.className="zvl-msg"; msg.textContent="שומר…";
        const ok=await mutate({upsert:e.ids.map(id=>({id, custom_slug:v}))});
        if (ok){ render(); } else { btn.disabled=false; msg.className="zvl-msg bad"; msg.textContent="השמירה נכשלה"; } };
    });
  }

  const origShow=window.showTab;
  window.showTab=function(n){
    pane.classList.add("hidden"); tb.classList.remove("active");
    if (n!=="links") return origShow.apply(this,arguments);
    document.querySelectorAll('[id^="pane-"]').forEach(p=>p.classList.add("hidden"));
    document.querySelectorAll(".tabs button").forEach(b=>b.classList.remove("active"));
    pane.classList.remove("hidden"); tb.classList.add("active"); render();
  };
  tb.onclick=()=>showTab("links");
  window.zvLinks={normSlug,suggest,validate,render};
})();
