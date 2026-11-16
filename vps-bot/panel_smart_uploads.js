/* ZOVEX · העלאות חכמות מהבוט — זיהוי הסדרה אוטומטית + חלון בחירה.
   בלוק עצמאי: עוטף את addSeriesUploads ואת loadUploads הקיימים בלי לשנות אותם.
   נשען על הגלובליים של הפאנל: _uploads, _serGroups, movies, seriesMap, persist,
   mutate, loadUploads, extractVideoInfo, esc, PASS. */
(function(){
  if (window.__zvSmartUploads) return; window.__zvSmartUploads = true;

  // ── נרמול שם: מסיר עונה/פרק/איכות/סימנים/מספרים, כדי ש"פאודה1", "פאודה •" ו-"Fauda S02" יתאימו
  function norm(s){
    return String(s||"").toLowerCase()
      .replace(/[._\-–—:|()\[\]{}"'׳״!?,•·+]/g," ")
      .replace(/עונה\s*\d+|פרק\s*\d+|ע\s*\d+\s*פ\s*\d+|מתורגם|כתוביות|תרגום\s*מובנה|דיבוב/g," ")
      .replace(/\b(s\d{1,2}(e\d{1,3})?|season\s*\d+|e\d{1,3}|ep\s*\d+|\d{3,4}p|hd|fhd|web(-?dl|rip)?|hebsub|x26[45]|hevc)\b/g," ")
      .replace(/\d+/g," ").replace(/\s+/g," ").trim();
  }
  function bigrams(s){ s=s.replace(/\s/g,""); const out=new Map(); for(let i=0;i<s.length-1;i++){const g=s.slice(i,i+2); out.set(g,(out.get(g)||0)+1);} return out; }
  function dice(a,b){ const A=bigrams(a),B=bigrams(b); let inter=0,na=0,nb=0; A.forEach(v=>na+=v); B.forEach(v=>nb+=v);
    A.forEach((v,k)=>{ if(B.has(k)) inter+=Math.min(v,B.get(k)); }); return (na+nb)? 2*inter/(na+nb) : 0; }
  function sim(a,b){
    a=norm(a); b=norm(b); if(!a||!b) return 0; if(a===b) return 1;
    const short=a.length<b.length?a:b, long=a.length<b.length?b:a;
    if(short.length>=3 && long.includes(short)) return 0.9;
    const ta=new Set(a.split(" ")), tb=new Set(b.split(" ")); let i=0; ta.forEach(t=>{ if(tb.has(t)) i++; });
    const jac=i/(ta.size+tb.size-i);
    return Math.max(jac, dice(a,b)*0.95);
  }
  // מועמדים: שם הסדרה, השם האנגלי וה-slug של הסדרות שכבר באתר
  function candidates(name){
    const sm=seriesMap(), out=[];
    for (const sn of Object.keys(sm)){
      const eps=sm[sn], f=eps.find(e=>e.thumbnail_url)||eps[0]||{};
      const keys=[sn, f.en_title||"", (f.custom_slug||"").replace(/-/g," ")];
      const score=Math.max(...keys.map(k=>sim(name,k)));
      if (score>=0.55) out.push({name:sn, score, poster:f.thumbnail_url||"", count:eps.length, category:f.category||""});
    }
    return out.sort((a,b)=>b.score-a.score).slice(0,4);
  }
  window.zvSeriesCandidates = candidates;   // לבדיקות

  // ── עיצוב החלון (נשען על משתני העיצוב אם קיימים, עם ברירות מחדל)
  const st=document.createElement("style"); st.id="zv-smart-css";
  st.textContent=`
  .zvov{position:fixed;inset:0;z-index:2000;background:rgba(30,20,50,.28);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
    display:flex;align-items:flex-end;justify-content:center;animation:zvfade .18s ease-out}
  @media(min-width:700px){.zvov{align-items:center}}
  .zvsheet{width:min(640px,100%);max-height:88vh;overflow:auto;background:var(--glass-strong,#fff);
    -webkit-backdrop-filter:saturate(170%) blur(28px);backdrop-filter:saturate(170%) blur(28px);
    border:1px solid var(--edge,rgba(255,255,255,.8));border-radius:26px 26px 0 0;padding:18px 18px 22px;
    box-shadow:var(--depth,0 20px 60px rgba(0,0,0,.25));animation:zvup .26s cubic-bezier(.2,.9,.3,1)}
  @media(min-width:700px){.zvsheet{border-radius:26px}}
  .zvsheet h3{margin:0 0 4px;font-size:18px;letter-spacing:-.01em;overflow-wrap:anywhere}
  .zvsub{color:var(--text-2,#666);font-size:13px;margin-bottom:14px}
  .zvsec{font-size:12.5px;font-weight:700;color:var(--text-2,#666);margin:14px 2px 8px}
  .zvgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:10px}
  .zvcard{display:flex;flex-direction:column;gap:6px;padding:8px;border-radius:16px;cursor:pointer;text-align:right;
    background:rgba(255,255,255,.55);border:1px solid rgba(255,255,255,.9);box-shadow:var(--depth-sm,0 4px 12px rgba(0,0,0,.08));
    transition:transform .12s ease-out;min-width:0;color:inherit;font:inherit;font-weight:600}
  .zvcard:active{transform:scale(.97)}
  .zvcard.sel{outline:2px solid var(--gold,#b08a4e);outline-offset:1px}
  .zvcard img,.zvcard .ph{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:11px;background:rgba(60,45,80,.08)}
  .zvcard .n{font-size:13px;line-height:1.3;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
  .zvcard .m{font-size:11.5px;color:var(--text-2,#666);font-weight:500}
  .zvrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px}
  .zvrow>input,.zvrow>select{flex:1 1 180px;margin:0}
  .zvchip{display:inline-flex;align-items:center;gap:4px;margin:6px 0 0;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;
    background:rgba(176,138,78,.14);color:var(--ink,#18171c);border:1px solid rgba(176,138,78,.35);cursor:pointer;max-width:100%;
    overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  @keyframes zvfade{from{opacity:0}} @keyframes zvup{from{transform:translateY(24px);opacity:.6}}
  @media(prefers-reduced-motion:reduce){.zvov,.zvsheet{animation:none}}`;
  document.head.appendChild(st);

  function idxsFor(name){
    return _uploads.map((u,i)=>i).filter(i=>{ const u=_uploads[i]; const isSer=(u.media_kind==="tv")||!!u.series_name;
      return isSer && (u.series_name||u.title||"סדרה")===name; });
  }

  // הוספה בפועל: אותו מבנה רשומה כמו addSeriesUploads המקורי, עם יעד ומטא שנבחרו
  async function addAs(idxs, target, meta){
    const exist=movies.find(m=>m.series_name===target && (m.thumbnail_url||m.description));
    const poster=meta.poster || (exist&&exist.thumbnail_url) || "";
    const desc=meta.overview || (exist&&exist.description) || "";
    const year=meta.year || (exist&&exist.year) || null;
    const slug=(exist&&exist.custom_slug) || null;
    const cat=meta.category || (exist&&exist.category) || "סדרות";
    const ids=[];
    const items=idxs.map(i=>{ const u=_uploads[i]; const vid=(u.video_url||"").trim(); const info=extractVideoInfo(vid);
      if(u.channel_msg_id!=null) ids.push(u.channel_msg_id);
      return { id:crypto.randomUUID(), created_date:new Date().toISOString(),
        title:target, year:year?parseInt(year):null, category:cat, description:u.description||desc,
        type:info.type, video_id:info.video_id, video_url:vid, thumbnail_url:u.thumbnail_url||poster,
        custom_slug:slug, series_name:target, season_number:u.season_number||1,
        episode_number:u.episode_number||null, episode_title:"" }; });
    // mutate ולא persist: מוסיף רק את הפרקים החדשים על המצב הנוכחי בשרת, ולכן
    // לא מתנגש (409) עם בוט ההעלאות שמוסיף פריטים כל הזמן.
    if(!(await mutate({upsert:items}))) return false;
    try{ await fetch("/uploads/clear",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS, channel_msg_ids:ids})}); }catch{}
    await loadUploads();
    return items.length;
  }

  function close(ov){ ov.remove(); document.removeEventListener("keydown", ov._esc); }

  async function open(gi){
    const name=_serGroups[gi]; if(!name) return;
    const idxs=idxsFor(name); if(!idxs.length) return;
    const cands=candidates(name);
    const clean=(norm(name)||name).replace(/\s+/g," ");
    const ov=document.createElement("div"); ov.className="zvov";
    ov.innerHTML=`<div class="zvsheet" role="dialog" aria-modal="true">
      <h3>📺 ${esc(name)}</h3><div class="zvsub">${idxs.length} פרקים ממתינים · לאן להוסיף?</div>
      ${cands.length?`<div class="zvsec">נראה שזו הסדרה שכבר באתר</div><div class="zvgrid" data-k="ex">${cands.map((c,j)=>`
        <button class="zvcard" data-j="${j}">${c.poster?`<img src="${esc(c.poster)}" alt="" loading="lazy">`:'<div class="ph"></div>'}
          <span class="n">${esc(c.name)}</span><span class="m">${c.count} פרקים · ${Math.round(c.score*100)}% התאמה</span></button>`).join("")}</div>`:""}
      <div class="zvsec">${cands.length?"או — סדרה חדשה":"סדרה חדשה"}</div>
      <div class="zvrow"><input id="zvName" value="${esc(clean)}" placeholder="שם הסדרה">
        <select id="zvCat"><option>סדרות</option><option>סדרות לילדים</option><option>סדרות ישראליות</option><option>אנימה</option></select></div>
      <div class="zvsub" id="zvTmdbMsg" style="margin:10px 2px 6px">מחפש פוסטר ב-TMDB…</div>
      <div class="zvgrid" data-k="tm"></div>
      <div class="zvrow"><button id="zvNew" style="flex:1">➕ הוסף כסדרה חדשה</button><button class="gray" id="zvCancel">ביטול</button></div>
      <div class="zvsub" id="zvMsg" style="margin-top:8px"></div></div>`;
    document.body.appendChild(ov);
    ov._esc=e=>{ if(e.key==="Escape") close(ov); }; document.addEventListener("keydown", ov._esc);
    ov.addEventListener("click", e=>{ if(e.target===ov) close(ov); });
    ov.querySelector("#zvCancel").onclick=()=>close(ov);
    const msg=ov.querySelector("#zvMsg");
    const busy=on=>ov.querySelectorAll("button").forEach(b=>b.disabled=on);

    ov.querySelectorAll('[data-k="ex"] .zvcard').forEach(b=>b.onclick=async()=>{
      const c=cands[+b.dataset.j]; busy(true); msg.textContent="מוסיף…";
      const n=await addAs(idxs, c.name, {});
      if(n){ close(ov); toastOk(`נוספו ${n} פרקים ל«${c.name}» — עם הפוסטר והתקציר של הסדרה ✓`); } else { busy(false); msg.textContent="השמירה נכשלה"; }
    });

    let picked=null;
    const grid=ov.querySelector('[data-k="tm"]'), tmsg=ov.querySelector("#zvTmdbMsg");
    async function search(q){
      tmsg.textContent="מחפש פוסטר ב-TMDB…"; grid.innerHTML=""; picked=null;
      try{
        const d=await (await fetch("/admin/tmdb?q="+encodeURIComponent(q))).json();
        let res=(d.results||[]); res=res.filter(x=>x.type==="tv").concat(res.filter(x=>x.type!=="tv")).slice(0,6);
        if(!res.length){ tmsg.textContent="לא נמצא ב-TMDB — אפשר להוסיף גם בלי פוסטר, או לשנות את השם ולחפש שוב."; return; }
        tmsg.textContent="בחר את הפוסטר הנכון (לא חובה):";
        grid.innerHTML=res.map((x,j)=>`<button class="zvcard" data-j="${j}">${x.poster?`<img src="${esc(x.poster)}" alt="" loading="lazy">`:'<div class="ph"></div>'}
          <span class="n">${esc(x.title||"")}</span><span class="m">${x.year||""} ${x.type==="tv"?"· סדרה":"· סרט"}</span></button>`).join("");
        grid.querySelectorAll(".zvcard").forEach(b=>b.onclick=()=>{ grid.querySelectorAll(".zvcard").forEach(x=>x.classList.remove("sel"));
          b.classList.add("sel"); picked=res[+b.dataset.j]; if(picked.title && !ov._renamed) ov.querySelector("#zvName").value=picked.title; });
        const first=grid.querySelector(".zvcard"); if(first) first.click();
      }catch(e){ tmsg.textContent="החיפוש ב-TMDB נכשל — אפשר להוסיף בלי פוסטר."; }
    }
    const nameIn=ov.querySelector("#zvName"); let t=null;
    nameIn.addEventListener("input",()=>{ ov._renamed=true; clearTimeout(t); t=setTimeout(()=>search(nameIn.value.trim()), 450); });
    search(clean);

    ov.querySelector("#zvNew").onclick=async()=>{
      const target=nameIn.value.trim(); if(!target){ msg.textContent="חסר שם"; return; }
      busy(true); msg.textContent="מוסיף…";
      const meta=picked?{poster:picked.poster, overview:picked.overview, year:picked.year}:{};
      meta.category=ov.querySelector("#zvCat").value;
      const n=await addAs(idxs, target, meta);
      if(n){ close(ov); toastOk(`נוספו ${n} פרקים כסדרה «${target}»${picked?" — עם פוסטר ותקציר ✓":""}`); } else { busy(false); msg.textContent="השמירה נכשלה"; }
    };
  }

  function toastOk(text){
    const el=document.createElement("div"); el.className="saving"; el.textContent=text; el.style.whiteSpace="normal";
    el.style.maxWidth="min(520px,92vw)"; el.style.textAlign="center"; document.body.appendChild(el);
    setTimeout(()=>el.remove(), 3800);
  }

  // ── חיבור לפאנל הקיים
  window.addSeriesUploads = gi => open(gi);
  const origLoad = window.loadUploads || loadUploads;
  window.loadUploads = async function(){
    const r = await origLoad.apply(this, arguments);
    try{
      document.querySelectorAll('#uploadsList .ser .head button[onclick^="addSeriesUploads("]').forEach(btn=>{
        const gi=+(btn.getAttribute("onclick").match(/\d+/)||[])[0]; const name=_serGroups[gi]; if(!name) return;
        const c=candidates(name)[0]; const meta=btn.parentElement.querySelector(".meta")||btn.parentElement;
        if(meta.querySelector(".zvchip")) return;
        const chip=document.createElement("span"); chip.className="zvchip";
        chip.textContent = c ? (c.name===name ? `✓ ${c.name} — כבר באתר` : `🔗 נראה כמו: ${c.name}`) : "✨ סדרה חדשה — לחץ להוספה עם פוסטר";
        chip.onclick=e=>{ e.stopPropagation(); open(gi); };
        meta.appendChild(chip);
      });
    }catch(e){}
    return r;
  };
})();
