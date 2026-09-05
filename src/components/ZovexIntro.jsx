import { useRef, useEffect } from "react";

// ── פתיח קולנועי ל-ZOVEX (זהה לאפליקציה) ────────────────────────────────────
// אותה אנימציית קנבס בדיוק כמו באפליקציה (zovex-android/src/components/ZovexIntro.js):
// אלפי חלקיקי אור מתכנסים ל-"ZOVEX", התלקחות + נצנוץ, "הבידור מתחיל" עולה, ואז
// נמוג. מוצג ב-iframe (srcDoc) כדי לשמור על אותו HTML/Canvas בדיוק בשני הצדדים
// במקום שתי מימושים שיכולים להתפצל זה מזה — זה בדיוק מה שקרה כשהאתר איבד את
// הפתיח בזמן שהאפליקציה שמרה עליו. משחק פעם אחת, אפשר לגעת כדי לדלג.
const INTRO_HTML = `<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;background:#000}
#root{position:fixed;inset:0;overflow:hidden;
  background:radial-gradient(circle at 50% 44%,#210608 0%,#0d0509 55%,#000 100%);
  opacity:1;transition:opacity .65s ease}
#root.fade{opacity:0}
canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
#vig{position:absolute;inset:0;z-index:3;pointer-events:none;
  background:radial-gradient(ellipse 75% 60% at 50% 46%,transparent 55%,rgba(0,0,0,.55) 100%)}
#tag{position:absolute;left:0;right:0;z-index:4;text-align:center;bottom:calc(50% - 15vh);
  font-family:Arial;font-size:clamp(12px,3.2vw,18px);font-weight:600;color:#ffdccb;direction:rtl;
  letter-spacing:.55em;padding-inline-start:.55em;text-shadow:0 0 20px rgba(255,50,40,.55);
  opacity:0;transform:translateY(12px);
  transition:opacity .8s ease,transform .8s cubic-bezier(.2,.8,.3,1),letter-spacing 1.4s ease}
#tag.show{opacity:1;transform:none;letter-spacing:.36em}
#skip{position:absolute;bottom:22px;left:50%;transform:translateX(-50%);z-index:5;color:#fff;
  font-family:Arial;font-size:13px;font-weight:700;opacity:.7;background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.18);border-radius:999px;padding:8px 18px;direction:rtl}
</style></head><body>
<div id="root">
  <canvas id="cv"></canvas>
  <div id="vig"></div>
  <div id="tag" dir="rtl">הבידור מתחיל</div>
  <div id="skip" dir="rtl">דלג ✕</div>
</div>
<script>
(function(){
  var c=document.getElementById('cv');
  var rootEl=document.getElementById('root');
  var tagEl=document.getElementById('tag');
  var x=c.getContext('2d');
  var reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var DPR=Math.min(window.devicePixelRatio||1,2);
  var WORD='ZOVEX';
  var COOL=['#ff1f3d','#ff3d00','#ff7a00','#ffb020','#ffe066'];
  var W,H,CX,CY,fontSize=0,wordBox=null;
  var particles=[],embers=[],sparks=[],ring=null,flash=0,ignited=false;
  var raf=0,T0=0,IGNITE=0;
  var timers=[];
  var doneFlag=false;
  function post(m){try{window.parent!==window&&window.parent.postMessage(m,'*');}catch(e){}}
  function finish(){ if(doneFlag)return; doneFlag=true; rootEl.classList.add('fade');
    setTimeout(function(){post('introDone');},650); }
  rootEl.addEventListener('click',finish);

  var rnd=function(a,b){return a+Math.random()*(b-a);};
  var ease=function(t){return 1-Math.pow(1-t,3);};
  var ASM_START=620,ASM_DUR=780;

  function buildTargets(){
    fontSize=Math.min(W*0.165,H*0.30);
    var setFont=function(s){x.font='900 '+s+'px "Arial Black","Arial Narrow",Arial,sans-serif';};
    setFont(fontSize);
    var w=x.measureText(WORD).width;
    if(w>W*0.84){fontSize*=(W*0.84)/w;setFont(fontSize);w=x.measureText(WORD).width;}
    var left=CX-w/2;
    wordBox={left:left,top:CY-fontSize*0.65,w:w,h:fontSize*1.15,right:left+w};
    var oc=document.createElement('canvas');oc.width=W;oc.height=H;
    var ox=oc.getContext('2d');
    ox.font='900 '+fontSize+'px "Arial Black","Arial Narrow",Arial,sans-serif';
    ox.textBaseline='middle';ox.textAlign='left';ox.fillStyle='#fff';
    ox.fillText(WORD,left,CY);
    var img=ox.getImageData(0,0,W,H).data;
    var step=Math.max(3,Math.round(4*DPR));
    var targets=[];
    for(var yy=0;yy<H;yy+=step)for(var xx=0;xx<W;xx+=step)
      if(img[(yy*W+xx)*4+3]>130){
        var nx=(xx-left)/w;
        targets.push({x:xx,y:yy,nx:nx,col:COOL[Math.min(COOL.length-1,((nx*3.2+Math.random()*1.2)|0))]});
      }
    particles=targets.map(function(t){
      var ang=Math.random()*Math.PI*2,dist=Math.max(W,H)*(0.35+Math.random()*0.5);
      return {tx:t.x,ty:t.y,col:t.col,sx:CX+Math.cos(ang)*dist,sy:CY+Math.sin(ang)*dist,px:0,py:0,delay:t.nx*620,r:(0.8+Math.random()*1.3)*DPR};
    });
    var md=0;for(var i=0;i<particles.length;i++)if(particles[i].delay>md)md=particles[i].delay;
    IGNITE=ASM_START+md+ASM_DUR;
  }
  function fit(){
    W=c.width=Math.floor(window.innerWidth*DPR);
    H=c.height=Math.floor(window.innerHeight*DPR);
    c.style.width=window.innerWidth+'px';c.style.height=window.innerHeight+'px';
    CX=W/2;CY=H*0.44;
    buildTargets();
  }
  function ignite(){
    ring={r:0,life:1};flash=1;
    for(var i=0;i<70;i++){var a=rnd(0,Math.PI*2),sp=rnd(4,15)*DPR;
      sparks.push({x:CX,y:CY,vx:Math.cos(a)*sp,vy:Math.sin(a)*sp,r:rnd(1.2,3.4)*DPR,age:0,life:rnd(40,75),col:COOL[(Math.random()*COOL.length)|0],g:rnd(0.05,0.13)*DPR});}
  }
  function drawWord(alpha,glow){
    x.save();x.globalAlpha=alpha;
    x.font='900 '+fontSize+'px "Arial Black","Arial Narrow",Arial,sans-serif';
    x.textBaseline='middle';x.textAlign='left';
    var g=x.createLinearGradient(0,wordBox.top,0,wordBox.top+wordBox.h);
    g.addColorStop(0,'#ff5c3c');g.addColorStop(0.3,'#ff1f2e');g.addColorStop(0.62,'#e50914');g.addColorStop(1,'#8a0510');
    x.shadowColor='rgba(255,35,30,'+(0.55*glow)+')';x.shadowBlur=38*glow*DPR;
    x.fillStyle=g;x.fillText(WORD,wordBox.left,CY);x.shadowBlur=0;x.restore();
  }
  function drawShimmer(alpha,pos){
    x.save();x.globalCompositeOperation='source-atop';x.globalAlpha=alpha;
    var sw=wordBox.w*0.28,sx=wordBox.left-sw+(wordBox.w+sw*2)*pos;
    var g=x.createLinearGradient(sx,0,sx+sw,0);
    g.addColorStop(0,'rgba(255,240,190,0)');g.addColorStop(0.5,'rgba(255,245,210,.9)');g.addColorStop(1,'rgba(255,240,190,0)');
    x.fillStyle=g;x.fillRect(wordBox.left-4,wordBox.top-4,wordBox.w+8,wordBox.h+8);x.restore();
  }
  function frame(now){
    if(!T0)T0=now;var t=now-T0;
    x.clearRect(0,0,W,H);x.globalCompositeOperation='lighter';
    var glowPhase=Math.min(1,t/IGNITE);
    var gr=x.createRadialGradient(CX,CY,0,CX,CY,Math.max(W,H)*0.5);
    var gi=t<IGNITE?0.12+0.18*glowPhase:0.30;
    gr.addColorStop(0,'rgba(255,35,30,'+gi+')');gr.addColorStop(0.4,'rgba(170,15,15,'+(gi*0.4)+')');gr.addColorStop(1,'rgba(0,0,0,0)');
    x.fillStyle=gr;x.fillRect(0,0,W,H);
    if(!reduce&&Math.random()<0.5)embers.push({x:rnd(0,W),y:H+10,vx:rnd(-0.15,0.15)*DPR,vy:-rnd(0.3,1.1)*DPR,r:rnd(0.7,2)*DPR,a:rnd(0.2,0.6),col:COOL[(Math.random()*4)|0]});
    for(var e=embers.length-1;e>=0;e--){var m=embers[e];m.x+=m.vx;m.y+=m.vy;m.a-=0.004;
      if(m.a<=0||m.y<-10){embers.splice(e,1);continue;}x.globalAlpha=m.a;x.fillStyle=m.col;x.beginPath();x.arc(m.x,m.y,m.r,0,7);x.fill();}
    x.globalAlpha=1;
    if(reduce){drawWord(1,1);raf=requestAnimationFrame(frame);return;}
    if(t<IGNITE){
      for(var i=0;i<particles.length;i++){var p=particles[i];
        var lt=(t-ASM_START-p.delay)/ASM_DUR;if(lt<=0)continue;if(lt>1)lt=1;var k=ease(lt);
        var cx=p.sx+(p.tx-p.sx)*k,cy=p.sy+(p.ty-p.sy)*k;
        x.globalAlpha=Math.min(1,lt*1.6);x.strokeStyle=p.col;x.lineWidth=p.r;
        if(p.px){x.beginPath();x.moveTo(p.px,p.py);x.lineTo(cx,cy);x.stroke();}
        p.px=cx;p.py=cy;
      }
      var pre=(t-(IGNITE-260))/260;if(pre>0)drawWord(Math.min(1,pre),Math.min(1,pre));
      x.globalAlpha=1;
    }else{
      var since=t-IGNITE;
      drawWord(1,0.75+0.25*Math.max(0,1-since/500));
      var shPos=(since-150)/1500;if(shPos>0&&shPos<1.15)drawShimmer(0.9,shPos%1.15);
    }
    if(t>=IGNITE&&!ignited){ignited=true;ignite();}
    if(flash>0){x.globalAlpha=flash*0.5;x.fillStyle='#fff';x.fillRect(0,0,W,H);x.globalAlpha=1;flash-=0.05;if(flash<0)flash=0;}
    if(ring){ring.r+=Math.max(W,H)*0.012;ring.life-=0.03;
      if(ring.life<=0)ring=null;else{x.globalAlpha=ring.life*0.8;x.strokeStyle='#ffdca0';x.lineWidth=3*DPR;x.beginPath();x.arc(CX,CY,ring.r,0,7);x.stroke();
        x.globalAlpha=ring.life*0.35;x.lineWidth=10*DPR;x.beginPath();x.arc(CX,CY,ring.r,0,7);x.stroke();x.globalAlpha=1;}}
    for(var s=sparks.length-1;s>=0;s--){var q=sparks[s];q.age++;q.vy+=q.g;q.x+=q.vx;q.y+=q.vy;q.vx*=0.99;
      var qa=1-q.age/q.life;if(qa<=0){sparks.splice(s,1);continue;}x.globalAlpha=qa;x.fillStyle=q.col;x.beginPath();x.arc(q.x,q.y,q.r*qa,0,7);x.fill();}
    x.globalAlpha=1;x.globalCompositeOperation='source-over';
    raf=requestAnimationFrame(frame);
  }
  fit();
  window.addEventListener('resize',function(){fit();});
  raf=requestAnimationFrame(frame);
  if(reduce){tagEl.classList.add('show');timers.push(setTimeout(finish,1400));}
  else{
    timers.push(setTimeout(function(){tagEl.classList.add('show');},IGNITE+520));
    timers.push(setTimeout(finish,IGNITE+1900));
  }
})();
</script>
</body></html>`;

export default function ZovexIntro({ onDone }) {
  const done = useRef(false);
  const finish = () => {
    if (done.current) return;
    done.current = true;
    onDone && onDone();
  };

  useEffect(() => {
    const onMessage = (e) => { if (e.data === "introDone") finish(); };
    window.addEventListener("message", onMessage);
    // רשת ביטחון: אם מסיבה כלשהי ההודעה לא מגיעה, ממשיכים אחרי 7 שניות.
    const timer = setTimeout(finish, 7000);
    return () => { window.removeEventListener("message", onMessage); clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <iframe
      title="ZOVEX"
      srcDoc={INTRO_HTML}
      style={{
        position: "fixed", inset: 0, zIndex: 9999, border: "none",
        width: "100%", height: "100%", background: "#000",
      }}
    />
  );
}
