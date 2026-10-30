"""A self-contained offline map viewer with representative spectral previews."""
import json


def write_report(path, data):
    # Escape '<' so sample labels/metadata can never end the JSON script block.
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    path.write_text(HTML.replace("__DATA__", payload), encoding="utf-8")


HTML = r'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raman scan report</title>
<style>
:root{font-family:system-ui,sans-serif;color:#172d35;background:#eef3f2}*{box-sizing:border-box}body{max-width:1250px;margin:auto;padding:32px}h1{font-size:30px;letter-spacing:-1px;margin:8px 0}p{line-height:1.5}.eyebrow{text-transform:uppercase;letter-spacing:2px;color:#536b71;font-size:12px}.badge{display:inline-block;background:#e5f4d0;padding:5px 10px;border-radius:5px;font-size:13px}.stats{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.stat{background:white;padding:18px;min-width:170px;flex:1;border:1px solid #d6e0df;border-radius:9px}.stat strong{display:block;font-size:24px;margin:5px 0}.stat span{font-size:13px;color:#536b71}.panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}.panel{background:white;border:1px solid #d6e0df;border-radius:9px;padding:20px;min-width:0}h2{font-size:18px;margin:0 0 12px}canvas{width:100%;height:auto;display:block}button,select{padding:8px;border:1px solid #c9d6d4;border-radius:5px;background:white;color:inherit}button{cursor:pointer}#detail,#range,.muted{font-size:13px;color:#536b71}.scale{height:12px;background:linear-gradient(90deg,hsl(220,70%,47%),hsl(110,70%,47%),hsl(0,70%,47%));margin-top:8px;border-radius:3px}.legend{display:flex;justify-content:space-between;font-size:12px;margin-top:5px}.notice{background:#f9f1d8;padding:12px;border-radius:6px}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.footer{font-size:12px;color:#536b71;overflow-wrap:anywhere;margin-top:24px}@media(max-width:800px){.panels{grid-template-columns:1fr}body{padding:18px}}
</style>
<div class="eyebrow">Spatial spectroscopy</div><h1>Raman scan report</h1><span id="badge" class="badge"></span>
<p id="subtitle"></p><p id="notice" class="notice" hidden>Simulated data. No printer motion or laser emission occurred. This map demonstrates the pipeline.</p>
<div class="stats"><div class="stat"><span>Recorded positions</span><strong id="count"></strong></div><div class="stat"><span>Valid band measurements</span><strong id="valid"></strong></div><div class="stat"><span>Raman band (cm⁻¹)</span><strong id="band"></strong></div><div class="stat"><span>Acquisition state</span><strong id="state"></strong></div></div>
<div class="panels"><section class="panel"><h2>Spatial band area</h2><p class="muted">Click a recorded position. Gray cells are missing or flagged. Axes show sample coordinates in mm.</p><canvas id="map" width="620" height="600" aria-label="Spatial Raman band area map"></canvas><div class="scale"></div><div class="legend"><span id="min"></span><span>Band area · counts × cm⁻¹</span><span id="max"></span></div></section>
<section class="panel"><h2>Spectrum at selected position</h2><div class="controls"><label>Signal <select id="signal"><option value="corrected">Dark corrected</option><option value="raw">Raw detector counts</option></select></label><button id="download">Download selected spectrum</button></div><p id="detail">Select a position on the map.</p><canvas id="spectrum" width="620" height="520" aria-label="Selected spectrum"></canvas><p id="range"></p><p class="muted" id="previewNote"></p></section></div>
<p class="muted" id="method"></p><p class="muted">Raw spectra, per-session dark references, coordinates, configuration, and events are stored in run.sqlite. Values are not normalized for exposure or laser power. Maps show spectral features; chemical identification requires validated references.</p><p class="footer" id="hash"></p>
<script id="data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent),s=data.summary,$=id=>document.getElementById(id);
$('badge').textContent=s.mode.toUpperCase();$('notice').hidden=s.mode!=='simulation';$('subtitle').textContent='Sample: '+s.sample_id;
if(s.mode==='imported'){$('notice').hidden=false;$('notice').textContent='Imported spectra. Coordinate association and acquisition settings are user supplied. Timestamps are file modification times; saturation is unverified unless an ADC threshold was configured.';}
$('count').textContent=s.saved_points.toLocaleString();$('valid').textContent=s.valid_points.toLocaleString();$('band').textContent=s.analysis.band_cm1.join('–');$('state').textContent=s.state;
$('method').textContent='Band processing: dark subtraction; '+(s.analysis.baseline==='linear_endpoints'?'a straight baseline joins the two band endpoints before integration.':'no baseline subtraction before integration.');
$('hash').textContent='Configuration SHA-256: '+s.config_sha256;
$('previewNote').textContent='This report embeds '+s.preview_spectra+' representative spectra (up to 256). Every recorded spectrum remains available in run.sqlite and the full CSV export.';
const valid=data.points.filter(p=>p.area!==null);let low=Infinity,high=-Infinity;for(const p of valid){low=Math.min(low,p.area);high=Math.max(high,p.area);}if(!valid.length){low=0;high=0;}
$('min').textContent=low.toPrecision(4);$('max').textContent=high.toPrecision(4);
const map=$('map'),ctx=map.getContext('2d'),pad=65,W=490,H=465;
const gx=data.grid.x_mm,gy=data.grid.y_mm,px=data.grid.pitch_mm[0],py=data.grid.pitch_mm[1];
const xmin=gx[0]-px/2,xmax=gx[1]+px/2,ymin=gy[0]-py/2,ymax=gy[1]+py/2;
const mx=x=>pad+(x-xmin)/(xmax-xmin)*W,my=y=>pad+H-(y-ymin)/(ymax-ymin)*H;
const coordMap=new Map(data.points.map(p=>[p.x.toFixed(8)+','+p.y.toFixed(8),p]));
function color(v){if(v===null)return '#8a979b';let t=high===low?0.5:(v-low)/(high-low);return 'hsl('+(220*(1-t))+',70%,47%)';}
let selected=null;
function drawMap(){ctx.clearRect(0,0,620,600);ctx.fillStyle='#eef1f1';ctx.fillRect(pad,pad,W,H);
const xs=[...new Set(data.points.map(p=>p.x))].sort((a,b)=>a-b),ys=[...new Set(data.points.map(p=>p.y))].sort((a,b)=>a-b);
for(const p of data.points){let xi=xs.indexOf(p.x),yi=ys.indexOf(p.y);let left=xi>0?(p.x+xs[xi-1])/2:xmin,right=xi<xs.length-1?(p.x+xs[xi+1])/2:xmax;
let bottom=yi>0?(p.y+ys[yi-1])/2:ymin,top=yi<ys.length-1?(p.y+ys[yi+1])/2:ymax;
// Cap cells at a pitch so gaps in a partial scan stay visibly missing.
left=Math.max(left,p.x-px/2);right=Math.min(right,p.x+px/2);bottom=Math.max(bottom,p.y-py/2);top=Math.min(top,p.y+py/2);
ctx.fillStyle=color(p.area);ctx.fillRect(mx(left),my(top),mx(right)-mx(left)+0.5,my(bottom)-my(top)+0.5);}
ctx.strokeStyle='#536b71';ctx.strokeRect(pad,pad,W,H);ctx.fillStyle='#536b71';ctx.font='13px system-ui';ctx.textAlign='center';
for(let i=0;i<=4;i++){let x=gx[0]+(gx[1]-gx[0])*i/4,y=gy[0]+(gy[1]-gy[0])*i/4;ctx.fillText(x.toFixed(1),mx(x),pad+H+23);ctx.fillText(y.toFixed(1),pad-31,my(y)+4);}
ctx.fillText('Sample X (mm)',pad+W/2,580);ctx.save();ctx.translate(15,pad+H/2);ctx.rotate(-Math.PI/2);ctx.fillText('Sample Y (mm)',0,0);ctx.restore();
if(selected){ctx.beginPath();ctx.arc(mx(selected.x),my(selected.y),7,0,Math.PI*2);ctx.strokeStyle='#fff';ctx.lineWidth=3;ctx.stroke();ctx.lineWidth=1;}}
function selectPoint(p){selected=p;drawMap();let spec=data.spectra[String(p.index)];$('detail').textContent='Point '+p.index+' · X '+p.x+' mm · Y '+p.y+' mm'+(p.flags.length?' · '+p.flags.join(', '):'');
let c=$('spectrum').getContext('2d');c.clearRect(0,0,620,520);$('download').disabled=!spec;
if(!spec){$('range').textContent='This point is stored in run.sqlite. Use the export command for the full spectral dataset.';return;}
const xs=spec.shift,ys=spec[$('signal').value];let ymin=Infinity,ymax=-Infinity;for(let y of ys){ymin=Math.min(ymin,y);ymax=Math.max(ymax,y);}let dy=Math.max(ymax-ymin,1);ymin-=dy*0.07;ymax+=dy*0.07;
const x=x=>70+(x-xs[0])/(xs[xs.length-1]-xs[0])*520,y=v=>440-(v-ymin)/(ymax-ymin)*380;
c.fillStyle='#ebf3df';c.fillRect(x(Math.max(xs[0],s.analysis.band_cm1[0])),60,x(Math.min(xs[xs.length-1],s.analysis.band_cm1[1]))-x(Math.max(xs[0],s.analysis.band_cm1[0])),380);
c.beginPath();xs.forEach((v,i)=>i?c.lineTo(x(v),y(ys[i])):c.moveTo(x(v),y(ys[i])));c.strokeStyle='#147d78';c.lineWidth=1.6;c.stroke();c.lineWidth=1;c.strokeStyle='#aebfbd';c.strokeRect(70,60,520,380);
c.fillStyle='#536b71';c.font='13px system-ui';c.textAlign='center';for(let i=0;i<=4;i++){let value=xs[0]+(xs[xs.length-1]-xs[0])*i/4;c.fillText(value.toFixed(0),x(value),464);let val=ymin+(ymax-ymin)*i/4;c.textAlign='right';c.fillText(val.toFixed(0),62,y(val)+4);c.textAlign='center';}c.fillText('Raman shift (cm⁻¹)',330,500);c.save();c.translate(15,250);c.rotate(-Math.PI/2);c.fillText('Detector counts',0,0);c.restore();
$('range').textContent='Shaded region: integration band. The displayed dark-corrected line retains its background; endpoint baseline correction applies only to the band area.';}
map.addEventListener('click',event=>{let rect=map.getBoundingClientRect(),cx=(event.clientX-rect.left)*620/rect.width,cy=(event.clientY-rect.top)*600/rect.height;
if(cx<pad||cx>pad+W||cy<pad||cy>pad+H)return;let x=xmin+(cx-pad)/W*(xmax-xmin),y=ymin+(pad+H-cy)/H*(ymax-ymin);let best=null,d=Infinity;
for(let p of data.points){let distance=((x-p.x)/px)**2+((y-p.y)/py)**2;if(distance<d){d=distance;best=p;}}if(best&&Math.abs(x-best.x)<=px/2&&Math.abs(y-best.y)<=py/2)selectPoint(best);});
$('signal').addEventListener('change',()=>{if(selected)selectPoint(selected);});
$('download').addEventListener('click',()=>{if(!selected)return;let spec=data.spectra[String(selected.index)];if(!spec)return;let lines=['raman_shift_cm1,raw_counts,dark_corrected_counts'];spec.shift.forEach((x,i)=>lines.push([x,spec.raw[i],spec.corrected[i]].join(',')));let url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/csv'}));let a=document.createElement('a');a.href=url;a.download='spectrum-'+selected.index+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
drawMap();if(data.points.length)selectPoint(data.points.find(p=>data.spectra[String(p.index)])||data.points[0]);else $('download').disabled=true;
</script></html>'''
