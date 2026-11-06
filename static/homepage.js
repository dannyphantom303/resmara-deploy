function home(){
 if(window.stopResmaraGuide)stopResmaraGuide();
 location.hash='';document.title='Resmara — Your listing gets attention. Your clients get you.';
 app.innerHTML=`<div class="marketing-home">
 ${siteNav("home")}
 <main>
 <section class="home-hero">
  <div class="home-hero-copy"><h1>More eyes on<br> your listing.<br><span>More time for<br> your clients.</span></h1><p>Let Resmara take the marketing off your plate. A branded 14-day campaign, digital ads and seller-ready reports—with one credit per property.</p><div class="home-actions"><button class="home-primary" onclick="newCampaign()">Let’s get started ↗</button></div></div>
  <div class="home-visual"><div class="home-hello"><b>Hi, I’m Resmara.</b><span>Your Real Estate Social Marketing, Analytics &amp; Reporting Assistant.</span></div>${homeWorld()}</div>
 </section>
 <section class="home-goal home-section"><div><span class="home-kicker">MAKE THE FIRST IMPRESSION COUNT</span><h2>Your first 14 days.<br><span>Make them count.</span></h2><p>Your listing is new. Buyers are looking. This is the window to build attention—not spend days getting the marketing ready.</p><p>Week one introduces the home. Week two keeps it in the conversation. Daily social posts keep it showing up, while digital ads help it reach beyond your followers.</p></div><div class="home-fortnight"><span>YOUR LAUNCH WINDOW</span><b>14<span>days to build momentum.</span></b><div class="home-window-line"><i>Launch</i><i>Day 7</i><i>Day 14</i></div><p><strong>Week 1 · Make an entrance.</strong><br>Introduce the home and get it seen.</p><p><strong>Week 2 · Keep showing up.</strong><br>Build on that attention with daily posts and ads.</p></div></section>
 <section class="home-workload"><div class="home-section home-workload-inner"><div><span class="home-kicker">THE WORK BEHIND A GOOD LAUNCH</span><h2>You have clients.<br><span>Not hours to<br>make content.</span></h2><p>That short launch window comes with a long to-do list: two weeks of posts, branded creative, ad setup, scheduling, monitoring and reporting.</p><p>Getting it all ready takes hours you need for your clients. Resmara takes on the marketing work, so your listing can show up consistently without taking over your day.</p></div><div class="home-task-stack"><div><span>✎</span><b>The copy and creative</b><small>Your photos. Your voice. Your brand.</small></div><div><span>▦</span><b>The posts and digital ads</b><small>Planned, prepared and scheduled.</small></div><div><span>↗</span><b>The numbers that matter</b><small>Clear results to share with your seller.</small></div><p>YOUR EXPERTISE. WITH A LITTLE SUPERPOWER.</p></div></div></section>
 <section class="home-section home-campaign"><div class="home-section-heading"><div><span class="home-kicker">ONE LISTING. A WHOLE CAMPAIGN.</span><h2>Your launch.<br><span>All lined up.</span></h2></div><p>Share your listing and media. Resmara builds a complete campaign calendar: the post and creative going live each day, plus exactly when your digital ads run. Review everything together, choose your launch date and approve it.</p></div>
 <div class="home-calendar home-calendar-preview"><div class="home-calendar-head"><div><span>YOUR CAMPAIGN, BEFORE IT GOES LIVE</span><h3>See what’s going live.<br>And exactly when.</h3></div></div><div class="home-calendar-preview-body"><div class="flex home-preview-month"><strong id="home-month-title"></strong><span class="fine">Sample schedule · Pacific time</span></div><div class="review-month-grid" aria-label="Campaign calendar preview"><div class="review-month-weekdays">${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>'<span>'+d+'</span>').join('')}</div><div id="home-month-grid"></div></div></div><div id="home-calendar-selection" hidden></div><p id="home-calendar-range" class="home-calendar-caption" hidden></p></div><p class="home-launch-note">Open an ad bar or the Room Spotlight post to see what you can review before launch.</p>
 </section>
 <section class="home-section home-samples"><div class="home-section-heading"><div><span class="home-kicker">YOUR BRAND IS THE BRIEF</span><h2>Your brand.<br><span>Down to the details.</span></h2></div><p>Resmara researches your website, brokerage and brand. Your colours, fonts, tone and visual style become a brand profile you can review—then that profile guides every post, caption and ad.</p></div><div class="home-sample-layout"><div class="home-brand-profile"><span class="home-kicker">BRAND PROFILE PREVIEW</span><div class="home-brand-name"><span>M</span><div><b>Morgan &amp; Co.</b><small>Property advisors</small></div></div><div class="home-brand-field"><small>YOUR COLOURS</small><div class="home-brand-swatches"><i style="background:#143a50"></i><i style="background:#d8c8ac"></i><i style="background:#f5f2eb"></i></div></div><div class="home-brand-field"><small>YOUR TYPOGRAPHY</small><b class="home-brand-type">A place to call home.</b><span>Editorial headlines. Clean, readable copy.</span></div><div class="home-brand-field"><small>YOUR VOICE</small><b>Warm. Assured. Property-focused.</b><span>Your personality, carried into every caption.</span></div><p>Brokerage identity. Personal brand. One consistent look.</p></div><div class="home-brand-creative"><div class="sample-tabs" role="tablist" aria-label="Branded creative previews"><button role="tab" id="tab-social" aria-selected="true" aria-controls="sample-output" onclick="sampleOutput('social')">Social post</button><button role="tab" id="tab-ad" aria-selected="false" aria-controls="sample-output" onclick="sampleOutput('ad')">Digital ad</button></div><div id="sample-output" role="tabpanel" aria-labelledby="tab-social"></div></div></div></section>
 <section class="home-results"><div class="home-section home-results-layout"><div><span class="home-kicker">CLEAR RESULTS. BETTER CONVERSATIONS.</span><h2>Go back to your<br><span>seller with confidence.</span></h2><p>Know what your marketing delivered. Your day 7 and day 14 reports give you the numbers to make informed decisions with your client.</p><div class="home-report-moments"><div><span>07</span><div><h3>A confident check-in.</h3><p>At day 7, share the exposure, engagement and listing activity so far.</p></div></div><div><span>14</span><div><h3>A clear way forward.</h3><p>At day 14, review the full campaign together and decide what comes next.</p></div></div></div></div><div class="home-seller-preview"><div class="home-report-switch" role="tablist" aria-label="Seller report previews"><button role="tab" id="seller-tab-7" aria-selected="true" aria-controls="home-report-preview" onclick="homeSellerReport(7)">Day 7</button><button role="tab" id="seller-tab-14" aria-selected="false" aria-controls="home-report-preview" onclick="homeSellerReport(14)">Day 14</button></div><div id="home-report-preview" role="tabpanel" aria-labelledby="seller-tab-7"></div></div></div></section>
 <section class="home-section home-price" id="home-pricing"><div><span class="home-kicker">DONE FOR YOU. ON YOUR TERMS.</span><h2>All that.<br>One credit per listing.<br><span>No subscription.</span></h2><p>Your campaign, creative, publishing and seller reports, wrapped into one credit per property. Buy credits when you need them, with no monthly commitment.</p></div><div class="home-price-detail"><h3>Your listing launch includes</h3><ul><li>A branded 14-day social campaign</li><li>Digital ad creative and campaign setup</li><li>Your calendar, review and approval</li><li>Scheduled social publishing</li><li>Day 7 and day 14 seller reports</li></ul><p>You choose the ad budget. Meta ad spend is separate from your credits.</p><button class="home-primary" onclick="pricing()">See credit pricing ↗</button></div></section>
 <section class="home-finish"><span class="home-mini-robot" aria-hidden="true"></span><h2>Let’s give your next listing<br>a proper launch.</h2><button class="home-primary" onclick="newCampaign()">Let’s get started ↗</button></section>
 </main><footer class="home-footer">${logo}<span>Your expertise. Superpowered.</span><a href="#how-it-works" onclick="howItWorks();return false">How it works ↗</a></footer></div>`;
 homeCalendarState={start:new Date('2026-11-02T12:00:00'),month:new Date('2026-11-01T12:00:00'),selected:0};renderHomeMonth();homeSellerReport(7);if(window.sampleOutput)sampleOutput('social');
}
function homeWorld(){return `<div class="home-world" role="img" aria-label="Resmara orchestrating social posts, digital advertising, a campaign calendar and analytics around your property"><span class="home-world-card hw-social"></span><span class="home-world-card hw-ad"></span><span class="home-world-card hw-calendar"></span><span class="home-world-card hw-report"></span><img class="home-world-house" src="resmara-house-complete-v1.png" alt=""><img class="home-world-robot" src="resmara-robot-clean-v1.png" alt=""></div>`}
let homeCalendarState;
const homePostTitles=['Just listed','Property highlights','Room spotlight','The details','Lifestyle story','Weekend viewing','Home highlights','A closer look','Neighbourhood','A favourite feature','Design details','Viewing reminder','Property spotlight','One more look'];
function calendarDateOffset(a,b){return Math.round((Date.UTC(a.getFullYear(),a.getMonth(),a.getDate())-Date.UTC(b.getFullYear(),b.getMonth(),b.getDate()))/86400000)}
function renderHomeMonth(){
 const state=homeCalendarState,host=document.querySelector('#home-month-grid');if(!host)return;
 document.querySelector('#home-month-title').textContent=state.month.toLocaleDateString(undefined,{month:'long',year:'numeric'});
 host.innerHTML=sampleCalendarWeeks(state);
 const end=new Date(state.start);end.setDate(end.getDate()+13);
 const f=new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric'});
 document.querySelector('#home-calendar-range').textContent=f.format(state.start)+'–'+f.format(end);
}
function sampleCalendarWeeks(state,mini=false){
 const first=new Date(state.month);first.setDate(1-first.getDay());
 return (mini?[0,1]:[0,1,2]).map(week=>{
  const dates=Array.from({length:7},(_,col)=>{const d=new Date(first);d.setDate(first.getDate()+week*7+col);return d});
  const days=dates.map(date=>calendarDateOffset(date,state.start));
  const from=days.findIndex(day=>day>=0&&day<14),to=days.findLastIndex(day=>day>=0&&day<14);
  const bars=from<0?'': ['Photo carousel ad','Video ad'].map((title,lane)=>`<button class="review-month-ad" style="grid-column:${from+1}/${to+2};grid-row:${lane+2}" onclick="openCalendarAd(${lane})">${title}</button>`).join('');
  if(week===2)return `<div class="review-month-week home-calendar-fade-week" aria-hidden="true" style="--post-row:2">${dates.map((date,col)=>`<span class="review-month-date" style="grid-column:${col+1}">${date.getDate()}</span><div class="review-month-cell" style="grid-column:${col+1}"></div>`).join('')}</div>`;
  return `<div class="review-month-week" style="--post-row:${bars?4:2}">${dates.map((date,col)=>`<span class="review-month-date" style="grid-column:${col+1}">${date.getDate()}</span>`).join('')}${bars}${days.map((day,col)=>`<div class="review-month-cell" style="grid-column:${col+1}">${day>=0&&day<14?`<button class="review-calendar-post" onclick="openCalendarPost(${day})"><img src="${day%3===0?img2:img}" alt=""><b>${homePostTitles[day]}</b><small>09:00</small></button>${day===6?`<span class="review-calendar-report"><button class="alt" onclick="${mini?'campaignReport(examples[0],7)':'openCalendarReport(7)'}">● View report</button></span>`:''}`:''}</div>`).join('')}</div>`;
 }).join('');
}
function samplePostPreview(day){
 const date=new Date(2026,10,2,12);date.setDate(date.getDate()+day);
 return `<img src="${day%3===0?img2:img}" alt="Property creative preview"><p>${date.toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'})} · 09:00 Pacific</p><p>Branded property post · Facebook + Instagram</p>`;
}
function homeSellerReport(day){const target=document.querySelector('#home-report-preview');if(!target)return;const full=day===14;document.querySelectorAll('.home-report-switch button').forEach(b=>b.setAttribute('aria-selected',String(b.id==='seller-tab-'+day)));target.setAttribute('aria-labelledby','seller-tab-'+day);const metrics=full?[['People reached','14,860'],['Engagements','632'],['Listing clicks','238'],['Ad spend','$50.00']]:[['People reached','8,420'],['Engagements','348'],['Listing clicks','126'],['Ad spend','$25.00']];target.innerHTML=`<article class="home-report-document"><header><span>EXAMPLE SELLER REPORT · DAY ${day}</span><h3>Your listing.<br>Here’s the picture.</h3><p>1248 Oakridge Drive</p></header><div class="home-report-metrics">${metrics.map(([label,value])=>'<div><span>'+label+'</span><b>'+value+'</b></div>').join('')}</div><div class="home-report-chart"><span>CAMPAIGN ACTIVITY</span><div aria-hidden="true">${(full?[32,48,63,52,78,69,91,66,83,75,94,87,100,90]:[32,48,63,52,78,69,91]).map(h=>'<i style="height:'+h+'%"></i>').join('')}</div><small>Launch <span>Day ${day}</span></small></div><footer><b>${full?'Your first two weeks, in one place.':'Your first week, ready to share.'}</b><p>Published content, paid and organic exposure, engagement and budget use.</p></footer></article>`}

