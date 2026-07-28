import { useEffect, useState } from "react";

const AD_KEY = "833479e14706e97fe2b8acbc143a4963";

// גרסת דיבאג זמנית: ה-iframe מדווח על עצמו דרך postMessage בכל שלב,
// כדי לראות ישירות על המסך (בלי תלות ב-DevTools) איפה בדיוק זה נתקע.
const AD_HTML = `<!DOCTYPE html>
<html>
<head><style>body{margin:0;padding:0;overflow:hidden;background:transparent;}</style></head>
<body>
  <script>
    function report(msg){ try{ parent.postMessage({ __adDebug: true, msg: msg, t: Date.now() }, '*'); }catch(e){} }
    report('1-iframe-script-started');
    atOptions = {
      'key' : '${AD_KEY}',
      'format' : 'iframe',
      'height' : 50,
      'width' : 320,
      'params' : {}
    };
    report('2-atOptions-set');
  </script>
  <script
    src="https://www.highperformanceformat.com/${AD_KEY}/invoke.js"
    onload="report('3-invoke-onload-fired')"
    onerror="report('3-invoke-ONERROR-fired')"
  ></script>
  <script>report('4-after-invoke-tag');</script>
</body>
</html>`;

export default function AdBanner() {
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    const onMsg = (e) => {
      if (!e.data || !e.data.__adDebug) return;
      setLogs((prev) => [...prev, e.data.msg]);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);

  return (
    <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 9999, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <div style={{ background: "#000", color: "#0f0", fontFamily: "monospace", fontSize: 11, padding: "4px 8px", direction: "ltr", maxWidth: "100%", overflowWrap: "break-word" }}>
        AD DEBUG: {logs.length === 0 ? "waiting..." : logs.join(" | ")}
      </div>
      <iframe
        srcDoc={AD_HTML}
        title="ad-banner"
        scrolling="no"
        frameBorder="0"
        style={{ width: 320, height: 50, border: "none", display: "block" }}
      />
    </div>
  );
}
