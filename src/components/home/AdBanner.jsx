import { useEffect } from "react";

// סקריפט הפרסומת (effectivecpmnetwork / Monetag). זהו פורמט שמזריק את עצמו
// לדף (social-bar / interstitial) ולכן הוא נטען ב-document הראשי פעם אחת,
// לא בתוך iframe. הסקריפט מרנדר את הפרסומת בעצמו — אין צורך במיכל בגודל קבוע.
const AD_SRC =
  "https://pl30611396.effectivecpmnetwork.com/31/55/3b/31553bb13b5818074248fff95e48cfa9.js";
const AD_ID = "zovex-ad-script";

export default function AdBanner() {
  useEffect(() => {
    // טעינה חד-פעמית — אם כבר קיים, לא נטען שוב (מונע כפילויות בניווט בין דפים)
    if (document.getElementById(AD_ID)) return;
    const s = document.createElement("script");
    s.id = AD_ID;
    s.src = AD_SRC;
    s.async = true;
    document.body.appendChild(s);
  }, []);

  return null;
}