function siteNav(active){
 const links=[['home','Home','home'],['how-it-works','How it works','howItWorks'],['pricing','Pricing','pricing']];
 return `<header class="home-nav shared-nav">${logo}<nav aria-label="Main navigation">${links.map(([id,label,fn])=>`<a href="#${id==='home'?'':id}" ${active===id?'aria-current="page"':''} onclick="${fn}();return false">${label}</a>`).join('')}</nav><button class="alt" onclick="clientAccess()">${state.clientSignedIn?'My Dashboard':'Client Login'} ↗</button></header>`;
}
function signOutDemo(){state.clientSignedIn=false;persist();home();window.scrollTo(0,0)}
function clientAccess(mode='signin'){
 if(state.clientSignedIn){dashboard();return}
 const creating=mode==='create';
 show(`<span class="eyebrow">RESMARA CLIENT AREA</span><h2>${creating?'Create an account':'Client Login'}</h2><p>${creating?'Resmara is in private beta. Use the invite code you were sent, or an invited email address.':'Enter your email and password.'}</p><form onsubmit="event.preventDefault();submitTestClient(this,${creating})">${creating?'<label class="field">Full name<input name="clientName" required maxlength="120" autocomplete="name"></label>':''}<label class="field">Email address<input name="clientEmail" type="email" required maxlength="254" autocomplete="email"></label><label class="field">Password<input name="clientPassword" type="password" required minlength="6" autocomplete="current-password" value="test123"></label>${creating?'<label class="field">Invite code<input name="inviteCode" maxlength="64" autocomplete="off" spellcheck="false" placeholder="From your invitation"></label>':''}<p class="fine" role="status"></p><div class="modal-actions"><button>${creating?'Create account →':'Sign in →'}</button><button type="button" class="alt" onclick="clientAccess('${creating?'signin':'create'}')">${creating?'Back to sign in':'Create an account'}</button></div></form>${state.name&&!state.email?'<button class="alt" onclick="resumeDemo()">Resume previous demo →</button>':''}<p class="fine">Connected to Resmara backend API.</p>`);
}
function resumeDemo(){state.clientSignedIn=true;persist();modal.close();dashboard()}
function submitTestClient(form,creating){
 const email=form.elements.clientEmail.value.trim().toLowerCase();
 const password=form.elements.clientPassword?form.elements.clientPassword.value:'test123';
 const name=creating?form.elements.clientName.value.trim():'';
 const invite=creating&&form.elements.inviteCode?form.elements.inviteCode.value.trim():'';
 const status=form.querySelector('[role="status"]');
 if(creating&&!name){status.textContent='Enter your name.';return}
 if(!window.RM){status.textContent='The API client is unavailable in this browser.';return}
 status.textContent=creating?'Creating your account…':'Signing in…';
 // Register/login now go through the shared API client (RM) instead of a hand-rolled fetch.
 (async()=>{
  let account;
  if(creating){
   account=await RM.register(email,password,name,invite);
   // Register returns the account (no token), so sign in to obtain one. Best effort.
   try{const session=await RM.login(email,password);if(session&&session.access_token)RM.setToken(session.access_token)}catch{}
  }else{
   account=await RM.login(email,password);
   if(account&&account.access_token)RM.setToken(account.access_token);
  }
  state={name:(account&&account.name)||name,email,clientSignedIn:true,campaigns:[],connected:false};
  try{localStorage.setItem('resmara',JSON.stringify(state))}catch{}
  modal.close();dashboard();toast('Signed in as '+email);
 })().catch(e=>{
  if(e&&e.status){ // a real API answer (400/401/403): show the server's reason
   status.textContent=e.message||'Login failed';
   return;
  }
  // API unreachable (offline): keep the local demo usable so the prototype still renders.
  state={...state,name:name||state.name,email,clientSignedIn:true,campaigns:state.campaigns||[],connected:false};
  try{localStorage.setItem('resmara',JSON.stringify(state))}catch{}
  modal.close();dashboard();toast('Offline demo session · '+email);
 });
}
function restorePriorDemo(){
 const prior=state.priorDemos||[];if(!prior.length)return;
 const {priorDemos,...current}=state;
 state={...prior.at(-1),clientSignedIn:true,priorDemos:[...prior.slice(0,-1),current]};
 persist();dashboard()
}
function openCalendarPost(day){
 show(`<span class="eyebrow">SCHEDULED SOCIAL POST</span><h2>${homePostTitles[day]}</h2>${samplePostPreview(day)}<p>See the creative and publishing details before approving your campaign.</p>`);
}
function openCalendarAd(lane=0){
 show(`<span class="eyebrow">DIGITAL AD PREVIEW</span><h2>${lane===1?'Video ad · creative preview':'Photo carousel ad · creative preview'}</h2><p>Nov 2–Nov 15</p>${sampleAdMarkup()}`);
}
function openCalendarReport(day){
 const current=document.querySelector('#seller-tab-14').getAttribute('aria-selected')==='true'?14:7;
 homeSellerReport(day);const preview=document.querySelector('#home-report-preview').innerHTML;homeSellerReport(current);show(preview);
}

