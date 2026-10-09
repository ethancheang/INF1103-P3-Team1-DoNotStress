(() => {
  const root = document.getElementById('dns-campus');
  const main = root.querySelector('#ds-main');
  const boot = JSON.parse(document.getElementById('campus-config').textContent);
  let page = boot.page || 'home', step = 0, completed = !!boot.completed;
  let assessment = boot.result || null, busy = false;
  const selected = new Set();
  const answers = {student_id:'', sleep_hours:7, stress_level:5, academic_workload:5,
    financial_stress:5, social_support:5, feelings_text:''};
  const scales = ['stress_level', 'academic_workload', 'financial_stress', 'social_support'];
  const chapters = ['Your starting point', 'Rest & recharge', 'Campus life', 'What’s on your mind'];
  const labels = {student_id:'Student ID', sleep_hours:'Sleep last night', stress_level:'Self-reported stress',
    academic_workload:'Academic workload', financial_stress:'Financial stress', social_support:'Social support', feelings_text:'On your mind'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function plant(g=1){return `<div class="ds-plant" aria-hidden="true" style="--grow:${g}"><div class="ds-stem"><div class="ds-leaf"></div><div class="ds-leaf r"></div><div class="ds-leaf s"></div></div><div class="ds-pot"></div></div>`}
function footer(){return '<footer class="ds-footer"><span>A little space for you, between everything else.</span><span>DoNotStress · Student wellbeing</span></footer>'}
function home(){main.innerHTML=`<div class="ds-hero"><section><span class="ds-pill">✦ A small pause. A fresh perspective.</span><h1>Uni is a lot.<br>Let's check in<br><em style="font-family:Georgia,serif;font-weight:400">with you.</em></h1><p>Sleep, deadlines, life. Make a little room to notice how you're doing — and find your next small step.</p><div class="ds-actions"><button class="ds-primary" data-action="start">Start my check-in <span>↗</span></button><span class="ds-note">4 short chapters<br>Go at your own pace</span></div></section><div class="ds-art ds-companion"><div class="ds-orbit"></div><span class="ds-float a">☾ Rest counts, too.</span><span class="ds-float b">One thing at a time.</span><span class="ds-float c">✦ Showing up is enough.</span>${plant()}<div class="ds-ground"></div><span class="ds-art-label">Meet your little growth buddy</span></div></div><div class="ds-bottom"><section class="ds-feature"><span class="ds-num">01 / NOTICE</span><h3>A check-in, on your terms.</h3><p>Simple taps and sliders. No right answers, no pressure to feel a certain way.</p></section><section class="ds-feature"><span class="ds-num">02 / UNDERSTAND</span><h3>See the bigger picture.</h3><p>Bring your academic load and everyday wellbeing into one view.</p></section><section class="ds-feature"><span class="ds-num">03 / RESET</span><h3>Pick one small next step.</h3><p>Leave with a manageable plan. Grow your plant by taking time for yourself.</p></section></div>${footer()}`}
function garden(){main.innerHTML=`<div class="ds-garden"><span class="ds-pill">My little garden</span><h2>Growth, without the pressure.</h2><p>Your completed check-in plants a seed.<br>Missing a day never takes anything away.</p><div class="ds-art">${plant(completed?1:.45)}<div class="ds-ground"></div><span class="ds-art-label">${completed?'Your first check-in plant':'Your first seed is waiting'}</span></div><h3>${completed?'1 check-in · 1 moment for you':'A fresh start, whenever you’re ready.'}</h3><p>${completed?'You earned this by checking in — whatever your answers were.':'Take a moment for yourself and watch your first plant grow.'}</p><button class="ds-primary" data-action="${completed?'plan':'start'}">${completed?'Return to my plan':'Plant my first seed →'}</button></div>${footer()}`}

  function field(label, id, control, help='') {
    return `<div class="ds-field"><label class="ds-label" for="${id}">${label}</label>${control}<div class="ds-help">${help}</div></div>`;
  }
  function slider(id, prompt, low, high) {
    return field(prompt, id, `<div class="ds-big-value"><output id="${id}-value" for="${id}">${answers[id]}</output> <span>out of 10</span></div>
      <input type="range" id="${id}" name="${id}" min="1" max="10" step="1" value="${answers[id]}" aria-valuetext="${answers[id]} out of 10">
      <div class="ds-ends"><span>1 · ${low}</span><span>10 · ${high}</span></div>`, 'Slide to the number that feels closest. Starts at 5; adjust it or keep it.');
  }
  function checkin() {
    let content;
    if (step === 0) content = `<h2>First, how are you arriving?</h2><p>No need to put on a brave face here.</p>
      ${field('Student ID', 'student_id', '<input class="ds-input" id="student_id" inputmode="numeric" autocomplete="off" placeholder="e.g. 2605581">', '7 digits, starting with 23, 24, 25, or 26.')}
      ${slider('stress_level', 'How stressed have you been feeling?', 'Low stress', 'High stress')}`;
    if (step === 1) content = `<span class="ds-pill">☾ Recharge check</span><h2>How was last night's rest?</h2>
      <p>Count the hours you slept, even if your schedule was a little all over the place.</p>
      <div class="ds-big-value"><output id="ds-sleep-out">${answers.sleep_hours}</output> <span>hours of sleep</span></div>
      ${field('Sleep hours last night', 'sleep_hours', `<input type="range" id="sleep_hours" min="0" max="24" step="0.5" value="${answers.sleep_hours}"><div class="ds-ends"><span>0 hours</span><span>24 hours</span></div>`)}
      ${field('Fine-tune your hours', 'sleep_exact', `<input class="ds-input" id="sleep_exact" type="number" min="0" max="24" step="0.5" value="${answers.sleep_hours}">`, 'Use half-hour steps, such as 6, 6.5, or 7 hours.')}`;
    if (step === 2) content = `<h2>Let's unpack your campus load.</h2><p>Deadlines and the people around you are part of the picture.</p>
      ${slider('academic_workload', 'How heavy has your academic workload felt?', 'Light', 'Very heavy')}
      ${slider('social_support', 'How supported have you felt by people around you?', 'Little support', 'Very supported')}`;
    if (step === 3) content = `<h2>Anything else taking up space?</h2><p>Student life is more than your timetable.</p>
      ${slider('financial_stress', 'How stressed have you been about money?', 'Low stress', 'High stress')}
      ${field('In your own words, how have you been feeling about school lately?', 'feelings_text', '<textarea class="ds-input" id="feelings_text" rows="4" placeholder="You can put it into words here."></textarea>', 'Optional. You can leave this blank.')}`;
    if (step === 4) content = `<span class="ds-pill">✦ All four chapters complete</span><h2>A moment to look back.</h2>
      <p>Here's what you shared. You can go back to change anything.</p><dl class="ds-summary">${Object.entries(labels).map(([key,label]) =>
        `<div><dt>${label}</dt><dd>${escape(answers[key] === '' ? 'Not shared' : answers[key])}${scales.includes(key)?'/10':key==='sleep_hours'?' hours':''}</dd></div>`).join('')}</dl>
      <div class="ds-help">When you continue, your check-in answers are sent to Gemini for an AI-assisted assessment. Results are not a medical diagnosis. Your record is only saved to disk if you choose to save it afterwards.</div>`;
    main.innerHTML = `<div class="ds-journey"><aside class="ds-rail"><div class="ds-kicker">Your little reset</div>
      ${chapters.map((title,i)=>`<div class="ds-stop ${i===step?'current':i<step?'done':''}"><b>${i<step?'✓':i+1}</b><span>${title}</span></div>`).join('')}
      <div class="ds-mini ds-companion">${plant(.45+Math.min(step,4)*.14)}<h3>A little room to grow.</h3><p>Your plant grows as you check in. Every answer counts equally.</p></div></aside>
      <section><div class="ds-kicker">${step===4?'Review your check-in':`Chapter ${step+1} of 4 · ${chapters[step]}`}</div>
      <div class="ds-track" role="progressbar" aria-label="Chapters completed" aria-valuemin="0" aria-valuemax="4" aria-valuenow="${step}"><div style="width:${step*25}%"></div></div>
      ${content}<div class="ds-error" role="alert" id="ds-error"></div><div id="ds-failure-support"></div>
      <div class="ds-form-foot"><button class="ds-secondary" data-action="back">← ${step===0?'Overview':'Back'}</button>
      <button class="ds-primary" data-action="next">${step===4?'Get my check-in':step===3?'Review my check-in':'Continue'} →</button></div></section></div>${footer()}`;
    if (step === 0) main.querySelector('#student_id').value = answers.student_id;
    if (step === 3) main.querySelector('#feelings_text').value = answers.feelings_text;
  }
  function supportPanel(advisor) {
    // URLs are constructed from the existing I/O contact fields, never model text.
    const email = String(advisor.email || '');
    const phone = String(advisor.helpline || '').replace(/[^+0-9]/g, '');
    return `<div class="ds-support ${advisor.prominence==='high'?'ds-support-urgent':''}"><h3>${escape(advisor.heading)}</h3>
      <p>${escape(advisor.body)}</p><p>${escape(advisor.cta)}</p>
      <a href="mailto:${escape(email)}">${escape(email)}</a><br><a href="tel:${escape(phone)}">${escape(advisor.helpline)}</a></div>`;
  }
  function result() {
    if (!assessment) {page='checkin';checkin();return;}
    main.innerHTML = `<span class="ds-pill">✦ Check-in complete</span><div class="ds-result"><section>
      <h2>You don't have to do<br>everything at once.</h2><p>A little perspective, and a small step forward.</p>
      <div class="ds-result-hero"><div class="ds-kicker">Your AI-assisted check-in</div><h2>${escape(assessment.soft.heading)}</h2>
      <p>${escape(assessment.soft.body)}</p><div class="ds-note">A wellbeing check-in, not a medical diagnosis.</div></div>
      <h3>${escape(assessment.tips.heading)}</h3><p>Choose what you'd like to try. One is enough to start.</p>
      ${assessment.tips.items.map((tip,i)=>`<button class="ds-task" data-task="${i}" aria-pressed="${selected.has(i)}"><span class="ds-check">${selected.has(i)?'✓':'+'}</span><span>${escape(tip.text)}</span></button>`).join('')}
      <div class="ds-status" aria-live="polite">${selected.size?selected.size+' small step(s) chosen.':'Your plan starts with a choice.'}</div>
      <section class="ds-support"><h3>${assessment.saved?'Saved on this computer':'Keep this check-in?'}</h3>
      ${assessment.saved?'<p>You chose to save this check-in.</p>':'<p>Your result is held temporarily in server memory. Saving writes the check-in and assessment to this computer.</p><label><input type="checkbox" id="ds-opt-in"> I want to save my check-in on this computer.</label><p></p><button class="ds-secondary" data-action="save">Save my check-in</button>'}
      <div class="ds-error" id="ds-save-status" role="status"></div></section>
      <button class="ds-link" data-action="edit">${answers.student_id?'Review my answers':'Start another check-in'}</button>
      <span> · </span><button class="ds-link" data-action="new">Start fresh</button></section>
      <aside><div class="ds-mini ds-companion">${plant()}<span class="ds-pill">First seed planted</span><h3>You made space for you.</h3>
      <p>No streaks to keep. No scores to beat. Just a little growth, at your pace.</p><button class="ds-link" data-nav="garden">Visit my garden →</button></div>
      ${supportPanel(assessment.advisor)}</aside></div>${footer()}`;
  }
  function render() {
    root.querySelectorAll('[data-nav]').forEach(button => {
      if(button.dataset.nav===(page==='result'?'checkin':page))button.setAttribute('aria-current','page');
      else button.removeAttribute('aria-current');
    });
    ({home,checkin,result,garden}[page] || home)();
  }
  function valid() {
    let message='';
    if(step===0 && !/^(23|24|25|26)[0-9]{5}$/.test(answers.student_id.trim()))message='Enter a 7-digit student ID starting with 23, 24, 25, or 26.';
    if(step===1 && (answers.sleep_hours==='' || !Number.isFinite(+answers.sleep_hours) || +answers.sleep_hours<0 || +answers.sleep_hours>24 || !Number.isInteger(+answers.sleep_hours*2)))message='Enter sleep hours from 0 to 24, in half-hour steps.';
    main.querySelector('#ds-error').textContent=message;
    return !message;
  }
  function setBusy(value) {
    busy=value;root.setAttribute('aria-busy',String(value));
    root.querySelectorAll('button,input,textarea').forEach(control=>control.disabled=value);
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
        if(data.errors){const byField={student_id:0,stress_level:0,sleep_hours:1,academic_workload:2,social_support:2,financial_stress:3,feelings_text:3};step=byField[Object.keys(data.errors)[0]]??0;render();}
        main.querySelector('#ds-error').textContent=data.errors?Object.values(data.errors).join(' '):data.message;
        if(data.advisor)main.querySelector('#ds-failure-support').innerHTML=supportPanel(data.advisor);
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
    if(scales.includes(id)){answers[id]=+value;main.querySelector('#'+id+'-value').textContent=value;event.target.setAttribute('aria-valuetext',value+' out of 10');}
    else if(id==='sleep_exact'||id==='sleep_hours'){answers.sleep_hours=value;main.querySelector('#ds-sleep-out').textContent=value;main.querySelector(id==='sleep_exact'?'#sleep_hours':'#sleep_exact').value=value;}
    else if(id==='student_id'||id==='feelings_text')answers[id]=value;
  });
  root.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button||busy)return;
    if(button.dataset.nav){page=button.dataset.nav;render();return;}
    if(button.dataset.task!==undefined){const id=+button.dataset.task;selected.has(id)?selected.delete(id):selected.add(id);render();return;}
    switch(button.dataset.action){
      case 'start':page='checkin';break;
      case 'plan':page=assessment?'result':'checkin';break;
      case 'back':if(step===0)page='home';else step--;break;
      case 'next':if(!valid())return;if(step<4)step++;else{await submit();return;}break;
      case 'edit':page='checkin';step=answers.student_id?4:0;break;
      case 'save':await save();return;
      case 'new':location.assign(boot.newUrl);return;
      default:return;
    }
    render();
  });
  render();
})();
