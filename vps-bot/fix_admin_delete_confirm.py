import pathlib, shutil, datetime, sys

TARGET = pathlib.Path("/opt/zovex-bot/admin.html")
OLD = '''async function persist(){
  toast(true);
  try{
    const r=await fetch("/content/save",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({password:PASS, movies,
        base_version: contentVersion===null?null:Number(contentVersion)})});
    const d=await r.json().catch(()=>({}));
    // ── הגנת עריכה במקביל: מישהו אחר שמר בזמן שעבדנו → לא דורסים, טוענים מחדש ──
    if(r.status===409){
      alert((d.detail||"מישהו אחר עדכן את התוכן בזמן שעבדת.")+
            "\\n\\nהתוכן נטען עכשיו מחדש — בצע את השינוי שוב על הגרסה העדכנית.");
      await loadContent();
      return false;
    }
    if(!r.ok) throw new Error(d.detail||r.status);
    if(d.version!==undefined && d.version!==null) contentVersion=String(d.version);  // עדכון הגרסה שלנו
    return true;
  }catch(e){ alert("שמירה נכשלה: "+e.message); return false; }
  finally{ toast(false); }
}'''

NEW = '''async function persist(){
  toast(true);
  try{
    const body={password:PASS, movies,
      base_version: contentVersion===null?null:Number(contentVersion)};
    let r=await fetch("/content/save",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)});
    let d=await r.json().catch(()=>({}));
    // ── הגנת מחיקה המונית: השרת עצר כי חלק גדול מהקטלוג נעלם. אם זה מכוון
    // (מוחקים סדרה שלמה וכו') — מציעים לאשר ולשלוח שוב עם confirm_delete. ──
    if(r.status===409 && /מוחקת .* פריטים/.test(d.detail||"")){
      if(!confirm((d.detail||"")+"\\n\\nלאשר את המחיקה ולשמור בכל זאת?")) return false;
      r=await fetch("/content/save",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...body, confirm_delete:true})});
      d=await r.json().catch(()=>({}));
    }
    // ── הגנת עריכה במקביל: מישהו אחר שמר בזמן שעבדנו → לא דורסים, טוענים מחדש ──
    if(r.status===409){
      alert((d.detail||"מישהו אחר עדכן את התוכן בזמן שעבדת.")+
            "\\n\\nהתוכן נטען עכשיו מחדש — בצע את השינוי שוב על הגרסה העדכנית.");
      await loadContent();
      return false;
    }
    if(!r.ok) throw new Error(d.detail||r.status);
    if(d.version!==undefined && d.version!==null) contentVersion=String(d.version);  // עדכון הגרסה שלנו
    return true;
  }catch(e){ alert("שמירה נכשלה: "+e.message); return false; }
  finally{ toast(false); }
}'''

src = TARGET.read_text(encoding="utf-8")
if "confirm_delete:true" in src:
    print("✓ כבר מוחל. אין מה לעשות.")
    sys.exit(0)
n = src.count(OLD)
if n != 1:
    print(f"❌ נמצא {n} פעמים (ציפינו לאחת) — הקובץ שונה ממה שציפינו. לא שונה כלום.")
    sys.exit(1)
bak = f"{TARGET}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(TARGET, bak)
TARGET.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"✅ הוחל. גיבוי: {bak}")
print("אין צורך בריסט — רענן את דף הפאנל (Ctrl+Shift+R) ונסה למחוק שוב.")
