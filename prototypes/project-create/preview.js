/* Standalone prototype: example data stays in memory. No API or filesystem calls. */
const $ = selector => document.querySelector(selector);
const sample = {
  name: 'Atlas GPIO Library 개발',
  purpose: '28nm 공정용 GPIO library를 개발합니다. cell별 회로 설계와 PVT 검증을 마친 뒤, 검증된 library와 sign-off 보고서를 전달합니다.',
  process: '28nm', target: 'GPIO Library · 1.8V / 3.3V', owner: 'Library 개발팀',
  date: '2027-03-31', start: '2026-11-10', spec: 'I/O 1.8V / 3.3V\n온도 −40~125°C\nPVT 9 corners'
};
const examples = [
  {code: 'JOB-028', ...sample, issues: 28, state: '진행 중'},
  {code: 'JOB-041', name: 'Orion ADC 검증', purpose: '65nm ADC의 PVT 시뮬레이션과 노이즈 분석 결과를 검증 보고서로 정리합니다.', owner: 'Analog 검증팀', date: '2027-02-24', issues: 3, state: '진행 중'},
  {code: 'JOB-046', name: 'Vega PLL 평가', purpose: '90nm PLL의 평가 조건을 정리하고 특성 평가 결과를 전달합니다.', owner: '평가 담당팀', date: '2027-04-10', issues: 5, state: '보류'}
];
const history = [
  {request:'GPIO 1.8V 계열 검증 결과 정리', project:sample.name, state:'완료', time:'오늘 10:24'},
  {request:'PVT 검증 조건을 프로젝트 Spec에 추가', project:sample.name, state:'완료', time:'오늘 09:40'},
  {request:'메일에서 개발 범위와 산출물 정리', project:'Orion ADC 검증', state:'추가 정보 필요', time:'어제 16:12'}
];
const prompts = {
  create:'Nova DAC 개발 프로젝트를 만들어줘. 40nm 공정에서 DAC 회로 설계와 PVT 검증을 진행하고, 2027년 6월 30일까지 검증 보고서를 전달해. 담당은 Analog 개발팀이야.',
  update:'Atlas GPIO Library의 목표 일정을 2027년 4월 15일로 바꾸고, GPIO_BIDIR_3V3 하위 이슈에 PVT 검증 시작일 12월 7일을 추가해줘.',
  search:'3.3V GPIO cell을 개발하는 프로젝트를 찾아서 목적과 하위 이슈를 알려줘.',
  auto:'아래 내용이 기존 프로젝트에 해당하는지 찾아줘. 있으면 검증 일정을 업데이트하고, 없으면 새 프로젝트를 만들어줘.\n28nm Atlas GPIO Library · 3.3V 계열 PVT 검증은 12월 7일 시작, 기존 testbench 조건 유지.'
};
const controls = Object.fromEntries([...$('#details-form').elements].filter(e => e.name).map(e => [e.name, e]));
const scrollPositions = new Map();
const initialOutput = $('#ai-output-body').innerHTML;
let currentRoute = '', pendingRun = 0, proposal = null;
const escapeHtml = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const values = () => Object.fromEntries(Object.entries(controls).map(([name, input]) => [name, input.value.trim()]));

