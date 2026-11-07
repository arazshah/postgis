const {chromium}=require('playwright');const fs=require('fs');
(async()=>{const [,,mode,out,...rest]=process.argv;
const b=await chromium.launch({args:['--force-color-profile=srgb']});const p=await b.newPage({viewport:{width:1080,height:1920},deviceScaleFactor:1});
const errs=[];p.on('pageerror',e=>errs.push(e.message));p.on('console',m=>{if(m.type()==='error')errs.push(m.text())});
await p.goto('http://127.0.0.1:8111/stage.html');await p.evaluate(()=>window.setup());
if(mode==='still'){for(const t of rest){await p.evaluate(t=>render(+t),t);await p.screenshot({path:`${out}/t_${(+t).toFixed(2)}.jpg`,type:'jpeg',quality:80});}}
else{const fps=30,dur=+rest[0];fs.mkdirSync(out,{recursive:true});const t0=Date.now();
 for(let i=+(rest[1]||0);i<Math.round(dur*fps);i++){await p.evaluate(t=>render(t),i/fps);await p.screenshot({path:`${out}/f_${String(i).padStart(5,'0')}.jpg`,type:'jpeg',quality:92});
 if(i%150===0)console.log('frame',i,((Date.now()-t0)/1000).toFixed(0)+'s');}}
console.log(errs.length?errs:'no errors');await b.close();})();
