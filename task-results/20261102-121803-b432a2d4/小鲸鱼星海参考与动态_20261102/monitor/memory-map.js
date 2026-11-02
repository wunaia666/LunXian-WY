/* 三维星团只投影已有记忆。关键词关系可追溯，背景星尘不算作记忆。 */
function buildWhaleConstellation(input) {
  const rules=[
    ['声音与语音',['声音','语音','音色','原声','声线','配音','多萝','生日对白']],
    ['电脑与软件',['电脑','桌面','软件','客户端','模拟器','窗口','程序']],
    ['记忆与陪伴',['记忆','上下文','陪伴','称呼','老爸','昵称','小鲸鱼']],
    ['创作与图片',['图片','绘图','画图','插画','作品','创作','动画']],
    ['科学与技术',['数学','物理','科技','人工智能','算法','机器人','模型','开源','芯片','研究']],
    ['生活与心情',['日常','生活','心情','开心','难过','睡觉','晚安','早安','家人','食物']],
    ['新闻与见闻',['新闻','全球','国际','俄罗斯','美国','中国','网友','媒体','亿元']]
  ];
  const fallback={preference:'偏好与约定',event:'共同经历',plan:'未来计划',browse:'浏览见闻'};
  const colors=['#a1c9ff','#f1d29b','#9ddfd1','#e7a6c5','#c0b2ea','#a9d4a2','#8fbad5'];
  const memories=(input.nodes||[]).filter(n=>n.type==='memory').map(n=>({...n}));
  const topics=new Map();for(const n of memories)if(n.topic)topics.set(n.topic,(topics.get(n.topic)||0)+1);
  const groups=new Map(),links=[];
  function join(label,record,relation,evidence,primary) {
    if(!groups.has(label))groups.set(label,{id:'cluster:'+label,type:'cluster',label,members:new Set(),primary:0});
    const group=groups.get(label);group.members.add(record.id);if(primary)group.primary++;
    links.push({source:group.id,target:record.id,relation,evidence,primary});
  }
  for(const record of memories) {
    const content=(record.content||'').toLowerCase(),topic=(record.topic||'').toLowerCase();
    const matches=rules.map(([label,words])=>{const evidence=words.filter(word=>content.includes(word)||topic.includes(word));return {label,evidence,score:evidence.reduce((sum,word)=>sum+(topic.includes(word)?4:1),0)}}).filter(r=>r.score>0).sort((a,b)=>b.score-a.score||a.label.localeCompare(b.label,'zh-CN'));
    if(record.topic&&topics.get(record.topic)>1) {
      join(record.topic,record,'相同主题',[record.topic],true);
      if(matches[0]?.score>=2)join(matches[0].label,record,'关键词关联',matches[0].evidence,false);
    } else if(matches.length) {
      join(matches[0].label,record,'关键词关联',matches[0].evidence,true);
      if(matches[1]?.score>=2)join(matches[1].label,record,'关键词关联',matches[1].evidence,false);
    } else join(fallback[record.kind]||'其他记忆',record,'所属分类',[record.kind],true);
  }
  const clusters=[...groups.values()].filter(g=>g.primary>0||g.members.size>1).sort((a,b)=>b.members.size-a.members.size||a.label.localeCompare(b.label,'zh-CN')).map((g,index)=>({...g,count:g.members.size,members:[...g.members],color:colors[index%colors.length]}));
  const valid=new Set(clusters.map(c=>c.id));
  return {nodes:[...clusters,...memories],links:links.filter(l=>valid.has(l.source)),clusters,total:input.total??memories.length,shown:memories.length,omitted:input.omitted||0};
}
if(typeof module!=='undefined'&&module.exports)module.exports={buildWhaleConstellation};