function onboard(stage=0){
 if(stage===0){
  show(`<span class="eyebrow">FIRST CAMPAIGN · STEP 1 OF 3</span><h2>Set up My Brand.</h2><p>Start with three details. Resmara can use your public website to draft a brand profile for you to review later.</p>${brandProfileForm(true)}`);return
 }
 if(liveCampaignsAvailable()){
  // A signed-in client connects for real: Facebook Login hands the app an ad account it may
  // manage, and Meta bills the client's own card. No demo audit is pretended here.
  show(`<span class="eyebrow">FIRST CAMPAIGN · STEP 2 OF 3</span><h2>Connect your Meta business assets.</h2><p>Facebook Login lets you choose the Business Portfolio, Page and ad account Resmara may manage. Ad spend is billed by Meta to your own card; Resmara never handles your money.</p><div class="notice checkout-notice" id="live-meta-step">Reading your connected accounts…</div><div class="modal-actions"><button class="alt" onclick="onboard()">Back</button><button class="campaign-primary" onclick="modal.close();newCampaign()">Continue →</button></div>`);
  renderLiveMetaStep();return
 }
 show(`<span class="eyebrow">FIRST CAMPAIGN · STEP 2 OF 3</span><h2>Connect your Meta business assets.</h2><p>In the live app, Facebook Login for Business will let you select your Business Portfolio, Facebook Page and ad account. You can also select Instagram if you publish there.</p><div class="notice checkout-notice">Preview mode · no Facebook login, permissions or live account checks.</div><label class="field">Try an account scenario<select id="demo-meta-scenario"><option value="ready">Business, Page and ad account ready</option><option value="blocked">Ad account needs attention</option></select></label><div class="modal-actions"><button class="alt" onclick="onboard()">Back</button><button onclick="runMetaAudit(document.querySelector('#demo-meta-scenario').value)">Run demo connection check →</button></div>`);
}
// Shows the ad accounts that are really connected, and offers the real Facebook login when
// there are none. Never invents a "connected" state.
async function renderLiveMetaStep(){
 const box=document.getElementById('live-meta-step');if(!box||!window.RM)return;
 try{
  const rows=await RM.adAccounts();
  const list=Array.isArray(rows)?rows:(rows&&(rows.accounts||rows.items))||[];
  if(!list.length){box.innerHTML='No Meta ad account is connected yet. <button class="alt" onclick="RM.metaConnect()">Connect a Meta account →</button>';return}
  box.innerHTML=list.map(a=>esc([a.name||'Ad account',a.ad_account_id||a.external_id||'',a.simulated?'(demo)':''].filter(Boolean).join(' · '))).join('<br>');
 }catch(error){box.textContent='Could not read your connected accounts: '+error.message}
}
function campaignBrandProfile(){
 return {...state.brand,agent:state.name||'',brokerage:state.company||''};
}
function myBrand(){
 $('#content').innerHTML=`<div class="welcome"><h1>My Brand</h1><p>Set up your agent identity once. Resmara uses this profile when building your listing campaigns.</p></div><section class="panel brand-profile">${brandProfileForm(false)}</section>`;
}
function brandProfileForm(onboarding){
 const b=campaignBrandProfile();
 const text=(name,label,value,required=false,mode='text')=>`<label class="field">${label}<input name="${name}" inputmode="${mode}" value="${esc(value)}" ${required?'required':''}></label>`;
 if(onboarding)return `<form onsubmit="saveBrandBasics(event,this)"><div class="brand-fields">${text('agent','Agent name',b.agent,true)}${text('license','Agent license number',b.license,true)}${text('website','Personal, team or brokerage website',b.website,true,'url')}</div><p class="fine">Use the website that best represents the brand you want on your listings.</p><p class="fine" data-brand-error role="alert"></p><div class="modal-actions"><button class="campaign-primary">Save and continue →</button></div></form>`;
 const suggestion=b.suggestion||{};
 const asset=(kind,label)=>{const current=state.brandMedia?.[b[kind+'Id']];return `<div class="brand-upload"><label class="field">${label} (optional)<input name="${kind}" type="file" accept="image/png,image/jpeg,image/webp"></label>${current?`<img src="${esc(current)}" alt="Saved ${label.toLowerCase()}"><label class="brand-remove"><input type="checkbox" name="remove_${kind}"> Remove saved image</label>`:''}</div>`};
 return `<form onsubmit="saveBrandProfile(event,this,${onboarding})">${b.suggestion?'<p class="notice checkout-notice">Website research draft. Review the suggested details below and save to use them in future campaigns.</p>':''}<div class="brand-fields">${text('agent','Agent name',b.agent,true)}${text('company','Brokerage',b.brokerage||suggestion.brokerage)}${text('license','Agent license number',b.license)}${text('website','Website',b.website,true,'url')}${text('market','Markets you serve',b.market||suggestion.market)}${text('colours','Brand colours',b.colours||b.colour||suggestion.colours)}${text('brandLink','Public social or brand guide URL (optional)',b.brandLink,false,'url')}<label class="field">Social voice and style<textarea name="voice" rows="2" placeholder="Warm, direct, neighbourhood-focused">${esc(b.voice||suggestion.voice)}</textarea></label>${asset('logo','Logo')}${asset('headshot','Headshot')}</div><p class="fine">PNG, JPEG, or WebP, up to 500 KB per image. This demo stores your profile in this browser.</p><p class="fine" data-brand-error role="alert"></p><div class="modal-actions"><button class="campaign-primary">${onboarding?'Save brand and continue →':'Save My Brand'}</button></div></form>`;
}
function saveBrandBasics(event,form){
 event.preventDefault();
 const fields=form.elements,error=form.querySelector('[data-brand-error]');
 const name=fields.agent.value.trim(),license=fields.license.value.trim(),website=normalizeWebLink(fields.website.value);
 if(!name||!license||!website){error.textContent='Enter your name, license number and a valid website.';return}
 const brand={...state.brand,license,website};
 if(website!==state.brand?.website)delete brand.suggestion;
 const next={...state,name,brand};
 try{localStorage.setItem('resmara',JSON.stringify(next))}catch{error.textContent='This browser couldn’t save your brand.';return}
 state=next;onboard(1);
 draftWebsiteBrand(next,name,website);
}
// Brand suggestions are drafted by the campaign engine when a campaign is built (the
// boost's brand profile), so there is nothing to fetch here. My Brand stays manual.
async function draftWebsiteBrand(){return}
function readBrandImage(file){
 return new Promise((resolve,reject)=>{
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>500000){reject(new Error('Choose a PNG, JPEG, or WebP image under 500 KB.'));return}
  const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('That image couldn’t be read. Try another file.'));reader.readAsDataURL(file);
 });
}
async function saveBrandProfile(event,form,onboarding){
 event.preventDefault();const account=state,fields=form.elements,button=form.querySelector('button'),error=form.querySelector('[data-brand-error]');
 if(button.disabled)return;button.disabled=true;error.textContent='';
 try{
  const website=normalizeWebLink(fields.website.value),brandLink=normalizeWebLink(fields.brandLink.value);
  if(!website||brandLink===null)throw new Error('Enter a valid website or public profile link, such as www.bap.digital.');
  const name=fields.agent.value.trim(),company=fields.company.value.trim(),market=fields.market.value.trim();
  if(!name)throw new Error('Enter your agent name.');
  const brand={...state.brand,website,brandLink,market,license:fields.license.value.trim(),colours:fields.colours.value.trim(),voice:fields.voice.value.trim()};
  delete brand.suggestion;
  brand.colour=brand.colours;
  const brandMedia={...state.brandMedia};
  for(const kind of ['logo','headshot']){
   const file=fields[kind].files[0];
   if(file){const image=await readBrandImage(file);const id=kind+'-'+Date.now()+'-'+Math.random().toString(36).slice(2);brandMedia[id]=image;brand[kind+'Id']=id;}
   else if(fields['remove_'+kind]?.checked)delete brand[kind+'Id'];
  }
  if(state!==account||!form.isConnected)return;
  const next={...state,name,company,brand,brandMedia};
  try{localStorage.setItem('resmara',JSON.stringify(next))}catch{throw new Error('This browser couldn’t save the profile. Try smaller images or use the Chrome preview.')}
  Object.assign(state,next);
  if(onboarding)onboard(1);else{myBrand();toast('Brand profile saved.')}
 }catch(e){error.textContent=e.message}finally{button.disabled=false}
}
function runMetaAudit(scenario){
 show(`<span class="eyebrow">FIRST CAMPAIGN · STEP 3 OF 3</span><h2>Resmara is checking your setup.</h2><div class="audit-track"><span class="robot-avatar" aria-hidden="true"></span></div><p role="status">Checking business access, Page permissions and ad account readiness…</p><p class="fine">Simulated check. No access to your Meta account.</p>`);
 const status=modal.querySelector('[role="status"]');
 setTimeout(()=>{if(!modal.open||!status?.isConnected)return;state.metaAudit={status:scenario==='ready'?'ready':'blocked',checkedAt:new Date().toISOString()};state.connected=state.metaAudit.status==='ready';persist();showMetaResult()},1800)
}
function showMetaResult(){
 const ready=state.metaAudit?.status==='ready';
 if(ready){
 show(`<span class="robot-avatar" aria-hidden="true"></span><span class="eyebrow">DEMO CHECK COMPLETE</span><h2>Congratulations, you’re ready to run your first campaign.</h2><p>In this scenario your Business Portfolio, Page access and ad account passed the check.</p><div class="check">1. Add your listing and media, then use one credit to start.</div><div class="check">2. Review the branded draft and approve it.</div><div class="check">3. Approve your campaign when you’re ready to launch.</div><div class="modal-actions"><button class="alt" onclick="finishWorkspaceTour()">Skip for now</button><button onclick="workspaceTour(0)">Show me my dashboard →</button></div>`);return
 }
 show(`<span class="eyebrow">DEMO CHECK · ACTION NEEDED</span><h2>Your ad account needs attention.</h2><p>You can still build a draft. Launch stays on hold until the account passes the check.</p><div class="check">✓ Business Portfolio and Facebook Page found in this scenario.</div><div class="notice"><strong>Ad account access needs to be granted.</strong><br>In Meta Business Settings, select the ad account and confirm your profile has permission to manage campaigns. Then reconnect and check again.</div><p>Want a hand? Try booking a setup session with Adam. No meeting or invitation will be created.</p><div class="modal-actions"><button class="alt" onclick="onboard(1)">Reconnect and recheck</button><button class="alt" onclick="mockHelpBooking()">Try booking help →</button><button onclick="newCampaign()">Build a draft anyway →</button></div>`);
}
function campaignSampleCaption(c,i){
 const agent=state.company||state.name||'your local real estate team';
 return (i===0?'Take a closer look at ':i===1?'See what’s on offer at ':homePostTitles[(i-2)%14]+' · ')+c.address+'. '+(state.brand?.market?'Explore the listing in '+state.brand.market+' and contact '+agent+' to arrange a viewing.':'Explore the listing and contact '+agent+' to arrange a viewing.')
}
function launchOrder(){
 const live=reviewCampaignBoostId()!=null&&!!(window.RM&&RM.isLoggedIn());
 if(!live&&state.metaAudit?.status!=='ready'){show(`<h2>Check your Meta setup first.</h2><p>Your draft is saved. Complete a readiness check before proceeding to launch.</p><button onclick="onboard(1)">Check Meta setup →</button>`);return}
 if(!activeReview()?.approved)return;
 if(live){
  show(`<span class="eyebrow">LAUNCH PREVIEW</span><h2>Ready to launch your property?</h2><div class="check">One property · 14-day campaign · Approved</div><p>Ad spend is billed to your own connected ad account. No campaign credit is used at launch. The campaign is created paused, and you activate it in Meta Ads Manager.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Back to your campaign</button><button class="campaign-primary" onclick="launchCampaignViaApi()">Launch on Meta →</button></div>`);
  return;
 }
 show(`<span class="eyebrow">LAUNCH PREVIEW</span><h2>Ready to launch your property?</h2><div class="check">One property · 14-day campaign · Approved</div><p>Meta ad spend is separate. No additional credit is used at launch. Publishing is not connected in this demo.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Back to your campaign</button>${reviewCampaignBoostId()!=null?'<button class="campaign-primary" onclick="launchCampaignViaApi()">Launch on Meta →</button>':''}</div>`);
}

