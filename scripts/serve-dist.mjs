import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname } from 'node:path';
import { spawn } from 'node:child_process';
const DIST='dist', PORT=Number(process.argv[2]||8868), API='https://zovex.duckdns.org';
// הבנייה הרגילה יוצאת עם base=/zovex/. בלי חיתוך הקידומת הנכסים
// חוזרים כ-HTML, הדפדפן מסרב לטעון אותם, והבדיקה רואה דף ריק.
const { readFile: _rf } = await import('node:fs/promises');
const BASE = await _rf(join(DIST, 'index.html'), 'utf8')
  .then(h => (h.match(/src="(\/[^"]*?)assets\//) || [, '/'])[1]).catch(() => '/');
export const base = BASE;
const T={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.ico':'image/x-icon','.webp':'image/webp'};
createServer(async(req,res)=>{
 let path=decodeURIComponent(req.url.split('?')[0]);
 if (BASE !== '/' && path.startsWith(BASE)) path = '/' + path.slice(BASE.length);
 if (/^\/(content|feedback|api|movies\.json)/.test(path)) {
   try {
     const buf = await new Promise((ok,bad)=>{const c=spawn('curl',['-s','--compressed','-m','180',API+req.url]);const k=[];c.stdout.on('data',d=>k.push(d));c.on('close',x=>x===0?ok(Buffer.concat(k)):bad(new Error('curl')));});
     res.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Content-Length':String(buf.length)});
     return res.end(buf);
   } catch { res.writeHead(502); return res.end('{}'); }
 }
 let p=join(DIST,path);
 try{if((await stat(p)).isDirectory())p=join(p,'index.html');}catch{p=join(DIST,'index.html');}
 try{const b=await readFile(p);res.writeHead(200,{'Content-Type':T[extname(p)]||'application/octet-stream'});res.end(b);}
 catch{res.writeHead(404);res.end('x');}
}).listen(PORT, ()=>console.log('http://127.0.0.1:'+PORT+BASE));
