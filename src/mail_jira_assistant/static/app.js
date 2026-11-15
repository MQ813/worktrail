let dirty=false;
const editor=document.querySelector('#draft-body');
if(editor) editor.addEventListener('input',()=>{dirty=true;document.querySelector('#save-status').textContent='저장하지 않은 변경이 있습니다.'});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
function toast(text){let t=document.querySelector('#toast');t.textContent=text;t.style.display='block';setTimeout(()=>t.style.display='none',5000)}
async function api(url,method='POST',data={}){let r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let x=await r.json();if(!r.ok)throw Error(typeof x.detail==='string'?x.detail:JSON.stringify(x.detail));return x}
async function saveDraft(review){try{let x=await api('/api/drafts/'+editor.dataset.id,'PUT',{version:Number(editor.dataset.version),body:editor.value,review});editor.dataset.version=x.version;dirty=false;document.querySelector('#save-status').textContent=review==='reviewed'?'검토 완료로 저장했습니다. 발송·업무 상태는 별도로 관리합니다.':'저장했습니다.';toast('초안을 저장했습니다.')}catch(e){toast(e.message)}}
async function command(url,data={},reload=false){try{const result=await api(url,'POST',data);toast(result.queued?(url.endsWith('/regenerate')?'초안 생성 요청을 등록했습니다. 완료 후 새로고침하면 결과를 확인할 수 있습니다.':url.endsWith('/classify')?'분류 요청을 등록했습니다. 처리 상태는 운영 상태에서 확인할 수 있습니다.':'처리 요청을 등록했습니다. 운영 상태에서 진행 상황을 확인할 수 있습니다.'):'반영했습니다.');if(reload)location.reload()}catch(e){toast(e.message)}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-command]');if(!b)return;b.disabled=true;try{let data=JSON.parse(b.dataset.payload||'{}');await command(b.dataset.command,data,b.dataset.reload==='true')}finally{b.disabled=false}});
const override=document.querySelector('#override-form');if(override)override.addEventListener('submit',async e=>{e.preventDefault();await command(override.action,{state:override.state.value,note:override.note.value,revision:Number(override.dataset.revision)},true)});
const jira=document.querySelector('#jira-form');if(jira)jira.addEventListener('submit',async e=>{e.preventDefault();await command('/api/jira',{url:jira.url.value},true)});
const link=document.querySelector('#link-form');if(link)link.addEventListener('submit',async e=>{e.preventDefault();await command(link.action,{target:link.elements.namedItem('target').value||null},true)});
document.querySelector('#save-edit')?.addEventListener('click',()=>saveDraft('editing'));
document.querySelector('#save-review')?.addEventListener('click',()=>saveDraft('reviewed'));
const classification=document.querySelector('#classification-form');if(classification)classification.addEventListener('submit',async e=>{e.preventDefault();let data={revision:Number(classification.dataset.revision),note:classification.note.value};for(let axis of ['response_expected','action_required','work_performed','waiting_for_others'])data[axis]=classification.elements[axis].value;await command(classification.action,data,true)});
document.querySelector('#copy-draft')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(editor.value);toast('초안을 복사했습니다.')}catch{editor.select();toast('내용을 선택했습니다. Ctrl+C로 복사하세요.')}});
document.querySelector('#hold-draft')?.addEventListener('click',()=>saveDraft('archived'));
const activity=document.querySelector('#activity-form');
activity?.addEventListener('input',()=>{dirty=true});
if(activity)activity.addEventListener('submit',async e=>{e.preventDefault();try{const d=Object.fromEntries(new FormData(activity));for(const k of ['action_id','duplicate_of','minutes'])d[k]=d[k]===''?null:Number(d[k]);d.inquiry_id=d.inquiry_id||null;d.complete_action=activity.complete_action.checked;d.version=Number(activity.dataset.version);await api('/api/activities'+(activity.dataset.id?'/'+activity.dataset.id:''),activity.dataset.id?'PUT':'POST',d);dirty=false;location.href='/projects/'+activity.dataset.projectId+'?on='+encodeURIComponent(d.performed_on||'')+'#project-records'}catch(x){toast(x.message)}});
const importer=document.querySelector('#import-form');if(importer)importer.addEventListener('submit',async e=>{e.preventDefault();await command('/api/worklog/import',Object.fromEntries(new FormData(importer)),true)});
const projectForm=document.querySelector('#project-form');if(projectForm)projectForm.addEventListener('submit',async e=>{e.preventDefault();await command('/api/projects/link',Object.fromEntries(new FormData(projectForm)),true)});

