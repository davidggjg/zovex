// מרכיב את הנגן האמיתי של האתר לבדו, כדי שאפשר יהיה ללחוץ על הכפתורים
// שלו בדפדפן אמיתי בלי לנווט בכל האתר ובלי קטלוג.
import React from "react";
import { createRoot } from "react-dom/client";
import CustomVideoPlayer from "../../src/components/home/CustomVideoPlayer.jsx";

const movie = {
  id: "harness-1",
  title: "בדיקה",
  type: "direct",
  video_url: window.__SRC || (location.origin + "/scripts/iostest/sample.webm"),
};
createRoot(document.getElementById("root")).render(
  <CustomVideoPlayer movie={movie} onClose={() => {}} />
);
