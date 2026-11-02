/* 星海只读取本机真实记忆；每一条可见航线都有接口返回的关系依据。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const categories = {preference:'偏好与个人事实',event:'共同经历',plan:'约定与计划',browse:'浏览记录'};
  const palette = {preference:'#88e5dc',event:'#8dc8f8',plan:'#efcf93',browse:'#a0b6ef'};
  const anchors = {preference:[285,225],event:[285,570],plan:[905,180],browse:[900,440]};
  const center = [580,380];
  const svg = $('memory-star-svg');
  const inspector = $('star-detail');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const view = {x:0,y:0,k:1};
  let data = null, selected = '', digest = '', sequence = 0;
  let scene = null, dragging = null, labelsExpanded = false, motionEnabled = !reducedMotion.matches, compactView = null;

  function element(tag, attrs={}, text='') {
    const node = document.createElementNS(NS,tag);
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,String(value));
    if (text) node.textContent=text;
    return node;
  }
  function html(tag,text,className='') {
    const node=document.createElement(tag);node.textContent=text;
    if(className)node.className=className;
    return node;
  }
  function whale(className='') {
    const node=element('svg',{viewBox:'0 0 200 150',class:className,'aria-hidden':'true'});
    node.append(element('use',{href:'#whale-mark'}));return node;
  }
  function date(value) {
    return value ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value*1000)) : '未记录';
  }
  function transform() {
    if(scene)scene.setAttribute('transform',`translate(${view.x} ${view.y}) scale(${view.k})`);
  }
  function zoom(factor) {
    const next=Math.max(.65,Math.min(3.8,view.k*factor)),ratio=next/view.k;
    const x=svg.viewBox.baseVal.width/2,y=svg.viewBox.baseVal.height/2;
    view.x=x-(x-view.x)*ratio;view.y=y-(y-view.y)*ratio;view.k=next;transform();
  }
  function move(x,y){view.x+=x;view.y+=y;transform()}
  function reset(){view.x=0;view.y=0;view.k=1;transform();choose('')}
  function setMode(mode) {
    $('memory-map-view').hidden=mode!=='map';$('memory-list-view').hidden=mode!=='list';
    $('memory-mode-map').setAttribute('aria-pressed',String(mode==='map'));
    $('memory-mode-list').setAttribute('aria-pressed',String(mode==='list'));
    syncMotion();
  }
  function syncMotion() {
    const running=motionEnabled&&!reducedMotion.matches&&!document.hidden&&!$('page-memory').hidden&&!$('memory-map-view').hidden;
    document.body.classList.toggle('visual-motion-off',!motionEnabled||reducedMotion.matches);
    document.body.classList.toggle('is-backgrounded',document.hidden);
    svg.classList.toggle('motion-off',!running);
    if(running)svg.unpauseAnimations?.();else svg.pauseAnimations?.();
    $('star-motion').textContent=motionEnabled&&!reducedMotion.matches?'动效已开':'动效已关';
    $('star-motion').setAttribute('aria-pressed',String(motionEnabled&&!reducedMotion.matches));
  }
  function relationPath(record) {
    if(!record)return [];
    if(record.type==='memory')return ['小鲸鱼',categories[record.kind],record.topic||record.label];
    if(record.type==='kind')return ['小鲸鱼',record.label];
    return [record.type==='collection'?'小鲸鱼':record.label];
  }
  function choose(id) {
    selected=id;
    const record=data?.nodes.find(item=>item.id===id);
    const adjacent=new Set(record?[id]:[]);
    const activeEdges=new Set();
    for(const [index,link] of (data?.links||[]).entries()) {
      if(link.source===id||link.target===id){adjacent.add(link.source);adjacent.add(link.target);activeEdges.add(index)}
    }
    // 叶节点沿所属分类回到中心，展示真实存在的两段关系。
    if(record?.type==='memory') {
      adjacent.add('collection');
      for(const [index,link] of data.links.entries()) {
        if(link.source==='collection'&&link.target==='kind:'+record.kind)activeEdges.add(index);
      }
    }
    for(const node of svg.querySelectorAll('.star-node')) {
      node.classList.toggle('selected',node.dataset.id===id);
      node.classList.toggle('faded',!!record&&!adjacent.has(node.dataset.id));
      node.setAttribute('aria-pressed',String(node.dataset.id===id));
    }
    for(const link of svg.querySelectorAll('.star-link')) {
      const relevant=activeEdges.has(Number(link.dataset.edgeIndex));
      link.classList.toggle('highlight',!!record&&relevant);
      link.classList.toggle('faded',!!record&&!relevant);
    }
    inspector.replaceChildren(html('div',record?'这颗记忆，正在发光':'听见记忆的回声','star-selection-label'));
    if(!record) {
      const art=html('div','','inspector-empty-art');art.append(whale());
      inspector.append(art,html('h3','点亮一颗，想起一段。'),html('p','选一颗记忆，看看小鲸鱼记住了什么。沿着亮起的航线，可以找到它所属的星域。','muted small'));
      const note=html('div','','inspector-path');
      note.append(html('span','每一条航线都有来处'),document.createTextNode(`当前展示 ${data?.shown||0} 条真实记忆、${data?.links.length||0} 条分类或主题关联。`));
      inspector.append(note,html('p','金色环是锁定珍藏。来源、保存期限和修改历史，都能在选中后查看。','muted small'));
      return;
    }
    const avatar=document.createElement('img');avatar.src='/assets/happy.png';avatar.alt='';avatar.width=58;avatar.height=58;avatar.className='inspector-avatar';
    inspector.append(avatar,html('h3',record.type==='memory'?(record.topic||categories[record.kind]):record.label));
    const path=html('div','','inspector-path');path.append(html('span','已点亮的真实关联路径'),document.createTextNode(relationPath(record).join('  ›  ')));inspector.append(path);
    if(record.type==='memory') {
      inspector.append(html('p',record.content,'star-content'));
      const fields=[['所属星域',categories[record.kind]],['保存方式',record.pinned?'锁定珍藏 · 长期保存':record.expires?(record.expired?'已过期 · 可查历史':'有效至 '+date(record.expires)):'长期保存 · 不设期限'],['记忆来源',record.source],['最近更新',date(record.updated)]];
      const dl=document.createElement('dl');for(const [key,value] of fields)dl.append(html('dt',key),html('dd',value||'未记录'));inspector.append(dl);
      const source=html('button','查看原始来源与修订');source.type='button';
      source.onclick=async()=>{try{await memoryDetail(record.memory_id);$('memory-detail').scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'nearest'})}catch(error){tell(error.message)}};
      inspector.append(source);
    } else {
      inspector.append(html('p',record.type==='collection'?`当前筛选共有 ${data.total} 条记忆，星海展示 ${data.shown} 条。`:`这个${record.type==='topic'?'主题':'星域'}关联了 ${record.count} 条已保存记忆。`,'muted small'));
    }
    const neighbors=data.nodes.filter(item=>adjacent.has(item.id)&&item.id!==id);
    if(neighbors.length) {
      inspector.append(html('h4','沿航线继续探索'));
      const list=html('div','','star-neighbors');
      for(const item of neighbors.slice(0,10)) {
        const button=html('button',item.type==='memory'?item.label:item.type==='collection'?'回到小鲸鱼':item.label);button.type='button';button.onclick=()=>choose(item.id);list.append(button);
      }
      if(neighbors.length>10&&record.type==='kind') {
        const button=html('button',`查看这个星域的 ${record.count} 条记忆`);button.type='button';
        button.onclick=()=>{$('memory-kind').value=record.kind;$('memory-kind').dispatchEvent(new Event('change'));setMode('list')};list.append(button);
      }
      inspector.append(list);
    }
  }
  function locationsFor(nodes,compact) {
    const points=compact?{preference:[155,170],event:[155,580],plan:[440,165],browse:[425,535]}:anchors;
    const middle=compact?[290,370]:center;
    const locations=new Map([['collection',middle]]);
    const rings=new Map();
    for(const [kind,point] of Object.entries(points))locations.set('kind:'+kind,point);
    for(const kind of Object.keys(categories)) {
      const records=nodes.filter(item=>item.type==='memory'&&item.kind===kind).sort((a,b)=>Number(b.pinned)-Number(a.pinned)||b.importance-a.importance||a.memory_id.localeCompare(b.memory_id));
      let cursor=0,ring=0;
      while(cursor<records.length) {
        const capacity=ring===0?8:ring===1?16:24;
        const count=Math.min(capacity,records.length-cursor);
        const radius=compact?(ring===0?(count<4?58:72):ring===1?104:136):(ring===0?(count<4?76:91):ring===1?146:193);
        for(let i=0;i<count;i++) {
          const item=records[cursor+i],angle=-Math.PI/2+2*Math.PI*(i+.5+(ring%2?.35:0))/count;
          const jitter=(i%3-1)*(compact?3:7);
          locations.set(item.id,[points[kind][0]+Math.cos(angle)*(radius+jitter),points[kind][1]+Math.sin(angle)*(radius+jitter)*.86]);
        }
        rings.set(kind,radius+(compact?12:20));cursor+=count;ring++;
      }
    }
    const topics=nodes.filter(item=>item.type==='topic');
    topics.forEach((item,index)=>{const angle=-Math.PI/2+index/Math.max(1,topics.length)*Math.PI*2;locations.set(item.id,[middle[0]+Math.cos(angle)*(compact?110:150),middle[1]+Math.sin(angle)*(compact?120:150)])});
    return {locations,rings,points,middle};
  }
  function curve(a,b,index,hub) {
    const dx=b[0]-a[0],dy=b[1]-a[1],bend=hub?.15:(index%2?.11:-.11);
    return `M${a[0]},${a[1]} C${a[0]+dx*.36-dy*bend},${a[1]+dy*.2+dx*bend} ${a[0]+dx*.7-dy*bend},${a[1]+dy*.82+dx*bend} ${b[0]},${b[1]}`;
  }
  function draw() {
    compactView=svg.getBoundingClientRect().width<600;
    const width=compactView?600:1200;
    svg.setAttribute('viewBox',`0 0 ${width} 760`);
    svg.replaceChildren();
    const stars=element('g',{'aria-hidden':'true'});
    const {locations,rings,points,middle}=locationsFor(data.nodes,compactView);
    for(let i=0;i<145;i++)stars.append(element('circle',{cx:(i*197+41)%width,cy:(i*i*43+31)%760,r:i%11===0?1.4:.6,fill:i%3===0?'#bce0df':'#a6bdd5',opacity:i%5===0?.6:.25}));
    for(const r of (compactView?[110,220,300]:[125,245,360]))stars.append(element('ellipse',{cx:middle[0],cy:middle[1],rx:r,ry:r*.75,class:'map-guide',transform:`rotate(-18 ${middle[0]} ${middle[1]})`}));
    svg.append(stars);
    scene=element('g',{'data-scene':'true'});svg.append(scene);
    const guides=element('g',{'aria-hidden':'true'});scene.append(guides);
    for(const [kind,radius] of rings) {
      const point=points[kind],orbit=element('ellipse',{cx:point[0],cy:point[1],rx:radius,ry:radius*.86,class:'cluster-orbit'});orbit.style.setProperty('--star-color',palette[kind]);guides.append(orbit);
    }
    const edges=element('g',{'aria-hidden':'true','data-relationships':'true'});scene.append(edges);
    data.links.forEach((edge,index)=> {
      const a=locations.get(edge.source),b=locations.get(edge.target);if(!a||!b)return;
      const source=data.nodes.find(node=>node.id===edge.source),target=data.nodes.find(node=>node.id===edge.target);
      const hub=edge.source==='collection',path=curve(a,b,index,hub);
      const line=element('path',{d:path,class:'star-link'+(hub?' hub-link':'')+(edge.relation==='相同主题'?' topic-link':''),'data-edge-index':index,'data-source':edge.source,'data-target':edge.target,'data-relation':edge.relation});
      line.style.setProperty('--edge-color',palette[target?.kind||source?.kind]||'#a0d4d6');edges.append(line);
      if(hub) {
        const dot=element('circle',{r:2.5,class:'star-flow'}),motion=element('animateMotion',{dur:`${8+index%4}s`,begin:`-${index*2}s`,repeatCount:'indefinite',path});dot.append(motion);edges.append(dot);
      }
    });
    const counters={};
    for(const record of data.nodes) {
      const point=locations.get(record.id);if(!point)continue;
      const featured=record.type==='memory'&&(record.pinned||(record.kind!=='browse'&&(counters[record.kind]=(counters[record.kind]||0)+1)%9===1));
      const group=element('g',{transform:`translate(${point[0]} ${point[1]})`,class:'star-node '+record.type+(record.expired?' expired':'')+(featured?' featured':''),tabindex:0,role:'button','aria-label':record.type==='memory'?`${categories[record.kind]}：${record.content.slice(0,90)}`:record.label,'data-id':record.id,'data-type':record.type,'aria-pressed':'false'});
      group.style.setProperty('--star-color',palette[record.kind]||'#a0e4dc');
      const radius=record.type==='collection'?54:record.type==='kind'?23:record.type==='topic'?9:record.pinned?8:5.6+(record.importance||0)/45;
      group.append(element('title',{},record.type==='memory'?record.content:record.label));
      if(record.type==='collection') {
        group.append(element('circle',{r:73,class:'center-ring'}),element('circle',{r:59,class:'collection-orb'}));
        const mark=whale();mark.setAttribute('x',-47);mark.setAttribute('y',-40);mark.setAttribute('width',94);mark.setAttribute('height',71);group.append(mark);
        group.append(element('text',{x:0,y:43,'text-anchor':'middle',class:'center-name'},'小鲸鱼'),element('text',{x:0,y:91,'text-anchor':'middle',class:'center-caption'},'每一段回声，都有归处'));
      } else if(record.type==='kind') {
        const labelWidth=record.label.length*15+65;
        group.append(element('rect',{x:-labelWidth/2,y:-20,width:labelWidth,height:40,rx:7,class:'kind-plate'}),element('text',{x:-18,y:5,'text-anchor':'middle',class:'kind-label'},record.label),element('circle',{cx:labelWidth/2-22,r:13,class:'kind-orb'}),element('text',{x:labelWidth/2-22,y:5,'text-anchor':'middle',class:'kind-count'},String(record.count)));
      } else if(record.type==='topic') {
        group.append(element('rect',{x:-8,y:-8,width:16,height:16,transform:'rotate(45)',class:'topic-orb'}),element('text',{x:15,y:4},record.label));
      } else {
        group.append(element('circle',{r:radius+8,class:'node-halo'}),element('circle',{r:radius+4,class:'node-fine-ring'}),element('circle',{r:radius,class:'star-orb'}));
        if(record.pinned)group.append(element('circle',{r:radius+7,class:'pinned-orbit'}));
        const side=point[0]>width-125?-1:point[0]<125?1:point[0]<points[record.kind][0]?-1:1;
        const label=record.label.slice(0,9)+(record.label.length>9?'…':'');
        group.append(element('text',{x:side*(radius+13),y:4,'text-anchor':side<0?'end':'start',class:'node-label'},label));
      }
      group.append(element('circle',{r:radius+12,class:'selected-orbit'}),element('circle',{r:Math.max(radius+12,18),class:'hit'}));
      group.onclick=()=>choose(record.id);group.onfocus=()=>choose(record.id);
      group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(record.id)}};
      scene.append(group);
    }
    transform();
    $('star-empty').hidden=!data.empty;
    $('star-summary').textContent=`${data.shown} 条记忆 · ${data.links.length} 条真实关联`+(data.omitted?` · 另 ${data.omitted} 条可检索`:'');
    $('star-count-all').textContent=data.shown;$('star-count-links').textContent=data.links.length;
    $('star-count-pinned').textContent=data.nodes.filter(node=>node.type==='memory'&&node.pinned).length;
    $('star-relation-note').textContent=data.relation_note;
    svg.classList.toggle('labels-expanded',labelsExpanded);
    choose(data.nodes.some(item=>item.id===selected)?selected:'');syncMotion();
  }
  window.whaleMemoryMap={
    async update(query) {
      const request=++sequence;$('memory-star-svg').setAttribute('aria-busy','true');
      try {
        const response=await fetch('/api/memory-map?'+query,{cache:'no-store'}),body=await response.json();
        if(!response.ok||!body.ok)throw new Error(body.error||'记忆星图暂不可读');
        if(request!==sequence)return;
        const next=JSON.stringify(body.data);if(next===digest)return;
        digest=next;data=body.data;draw();
      } catch(error) {
        if(request===sequence)$('star-summary').textContent='读取未完成：'+error.message;
      } finally {if(request===sequence)$('memory-star-svg').setAttribute('aria-busy','false')}
    },
    setMode
  };
  $('memory-mode-map').onclick=()=>setMode('map');$('memory-mode-list').onclick=()=>setMode('list');
  $('star-zoom-in').onclick=()=>zoom(1.25);$('star-zoom-out').onclick=()=>zoom(.8);$('star-reset').onclick=reset;
  for(const [id,x,y] of [['star-left',70,0],['star-right',-70,0],['star-up',0,70],['star-down',0,-70]])$(id).onclick=()=>move(x,y);
  $('star-labels').onclick=()=>{labelsExpanded=!labelsExpanded;svg.classList.toggle('labels-expanded',labelsExpanded);$('star-labels').setAttribute('aria-pressed',String(labelsExpanded));$('star-labels').textContent=labelsExpanded?'收起标签':'展开标签'};
  $('star-motion').onclick=()=>{motionEnabled=!motionEnabled;if(reducedMotion.matches&&motionEnabled){motionEnabled=false;tell('已遵循系统减少动态效果的设置')}syncMotion()};
  $('star-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.querySelector('.memory-star-panel').requestFullscreen()}catch{tell('当前窗口不支持全屏，可使用放大按钮探索星图')}};
  document.addEventListener('fullscreenchange',()=>{$('star-fullscreen').textContent=document.fullscreenElement?'退出沉浸':'沉浸星海'});
  svg.addEventListener('wheel',event=>{if(event.ctrlKey||document.activeElement===svg){event.preventDefault();zoom(event.deltaY<0?1.12:.89)}},{passive:false});
  svg.addEventListener('keydown',event=>{if(event.target!==svg)return;const directions={ArrowLeft:[70,0],ArrowRight:[-70,0],ArrowUp:[0,70],ArrowDown:[0,-70]};if(directions[event.key]){event.preventDefault();move(...directions[event.key])}if(event.key==='+'||event.key==='=')zoom(1.25);if(event.key==='-')zoom(.8);if(event.key==='Home'){event.preventDefault();reset()}});
  svg.onpointerdown=event=>{if(event.target.closest('.star-node'))return;dragging={x:event.clientX,y:event.clientY};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging')};
  svg.onpointermove=event=>{if(!dragging)return;const matrix=svg.getScreenCTM();if(!matrix)return;move((event.clientX-dragging.x)/matrix.a,(event.clientY-dragging.y)/matrix.d);dragging={x:event.clientX,y:event.clientY}};
  svg.onpointerup=svg.onpointercancel=()=>{dragging=null;svg.classList.remove('dragging')};
  document.addEventListener('visibilitychange',syncMotion);reducedMotion.addEventListener('change',syncMotion);
  new MutationObserver(syncMotion).observe($('page-memory'),{attributes:true,attributeFilter:['hidden']});
  new ResizeObserver(entries=>{const width=entries[0].contentRect.width;if(data&&width>0&&(width<600)!==compactView){view.x=0;view.y=0;view.k=1;draw()}}).observe(svg.parentElement);
  setMode('map');choose('');syncMotion();
})();