document.querySelectorAll('form[data-project-api]').forEach(form=>{
  form.addEventListener('input',()=>{dirty=true});
  form.addEventListener('submit',async event=>{
    event.preventDefault();const feedback=form.querySelector('.form-feedback');const button=form.querySelector('button');
    const data=Object.fromEntries(new FormData(form));
    if(form.dataset.version)data.version=Number(form.dataset.version);
    if(form.elements.namedItem('detail'))data.detail=form.elements.namedItem('detail').type==='hidden'?form.elements.namedItem('detail').value==='true':form.elements.namedItem('detail').checked;
    if(data.work_item_id)data.work_item_id=Number(data.work_item_id);
    button.disabled=true;feedback.classList.remove('is-error');feedback.textContent='저장 중입니다…';
    try{const result=await api(form.dataset.projectApi,form.dataset.method||'POST',data);dirty=false;
      if(result.queued!==undefined){feedback.textContent=result.queued+'건을 등록했습니다. 운영 상태에서 처리 결과를 확인하세요.';button.disabled=false}
      else if(result.redirect){if(result.message){try{sessionStorage.setItem('worktrail-save-feedback',result.message)}catch{}}location.href=result.redirect}
      else if(result.id)location.href='/projects/'+result.id;else location.reload();
    }catch(error){feedback.classList.add('is-error');feedback.textContent=error.message;button.disabled=false}
  });
});
document.querySelectorAll('.project-proposal').forEach(input=>input.addEventListener('input',()=>{dirty=true}));
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-project-review],[data-project-batch]');if(!button)return;
  const single=button.closest('[data-change-id]');
  const articles=single?[single]:[...document.querySelectorAll('[data-change-id]')].filter(a=>a.querySelector('.project-select').checked);
  const feedback=single?single.querySelector('.form-feedback'):document.querySelector('#project-review-feedback');
  const decision=button.dataset.projectReview||button.dataset.projectBatch;
  button.disabled=true;feedback.textContent='변경을 저장 중입니다…';
  try{await api('/api/projects/review','POST',{selections:articles.map(a=>({id:Number(a.dataset.changeId),decision,text:a.querySelector('.project-proposal').value}))});dirty=false;location.reload()}
  catch(error){feedback.textContent=error.message;button.disabled=false}
});
async function submitProjectAI(data, feedback, button) {
  button.disabled=true;
  feedback.classList.remove('is-error');
  feedback.textContent='AI 처리 요청을 등록 중입니다…';
  try {
    const result=await api('/api/project-ai','POST',data);
    dirty=false;
    feedback.textContent='AI가 처리 중입니다. 완료되면 프로젝트로 이동합니다.';
    let count=0;
    const poll=async()=>{
      try {
        const response=await fetch('/api/project-ai/'+encodeURIComponent(result.request_id));
        if(!response.ok)throw Error('처리 상태를 불러오지 못했습니다. 최근 AI 요청에서 확인하세요.');
        const state=await response.json();
        if(state.state==='applied'){location.href='/projects/'+state.project_id+(data.work_item_id?'?view=issues&work_item='+data.work_item_id:'?view=review');return}
        if(state.state==='needs_input'||state.job_state==='failed'){
          feedback.classList.add('is-error');feedback.textContent=state.question||state.error||'처리에 실패했습니다.';button.disabled=false;delete button.dataset.requestKey;return;
        }
        if(++count>=180){feedback.textContent='계속 처리 중입니다. 프로젝트 목록의 최근 AI 요청에서 결과를 확인하세요.';button.disabled=false;return}
        setTimeout(poll,2000);
      }catch(error){feedback.classList.add('is-error');feedback.textContent=error.message;button.disabled=false}
    };
    setTimeout(poll,500);
  }catch(error){feedback.classList.add('is-error');feedback.textContent=error.message;button.disabled=false}
}
document.querySelectorAll('.project-ai-form').forEach(form=>{
  form.addEventListener('input',()=>{dirty=true;delete form.querySelector('button').dataset.requestKey});
  form.addEventListener('submit',event=>{
    event.preventDefault();const button=form.querySelector('button');
    button.dataset.requestKey ||= crypto.randomUUID();
    const data={text:form.elements.text.value,mode:form.elements.mode.value,project_id:Number(form.elements.project_id.value)||null,
      inquiry_ids:[...form.elements.inquiry_ids.selectedOptions].map(option=>option.value),request_key:button.dataset.requestKey};
    if(form.elements.work_item_id)data.work_item_id=Number(form.elements.work_item_id.value);
    submitProjectAI(data,form.querySelector('.form-feedback'),button);
  });
});
document.querySelectorAll('.project-ai-create').forEach(button=>button.addEventListener('click',()=>{
  button.dataset.requestKey ||= crypto.randomUUID();
  submitProjectAI({text:'선택한 문의 내용으로 신규 프로젝트를 만들어줘. 부족한 정보는 TBD로 남겨줘.',mode:'create',inquiry_ids:[button.dataset.inquiry],request_key:button.dataset.requestKey},button.closest('article').querySelector('.form-feedback'),button);
}));

document.querySelectorAll('[data-open-dialog]').forEach(button=>button.addEventListener('click',()=>{
  const dialog=document.getElementById(button.dataset.openDialog);
  dialog.showModal();const input=dialog.querySelector('textarea');
  if(button.dataset.aiPrompt&&!input.value)input.value=button.dataset.aiPrompt;
  input?.focus();
}));
document.querySelectorAll('[data-close-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
function revealHash(){
  const target=document.getElementById(location.hash.slice(1));
  if(!target)return;
  for(let element=target;element;element=element.parentElement)if(element.tagName==='DETAILS')element.open=true;
  target.scrollIntoView({block:'start'});
}
window.addEventListener('hashchange',revealHash);
if(location.hash)revealHash();
try{
  const feedback=sessionStorage.getItem('worktrail-save-feedback');
  if(feedback){sessionStorage.removeItem('worktrail-save-feedback');toast(feedback)}
}catch{}
