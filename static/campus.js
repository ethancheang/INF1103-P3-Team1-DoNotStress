(() => {
  const root = document.getElementById('dns-campus');
  const main = root.querySelector('#ds-main');
  const boot = JSON.parse(document.getElementById('campus-config').textContent);
  let page = boot.page || 'home', step = 0, completed = !!boot.completed;
  let assessment = boot.result || null, busy = false;
  const selected = new Set();
  const recordFilters = {student_id:'', tier:'', cohort_year:''};
  const tiers = ["You're doing ok", 'Worth a check-in', 'Please reach out'];
  let recordsRequest = 0, searchTimer;
  const survey = boot.survey;
  const questions = Object.fromEntries(survey.questions.map(q=>[q.key,q]));
  const answers = Object.fromEntries(survey.questions.map(q=>[q.key,null]));
  Object.assign(answers,{student_id:'',feelings_text:''});
  const chapters = survey.sections.map(section=>section.title);
  const reviewStep = chapters.length;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function plant(g=1){return `<div class="ds-plant" aria-hidden="true" style="--grow:${g}"><div class="ds-stem"><div class="ds-leaf"></div><div class="ds-leaf r"></div><div class="ds-leaf s"></div></div><div class="ds-pot"></div></div>`}
function home(){main.innerHTML=`<div class="ds-hero"><section><span class="ds-pill">✦ A small pause. A fresh perspective.</span><h1>Uni is a lot.<br>Let's check in<br><em style="font-family:Georgia,serif;font-weight:400">with you.</em></h1><p>Sleep, deadlines, life. Make a little room to notice how you're doing — and find your next small step.</p><div class="ds-actions"><button class="ds-primary" data-action="start">Start my check-in <span>↗</span></button><span class="ds-note">11 core questions · 6 chapters<br>Go at your own pace</span></div></section><div class="ds-art ds-companion"><div class="ds-orbit"></div><span class="ds-float a">☾ Rest counts, too.</span><span class="ds-float b">One thing at a time.</span><span class="ds-float c">✦ Showing up is enough.</span>${plant()}<div class="ds-ground"></div><span class="ds-art-label">Meet your little growth buddy</span></div></div><div class="ds-bottom"><section class="ds-feature"><span class="ds-num">01 / NOTICE</span><h3>A check-in, on your terms.</h3><p>Simple taps and sliders. No right answers, no pressure to feel a certain way.</p></section><section class="ds-feature"><span class="ds-num">02 / UNDERSTAND</span><h3>See the bigger picture.</h3><p>Bring your academic load and everyday wellbeing into one view.</p></section><section class="ds-feature"><span class="ds-num">03 / RESET</span><h3>Pick one small next step.</h3><p>Leave with a manageable plan. Grow your plant by taking time for yourself.</p></section></div><section class="ds-research"><h2>Backed by research</h2><p>Every question in this check-in is adapted from established, peer-reviewed questionnaires on stress, sleep, study load, finances and social support.</p><p>Sources: Cohen et al. (1983); Buysse et al. (1989); Bedewy &amp; Gabriel (2015); Prawitz et al. (2006); Zimet et al. (1988).</p></section>`}
function garden(){main.innerHTML=`<div class="ds-garden"><span class="ds-pill">My little garden</span><h2>Growth, without the pressure.</h2><p>Your completed check-in plants a seed.<br>Missing a day never takes anything away.</p><div class="ds-art">${plant(completed?1:.45)}<div class="ds-ground"></div><span class="ds-art-label">${completed?'Your first check-in plant':'Your first seed is waiting'}</span></div><h3>${completed?'1 check-in · 1 moment for you':'A fresh start, whenever you’re ready.'}</h3><p>${completed?'You earned this by checking in — whatever your answers were.':'Take a moment for yourself and watch your first plant grow.'}</p><button class="ds-primary" data-action="${completed?'plan':'start'}">${completed?'Return to my plan':'Plant my first seed →'}</button></div>`}

  function field(label, id, control, help='') {
    return `<div class="ds-field"><label class="ds-label" for="${id}">${label}</label>${control}<div class="ds-help">${help}</div></div>`;
  }
  function answerText(key, value=answers[key]) {
    if(value===null || value===undefined || value==='')return 'Not shared';
    const q=questions[key];
    if(!q)return String(value);
    if(q.options)return `${value} · ${q.options[+value-q.min]}`;
    return `${value} ${q.unit}`;
  }
  function questionControl(q) {
    if(q.kind==='slider' && answers[q.key]===null) answers[q.key]=q.default;
    const value=answers[q.key];
    const helpId=q.key+'-help';
    const title=`<h3 class="ds-q-title" id="${q.key}-title">${q.kind==='slider'?`<label for="${q.key}">${escape(q.prompt)}</label>`:escape(q.prompt)}</h3>`;
    if(q.kind==='slider'){
      const shown=escape(answerText(q.key, value));
      return `<div class="ds-question" id="question-${q.key}">
      ${title}
      <div class="ds-big-value"><output id="${q.key}-value" for="${q.key}" aria-live="polite">${shown}</output></div>
      <input type="range" id="${q.key}" min="${q.min}" max="${q.max}" step="${q.step}" value="${value}" ${q.key==='fin_stress'?`aria-describedby="${helpId}"`:''} aria-valuetext="${shown}">
      <div class="ds-ends"><span>${q.min} · ${escape(q.low)}</span><span>${q.max} · ${escape(q.high)}</span></div>
      ${q.key==='fin_stress'?`<p id="${helpId}" class="ds-help">Higher numbers mean more financial stress.</p>`:''}
      </div>`;
    }
    return `<div class="ds-question" id="question-${q.key}" role="group" aria-labelledby="${q.key}-title">${title}
      <div class="ds-answer-options">${q.options.map((label,i)=>`<label class="ds-answer"><input type="radio" name="${q.key}" value="${i+q.min}" ${answers[q.key]===i+q.min?'checked':''}><span><b>${i+q.min}</b>${escape(label)}</span></label>`).join('')}</div>
      </div>`;
  }
  function safetyPrompt() {
    return `<div class="ds-support ds-support-urgent" role="status"><h3>Please reach out</h3><p>If your words reflect how you feel right now, you deserve support. This basic word check cannot determine your safety.</p><p><a href="tel:65922030">SIT Counselling 24-hour helpline 6592 2030</a><br><a href="tel:1767">Samaritans of Singapore 1767</a><br><a href="tel:1771">National mindline 1771</a></p><a href="mailto:SITCounselling@SingaporeTech.edu.sg">SITCounselling@SingaporeTech.edu.sg</a></div>`;
  }
  function reflectionSafety() {
    const text=answers.feelings_text.toLowerCase().replaceAll('’',"'");
    return survey.safetyPatterns.some(pattern=>new RegExp(pattern,'i').test(text));
  }
  function checkin() {
    let content;
    if(step<reviewStep) {
      const section=survey.sections[step];
      content=`<span class="ds-pill">${escape(section.period)}</span><h2 tabindex="-1" id="ds-step-heading">${escape(section.heading)}</h2><p>${escape(section.intro)}</p>
        <div class="ds-why"><strong>Why this matters</strong><p>${escape(section.why)}</p></div>
        ${step===0?field('Student ID','student_id','<input class="ds-input" id="student_id" inputmode="numeric" maxlength="7" autocomplete="off" placeholder="e.g. 2605581">','7 digits starting with 2. Your student ID stays private.'):''}
        ${section.keys.map(key=>questionControl(questions[key])).join('')}
        ${step===5?field('Anything on your mind about school or life lately? (Optional)','feelings_text','<textarea class="ds-input" id="feelings_text" rows="4" maxlength="2000" placeholder="A space to reflect, if you want it."></textarea>','This space is just for you. It isn\'t scored or saved. If anything you write suggests you might need support right away, we\'ll show you who to contact.'):''}
        <div id="ds-safety">${reflectionSafety()?safetyPrompt():''}</div>`;
    } else {
      content=`<span class="ds-pill">✦ Your check-in, together</span><h2 tabindex="-1" id="ds-step-heading">A moment to look back.</h2><p>Check the time periods and answers below. You can edit any chapter before continuing.</p>
      <p><strong>Student ID:</strong> ${escape(answers.student_id)}</p>
      ${survey.sections.map((section,index)=>`<section class="ds-review-block"><div class="ds-actions"><h3>${escape(section.title)}</h3><button class="ds-link" data-edit-step="${index}">Edit</button></div><p class="ds-help">${escape(section.period)}</p>
      <dl class="ds-summary">${section.keys.map(key=>`<div><dt>${escape(questions[key].prompt)}</dt><dd>${escape(answerText(key))}</dd></div>`).join('')}${index===5?`<div><dt>Reflection</dt><dd>${answers.feelings_text?'Written for you only. It isn\'t scored or saved.':'Skipped'}</dd></div>`:''}</dl></section>`).join('')}
      ${reflectionSafety()?safetyPrompt():''}
      <div class="ds-why"><strong>What happens next</strong><p>After you submit, we'll look at your answers and share a few suggestions that may help. Your student ID and personal reflection stay private. This check-in isn't a diagnosis, and you can choose whether to save your results at the end.</p></div>`;
    }
    main.innerHTML=`<div class="ds-journey"><aside class="ds-rail"><div class="ds-kicker">Your little reset</div>
      ${chapters.map((title,i)=>`<div class="ds-stop ${i===step?'current':i<step?'done':''}"><b>${i<step?'✓':i+1}</b><span>${escape(title)}</span></div>`).join('')}
      <div class="ds-mini ds-companion">${plant(.45+Math.min(step,reviewStep)*.09)}<h3>A little room to grow.</h3><p>Your plant grows with participation, whatever your answers.</p></div></aside>
      <section><div class="ds-kicker">${step===reviewStep?'Review your check-in':`Chapter ${step+1} of ${reviewStep} · ${escape(chapters[step])}`}</div>
      <div class="ds-track" role="progressbar" aria-label="Chapters completed" aria-valuemin="0" aria-valuemax="${reviewStep}" aria-valuenow="${step}"><div style="width:${step/reviewStep*100}%"></div></div>
      ${content}<div class="ds-error" role="alert" id="ds-error"></div><div id="ds-failure-support"></div>
      <div class="ds-form-foot"><button class="ds-secondary" data-action="back">← ${step===0?'Home':'Back'}</button><button class="ds-primary" data-action="next">${step===reviewStep?'Get my check-in':step===reviewStep-1?'Review my check-in':'Continue'} →</button></div></section></div>`;
    if(step===0)main.querySelector('#student_id').value=answers.student_id;
    if(step===5)main.querySelector('#feelings_text').value=answers.feelings_text;
  }
  function supportPanel(advisor) {
    // URLs are constructed from the existing I/O contact fields, never model text.
    const email = String(advisor.email || '');
    const phone = String(advisor.helpline || '').replace(/[^+0-9]/g, '');
    const sos = String(advisor.sos || '1767').replace(/[^+0-9]/g, '');
    const mindline = String(advisor.mindline || '1771').replace(/[^+0-9]/g, '');
    return `<div class="ds-support ${advisor.prominence==='high'?'ds-support-urgent':''}"><h3>${escape(advisor.heading)}</h3>
      <p>${escape(advisor.body)}</p><p>${escape(advisor.cta)}</p>
      <a href="mailto:${escape(email)}">${escape(email)}</a><br>
      <a href="tel:${escape(phone)}">SIT Counselling 24-hour helpline ${escape(advisor.helpline)}</a><br>
      <a href="tel:${escape(sos)}">Samaritans of Singapore ${escape(advisor.sos || '1767')}</a><br>
      <a href="tel:${escape(mindline)}">National mindline ${escape(advisor.mindline || '1771')}</a></div>`;
  }
  function result() {
    if (!assessment) {page='checkin';checkin();return;}
    main.innerHTML = `<span class="ds-pill">✦ Check-in complete</span><div class="ds-result"><section>
      <h2>You don't have to do<br>everything at once.</h2><p>A little perspective, and a small step forward.</p>
      <div class="ds-result-hero" data-risk="${riskClass(assessment.insights?.risk_category)}"><div class="ds-kicker">Your check-in</div><h2>${escape(assessment.soft.heading)}</h2>
      <p>${escape(assessment.soft.body)}</p><div class="ds-note">A wellbeing check-in, not a medical diagnosis.</div></div>
      ${insightsPanel()}
      <h3>${escape(assessment.tips.heading)}</h3><p>Choose what you'd like to try. One is enough to start.</p>
      ${assessment.tips.items.map((tip,i)=>`<button class="ds-task" data-task="${i}" aria-pressed="${selected.has(i)}"><span class="ds-check">${selected.has(i)?'✓':'+'}</span><span>${escape(tip.text)}</span></button>`).join('')}
      <div class="ds-status" aria-live="polite">${selected.size?selected.size+' small step(s) chosen.':'Your plan starts with a choice.'}</div>
      <section class="ds-support"><h3>${assessment.saved?'Saved on this computer':'Keep this check-in?'}</h3>
      ${assessment.saved?'<p>You chose to save this check-in. Saved records are available in the admin view.</p>':'<p>Your result is held temporarily in server memory. Saving writes your questionnaire answers, assessment, and whether a safety prompt was shown to this computer. Reflection text is never saved. Only a signed-in admin can view saved records through this app.</p><label><input type="checkbox" id="ds-opt-in"> I want to save my check-in on this computer for admin review.</label><p></p><button class="ds-secondary" data-action="save">Save my check-in</button>'}
      <div class="ds-error" id="ds-save-status" role="status"></div></section>
      <button class="ds-link" data-action="edit">${answers.student_id?'Review my answers':'Start another check-in'}</button>
      <span> · </span><button class="ds-link" data-action="new">Start fresh</button></section>
      <aside><div class="ds-mini ds-companion">${plant()}<span class="ds-pill">First seed planted</span><h3>You made space for you.</h3>
      <p>No streaks to keep. No scores to beat. Just a little growth, at your pace.</p><button class="ds-link" data-nav="garden">Visit my garden →</button></div>
      ${supportPanel(assessment.advisor)}</aside></div>`;
  }
  function render() {
    if(page==='records' && !boot.isAdmin)page='home';
    root.querySelectorAll('[data-nav]').forEach(button => {
      if(button.dataset.nav===(page==='result'?'checkin':page))button.setAttribute('aria-current','page');
      else button.removeAttribute('aria-current');
    });
    ({home,checkin,result,garden,records}[page] || home)();
  }
  function riskClass(value) {
    return {Low:'low',Moderate:'moderate',High:'high'}[value] || 'unknown';
  }
  function riskBadge(value) {
    return `<span class="ds-risk ds-risk-${riskClass(value)}">${escape(value || 'Unknown')}</span>`;
  }
  function insightsPanel() {
    const info=assessment.insights;
    if(!info)return '';
    return `<section class="ds-insights"><div class="ds-actions"><h3>Your stress picture</h3>${riskBadge(info.risk_category)}</div>
      <div class="ds-score"><strong>${escape(info.stress_score ?? '—')}<small> / 5</small></strong><span>Average stress score · 1 (low) to 5 (high)<br>Across all your answers</span></div>
      <p class="ds-explanation">${escape(info.explanation)}</p>
      <details class="ds-scoring"><summary>How this guidance is calculated</summary><p>Every question uses a 1–5 scale except typical sleep, which you enter in hours. Those hours are converted when scoring (8 or more hours is 1, under 5 hours is 5). Positively worded questions (confident handling personal problems, things going well, and support from friends and family) are reversed as 6 − answer, so a higher number always means more stress. Your score is the average of all 11 answers, each with equal weight. Below 2.5 means you're doing ok, 2.5 to 3.5 is worth a check-in, and above 3.5 means please reach out. Some answers choose which suggestions appear first. A support prompt can show “Please reach out” without changing the score.</p><p>These bands are a simple guide, not clinical cut-offs.</p></details>
      </section><section class="ds-factor-section"><h3>How the pieces fit together</h3><p>These factors provide context and guide your next steps. They do not prove what caused your stress.</p><div class="ds-factor-grid">${(info.factors||[]).map(factor=>`<article class="ds-factor ${factor.flagged?'is-flagged':''}"><div class="ds-actions"><h3>${escape(factor.title)}</h3><span class="ds-pill">${factor.flagged?'Worth some attention':'Context noted'}</span></div><strong>${escape(factor.value)}</strong><p>${escape(factor.text)}</p></article>`).join('')}</div></section>
      ${info.safety_flag?safetyPrompt():''}`;
  }
  function records() {
    if(!boot.isAdmin){page='home';home();return;}
    main.innerHTML=`<section><span class="ds-pill">Check-in history</span><h2>Saved student check-ins.</h2><p>Explore saved records by student, tier, or cohort.</p>
      <div class="ds-record-filters">
        <label>Student ID<input class="ds-input" id="ds-record-search" type="search" inputmode="numeric" placeholder="Search all or part of an ID" value="${escape(recordFilters.student_id)}"></label>
        <label>Tier<select class="ds-input" id="ds-record-tier"><option value="">All tiers</option>${tiers.map(name=>`<option value="${escape(name)}"${name===recordFilters.tier?' selected':''}>${escape(name)}</option>`).join('')}</select></label>
        <label>Cohort year<select class="ds-input" id="ds-record-cohort"><option value="">All cohorts</option>${recordFilters.cohort_year?`<option value="${escape(recordFilters.cohort_year)}" selected>20${escape(recordFilters.cohort_year)}</option>`:''}</select></label>
        <button class="ds-secondary" data-action="clear-filters">Clear Filters</button>
      </div>
      <p class="ds-help">Cohort year uses the first two ID digits (26 → 2026). Dates use Singapore time.</p>
      <div id="ds-record-status" role="status" aria-live="polite"></div>
      <div class="ds-record-table" role="region" aria-label="Saved check-ins table" tabindex="0">
      <table><caption>All saved student check-ins</caption><thead><tr>${['Student ID','Stress score (/5)','Tier','Sleep (hours)','Sleep quality','Workload','Catch-up','Finances','Friends','Family','Status','Date saved'].map(label=>`<th scope="col">${label}</th>`).join('')}</tr></thead><tbody id="ds-record-rows"></tbody></table></div>
      <button class="ds-link" data-action="refresh-records">Refresh records</button></section>`;
    loadRecords();
  }
  function savedDate(value) {
    if(!value)return '—';
    const date=new Date(value);
    if(Number.isNaN(date.getTime()))return 'Unknown date';
    return new Intl.DateTimeFormat('en-SG',{timeZone:'Asia/Singapore',dateStyle:'medium',timeStyle:'short'}).format(date);
  }
  async function loadRecords() {
    if(!boot.isAdmin)return;
    const requestId=++recordsRequest;
    const status=main.querySelector('#ds-record-status');
    if(!status)return;
    status.textContent='Loading records…';
    main.querySelector('#ds-record-rows').innerHTML='';
    try {
      const params=new URLSearchParams(recordFilters);
      const response=await fetch(boot.recordsUrl+'?'+params.toString(),{cache:'no-store'});
      const data=await response.json();
      if(page!=='records'||requestId!==recordsRequest)return;
      if(response.status===401||response.status===403){
        main.querySelector('#ds-record-rows').innerHTML='';
        status.textContent='Your admin session has ended. Please sign in again.';
        location.replace(boot.adminLoginUrl);return;
      }
      if(!response.ok)throw new Error('load');
      const cohort=main.querySelector('#ds-record-cohort');
      cohort.innerHTML='<option value="">All cohorts</option>'+data.cohorts.map(year=>`<option value="${escape(year)}">20${escape(year)}</option>`).join('');
      cohort.value=recordFilters.cohort_year;
      status.textContent=`${data.matching} of ${data.total} saved check-ins`;
      const cell=value=>escape(value===null||value===undefined||value===''?'—':value);
      const opt=(key,value)=>value===null||value===undefined||value===''?'—':cell(value+' · '+questions[key].options[value-questions[key].min]);
      const tierName=row=>row.soft_label||{Low:"You're doing ok",Moderate:'Worth a check-in',High:'Please reach out'}[row.risk_category]||'—';
      main.querySelector('#ds-record-rows').innerHTML=data.records.length?data.records.map(row=>`<tr data-risk="${riskClass(row.risk_category)}"><td>${cell(row.student_id)}</td><td>${cell(row.stress_score)}</td><td><span class="ds-risk ds-risk-${riskClass(row.risk_category)}">${escape(tierName(row))}</span></td><td>${cell(row.sleep_hours_avg)}</td><td>${opt('sleep_quality',row.sleep_quality)}</td><td>${opt('pas_workload',row.pas_workload)}</td><td>${opt('pas_catchup',row.pas_catchup)}</td><td>${opt('fin_stress',row.fin_stress)}</td><td>${opt('mspss_friends',row.mspss_friends)}</td><td>${opt('mspss_family',row.mspss_family)}</td><td>${cell(row.status)}</td><td>${escape(savedDate(row.saved_at))}</td></tr>`).join(''):'<tr><td colspan="12" class="ds-empty">No records found</td></tr>';

    }catch(error){if(page==='records'&&requestId===recordsRequest){status.textContent='Could not load saved records. Use Refresh records to try again.';main.querySelector('#ds-record-rows').innerHTML='';}}
  }
  function valid() {
    let message='', focus;
    if(step===0&&!/^2[0-9]{6}$/.test(answers.student_id.trim())){message='Enter a 7-digit student ID starting with 2.';focus=main.querySelector('#student_id');}
    for(const key of survey.sections[step]?.keys||[]) {
      const q=questions[key], value=answers[key];
      if(value===null||value===''||!Number.isFinite(+value)||+value<q.min||+value>q.max||!Number.isInteger(+value/q.step)) {
        if(!message){message=`Please answer “${q.label}” using the available choices.`;focus=main.querySelector(`#question-${key} input`);}
      }
    }
    main.querySelector('#ds-error').textContent=message;
    if(focus)focus.focus();
    return !message;
  }
  function setBusy(value) {
    busy=value;root.setAttribute('aria-busy',String(value));
    root.querySelectorAll('button,input,textarea,select').forEach(control=>control.disabled=value);
  }
  async function post(url,body) {
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':boot.csrfToken},body:JSON.stringify(body)});
    const data=await response.json();return {response,data};
  }
  async function submit() {
    setBusy(true);
    main.querySelector('#ds-error').textContent='Taking a moment to understand your check-in…';
    main.querySelector('#ds-failure-support').innerHTML='';
    assessment=null;completed=false;selected.clear();
    try {
      const {response,data}=await post(boot.submitUrl,{...answers,student_id:answers.student_id.trim(),feelings_text:answers.feelings_text.trim()});
      if(!response.ok) {
        if(data.errors){const key=Object.keys(data.errors)[0];step=key==='student_id'?0:key==='feelings_text'?5:Math.max(0,survey.sections.findIndex(section=>section.keys.includes(key)));render();}
        main.querySelector('#ds-error').textContent=data.errors?Object.values(data.errors).join(' '):data.message;
        if(data.advisor)main.querySelector('#ds-failure-support').innerHTML=(data.safety_flag?safetyPrompt():'')+supportPanel(data.advisor);
        return;
      }
      assessment=data.result;completed=true;page='result';render();
    } catch(error) {main.querySelector('#ds-error').textContent='Could not connect. Your answers are still here; please try again.';}
    finally {setBusy(false);}
  }
  async function save() {
    const status=main.querySelector('#ds-save-status');
    if(!main.querySelector('#ds-opt-in').checked){status.textContent='Tick the consent box before saving.';return;}
    setBusy(true);
    try {
      const {response,data}=await post(boot.saveUrl,{opt_in:true});
      if(!response.ok){status.textContent=data.message;return;}
      assessment.saved=true;render();
    }catch(error){status.textContent='Could not save your check-in. Please try again.';}
    finally{setBusy(false);}
  }
  root.addEventListener('input',event=>{
    const {id,value}=event.target;
    if(id==='ds-record-search'){recordFilters.student_id=value;clearTimeout(searchTimer);recordsRequest++;searchTimer=setTimeout(()=>{if(page==='records')loadRecords();},200);return;}
    if(questions[id]?.kind==='slider') {
      answers[id]=+value;
      const shown=answerText(id);
      const out=main.querySelector('#'+id+'-value');if(out)out.textContent=shown;
      event.target.setAttribute('aria-valuetext',shown);
    } else if(id==='student_id'||id==='feelings_text') {
      answers[id]=value;
      if(id==='feelings_text')main.querySelector('#ds-safety').innerHTML=reflectionSafety()?safetyPrompt():'';
    }
  });
  root.addEventListener('change',event=>{
    if(questions[event.target.name]&&event.target.type==='radio')answers[event.target.name]=+event.target.value;
    if(event.target.id==='ds-record-tier'){recordFilters.tier=event.target.value;loadRecords();}
    if(event.target.id==='ds-record-cohort'){recordFilters.cohort_year=event.target.value;loadRecords();}
  });
  root.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button||busy)return;
    if(button.dataset.editStep!==undefined){step=+button.dataset.editStep;checkin();main.querySelector('#ds-step-heading').focus();return;}
    if(button.dataset.nav){page=button.dataset.nav;render();return;}
    if(button.dataset.task!==undefined){const id=+button.dataset.task;selected.has(id)?selected.delete(id):selected.add(id);render();return;}
    switch(button.dataset.action){
      case 'clear-filters':clearTimeout(searchTimer);Object.keys(recordFilters).forEach(key=>recordFilters[key]='');records();return;
      case 'refresh-records':loadRecords();return;
      case 'start':page='checkin';break;
      case 'plan':page=assessment?'result':'checkin';break;
      case 'back':if(step===0)page='home';else step--;break;
      case 'next':if(!valid())return;if(step<reviewStep)step++;else{await submit();return;}break;
      case 'edit':page='checkin';step=answers.student_id?reviewStep:0;break;
      case 'save':await save();return;
      case 'new':location.assign(boot.newUrl);return;
      default:return;
    }
    render();
    if(page==='checkin')main.querySelector('#ds-step-heading')?.focus();
  });
  // Clear sensitive table rows before a page can enter the back/forward cache.
  window.addEventListener('pagehide',()=>{
    if(page==='records'){recordsRequest++;main.querySelector('#ds-record-rows').innerHTML='';}
  });
  window.addEventListener('pageshow',event=>{
    if(event.persisted&&boot.isAdmin)location.reload();
  });
  document.addEventListener('visibilitychange',()=>{
    if(page==='records'&&!document.hidden)loadRecords();
  });
  render();
})();
