import { injectTokens } from "@/theme/tokens";
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// ── קישורים ישנים עם /zovex/ ───────────────────────────────────────────────
//
// חודשים שותפו קישורים בצורה /zovex/<שם>/watch, כי הקוד כתב אותם קשיח
// לשורת הכתובת. על השרת ה-basename הוא "/", ולכן כתובת כזאת לא תואמת
// לשום מסלול ומצוירת כעמוד לבן. כל קישור שנשלח בוואטסאפ עד היום מת.
//
// מסירים את הקידומת **לפני** שה-router נטען: הוא קורא את הכתובת פעם אחת
// בעלייה, ולכן replaceState כאן מגיע בזמן ואינו גורר ניווט או הבהוב.
// רק כשהאתר מוגש מהשורש — בבנייה עם base=/zovex/ הקידומת נכונה כמו שהיא.
try {
  const base = import.meta.env.BASE_URL;
  if ((base === '/' || base === '') && location.pathname.startsWith('/zovex/')) {
    const clean = location.pathname.slice('/zovex'.length) || '/';
    window.history.replaceState(null, '', clean + location.search + location.hash);
  }
} catch (_) {}

// ── דפי SEO מרונדרים מראש ────────────────────────────────────────────────
// prerender-routes.js שם על ‎#root‎ עיצוב מוטבע (padding, גופן, רקע) כדי
// שהתוכן הסטטי ייראה סביר לבוטים. React מחליף את התוכן אבל לא את המאפיינים
// של הקונטיינר — והאתר כולו נשאר "מעוות" אחרי שעוברים לדף הבית.
const rootEl = document.getElementById('root');
rootEl.removeAttribute('style');

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

injectTokens();