function updateSummary() {
  const data = values();
  $('#summary-name').textContent = data.name || '새 프로젝트';
  $('#summary-purpose').textContent = data.purpose || '프로젝트 이름과 목적을 입력하면 이곳에서 한눈에 확인할 수 있습니다.';
  $('#summary-purpose').classList.toggle('muted', !data.purpose);
  document.querySelectorAll('[data-summary]').forEach(el => el.textContent = data[el.dataset.summary] || (el.dataset.summary === 'date' ? '미정' : '미지정'));
  $('#summary-spec-block').hidden = !data.spec;
  $('#summary-spec').textContent = data.spec || '';
}
function clearErrors(scope) {
  scope.querySelectorAll('.field-error').forEach(e => { e.hidden = true; e.textContent = ''; });
  scope.querySelectorAll('[aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
}
function renderList() {
  const query = $('#project-search').value.trim().toLowerCase(), state = $('#project-state').value;
  const rows = examples.filter(p => (!query || (p.code + p.name + p.purpose).toLowerCase().includes(query)) && (!state || p.state === state));
  $('#result-count').textContent = rows.length === examples.length ? `전체 ${rows.length}개` : `검색 결과 ${rows.length}개`;
  $('#no-results').hidden = !!rows.length;
  $('#project-rows').innerHTML = rows.map(p => `<tr><td><span class="project-code">${escapeHtml(p.code)}</span><strong>${escapeHtml(p.name)}</strong><p class="row-excerpt">${escapeHtml(p.purpose)}</p>${p.issueNote ? `<p class="row-update">하위 이슈 · ${escapeHtml(p.issueNote)}</p>` : ''}</td><td><span class="status-label">${escapeHtml(p.state)}</span></td><td>${escapeHtml(p.owner)}</td><td>${escapeHtml(p.date)}</td><td>${p.issues}개</td></tr>`).join('');
}
function renderHistory() {
  $('#history-count').textContent = `최근 요청 ${history.length}건`;
  $('#history-rows').innerHTML = history.map(h => `<tr><td>${escapeHtml(h.request)}</td><td>${escapeHtml(h.project)}</td><td><span class="${h.state === '추가 정보 필요' ? 'entry-origin' : 'status-label'}">${h.state}</span></td><td>${h.time}</td></tr>`).join('');
}
function renderTargets() {
  const selected = $('#ai-target').value;
  $('#ai-target').innerHTML = '<option value="auto">요청 내용에서 찾기</option><option value="new">새 프로젝트</option>' + examples.map(p => `<option value="${p.code}">${escapeHtml(p.code + ' · ' + p.name)}</option>`).join('');
  $('#ai-target').value = selected || 'auto';
}
function renderResult() {
  const data = values();
  $('#result-name').textContent = data.name;
  $('#result-purpose').textContent = data.purpose;
  $('#result-facts').innerHTML = [['process','공정'],['target','개발 대상'],['owner','담당자'],['date','목표 일정'],['spec','Spec']].map(([key,label]) => `<div><dt>${label}</dt><dd class="project-text">${escapeHtml(data[key] || '미지정')}</dd></div>`).join('');
}
function route(moveFocus = true) {
  if (currentRoute) scrollPositions.set(currentRoute, window.scrollY);
  currentRoute = location.hash.slice(1) || '/projects';
  const [path, query = ''] = currentRoute.split('?');
  if (path === '/projects/new' && new URLSearchParams(query).get('method') === 'ai') { location.replace('#/projects/ai'); return; }
  const destination = path === '/projects/new' || path === '/projects/preview' ? 'new' : path.endsWith('/ai') ? 'ai' : path.endsWith('/connections') ? 'connections' : path.endsWith('/history') ? 'history' : 'list';
  $('#directory-screen').hidden = !['list','connections','history'].includes(destination);
  $('#create-screen').hidden = path !== '/projects/new';
  $('#result-screen').hidden = path !== '/projects/preview';
  $('#ai-screen').hidden = destination !== 'ai';
  for (const key of ['list','connections','history']) $(`#${key}-panel`).hidden = key !== destination;
  document.querySelectorAll('[data-destination]').forEach(link => {
    if (link.dataset.destination === destination) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
  if (path === '/projects/preview') renderResult();
  renderList(); renderHistory(); updateSummary();
  const title = document.querySelector(`[data-destination="${destination}"]`).textContent.trim();
  document.title = `WorkTrail · ${title} 미리보기`;
  if (moveFocus) $('#main').focus({preventScroll:true});
  window.scrollTo(0, scrollPositions.get(currentRoute) || 0);
}
function setBusy(busy) {
  $('#ai-submit').disabled = busy;
  $('#ai-submit').textContent = busy ? '예시 준비 중…' : '요청 실행';
  $('.ai-output').setAttribute('aria-busy', String(busy));
}
function resetAI() {
  pendingRun++; proposal = null; setBusy(false); clearErrors($('#ai-form'));
  $('#ai-form').reset(); $('#ai-progress').textContent = '';
  $('#ai-result-kind').textContent = '요청 대기'; $('#ai-output-body').innerHTML = initialOutput;
  $('#ai-request').focus();
}
function matchProjects(request, target) {
  if (!['auto','new'].includes(target)) return examples.filter(p => p.code === target);
  if (target === 'new') return [];
  const keys = ['GPIO','Atlas','ADC','Orion','PLL','Vega','DAC','Nova', ...examples.map(p => p.code)];
  const found = keys.filter(key => request.toLowerCase().includes(key.toLowerCase()));
  return examples.filter(p => found.some(key => (p.code + p.name).toLowerCase().includes(key.toLowerCase())));
}
function dateFrom(request, fallback) {
  const m = request.match(/(20\d{2})[년\s./-]+(\d{1,2})[월\s./-]+(\d{1,2})/);
  if (!m) return fallback;
  const value = `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  const date = new Date(value + 'T00:00:00Z');
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0,10) === value ? value : fallback;
}
function requestDetail(request) {
  return `<details class="ai-request-detail"><summary>요청 원문</summary><p>${escapeHtml(request)}</p></details>`;
}
function showAIResult(request, target, reference) {
  const context = request + (reference ? '\n' + $('#ai-reference').closest('label').textContent + '\n' + $('#reference-preview').textContent : '');
  const matches = matchProjects(context, target);
  const conditional = /없으면|있으면|해당하는지|기존.*찾.*만들/.test(request);
  const search = !conditional && /찾|검색|알려/.test(request) && !/수정|업데이트|바꾸|변경|추가|만들|생성/.test(request);
  const create = target === 'new' || (!conditional && /만들|생성|신규/.test(request));
  const update = /수정|업데이트|바꾸|변경|추가/.test(request);
  const body = $('#ai-output-body');
  proposal = null;
  if (search) {
    $('#ai-result-kind').textContent = '프로젝트 검색';
    body.innerHTML = `<p class="ai-decision">검색 결과 예시 <strong>${matches.length}개</strong></p>` + (matches.length ? matches.map(p => `<article class="ai-match"><span class="project-code">${escapeHtml(p.code)} · ${p.state}</span><h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.purpose)}</p><dl class="match-facts"><div><dt>목표 일정</dt><dd>${p.date}</dd></div><div><dt>하위 이슈</dt><dd>${p.issues}개</dd></div></dl>${p.code === 'JOB-028' ? '<p class="match-evidence">일치 단서 · GPIO Library, 3.3V cell<br>하위 이슈 · GPIO_BIDIR_1V8 / GPIO_BIDIR_3V3 / PVT 검증 외</p>' : ''}<button type="button" data-use-project="${p.code}">이 프로젝트에 요청하기</button></article>`).join('') : '<div class="ai-empty compact"><h3>일치하는 예시 프로젝트가 없습니다</h3><p>다른 이름으로 요청하거나, 이 내용으로 새 프로젝트를 만드는 흐름을 볼 수 있습니다.</p><button type="button" id="ai-create-from-search">이 내용으로 생성 요청</button></div>') + requestDetail(request);
    body.querySelectorAll('[data-use-project]').forEach(b => b.addEventListener('click', () => {
      $('#ai-target').value = b.dataset.useProject;
      $('#ai-request').value = `${examples.find(p => p.code === b.dataset.useProject).name}의 수정할 내용을 정리해줘.\n`;
      $('#ai-request').focus(); $('#ai-progress').textContent = '대상 프로젝트를 선택했습니다. 수정할 내용을 이어서 적어 주세요.';
    }));
    $('#ai-create-from-search')?.addEventListener('click', () => { $('#ai-target').value = 'new'; $('#ai-request').value = `다음 내용으로 새 프로젝트를 만들어줘.\n${request}`; $('#ai-request').focus(); });
  } else if ((create || (conditional && !matches.length)) && !(['auto','new'].includes(target))) {
    $('#ai-result-kind').textContent = '대상 확인 필요';
    body.innerHTML = '<div class="ai-empty compact"><h3>새 프로젝트를 만들 요청인가요?</h3><p>현재 기존 프로젝트가 선택되어 있습니다. 대상을 “새 프로젝트”로 바꾸거나, 수정할 내용을 요청해 주세요.</p><button type="button" id="ai-fix-target">대상 선택으로 이동</button></div>';
    $('#ai-fix-target').addEventListener('click', () => $('#ai-target').focus());
  } else if (create || (conditional && !matches.length)) {
    $('#ai-result-kind').textContent = conditional ? '일치 항목 없음 → 신규 생성' : '신규 프로젝트 생성';
    const name = /Nova|DAC/i.test(request) ? 'Nova DAC 개발' : (request.split('\n').filter(line => !/찾아|없으면|만들어|생성 요청/.test(line)).pop() || '새 프로젝트').slice(0,100);
    proposal = {kind:'create', request, name, date:dateFrom(request,'2027-06-30'), purpose:/Nova|DAC/i.test(request) ? '40nm DAC 회로 설계와 PVT 검증을 완료하고 검증 보고서를 전달합니다.' : request, owner:/Nova|DAC/i.test(request) ? 'Analog 개발팀' : '미지정'};
    body.innerHTML = `<p class="ai-decision">${conditional ? '예시 프로젝트에서 일치 항목이 없어 새로 만드는 흐름입니다.' : '새 프로젝트 1개를 만드는 예시입니다.'}</p><div class="ai-proposal creation-editor"><span class="project-code">신규 생성안</span><label for="proposal-name">프로젝트 이름</label><input id="proposal-name" value="${escapeHtml(name)}" maxlength="300"><label for="proposal-purpose">목적·산출물</label><textarea id="proposal-purpose" maxlength="5000">${escapeHtml(proposal.purpose)}</textarea><label for="proposal-date">목표 일정</label><input id="proposal-date" type="date" value="${proposal.date}"><p class="match-evidence">담당 · ${proposal.owner}</p></div>${requestDetail(request)}${applyActions()}`;
  } else if ((update || conditional) && matches.length === 1) {
    const project = matches[0];
    const note = project.code === 'JOB-028' ? 'GPIO_BIDIR_3V3 · PVT 검증 12월 7일 시작. 기존 testbench 조건 유지.' : context;
    const issueChange = /이슈|cell|검증|testbench/.test(context);
    const newDate = /목표.*일정|목표일|마감/.test(request) ? dateFrom(request,project.date) : project.date;
    proposal = {kind:'update',request,code:project.code,date:newDate,issueNote:issueChange ? note : null};
    $('#ai-result-kind').textContent = conditional ? '기존 프로젝트 일치 → 업데이트' : '기존 프로젝트 업데이트';
    body.innerHTML = `<p class="ai-decision">${conditional ? '일치하는 기존 프로젝트에 내용을 추가하는 예시입니다.' : '선택한 프로젝트의 변경 전후를 확인하세요.'}</p><div class="ai-project-context"><span class="project-code">${project.code}</span><h3>${escapeHtml(project.name)}</h3><p>${target === 'auto' ? '일치 단서 · ' + escapeHtml(project.name) + (reference ? ' · 참고 문의' : '') : '직접 선택한 대상 프로젝트'}</p></div><div class="change-heading"><h3>변경 내용</h3><span>${issueChange && newDate !== project.date ? '2개 항목' : '1개 항목'}</span></div>${newDate !== project.date || !issueChange ? `<div class="ai-change"><h4>프로젝트 · 목표 일정</h4><div class="change-before"><span>현재</span><p>${project.date}</p></div><label for="proposal-date">변경 후</label><input id="proposal-date" type="date" value="${newDate}"></div>` : ''}${issueChange ? `<div class="ai-change"><h4>하위 이슈 · ${project.code === 'JOB-028' ? 'GPIO_BIDIR_3V3' : '검증 기록'}</h4><div class="change-before"><span>현재</span><p>${escapeHtml(project.issueNote || 'PVT 검증 일정 미기록')}</p></div><label for="proposal-note">추가할 내용</label><textarea id="proposal-note" maxlength="5000">${escapeHtml(note)}</textarea></div>` : ''}${requestDetail(request)}${applyActions()}`;
  } else {
    $('#ai-result-kind').textContent = '추가 정보 필요';
    body.innerHTML = `<div class="ai-empty compact"><h3>${matches.length > 1 ? '수정할 프로젝트를 선택해 주세요' : '대상과 작업을 조금 더 알려 주세요'}</h3><p>대상 프로젝트를 선택하고, 변경할 일정이나 추가할 내용을 적어 주세요. 신규 생성·수정·검색 예시도 사용할 수 있습니다.</p><button type="button" id="ai-clarify">요청 이어서 작성</button></div>${requestDetail(request)}`;
    $('#ai-clarify').addEventListener('click', () => $('#ai-request').focus());
  }
  $('#ai-apply')?.addEventListener('click', applyProposal);
  $('#ai-revise')?.addEventListener('click', () => $('#ai-request').focus());
  $('#ai-output-title').focus({preventScroll: true});
  if (matchMedia('(max-width:850px)').matches) $('.ai-output').scrollIntoView({block:'start'});
}
function applyActions() {
  return '<p id="proposal-error" class="field-error" role="alert" hidden></p><div class="ai-result-actions"><button type="button" class="primary" id="ai-apply">예시 반영</button><button type="button" id="ai-revise">요청 수정</button></div><p class="action-note">이 미리보기의 목록과 이력에만 반영됩니다.</p><p id="ai-apply-feedback" class="prototype-feedback" role="status"></p>';
}
function applyProposal() {
  if (!proposal) return;
  let project;
  const dateInput = $('#proposal-date');
  if (proposal.kind === 'create' && (!$('#proposal-name').value.trim() || !$('#proposal-purpose').value.trim())) {
    $('#proposal-error').textContent = '프로젝트 이름과 목적·산출물을 입력하세요.'; $('#proposal-error').hidden = false;
    (!$('#proposal-name').value.trim() ? $('#proposal-name') : $('#proposal-purpose')).focus(); return;
  }
  if (proposal.kind === 'create') {
    project = {code:`JOB-${String(47 + examples.length - 3).padStart(3,'0')}`, name:$('#proposal-name').value.trim(), purpose:$('#proposal-purpose').value.trim(), date:dateInput.value || '미정', owner:proposal.owner, issues:0, state:'진행 중'};
    examples.unshift(project);
  } else {
    project = examples.find(p => p.code === proposal.code);
    if (dateInput) project.date = dateInput.value || '미정';
    if ($('#proposal-note')) project.issueNote = $('#proposal-note').value.trim();
  }
  history.unshift({request:proposal.request, project:project.name, state:'예시 반영', time:'방금'});
  renderTargets(); renderList(); renderHistory();
  $('#proposal-error').hidden = true;
  $('#ai-apply').disabled = true; $('#ai-apply').textContent = '예시 반영됨';
  $('#ai-apply-feedback').innerHTML = '화면에 반영했습니다. <a href="#/projects" id="ai-view-list">목록에서 보기</a> · <a href="#/projects/history">작업 이력 보기</a>';
  $('#ai-view-list').addEventListener('click', () => { $('#project-search').value = project.code; $('#project-state').value = ''; });
  proposal = null;
}
$('#list-filter').addEventListener('submit', event => { event.preventDefault(); renderList(); });
$('#details-form').addEventListener('input', () => { clearErrors($('#details-form')); updateSummary(); });
$('#fill-example').addEventListener('click', () => { Object.entries(sample).forEach(([k,v]) => controls[k].value = v); clearErrors($('#details-form')); updateSummary(); });
$('#details-form').addEventListener('submit', event => {
  event.preventDefault(); clearErrors($('#details-form'));
  const data = values(); let firstInvalid;
  for (const [key, errorId, message] of [['name','name-error','프로젝트 이름을 입력하세요.'],['purpose','purpose-error','목적이나 전달할 산출물을 입력하세요.']]) {
    if (!data[key]) { controls[key].setAttribute('aria-invalid','true'); $(`#${errorId}`).textContent = message; $(`#${errorId}`).hidden = false; firstInvalid ||= controls[key]; }
  }
  if (firstInvalid) { $('#form-feedback').textContent = '필수 입력 항목을 확인하세요.'; $('#form-feedback').hidden = false; firstInvalid.focus(); return; }
  location.hash = '/projects/preview';
});
$('#ai-reset').addEventListener('click', resetAI);
document.querySelectorAll('[data-ai-example]').forEach(button => button.addEventListener('click', () => {
  resetAI(); $('#ai-request').value = prompts[button.dataset.aiExample];
  $('#ai-target').value = button.dataset.aiExample === 'update' ? 'JOB-028' : button.dataset.aiExample === 'create' ? 'new' : 'auto';
  $('#ai-request').focus();
}));
$('#ai-form').addEventListener('submit', event => {
  event.preventDefault(); clearErrors($('#ai-form'));
  const request = $('#ai-request').value.trim(), target = $('#ai-target').value, reference = $('#ai-reference').checked;
  if (!request) { $('#ai-error').textContent = '요청할 작업이나 참고할 내용을 입력하세요.'; $('#ai-error').hidden = false; $('#ai-request').setAttribute('aria-invalid','true'); $('#ai-request').focus(); return; }
  const run = ++pendingRun; proposal = null; setBusy(true);
  $('#ai-progress').textContent = '요청에 맞는 결과 예시를 준비하고 있습니다.';
  $('#ai-result-kind').textContent = '예시 준비 중'; $('#ai-output-body').innerHTML = '<p class="ai-loading">프로젝트와 변경 내용 예시를 준비하고 있습니다…</p>';
  setTimeout(() => { if (run !== pendingRun) return; setBusy(false); $('#ai-progress').textContent = '결과 예시를 준비했습니다. 실제 AI는 실행하지 않았습니다.'; showAIResult(request,target,reference); }, 450);
});
document.querySelectorAll('[data-demo-notice]').forEach(button => button.addEventListener('click', () => button.closest('article').querySelector('[role=status]').textContent = button.dataset.demoNotice));
window.addEventListener('hashchange', () => route());
$('.skip-link').addEventListener('click', event => { event.preventDefault(); $('#main').focus(); window.scrollTo(0,0); });
renderTargets(); route(false);