function mockHelpBooking(){
 show(`<span class="eyebrow">DEMO HELP BOOKING</span><h2>Meta setup with Adam</h2><p>We’ll review the ad account permissions and help you reconnect. These are example appointments.</p><form onsubmit="event.preventDefault();confirmMockHelp(this.slot.value)"><label class="field">Choose an example time<select name="slot"><option>Tuesday · 10:00 AM Pacific</option><option>Thursday · 2:00 PM Pacific</option></select></label><div class="modal-actions"><button type="button" class="alt" onclick="showMetaResult()">Back</button><button>Confirm demo booking →</button></div></form>`);
}
function confirmMockHelp(slot){
 state.mockHelpSlot=slot;persist();
 show(`<span class="eyebrow">DEMO BOOKING CONFIRMED</span><h2>Your setup session preview</h2><div class="check">${esc(slot)} · Adam · Meta setup</div><p>No real meeting was booked. After the permissions are fixed, return here to reconnect and check again.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button><button onclick="onboard(1)">Reconnect and recheck →</button></div>`);
}

function creditQuote(quantity){
 const count=Number(quantity);
 if(!Number.isInteger(count)||count<1||count>100||(count!==1&&count%5!==0))return null;
 const unit=count>=100?3900:count>=50?4199:4999;
 return {count,unit,total:count*unit,savings:count*(4999-unit)};
}
function creditMoney(cents){return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100)}
function usableCreditPacks(now=Date.now()){
 return (state.creditPacks||[]).filter(pack=>pack.remaining>0&&Date.parse(pack.expiresAt)>now);
}
function creditBalance(){return usableCreditPacks().reduce((sum,pack)=>sum+pack.remaining,0)}
function useCampaignCredit(){
 const pack=usableCreditPacks().sort((a,b)=>Date.parse(a.expiresAt)-Date.parse(b.expiresAt))[0];
 if(!pack)return false;
 pack.remaining--;return true;
}
function pricing(){
 if(typeof stopResmaraGuide==='function')stopResmaraGuide();
 location.hash='pricing';document.title='Credit Pricing — Resmara';
 app.innerHTML=`<div class="marketing-home">${siteNav('pricing')}<main><section class="home-section package-page"><div><span class="home-kicker">PAY AS YOU GO</span><h1>Credits for<br><span>your next listings.</span></h1><p>One credit builds one 14-day listing campaign, with branded posts, digital ad creative and Day 7 and Day 14 seller reports.</p><p>Buy one credit or a pack of five or more. Use them as listings come in, within 12 months of purchase. No subscription or automatic renewal. Meta ad spend is separate.</p></div>${creditCalculator(false,true)}</section></main><footer class="home-footer">${logo}<span>Your expertise. Superpowered.</span></footer></div>`;
 updateCreditQuote(document.querySelector('.credit-calculator'));window.scrollTo(0,0)
}
function creditSliderQuantity(index){return Number(index)===0?1:Number(index)*5}
function creditCalculator(resume,estimateOnly=false){
 return `<form class="home-price-detail credit-calculator" oninput="updateCreditQuote(this)" onsubmit="event.preventDefault();${estimateOnly?'':'reviewCreditOrder(creditSliderQuantity(this.elements.quantity.value),'+resume+')'}"><h2>Choose your credits</h2><label class="field">Number of credits <output data-credit-count></output><input name="quantity" type="range" min="0" max="20" step="1" value="${resume?0:2}"></label><div class="credit-presets">${[1,5,10,50,100].map(n=>`<button type="button" class="alt" onclick="this.form.elements.quantity.value=${n===1?0:n/5};updateCreditQuote(this.form)">${n}</button>`).join('')}</div><div class="credit-quote" aria-live="polite"><strong data-credit-total></strong><span data-credit-unit></span><span data-credit-saving></span></div>${estimateOnly?'<p class="fine">Purchase credits from My Credits in your dashboard.</p>':'<button class="home-primary" data-credit-buy>Buy credits ↗</button><p class="fine">Demo checkout · no charge</p>'}</form>`;
}
function updateCreditQuote(form){
 if(!form)return;const quote=creditQuote(creditSliderQuantity(form.elements.quantity.value));if(!quote)return;
 form.elements.quantity.setAttribute('aria-valuetext',quote.count+' credits');
 form.querySelector('[data-credit-count]').textContent=quote.count;
 form.querySelector('[data-credit-total]').textContent=creditMoney(quote.total);
 form.querySelector('[data-credit-unit]').textContent=creditMoney(quote.unit)+' per credit · '+quote.count+' listings';
 form.querySelector('[data-credit-saving]').textContent=quote.savings?'Save '+creditMoney(quote.savings)+' compared with $49.99 per credit.':'50+ credits unlock volume pricing.';
 const buy=form.querySelector('[data-credit-buy]');if(buy)buy.textContent='Buy '+quote.count+' credits ↗';
}
function buyCreditsForDraft(){show(creditCalculator(true));updateCreditQuote(modal.querySelector('.credit-calculator'))}
function reviewCreditOrder(quantity,resume=false){
 if(!state.clientSignedIn){clientAccess();return}
 const quote=creditQuote(quantity);if(!quote)return;
 show(`<h2>Review your credit purchase</h2><div class="check">${quote.count} credits · ${creditMoney(quote.unit)} each · <strong>${creditMoney(quote.total)}</strong></div><p>Credits expire 12 months after purchase. Meta ad spend is separate.</p><p class="notice checkout-notice">Demo checkout. No card details or payment are collected.</p><div class="modal-actions"><button class="alt" onclick="${resume?'buyCreditsForDraft()':'modal.close()'}">Back</button><button class="campaign-primary" onclick="completeDemoCreditOrder(this,${quote.count},${resume})">Add demo credits →</button></div>`);
}
function completeDemoCreditOrder(button,quantity,resume){
 const quote=creditQuote(quantity);if(button.disabled||!quote||!state.clientSignedIn)return;
 button.disabled=true;const now=new Date(),expires=new Date(now);expires.setFullYear(expires.getFullYear()+1);
 (state.creditPacks ||= []).push({remaining:quote.count,purchasedAt:now.toISOString(),expiresAt:expires.toISOString()});
 persist();if(resume){reviewDraft();return}
 modal.close();dashboard('credits');toast(quote.count+' demo credits added.');
}

