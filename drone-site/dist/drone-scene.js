// 輕量 3D 投影：模型與地面都以世界座標繪製，不需要外部套件或地圖金鑰。
const add=(a,b)=>a.map((v,i)=>v+b[i]);
const sub=(a,b)=>a.map((v,i)=>v-b[i]);
const dot=(a,b)=>a.reduce((v,x,i)=>v+x*b[i],0);
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const unit=a=>a.map(x=>x/(Math.hypot(...a)||1));
export const DRONE_STYLES={camera:{label:'空拍機',body:'#dce6f0',accent:'#69e2fc',arm:'#869aaa',size:1},fpv:{label:'穿越機',body:'#283842',accent:'#ff9d55',arm:'#343b46',size:.86},mini:{label:'迷你機',body:'#a4ffdf',accent:'#6af7cc',arm:'#518c83',size:.75}};
export class DroneScene{
 constructor(canvas){this.canvas=canvas;this.ctx=canvas.getContext('2d');this.origin=null;this.lastStats=null;}
 reset(){this.origin=null;}
 render(flight,styleName='camera'){
  const c=this.canvas,ctx=this.ctx;if(!ctx)return;
  const w=c.clientWidth,h=c.clientHeight;if(!w||!h)return;
  const dpr=Math.min(2,window.devicePixelRatio||1);if(c.width!==Math.round(w*dpr)||c.height!==Math.round(h*dpr)){c.width=Math.round(w*dpr);c.height=Math.round(h*dpr);}ctx.setTransform(dpr,0,0,dpr,0,0);
  if(!this.origin)this.origin={lat:flight.lat,lng:flight.lng};
  const east=(flight.lng-this.origin.lng)*111320*Math.cos(flight.lat*Math.PI/180),north=(flight.lat-this.origin.lat)*111320;
  const height=flight.h+.65,center=[east,height,-north];
  const eye=[east+14,18+flight.h*.65,-north+24],target=[east,flight.h*.55,-north];
  const forward=unit(sub(target,eye)),right=unit(cross(forward,[0,1,0])),up=cross(right,forward);
  const focal=Math.min(w,h)*1.35,screenX=w>760?w*.43:w*.39,screenY=h*.55;
  const project=p=>{const rel=sub(p,eye),z=dot(rel,forward);if(z<.15)return null;return [screenX+dot(rel,right)*focal/z,screenY-dot(rel,up)*focal/z,z];};
  const background=ctx.createLinearGradient(0,0,0,h);background.addColorStop(0,'#0b172b');background.addColorStop(.48,'#1c3947');background.addColorStop(1,'#102128');ctx.fillStyle=background;ctx.fillRect(0,0,w,h);
  const line=(points,color,width=1,dash=[])=>{const projected=points.map(project);if(projected.some(p=>!p))return;ctx.beginPath();ctx.moveTo(projected[0][0],projected[0][1]);for(const p of projected.slice(1))ctx.lineTo(p[0],p[1]);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);};
  const baseX=Math.floor(east/5)*5,baseZ=Math.floor(-north/5)*5;
  for(let i=-12;i<=12;i++){const color=i===0?'#487b8688':'#47778255';line([[baseX+i*5,0,baseZ-45],[baseX+i*5,0,baseZ+18]],color);line([[baseX-55,0,baseZ+i*5],[baseX+55,0,baseZ+i*5]],color);}
  const faces=[],groundFaces=[],armFaces=[],bodyFaces=[],detailFaces=[],rotorFaces=[];let activeLayer=faces;
  const queue=(points,fill,stroke='#091721',layer=activeLayer)=>{const ps=points.map(project);if(ps.some(p=>!p))return;layer.push({ps,fill,stroke,z:ps.reduce((v,p)=>v+p[2],0)/ps.length});};
  const paint=layer=>{layer.sort((a,b)=>b.z-a.z);for(const face of layer){ctx.beginPath();face.ps.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=face.fill;ctx.fill();ctx.strokeStyle=face.stroke;ctx.lineWidth=1;ctx.stroke();}};
  // 起降區固定在地面，移動時不會跟隨無人機。
  const circle=(origin,r,steps=36)=>Array.from({length:steps},(_,i)=>[origin[0]+Math.cos(i/steps*Math.PI*2)*r,origin[1],origin[2]+Math.sin(i/steps*Math.PI*2)*r]);
  queue(circle([0,.01,0],5),'#1a3439','#6af7cc',groundFaces);
  queue(circle([east,.035,-north],Math.max(1.8,3-flight.h*.035)),`rgba(0,0,0,${Math.max(.12,.45-flight.h*.012)})`,'transparent',groundFaces);
  // 地面永遠在機體下方；用同一個平均深度排序會讓起降區蓋住遠側旋翼。
  paint(groundFaces);
  line([[-2,.025,-2],[-2,.025,2]],'#6af7cc',3);line([[2,.025,-2],[2,.025,2]],'#6af7cc',3);line([[-2,.025,0],[2,.025,0]],'#6af7cc',3);
  if(flight.h>1)line([[east,.04,-north],center],'#96ffe466',1,[4,6]);
  const style=DRONE_STYLES[styleName]||DRONE_STYLES.camera,yaw=flight.heading*Math.PI/180;
  const pitch=Math.max(-.18,Math.min(.18,flight.vy*.008)),roll=Math.max(-.18,Math.min(.18,-flight.vx*.008));
  const transform=p=>{let [x,y,z]=p.map(v=>v*style.size);const py=y*Math.cos(pitch)-z*Math.sin(pitch),pz=y*Math.sin(pitch)+z*Math.cos(pitch);y=py;z=pz;const rx=x*Math.cos(roll)-y*Math.sin(roll),ry=x*Math.sin(roll)+y*Math.cos(roll);x=rx;y=ry;return add(center,[x*Math.cos(yaw)-z*Math.sin(yaw),y,x*Math.sin(yaw)+z*Math.cos(yaw)]);};
  const mesh=(points,color,stroke)=>queue(points.map(transform),color,stroke);
  const segment=(points,color,width=2)=>line(points.map(transform),color,width);
  const box=(pos,size,color)=>{const [x,y,z]=pos,[a,b,d]=size.map(v=>v/2),points=[[-a,-b,-d],[a,-b,-d],[a,b,-d],[-a,b,-d],[-a,-b,d],[a,-b,d],[a,b,d],[-a,b,d]].map(v=>add(v,[x,y,z]));for(const face of [[0,1,2,3],[4,7,6,5],[0,4,5,1],[3,2,6,7],[1,5,6,2],[0,3,7,4]])mesh(face.map(i=>points[i]),color);};
  // 先畫機臂，再畫機身遮住插入機身內的接合端，避免各零件平均排序造成穿插。
  activeLayer=armFaces;
  // 四支機臂與四個獨立旋翼。
  for(const x of [-2,2])for(const z of [-2,2]){
   const direction=unit([x,0,z]),perpendicular=[-direction[2]*.2,0,direction[0]*.2],inner=[x*.30,.02,z*.30],outer=[x*.98,.02,z*.98];
   mesh([add(inner,perpendicular),add(outer,perpendicular),sub(outer,perpendicular),sub(inner,perpendicular)],style.arm);
   activeLayer=rotorFaces;box([x,.05,z],[.42,.42,.42],style.accent);
   const spinning=flight.mode!=='grounded',angle=spinning?flight.time*52*(x*z>0?1:-1):.4;
   if(styleName==='mini')segment([...circle([x,.35,z],1.13,24),[x+1.13,.35,z]],style.accent,2);
   if(spinning)mesh(circle([x,.35,z],1.03,24),'#c8fff126','transparent');
   const a=[Math.cos(angle)*1.05,0,Math.sin(angle)*1.05],b=[-Math.sin(angle)*.13,0,Math.cos(angle)*.13],origin=[x,.4,z];
   mesh([add(add(origin,a),b),sub(add(origin,a),b),sub(sub(origin,a),b),add(sub(origin,a),b)],'#e6eff4');
  }
  activeLayer=bodyFaces;
  box([0,0,0],styleName==='fpv'?[1.1,.4,1.4]:[1.4,.48,1.8],style.body);
  activeLayer=detailFaces;box([0,.29,0],[.7,.15,1.05],style.accent);
  activeLayer=bodyFaces;
  if(styleName==='camera'){box([0,-.35,-.9],[.55,.45,.5],'#18242f');box([0,-.35,-1.18],[.26,.26,.04],'#5ebfee');for(const x of [-.85,.85]){segment([[x,-.1,-.5],[x,-.6,-.5],[x,-.6,.7]],'#dae4ec',3);}}
  if(styleName==='fpv'){box([0,.16,-.9],[.5,.42,.4],'#253d47');box([0,.16,-1.13],[.25,.25,.1],style.accent);segment([[0,.25,.7],[0,.8,1]],style.accent,3);}
  // 顏色標記機頭，方便辨識朝向。
  mesh([[-.4,.27,-.6],[.4,.27,-.6],[0,.27,-1.12]],style.accent);
  paint(armFaces);paint(bodyFaces);paint(detailFaces);paint(rotorFaces);paint(faces);
  const projected=project(center);this.lastStats={height:flight.h,style:styleName,rotors:4,screen:projected?.slice(0,2),world:[east,flight.h,-north]};
  if(projected){ctx.font='14px system-ui';ctx.fillStyle='#d8fff1';ctx.textAlign='center';ctx.fillText(`${style.label} · ${flight.h.toFixed(1)} m`,projected[0],projected[1]-70);}
  c.dataset.height=flight.h.toFixed(2);c.dataset.style=styleName;
 }
}
