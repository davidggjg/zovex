/* ZOVEX · תמיכה בסגנון אפליקציית הודעות: רשימה/צ'אט במסך מלא בטלפון, שני טורים במחשב.
   מחליף רק את openThread (התצוגה); השליחה נשארת sendReply/‎/feedback/reply‎ המקוריים. */
(function(){
  if (window.__zvSupport) return; window.__zvSupport = true;
  const st=document.createElement("style"); st.id="zv-support-css";
  st.textContent=`
  #pane-support .grid2{display:grid!important;grid-template-columns:minmax(0,330px) minmax(0,1fr)!important;gap:16px}
  #pane-support #supThreads{max-height:calc(100vh - 230px)!important;overflow:auto}
  #pane-support #supThreads .item{cursor:pointer;border-radius:16px;border-bottom:none;margin-bottom:4px}
  #pane-support #supThreads .item.zv-active{background:rgba(255,255,255,.75);box-shadow:var(--depth-sm,0 4px 12px rgba(0,0,0,.08))}
  #supChat{display:flex;flex-direction:column;padding:0!important;overflow:hidden;
    height:calc(100vh - 230px);min-height:420px;position:sticky;top:130px}
  .zvc-head{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--hair,#eee);
    background:rgba(255,255,255,.55);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px)}
  .zvc-back{display:none}
  .zvc-av{flex:none;width:38px;height:38px;border-radius:50%;display:grid;place-items:center;font-weight:700;color:#fff;
    background:linear-gradient(140deg,#c7b5ff,#ffb9a3)}
  .zvc-who{min-width:0;flex:1}
  .zvc-name{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .zvc-mail{font-size:12px;color:var(--text-2,#666);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;direction:ltr;text-align:right}
  .zvc-msgs{flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:6px;scroll-behavior:smooth}
  .zvc-day{align-self:center;font-size:11.5px;color:var(--text-2,#666);background:rgba(255,255,255,.6);padding:3px 10px;border-radius:999px;margin:8px 0 4px}
  .zvc-b{max-width:min(78%,560px);padding:9px 13px 7px;border-radius:20px;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;
    font-size:14.5px;line-height:1.45;box-shadow:0 1px 2px rgba(40,25,70,.08)}
  .zvc-b.u{align-self:flex-start;background:rgba(255,255,255,.88);border:1px solid rgba(255,255,255,.95);border-bottom-right-radius:6px;color:var(--text,#1d1b22)}
  .zvc-b.a{align-self:flex-end;background:linear-gradient(180deg,#2e2c34,#17161b);color:#fff;border-bottom-left-radius:6px}
  .zvc-b a{color:inherit;text-decoration:underline}
  .zvc-t{display:block;font-size:10.5px;opacity:.55;margin-top:3px;direction:ltr}
  .zvc-b.u .zvc-t{text-align:right} .zvc-b.a .zvc-t{text-align:left}
  .zvc-kind{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:999px;margin-bottom:3px;
    background:rgba(176,138,78,.16);color:#8a6a35}
  .zvc-compose{display:flex;align-items:flex-end;gap:8px;padding:10px 12px;border-top:1px solid var(--hair,#eee);
    background:rgba(255,255,255,.6);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px)}
  .zvc-compose textarea{flex:1;margin:0;min-height:42px;max-height:140px;resize:none;border-radius:21px;padding:10px 14px;line-height:1.4}
  .zvc-send{flex:none;width:42px;height:42px;padding:0;border-radius:50%;font-size:18px;display:grid;place-items:center}
  .zvc-note{padding:0 14px 8px;font-size:12px}
  .zvc-empty{flex:1;display:grid;place-items:center;color:var(--text-2,#666);font-size:14px;padding:30px;text-align:center}
  @media(max-width:760px){
    #pane-support .grid2{grid-template-columns:1fr!important}
    #pane-support #supThreads{max-height:none!important}
    #pane-support:not(.zv-open) #supChat{display:none}
    #pane-support.zv-open #supThreads{display:none}
    /* כמו וואטסאפ: השיחה נפתחת על כל המסך, מעל הטאבים, עם חזרה למעלה */
    /* backdrop-filter על הכרטיס העוטף הופך אותו למסגרת של position:fixed — מכבים אותו בזמן שיחה */
    #pane-support.zv-open > .card{-webkit-backdrop-filter:none!important;backdrop-filter:none!important;transform:none!important}
    #pane-support.zv-open #supChat{position:fixed!important;inset:0;z-index:1500;height:100dvh;min-height:0;
      margin:0!important;border-radius:0!important;border:none!important;background:var(--bg,#f7f3ee)!important}
    #pane-support.zv-open #supChat .zvc-head{padding-top:max(12px,env(safe-area-inset-top))}
    #pane-support.zv-open #supChat .zvc-compose{padding-bottom:max(10px,env(safe-area-inset-bottom))}
    .zvc-back{display:inline-flex;font-size:18px;padding:6px 12px}
  }`;
  document.head.appendChild(st);

  const pane=()=>document.getElementById("pane-support");
  const urlRe=/(https?:\/\/[^\s<]+)/g;
  function body(text){ return esc(text||"").replace(urlRe,u=>`<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`); }
  function dayOf(ts){ try{ const d=new Date(ts); return isNaN(d)? "" : d.toLocaleDateString("he-IL",{day:"numeric",month:"long"}); }catch{ return ""; } }

  window.openThread=function(i){
    _curThread=_threads[i]; const t=_curThread; if(!t) return;
    let last="";
    const msgs=(t.messages||[]).map(m=>{
      const mine=m.from==="admin", d=dayOf(m.ts); let sep="";
      if(d && d!==last){ sep=`<div class="zvc-day">${esc(d)}</div>`; last=d; }
      const kind=(!mine && m.kind)?`<span class="zvc-kind">${esc(KIND_HE[m.kind]||m.kind)}</span><br>`:"";
      return `${sep}<div class="zvc-b ${mine?"a":"u"}">${kind}${body(m.text)}<span class="zvc-t">${esc(tsFmt(m.ts)||"")}</span></div>`;
    }).join("");
    const name=t.name||"משתמש";
    $("supChat").innerHTML=`
      <div class="zvc-head"><button class="zvc-back mini gray" type="button" aria-label="חזרה">→</button>
        <div class="zvc-av">${esc(name.trim().charAt(0)||"?")}</div>
        <div class="zvc-who"><div class="zvc-name">${esc(name)}</div><div class="zvc-mail">${esc(t.email||t.user_id||"")}</div></div></div>
      <div class="zvc-msgs" id="zvcMsgs">${msgs||'<div class="zvc-empty">אין הודעות בשיחה הזו</div>'}</div>
      <div class="zvc-compose"><textarea id="supReply" rows="1" placeholder="כתוב תשובה…" title="Enter לשליחה · Shift+Enter לשורה חדשה"></textarea>
        <button class="zvc-send" type="button" aria-label="שלח">↑</button></div>
      <div id="supReplyMsg" class="muted zvc-note"></div>`;
    pane().classList.add("zv-open");   // קודם מציגים — לרכיב מוסתר אין גובה לגלול אליו
    const box=$("zvcMsgs");
    const toEnd=()=>{ box.style.scrollBehavior="auto"; box.scrollTop=box.scrollHeight; box.style.scrollBehavior=""; };
    toEnd(); requestAnimationFrame(toEnd);
    const ta=$("supReply");
    const grow=()=>{ ta.style.height="auto"; ta.style.height=Math.min(ta.scrollHeight,140)+"px"; };
    ta.addEventListener("input",grow);
    ta.addEventListener("keydown",e=>{ if(e.key==="Enter" && !e.shiftKey && !e.isComposing){ e.preventDefault(); sendReply(); } });
    $("supChat").querySelector(".zvc-send").onclick=()=>sendReply();
    $("supChat").querySelector(".zvc-back").onclick=()=>{ pane().classList.remove("zv-open"); };
    document.querySelectorAll("#supThreads .item").forEach((el,k)=>el.classList.toggle("zv-active",k===i));
    if (matchMedia("(min-width:761px)").matches) ta.focus();
    try{ markRead(t); }catch(e){}
  };

  // רשימה ריקה/רענון: מציג מצב ריק נעים, וסוגר את הצ'אט במובייל אם השיחה נעלמה
  const origLoad=window.loadSupport;
  if (origLoad) window.loadSupport=async function(){
    const r=await origLoad.apply(this,arguments);
    const chat=$("supChat");
    if (chat && !chat.querySelector(".zvc-head")) chat.innerHTML='<div class="zvc-empty">💬<br>בחר שיחה מהרשימה</div>';
    if (_curThread){ const k=_threads.findIndex(x=>x.user_id===_curThread.user_id);
      document.querySelectorAll("#supThreads .item").forEach((el,j)=>el.classList.toggle("zv-active",j===k)); }
    return r;
  };
})();