function myCredits(){
 const packs=state.creditPacks||[],available=creditBalance();
 const date=value=>new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
 $('#content').innerHTML=`<div class="welcome"><h1>My Credits</h1><p>One credit builds one property campaign. Meta ad spend is separate.</p></div><section class="panel"><h2>${available} ${available===1?'credit':'credits'} available</h2><p>Credits can be used for 12 months after purchase. The soonest-expiring credit is used first.</p>${packs.length?`<ul class="campaign-report-list">${[...packs].reverse().map(pack=>`<li><strong>${pack.remaining} unused</strong><span class="fine">${Date.parse(pack.expiresAt)<=Date.now()?'Expired':'Expires'} ${esc(date(pack.expiresAt))}</span></li>`).join('')}</ul>`:'<p class="fine">No credit purchases yet.</p>'}</section>${creditCalculator(false)}`;
 updateCreditQuote(document.querySelector('.credit-calculator'));
}

let workspaceTourCleanup;
function workspaceTour(step=0){
 workspaceTourCleanup?.();
 if(modal.open)modal.close();
 const steps=[
  ['My Campaigns','This is where all your properties live. Open any campaign to see its scope, calendar and seller reports.','.welcome h1','campaigns'],
  ['Add a campaign','Use this button to add the property address, listing link and media. Checkout shows your credit balance.','.welcome [onclick="newCampaign()"]','campaigns'],
  ['Property Scope','Resmara fills in the property brief. Check the facts and pick a go-live date. Approving the scope starts the campaign build.','.campaign-scope summary','example'],
  ['Campaign Calendar','The posts and ads appear here when the build is done. Open any item to edit it, then approve the calendar.','.review-calendar summary','example'],
  ['Approve the campaign','Once the scope and calendar are approved, you can approve the full campaign here.','.review-approval h2','example'],
  ['My Credits','Check your balance or buy more credits here. One credit builds one property campaign.','.welcome h1','credits']
 ];
 const [title,description,selector,page]=steps[step];
 dashboard(page==='example'?'campaigns':page);
 if(page==='example')details(state.campaigns.length);
 const target=document.querySelector('#content '+selector);
 if(!target)return;
 target.classList.add('workspace-tour-target');
 const tip=document.createElement('section');
 tip.className='workspace-tour-tip';
 tip.setAttribute('aria-label','Dashboard tour');
 tip.innerHTML=`<span class="eyebrow">DASHBOARD TOUR · ${step+1} OF ${steps.length}</span><h2>${title}</h2><p>${description}</p><div class="modal-actions"><button class="alt" onclick="${step?'workspaceTour('+(step-1)+')':'finishWorkspaceTour()'}">${step?'Back':'Skip tour'}</button><button class="campaign-primary" onclick="${step===steps.length-1?'finishWorkspaceTour()':'workspaceTour('+(step+1)+')'}">${step===steps.length-1?'Finish tour ✓':'Next →'}</button></div>`;
 document.body.append(tip);
 target.scrollIntoView({block:'center'});
 function place(){
  const rect=target.getBoundingClientRect();
  const left=Math.max(12,Math.min(rect.left,innerWidth-tip.offsetWidth-12));
  const below=rect.bottom+12;
  const top=below+tip.offsetHeight<=innerHeight-12?below:Math.max(12,rect.top-tip.offsetHeight-12);
  tip.style.left=left+'px';tip.style.top=top+'px';
 }
 function onKey(event){if(event.key==='Escape')finishWorkspaceTour()}
 const observer=new MutationObserver(()=>{if(!target.isConnected)workspaceTourCleanup?.()});
 observer.observe(app,{childList:true,subtree:true});
 addEventListener('scroll',place,true);addEventListener('resize',place);addEventListener('keydown',onKey);
 workspaceTourCleanup=()=>{
  observer.disconnect();target.classList.remove('workspace-tour-target');tip.remove();
  removeEventListener('scroll',place,true);removeEventListener('resize',place);removeEventListener('keydown',onKey);
  workspaceTourCleanup=null;
 };
 place();tip.querySelector('.campaign-primary').focus({preventScroll:true});
}
function finishWorkspaceTour(){workspaceTourCleanup?.();dashboard()}