(() => {
  if(typeof document==='undefined')return;
  'use strict';
  const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
  const svg=$('memory-star-svg'),canvas=$('memory-space-canvas'),ctx=canvas.getContext('2d',{alpha:true}),inspector=$('star-detail');
  const media=matchMedia('(prefers-reduced-motion: reduce)');
  const kinds={preference:'偏好与个人事实',event:'共同经历',plan:'约定与计划',browse:'浏览记录'};
  const camera={yaw:-.28,pitch:.13,k:1.12,x:0,y:0};
  let data=null,sequence=0,digest='',selected='',expanded=false,motion=!media.matches;
  let positions=new Map(),elements=new Map(),dust=[],raf=0,last=0,draws=0,dragging=null;
  const rng=seed=>{let n=seed>>>0;return()=>{n=(Math.imul(n,1664525)+1013904223)>>>0;return n/4294967296}};
  function hash(text){let n=2166136261;for(const c of text)n=Math.imul(n^c.charCodeAt(0),16777619);return n>>>0}
  function el(tag,attrs={},text=''){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text)n.textContent=text;return n}
  function html(tag,text='',cls=''){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n}
  function date(value){return value?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value*1000)):'未记录'}
  function active(){return !document.hidden&&!$('page-memory').hidden&&!$('memory-map-view').hidden}
  function syncMotion(){
    document.body.classList.toggle('is-backgrounded',document.hidden);
    document.body.classList.toggle('visual-motion-off',!motion||media.matches);
    $('star-motion').textContent=motion&&!media.matches?'巡游已开':'巡游已关';
    $('star-motion').setAttribute('aria-pressed',String(motion&&!media.matches));
    if(!active()){cancelAnimationFrame(raf);raf=0;last=0}else requestFrame();
  }
  function requestFrame(){if(!raf&&active())raf=requestAnimationFrame(frame)}
  function project(point,w,h){
    const cy=Math.cos(camera.yaw),sy=Math.sin(camera.yaw),cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);
    const x=point.x*cy+point.z*sy,z=-point.x*sy+point.z*cy,y=point.y*cp-z*sp,depth=point.y*sp+z*cp;
    const perspective=1700/(1700+depth),fit=Math.min(w/1180,h/920)*camera.k;
    return {x:w*.53+camera.x+x*fit*perspective,y:h*.46+camera.y+y*fit*perspective,z:depth,p:perspective,scale:fit};
  }
  function frame(time){
    raf=0;if(!data||!active())return;
    if(motion&&!media.matches&&last&&time-last<30){requestFrame();return}
    if(motion&&!media.matches&&last)camera.yaw+=Math.min(50,time-last)*.000055;
    last=time;draws++;
    const rect=svg.getBoundingClientRect(),w=rect.width,h=rect.height,dpr=Math.min(2,devicePixelRatio||1);
    if(!w||!h)return;
    if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);svg.setAttribute('viewBox',`0 0 ${w} ${h}`)}
    ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
    const projected=new Map();for(const[id,point]of positions)projected.set(id,project(point,w,h));
    for(const item of dust){const p=project(item,w,h);if(p.x<0||p.x>w||p.y<0||p.y>h)continue;ctx.globalAlpha=item.a*(.85+.15*Math.sin(time*.0006+item.phase));ctx.fillStyle=item.color;const r=item.r*Math.min(1.5,p.p);ctx.fillRect(p.x,p.y,r,r)}
    const linked=new Set([selected]);for(const edge of data.links)if(edge.source===selected||edge.target===selected){linked.add(edge.source);linked.add(edge.target)}
    for(const cluster of data.clusters){const p=projected.get(cluster.id),r=Math.max(30,75*p.scale*p.p);const glow=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,r);glow.addColorStop(0,cluster.color+'18');glow.addColorStop(1,cluster.color+'00');ctx.globalAlpha=1;ctx.fillStyle=glow;ctx.fillRect(p.x-r,p.y-r,r*2,r*2)}
    let lines=0;
    for(const edge of data.links){
      const a=projected.get(edge.source),b=projected.get(edge.target);if(!a||!b)continue;
      const cluster=data.clusters.find(c=>c.id===edge.source),highlight=edge.source===selected||edge.target===selected;
      ctx.globalAlpha=selected?(highlight?.96:.08):(edge.primary?.45:.24);ctx.strokeStyle=highlight?'#f4dfa8':cluster.color;ctx.lineWidth=highlight?1.45:edge.primary?.7:.5;
      ctx.setLineDash(edge.primary?[]:[3,5]);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();lines++;
    }
    ctx.setLineDash([]);ctx.globalAlpha=1;
    for(const record of data.nodes){
      const p=projected.get(record.id),group=elements.get(record.id);if(!p||!group)continue;
      group.setAttribute('transform',`translate(${p.x.toFixed(2)} ${p.y.toFixed(2)}) scale(${Math.max(.65,Math.min(1.5,p.p)).toFixed(3)})`);
      group.style.opacity=selected&&!linked.has(record.id)?'.27':record.expired?'.48':String(Math.min(1,.72+p.p*.2));
      group.classList.toggle('selected',record.id===selected);
      group.setAttribute('aria-pressed',String(record.id===selected));
      const label=group.querySelector('.cluster-text');if(label)label.style.display=record.count<3&&camera.k<1.5&&record.id!==selected&&!expanded?'none':'';
    }
    svg.dataset.linkCount=String(lines);svg.dataset.camera=JSON.stringify(camera);svg.dataset.draws=String(draws);
    if(motion&&!media.matches)requestFrame();
  }
  function createScene(){
    positions=new Map();elements=new Map();dust=[];svg.replaceChildren();
    const scene=el('g',{'data-scene':'true'});svg.append(scene);
    data.clusters.forEach((cluster,index)=>{
      const angle=index*2.39996323,radius=170+Math.sqrt(index)*145;
      positions.set(cluster.id,{x:Math.cos(angle)*radius,y:Math.sin(angle)*radius*.8,z:Math.sin(index*1.91)*190});
    });
    for(const record of data.nodes.filter(n=>n.type==='memory')){
      const primary=data.links.find(l=>l.target===record.id&&l.primary),group=positions.get(primary.source),random=rng(hash(record.id));
      const theta=random()*Math.PI*2,z=random()*2-1,radius=65+Math.pow(random(),.45)*130,spread=Math.sqrt(1-z*z);
      positions.set(record.id,{x:group.x+Math.cos(theta)*spread*radius,y:group.y+Math.sin(theta)*spread*radius,z:group.z+z*radius});
    }
    const random=rng(428975);
    for(let i=0;i<2400;i++){
      const cluster=data.clusters.length?data.clusters[i%data.clusters.length]:null,hub=cluster?positions.get(cluster.id):{x:0,y:0,z:0};
      const around=i%3!==0;
      dust.push({x:around?hub.x+(random()-.5)*490:(random()-.5)*1900,y:around?hub.y+(random()-.5)*400:(random()-.5)*1350,z:(random()-.5)*900,r:random()*1.2+.5,a:random()*.42+.16,color:cluster?.color||'#8eabc8',phase:random()*8});
    }
    for(const record of data.nodes){
      const primary=record.type==='memory'?data.links.find(l=>l.target===record.id&&l.primary):null;
      const color=record.color||data.clusters.find(c=>c.id===primary?.source)?.color||'#b4d6ec';
      const group=el('g',{class:'star-node '+record.type,tabindex:0,role:'button','aria-label':record.type==='memory'?`${kinds[record.kind]}：${record.content.slice(0,90)}`:`${record.label}星团，${record.count}条记忆`,'aria-pressed':'false','data-id':record.id,'data-type':record.type});
      group.style.setProperty('--star-color',color);group.append(el('title',{},record.type==='memory'?record.content:record.label));
      const radius=record.type==='cluster'?4.5:record.pinned?4.2:2.6;
      group.append(el('circle',{r:radius+4,class:'node-halo'}),el('circle',{r:radius,class:'star-orb'}));
      if(record.pinned)group.append(el('circle',{r:radius+3,class:'pinned-orbit'}));
      group.append(el('circle',{r:radius+6,class:'selected-orbit'}));
      if(record.type==='cluster'){
        const label=el('g',{class:'cluster-text'}),width=record.label.length*12+20;
        label.append(el('rect',{x:-width/2,y:10,width,height:36,rx:3,class:'cluster-label-bg'}),el('text',{x:0,y:25,'text-anchor':'middle',class:'cluster-label'},record.label),el('text',{x:0,y:39,'text-anchor':'middle',class:'cluster-count'},record.count+' 条记忆'));group.append(label);
      }else group.append(el('text',{x:10,y:-7,class:'node-label'},record.label.slice(0,12)+(record.label.length>12?'…':'')));
      group.append(el('circle',{r:Math.max(radius+8,14),class:'hit'}));
      group.onclick=()=>choose(record.id);group.onfocus=()=>choose(record.id);group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(record.id)}};
      scene.append(group);elements.set(record.id,group);
    }
    svg.classList.toggle('labels-expanded',expanded);svg.dataset.memoryCount=String(data.shown);svg.dataset.clusterCount=String(data.clusters.length);
    $('star-count-all').textContent=data.shown;$('star-count-links').textContent=data.links.length;$('star-count-pinned').textContent=data.nodes.filter(n=>n.type==='memory'&&n.pinned).length;
    $('star-summary').textContent=`${data.shown} 条真实记忆 · ${data.clusters.length} 个主题星团 · ${data.links.length} 条关联`+(data.omitted?` · 另 ${data.omitted} 条可检索`:'');
    $('star-empty').hidden=!!data.shown;
    $('star-relation-note').textContent='星团按记录中的相同主题、实际出现的关键词或所属分类汇聚。选中节点可核对关联词；细碎星尘仅作背景装饰。';
    fitCamera();choose(data.nodes.some(n=>n.id===selected)?selected:'');requestFrame();
  }
  function choose(id){
    selected=id;const record=data?.nodes.find(n=>n.id===id);
    inspector.replaceChildren(html('div',record?'这段回声，有了来处':'记忆星团 · 三维探索','star-selection-label'));
    if(!record){inspector.append(html('h3','拖动星海，循着回声。'),html('p',`当前 ${data?.shown||0} 条记忆，汇成 ${data?.clusters.length||0} 个主题与关键词星团。点选星团，展开真实关联；放大可看见小星团的名字。`,'muted small'),html('p','亮点才是真实记忆，背景星尘不计入记忆数量。','muted small'));requestFrame();return}
    inspector.append(html('h3',record.type==='memory'?(record.topic||record.label):record.label));
    const edges=data.links.filter(l=>l.source===id||l.target===id);
    if(record.type==='memory'){
      inspector.append(html('p',record.content,'star-content'));
      const note=html('div','','inspector-path');note.append(html('span','本条记忆的真实归组依据'));
      for(const edge of edges){const cluster=data.clusters.find(c=>c.id===edge.source);note.append(html('div',cluster.label+'：'+(edge.relation==='所属分类'?'所属分类为'+(kinds[record.kind]||'其他'):edge.relation==='相同主题'?'主题完全相同':edge.evidence.join('、'))))}inspector.append(note);
      const dl=html('dl');for(const[key,value]of [['保存方式',record.pinned?'锁定珍藏 · 长期保存':record.expires?(record.expired?'已过期 · 可查历史':'有效至 '+date(record.expires)):'长期保存'],['记忆来源',record.source],['最近更新',date(record.updated)]])dl.append(html('dt',key),html('dd',value));inspector.append(dl);
      const button=html('button','查看原始来源与修订');button.type='button';button.onclick=async()=>{try{await memoryDetail(record.memory_id);$('memory-detail').scrollIntoView({behavior:media.matches?'instant':'smooth',block:'nearest'})}catch(error){tell(error.message)}};inspector.append(button);
    }else inspector.append(html('p',`${record.count} 条记忆因主题一致、正文命中关键词或同属一个分类汇聚在这里。选一条即可查看具体依据。`,'muted small'));
    const neighbors=[...new Set(edges.map(l=>l.source===id?l.target:l.source))];
    if(neighbors.length){inspector.append(html('h4','沿着关联继续探索'));const list=html('div','','star-neighbors');for(const neighbor of neighbors.slice(0,8)){const next=data.nodes.find(n=>n.id===neighbor),button=html('button',next.label);button.type='button';button.onclick=()=>choose(neighbor);list.append(button)}inspector.append(list)}
    requestFrame();
  }
  function zoom(factor){camera.k=Math.max(.2,Math.min(4,camera.k*factor));requestFrame()}
  function fitCamera(){
    if(!positions.size)return;
    const box=svg.getBoundingClientRect();if(!box.width||!box.height)return;
    camera.k=1;camera.x=0;camera.y=0;
    let points=[...positions.values()].map(point=>project(point,box.width,box.height));
    const extent=points=>({left:Math.min(...points.map(p=>p.x)),right:Math.max(...points.map(p=>p.x)),top:Math.min(...points.map(p=>p.y)),bottom:Math.max(...points.map(p=>p.y))});
    let bounds=extent(points);const padding=box.width<600?45:75;
    camera.k=Math.max(.35,Math.min(1.4,(box.width-padding*2)/Math.max(1,bounds.right-bounds.left),(box.height-padding*2)/Math.max(1,bounds.bottom-bounds.top)));
    points=[...positions.values()].map(point=>project(point,box.width,box.height));bounds=extent(points);
    camera.x=box.width/2-(bounds.left+bounds.right)/2;camera.y=box.height/2-(bounds.top+bounds.bottom)/2;
  }
  function reset(){Object.assign(camera,{yaw:-.28,pitch:.13,k:1.12,x:0,y:0});fitCamera();choose('');requestFrame()}
  function setMode(mode){$('memory-map-view').hidden=mode!=='map';$('memory-list-view').hidden=mode!=='list';$('memory-mode-map').setAttribute('aria-pressed',String(mode==='map'));$('memory-mode-list').setAttribute('aria-pressed',String(mode==='list'));syncMotion()}
  window.whaleMemoryMap={async update(query){const token=++sequence;svg.setAttribute('aria-busy','true');try{const response=await fetch('/api/memory-map?'+query,{cache:'no-store'}),body=await response.json();if(!response.ok||!body.ok)throw Error(body.error||'读取未完成');if(token!==sequence)return;const value=JSON.stringify(body.data);if(value===digest)return;digest=value;data=buildWhaleConstellation(body.data);createScene()}catch(error){if(token===sequence)$('star-summary').textContent='读取未完成：'+error.message}finally{if(token===sequence)svg.setAttribute('aria-busy','false')}},setMode,inspect:()=>({camera:{...camera},draws,animationRunning:!!raf&&active()&&motion&&!media.matches,memories:data?.shown||0,clusters:data?.clusters.length||0,links:data?.links.length||0})};
  $('memory-mode-map').onclick=()=>setMode('map');$('memory-mode-list').onclick=()=>setMode('list');$('star-reset').onclick=reset;
  $('star-zoom-in').onclick=()=>zoom(1.25);$('star-zoom-out').onclick=()=>zoom(.8);
  for(const[id,dy,dp]of [['star-left',-.2,0],['star-right',.2,0],['star-up',0,-.16],['star-down',0,.16]])$(id).onclick=()=>{camera.yaw+=dy;camera.pitch=Math.max(-1.2,Math.min(1.2,camera.pitch+dp));requestFrame()};
  $('star-labels').onclick=()=>{expanded=!expanded;svg.classList.toggle('labels-expanded',expanded);$('star-labels').setAttribute('aria-pressed',String(expanded));$('star-labels').textContent=expanded?'收起标签':'展开标签';requestFrame()};
  $('star-motion').onclick=()=>{motion=!motion;if(media.matches&&motion){motion=false;tell('已遵循系统减少动态效果设置')}syncMotion()};
  $('star-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.querySelector('.memory-star-panel').requestFullscreen()}catch{tell('当前窗口不支持全屏，可使用放大按钮探索')}};
  document.addEventListener('fullscreenchange',()=>{$('star-fullscreen').textContent=document.fullscreenElement?'退出沉浸':'沉浸星海';requestFrame()});
  svg.onpointerdown=event=>{if(event.target.closest('.star-node'))return;dragging={x:event.clientX,y:event.clientY,pan:event.shiftKey};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging')};
  svg.onpointermove=event=>{if(!dragging)return;const dx=event.clientX-dragging.x,dy=event.clientY-dragging.y;if(dragging.pan){camera.x+=dx;camera.y+=dy}else{camera.yaw+=dx*.005;camera.pitch=Math.max(-1.2,Math.min(1.2,camera.pitch+dy*.004))}dragging.x=event.clientX;dragging.y=event.clientY;requestFrame()};
  svg.onpointerup=svg.onpointercancel=()=>{dragging=null;svg.classList.remove('dragging')};
  svg.addEventListener('wheel',event=>{if(event.ctrlKey||document.activeElement===svg){event.preventDefault();zoom(event.deltaY<0?1.1:.91)}},{passive:false});
  svg.addEventListener('keydown',event=>{if(event.target!==svg)return;const map={ArrowLeft:['star-left'],ArrowRight:['star-right'],ArrowUp:['star-up'],ArrowDown:['star-down']};if(map[event.key]){event.preventDefault();$(map[event.key][0]).click()}if(event.key==='+'||event.key==='=')zoom(1.25);if(event.key==='-')zoom(.8);if(event.key==='Home'){event.preventDefault();reset()}});
  document.addEventListener('visibilitychange',syncMotion);media.addEventListener('change',syncMotion);
  new MutationObserver(syncMotion).observe($('page-memory'),{attributes:true,attributeFilter:['hidden']});
  new ResizeObserver(()=>{if(data)fitCamera();requestFrame()}).observe(svg.parentElement);
  setMode('map');choose('');syncMotion();
})();
