import { useState, useEffect } from "react";

// ── API endpoint: /zovex/api?key=XXX ── מחזיר את מאגר הסרטים כ-JSON למי שמחזיק מפתח API תקף
export function useApiKeyEndpoint(slug) {
  const [apiResult, setApiResult] = useState(null);

  useEffect(() => {
    if (slug !== "api") return;
    (async () => {
      const params = new URLSearchParams(window.location.search);
      const key = params.get("key");
      try {
        const keysRes = await fetch(`${import.meta.env.BASE_URL}apikeys.json?t=` + Date.now());
        const keys = keysRes.ok ? await keysRes.json() : [];
        const valid = keys.find(k => k.key === key && k.active);
        if (!valid) {
          setApiResult({ error: "Invalid or inactive API key" });
          return;
        }
        const moviesRes = await fetch(`${import.meta.env.BASE_URL}movies.json?t=` + Date.now());
        const moviesData = moviesRes.ok ? await moviesRes.json() : [];
        setApiResult(moviesData);
      } catch (e) {
        setApiResult({ error: "Server error: " + e.message });
      }
    })();
  }, [slug]);

  return apiResult;
}
