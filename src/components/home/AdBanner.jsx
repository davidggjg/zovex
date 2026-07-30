import { useEffect, useRef } from "react";

const AD_KEY = "8050516fd44627d57aee36c0f8306419";

// הבאנר נטען בתוך iframe מבודד (ולא ישירות בדף) כי סקריפט הפרסומת משתמש
// ב-document.write, שיכול למחוק את כל האתר אם ירוץ ישירות בתוך ה-DOM של React.
export default function AdBanner() {
  const iframeRef = useRef(null);

  useEffect(() => {
    const doc = iframeRef.current?.contentWindow?.document;
    if (!doc) return;
    doc.open();
    doc.write(`<!DOCTYPE html><html><head><style>body{margin:0;padding:0;overflow:hidden;background:transparent;}</style></head><body>
      <script>
        atOptions = {
          'key' : '${AD_KEY}',
          'format' : 'iframe',
          'height' : 50,
          'width' : 320,
          'params' : {}
        };
      </script>
      <script src="https://www.highperformanceformat.com/${AD_KEY}/invoke.js"></script>
    </body></html>`);
    doc.close();
  }, []);

  return (
    <div style={{ position: "fixed", bottom: 0, left: "50%", transform: "translateX(-50%)", zIndex: 9999, width: 320, height: 50, lineHeight: 0 }}>
      <iframe
        ref={iframeRef}
        title="ad-banner"
        scrolling="no"
        style={{ width: 320, height: 50, border: "none", display: "block" }}
      />
    </div>
  );
}
