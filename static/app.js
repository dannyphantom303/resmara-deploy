const $=s=>document.querySelector(s),app=$('#app'),modal=$('#modal');const img='https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=1000&q=85',img2='https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=800&q=85';let saved;try{saved=JSON.parse(localStorage.getItem('resmara') || localStorage.getItem('listing14')||'{}')}catch{saved={}}let state={name:'',connected:false,campaigns:[],...saved},view='overview',step=0,draft={};const logo='<a href="#" class="logo resmara-wordmark" aria-label="Resmara home" onclick="home();return false">RESMARA<span aria-hidden="true">.</span></a>';const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function persist(){try{localStorage.setItem('resmara',JSON.stringify(state))}catch(e){/* Embedded preview keeps state in memory when storage is unavailable. */}}function toast(t){let e=document.createElement('div');e.className='toast';e.textContent=t;document.body.append(e);setTimeout(()=>e.remove(),3500)}function howItWorks(){location.hash='how-it-works';document.title='How It Works — Resmara';app.innerHTML=`<div class="launch-home journey">${siteNav("how-it-works")}<main><section class="journey-step intro-step" data-scene="intro" data-guide="Let me show you how this works.|Your listing. My superpowers. A few simple steps."><h1>A little help.<br><span>A powerful launch.</span></h1><p>Here’s how we turn your photos and videos into a branded 14-day campaign—from connecting your accounts to sharing the results.</p></section><section class="journey-step connect-step" id="connect" data-scene="connect" data-guide="First, let’s get connected.|Your Facebook. Your Instagram. Your brand."><span class="launch-tag">01 · CONNECT</span><h2>Your accounts.<br>All connected.</h2><p>Connect your social media and ad account once. I’ll help you get set up, then remember them for your next listing.</p><div class="simple-connections"><span>f <b>Facebook</b></span><span>◎ <b>Instagram</b></span><span>↗ <b>Meta ads</b></span></div></section><section class="journey-step property-step" data-scene="property" data-guide="Now, show me the home.|One listing link. Your photos and videos. I’ll take it from there."><span class="launch-tag">02 · ADD YOUR LISTING</span><h2>You’ve got the home.<br>I’ll get to know it.</h2><p>Paste your property link and share the photos and videos you’ve already had shot.</p><p>I’ll gather the property details and learn your professional style, using your website, public brand information and the examples you share. You check that I’ve got it right.</p><div class="simple-listing-link"><span>↗</span><div><small>YOUR PROPERTY LINK</small><b>youragency.com/your-next-listing</b></div><span>✓</span></div></section><section class="journey-step build-step" id="sample-campaign" data-scene="build" data-guide="This is where my superpowers come in.|I’ll build the calendar, write the posts and create your digital ads."><span class="launch-tag">03 · WATCH IT COME TOGETHER</span><h2>One listing becomes<br>a whole campaign.</h2><p>I turn your photos, video and property details into 14 days of marketing that looks and sounds like you.</p><div class="simple-deliverables"><div><span>▦</span><b>Your calendar</b><p>Fourteen days, all lined up.</p></div><div><span>✎</span><b>Your social posts</b><p>Copy and branded creative, ready to review.</p></div><div><span>↗</span><b>Your digital ads</b><p>Photo or video ads, built from the media you supply.</p></div></div><details class="sample-discovery"><summary>See what your campaign could look like ↗</summary><div class="sample-tabs" role="tablist" aria-label="Sample campaign outputs"><button role="tab" id="tab-social" aria-selected="true" aria-controls="sample-output" onclick="sampleOutput('social')">Social</button><button role="tab" id="tab-ad" aria-selected="false" aria-controls="sample-output" onclick="sampleOutput('ad')">Ad</button><button role="tab" id="tab-calendar" aria-selected="false" aria-controls="sample-output" onclick="sampleOutput('calendar')">Calendar</button><button role="tab" id="tab-report" aria-selected="false" aria-controls="sample-output" onclick="sampleOutput('report')">Report</button></div><div id="sample-output" role="tabpanel" aria-labelledby="tab-social"></div><p class="sample-disclosure">Illustrative creative and data. This demo doesn’t generate or publish a real campaign.</p></details></section><section class="journey-step launch-step" data-scene="launch" data-guide="Make it yours. Give it the thumbs-up.|Review the posts and ads, make your changes, then approve your launch."><span class="launch-tag">04 · APPROVE & LAUNCH</span><h2>A quick look from you.<br>A proper launch from me.</h2><p>Check the campaign, change anything you like and choose your ad spend. Nothing goes live without your approval.</p><p>Then I schedule your posts and submit your ads, with housing-ad settings checked before launch. I’ll keep you informed while Meta reviews them.</p><div class="launch-sequence"><span>You approve</span><i>→</i><span>I schedule</span><i>→</i><span>Your listing gets seen</span></div></section><section class="journey-step outcome-step" id="seller-report" data-scene="outcome" data-guide="And I’ll show you how it’s going.|Real exposure. Clear numbers. Something to share with your seller."><span class="launch-tag">05 · SEE & SHARE THE RESULTS</span><h2>“How’s the marketing going?”<br>Now you have an answer.</h2><p>I bring the results together at day 7 and day 14: what went out, who it reached, listing clicks and ad spend.</p><div class="phone-report"><div><b>Your seller update</b><span>Day 7 + Day 14</span></div><ul><li>What was published</li><li>People reached and listing clicks</li><li>How your ad budget was used</li></ul><button class="alt" onclick="campaignReport(examples[0],7)">See a sample report ↗</button></div><p>Less time making marketing. More time being the agent your clients count on.</p></section><section class="journey-step start-step" data-scene="start" data-guide="Ready to do this?|Your whole campaign. All working together."><span class="launch-tag">YOUR EXPERTISE. SUPERPOWERED.</span><h2>Ready to supercharge<br>your next listing?</h2><p>And when the next home comes along? We’ll be ready to do it again.</p><button class="journey-start" onclick="newCampaign()">Let’s get started ↗</button><span class="journey-demo">Interactive prototype · No live posts, ads or payments.</span></section></main><footer class="launch-footer"><span>Resmara</span><span>Real Estate Social Marketing,<br>Analytics & Reporting Assistant</span></footer></div>`;if(window.mountResmaraGuide)mountResmaraGuide();if(window.sampleOutput)sampleOutput('social')}

