import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';

export default function App() {
  return (
    <Router basename="/zovex">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/:slug" element={<Home />} />
      </Routes>
    </Router>
  );
}
