import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';

export default function App() {
  // ה-basename נגזר מ-base של הבנייה: ב-GitHub Pages בונים עם base=/zovex/
  // וב-VPS (שמגיש מהשורש) בונים עם --base=/ — כך אותו קוד מתאים לשניהם בלי
  // לתקן מחרוזות ב-bundle אחרי הבנייה.
  return (
    <Router basename={import.meta.env.BASE_URL}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/:slug" element={<Home />} />
        <Route path="/:slug/:episode" element={<Home />} />
      </Routes>
    </Router>
  );
}
