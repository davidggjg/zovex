const AD_KEY = "833479e14706e97fe2b8acbc143a4963";

// srcDoc נותן ל-iframe מסמך משלו מההתחלה (בלי לחכות ל-onLoad/ref כמו עם
// contentWindow.document.write ידני), כך שסקריפט הפרסומת - שמשתמש
// ב-document.write - רץ מיד בתוך סביבה מבודדת משלו ולא נוגע ב-DOM של React.
const AD_HTML = `<!DOCTYPE html>
<html>
<head><style>body{margin:0;padding:0;overflow:hidden;background:transparent;}</style></head>
<body>
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
</body>
</html>`;

export default function AdBanner() {
  return (
    <div style={{ position: "fixed", bottom: 0, left: "50%", transform: "translateX(-50%)", zIndex: 9999, width: 320, height: 50, lineHeight: 0 }}>
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
