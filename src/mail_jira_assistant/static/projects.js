/* Project directory forms and durable AI proposals. No sample result is generated here. */
(() => {
  const $ = selector => document.querySelector(selector);
  if (!$('.project-directory-screen')) return;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const save = (key, value) => { try { sessionStorage.setItem(key,JSON.stringify(value)); } catch {} };
  const read = key => { try { return JSON.parse(sessionStorage.getItem(key)||'null'); } catch { return null; } };
  const remove = key => { try { sessionStorage.removeItem(key); } catch {} };
  const labels = {purpose:'목적·산출물',owner:'담당자',state:'진행 상태',started_on:'시작일',target_on:'목표 일정',spec:'Spec',process:'공정',development_target:'개발 대상'};
  const metadataControl = (key,value,index) => {
    const attrs='id="metadata-'+index+'" data-metadata="'+escape(key)+'" maxlength="5000"';
    if(['purpose','spec'].includes(key))return '<textarea '+attrs+'>'+escape(value)+'</textarea>';
    const type=['started_on','target_on'].includes(key)&&/^\d{4}-\d{2}-\d{2}$/.test(value)?'date':'text';
    return '<input '+attrs+' type="'+type+'" value="'+escape(value)+'">';
  };
  const sections = {overview:'개요',progress:'진행',issues:'이슈·리스크',decisions:'결정',updates:'변경',next_actions:'다음 액션'};
  const manual = $('#project-create-form');
  if (manual) {
    const key = 'worktrail-project-create';
    const controls = Object.fromEntries([...manual.elements].filter(e=>e.name).map(e=>[e.name,e]));
    const values = () => Object.fromEntries(Object.entries(controls).map(([k,e])=>[k,e.value.trim()]));
    const summary = () => {
      const data = values();
      $('#summary-name').textContent=data.name||'새 프로젝트';
      $('#summary-purpose').textContent=data.purpose||'프로젝트 이름과 목적을 입력하면 이곳에서 한눈에 확인할 수 있습니다.';
      $('#summary-purpose').classList.toggle('muted',!data.purpose);
      const keys={target:'development_target',date:'target_on'};
      document.querySelectorAll('[data-summary]').forEach(e=>e.textContent=data[keys[e.dataset.summary]||e.dataset.summary]||(e.dataset.summary==='date'?'미정':'미지정'));
      $('#summary-spec-block').hidden=!data.spec; $('#summary-spec').textContent=data.spec;
    };
    const draft=read(key);
    if(draft)Object.entries(controls).forEach(([k,e])=>{if(typeof draft[k]==='string')e.value=draft[k]});
    summary();
    manual.addEventListener('input',()=>{save(key,values());summary()});
    manual.addEventListener('submit',async event=>{
      event.preventDefault();
      const data=values(), feedback=$('#form-feedback'), button=manual.querySelector('button[type=submit],button.primary');
      let first;
      for(const [name,id,message] of [['name','name-error','프로젝트 이름을 입력하세요.'],['purpose','purpose-error','목적이나 전달할 산출물을 입력하세요.']]){
        const invalid=!data[name];$('#'+id).hidden=!invalid;$('#'+id).textContent=invalid?message:'';
        if(invalid){controls[name].setAttribute('aria-invalid','true');first ||= controls[name]}
        else controls[name].removeAttribute('aria-invalid');
      }
      if(first){first.focus();return}
      if(!manual.reportValidity())return;
      button.disabled=true;feedback.hidden=false;feedback.textContent='프로젝트를 만드는 중입니다…';
      for(const field of ['target_on','process','development_target','spec'])data[field] ||= 'TBD';
      try { const result=await api('/api/projects','POST',data);remove(key);dirty=false;location.href='/projects/'+result.id; }
      catch(error){feedback.textContent=error.message;button.disabled=false}
    });
  }
  const listFilter=$('.project-directory-screen .workspace-filter');
  const listStateKey='worktrail-project-list';
  if(listFilter){save(listStateKey,location.search);}
  else {
    const saved=read(listStateKey);
    const listLink=$('.directory-tabs a[href="/projects"]');
    if(listLink&&typeof saved==='string')listLink.href='/projects'+saved;
  }
  const form=$('#ai-workspace-form');
  if(!form)return;
  const input=$('#ai-request'), target=$('#ai-target'), sources=$('#ai-inquiries'), button=$('#ai-submit'), progress=$('#ai-progress'), output=$('#ai-output-body');
  const initial=output.innerHTML;
  let generation=0, timer, proposal=null, state=null, selectedRequest=new URL(location.href).searchParams.get('request')||'';
  let requestKey='', signature='';
  const entryContext=new URL(location.href).searchParams;
  const contextKey=entryContext.get('project_id')?'project-'+entryContext.get('project_id'):entryContext.get('inquiry')?'inquiry-'+entryContext.get('inquiry'):'new';
  const draftKey=()=> 'worktrail-project-ai:'+(selectedRequest||contextKey);
  const fields=()=>({text:input.value,target:target.value,inquiries:[...sources.selectedOptions].map(e=>e.value)});
  const store=()=>save(draftKey(),fields());
  const restore=data=>{
    if(!data)return;
    input.value=data.text||'';
    target.value=data.target||'auto';if(!target.value)target.value='auto';
    const ids=data.inquiries||[];[...sources.options].forEach(e=>e.selected=ids.includes(e.value));
    if(ids.length)sources.closest('details').open=true;
  };
  function busy(value){button.disabled=value;button.textContent=value?'AI 처리 중…':'요청 실행';$('.ai-output').setAttribute('aria-busy',String(value))}
  function kind(value){$('#ai-result-kind').textContent=value}
  function resultFocus(){ $('#ai-output-title').focus({preventScroll:true});if(matchMedia('(max-width:850px)').matches)$('.ai-output').scrollIntoView({block:'start'}); }
  function changeURL(key){const url=new URL(location.href);url.searchParams.set('tab','ai');if(key)url.searchParams.set('request',key);else url.searchParams.delete('request');history.replaceState(null,'',url);selectedRequest=key}
  function requestError(message){progress.classList.add('is-error');progress.textContent=message;busy(false);kind('요청 확인 필요')}
  function detail(request){return '<details class="ai-request-detail"><summary>요청 원문</summary><p>'+escape(request.text)+'</p></details>'}
  function reset(){generation++;clearTimeout(timer);proposal=null;state=null;requestKey='';signature='';changeURL('');form.reset();remove(draftKey());busy(false);kind('요청 대기');progress.textContent='';progress.classList.remove('is-error');$('#ai-error').hidden=true;input.removeAttribute('aria-invalid');output.innerHTML=initial;input.focus()}
  $('#ai-reset').addEventListener('click',reset);
  document.querySelectorAll('[data-ai-example]').forEach(b=>b.addEventListener('click',()=>{
    const current=target.value;
    const option=[...target.options].find(o=>o.value===current&&!['auto','new'].includes(o.value))||[...target.options].find(o=>!['auto','new'].includes(o.value));
    const name=option?option.textContent.split(' · ').slice(1).join(' · '):'수정할 프로젝트';
    reset();
    const prompts={create:'Nova DAC 개발 프로젝트를 만들어줘. 40nm 공정에서 DAC 회로 설계와 PVT 검증을 진행하고, 2027년 6월 30일까지 검증 보고서를 전달해. 담당은 Analog 개발팀이야.',update:name+'의 목표 일정을 2027년 4월 15일로 바꾸고, 하위 이슈의 검증 조건을 확인할 다음 액션을 추가해줘.',search:'3.3V GPIO cell을 개발하는 프로젝트를 찾아서 목적과 하위 이슈를 알려줘.',auto:'다음 내용이 기존 프로젝트에 해당하는지 찾아줘. 있으면 검증 일정을 업데이트하고, 없으면 새 프로젝트를 만들어줘.\n'+name+' · 검증 시작일은 2027년 12월 7일, 기존 testbench 조건 유지.'};
    input.value=prompts[b.dataset.aiExample];target.value=b.dataset.aiExample==='create'?'new':b.dataset.aiExample==='update'&&option?option.value:'auto';store();input.focus();
  }));
  form.addEventListener('input',()=>{requestKey='';store()});form.addEventListener('change',store);
  function render(data){
    state=data;proposal=null;busy(false);progress.classList.remove('is-error');
    if(data.state==='needs_input'||data.job_state==='failed'){
      kind(data.state==='needs_input'?'추가 정보 필요':'처리 실패');
      output.innerHTML='<div class="ai-empty compact"><h3>'+escape(data.question||data.error||'처리를 완료하지 못했습니다.')+'</h3><p>요청이나 대상·참고 문의를 확인한 뒤 다시 실행하세요.</p><button type="button" id="ai-revise">요청 이어서 작성</button><a class="button" href="/projects?tab=history">작업 이력</a></div>';
      progress.classList.add('is-error');progress.textContent=data.question||data.error||'처리에 실패했습니다.';
    }else if(data.state==='searched'){
      kind('프로젝트 검색');const matches=data.result.matches;
      output.innerHTML='<p class="ai-decision">검색 결과 <strong>'+matches.length+'개</strong></p>'+(matches.length?matches.map(m=>{
        const p=data.projects.find(p=>p.id===m.project_id);if(!p)return '';
        return '<article class="ai-match"><span class="project-code">'+escape(p.code)+'</span><h3><a class="text-link" href="/projects/'+p.id+'">'+escape(p.name)+'</a></h3><p>'+escape(p.purpose||'목적 미입력')+'</p><dl class="match-facts"><div><dt>목표 일정</dt><dd>'+escape(p.target_on)+'</dd></div><div><dt>하위 이슈</dt><dd><a href="/projects/'+p.id+'?view=issues">'+p.work_items.length+'개</a></dd></div></dl><p class="match-evidence">일치 단서 · '+escape(m.reason)+'</p><button type="button" data-use-project="'+p.id+'">이 프로젝트에 요청하기</button></article>';
      }).join(''):'<div class="ai-empty compact"><h3>일치하는 프로젝트가 없습니다</h3><p>다른 이름으로 검색하거나 이 내용으로 신규 생성을 요청할 수 있습니다.</p><button type="button" id="ai-create-from-search">이 내용으로 생성 요청</button></div>')+detail(data.input);
      progress.textContent='검색을 완료했습니다. 프로젝트 내용은 변경하지 않았습니다.';
      output.querySelectorAll('[data-use-project]').forEach(b=>b.addEventListener('click',()=>{target.value=b.dataset.useProject;input.value=data.projects.find(p=>p.id===Number(b.dataset.useProject)).name+'의 수정할 내용을 정리해줘.\n';store();input.focus()}));
      $('#ai-create-from-search')?.addEventListener('click',()=>{target.value='new';input.value='다음 내용으로 새 프로젝트를 만들어줘.\n'+data.input.text;store();input.focus()});
    }else if(data.state==='ready'){
      proposal=data.result;const p=data.projects.find(p=>p.id===proposal.project_id);
      kind(proposal.outcome==='create'?'신규 프로젝트 생성':'기존 프로젝트 업데이트');
      let body='<p class="ai-decision">변경안을 직접 수정한 뒤 반영할 수 있습니다.</p>';
      if(p)body+='<div class="ai-project-context"><span class="project-code">'+escape(p.code)+'</span><h3>'+escape(p.name)+'</h3><p>업데이트 대상 프로젝트</p></div>';
      body+='<div class="change-heading"><h3>'+ (proposal.outcome==='create'?'신규 생성안':'변경 내용')+'</h3></div><form id="ai-proposal-form" novalidate><div class="ai-proposal creation-editor">';
      if(proposal.outcome==='create')body+='<label for="proposal-name">프로젝트 이름</label><input id="proposal-name" maxlength="300" value="'+escape(proposal.name)+'" required>';
      body+=Object.entries(proposal.metadata).map(([key,value],i)=>'<div class="ai-change"><h4>프로젝트 · '+escape(labels[key]||key)+'</h4>'+(p?'<div class="change-before"><span>현재</span><p>'+escape(p[key]||'미입력')+'</p></div>':'')+'<label for="metadata-'+i+'">'+(p?'변경 후':escape(labels[key]||key))+'</label>'+metadataControl(key,value,i)+'</div>').join('');
      body+=proposal.changes.map((c,i)=>{
        const issue=p?.work_items.find(w=>w.id===c.work_item_id);
        const scope=issue?.title||c.work_title||'프로젝트';
        const previous=c.entry_id?proposal.before_text[String(c.entry_id)]:'';
        return '<div class="ai-change"><h4>'+escape(scope)+' · '+escape(sections[c.section]||c.section)+'</h4>'+(previous?'<div class="change-before"><span>현재</span><p>'+escape(previous)+'</p></div>':'')+'<label for="change-'+i+'">'+(previous?'변경 후':'추가할 내용')+'</label><textarea id="change-'+i+'" data-change-text maxlength="5000" required>'+escape(c.text)+'</textarea><details><summary>입력 근거</summary>'+c.evidence.map(e=>'<blockquote class="project-text">'+escape(e.text)+'</blockquote>').join('')+'</details></div>';
      }).join('');
      body+='</div>'+detail(data.input)+'<p class="field-error" id="proposal-error" role="alert" hidden></p><div class="ai-result-actions"><button type="submit" class="primary">변경안 반영</button><button type="button" id="ai-revise">요청 수정</button></div><p class="action-note">반영한 내용은 프로젝트의 변경 검토에서 확인하거나 되돌릴 수 있습니다.</p><p class="form-feedback" id="proposal-feedback" role="status"></p></form>';
      output.innerHTML=body;progress.textContent='변경안을 준비했습니다. 아직 프로젝트에 반영하지 않았습니다.';
      const proposalForm=$('#ai-proposal-form');
      const proposalKey='worktrail-project-proposal:'+data.request_id;
      const resultSignature=JSON.stringify(data.result);
      const saved=read(proposalKey);
      if(saved?.signature===resultSignature){
        if($('#proposal-name')&&typeof saved.name==='string')$('#proposal-name').value=saved.name;
        proposalForm.querySelectorAll('[data-metadata]').forEach(e=>{if(typeof saved.metadata?.[e.dataset.metadata]==='string')e.value=saved.metadata[e.dataset.metadata]});
        proposalForm.querySelectorAll('[data-change-text]').forEach((e,i)=>{if(typeof saved.texts?.[i]==='string')e.value=saved.texts[i]});
      }
      proposalForm.addEventListener('input',()=>save(proposalKey,{signature:resultSignature,name:$('#proposal-name')?.value,metadata:Object.fromEntries([...proposalForm.querySelectorAll('[data-metadata]')].map(e=>[e.dataset.metadata,e.value])),texts:[...proposalForm.querySelectorAll('[data-change-text]')].map(e=>e.value)}));
      proposalForm.addEventListener('submit',apply);
    }else if(data.state==='applied'){
      kind('반영 완료');
      output.innerHTML='<div class="ai-empty compact"><h3>프로젝트에 반영했습니다</h3><p>변경 전후를 확인하거나 후속 요청을 작성할 수 있습니다.</p><div class="ai-result-actions"><a class="button primary" href="/projects/'+data.project_id+'?view=review">변경 검토에서 보기</a><a class="button" href="/projects/'+data.project_id+'">프로젝트 열기</a></div><p><a href="/projects?tab=history">작업 이력 보기</a></p></div>'+detail(data.input);
      progress.textContent='프로젝트에 반영했습니다.';
    }
    $('#ai-revise')?.addEventListener('click',()=>input.focus());
    resultFocus();
  }
  async function apply(event){
    event.preventDefault();if(!proposal)return;
    const applyForm=event.currentTarget, submit=applyForm.querySelector('button[type=submit]'), error=$('#proposal-error'), feedback=$('#proposal-feedback');
    const name=$('#proposal-name'), texts=[...applyForm.querySelectorAll('[data-change-text]')], metadata=[...applyForm.querySelectorAll('[data-metadata]')];
    const first=[...(name?[name]:[]),...texts].find(e=>!e.value.trim());
    error.hidden=true;
    if(first){error.hidden=false;error.textContent='프로젝트 이름과 변경 내용의 빈 항목을 채워 주세요.';first.focus();return}
    const edits={metadata:Object.fromEntries(metadata.map(e=>[e.dataset.metadata,e.value.trim()])),texts:texts.map(e=>e.value.trim())};if(name)edits.name=name.value.trim();
    const gen=generation, request=state;
    submit.disabled=true;feedback.textContent='변경안을 반영 중입니다…';
    try{const result=await api('/api/project-ai/'+encodeURIComponent(request.request_id)+'/apply','POST',edits);remove('worktrail-project-proposal:'+request.request_id);if(gen===generation)render({...request,state:'applied',project_id:result.project_id});}
    catch(e){error.hidden=false;error.textContent=e.message;feedback.textContent='반영하지 못했습니다. 최신 프로젝트를 확인한 뒤 새 요청을 실행하세요.';submit.disabled=false}
  }
  async function getStatus(key){const response=await fetch('/api/project-ai/'+encodeURIComponent(key));if(!response.ok)throw Error('처리 상태를 불러오지 못했습니다. 작업 이력에서 확인하거나 다시 실행하세요.');return response.json()}
  async function poll(key,gen,count=0){
    try{const data=await getStatus(key);if(gen!==generation)return;
      if(['ready','applied','searched','needs_input'].includes(data.state)||data.job_state==='failed'){requestKey='';render(data);return}
      busy(true);kind(data.job_state==='retry_wait'?'재시도 대기':'처리 중');progress.textContent='AI가 처리 중입니다. 다른 탭으로 이동해도 작업 이력에서 이어서 확인할 수 있습니다.';
      if(count>=180){busy(false);progress.textContent='계속 처리 중입니다. 작업 이력에서 요청을 열어 결과를 확인하세요.';return}
      timer=setTimeout(()=>poll(key,gen,count+1),2000);
    }catch(e){if(gen===generation)requestError(e.message)}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();$('#ai-error').hidden=true;input.removeAttribute('aria-invalid');progress.classList.remove('is-error');
    const f=fields();if(!f.text.trim()&&!f.inquiries.length){$('#ai-error').hidden=false;$('#ai-error').textContent='요청할 작업이나 참고 문의를 입력하세요.';input.setAttribute('aria-invalid','true');input.focus();return}
    const search=/찾|검색|알려/.test(f.text)&&!/수정|업데이트|바꾸|변경|추가|만들|생성|없으면|있으면/.test(f.text);
    const data={text:f.text,mode:search?'search':f.target==='new'?'create':'auto',project_id:['auto','new'].includes(f.target)?null:Number(f.target),inquiry_ids:f.inquiries,preview:true,include_subissues:true};
    const sig=JSON.stringify(data);if(signature!==sig){signature=sig;requestKey=''}requestKey ||= crypto.randomUUID();data.request_key=requestKey;
    const gen=++generation;clearTimeout(timer);busy(true);proposal=null;kind('요청 등록 중');progress.textContent='AI 처리 요청을 등록 중입니다…';output.innerHTML='<p class="ai-loading">프로젝트와 요청 내용을 확인하고 있습니다…</p>';store();
    try{const result=await api('/api/project-ai','POST',data);if(gen!==generation)return;changeURL(result.request_id);store();poll(result.request_id,gen);}
    catch(e){if(gen===generation)requestError(e.message)}
  });
  if(selectedRequest){
    const gen=++generation;busy(true);
    getStatus(selectedRequest).then(data=>{if(gen!==generation)return;restore({text:data.input.text,target:data.input.project_id?String(data.input.project_id):data.input.mode==='create'?'new':'auto',inquiries:data.input.inquiry_ids});restore(read(draftKey()));if(['ready','applied','searched','needs_input'].includes(data.state)||data.job_state==='failed')render(data);else poll(selectedRequest,gen)}).catch(e=>requestError(e.message));
  }else restore(read(draftKey()));
})();
