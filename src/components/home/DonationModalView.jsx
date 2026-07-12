export default function DonationModalView({ onContinue }) {
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.88)", zIndex: 9998, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} dir="rtl">
      <div style={{ background: "#111", borderRadius: 24, padding: 28, maxWidth: 380, width: "100%", textAlign: "center", boxShadow: "0 20px 60px rgba(0,0,0,0.6)", border: "1px solid #222" }}>
        <div style={{ fontSize: 32, marginBottom: 10 }}>🎬</div>
        <h2 style={{ fontSize: 20, fontWeight: 900, margin: "0 0 10px", color: "#fff" }}>עזרו לנו לשפר את האתר</h2>
        <p style={{ fontSize: 14, color: "#aaa", margin: "0 0 20px", lineHeight: 1.7 }}>
          ZOVEX פועל ללא מטרות רווח ובהתנדבות מלאה.<br/>
          תרומה קטנה תעזור לנו לשפר את איכות האתר,<br/>
          לשדרג את הנגנים ולהוסיף עוד תכנים כיפיים לצפייה 💙
        </p>
        <a href="https://www.bitpay.co.il/app/me/F062649F-7124-4CDF-88DD-A1FEA14185EB" target="_blank" rel="noreferrer" style={{ display: "block", background: "#0d7a5f", color: "#fff", borderRadius: 14, padding: "14px 0", fontSize: 16, fontWeight: 700, textDecoration: "none", marginBottom: 10 }}>
          💳 תרום בביט
        </a>
        <button onClick={onContinue} style={{ width: "100%", background: "#1e1e1e", color: "#888", border: "1px solid #333", borderRadius: 14, padding: "12px 0", fontSize: 14, cursor: "pointer", fontFamily: "inherit" }}>
          המשך לצפייה
        </button>
      </div>
    </div>
  );
}
