import { useState, useEffect } from "react";
import { lsJson, lsSet } from "./helpers";

// קטגוריות — משולבות מ-localStorage ומהקטגוריות שמופיעות בפועל בתכנים
export function useCategories(movies) {
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    if (!movies.length) return;
    const saved = lsJson("zovex_cats");
    const fromMovies = [...new Set(movies.map(m => m.category).filter(Boolean))];
    if (saved?.length) {
      const merged = [...saved, ...fromMovies.filter(c => !saved.includes(c))];
      setCategories(merged); lsSet("zovex_cats", JSON.stringify(merged)); return;
    }
    setCategories(fromMovies); lsSet("zovex_cats", JSON.stringify(fromMovies));
  }, [movies]);

  const saveCats = (c) => { setCategories(c); lsSet("zovex_cats", JSON.stringify(c)); };

  return [categories, saveCats];
}
