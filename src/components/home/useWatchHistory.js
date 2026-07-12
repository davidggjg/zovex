import React from "react";
import { apiCall } from "./helpers";

// ── Progress / History (רק למשתמשים מחוברים) ──
export function useWatchHistory(user) {
  const saveProgress = React.useCallback(async (mediaId, position, duration) => {
    if (!user) return;
    await apiCall("/api/progress", "POST", { media_id: mediaId, position, duration }, user.id);
  }, [user]);

  const loadProgress = React.useCallback(async (mediaId) => {
    if (!user) return 0;
    const res = await apiCall(`/api/progress/${mediaId}`, "GET", null, user.id);
    return res?.position || 0;
  }, [user]);

  const saveHistory = React.useCallback(async (mediaId, title, thumbnailUrl) => {
    if (!user) return;
    // עדכון מיידי של הרשימה המקומית — כך שהיא תופיע מיד בקטגוריית "היסטוריה"
    // בלי לחכות/לדרוש רענון של הדף (זה מה שגרם ל"נכנסתי להיסטוריה ואין כלום")
    const entry = { media_id: mediaId, title, thumbnail_url: thumbnailUrl || "" };
    setHistory(prev => [entry, ...prev.filter(h => h.media_id !== mediaId)]);
    const saved = await apiCall("/api/history", "POST", { media_id: mediaId, title, thumbnail_url: thumbnailUrl || "" }, user.id);
    // אם השרת מחזיר את הרשומה/הרשימה המעודכנת בפועל — נסנכרן איתה בשקט
    if (Array.isArray(saved)) setHistory(saved);
  }, [user]);

  const [history, setHistory] = React.useState([]);
  const refreshHistory = React.useCallback(() => {
    if (!user) return;
    apiCall("/api/history", "GET", null, user.id).then(h => { if (h) setHistory(h); });
  }, [user]);
  React.useEffect(() => { refreshHistory(); }, [refreshHistory]);

  return { history, saveProgress, loadProgress, saveHistory, refreshHistory };
}
