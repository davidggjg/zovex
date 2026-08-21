import { useState, useEffect } from "react";

// פרסומת תרומה במסך הבית — כמו פרסומת שאפשר לדלג עליה אחרי 3 שניות.
// חמה, כנה, בלי לחץ. מוצגת פעם אחת לכל כניסה (session), רק במסך הבית.
const BIT_URL = "https://www.bitpay.co.il/app/me/F062649F-7124-4CDF-88DD-A1FEA14185EB";
const SKIP_AFTER = 3; // שניות עד שמותר לדלג

export default function DonationAd({ onSkip }) {
  const [left, setLeft] = useState(SKIP_AFTER);

  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);

  const canSkip = left <= 0;

  return (
    <div
      dir="rtl"
      style={{
        position: "fixed", inset: 0, zIndex: 10000,
        background: "rgba(0,0,0,0.92)", backdropFilter: "blur(4px)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
        animation: "zxfade .25s ease",
      }}
    >
      <style>{`@keyframes zxfade{from{opacity:0}to{opacity:1}}
        @keyframes zxpop{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}`}</style>

      <div
        style={{
          position: "relative", width: "100%", maxWidth: 420,
          background: "linear-gradient(180deg,#191013 0%,#0d0d10 100%)",
          border: "1px solid #2a1a1e", borderRadius: 24,
          padding: "34px 26px 26px", textAlign: "center",
          boxShadow: "0 24px 70px rgba(0,0,0,.65)",
          animation: "zxpop .3s ease both",
        }}
      >
        {/* תווית "פרסומת" בפינה */}
        <div style={{
          position: "absolute", top: 12, right: 14, fontSize: 10, fontWeight: 700,
          color: "#7a7a80", letterSpacing: 1, textTransform: "uppercase",
        }}>פרסומת</div>

        <div style={{ fontSize: 40, marginBottom: 12 }}>💙</div>

        <h2 style={{ fontSize: 22, fontWeight: 900, margin: "0 0 14px", color: "#fff", lineHeight: 1.3 }}>
          רגע לפני שנמשיך…
        </h2>

        <p style={{ fontSize: 15, color: "#c4c4cc", margin: "0 0 8px", lineHeight: 1.85 }}>
          חברים, בכנות מלאה: אנחנו מפעילים את <b style={{ color: "#fff" }}>ZOVEX</b> ב<b style={{ color: "#fff" }}>התנדבות</b>,
          ומשלמים על השרתים <b style={{ color: "#fff" }}>מהכיס האישי שלנו</b> — כל חודש מחדש.
        </p>
        <p style={{ fontSize: 15, color: "#c4c4cc", margin: "0 0 22px", lineHeight: 1.85 }}>
          ההוצאות כבר גדולות עלינו, ואנחנו לא מרוויחים מזה שקל. אם ZOVEX עושה לכם טוב —
          <b style={{ color: "#fff" }}> תרומה קטנה</b> תעזור לנו להמשיך, לשדרג ולהוסיף עוד תכנים.
          כל שקל באמת משנה 🙏
        </p>

        <a
          href={BIT_URL} target="_blank" rel="noreferrer"
          style={{
            display: "block", background: "linear-gradient(90deg,#e50914,#b70710)",
            color: "#fff", borderRadius: 14, padding: "15px 0", fontSize: 17, fontWeight: 800,
            textDecoration: "none", marginBottom: 12, boxShadow: "0 8px 24px rgba(229,9,20,.35)",
          }}
        >
          💳 לתרומה מהירה בביט
        </a>

        <button
          onClick={canSkip ? onSkip : undefined}
          disabled={!canSkip}
          style={{
            width: "100%", background: "transparent",
            color: canSkip ? "#e7e7ea" : "#6a6a70",
            border: `1px solid ${canSkip ? "#3a3a42" : "#26262c"}`,
            borderRadius: 14, padding: "13px 0", fontSize: 15,
            cursor: canSkip ? "pointer" : "default", fontFamily: "inherit",
            fontWeight: 700, transition: "color .2s,border-color .2s",
          }}
        >
          {canSkip ? "דילוג ✕" : `אפשר לדלג בעוד ${left}…`}
        </button>

        <div style={{ fontSize: 12, color: "#6a6a70", marginTop: 14 }}>
          תודה שאתם חלק מ-ZOVEX ❤️
        </div>
      </div>
    </div>
  );
}
