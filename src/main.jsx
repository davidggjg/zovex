import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { prefetchMovies } from './entities/Movie';
import './index.css';

// מתחילים למשוך את הקטלוג עוד לפני שהאפליקציה מציירת משהו. מסך הכניסה
// והפתיח נמשכים כמה שניות שבהן הרשת עמדה בטלה, והטעינה התחילה רק אחרי
// "התחבר"/"דלג" — כלומר המשתמש שילם את הזמן הזה פעמיים.
prefetchMovies();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
