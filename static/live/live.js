(() => {
  'use strict';
  const $ = id => document.getElementById(id), read = id => JSON.parse($(id).textContent);
  const cfg = read('config'), tables = read('tables'), tools = read('tools'), links = read('links');
  const app = document.querySelector('.live-app'), editable = app.dataset.editable === '1';
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let layers = cfg.layers.slice(), selected = layers[0], page = 1, active = 'نقشه';
  const state = new LiveState();
  const resultState = new LiveResults();
  let resultTab="table";
  const drawResults=()=>{ if(resultTab==="table") $("results").innerHTML=resultState.table; else {$("results").replaceChildren();for(const [id,job] of resultState.jobs){const row=document.createElement("p");row.textContent=`${job.title||"پردازش"} · ${job.status} · ${job.progress||0}% · ${job.message||""}`;$("results").append(row);if(job.status==="done"&&job.output)button("افزودن نتیجه به نقشه",()=>add(job.output.includes(".")?job.output:"public."+job.output),$("results"),!editable);}if(!resultState.jobs.size)$("results").textContent="هنوز پردازشی ثبت نشده است.";} };
  const markDirty = () => { if(!editable)return; state.markDirty(); $('saveState').textContent='ذخیره‌نشده'; };
  const client = new LiveClient({csrf});
  const gm = GPMap.createMulti($('map'), {...cfg,legend:false,printable:true});
  new ResizeObserver(() => gm.map.resize()).observe($('map'));
  const note = text => { $('notice').textContent = text; };
  const panel = (title, html) => { $('panelTitle').textContent = title; $('panel').innerHTML = html; LivePanels.open(document.querySelector('.details')); $('panelClose').focus(); };
  function button(label, fn, target, disabled = false) { const b = document.createElement('button'); b.textContent = label; b.disabled = disabled; b.addEventListener('click', fn); target.append(b); return b; }
  const auth = new LiveAuth({onSuccess:token=>{if(token)client.csrf=token;note('ورود انجام شد؛ اطلاعات فرم حفظ شده است. عملیات قبلی را دوباره بررسی و اجرا کنید.');},onError:message=>note(message)});
  async function request(url, body) { try{return await client.request(url, body ? {method:'POST',body} : {});}catch(error){if(error.code==='auth_required')auth.open();throw error;} }
  const workspaceId=Number(app.dataset.table.match(/live\/(\d+)/)?.[1]);
  const workflows=new LiveWorkflows({workspace:workspaceId,request,onComplete:data=>{if(data.tables){tables.splice(0,tables.length,...data.tables);}if(data.layer){layers.unshift(data.layer);gm.setLayers(layers);renderLayers();}if(data.jobsChanged)showJobs();note(data.message||'عملیات انجام شد.');}});
  function openLink(key){if(key==='qgis'){if(links.qgis){const a=document.createElement('a');a.href=links.qgis;a.download='';a.click();}return;}const url=links['workflow_'+key];if(url)workflows.open({import:'ورود فایل',data:'مدیریت داده',ai:'پرسش فارسی',satellite:'تصاویر ماهواره‌ای',publish:'انتشار',ows:'WMS / WFS',rest:'REST API',survey:'برداشت میدانی',plugins:'پلاگین‌ها'}[key]||'عملیات',url);else note('این جریان هنوز برای این فضای کار در دسترس نیست.');}
  function renderLayers() {
    const el=$('layers');el.replaceChildren();
    for(const l of layers.filter(l=>l.title.toLocaleLowerCase().includes($('search').value.toLocaleLowerCase()))){
      const row=document.createElement('div');row.className='layer'+(selected?.id===l.id?' active':'');row.dataset.layerId=l.id;row.draggable=editable;
      row.ondragstart=e=>e.dataTransfer.setData('text/plain',String(l.id));row.ondragover=e=>e.preventDefault();row.ondrop=e=>{e.preventDefault();const id=Number(e.dataTransfer.getData('text/plain')),from=layers.findIndex(x=>x.id===id),to=layers.indexOf(l);if(from<0||from===to||!editable)return;const [item]=layers.splice(from,1);layers.splice(to,0,item);gm.setLayers(layers);markDirty();renderLayers();};
      const check=document.createElement('input');check.type='checkbox';check.checked=l.visible;check.setAttribute('aria-label','نمایش '+l.title);check.onchange=()=>{l.visible=check.checked;gm.setVisible(l.key,l.visible);markDirty();};
      const sw=document.createElement('i');sw.className='swatch';sw.style.background=l.style.color;
      const name=button(l.title,()=>{selected=l;page=1;renderLayers();showTable();},row);name.className='layer-name';name.title=l.title;name.setAttribute('aria-pressed',String(selected?.id===l.id));name.insertAdjacentHTML('afterbegin',StudioUI.icon(LiveLayers.geometryIcon(l.geomType)));name.ondblclick=()=>layerOptions(l);
      name.onkeydown=e=>{if(e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();move(l,e.key==='ArrowUp'?-1:1);}};
      row.prepend(check,sw);const more=button('',()=>layerOptions(l),row);more.innerHTML=StudioUI.icon('more');more.setAttribute('aria-label','گزینه‌های لایهٔ '+l.title);el.append(row);
    }
    if(!layers.length)el.textContent='هنوز لایه‌ای اضافه نشده است. از افزودن داده شروع کنید.';
  }
  async function layerOptions(l){
    if(links.source){try{const data=await request(links.source.replace('/0/','/'+l.id+'/'));Object.assign(l,{srid:data.source.srid,fields:data.source.fields,schema:data.source.schema,table_name:data.source.table,bbox:data.source.extent});}catch(error){note(error.message);}}
    selected=l;renderLayers();const draft=new LayerDraft(l),dialog=$('propertiesDialog'),body=$('propertiesBody');$('propertiesTitle').textContent='ویژگی‌های '+l.title;
    const preview=()=>gm.setLayerStyle(l.key,draft.style);
    const field=(label,key,type,min,max)=>{const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement('input');input.type=type;input.value=draft.style[key]??'';input.disabled=!editable;if(min!==undefined){input.min=min;input.max=max;input.step=key==='opacity'?.05:1;}input.oninput=()=>{draft.style[key]=type==='number'||type==='range'?Number(input.value):input.value;preview();};wrap.append(input);body.append(wrap);};
    const tabs={
      'عمومی':()=>{const label=document.createElement('label');label.textContent='نام نمایشی';const input=document.createElement('input');input.value=draft.title;input.maxLength=120;input.disabled=!editable;input.oninput=()=>draft.title=input.value;label.append(input);body.append(label);const actions=document.createElement('div');button('رفتن به لایه',()=>gm.goToLayer(l.key),actions);button('جدول توصیفی',()=>{showTable();dialog.close();},actions);button('انتقال به بالا',()=>move(l,-1),actions,!editable);button('انتقال به پایین',()=>move(l,1),actions,!editable);button('حذف از پروژه',async()=>{if(!confirm('فقط از پروژه حذف شود؟ دادهٔ اصلی حذف نمی‌شود.'))return;try{await request(links.remove.replace('/0/','/'+l.id+'/'),new FormData());layers=layers.filter(x=>x.id!==l.id);selected=layers[0];gm.setLayers(layers);renderLayers();showTable();dialog.close();}catch(e){note(e.message)}},actions,!editable);body.append(actions);},
      'نمایش و نمادگذاری':()=>{field('رنگ نماد','color','color');field('شفافیت','opacity','range',.05,1);if(/POINT|LINE/i.test(l.geomType))field(/LINE/i.test(l.geomType)?'اندازهٔ خط':'اندازهٔ نماد','size','number',1,40);field('رنگ خط دور','outline','color');},
      'منبع':()=>{const dl=document.createElement('dl');for(const [label,value] of [['نام منبع',l.table_name||l.table],['طرح‌واره',l.schema||'public'],['نوع هندسه',l.geomType],['سیستم مختصات',l.srid||'در اطلاعات فعلی موجود نیست'],['محدوده',l.bbox?.join(', ')||'در اطلاعات فعلی موجود نیست']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;dd.dir='ltr';dl.append(dt,dd);}body.append(dl);},
      'برچسب':()=>{if(l.fields?.length){const label=document.createElement('label');label.textContent='فیلد برچسب';const select=document.createElement('select');select.disabled=!editable;select.add(new Option('بدون برچسب',''));for(const f of l.fields)select.add(new Option(f.name,f.name));select.value=draft.style.label||'';select.onchange=()=>{draft.style.label=select.value;preview();};label.append(select);body.append(label);}else field('فیلد برچسب','label','text');field('اندازهٔ برچسب','label_size','number',8,24);field('رنگ برچسب','label_color','color');const help=document.createElement('p');help.textContent='نام دقیق ستون را وارد کنید؛ ستون‌های نامعتبر هنگام ذخیره پذیرفته نمی‌شوند.';body.append(help);}
    };
    const draw=name=>{body.replaceChildren();tabs[name]();$('propertiesTabs').replaceChildren();for(const key of Object.keys(tabs)){const b=button(key,()=>draw(key),$('propertiesTabs'));b.setAttribute('aria-pressed',String(key===name));}};
    const apply=()=>{if(!editable)return;draft.apply();markDirty();renderLayers();};
    const cancel=()=>{draft.cancel();gm.setLayerStyle(l.key,draft.style);};
    $('propertiesApply').disabled=!editable;$('propertiesOK').disabled=!editable;$('propertiesApply').onclick=apply;$('propertiesOK').onclick=()=>{apply();dialog.close();};$('propertiesCancel').onclick=()=>{cancel();dialog.close();};$('propertiesClose').onclick=()=>{cancel();dialog.close();};dialog.oncancel=cancel;dialog.onclose=cancel;draw('نمایش و نمادگذاری');dialog.showModal();
  }
  function move(l,d){if(!editable)return;layers=LiveLayers.reorderLayers(layers,l.id,d);gm.setLayers(layers);renderLayers();markDirty();}
  async function add(key){if(!editable)return;try{const f=new FormData();f.set('t',key);const r=await request(links.add,f);const [schema,table]=key.split('.');if(!tables.some(t=>t.key===key)){const t={key,schema,table,geom_type:r.layer.geomType};tables.push(t);button(t.table,()=>add(t.key),$('catalog'),!editable).classList.add('catalog-item');}layers.unshift(r.layer);selected=r.layer;page=1;gm.setLayers(layers);renderLayers();gm.reveal(selected.key);note('لایه افزوده شد.');showTable();}catch(e){note(e.message)}}
  function catalog(){
    const dialog=$('addDialog'),list=$('addList'),picked=new Set();
    const draw=()=>{list.replaceChildren();for(const t of LiveLayers.filterTables(tables,$('catalogSearch').value,$('geometryFilter').value)){
      const row=document.createElement('label');row.className='catalog-row';const check=document.createElement('input');check.type='checkbox';check.checked=picked.has(t.key);check.onchange=()=>check.checked?picked.add(t.key):picked.delete(t.key);
      const content=document.createElement('span');content.innerHTML=StudioUI.icon(LiveLayers.geometryIcon(t.geom_type));const title=document.createElement('b');title.textContent=t.title||t.table;const source=document.createElement('small');source.textContent=t.key+(layers.some(l=>(l.schema||'public')+'.'+(l.table_name||l.table)===t.key)?' — موجود در پروژه':'');content.append(title,source);row.append(check,content);list.append(row);
    }if(!list.children.length)list.textContent='داده‌ای با این فیلتر پیدا نشد.';};
    $('catalogSearch').oninput=draw;$('geometryFilter').onchange=draw;$('addSelected').onclick=async()=>{if(!picked.size){$('addNotice').textContent='حداقل یک لایه انتخاب کنید.';return;}$('addSelected').disabled=true;for(const key of picked)await add(key);$('addSelected').disabled=false;dialog.close();};
    $('addNotice').textContent='افزودن دوبارهٔ یک منبع، نسخهٔ دیگری از لایه را می‌سازد.';draw();dialog.showModal();
  }
  let saving=false;
  async function save(){if(!editable||saving)return;saving=true;$('save').disabled=true;const revision=state.revision;$('saveState').textContent='در حال ذخیره…';try{await request(links.save,{title:$('title').value,description:read('description'),is_public:app.dataset.public==='1',basemap:cfg.basemapKind,view:gm.getView(),layers:layers.map(l=>({id:l.id,title:l.title,visible:l.visible,style:l.style}))});state.markSaved(revision);$('saveState').textContent=state.dirty?'ذخیره‌نشده':'ذخیره شد';note('پروژه ذخیره شد.');}catch(e){$('saveState').textContent='ذخیره ناموفق؛ دوباره تلاش کنید';note(e.message)}finally{saving=false;$('save').disabled=!editable}}
  async function editAttribute(config, key) {
    const trigger = document.activeElement;
    try {
      if (!config.active) {
        await request(config.urls.mode, {on:true});
        config.active = true;
      }
      const row = await request(config.urls.row + '?' + new URLSearchParams({pk:JSON.stringify(key.pk),geometry:"1"}));
      const dialog = document.createElement('dialog');
      dialog.setAttribute('aria-label', 'ویرایش مشخصات سطر');
      const form = document.createElement('form');
      const status = document.createElement('p');
      status.setAttribute('role', 'status');
      const fields = config.columns.filter(column => column.writable && !column.spatial);
      for (const column of fields) {
        const label = document.createElement('label');
        label.textContent = column.name;
        const input = document.createElement('input');
        input.name = column.name;
        input.value = row.values[column.name] ?? '';
        input.dir = 'auto';
        label.append(input);
        form.append(label);
      }
      const geometry = [];
      for (const [column, value] of Object.entries(row.geometry || {})) {
        const label = document.createElement('label');
        label.textContent = `هندسهٔ ${column} (WKT، EPSG:${value.srid})`;
        const input = document.createElement('textarea');
        input.dir = 'ltr';
        input.rows = 4;
        input.value = value.wkt ?? '';
        label.append(input);
        form.append(label);
        const field = {column, value, input, srid:value.srid};
        geometry.push(field);
        const shape = config.geometry?.find(item => item.column === column)?.type;
        if (LiveDrawing.supports(shape)) {
          const draw = button('ترسیم روی نقشه', () => {
            try {
              LiveDrawing.open({type:shape, config:{...cfg, layers}, view:gm.getView(), onApply:wkt=>{
                input.value = wkt;
                field.srid = 4326;
                label.firstChild.nodeValue = 'هندسهٔ ' + column + ' (WKT، EPSG:4326)';
              }});
            } catch (error) { status.textContent = error.message; }
          }, form);
          draw.type = 'button';
        }
      }
      const save = button('ذخیرهٔ سطر', () => {}, form);
      save.type = 'submit';
      const cancel = button('انصراف', () => dialog.close(), dialog);
      cancel.type = 'button';
      dialog.prepend(form, status);
      form.onsubmit = async event => {
        event.preventDefault();
        const values = Object.fromEntries([...new FormData(form)].filter(([name,value]) => value !== (row.values[name] ?? '')));
        const spatialChanges = geometry.filter(({input,value}) => input.value.trim() !== (value.wkt ?? ''));
        if (spatialChanges.length > 1) {
          status.textContent = 'در هر ذخیره فقط یک ستون هندسه را تغییر دهید.';
          return;
        }
        const change = spatialChanges[0];
        const geom = change ? (change.input.value.trim()
          ? {column:change.column,wkt:change.input.value.trim(),srid:change.srid}
          : {column:change.column,null:true}) : undefined;
        if (!Object.keys(values).length && !geom) { dialog.close(); return; }
        save.disabled = true;
        try {
          const result = await request(config.urls.apply, {changes:[{op:'update',pk:key.pk,v:row.v,values,geom}]});
          if (!result.ok) throw Error(result.results?.find(item => item.error)?.error || result.error);
          dialog.close();
          note('سطر ذخیره شد.');
          showTable();
        } catch (error) {
          status.textContent = error.message;
        } finally {
          save.disabled = false;
        }
      };
      dialog.addEventListener('close', () => { dialog.remove(); trigger?.focus(); }, {once:true});
      document.body.append(dialog);
      dialog.showModal();
    } catch (error) {
      note(error.message);
    }
  }
  async function showTable(){resultTab="table";const generation=resultState.beginTable();const l=selected;if(!l){$('results').textContent='لایه‌ای انتخاب نشده است.';return;} if(!links.data){$('results').textContent='مجوز جدول در دسترس نیست.';return;}try{const t=tables.find(t=>(t.schema==='public'?t.table:t.key)===l.table);if(!t){$('results').textContent='جدول در کاتالوگ پیدا نشد.';return;}const d=await request(app.dataset.table+'?'+new URLSearchParams({schema:t.schema,table:t.table,page}));if(selected!==l||generation!==resultState.generation)return; const markup=`<div><button id="prev">قبلی</button> صفحه ${d.page} از ${d.pages} <button id="next">بعدی</button></div><table><thead><tr>${d.columns.map(c=>`<th>${esc(c.name)}</th>`).join('')}</tr></thead><tbody>${d.rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;resultState.acceptTable(generation,markup);if(resultTab!=="table")return;drawResults();$('prev').disabled=page<=1;$('next').disabled=page>=d.pages;$('prev').onclick=()=>{page--;showTable()};$('next').onclick=()=>{page++;showTable()};if(d.edit?.capable&&(d.edit.geometry?.some(g=>g.srid)||d.edit.columns.some(c=>c.writable&&!c.spatial))){const head=$('results').querySelector('thead tr');const cell=document.createElement('th');cell.textContent='عملیات';head.append(cell);$('results').querySelectorAll('tbody tr').forEach((row,index)=>{if(d.keys[index])button('ویرایش سطر',()=>editAttribute(d.edit,d.keys[index]),row.insertCell());});}}catch(e){$('results').textContent=e.message}}
  function toolList(category){panel('جعبه ابزار تحلیل','<input id="toolSearch" placeholder="جستجوی ابزار"><div id="toolList" class="tool-list"></div>');const draw=()=>{const el=$('toolList');el.replaceChildren();tools.filter(t=>(!category||t.category===category)&&t.title.includes($('toolSearch').value)).forEach(t=>button(t.title,()=>toolForm(t),el));};$('toolSearch').oninput=draw;draw();}
  function toolForm(t){
    panel('پردازش مکانی',`<h2>${esc(t.title)}</h2><p>${esc(t.description)}</p><form id="toolForm"></form>`);const f=$('toolForm'),groups={};
    for(const [key,title]of [['input','ورودی‌ها'],['settings','تنظیمات'],['advanced','پیشرفته']]){const group=document.createElement(key==='advanced'?'details':'fieldset'),heading=document.createElement(key==='advanced'?'summary':'legend');heading.textContent=title;group.append(heading);f.append(group);groups[key]=group;}
    for(const p of t.params){
      const label=document.createElement('label');label.textContent=p.label;label.className=p.wide?'wide':'';let input;
      if(['layer','choice'].includes(p.kind)){input=document.createElement('select');const opts=p.kind==='choice'?p.choices:tables.filter(x=>!p.geom||String(x.geom_type).toLowerCase().includes(p.geom)).map(x=>[x.key,x.title||x.key]);if(!p.required)input.add(new Option(p.empty||'انتخاب نشده',''));for(const [value,title]of opts)input.add(new Option(title,value));const selectedKey=selected&&(selected.schema||'public')+'.'+(selected.table_name||selected.table);if(p.kind==='layer'&&opts.some(([key])=>key===selectedKey))input.value=selectedKey;else if(p.default!==undefined&&p.default!=='')input.value=p.default;}
      else{input=document.createElement('input');input.type=p.kind==='bool'?'checkbox':p.kind==='number'?'number':'text';if(p.kind==='number')input.step='any';if(p.kind==='bool'){input.checked=LiveTools.initialValue(p);input.value='on';}else input.value=LiveTools.initialValue(p);}
      input.name=p.name;input.required=p.required&&p.kind!=='bool';input.placeholder=p.placeholder||'';label.append(input);if(p.unit){const unit=document.createElement('small');unit.textContent=p.unit;label.append(unit);}if(p.help){const help=document.createElement('small');help.textContent=p.help;label.append(help);}groups[LiveTools.paramGroup(p)]?.append(label);
    }
    const output=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='خروجی';const label=document.createElement('label');label.textContent='نام جدول خروجی';const out=document.createElement('input');out.name='output';out.value=t.key+'_result';out.required=true;out.dir='ltr';label.append(out);output.append(legend,label);f.append(output);
    const errors=document.createElement('div');errors.setAttribute('role','alert');f.append(errors);const run=document.createElement('button');run.type='submit';run.className='primary';run.textContent='اجرای ابزار';f.append(run);
    f.onsubmit=async e=>{e.preventDefault();run.disabled=true;errors.replaceChildren();const data=new FormData(f);data.set('key',t.key);try{const result=await request(app.dataset.tool,data);note('تحلیل در صف قرار گرفت.');poll(result.url);}catch(error){errors.textContent=error.message;for(const [name,message]of Object.entries(error.fields||{})){const input=f.elements.namedItem(name);if(input){const help=document.createElement('small');help.textContent=message;help.className='field-error';input.setAttribute('aria-invalid','true');input.parentElement.append(help);}}}finally{run.disabled=false;}};
  }
  async function poll(url){try{const d=await request(url);resultState.setJob(url,d);if(resultTab==='jobs')drawResults();if(['queued','running'].includes(d.status)){setTimeout(()=>poll(url),2500);return;}note(d.status==='done'?'پردازش پایان یافت.':d.message||'پردازش پایان یافت.');}catch(e){note(e.message)}}
  async function showJobs(){resultTab='jobs';drawResults();if(!links.history)return;try{const data=await request(links.history);for(const job of data.jobs||[])resultState.setJob(job.id,job);drawResults();}catch(e){note(e.message)}}
  function showPublish(){
    const dialog=document.createElement('dialog');dialog.className='live-project-dialog';dialog.setAttribute('aria-label','انتشار لایه');const title=document.createElement('h2');title.textContent='انتشار Vector Tile';dialog.append(title);button('بستن',()=>dialog.close(),dialog);const form=document.createElement('form'),label=document.createElement('label'),select=document.createElement('select');label.textContent='لایهٔ منبع';for(const table of tables)select.add(new Option(table.title||table.key,table.key));label.append(select);form.append(label);const visibility=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.name='public';visibility.append(checkbox,document.createTextNode('انتشار عمومی — بدون کلید در دسترس همه خواهد بود'));form.append(visibility);const status=document.createElement('p');status.setAttribute('role','status');form.append(status);const run=button('انتشار لایه',()=>{},form,!editable);run.type='submit';form.onsubmit=async e=>{e.preventDefault();run.disabled=true;const [schema,...name]=select.value.split('.');const data=new FormData(form);data.set('schema',schema);data.set('table',name.join('.'));try{const result=await request(links.publish_api,data);status.textContent=result.message||'لایه منتشر شد.';}catch(error){status.textContent=error.message;}finally{run.disabled=!editable;}};dialog.append(form);document.body.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal();
  }
  async function showProjects(){
    const dialog=document.createElement('dialog');dialog.className='live-project-dialog';dialog.setAttribute('aria-label','پروژه‌ها');const close=button('بستن',()=>dialog.close(),dialog);const title=document.createElement('h2');title.textContent='پروژه‌های فضای کار';dialog.append(title);const content=document.createElement('div');dialog.append(content);document.body.append(dialog);dialog.onclose=()=>dialog.remove();dialog.showModal();
    const go=url=>{if(state.dirty&&!confirm('تغییرات ذخیره‌نشده دارید. از پروژه خارج می‌شوید؟'))return;const parsed=new URL(url,location.origin);if(parsed.origin!==location.origin||!parsed.pathname.startsWith('/live/'))return;location.href=parsed.href;};
    try{const data=await request(links.projects);for(const project of data.projects)button(project.title,()=>go(project.url),content);if(!data.projects.length)content.textContent='هنوز پروژه‌ای وجود ندارد.';
    if(editable){const form=document.createElement('form'),label=document.createElement('label'),input=document.createElement('input');label.textContent='نام پروژه جدید';input.name='title';input.required=true;input.maxLength=120;label.append(input);form.append(label);const create=button('ساخت پروژه',()=>{},form);create.type='submit';form.onsubmit=async e=>{e.preventDefault();create.disabled=true;try{const result=await request(links.projects,new FormData(form));go(result.project.url);}catch(error){note(error.message);}finally{create.disabled=false;}};dialog.append(form);}}catch(error){content.textContent=error.message;}close.focus();
  }
  function showPrintPreview() {
    const dialog = document.createElement('dialog');
    dialog.className = 'live-print-dialog';
    dialog.setAttribute('aria-label', 'پیش‌نمایش چاپ نقشه');
    const title = document.createElement('h2');
    title.textContent = $('title').value || 'نقشه';
    const image = document.createElement('img');
    image.alt = 'نمای فعلی نقشه';
    image.src = gm.map.getCanvas().toDataURL('image/png');
    const legend = document.createElement('ul');
    for (const layer of layers.filter(item => item.visible)) {
      const row = document.createElement('li');
      const swatch = document.createElement('i');
      swatch.className = 'swatch';
      swatch.style.backgroundColor = layer.style.color;
      row.append(swatch, document.createTextNode(layer.title));
      legend.append(row);
    }
    const attribution = document.createElement('p');
    attribution.textContent = $('map').querySelector('.maplibregl-ctrl-attrib-inner')?.textContent || 'PostGIS';
    const scale = document.createElement('p');
    scale.textContent = $('map').querySelector('.maplibregl-ctrl-scale')?.textContent || '';
    dialog.append(title, image, scale, legend, attribution);
    button('چاپ نقشه', () => window.print(), dialog);
    button('بستن', () => dialog.close(), dialog);
    dialog.addEventListener('close', () => dialog.remove(), {once:true});
    document.body.append(dialog);
    dialog.showModal();
  }
  const menus={پروژه:[['باز کردن پروژه',showProjects],['ذخیره',save]],نقشه:[['نمای کامل',()=>gm.fit()],['بزرگ‌نمایی',()=>gm.map.zoomIn()],['کوچک‌نمایی',()=>gm.map.zoomOut()],['ویژگی لایه',()=>selected&&layerOptions(selected)],['نقشه پایه',()=>{panel('نقشه پایه','<div id="bases"></div>');for(const b of ['osm','iran'])button(b,()=>{gm.setBasemap(b);cfg.basemapKind=b;markDirty();},$('bases'));}]],داده:[['افزودن لایه',catalog],['ورود فایل',()=>openLink('import')],['جدول توصیفی',showTable],['مدیریت جدول',showTable]],ویرایش:[['ویرایش داده',showTable],['سبک لایه',()=>selected&&layerOptions(selected)]],تحلیل:[['حریم (Buffer)',()=>{const t=tools.find(x=>x.key==='buffer');if(t)toolForm(t);else toolList()}],['مجاورت',()=>toolList('proximity')],['همپوشانی',()=>toolList('overlay')],['هندسه',()=>toolList('geometry')],['آمار مکانی',()=>toolList('stats')],['شبکه',()=>toolList('network')],['همه ابزارها',()=>toolList()]],ماهواره:[['تصاویر ماهواره‌ای',()=>openLink('satellite')]],GeoAI:[['پرسش فارسی',()=>openLink('ai')]],انتشار:[['Vector Tile',showPublish],['WMS / WFS',()=>openLink('ows')],['REST API',()=>openLink('rest')],['خروجی QGIS',()=>openLink('qgis')]],گزارش:[['چاپ و گزارش',showPrintPreview]],پلاگین‌ها:[['بازارچه',()=>openLink('plugins')],['برداشت میدانی',()=>openLink('survey')]]};
  function ribbon(){
    const focused=document.activeElement?.dataset.tab;
    $('tabs').replaceChildren();$('ribbon').replaceChildren();
    for(const k of Object.keys(menus)){
      const b=button(k,()=>{active=k;ribbon()},$('tabs'));b.dataset.tab=k;b.id='tab-'+Object.keys(menus).indexOf(k);b.setAttribute('role','tab');b.setAttribute('aria-selected',String(k===active));b.tabIndex=k===active?0:-1;
      b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const names=Object.keys(menus),i=names.indexOf(k);active=names[e.key==='Home'?0:e.key==='End'?names.length-1:(i+(e.key==='ArrowLeft'?1:-1)+names.length)%names.length];ribbon();$('tabs').querySelector('[aria-selected="true"]').focus();};
      if(k===active)b.classList.add('active');if(focused===k)b.focus();
    }
    const groups=new Map();
    for(const [name,fn] of menus[active]){
      const cmd=LiveCommands[name];if(!cmd)throw Error('Unknown Live command: '+name);
      if(!groups.has(cmd.group)){const group=document.createElement('section');group.className='ribbon-group';const actions=document.createElement('div'),caption=document.createElement('small');caption.textContent=cmd.group;group.append(actions,caption);$('ribbon').append(group);groups.set(cmd.group,actions);}
      const b=button(name,fn,groups.get(cmd.group));b.title=name;b.insertAdjacentHTML('afterbegin',StudioUI.icon(cmd.icon));
    }
  }
  const contentsView=(catalogActive)=>{$('contentsView').hidden=catalogActive;$('catalogView').hidden=!catalogActive;$('catalogTab').setAttribute('aria-pressed',String(catalogActive));$('contentsTab').setAttribute('aria-pressed',String(!catalogActive));};
  $('contentsTab').onclick=()=>contentsView(false);$('catalogTab').onclick=()=>contentsView(true);$('catalogAdd').onclick=catalog;$('contentsToggle').onclick=()=>{$('contentsPanel').classList.add('open');$('contentsClose').focus();};$('contentsClose').onclick=()=>{$('contentsPanel').classList.remove('open');$('contentsToggle').focus();};
  $('add').onclick=catalog;$('search').oninput=renderLayers;$('save').onclick=save;$('fit').onclick=()=>gm.fit();$('attributes').onclick=showTable;$('jobs').onclick=showJobs;$('collapse').onclick=()=>document.querySelector('.bottom').classList.toggle('collapsed');$('panelToggle').onclick=()=>{const el=document.querySelector('.details');if(el.classList.contains('hidden')){LivePanels.open(el,$('panelToggle'));$('panelClose').focus();}else LivePanels.close(el);};$('panelClose').onclick=()=>LivePanels.close(document.querySelector('.details'));document.querySelector('.details').addEventListener('keydown',e=>{if(e.key==='Escape')LivePanels.close(document.querySelector('.details'));});$('title').oninput=()=>{markDirty()};gm.map.on('moveend',markDirty);gm.map.on('mousemove',e=>{$('coords').textContent=e.lngLat.lat.toFixed(5)+'°, '+e.lngLat.lng.toFixed(5)+'°';});document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'){e.preventDefault();save()}});window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue=''}});for(const t of tables)button(t.table,()=>add(t.key),$('catalog'),!editable).classList.add('catalog-item');ribbon();renderLayers();showTable();
})();
