(function(){let observer=null,scene=null,root=null,raf=0;
window.stopResmaraGuide=function(){if(root?._sceneResize)root._sceneResize.disconnect();if(root?._sceneAbort)root._sceneAbort.abort();if(observer)observer.disconnect();if(raf)cancelAnimationFrame(raf);if(scene)scene.remove();observer=null;scene=null;root=null};
window.mountResmaraGuide=function(){stopResmaraGuide();root=document.querySelector('.journey');if(!root)return;
root.querySelectorAll('.guide-stop').forEach(el=>el.hidden=true);
scene=document.createElement('div');scene.className='orchestration-stage scene-intro';scene.setAttribute('role','img');scene.setAttribute('aria-label','Resmara, your three-dimensional robot guide, orchestrating property ads, social posts, scheduling and reporting.');
scene.innerHTML='<div class="orchestration-canvas"><img class="scene-fallback" src="orchestrator-v1.png" alt=""><svg class="scene-wires" viewBox="0 0 390 330" aria-hidden="true"><path d="M195 167Q120 135 91 72"/><path d="M195 167Q270 135 305 72"/><path d="M195 167Q130 211 78 230"/><path d="M195 167Q260 211 316 230"/></svg><span class="scene-sprite scene-house" aria-hidden="true"></span><span class="scene-sprite scene-social" aria-hidden="true"></span><span class="scene-sprite scene-ad" aria-hidden="true"></span><span class="scene-sprite scene-calendar" aria-hidden="true"></span><span class="scene-sprite scene-report" aria-hidden="true"></span><span class="scene-sprite scene-orb" aria-hidden="true"></span><div class="account-network" aria-hidden="true"><svg class="account-links" viewBox="0 0 390 235"><path d="M77 180Q105 55 206 54"/><path d="M77 180Q181 65 325 94"/><path d="M77 180Q130 193 214 170"/></svg><div class="account-node network-facebook"><span class="network-logo facebook-mark"><svg viewBox="0 0 24 24"><path d="M14 22v-9h3l.5-3.5H14V7.3c0-1 .3-1.7 1.8-1.7h1.9V2.5c-.3 0-1.5-.1-2.8-.1-2.8 0-4.7 1.7-4.7 4.8v2.3H7V13h3.2v9Z"/></svg></span><b>Facebook</b><i>✓</i></div><div class="account-node network-instagram"><span class="network-logo instagram-mark"><svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" rx="7"/><circle cx="16" cy="16" r="5"/><circle class="instagram-dot" cx="23" cy="9.5" r="1.5"/></svg></span><b>Instagram</b><i>✓</i></div><div class="account-node network-meta"><span class="network-logo meta-mark"><svg viewBox="0 0 48 32"><path d="M4 23C4 5 14 1 23 17L29 26C36 36 46 26 43 15C40 4 35 3 29 12L17 27C10 35 4 29 4 23Z"/></svg></span><b>Meta Ads</b><i>✓</i></div></div><div class="scene-caption"><b>Let me show you how this works.</b><span>Your listing. My superpowers. A few simple steps.</span></div><div class="scene-progress" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div></div>';
root.querySelector('main').prepend(scene);
function fitScene(){if(!scene)return;const mobile=innerWidth<850;const scale=Math.min(1,scene.clientWidth/390);scene.style.setProperty('--scene-scale',scale);scene.style.setProperty('--scene-width-scale',scene.clientWidth/390);scene.style.height=mobile?(352*scale)+'px':''}
root._sceneResize=new ResizeObserver(fitScene);root._sceneResize.observe(scene);fitScene();
const mountScene=scene;const probe=new Image();probe.onload=()=>{if(scene===mountScene){scene.classList.add('sprite-ready');setTimeout(()=>{if(scene===mountScene)scene.classList.add('arrival-done')},2200)}};probe.src='resmara-atlas-v1.png';
const steps=[...root.querySelectorAll('[data-guide]')],names=steps.map(step=>step.dataset.scene||'intro');let active=-1;
function update(){raf=0;if(!root?.isConnected)return;const boundary=innerWidth>=850?innerHeight*.42:scene.getBoundingClientRect().bottom+32;let n=0;steps.forEach((step,i)=>{if(step.getBoundingClientRect().top<=boundary)n=i});const last=steps.length-1;const finaleBoundary=boundary+Math.max(0,(innerHeight-boundary)*.30);const atBottom=scrollY+innerHeight>=document.documentElement.scrollHeight-8;if(steps[last].getBoundingClientRect().top<=finaleBoundary||atBottom)n=last;if(n!==active){delete scene.dataset.preview;scene.className='orchestration-stage scene-'+names[n]+(scene.classList.contains('sprite-ready')?' sprite-ready':'')+(scene.classList.contains('arrival-done')?' arrival-done':'');const lines=steps[n].dataset.guide.split('|');scene.querySelector('.scene-caption b').textContent=lines[0];scene.querySelector('.scene-caption span').textContent=lines[1]||'';scene.querySelectorAll('.scene-progress i').forEach((dot,i)=>dot.classList.toggle('current',i===n));active=n}}
function queue(){if(!raf)raf=requestAnimationFrame(update)}
observer=new IntersectionObserver(queue,{threshold:[0,.1,.3,.5,.8,1]});steps.forEach(s=>observer.observe(s));root._sceneQueue=queue;window.addEventListener('scroll',queue,{passive:true,signal:makeSignal()});window.addEventListener('resize',queue,{passive:true,signal:root._sceneAbort.signal});update();
};
function makeSignal(){if(root._sceneAbort)root._sceneAbort.abort();root._sceneAbort=new AbortController();return root._sceneAbort.signal}
// Keep the on-page sample and the floating panel in sync.
window.focusResmaraPanel=function(panel){if(!scene)return;scene.dataset.preview=panel};
// Content-generation step. The brand-guide screen has no form of its own, so this collects the
// fields the app already gathers (My Brand profile + the active campaign's approved scope) and
// runs them through the real content engine (POST /api/content/generate/content).
window.resmaraGenerateContent=async function(extra){
 if(!window.RM){show(`<h2>API unavailable</h2><p>The Resmara API client didn’t load.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);return}
 const campaign=(typeof reviewCampaign==='function')?reviewCampaign():null;
 const boostId=campaignBoostId(campaign);
 if(boostId==null){show(`<span class="eyebrow">GENERATE CONTENT</span><h2>Connect this campaign first</h2><p>Content generation runs against a backend boost. This demo campaign isn’t linked to one yet.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);return}
 const brand=(campaign&&campaign.brandProfile)||(typeof campaignBrandProfile==='function'?campaignBrandProfile():{})||{};
 const scope=(campaign&&campaign.scope)||{};
 const account=(typeof state!=='undefined'&&state)||{};
 const fields=Object.assign({boost_id:boostId,agent_name:brand.agent||brand.brokerage||account.name||'',phone:brand.phone||'',license_no:brand.license||'',brokerage:brand.brokerage||brand.company||'',instagram:brand.instagram||'',website:brand.website||'',property_website:scope.listing||'',beds:'',baths:'',sqft:'',city:'',feature:scope.highlights||'',cta:'',notes:scope.facts||'',force:false},extra||{});
 show(`<span class="eyebrow">GENERATING CONTENT</span><h2>Resmara is writing your campaign.</h2><p role="status">Running research, brand and plan against your approved scope…</p>`);
 try{
  const result=await RM.generateContent(fields);
  const lines=[];
  if(result&&result.posts_created!=null)lines.push(result.posts_created+' posts created.');
  (result&&result.violations||[]).forEach(v=>lines.push('Violation: '+v));
  (result&&result.missing_info||[]).forEach(m=>lines.push('Missing: '+m));
  if(!lines.length)lines.push('Content generated.');
  show(`<span class="eyebrow">CONTENT GENERATED</span><h2>Your campaign content is ready.</h2><ul class="campaign-report-list">${lines.map(line=>`<li>${esc(String(line))}</li>`).join('')}</ul><div class="modal-actions"><button onclick="modal.close()">Close</button></div>`);
 }catch(e){
  show(`<h2>Content generation failed</h2><p>${esc(e.message)}</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
 }
};
mountResmaraGuide();
})();