const examples=[{address:'1248 Oakridge Drive',area:'Austin, TX · $845,000',day:7,status:'Demo · Running',image:img},{address:'76 Willow Lane',area:'Austin, TX · $625,000',day:3,status:'Demo · Running',image:img2},{address:'309 Cedar House',area:'Austin, TX · $1,150,000',day:14,status:'Demo · Complete',image:img}];function dashboard(v='campaigns'){if(window.stopResmaraGuide)stopResmaraGuide();view=v;location.hash='dashboard';app.innerHTML=`<div class="shell"><aside class="sidebar">${logo}<span class="eyebrow" style="margin:16px 12px -15px;color:#52778f">YOUR WORKSPACE</span><nav class="side-nav">${[['campaigns','◫','My campaigns'],['brand','✦','My Brand'],['credits','◇','Billing'],['accounts','◎','Connected accounts'],['support','✉','Support']].map(([id,icon,label])=>`<button class="${v===id?'active':''}" onclick="dashboard('${id}')">${icon} &nbsp; ${label}</button>`).join('')}</nav><div class="side-foot"><span class="robot-avatar" role="img" aria-label="Resmara, your three-dimensional robot guide"></span><b style="display:block">Resmara’s got your back.</b><button class="side-campaign campaign-primary" onclick="newCampaign()">＋ Campaign</button></div><button class="alt" onclick="onboard(0)">Replay onboarding</button>${state.priorDemos?.length?'<button class="alt" onclick="restorePriorDemo()">Switch to previous demo</button>':''}<button class="alt" onclick="signOutDemo()">Sign out</button><a class="small" onclick="home()">← Back to homepage</a></aside><main class="main workspace-main"><div id="content"></div></main></div>`;if(v==='accounts')accounts();else if(v==='brand')myBrand();else if(v==='credits')myCredits();else if(v==='support')supportPage();else campaignList()}// Pull the campaigns that actually exist in the API and keep them in the same list as local
// drafts, so a client sees their real campaign after a reload or on another device.
let liveCampaignsSyncedAt=0;
function liveStatusLabel(b){
 const stage=String((b&&b.stage)||'').toUpperCase();
 if(b&&b.meta_campaign_id)return 'Ad campaign created · paused';
 if(stage==='APPROVED')return 'Approved · ready to launch';
 if(stage==='DEPLOYED'||stage==='LIVE')return 'Launched';
 return (b&&b.posts_total)?'Built · awaiting approval':'Draft';
}
async function syncLiveCampaigns(){
 if(!liveCampaignsAvailable()||Date.now()-liveCampaignsSyncedAt<10000)return;
 liveCampaignsSyncedAt=Date.now();
 try{
  const rows=await RM.boosts();
  const list=Array.isArray(rows)?rows:(rows&&rows.boosts)||[];
  // Signature includes the cover photo: a card that swaps stock art for the property photo is
  // a visible change and must repaint, even though the campaign list itself is unchanged.
  const signature=list=>list.map(c=>[campaignBoostId(c),c.image||'',c.status].join(':')).join(',').slice(0,4000);
  const before=signature(state.campaigns);
  list.forEach(b=>{
   if(!b||b.id==null)return;
   const card={address:b.address,area:(b.campaign_days||14)+'-day campaign · $'+Number(b.ad_budget_usd||0).toFixed(0)+'/day',status:liveStatusLabel(b),boostId:b.id,live:true,day:0,hidden:b.hidden===true,posts_total:b.posts_total||0,posts_approved:b.posts_approved||0,posts_published:b.posts_published||0,url:'',media:'',image:b.image||undefined,budget:'$'+Number(b.ad_budget_usd||0).toFixed(0)+'/day'};
   const existing=state.campaigns.find(c=>String(campaignBoostId(c))===String(b.id));
   if(existing)Object.assign(existing,card);else state.campaigns.push(card);
  });
  persist();
  if(before!==signature(state.campaigns)&&typeof view!=='undefined'&&view==='campaigns')campaignList();
 }catch(e){}
}
// --- Hiding and deleting campaigns -----------------------------------------
// A campaign is either the customer's own (it has a boost id and the account owns it) or one of
// the built-in samples. Hiding is reversible on both; deleting is only offered for the customer's
// own campaigns, and the server decides whether deleting is allowed (a paid campaign is not).
function isSample(campaign){return !campaignBoostId(campaign)}
function campaignKey(campaign){return isSample(campaign)?'sample:'+campaign.address:'boost:'+campaignBoostId(campaign)}
function campaignByKey(key){return [...state.campaigns,...examples].find(c=>campaignKey(c)===key)}
function campaignHidden(campaign){
 if(isSample(campaign))return (state.hiddenSamples||[]).includes(campaign.address);
 return campaign.hidden===true;
}
function visibleCampaigns(){return [...state.campaigns,...examples].filter(c=>!campaignHidden(c))}
function hiddenCampaigns(){return [...state.campaigns,...examples].filter(campaignHidden)}
function hideCampaign(key){
 const c=campaignByKey(key);if(!c)return;
 if(isSample(c)){state.hiddenSamples=[...(state.hiddenSamples||[]),c.address];persist();campaignList();toast('Hidden. You can bring it back any time.');return}
 RM.hideBoost(campaignBoostId(c),true).then(()=>{c.hidden=true;persist();campaignList();toast('Campaign hidden. Nothing was deleted.')})
  .catch(e=>toast('Could not hide that campaign: '+((e&&e.message)||'unknown error')));
}
function unhideCampaign(key){
 const c=campaignByKey(key);if(!c)return;
 if(isSample(c)){state.hiddenSamples=(state.hiddenSamples||[]).filter(a=>a!==c.address);persist();campaignList();return}
 RM.hideBoost(campaignBoostId(c),false).then(()=>{c.hidden=false;persist();campaignList();toast('Campaign is back in your list.')})
  .catch(e=>toast('Could not restore that campaign: '+((e&&e.message)||'unknown error')));
}
function deleteCampaign(key){
 const c=campaignByKey(key);if(!c)return;
 if(isSample(c)){hideCampaign(key);return}
 const id=campaignBoostId(c);
 const ok=confirm('Delete “'+c.address+'”?\n\nIts posts, ads and photos are removed from Resmara and cannot be brought back. Anything already published to Facebook or Instagram stays in Meta Ads Manager.');
 if(!ok)return;
 RM.deleteBoost(id).then(()=>{
   state.campaigns=state.campaigns.filter(x=>String(campaignBoostId(x))!==String(id));
   persist();campaignList();dashboard('campaigns');toast('Campaign deleted.');
 }).catch(e=>toast(((e&&e.message)||'Could not delete that campaign.')));
}
function campaignList(){
 syncLiveCampaigns();
 const campaigns=visibleCampaigns(),away=hiddenCampaigns();
  $('#content').innerHTML=`<div class="welcome flex"><div><h1>My campaigns</h1><p>Open a property to review its campaign and reports.</p><p><strong>$49 per campaign</strong> · <a href="#pricing" onclick="dashboard('credits');return false">Billing</a></p></div><button class="campaign-primary" onclick="newCampaign()">＋ Campaign</button></div>${(!state.campaigns.length&&(!state.brand?.website||state.metaAudit?.status!=='ready'))?`<div class="banner flex"><div><b>Your first campaign starts with a connection.</b><p class="small" style="margin:5px 0">Walk through your profile and social accounts to get set up.</p></div><button class="alt" onclick="state.metaAudit?.status==='blocked'?showMetaResult():onboard(state.brand?.website?1:0)">${state.metaAudit?.status==='blocked'?'View Meta check →':'Set up workspace →'}</button></div>`:''}<div class="cards">${campaigns.map((c,i)=>`<article class="card">${c.image?`<img src="${esc(c.image)}" alt="${esc(c.address)}">`:(c.live?`<div class="card-noimg">No photos yet — import the listing link</div>`:`<img src="${img}" alt="Illustrative property photo">`)}<div class="card-body"><span class="pill">${esc(c.status)}</span><h3>${esc(c.address)}</h3><p>${esc(c.area||'Your saved campaign draft')}</p><div class="progress"><i style="width:${c.live?Math.min(100,(c.posts_published||0)/Math.max(c.posts_total||14,1)*100):(c.day||0)/14*100}%"></i></div><div class="flex small"><span>${c.live?(c.posts_total||0)+' posts · '+(c.posts_published||0)+' published':c.day?'Day '+c.day+' of 14':'Awaiting campaign generation'}</span><span>${c.live?esc(c.status==='Draft'?'Not built yet':'Meta ad'):c.day?'Facebook + Instagram':'Draft'}</span></div><button class="alt" onclick="details(${[...state.campaigns,...examples].indexOf(c)})">${c.day?'View campaign':'Review draft'} &nbsp; →</button><div class="card-manage"><button class="linkbtn" onclick="hideCampaign(decodeURIComponent('${encodeURIComponent(campaignKey(c))}'))">Hide</button>${isSample(c)?'':`<button class="linkbtn danger" onclick="deleteCampaign(decodeURIComponent('${encodeURIComponent(campaignKey(c))}'))">Delete</button>`}</div></div></article>`).join('')||`<div class="panel"><b>Nothing in your list.</b><p class="small">Start a campaign, or bring back one you hid.</p></div>`}</div>${away.length?`<details class="panel hidden-campaigns"><summary><b>Hidden campaigns (${away.length})</b> <span class="small">— nothing was deleted</span></summary><div class="hidden-list">${away.map(c=>`<div class="flex small"><span>${esc(c.address)}</span><button class="alt" onclick="unhideCampaign(decodeURIComponent('${encodeURIComponent(campaignKey(c))}'))">Show again</button></div>`).join('')}</div></details>`:''}`;
}
function details(i){const c=[...state.campaigns,...examples][i]||visibleCampaigns()[0];$('#content').innerHTML=`<a onclick="dashboard('campaigns')" class="small">← All campaigns</a><div class="welcome flex" style="margin-top:22px"><div><span class="pill">${esc(c.status)}</span><h1>${esc(c.address)}</h1><p>${esc(c.area||'Campaign draft · saved in this browser')}</p></div><button class="alt" onclick="campaignReport([...state.campaigns,...examples][${i}]||c,7)">View report ↗</button></div>${!c.day?`<div class="notice">This draft is saved locally. Listing import, creative generation, payment and launch need to be connected to your production engine.</div><div class="panel"><b>Listing link</b><p>${esc(c.url)}</p><b>Photo and video folder</b><p>${esc(c.media)}</p><b>Meta ad budget</b><p>${esc(c.budget||'Use default spend (amount to be confirmed)')}</p></div>`:`<div class="notice">Sample campaign and illustrative schedule. No posts or ads are running.</div>`}<div class="panel"><div class="flex"><div><span class="eyebrow">THE CAMPAIGN PLAN</span><h3>Your 14 days, at a glance.</h3></div><span class="pill">Meta ad · Days 1–14</span></div><div class="calendar">${['Just listed','Property highlights','Room spotlight','Lifestyle story','Video walkthrough','Weekend viewing','Day 7 report','Neighbourhood','Design details','Property reel','Key features','Viewing reminder','Final spotlight','Day 14 report'].map((t,j)=>`<div class="day ${j===6||j===13?'report':''}"><b>DAY ${j+1}</b>${t}<em>${j===6||j===13?'Performance report':'Social content concept'}</em></div>`).join('')}</div><p class="fine">Illustrative content plan. Final assets and posting frequency come from your campaign engine.</p></div>`}
function accounts(){$('#content').innerHTML=`<div class="welcome"><h1>Your social connections.</h1><p>Connect once. Choose where each property campaign appears.</p></div><div class="notice connection-notice" id="connNotice">Prototype only. Sign in to connect a real Meta account.</div><div class="grid2"><div class="panel"><span class="eyebrow">META</span><h3>Facebook Page + ad account</h3><p id="connDetail">Choose the account you want to use for property marketing.</p><p id="connHealth" class="small" hidden></p><button id="metaConnectBtn" onclick="connectMeta()">Connect Meta</button><button class="alt" id="metaCheckBtn" onclick="checkConnections()">Check connection</button></div><div class="panel"><span class="eyebrow">◎ INSTAGRAM</span><h3>Instagram professional account</h3><p id="igDetail">A professional account linked to your Facebook Page is required for feed posts.</p></div></div>`;if(RM.isLoggedIn()){loadConnections()}else{const n=$('#connNotice');if(n)n.innerHTML='You are signed out, so no Meta account can be connected. <button class="alt" type="button" onclick="clientAccess(\'signin\')">Sign in →</button>';}}function disconnect(){state.connected=false;state.metaAudit=null;persist();dashboard('accounts')}
// --- Reports ---------------------------------------------------------------
// A backend-backed campaign carries the boost id the API needs. Local demo
// campaigns do not, so every caller falls back to the local behaviour.
function campaignBoostId(campaign){
 if(!campaign)return null;
 const id=campaign.boostId!=null?campaign.boostId:campaign.boost_id;
 return id===undefined||id===null||id===''?null:id;
}
function reportMoney(value){return value==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value))}
function reportMetricTiles(tiles){return tiles.map(([label,value])=>`<div><span>${esc(label)}</span><b>${value==null?'—':value}</b></div>`).join('')}
// The four headline tiles for a real report payload. A section whose source is not
// 'meta' carries no numbers, so it renders an em dash - never an invented figure.
function liveReportTiles(data){
 const organic=(data&&data.organic)||{},paid=(data&&data.paid)||{},summary=organic.summary||{};
 return [['People reached',organic.source==='meta'?summary.reach:null],['Engagements',organic.source==='meta'?summary.interactions:null],['Listing clicks',paid.source==='meta'?paid.clicks:null],['Ad spend',paid.source==='meta'?reportMoney(paid.spend):null]];
}
async function campaignReport(property,day){
 if(!property)return;
 const boostId=campaignBoostId(property);
 if(boostId!=null&&window.RM){
  show(`<span class="eyebrow">SELLER REPORT · DAY ${day}</span><h2>${esc(property.address||'')}</h2><p role="status">Loading the real report from the Resmara API…</p>`);
  try{
   const data=await RM.report(boostId,day);
   const organic=(data&&data.organic)||{},paid=(data&&data.paid)||{},posts=(data&&data.posts)||{};
   const notes=[];
   if(organic.source!=='meta')notes.push('Meta has not returned organic post data yet'+(organic.reason?': '+organic.reason:'.'));
   if(paid.source!=='meta')notes.push('Meta has not returned ad data yet'+(paid.reason?': '+paid.reason:'.'));
   const when=((data&&data.period)||{}).label||('Day 1 to Day '+day);
   show(`<span class="eyebrow">SELLER REPORT · DAY ${day}</span><h2>${esc((data&&data.address)||property.address||'')}</h2><p>${esc(when)}</p><div class="home-report-metrics">${reportMetricTiles(liveReportTiles(data))}</div><div class="check">${posts.published||0} of ${posts.total||0} posts published · ${posts.approved||0} approved</div>${notes.length?`<p class="fine">${notes.map(esc).join(' ')}</p>`:'<p class="fine">Live Meta figures for this period.</p>'}<div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
  }catch(e){
   show(`<h2>Report unavailable</h2><p>${esc(e.message)}</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
  }
  return;
 }
 // Local demo campaign: report only facts we actually hold (scheduled/approved) and say
 // plainly that Meta has not returned data. No sample metric is rendered as real.
 if(Number(property.day)<day)return;
 const campaigns=[...state.campaigns,...examples];
 const review=state.reviews&&state.reviews['review-'+(property.reviewId||campaigns.indexOf(property))];
 const items=(review&&review.items)||[];
 show(`<span class="eyebrow">SELLER REPORT · DAY ${day}</span><h2>${esc(property.address||'')}</h2><p>Local demo campaign · not connected to a backend boost.</p><div class="home-report-metrics">${reportMetricTiles([['People reached',null],['Engagements',null],['Listing clicks',null],['Ad spend',null]])}</div><div class="check">${items.length} posts scheduled · ${items.filter(item=>item.reviewed).length} spot-checked</div><p class="fine">Meta has not returned data yet. Connect a backend boost to see published, organic and paid figures.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
}
function normalizeWebLink(value){
 const link=value.trim();
 if(!link)return '';
 if(/\s/.test(link))return null;
 try{
  const url=new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(link)?link:'https://'+link);
  if(!['https:','http:'].includes(url.protocol)||!url.hostname.includes('.')||url.username||url.password)return null;
  return url.href;
 }catch{return null}
}
function show(html){html=html.replace(/<input\b[^>]*>/g,input=>input.replace('type="url"','type="text" inputmode="url" data-web-link'));modal.innerHTML=`<button class="close" aria-label="Close" onclick="modal.close()">×</button>${html}`;const form=modal.querySelector('form');
 if(form?.querySelector('[data-web-link]')){
  form.addEventListener('input',event=>{if(event.target.matches('[data-web-link]'))event.target.setCustomValidity('')});
  form.addEventListener('submit',event=>{
   for(const field of form.querySelectorAll('[data-web-link]')){
    const url=normalizeWebLink(field.value);
    if(url===null||(field.required&&!url)){
     event.preventDefault();event.stopImmediatePropagation();
     field.setCustomValidity('Enter a website address, such as www.bap.digital.');
     field.reportValidity();return;
    }
    field.value=url;
   }
  },true);
 }
 if(!modal.open)modal.showModal()}function newCampaign(){if(!state.clientSignedIn){clientAccess();return}if(!state.brand?.website){onboard();return}draft={};show(`<span class="eyebrow">NEW CAMPAIGN · 1 OF 2</span><h2>Show me your next listing.</h2><p>One property, one coordinated 14-day campaign.</p><form onsubmit="event.preventDefault();draft={address:this.address.value.trim(),addressSource:this.addressSource.value,placeId:this.placeId.value,url:this.url.value,media:this.media.value,photos:this.photos.value.split(String.fromCharCode(10)).map(link=>link.trim()).filter(Boolean).slice(0,10)};reviewDraft()"><div id="listing-address-lookup"></div><label class="field" id="listing-address-manual">Property address<input name="address" required autocomplete="off" placeholder="Start typing a street address" oninput="updateListingAddress(this)"></label><div id="listing-address-options" hidden><button type="button" class="alt listing-address-match" onclick="pickDemoListingAddress(this)">983 Mission De Oro Dr, Suite E, Redding, CA<small>Demo address suggestion</small></button></div><input type="hidden" name="addressSource" value="manual"><input type="hidden" name="placeId"><p id="listing-address-status" class="fine" aria-live="polite">Enter the full property address. Live suggestions require Google Places setup.</p><label class="field">MLS or public listing URL<input name="url" type="url" required placeholder="https://youragency.com/property/..."></label><label class="field">Photo and video folder URL (optional)<input name="media" type="url" placeholder="https://drive.google.com/... or Dropbox link"></label><p class="fine">Use a shared folder your campaign team can access.</p><label class="field">Direct photo links (optional)<textarea name="photos" rows="2" placeholder="Up to 10 public HTTPS image URLs, one per line"></textarea></label><p class="fine">For this test, use direct image links if you want Resmara to inspect and choose photos from your listing.</p><div class="modal-actions"><button type="button" class="alt" onclick="modal.close()">Cancel</button><button>Continue →</button></div></form>`);mountListingAddressLookup()}function reviewDraft(){
 // No credit gate: a campaign is $49 and Stripe charges for it when it is built, so the
 // draft can always be prepared. Losing the sale before the person has seen their calendar
 // was the worst part of the credit flow.
 show(`<h2>Preparing your property brief…</h2><p role="status">Resmara will draft this campaign for <strong>${esc(draft.address||'your listing')}</strong>. You pay $49 when you build it.</p><button hidden id="start-campaign-scope" type="button">Start campaign</button>`);
 startCampaignScope(modal.querySelector('#start-campaign-scope'));
}
function saveDraft(paidDraft){if(!paidDraft?.scopeFirst){reviewDraft();return;}state.campaigns.unshift({...paidDraft,reviewId:Date.now().toString(),status:'Draft',day:0});persist();modal.close();dashboard('campaigns');details(0);toast(paidDraft.liveGeneration?'Property scope ready for review.':'Demo draft ready for review.')}
// A browser that remembers "signed in" but holds a session that has ended must not open the
// dashboard on a dead token: it lands on the sign-in instead.
if(state.clientSignedIn&&window.RM&&!RM.isLoggedIn()){state.clientSignedIn=false;persist();}
if(location.hash==='#pricing'||(!location.hash&&document.body.dataset.page==='pricing'))pricing();else if(location.hash==='#dashboard'&&state.clientSignedIn)dashboard();else if(document.body.dataset.page==='how-it-works'||location.hash==='#how-it-works')howItWorks();else home();
// If a bearer token is stored, refresh the session from the backend (best effort).
// A token that has already passed its expiry is dropped by RM.isLoggedIn(), so this only
// asks when there is a real session to ask about.
if(window.RM&&RM.isLoggedIn())RM.me().then(u=>{if(u&&u.email){state.name=u.name||state.name;state.email=u.email;state.clientSignedIn=true;persist()}}).catch(()=>{});
// A profile kept on the account is the one that survives a cleared browser; a browser with
// no local brand takes it back rather than showing an empty My Brand form.
if(window.RM&&RM.isLoggedIn()&&RM.brandProfile)RM.brandProfile().then(remote=>{
 if(!remote||!Object.keys(remote).length)return;
 if(state.brand&&Object.keys(state.brand).length)return;
 state.brand={...remote};
 if(remote.brokerage&&!state.company)state.company=remote.brokerage;
 if(remote.agent&&!state.name)state.name=remote.agent;
 persist();if(view==='brand')myBrand();
}).catch(()=>{});
// When the backend stops accepting the session, say so once and stop pretending to be signed in.
if(window.RM&&RM.onSessionLost)RM.onSessionLost(()=>{
 state.clientSignedIn=false;persist();
 toast('Your session ended. Sign in again to keep working.');
 if(location.hash==='#dashboard'){const n=$('#connNotice');if(n)n.innerHTML='You are signed out, so no Meta account can be connected. <button class="alt" type="button" onclick="clientAccess(\'signin\')">Sign in →</button>';}
});

// Resmara stays available across the workspace and homepage.
const pipDock=document.createElement('div');pipDock.id='pip-dock';pipDock.innerHTML='<button class="pip-launcher" onclick="togglePip()" aria-label="Ask Resmara for help"><span class="robot-avatar" role="img" aria-label="Resmara, your three-dimensional robot guide"></span><span>Ask Resmara</span><span class="pip-online"></span></button><section id="pip-chat" class="pip-chat" hidden aria-label="Resmara support chat"><header class="flex"><div class="flex"><span class="robot-avatar" role="img" aria-label="Resmara, your three-dimensional robot guide"></span><div><b>Resmara</b><small>Real Estate Social Marketing, Analytics & Reporting Assistant</small></div></div><button class="pip-close" onclick="togglePip()" aria-label="Close Resmara chat">×</button></header><div id="pip-messages" class="pip-messages" aria-live="polite"><div class="pip-reply">Hi, I’m Resmara! I’ll help you get settled, build your campaign and find your way around. What can I help with?</div></div><div class="pip-questions"><button onclick="pipAnswer(0)">Start my first campaign</button><button onclick="pipAnswer(1)">Connect social accounts</button><button onclick="pipAnswer(2)">Fees and ad spend</button><button onclick="pipAnswer(3)">Find my reports</button></div><form class="pip-input" onsubmit="event.preventDefault();pipFreeText(this.question.value);this.reset()"><input name="question" aria-label="Message Resmara" required placeholder="Ask Resmara a question…"><button aria-label="Send message">↑</button></form><p class="pip-demo-note">Guided answers · anything else can be sent to the team as a real support request.</p></section>';document.body.append(pipDock);function togglePip(){const panel=document.querySelector('#pip-chat');panel.hidden=!panel.hidden}function pipMessage(t,mine=false){const e=document.createElement('div');e.className=mine?'pip-user':'pip-reply';e.textContent=t;document.querySelector('#pip-messages').append(e);e.scrollIntoView({block:'nearest'})}function pipAnswer(n){const questions=['How do I start my first campaign?','How do I connect my social accounts?','How do fees and ad spend work?','Where are my reports?'];const answers=['I’ll take you through it. Start with your profile and social accounts, then add your listing URL and your photo and video folder. Review your campaign before launch. In this demo, you can save a draft using “New campaign”.','Open Connected accounts in your dashboard. I’ll guide you through choosing your Facebook Page and Instagram account. This prototype uses demo accounts; a real Meta connection will be added later.','One credit builds one property campaign. Buy credits in My Credits. Meta ad spend is paid separately. There will be a default ad budget, and you can increase it. The amounts are still being finalised.','I’ll help you check progress at the halfway point and finish. Open Reports in your dashboard for day 7 and day 14 views. The figures in this prototype are sample data.'];pipMessage(questions[n],true);pipMessage(answers[n])}function pipFreeText(q){if(/start|first|campaign|listing/i.test(q))return pipAnswer(0);if(/connect|facebook|instagram|meta account/i.test(q))return pipAnswer(1);if(/cost|fee|price|budget|spend|pay/i.test(q))return pipAnswer(2);if(/report|result|performance/i.test(q))return pipAnswer(3);pipMessage(q,true);pipMessage('I keep to the guided answers above for setup, social connections, fees and reports. For anything else, send it to the team and a person will reply on your Support page.');pipOfferTicket(q)}


function confirmDemoCampaignCredit(button){
 if(button.disabled||!draft.address||!draft.url)return;
 button.disabled=true;
 const account=state,paidDraft={...draft,creditUsed:1,scopeFirst:true};
 show(`<span class="eyebrow">PREPARING YOUR PROPERTY SCOPE</span><h2>Resmara is preparing your property brief.</h2><div class="audit-track campaign-build-track"><span class="robot-avatar" aria-hidden="true"></span></div><p role="status">Gathering the listing and media references…</p><p class="fine">Demo setup · Uses the details you submitted. No live listing research or real payment has run.</p>`);
 const progress=modal.querySelector('[role="status"]');
 ['Preparing the property brief…','Applying your brokerage and brand profile…','Preparing your scope for approval…'].forEach((message,i)=>setTimeout(()=>{if(modal.open&&progress?.isConnected)progress.textContent=message},900+i*1500));
 setTimeout(()=>{if(state===account&&state.clientSignedIn&&modal.open&&progress?.isConnected)saveDraft(paidDraft)},5700);
}

function demoAddressMatches(value){
 const words=value.toLowerCase().match(/[a-z0-9]+/g)||[];
 return words.join('').length>=3&&words.every(word=>['983','mission','de','oro','drive','dr','suite','e','redding','california','ca'].some(part=>part.startsWith(word)));
}
function updateListingAddress(input){
 const form=input.form;
 form.elements.placeId.value='';
 form.elements.addressSource.value='manual';
 const match=!liveCampaignsAvailable()&&demoAddressMatches(input.value);
 form.querySelector('#listing-address-options').hidden=!match;
 form.querySelector('#listing-address-status').textContent=liveCampaignsAvailable()?'Manual address · enter the street, city and state.':match?'Select the demo match below the address field.':input.value.trim()?'No demo match. You can continue with the address you entered.':'Try 983 Mission De Oro, or enter another address manually.';
}
function pickDemoListingAddress(button){
 const form=button.closest('form');
 form.elements.address.value='983 Mission De Oro Dr, Suite E, Redding, CA';
 form.elements.addressSource.value='demo';
 form.elements.placeId.value='';
 form.querySelector('#listing-address-options').hidden=true;
 form.querySelector('#listing-address-status').textContent='Demo address selected · not verified by Google.';
 form.elements.address.focus();
}
let listingMapsLoad;
function loadListingMaps(key){
 if(window.google?.maps?.importLibrary)return Promise.resolve();
 if(!listingMapsLoad)listingMapsLoad=new Promise((resolve,reject)=>{
  const script=document.createElement('script');
  const timer=setTimeout(()=>finish(false),12000);
  function finish(ok){
   clearTimeout(timer);
   delete window.resmaraMapsReady;
   if(ok)resolve();else{script.remove();reject(new Error('Google Maps did not load.'))}
  }
  window.resmaraMapsReady=()=>finish(true);
  script.onerror=()=>finish(false);
  script.src='https://maps.googleapis.com/maps/api/js?'+new URLSearchParams({key,v:'weekly',loading:'async',callback:'resmaraMapsReady'});
  document.head.append(script);
 }).catch(error=>{listingMapsLoad=null;throw error});
 return listingMapsLoad;
}
async function mountListingAddressLookup(){
 const target=document.querySelector('#listing-address-lookup');
 if(!target)return;
 const form=target.closest('form'),manual=form.querySelector('#listing-address-manual');
 const address=form.elements.address,status=form.querySelector('#listing-address-status');
 const fallback=message=>{
  target.replaceChildren();
  manual.hidden=false;
  address.required=true;
  status.textContent=message;
 };
 try{
  if(!window.google?.maps?.importLibrary){
   // No Maps key is configured for this app, so the address is typed by hand. (This used to
   // ask a separate local test server for a key; that server no longer exists.)
   return;
  }
  const {PlaceAutocompleteElement}=await google.maps.importLibrary('places');
  if(!target.isConnected||address.value)return;
  const lookup=new PlaceAutocompleteElement();
  lookup.placeholder='Start typing a street address';
  lookup.setAttribute('aria-label','Property address');
  const label=document.createElement('b');
  label.textContent='Property address';
  const manualButton=document.createElement('button');
  manualButton.type='button';
  manualButton.className='alt';
  manualButton.textContent='Enter address manually';
  manualButton.onclick=()=>{fallback('Enter the full street address, city and state.');address.focus()};
  target.append(label,lookup,manualButton);
  manual.hidden=true;
  status.textContent='Type a street address, then select the match. Add the city to narrow results.';
  let selection=0;
  lookup.addEventListener('gmp-select',async ({placePrediction})=>{
   const request=++selection;
   try{
    const place=placePrediction.toPlace();
    await place.fetchFields({fields:['id','formattedAddress']});
    if(!lookup.isConnected||request!==selection)return;
    if(!place.formattedAddress)throw new Error('Missing address');
    address.value=place.formattedAddress;
    form.elements.addressSource.value='google-places';
    form.elements.placeId.value=place.id;
    fallback('Google Places address selected. Add a suite or unit if needed.');
    address.focus();
   }catch{if(lookup.isConnected&&request===selection)fallback('Google couldn’t load that address. Enter it manually.')}
  });
  lookup.addEventListener('gmp-error',()=>fallback('Google Places couldn’t load suggestions. Enter the address manually.'));
  form.addEventListener('submit',event=>{
   if(!lookup.isConnected||address.value)return;
   event.preventDefault();event.stopImmediatePropagation();
   status.textContent='Select a Google suggestion or choose Enter address manually.';
   lookup.focus();
  },true);
  address.required=false;
 }catch{if(target.isConnected)fallback('Google Places is unavailable. Enter the address manually.')}
}

/* Retired: the prototype generator used to run on its own server on port 8092, so every
 * live-generation hook also doubled as an origin check. That server is gone and the engine
 * now runs inside this app (review.js drives it through RM.buildCampaign / RM.posts /
 * RM.approveAll / RM.launch), so this gate is false everywhere and the hooks below stay on
 * the local demo path. Left in place deliberately: it is the honest fallback, not a bug.
 */
// A signed-in client runs the real thing: the boost is created through the API and the
// campaign engine lives inside this app. Signed-out visitors keep the demo path. (The old
// build was gated on the page being served from a standalone test server on 127.0.0.1:8092,
// which is why a real campaign was never created from the UI.)
function liveCampaignsAvailable(){return !!(window.RM&&RM.isLoggedIn())}
async function campaignEngineAvailable(){return liveCampaignsAvailable()}
// The first connected ad account, or null. The launch step needs one; building does not.
async function firstAdAccountId(){
 try{
  const rows=await RM.adAccounts();
  const list=Array.isArray(rows)?rows:(rows&&(rows.accounts||rows.items))||[];
  const real=list.find(a=>a&&a.id!=null&&!a.simulated)||list.find(a=>a&&a.id!=null);
  return real?real.id:null;
 }catch{return null}
}
async function startCampaignScope(button){
 if(button.disabled)return;button.disabled=true;
 const account=state,submitted={...draft};
 const live=await campaignEngineAvailable();
 if(state!==account||!modal.open||!button.isConnected)return;
 if(!live){
  button.disabled=false;
  confirmDemoCampaignCredit(button);return
 }
 show(`<span class="eyebrow">SETTING UP YOUR CAMPAIGN</span><h2>Resmara is preparing your campaign.</h2><div class="audit-track campaign-build-track"><span class="robot-avatar" aria-hidden="true"></span></div><p role="status">Saving the listing to your workspace and linking your ad account…</p>`);
 const progress=modal.querySelector('[role="status"]');
 try{
  const adAccountId=await firstAdAccountId();
  const boost=await RM.createBoost({address:submitted.address,campaign_days:14,ad_budget_usd:50,ad_account_id:adAccountId,property_facts:[submitted.facts,submitted.url?'Listing: '+submitted.url:''].filter(Boolean).join('\n')||undefined});
  if(!boost||boost.id==null)throw new Error('The API did not return a campaign id.');
  // Bring the gallery in now: a post can only show a photo that exists as an asset, so an
  // empty gallery here means a text-only calendar later. A bot-walled listing is not fatal.
  if(progress?.isConnected)progress.textContent='Finding the photos on your listing…';
  try{
   const pulled=await RM.importPhotos(boost.id,{listingUrl:submitted.url||undefined,urls:[...(submitted.photos||[])].slice(0,10),limit:10});
   if(progress?.isConnected&&pulled&&pulled.imported)progress.textContent='Imported '+pulled.imported+' listing photos. Linking your ad account…';
  }catch(photoError){/* keep going: the photos can be added from the campaign page */}
  liveCampaignsSyncedAt=0;
  if(state===account&&state.clientSignedIn&&modal.open&&progress?.isConnected)saveDraft({...submitted,creditUsed:1,scopeFirst:true,liveGeneration:true,boostId:boost.id,adAccountId:adAccountId||undefined});
 }catch(error){
  if(state===account&&modal.open&&progress?.isConnected){
   show(`<h2>We could not set up the campaign</h2><p>${esc(error.message)}</p><p>Nothing was charged and nothing was saved.</p><button class="alt" onclick="reviewDraft()">Try again</button>`);
  }
 }
}

/* --- Support: the client's side of the support desk -------------------------
 * The Support page and the in-page assistant both go through RM.createTicket /
 * RM.tickets, so a question the guided answers cannot cover becomes a real ticket the
 * operator answers in the console - instead of a dead end that says "not connected".
 */
function supportSignedIn(){return !!(window.RM&&RM.isLoggedIn())}
function supportPage(){
 const signedIn=supportSignedIn();
 $('#content').innerHTML=`<div class="welcome"><h1>Support.</h1><p>Ask a question or tell us what went wrong. Every request here is read by a person.</p></div>
 ${signedIn?'':'<div class="notice">Requests live in your workspace, so sign in first and we can see which campaign you mean and answer you in the same place.</div>'}
 <div class="grid2">
  <div class="panel"><span class="eyebrow">OPEN A REQUEST</span><h3>Tell us what you need.</h3>
   <label class="field">Subject<input id="ticketSubject" maxlength="120" placeholder="e.g. Instagram post failed on day 1"></label>
   <label class="field">Message<textarea id="ticketMessage" rows="5" maxlength="4000" placeholder="What happened, and what did you expect instead?"></textarea></label>
   <p class="fine" id="ticketFormMsg" role="status"></p>
   <button onclick="submitTicket()"${signedIn?'':' disabled'}>Send request</button>
   ${signedIn?'':'<button class="alt" onclick="clientAccess()" style="margin-left:8px">Sign in</button>'}
  </div>
  <div class="panel"><span class="eyebrow">YOUR REQUESTS</span><h3>What we have from you.</h3>
   <div id="ticketList">${signedIn?'<p class="fine">Loading your requests…</p>':'<p class="fine">Sign in to see your requests and our replies.</p>'}</div>
  </div>
 </div>`;
 if(signedIn)loadMyTickets();
}
async function loadMyTickets(){
 const box=document.querySelector('#ticketList');if(!box)return;
 try{
  const rows=await RM.tickets();
  if(!rows.length){box.innerHTML='<p class="fine">Nothing yet. Anything you send appears here with our reply.</p>';return}
  box.innerHTML=rows.map(t=>`<article class="panel" style="margin:0 0 12px">
   <div class="flex"><b>${esc(t.subject)}</b><span class="pill">${esc(t.status)}</span></div>
   <p class="fine">Request #${esc(t.id)} · raised ${esc(String(t.created_at||'').replace('T',' ').slice(0,16))} UTC</p>
   ${(t.messages||[]).map(m=>`<div style="border-left:2px solid #c7e2f2;padding-left:10px;margin:8px 0">
     <span class="eyebrow">${esc(m.from||'')}</span><p style="white-space:pre-wrap;margin:2px 0 0">${esc(m.text||'')}</p></div>`).join('')}
  </article>`).join('');
 }catch(error){
  const detail=(error&&error.status===401)?'Sign in to see your requests.':((error&&error.message)||'Could not load your requests.');
  box.innerHTML='<p class="fine">'+esc(detail)+'</p>';
 }
}
async function submitTicket(){
 const subject=(document.querySelector('#ticketSubject')||{}).value||'';
 const message=(document.querySelector('#ticketMessage')||{}).value||'';
 const msg=document.querySelector('#ticketFormMsg');
 const say=(text,cls)=>{if(msg){msg.className='fine '+(cls||'');msg.textContent=text}};
 if(!supportSignedIn())return say('Sign in first - a request is attached to your workspace.','bad');
 if(!subject.trim()||!message.trim())return say('A subject and a message, please.','bad');
 say('Sending…');
 try{
  const t=await RM.createTicket(subject.trim(),message.trim());
  say('Sent as request #'+t.id+'. The answer appears on this page.','ok');
  document.querySelector('#ticketSubject').value='';
  document.querySelector('#ticketMessage').value='';
  loadMyTickets();
 }catch(error){say('Not sent: '+((error&&error.message)||'unknown error'),'bad')}
}
function pipOfferTicket(q){
 const panel=document.querySelector('#pip-messages');if(!panel)return;
 const wrap=document.createElement('div');wrap.className='pip-reply';
 const lead=document.createElement('p');lead.textContent='That question is outside my guided answers. Send it to the team and a person will reply on your Support page.';
 wrap.append(lead);
 const btn=document.createElement('button');btn.type='button';btn.className='alt';btn.textContent='Send to support';
 btn.addEventListener('click',async()=>{
  if(!supportSignedIn()){pipMessage('Sign in first - a request is attached to your workspace, and the reply lands on your Support page.');return}
  btn.disabled=true;btn.textContent='Sending…';
  try{
   const t=await RM.createTicket(String(q||'').slice(0,120)||'Question from the Resmara assistant',String(q||''));
   pipMessage('Sent as request #'+t.id+'. The answer will appear on your Support page.');
   btn.remove();
  }catch(error){btn.disabled=false;btn.textContent='Send to support';pipMessage('Could not send that: '+((error&&error.message)||'unknown error'))}
 });
 wrap.append(btn);panel.append(wrap);wrap.scrollIntoView({block:'nearest'});
}


// ---- Meta connection (real, not the demo walkthrough) ----------------------
// The browser leaves the app for Facebook's consent screen and comes back through
// /api/oauth/meta/callback, which redirects to the app root with ?meta=… .
// One line per account, saying what Meta currently thinks of it: whether our access still
// works, and whether the customer's own card is on the account that pays for the ads.
// Nothing here is guessed - an unmeasured status says so.
function accountHealthLine(a){
 if(a.needs_reconnect)return 'Needs reconnecting: '+(a.token_note||'Meta will not accept this connection any more.');
 if(a.token_status==='simulated')return 'Demo connection — no Meta account is used and nothing is billed.';
 if(!a.token_status)return 'Not checked yet — run Check connection.';
 if(a.token_status==='expiring')return 'Access expires soon — '+(a.token_refresh_note||a.token_note||'reconnect before it does')+'.';
 const bits=['Access valid'];
 if(a.token_expires_at)bits.push('until '+String(a.token_expires_at).slice(0,10));
 if(a.funding_status==='has_funding')bits.push('payment method on file — the client is billed by Meta directly');
 else if(a.funding_status==='no_funding')bits.push('no payment method on the ad account — ads cannot run until one is added in Meta');
 else bits.push('payment method not checked yet');
 bits.push('ad account '+(a.account_status_label||'status not read'));
 return bits.join(' · ');
}
function loadConnections(){
 RM.adAccounts().then(rows=>{
  const list=(Array.isArray(rows)?rows:[]).filter(a=>a.platform==='meta');
  const n=$('#connNotice'),d=$('#connDetail'),h=$('#connHealth');if(!n)return;
  const live=list.filter(a=>a.is_active!==false);
  if(live.length){
   const broken=live.filter(a=>a.needs_reconnect);
   n.textContent=live.length+' Meta ad account'+(live.length>1?'s':'')+' connected to your account.'
    +(broken.length?' — '+broken.length+' need'+(broken.length>1?'':'s')+' reconnecting.':'');
   if(d)d.textContent=live.map(a=>(a.account_name||a.advertiser_id)+' ('+a.advertiser_id+', '+a.currency+')').join(' · ');
   if(h){h.hidden=false;h.innerHTML=live.map(a=>'<b>'+esc(a.account_name||a.advertiser_id)+'</b>: '+esc(accountHealthLine(a))).join('<br>');}
  }else{
   n.textContent='No Meta account is connected yet. Connect one to post and run ads.';
   if(d)d.textContent='Choose the account you want to use for property marketing.';
   if(h)h.hidden=true;
  }
 }).catch(e=>{const n=$('#connNotice');if(n)n.textContent='Could not read your connections: '+e.message;});
}
// Ask the backend - and through it, Meta - for the current state of every connection.
function checkConnections(){
 if(!RM.isLoggedIn()){toast('Sign in first');return;}
 const b=$('#metaCheckBtn');if(b){b.disabled=true;b.textContent='Checking…';}
 const done=()=>{if(b){b.disabled=false;b.textContent='Check connection';}loadConnections();};
 RM.checkConnections().then(r=>{
  const broken=(r&&r.needs_reconnect)||[],unfunded=(r&&r.not_ready_to_spend)||[];
  if(broken.length)toast('Reconnect needed: '+broken.join(', '));
  else if(unfunded.length)toast('Ad account cannot run ads yet: '+unfunded.join(', '));
  else toast('Checked '+((r&&r.checked)||0)+' connection(s) — all good.');
 }).catch(e=>toast('Check failed: '+e.message)).then(done,done);
}
function connectMeta(){
 // No session, no consent: send them to the sign-in form instead of letting the request
 // come back 401 and reporting that as a Meta problem.
 if(!RM.isLoggedIn()){toast('Sign in first — then Connect Meta.');if(window.clientAccess)clientAccess('signin');return;}
 const b=$('#metaConnectBtn');if(b){b.disabled=true;b.textContent='Opening Facebook…';}
 const reset=()=>{if(b){b.disabled=false;b.textContent='Connect Meta';}};
 RM.metaConnect().then(r=>{
  if(r&&r.redirect_url){location.href=r.redirect_url;return;}
  reset();
  toast(r&&r.demo_mode?'Meta is not configured on the server yet.':'Meta did not return a consent link.');
 }).catch(e=>{
  reset();
  if(e&&e.status===401){toast('Your session ended — sign in again, then Connect Meta.');if(window.clientAccess)clientAccess('signin');return;}
  toast('Could not start the Meta connection: '+(e&&e.message?e.message:'unknown error'));
 });
}
// Landing back from Meta: say what actually happened, then open the connections page.
function metaReturnNotice(){
 const p=new URLSearchParams(location.search),m=p.get('meta');if(!m)return;
 const n=document.createElement('div');n.className='notice connection-notice';
 if(m==='connected')n.textContent='Meta connected — '+p.get('accounts')+' ad account(s) and '+p.get('pages')+' Page(s) authorised.';
 else if(m==='no_accounts')n.textContent='Meta authorised, but this login can see no ad accounts. Add the ad account to the Meta app, or connect a login that owns it.';
 else n.textContent='Meta connection failed: '+(p.get('reason')||m);
 document.body.prepend(n);
 history.replaceState(null,'',location.pathname+location.hash);
 if(RM.isLoggedIn()){state.clientSignedIn=true;state.name=state.name||'there';persist();dashboard('accounts');}
}
window.addEventListener('load',()=>{try{metaReturnNotice();}catch(e){}});
