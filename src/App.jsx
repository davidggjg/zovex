import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';

// נתיב הבסיס נגזר מ-BASE_URL של הבנייה: '/zovex/' ל-GitHub Pages, '/' לשרת.
const BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');

export default function App() {
  return (
    <Router basename={BASENAME}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/:slug" element={<Home />} />
        <Route path="/:slug/:episode" element={<Home />} />
      </Routes>
    </Router>
  );
}
