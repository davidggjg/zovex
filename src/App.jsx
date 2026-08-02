import { useState } from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';
import ZovexIntro from './components/ZovexIntro';

// נתיב הבסיס נגזר מ-BASE_URL של הבנייה: '/zovex/' ל-GitHub Pages, '/' לשרת.
const BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');

export default function App() {
  // פתיח מוצג פעם אחת לכל כניסה (session) — לא חוזר בכל רענון/ניווט פנימי.
  const [showIntro, setShowIntro] = useState(() => {
    try { return !sessionStorage.getItem('zovex_intro_seen'); } catch (e) { return true; }
  });
  const dismissIntro = () => {
    try { sessionStorage.setItem('zovex_intro_seen', '1'); } catch (e) { /* ignore */ }
    setShowIntro(false);
  };

  return (
    <>
      {showIntro && <ZovexIntro onDone={dismissIntro} />}
      <Router basename={BASENAME}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/:slug" element={<Home />} />
          <Route path="/:slug/:episode" element={<Home />} />
        </Routes>
      </Router>
    </>
  );
}
