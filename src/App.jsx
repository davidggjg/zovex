import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';

// Basename follows the Vite build base: "/zovex" for GitHub Pages, "/" when
// the site is served from the VPS root. Strip the trailing slash so
// react-router gets "/zovex" or "" (which it treats as root).
const ROUTER_BASENAME = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');

export default function App() {
  return (
    <Router basename={ROUTER_BASENAME}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/:slug" element={<Home />} />
        <Route path="/:slug/:episode" element={<Home />} />
      </Routes>
    </Router>
  );
}
