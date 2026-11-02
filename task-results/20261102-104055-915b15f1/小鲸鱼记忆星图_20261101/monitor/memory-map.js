/* 记忆星图只展示本机接口返回的记录与实际分类、主题，不生成虚构关系。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const NS = 'http://www.w3.org/2000/svg';
  const palette = {preference:'#8de7ad',event:'#8ec9de',plan:'#f0d09a',browse:'#b7bfd0'};
  const categories = {preference:'偏好与个人事实',event:'共同经历',plan:'约定与计划',browse:'浏览记录'};
  const anchors = {preference:[300,175],event:[735,180],plan:[730,500],browse:[285,480]};
  const svg = $('memory-star-svg');
  const inspector = $('star-detail');
  let data = null, selected = '', digest = '', sequence = 0;
  const view = {x:0,y:0,k:1};
  let scene = null, dragging = null;

  function element(tag, attrs={}, text='') {
    const node = document.createElementNS(NS,tag);
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,String(value));
    if (text) node.textContent=text;
    return node;
  }
  function html(tag,text,className='') {
    const node=document.createElement(tag);
    node.textContent=text;
    if(className) node.className=className;
    return node;
  }
  function date(value) {
    return value ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value*1000)) : '未记录';
  }
  function transform() {if(scene) scene.setAttribute('transform',`translate(${view.x} ${view.y}) scale(${view.k})`)}
  function zoom(factor) {
    const next=Math.max(.6,Math.min(3,view.k*factor)), ratio=next/view.k;
    view.x=500-(500-view.x)*ratio; view.y=340-(340-view.y)*ratio; view.k=next; transform();
  }
  function move(x,y) {view.x+=x;view.y+=y;transform()}
  function setMode(mode) {
    $('memory-map-view').hidden=mode!=='map';
    $('memory-list-view').hidden=mode!=='list';
    $('memory-mode-map').setAttribute('aria-pressed',String(mode==='map'));
    $('memory-mode-list').setAttribute('aria-pressed',String(mode==='list'));
  }

  function choose(id) {
    selected=id;
    const record=data?.nodes.find(item=>item.id===id);
    const adjacent=new Set([id]);
    for(const link of data?.links||[]) if(link.source===id||link.target===id){adjacent.add(link.source);adjacent.add(link.target)}
    for(const node of svg.querySelectorAll('.star-node')){
      node.classList.toggle('selected',node.dataset.id===id);
      node.classList.toggle('faded',!!record&&!adjacent.has(node.dataset.id));
      node.setAttribute('aria-pressed',String(node.dataset.id===id));
    }
    for(const link of svg.querySelectorAll('.star-link')){
      const relevant=link.dataset.source===id||link.dataset.target===id;
      link.classList.toggle('highlight',!!record&&relevant);
      link.classList.toggle('faded',!!record&&!relevant);
    }
    inspector.replaceChildren(html('div',record?'正在查看':'选择一颗记忆','star-selection-label'));
    if(!record){
      inspector.append(html('h3','点亮一颗记忆'),html('p','点击或用键盘选择节点，查看小鲸鱼记住的内容、来源与保留期限。','muted small'),html('p','圆点是记忆，较大的圆是分类，菱形表示多条记录共享的主题。金色圆环表示已锁定。','muted small'));
      return;
    }
    inspector.append(html('h3',record.type==='memory'?(record.topic||categories[record.kind]||'一条记忆'):record.label));
    if(record.type==='memory'){
      inspector.append(html('p',record.content,'star-content'));
      const fields=[['所属分类',categories[record.kind]],['保存方式',record.pinned?'已锁定 · 长期保存':record.expires?(record.expired?'已过期 · 仍可查历史':'有效至 '+date(record.expires)):'长期保存 · 不设期限'],['记录来源',record.source],['最近更新',date(record.updated)]];
      const dl=document.createElement('dl');
      for(const [key,value] of fields) dl.append(html('dt',key),html('dd',value||'未记录'));
      inspector.append(dl);
      const source=html('button','查看原始来源与修订');source.type='button';
      source.onclick=async()=>{try{await memoryDetail(record.memory_id);$('memory-detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'})}catch(error){tell(error.message)}};
      inspector.append(source);
    }else{
      inspector.append(html('p',record.type==='collection'?`当前筛选共有 ${data.total} 条记忆，星图展示 ${data.shown} 条。`:`这${record.type==='topic'?'个主题':'类记录'}关联了 ${record.count} 条已保存记忆。`,'muted small'));
    }
    const neighbors=(data?.nodes||[]).filter(item=>adjacent.has(item.id)&&item.id!==id);
    if(neighbors.length){
      inspector.append(html('h4','直接关联'));
      const list=html('div','','star-neighbors');
      for(const item of neighbors){const button=html('button',item.label);button.type='button';button.onclick=()=>choose(item.id);list.append(button)}
      inspector.append(list);
    }
  }

  function draw() {
    svg.replaceChildren();
    const stars=element('g',{'aria-hidden':'true'});
    for(let i=0;i<90;i++) stars.append(element('circle',{cx:(i*193+71)%1000,cy:(i*i*43+37)%680,r:i%9===0?1.5:.65,fill:'#b2bfd0',opacity:i%5===0?.5:.16}));
    svg.append(stars);
    scene=element('g');svg.append(scene);
    const locations=new Map([['collection',[500,335]]]);
    for(const [kind,point] of Object.entries(anchors)) locations.set('kind:'+kind,point);
    for(const kind of Object.keys(categories)){
      const records=data.nodes.filter(item=>item.type==='memory'&&item.kind===kind).sort((a,b)=>a.memory_id.localeCompare(b.memory_id));
      records.forEach((item,index)=>{const angle=index*2.399963+kind.length*.3,radius=48+Math.sqrt(index)*20,center=anchors[kind];locations.set(item.id,[center[0]+Math.cos(angle)*radius,center[1]+Math.sin(angle)*radius*.78])});
    }
    const topics=data.nodes.filter(item=>item.type==='topic');
    topics.forEach((item,index)=>{const angle=index/Math.max(1,topics.length)*Math.PI*2;locations.set(item.id,[500+Math.cos(angle)*105,335+Math.sin(angle)*95])});
    const edges=element('g',{'aria-hidden':'true'});scene.append(edges);
    for(const edge of data.links){
      const a=locations.get(edge.source),b=locations.get(edge.target);if(!a||!b)continue;
      const line=element('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],class:'star-link'+(edge.relation==='相同主题'?' topic-link':''),'data-source':edge.source,'data-target':edge.target});edges.append(line);
    }
    for(const record of data.nodes){
      const point=locations.get(record.id);if(!point)continue;
      const group=element('g',{transform:`translate(${point[0]} ${point[1]})`,class:'star-node '+record.type+(record.expired?' expired':''),tabindex:0,role:'button','aria-label':record.type==='memory'?`${categories[record.kind]}：${record.content.slice(0,90)}`:record.label,'data-id':record.id,'data-type':record.type,'aria-pressed':'false'});
      group.style.setProperty('--star-color',palette[record.kind]||'#f0d09a');
      const radius=record.type==='collection'?32:record.type==='kind'?25:record.type==='topic'?8:5+(record.importance||0)/28;
      group.append(element('circle',{r:Math.max(radius,16),class:'hit'}),element('title',{},record.type==='memory'?record.content:record.label));
      if(record.type==='topic')group.append(element('rect',{x:-7,y:-7,width:14,height:14,transform:'rotate(45)',class:'topic-orb'}));
      else group.append(element('circle',{r:radius,class:record.type==='kind'?'kind-orb':record.type==='collection'?'collection-orb':'star-orb'}));
      if(record.pinned)group.append(element('circle',{r:radius+5,class:'pinned-orbit'}));
      group.append(element('circle',{r:radius+9,class:'selected-orbit'}));
      const label=record.type==='memory'?record.label.slice(0,9)+(record.label.length>9?'…':''):record.label;
      group.append(element('text',{x:record.type==='memory'?radius+8:0,y:record.type==='memory'?4:radius+21,'text-anchor':record.type==='memory'?'start':'middle'},label));
      if(record.type==='kind'||record.type==='collection')group.append(element('text',{x:0,y:5,'text-anchor':'middle'},String(record.count)));
      group.onclick=()=>choose(record.id);group.onfocus=()=>choose(record.id);group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose(record.id)}};
      scene.append(group);
    }
    transform();
    $('star-empty').hidden=!data.empty;
    $('star-summary').textContent=`展示 ${data.shown} / ${data.total} 条记忆`+(data.omitted?` · 其余 ${data.omitted} 条可搜索或切换列表查看`:'');
    $('star-relation-note').textContent=data.relation_note;
    choose(data.nodes.some(item=>item.id===selected)?selected:'');
  }

  window.whaleMemoryMap={
    async update(query){
      const request=++sequence;
      try{
        const response=await fetch('/api/memory-map?'+query,{cache:'no-store'}),body=await response.json();
        if(!response.ok||!body.ok)throw new Error(body.error||'记忆星图暂不可读');
        if(request!==sequence)return;
        const next=JSON.stringify(body.data);
        if(next===digest)return;
        digest=next;data=body.data;draw();
      }catch(error){if(request===sequence)$('star-summary').textContent=error.message}
    },
    setMode
  };
  $('memory-mode-map').onclick=()=>setMode('map');$('memory-mode-list').onclick=()=>setMode('list');
  $('star-zoom-in').onclick=()=>zoom(1.25);$('star-zoom-out').onclick=()=>zoom(.8);
  $('star-reset').onclick=()=>{view.x=0;view.y=0;view.k=1;transform();choose('')};
  for(const [id,x,y] of [['star-left',65,0],['star-right',-65,0],['star-up',0,65],['star-down',0,-65]])$(id).onclick=()=>move(x,y);
  svg.addEventListener('wheel',event=>{if(event.ctrlKey||document.activeElement===svg){event.preventDefault();zoom(event.deltaY<0?1.12:.89)}},{passive:false});
  svg.addEventListener('keydown',event=>{if(event.target!==svg)return;const directions={ArrowLeft:[65,0],ArrowRight:[-65,0],ArrowUp:[0,65],ArrowDown:[0,-65]};if(directions[event.key]){event.preventDefault();move(...directions[event.key])}if(event.key==='+'||event.key==='=')zoom(1.25);if(event.key==='-')zoom(.8)});
  svg.onpointerdown=event=>{if(event.target.closest('.star-node'))return;dragging={x:event.clientX,y:event.clientY};svg.setPointerCapture(event.pointerId);svg.classList.add('dragging')};
  svg.onpointermove=event=>{if(!dragging)return;const rect=svg.getBoundingClientRect();move((event.clientX-dragging.x)*1000/rect.width,(event.clientY-dragging.y)*680/rect.height);dragging={x:event.clientX,y:event.clientY}};
  svg.onpointerup=svg.onpointercancel=()=>{dragging=null;svg.classList.remove('dragging')};
  setMode('map');choose('');
})();
