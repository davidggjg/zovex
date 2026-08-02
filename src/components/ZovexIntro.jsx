import { useEffect, useRef, useState } from "react";

// ── פתיח קולנועי ל-ZOVEX ──────────────────────────────────────────────────────
// אלפי חלקיקי אור מתכנסים ומתגבשים לצורת "ZOVEX", ואז בום (גל הדף + הבזק +
// נצנוץ זהב), הטאגליין עולה, וכל המסך נמוג וחושף את האתר. משחק פעם אחת ואז נעלם.
// הכל בקנבס אחד (מהיר גם בטלפון). מכבד prefers-reduced-motion.
export default function ZovexIntro({ onDone }) {
  const canvasRef = useRef(null);
  const [fading, setFading] = useState(false);
  const [tagShown, setTagShown] = useState(false);
  const doneRef = useRef(false);

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setFading(true);
    setTimeout(() => onDone && onDone(), 650);
  };

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const x = c.getContext("2d");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    const WORD = "ZOVEX";
    const COOL = ["#ff3d00", "#ff7a00", "#ffb020", "#ffd000", "#fff0b0"];
    let W, H, CX, CY, fontSize = 0, wordBox = null;
    let particles = [], embers = [], sparks = [], ring = null, flash = 0, ignited = false;
    let raf = 0, T0 = 0, IGNITE = 0;
    const timers = [];

    const rnd = (a, b) => a + Math.random() * (b - a);
    const ease = (t) => 1 - Math.pow(1 - t, 3);
    const ASM_START = 620, ASM_DUR = 780;

    function buildTargets() {
      fontSize = Math.min(W * 0.165, H * 0.30);
      const setFont = (s) => { x.font = '900 ' + s + 'px "Arial Black","Arial Narrow",Arial,sans-serif'; };
      setFont(fontSize);
      let w = x.measureText(WORD).width;
      if (w > W * 0.84) { fontSize *= (W * 0.84) / w; setFont(fontSize); w = x.measureText(WORD).width; }
      const left = CX - w / 2;
      wordBox = { left, top: CY - fontSize * 0.65, w, h: fontSize * 1.15, right: left + w };
      const oc = document.createElement("canvas"); oc.width = W; oc.height = H;
      const ox = oc.getContext("2d");
      ox.font = '900 ' + fontSize + 'px "Arial Black","Arial Narrow",Arial,sans-serif';
      ox.textBaseline = "middle"; ox.textAlign = "left"; ox.fillStyle = "#fff";
      ox.fillText(WORD, left, CY);
      const img = ox.getImageData(0, 0, W, H).data;
      const step = Math.max(3, Math.round(4 * DPR));
      const targets = [];
      for (let yy = 0; yy < H; yy += step)
        for (let xx = 0; xx < W; xx += step)
          if (img[(yy * W + xx) * 4 + 3] > 130) {
            const nx = (xx - left) / w;
            targets.push({ x: xx, y: yy, nx, col: COOL[Math.min(COOL.length - 1, ((nx * 3.2 + Math.random() * 1.2) | 0))] });
          }
      particles = targets.map((t) => {
        const ang = Math.random() * Math.PI * 2, dist = Math.max(W, H) * (0.35 + Math.random() * 0.5);
        return { tx: t.x, ty: t.y, col: t.col, sx: CX + Math.cos(ang) * dist, sy: CY + Math.sin(ang) * dist, px: 0, py: 0, delay: t.nx * 620, r: (0.8 + Math.random() * 1.3) * DPR };
      });
      let md = 0; for (const p of particles) if (p.delay > md) md = p.delay;
      IGNITE = ASM_START + md + ASM_DUR;
    }

    function fit() {
      W = c.width = Math.floor(window.innerWidth * DPR);
      H = c.height = Math.floor(window.innerHeight * DPR);
      c.style.width = window.innerWidth + "px"; c.style.height = window.innerHeight + "px";
      CX = W / 2; CY = H * 0.44;
      buildTargets();
    }

    function ignite() {
      ring = { r: 0, life: 1 }; flash = 1;
      for (let i = 0; i < 70; i++) { const a = rnd(0, Math.PI * 2), sp = rnd(4, 15) * DPR;
        sparks.push({ x: CX, y: CY, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, r: rnd(1.2, 3.4) * DPR, age: 0, life: rnd(40, 75), col: COOL[(Math.random() * COOL.length) | 0], g: rnd(0.05, 0.13) * DPR }); }
    }

    function drawWord(alpha, glow) {
      x.save(); x.globalAlpha = alpha;
      x.font = '900 ' + fontSize + 'px "Arial Black","Arial Narrow",Arial,sans-serif';
      x.textBaseline = "middle"; x.textAlign = "left";
      const g = x.createLinearGradient(0, wordBox.top, 0, wordBox.top + wordBox.h);
      g.addColorStop(0, "#ff7a3c"); g.addColorStop(0.42, "#ff2d16"); g.addColorStop(0.66, "#e50914"); g.addColorStop(1, "#9c040e");
      x.shadowColor = "rgba(255,80,10," + (0.55 * glow) + ")"; x.shadowBlur = 38 * glow * DPR;
      x.fillStyle = g; x.fillText(WORD, wordBox.left, CY); x.shadowBlur = 0; x.restore();
    }
    function drawShimmer(alpha, pos) {
      x.save(); x.globalCompositeOperation = "source-atop"; x.globalAlpha = alpha;
      const sw = wordBox.w * 0.28, sx = wordBox.left - sw + (wordBox.w + sw * 2) * pos;
      const g = x.createLinearGradient(sx, 0, sx + sw, 0);
      g.addColorStop(0, "rgba(255,240,190,0)"); g.addColorStop(0.5, "rgba(255,245,210,.9)"); g.addColorStop(1, "rgba(255,240,190,0)");
      x.fillStyle = g; x.fillRect(wordBox.left - 4, wordBox.top - 4, wordBox.w + 8, wordBox.h + 8); x.restore();
    }

    function frame(now) {
      if (!T0) T0 = now; const t = now - T0;
      x.clearRect(0, 0, W, H); x.globalCompositeOperation = "lighter";
      const glowPhase = Math.min(1, t / IGNITE);
      const gr = x.createRadialGradient(CX, CY, 0, CX, CY, Math.max(W, H) * 0.5);
      const gi = t < IGNITE ? 0.12 + 0.18 * glowPhase : 0.30;
      gr.addColorStop(0, "rgba(255,70,10," + gi + ")"); gr.addColorStop(0.4, "rgba(180,20,10," + (gi * 0.4) + ")"); gr.addColorStop(1, "rgba(0,0,0,0)");
      x.fillStyle = gr; x.fillRect(0, 0, W, H);

      if (!reduce && Math.random() < 0.5) embers.push({ x: rnd(0, W), y: H + 10, vx: rnd(-0.15, 0.15) * DPR, vy: -rnd(0.3, 1.1) * DPR, r: rnd(0.7, 2) * DPR, a: rnd(0.2, 0.6), col: COOL[(Math.random() * 4) | 0] });
      for (let e = embers.length - 1; e >= 0; e--) { const m = embers[e]; m.x += m.vx; m.y += m.vy; m.a -= 0.004;
        if (m.a <= 0 || m.y < -10) { embers.splice(e, 1); continue; } x.globalAlpha = m.a; x.fillStyle = m.col; x.beginPath(); x.arc(m.x, m.y, m.r, 0, 7); x.fill(); }
      x.globalAlpha = 1;

      if (reduce) { drawWord(1, 1); raf = requestAnimationFrame(frame); return; }

      if (t < IGNITE) {
        for (let i = 0; i < particles.length; i++) { const p = particles[i];
          let lt = (t - ASM_START - p.delay) / ASM_DUR; if (lt <= 0) continue; if (lt > 1) lt = 1; const k = ease(lt);
          const cx = p.sx + (p.tx - p.sx) * k, cy = p.sy + (p.ty - p.sy) * k;
          x.globalAlpha = Math.min(1, lt * 1.6); x.strokeStyle = p.col; x.lineWidth = p.r;
          if (p.px) { x.beginPath(); x.moveTo(p.px, p.py); x.lineTo(cx, cy); x.stroke(); }
          p.px = cx; p.py = cy;
        }
        const pre = (t - (IGNITE - 260)) / 260; if (pre > 0) drawWord(Math.min(1, pre), Math.min(1, pre));
        x.globalAlpha = 1;
      } else {
        const since = t - IGNITE;
        drawWord(1, 0.75 + 0.25 * Math.max(0, 1 - since / 500));
        const shPos = (since - 150) / 1500; if (shPos > 0 && shPos < 1.15) drawShimmer(0.9, shPos % 1.15);
      }

      if (t >= IGNITE && !ignited) { ignited = true; ignite(); }
      if (flash > 0) { x.globalAlpha = flash * 0.5; x.fillStyle = "#fff"; x.fillRect(0, 0, W, H); x.globalAlpha = 1; flash -= 0.05; if (flash < 0) flash = 0; }
      if (ring) { ring.r += Math.max(W, H) * 0.012; ring.life -= 0.03;
        if (ring.life <= 0) ring = null; else { x.globalAlpha = ring.life * 0.8; x.strokeStyle = "#ffdca0"; x.lineWidth = 3 * DPR; x.beginPath(); x.arc(CX, CY, ring.r, 0, 7); x.stroke();
          x.globalAlpha = ring.life * 0.35; x.lineWidth = 10 * DPR; x.beginPath(); x.arc(CX, CY, ring.r, 0, 7); x.stroke(); x.globalAlpha = 1; } }
      for (let s = sparks.length - 1; s >= 0; s--) { const q = sparks[s]; q.age++; q.vy += q.g; q.x += q.vx; q.y += q.vy; q.vx *= 0.99;
        const qa = 1 - q.age / q.life; if (qa <= 0) { sparks.splice(s, 1); continue; } x.globalAlpha = qa; x.fillStyle = q.col; x.beginPath(); x.arc(q.x, q.y, q.r * qa, 0, 7); x.fill(); }
      x.globalAlpha = 1; x.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(frame);
    }

    fit();
    const onResize = () => fit();
    window.addEventListener("resize", onResize);
    raf = requestAnimationFrame(frame);

    if (reduce) {
      setTagShown(true);
      timers.push(setTimeout(finish, 1400));
    } else {
      timers.push(setTimeout(() => setTagShown(true), IGNITE + 520));
      timers.push(setTimeout(finish, IGNITE + 1900)); // משחק פעם אחת ואז נמוג
    }

    return () => {
      cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
      window.removeEventListener("resize", onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      onClick={finish}
      role="button"
      aria-label="דלג על הפתיח"
      style={{
        position: "fixed", inset: 0, zIndex: 99999, cursor: "pointer",
        background: "radial-gradient(circle at 50% 44%,#140609 0%,#06070c 55%,#000 100%)",
        opacity: fading ? 0 : 1, transition: "opacity .65s ease",
        overflow: "hidden",
      }}
    >
      <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }} />
      <div style={{
        position: "absolute", inset: 0, zIndex: 3, pointerEvents: "none",
        background: "radial-gradient(ellipse 75% 60% at 50% 46%,transparent 55%,rgba(0,0,0,.55) 100%)",
      }} />
      <div dir="rtl" style={{
        position: "absolute", left: 0, right: 0, zIndex: 4, textAlign: "center",
        bottom: "calc(50% - clamp(90px,15vh,150px))",
        fontSize: "clamp(12px,3.2vw,18px)", fontWeight: 600, color: "#ffd9c4",
        letterSpacing: tagShown ? "0.36em" : "0.55em", paddingInlineStart: "0.55em",
        textShadow: "0 0 20px rgba(255,90,20,.55)",
        opacity: tagShown ? 1 : 0, transform: tagShown ? "none" : "translateY(12px)",
        transition: "opacity .8s ease, transform .8s cubic-bezier(.2,.8,.3,1), letter-spacing 1.4s ease",
      }}>הבידור מתחיל</div>
      <div dir="rtl" style={{
        position: "absolute", bottom: 22, left: "50%", transform: "translateX(-50%)", zIndex: 5,
        color: "#fff", fontSize: 13, fontWeight: 700, opacity: 0.7,
        background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.18)",
        borderRadius: 999, padding: "8px 18px", backdropFilter: "blur(6px)",
      }}>דלג ✕</div>
    </div>
  );
}
