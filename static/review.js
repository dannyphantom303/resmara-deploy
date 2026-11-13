// Local interaction prototype based on the Boost workflow. No engine requests or external side effects.
var ReviewStudio={active:0,building:new WeakSet()};
function reviewCampaign(){return [...state.campaigns,...examples][ReviewStudio.active]}
function reviewCampaignBoostId(){return campaignBoostId(reviewCampaign())}
// Real listing-photo count for a backend-backed campaign (falls back to nothing in the demo).
/* The strip is the engine's shortlist, not a folder listing: strongest-selling photo first, each
 * thumb labelled with the space it shows. An owner who sees the kitchen on post 3 should find the
 * kitchen at the top of this strip, not wherever the camera wrote it. */
async function refreshPhotoAssets(){
 const node=document.querySelector('[data-photo-count]');if(!node)return;
 const boostId=reviewCampaignBoostId();if(boostId==null||!window.RM)return;
 try{
  const data=(window.RM.gallery?await RM.gallery(boostId):null)||{};
  const photos=(Array.isArray(data.photos)?data.photos:[]).filter(a=>(a.kind||'photo')==='photo');
  if(!photos.length){node.textContent='No photos on this campaign yet, so the calendar has no images. Paste the listing link below or upload the photos.';const empty=document.querySelector('[data-photo-thumbs]');if(empty)empty.innerHTML='';return}
  const tagged=photos.filter(p=>p.room);
  const rooms=new Set(tagged.filter(p=>p.usable!==false).map(p=>p.room)).size;
  node.textContent=photos.length+' listing photo'+(photos.length===1?'':'s')
    +(tagged.length===photos.length&&rooms
      ? ' on this campaign · '+rooms+' different space'+(rooms===1?'':'s')+' · in the order Resmara will use them, best first.'
      : ' uploaded. Resmara reads each one when it builds — that is when the spaces are labelled and the strongest shot leads.');
  const strip=document.querySelector('[data-photo-thumbs]');
  if(strip)strip.innerHTML=photos.map((a,i)=>'<figure class="photo-thumb'+(a.usable===false?' unusable':'')+'">'
    +'<img src="'+esc(a.url)+'" alt="'+esc(a.room||a.original_name||'Listing photo')+'" loading="lazy">'
    +'<figcaption><b>'+(i+1)+'</b>'+(a.room?' '+esc(a.room):'')+(a.score!=null?' · '+esc(String(a.score)):'')+'</figcaption></figure>').join('');
 }catch(e){node.textContent='Could not read this campaign’s photos. Refresh and try again.'}
}
/* Photos the engine can actually use. Posts carry an image only when the plan names an
 * Asset, so this panel is the difference between a photo calendar and a text one. */
function photosPanel(r){
 const boostId=reviewCampaignBoostId();
 if(boostId==null)return '';
 const listing=String((r.scope&&r.scope.listing)||'');
 const seed=/^https?:\/\//i.test(listing)?esc(listing):'';
 return '<section class="panel campaign-photos"><h2 class="campaign-step-title"><span>1</span> Listing photos</h2>'
  +'<p data-photo-count>Checking this campaign’s photos…</p>'
  +'<p class="fine">Paste the listing link and Resmara pulls the gallery. Movoto and Trulia links work directly; Zillow, Realtor, Redfin and Homes.com block server reads, so those are matched to the same property on Trulia by address. Or upload the photos yourself — without photos the calendar stays text-only.</p>'
  +'<label class="scope-field">Listing link<input id="photo-listing-url" type="url" inputmode="url" placeholder="https://www.trulia.com/home/… or https://www.movoto.com/…" value="'+seed+'"></label>'
  +'<div class="modal-actions">'
  +'<button class="campaign-primary" type="button" onclick="importListingPhotos(this)">Import photos from listing →</button>'
  +'<label class="alt button-like">Upload photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onchange="uploadCampaignPhotos(this)"></label>'
  +'</div><p class="fine" role="status" data-photo-status></p><div class="photo-thumbs" data-photo-thumbs></div></section>';
}
async function importListingPhotos(button){
 const boostId=reviewCampaignBoostId();if(boostId==null||!window.RM)return;
 const field=document.getElementById('photo-listing-url');
 const status=document.querySelector('[data-photo-status]');
 const url=((field&&field.value)||'').trim();
 if(!/^https?:\/\//i.test(url)){if(status)status.textContent='Paste the full listing link first.';if(field)field.focus();return}
 button.disabled=true;if(status)status.textContent='Pulling the gallery from that page…';
 try{
  const res=await RM.importPhotos(boostId,{listingUrl:url,limit:20});
  const n=(res&&res.imported)||0;
  if(status)status.textContent=n
   ?'Imported '+n+' photo'+(n===1?'':'s')+'. Rebuild the campaign to put them in the calendar.'
   :(res&&res.detail)||'No photos found on that page. Try direct image links or uploads.';
  await refreshPhotoAssets();
 }catch(e){if(status)status.textContent=e.message}
 finally{button.disabled=false}
}
async function uploadCampaignPhotos(input){
 const boostId=reviewCampaignBoostId();if(boostId==null||!window.RM)return;
 const files=[...(input.files||[])];if(!files.length)return;
 const status=document.querySelector('[data-photo-status]');
 if(status)status.textContent='Uploading '+files.length+' photo'+(files.length===1?'':'s')+'…';
 let ok=0,failed=[];
 // A photo that fails to upload must be named, not counted. An owner who drops 61 files and
 // reads "Uploaded 56" has no way to know which five to send again.
 for(const file of files){
  try{await RM.uploadPhoto(file,boostId,'photo');ok++}
  catch(e){failed.push(file.name+(e&&e.message?' ('+e.message+')':''))}
 }
 if(status)status.textContent=ok
  ?('Uploaded '+ok+(failed.length?' — '+failed.length+' did not go: '+failed.slice(0,3).join(', ')+(failed.length>3?', and '+(failed.length-3)+' more':''):'')+'. Rebuild the campaign to put them in the calendar.')
  :('Upload failed for '+failed.length+' photo'+(failed.length===1?'':'s')+(failed.length?' — '+failed[0]:'')+'.');
 input.value='';await refreshPhotoAssets();
}
// A live campaign's calendar must show what the backend actually stored. Opening a campaign
// in a browser that has never built it used to leave the demo tiles (stock photos, made-up
// captions) on screen, which reads as "the photos never made it". Silent: no toast, and it
// only repaints when something really changed, so it cannot loop with details().
async function hydrateReviewItems(r){
 const id=(typeof reviewCampaignBoostId==='function')?reviewCampaignBoostId():null;
 if(id==null||!window.RM||!RM.posts||!r||r._hydrating)return;
 r._hydrating=true;
 try{
  const posts=await RM.posts(id);
  if(!Array.isArray(posts)||!posts.length)return;
  const mapped=posts.map(post=>({id:post.id,postId:post.id,day:post.day||1,
   title:post.title||String(post.caption||'Scheduled post').split(/[.\n]/)[0].slice(0,42)||'Scheduled post',
   kicker:post.kicker||'',overlay:post.overlay_text||'',room:post.photo_room||'',
   kind:post.kind==='short_video'?'Video post':'Photo post',caption:post.caption||'',
   image:post.image_url||'',reviewed:post.client_status==='approved',
   time:(post.publish_at||'').slice(11,16)||undefined}));
  const key=items=>items.map(x=>[x.id,x.day,x.image,x.title,x.overlay].join('|')).join(',');
  if(key(mapped)===key(r.items))return;
  r.items=mapped;r.needsBuild=false;persist();
  if(activeReview()===r&&ReviewStudio.active!=null)details(ReviewStudio.active);
 }catch(e){}finally{r._hydrating=false}
}
function details(index){if(ReviewStudio.active!==index)ReviewStudio.month=null;ReviewStudio.active=index;const c=[...state.campaigns,...examples][index];if(!c)return;const key='review-'+(c.reviewId||index);state.reviews=state.reviews||{};if(!state.reviews[key])state.reviews[key]={approved:false,items:(c.scopeFirst||campaignBoostId(c)!=null)?[]:sampleReviewItems(c)};const r=state.reviews[key];r.scopeFirst=Boolean(c.scopeFirst)||(campaignBoostId(c)!=null&&!Number(c.posts_total||0)&&!r.approved);r.liveGeneration=Boolean(c.liveGeneration)||campaignBoostId(c)!=null;r.scope ||= initialCampaignScope(c);if(examples.includes(c)&&!r.scope.demoBrief&&!r.scopeConfirmed&&!r.approved){r.scope.highlights ||= demoPropertyHighlights(c);r.scope.demoBrief=true;}$('#content').innerHTML=`<div class="review-heading"><h1>${esc(r.scope.address)}</h1></div>${campaignScopePanel(r)}${photosPanel(r)}${reviewCalendar(r,c)}<div class="review-approval"><div><h2 class="campaign-step-title"><span>3</span> ${r.approved?'Campaign approved':'Approve the campaign'}</h2><p>Approve the full calendar when you’re happy with the scope and creative.</p><p class="fine">${r.approved?'Approval saved. Nothing has been published.':!r.items.length?'Approve the property scope to build the calendar.':r.items.filter(i=>i.reviewed).length+' of '+r.items.length+' items spot-checked · Individual review is optional. Approve the scope and calendar first.'}</p></div>${r.approved?'<button onclick="launchOrder()">Review launch →</button>'+(reviewCampaignBoostId()!=null?' <button class="alt" onclick="publishApprovedPosts()">Publish approved posts →</button>':''):`<button class="campaign-primary scope-approval-button" onclick="approveReview()" ${r.scopeConfirmed&&r.calendarApproved&&r.items.length?'':'disabled'}>Approve entire campaign →</button>`}</div><section class="panel"><h3>Reports for this property</h3><ul class="campaign-report-list">${[7,14].map(day=>`<li><strong>Day ${day} report</strong>${Number(c.day)>=day?`<button class="alt" onclick="campaignReport([...state.campaigns,...examples][${index}],${day})">View report ↗</button>`:`<span class="fine">${c.day?'Available on day '+day:'Available after launch'}</span>`}</li>`).join('')}</ul></section>`;refreshPhotoAssets();hydrateReviewItems(r);persist()}
function sampleReviewItems(c){return Array.from({length:16},(_,i)=>({id:i,day:i<2?1:i-1,title:i===0?'Photo carousel ad':i===1?'Video ad':['Just listed','Property highlights','Step inside','Room spotlight','The details','Video walkthrough','Weekend viewing','A closer look','Neighbourhood','Design details','Property reel','Key features','Viewing reminder','Final spotlight'][i-2],kind:i<2?'Meta ad':([4,7,12,15].includes(i)?'Video post':'Photo post'),caption:campaignSampleCaption(c,i),image:i%3===0?img2:img,reviewed:false}))}
function activeReview(){return state.reviews['review-'+(([...state.campaigns,...examples][ReviewStudio.active]||{}).reviewId||ReviewStudio.active)]}
function reviewCheck(k,v){const r=activeReview();if(r.approved)return;r[k]=v;persist()}
function editCampaignItem(i){
 const r=activeReview(),it=r.items[i],slot=reviewSlot(r,it),brand=r.brandProfile||campaignBrandProfile();
 const locked=r.approved||r.calendarApproved,disabled=locked?'disabled':'',ad=it.kind==='Meta ad';
 show(`<span class="eyebrow">${esc(it.kind)} · ${ad?'Days 1–14':'Day '+it.day}</span><h2>${esc(it.title)}</h2><div class="review-preview" style="--agent-colour:${/^#[0-9a-f]{6}$/i.test(brand.colour)?brand.colour:'#143a50'}">${it.image?`<span class="creative-frame"><img src="${esc(it.image)}" alt="Campaign creative">${it.overlay?`<em class="post-overlay">${esc(it.overlay)}</em>`:''}${it.kicker?`<span class="post-kicker">${esc(it.kicker)}</span>`:''}</span>`:'<p class="fine">No photo selected yet.</p>'}${campaignBrandPreview(brand)}</div>${it.room?`<p class="fine">Photo: ${esc(it.room)} — the copy above is written for this photo.</p>`:''}<p>${esc(reviewDateLabel(slot.date,slot.time,r.scope.zone))}</p><p class="fine">${esc(it.visualBrief||'Sample creative preview.')}</p><form onsubmit="event.preventDefault();saveReviewItem(${i},this)"><label class="field">Title<input name="title" required value="${esc(it.title)}" ${disabled}></label><label class="field">Text on the photo<input name="overlay" maxlength="60" placeholder="Words that sit on the image" value="${esc(it.overlay||'')}" ${disabled}></label><label class="field">Caption<textarea name="caption" required ${disabled}>${esc(it.caption)}</textarea></label>${locked?'':`<label class="field">Upload a replacement photo<input name="photo" type="file" accept="image/png,image/jpeg,image/webp"></label><label class="field">Or use an image URL<input name="image" type="url" placeholder="Leave blank to keep the current photo"></label><p class="fine">PNG, JPEG or WebP, up to 500 KB in this preview.</p>${ad?'':`<label class="field">Publishing date<input name="publishDate" type="date" required min="${esc(r.scope.start)}" max="${esc(reviewSlot(r,{day:14}).date)}" value="${esc(slot.date)}"></label><label class="field">Publishing time (${esc(r.scope.zone)})<input name="publishTime" type="time" required value="${esc(slot.time)}"></label><p class="fine">Choosing a date with another post swaps their slots.</p>`}`}<p class="fine" role="alert"></p><div class="modal-actions"><button type="button" class="alt" onclick="modal.close()">Close</button>${locked?'':'<button>Save and mark reviewed ✓</button>'}</div></form>`);
}
function postDay(r,date){
 const day=1+(Date.parse(date)-Date.parse(r.scope.start))/86400000;
 return Number.isInteger(day)&&day>=1&&day<=14?day:null;
}
function moveReviewPost(r,index,date){
 const item=r.items[index],day=postDay(r,date);
 if(!item||item.kind==='Meta ad'||!day||r.approved||r.calendarApproved)return false;
 const origin=reviewSlot(r,item);
 if(origin.date===date)return false;
 const other=r.items.find(post=>post!==item&&post.kind!=='Meta ad'&&reviewSlot(r,post).date===date);
 const time=reviewSlot(r,other||{day}).time;
 if(other)Object.assign(other,{day:postDay(r,origin.date),date:origin.date,time:origin.time,reviewed:false});
 Object.assign(item,{day,date,time,reviewed:false});
 return true;
}
function dropReviewPost(event,date){
 event.preventDefault();
 const value=event.dataTransfer.getData('application/x-resmara-post');
 if(!/^\d+$/.test(value))return;
 const r=activeReview();
 if(moveReviewPost(r,Number(value),date)){persist();details(ReviewStudio.active);toast('Posting order updated.')}
}
async function saveReviewItem(i,form){
 const r=activeReview(),item=r.items[i],button=form.querySelector('button:not([type])'),error=form.querySelector('[role="alert"]');
 if(!item||r.approved||r.calendarApproved||button.disabled)return;
 button.disabled=true;error.textContent='';
 const before=r.items.map(post=>({...post}));
 try{
  const url=form.elements.image.value.trim(),file=form.elements.photo.files[0];
  if(!file&&url&&!['https:','http:'].includes(new URL(url).protocol))throw new Error('Use an HTTPS or HTTP image URL.');
  const image=file?await readBrandImage(file):url||item.image;
  if(!form.isConnected||!modal.open||activeReview()!==r||r.approved||r.calendarApproved)return;
  const date=form.elements.publishDate?.value,time=form.elements.publishTime?.value;
  const oldTime=reviewSlot(r,item).time;
  if(date)moveReviewPost(r,i,date);
  Object.assign(item,{title:form.elements.title.value,overlay:form.elements.overlay?form.elements.overlay.value:item.overlay,caption:form.elements.caption.value,image,reviewed:true});
  if(time&&(!date||date===reviewSlot(r,before[i]).date||time!==oldTime))item.time=time;
  // Approving this post is a backend call when the campaign is backed by a real boost.
  const boostId=reviewCampaignBoostId(),postId=item.postId??item.post_id;
  if(window.RM&&boostId!=null&&postId!=null){
   try{await RM.approvePost(postId)}
   catch(e){r.items=before;throw new Error('Couldn’t approve this post: '+e.message)}
  }
  // A replacement photo uploads to the backend boost; the local preview stands either way.
  if(window.RM&&boostId!=null&&file){
   try{await RM.uploadPhoto(file,boostId,'photo')}catch{}
  }
  try{localStorage.setItem('resmara',JSON.stringify(state))}catch{
   r.items=before;
   throw new Error('This browser couldn’t save the change. Try a smaller photo or an image URL.');
  }
  modal.close();details(ReviewStudio.active);
 }catch(e){error.textContent=e.message}finally{button.disabled=false}
}
function demoPropertyHighlights(c){
 return ({
 '1248 Oakridge Drive':'Open kitchen and living area, covered outdoor seating, and a pool. Lead with the exterior and follow with the kitchen and pool.',
 '76 Willow Lane':'Bright living room, updated kitchen, and a private backyard. Lead with the front exterior and the main living spaces.',
 '309 Cedar House':'Spacious grounds and an outdoor entertaining area. Use a wide exterior first, then show the living areas and grounds.'
 })[c.address]||'';
}
function nextCampaignDate(){
 const date=new Date();date.setDate(date.getDate()+1);
 return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
}
function initialCampaignScope(c){
 return {address:c.address,listing:c.url||'',media:c.media||'',facts:c.research?.facts||c.area||'',highlights:c.research?.highlights||'',photoPlan:c.research?.photoPlan||'Prioritize front and rear exterior, kitchen, living room and standout features. Include a pool, waterfront or land when present. Skip routine toilet and closet photos.',start:c.scopeFirst?nextCampaignDate():'2026-11-02',time:'10:00',zone:c.research?.zone||(examples.includes(c)?'America/Chicago':Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'),budget:'50'};
}
const scopeFields=[
 ['address','Property address','text'],['listing','Public listing or MLS URL','url'],['media','Photo and video gallery URL','url'],['facts','Property facts (price, beds, baths, size)','textarea'],['start','Go-live date','date'],['highlights','Standout features and location','textarea'],['photoPlan','Photo priorities and exclusions','textarea'],['budget','Meta ad budget','text']
];
function campaignScopePanel(r){
 const s=r.scope,locked=r.scopeConfirmed||r.approved;
 const budget=Number(s.budget)>0?Number(s.budget):50;
 const renderField=([key,label,type])=>key==='budget'?`<label class="scope-field">Select your Meta ad budget<select name="budget">${[...new Set([50,75,100,150,200,budget])].sort((a,b)=>a-b).map(amount=>`<option value="${amount}" ${amount===budget?'selected':''}>$${amount}${amount===50?' · Default':''}</option>`).join('')}</select></label>`:`<label class="scope-field">${label}${type==='textarea'? `<textarea name="${key}" rows="2">${esc(s[key])}</textarea>`:`<input name="${key}" type="${type==='url'?'text':type}" ${type==='url'?'inputmode="url"':''} value="${esc(s[key])}" ${['address','start'].includes(key)?'required':''}>`}</label>`;
 const columns=[['Listing details',['address','listing','media','facts','start']],['Creative & budget',['highlights','photoPlan','budget']]];
 return `<details class="panel campaign-scope" ${locked?'':'open'}><summary class="campaign-step-title">Property scope ${locked?'<small>✓ Scope Approved</small>':''}</summary><p>Review the brief that guides your campaign. Check the listing facts, photo priorities and go-live date before approving. Resmara recommends local posting times when it builds the calendar. Your saved My Brand profile supplies the agent details and creative style.</p><p class="fine">${r.liveGeneration?'Drafted from your listing submission and the details you supplied. Verify the facts before approving.':s.demoBrief?'Example of a populated research brief. Property highlights are sample data.':'Prefilled from your listing submission. Property research isn’t connected in this preview.'}</p>${r.liveGeneration?scopeResearchSources():''}<form onsubmit="event.preventDefault();saveCampaignScope(this)"><fieldset ${locked?'disabled':''}><legend class="sr-only">Property scope details</legend><div class="scope-form-columns">${columns.map(([title,keys])=>`<div class="scope-form-column"><h3>${title}</h3>${keys.map(key=>renderField(scopeFields.find(field=>field[0]===key))).join('')}</div>`).join('')}</div></fieldset><div class="scope-form-actions"><p class="fine">${r.scopeFirst&&r.items.length&&!locked?'Approving this revised scope replaces the current demo creative. ':'Campaign cost: 1 credit. ' }Meta ad spend is separate.</p>${locked?`<div class="scope-locked"><strong>✓ Scope Approved</strong>${r.approved?'':'<button type="button" class="alt" onclick="unlockCampaignScope()">Unlock scope</button>'}</div>`:'<button class="campaign-primary scope-approval-button">Approve Property Scope →</button>'}<p class="fine" data-photo-count></p>${reviewCampaignBoostId()==null?'':(r.items&&r.items.length?'':'<button type="button" class="alt" onclick="rebuildLiveCampaign()">Build content with Resmara →</button>')}</div></form></details>`;
}
function unlockCampaignScope(){
 const r=activeReview();if(r.approved||ReviewStudio.building.has(r))return;
 r.scopeConfirmed=false;r.calendarApproved=false;persist();details(ReviewStudio.active);
}
function saveCampaignScope(form){
 const r=activeReview();if(r.approved||r.scopeConfirmed)return;
 const next={};
 for(const [key,,type] of scopeFields){
  const field=form.elements[key];
  const value=field.value.trim();
  next[key]=type==='url'?normalizeWebLink(value):value;
  if(next[key]===null||(['address','start'].includes(key)&&!value)){toast('Check the '+field.closest('label').firstChild.textContent.toLowerCase()+' field.');field.focus();return}
 }
 if(next.start!==r.scope.start)ReviewStudio.month=null;
 r.scope={...r.scope,...next};r.brandProfile=campaignBrandProfile();r.scopeConfirmed=true;r.calendarApproved=false;r.needsBuild=r.scopeFirst;
 // The scope form already collects the photo gallery URL. Use it: a scope that names a
 // gallery but leaves the campaign with no photos is exactly the "why is my calendar blank"
 // case. Failing here must not block approval — the photos panel can still import by hand.
 const gallery=String(r.scope.media||r.scope.listing||'').trim();
 const boostId=reviewCampaignBoostId();
 if(boostId!=null&&window.RM&&/^https?:\/\//i.test(gallery)){
  RM.importPhotos(boostId,{listingUrl:gallery,limit:20}).then(res=>{
   if(res&&res.imported)toast('Imported '+res.imported+' listing photo'+(res.imported===1?'':'s')+'.');
   else if(res&&res.detail)toast(res.detail);
   refreshPhotoAssets();
  }).catch(()=>{});
 }
 persist();if(r.scopeFirst){buildApprovedScope();return}details(ReviewStudio.active);document.querySelector('.review-calendar')?.scrollIntoView({block:'start'});toast('Property scope approved.');
}

function reviewSlot(r,item){
 const date=new Date(r.scope.start+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+(item.day||1)-1);
 return {date:item.date||date.toISOString().slice(0,10),time:item.time||(item.kind==='Meta ad'?r.scope.time:['10:00','12:00','17:30'][((item.day||1)-1)%3])};
}
function reviewDateLabel(date,time,zone){
 const d=new Date(date+'T'+time+':00Z');
 if(Number.isNaN(d.getTime()))return 'Schedule not set';
 const label=new Intl.DateTimeFormat('en-US',{weekday:'short',month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit',timeZone:'UTC'}).format(d);
 return label+' · '+zone.replace('America/','').replaceAll('_',' ');
}
function approveReview(){
 const r=activeReview();if(r.approved)return;
 if(!r.scopeConfirmed||!r.calendarApproved||!r.items.length){toast('Approve the property scope and calendar first.');document.querySelector('.campaign-scope')?.scrollIntoView({block:'start'});return}
 show(`<h2>Approve the entire campaign?</h2><p>This approves all ${r.items.length} scheduled assets, including any you haven’t opened. Nothing goes live or gets charged at this step.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Keep reviewing</button><button onclick="confirmCampaignApproval()">Approve all →</button></div>`);
}
async function confirmCampaignApproval(){
 const r=activeReview();if(r.approved||!r.scopeConfirmed||!r.calendarApproved||!r.items.length)return;
 const boostId=reviewCampaignBoostId();
 if(boostId!=null&&window.RM){
  const buttons=[...modal.querySelectorAll('button')];
  buttons.forEach(b=>b.disabled=true);
  try{await RM.approveAll(boostId)}
  catch(e){
   buttons.forEach(b=>b.disabled=false);
   show(`<h2>Couldn’t approve the campaign</h2><p>${esc(e.message)}</p><p class="fine">Nothing was changed. Try again once the API is reachable.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
   return;
  }
 }
 r.approved=true;r.approvedAt=new Date().toISOString();persist();modal.close();details(ReviewStudio.active);
}

function changeReviewMonth(offset){
 const r=activeReview(),month=ReviewStudio.month||r.scope.start.slice(0,7);
 const d=new Date(month+'-01T12:00:00Z');d.setUTCMonth(d.getUTCMonth()+offset);
 ReviewStudio.month=d.toISOString().slice(0,7);
 const host=document.querySelector('.review-calendar');host.outerHTML=reviewCalendar(r,[...state.campaigns,...examples][ReviewStudio.active]);document.querySelector('.review-calendar').open=true;
}
function reviewCalendar(r,c){
 if(r.scopeFirst&&(!r.scopeConfirmed||!r.items.length||r.needsBuild||ReviewStudio.building.has(r))){
  return `<section class="panel review-calendar"><h2 class="campaign-step-title"><span>2</span> Campaign calendar</h2><p>${ReviewStudio.building.has(r)?'Resmara is building your draft posts and ads.':r.scopeConfirmed?'Your scope is approved. Build the draft to fill your calendar.':'Approve the property scope first. Resmara will use it to build the posts and ads for this calendar.'}</p>${r.scopeConfirmed&&!ReviewStudio.building.has(r)?'<button class="campaign-primary" onclick="buildApprovedScope()">Build campaign calendar →</button>':''}${r.scopeConfirmed&&!ReviewStudio.building.has(r)&&reviewCampaignBoostId()!=null?' <button class="alt" onclick="buildCampaignFromBackend()">Build with the Resmara engine →</button>':''}</section>`;
 }
 const month=ReviewStudio.month||r.scope.start.slice(0,7);
 const first=new Date(month+'-01T12:00:00Z'),end=new Date(first);end.setUTCMonth(end.getUTCMonth()+1);
 const gridStart=new Date(first);gridStart.setUTCDate(1-first.getUTCDay());
 const title=new Intl.DateTimeFormat('en-US',{month:'long',year:'numeric',timeZone:'UTC'}).format(first);
 const start=r.scope.start,last=reviewSlot(r,{day:14}).date;
 const posts=r.items.map((item,index)=>({item,index,...reviewSlot(r,item)}));
 const editable=!r.approved&&!r.calendarApproved;
 const ads=posts.filter(x=>x.item.kind==='Meta ad');
 const weeks=[];
 for(let cursor=new Date(gridStart);cursor<end;cursor.setUTCDate(cursor.getUTCDate()+7)){
  const dates=Array.from({length:7},(_,i)=>{const d=new Date(cursor);d.setUTCDate(d.getUTCDate()+i);return d.toISOString().slice(0,10)});
  const from=dates.findIndex(date=>date>=start&&date<=last);
  const to=dates.findLastIndex(date=>date>=start&&date<=last);
  const bars=from<0?'':ads.map(({item,index},lane)=>`<button class="review-month-ad" style="grid-column:${from+1}/${to+2};grid-row:${lane+2}" onclick="editCampaignItem(${index})" title="${esc(item.title)} · ${esc(start)}–${esc(last)}">${esc(item.title)}${item.reviewed?' ✓':''}</button>`).join('');
  weeks.push(`<div class="review-month-week" style="--post-row:${from<0?2:ads.length+2}">${dates.map((date,col)=>`<span class="review-month-date ${date.startsWith(month)?'':'outside-month'}" style="grid-column:${col+1}">${Number(date.slice(-2))}</span>`).join('')}${bars}${dates.map((date,col)=>{
   const reportDay=[7,14].find(day=>reviewSlot(r,{day}).date===date);
   return `<div class="review-month-cell ${date.startsWith(month)?'':'outside-month'}" style="grid-column:${col+1}" ${editable&&postDay(r,date)?`ondragover="if(event.dataTransfer.types.includes('application/x-resmara-post'))event.preventDefault()" ondrop="dropReviewPost(event,'${date}')"`:''}>${posts.filter(x=>x.item.kind!=='Meta ad'&&x.date===date).map(({item,index,time})=>`<button class="review-calendar-post" ${editable?`draggable="true" ondragstart="event.dataTransfer.setData('application/x-resmara-post','${index}');event.dataTransfer.effectAllowed='move'"`:''} onclick="editCampaignItem(${index})">${item.image?`<span class="calendar-media"><img src="${esc(item.image)}" alt="${esc(item.room||'')}">${item.kicker?`<span class="post-kicker">${esc(item.kicker)}</span>`:''}${item.overlay?`<em class="post-overlay">${esc(item.overlay)}</em>`:''}</span>`:''}<b>${esc(item.title)}</b><small>${esc(time)}${item.reviewed?' · ✓':''}</small></button>`).join('')}${reportDay?`<span class="review-calendar-report">${Number(c.day)>=reportDay?`<button class="alt" onclick="campaignReport([...state.campaigns,...examples][ReviewStudio.active],${reportDay})">● View report</button>`:'● Report due'}</span>`:''}</div>`;
  }).join('')}</div>`);
 }
 return `<details class="panel review-calendar" ${r.calendarApproved||r.approved?'':'open'}><summary class="campaign-step-title"><span>2</span> Campaign calendar ${r.calendarApproved||r.approved?'<small>✓ Calendar Approved</small>':''}</summary><p>This is your campaign calendar for the month. Open any post or ad to check its information and creative before you approve. You only need to open the items you want to spot-check or change.</p>${editable?'<p class="fine">Drag a post to another campaign day, or change its date in the post editor.</p>':''}<div class="flex review-month-nav"><button class="alt" onclick="changeReviewMonth(-1)" aria-label="Previous month">‹</button><strong>${title}</strong><button class="alt" onclick="changeReviewMonth(1)" aria-label="Next month">›</button></div><p class="fine">Times in ${esc(r.scope.zone)} · Ads run ${esc(start)} at ${esc(r.scope.time)} through ${esc(last)}, end of day.</p><div class="review-month-scroll"><div class="review-month-grid"><div class="review-month-weekdays">${['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d=>`<span>${d}</span>`).join('')}</div>${weeks.join('')}</div></div><p class="fine">${r.liveGeneration?'Draft copy, captions and creative directions from your campaign engine'+(r.engine&&r.engine.host?' ('+esc(r.engine.host)+')':'')+'. Nothing has been published.':'Sample schedule and creative. Nothing is published from this preview.'}${r.buildNotes&&r.buildNotes.length?' '+r.buildNotes.map(esc).join(' '):''}</p><div class="scope-form-actions"><span class="fine">${r.scopeConfirmed?'Confirm the dates and creative before approving.':'Approve the property scope first.'}</span>${r.approved?'':r.calendarApproved?'<button class="alt" onclick="unlockCampaignCalendar()">Unlock calendar</button>':`<button class="campaign-primary scope-approval-button" onclick="approveCampaignCalendar()" ${r.scopeConfirmed?'':'disabled'}>Approve Campaign Calendar →</button>`}</div></details>`;
}

function approveCampaignCalendar(){
 const r=activeReview();if(!r.scopeConfirmed||r.approved||!r.items.length||r.needsBuild||ReviewStudio.building.has(r))return;
 r.calendarApproved=true;persist();details(ReviewStudio.active);
 document.querySelector('.review-approval')?.scrollIntoView({block:'nearest'});
}
function unlockCampaignCalendar(){
 const r=activeReview();if(r.approved)return;
 r.calendarApproved=false;persist();details(ReviewStudio.active);
}

function buildApprovedScope(){
 const r=activeReview(),account=state;
 if(!r.scopeFirst||!r.scopeConfirmed||r.approved||ReviewStudio.building.has(r))return;
 const scope={...r.scope,...(r.brandProfile||campaignBrandProfile())};
 ReviewStudio.building.add(r);r.calendarApproved=false;
 show(`<span class="eyebrow">BUILDING YOUR CAMPAIGN</span><h2>Resmara is turning your scope into a campaign.</h2><div class="audit-track campaign-build-track"><span class="robot-avatar" aria-hidden="true"></span></div><p role="status">Planning 14 days of content…</p><p class="fine">${r.liveGeneration?'Resmara is drafting the 14 days of posts, captions and the ad from your approved brief.':'Demo build · Uses your approved brief and sample images.'}</p>`);
 const progress=modal.querySelector('[role="status"]');
 if(r.liveGeneration){ReviewStudio.building.delete(r);buildCampaignFromBackend();return}
 ['Writing drafts from your approved property details…','Applying your brand to the creative previews…','Placing the posts and ads on the calendar…'].forEach((text,i)=>setTimeout(()=>{if(progress?.isConnected)progress.textContent=text},900+i*1500));
 setTimeout(()=>{
  ReviewStudio.building.delete(r);
  if(state!==account||!r.scopeConfirmed)return;
  r.items=sampleReviewItems({address:scope.address}).map(item=>{
   const feature=item.id===0||item.id===2?scope.highlights:item.id===3?scope.facts:'';
   const friendly=/friendly|warm|conversational/i.test(scope.voice);
   return {...item,caption:[(friendly?'Come take a look at ':'Discover ')+scope.address+'.',feature,scope.brokerage?'Contact '+scope.brokerage+' for listing details.':'View the listing for more details.',scope.listing].filter(Boolean).join(' ')};
  });
  r.needsBuild=false;persist();
  if(progress?.isConnected&&modal.open)modal.close();
  if(document.querySelector('.campaign-scope')&&activeReview()===r){
   details(ReviewStudio.active);
   document.querySelector('.review-calendar')?.scrollIntoView({block:'start'});
   toast('Your demo calendar is ready to review.');
  }
 },5700);
}

// Build the calendar from the real content engine (POST /api/boosts/{id}/build + GET .../posts).
async function buildCampaignFromBackend(){
 const r=activeReview(),boostId=reviewCampaignBoostId();
 if(boostId==null||!window.RM){toast('This demo campaign isn’t linked to a backend boost yet.');return}
 if(!r.scopeFirst||!r.scopeConfirmed||r.approved||ReviewStudio.building.has(r))return;
 ReviewStudio.building.add(r);
 show(`<span class="eyebrow">BUILDING YOUR CAMPAIGN</span><h2>Resmara is turning your scope into a campaign.</h2><div class="audit-track campaign-build-track"><span class="robot-avatar" aria-hidden="true"></span></div><p role="status">Running the content engine…</p>`);
 const progress=modal.querySelector('[role="status"]');
 let finalStatus=null;
 try{
  const started=await RM.buildCampaign(boostId,{force:false});
  // The build is a background run (four model calls, minutes long) — a single request would be
  // cut by any hosted proxy. Poll the status, then read the posts it wrote.
  if(started&&started.status==='running'){
   const waitStart=Date.now(), limitMs=9*60*1000; let last='running';
   while(Date.now()-waitStart<limitMs){
    await new Promise(res=>setTimeout(res,3000));
    const st=(await RM.buildStatus(boostId).catch(()=>null))||{};
    if(progress?.isConnected){
     const secs=Math.round((Date.now()-waitStart)/1000);
     progress.textContent=`Running the content engine… ${secs}s${st.posts_created?` · ${st.posts_created} posts drafted`:''}`;
    }
    if(st.status==='error') throw new Error(st.error||'The content engine stopped without an error message.');
    if(st.status==='done'){finalStatus=st;last='done';break}
   }
   if(last!=='done') throw new Error('The build is still running after 9 minutes. Check the campaign again in a moment — the posts it writes are saved either way.');
  }
  const backendPosts=await RM.posts(boostId);
  const result=finalStatus||started||{};
  if(Array.isArray(backendPosts)&&backendPosts.length){
   r.items=backendPosts.map(post=>({id:post.id,postId:post.id,day:post.day||1,title:post.title||String(post.caption||'Scheduled post').split(/[.\n]/)[0].slice(0,42)||'Scheduled post',kicker:post.kicker||'',overlay:post.overlay_text||'',room:post.photo_room||'',kind:post.kind==='short_video'?'Video post':'Photo post',caption:post.caption||'',image:post.image_url||'',reviewed:post.client_status==='approved',time:(post.publish_at||'').slice(11,16)||undefined}));
  }
  r.needsBuild=false;r.engine=(result&&result.engine)||null;r.buildNotes=((result&&result.notes)||[]).slice();r.buildSource=(result&&result.source)||'';
  ReviewStudio.building.delete(r);   // before the re-render: the calendar draws its "building" state otherwise
  persist();
  if(progress?.isConnected&&modal.open)modal.close();
  if(activeReview()===r){details(ReviewStudio.active);document.querySelector('.review-calendar')?.scrollIntoView({block:'start'})}
  toast('Campaign built: '+(result&&result.posts_created!=null?result.posts_created:r.items.length)+' posts created'+(r.engine&&r.engine.host?' — drafted by '+r.engine.host:'')+'.');
 }catch(e){
  // 402 = this campaign has not been paid for. The API says so in a machine-readable detail,
  // so show the price and the checkout button instead of "build paused" and a dead end.
  if(e&&e.status===402){ReviewStudio.building.delete(r);showPaywall(boostId,e.detail);return}
  if(progress?.isConnected&&modal.open)show(`<h2>Campaign build paused</h2><p>${esc(e.message)}</p><p class="fine">Your approved scope is saved. You can retry any time.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Back to campaign</button></div>`);
 }finally{ReviewStudio.building.delete(r)}
}

// Launch the approved campaign through the real API (POST /api/launch).
// A live draft whose build produced no posts: retry through the same backend path. The scope is
// already approved at that point, which is exactly why buildCampaignFromBackend()'s guard would
// otherwise return without doing anything.
async function rebuildLiveCampaign(){
 const r=activeReview(),boostId=reviewCampaignBoostId();
 if(boostId==null||!window.RM)return;
 const approved=r.approved;r.approved=false;r.scopeConfirmed=true;r.scopeFirst=true;
 try{await buildCampaignFromBackend()}finally{r.approved=approved;persist()}
}

async function launchCampaignViaApi(){
 const boostId=reviewCampaignBoostId();
 if(boostId==null||!window.RM){toast('This demo campaign isn’t linked to a backend boost yet.');return}
 show(`<span class="eyebrow">LAUNCHING</span><h2>Launching your campaign…</h2><p role="status">Checking the budget and approvals, then creating the Meta campaign paused…</p>`);
 try{
  const result=await RM.launch(boostId,{auto_approve:false});
  if(result&&['approval_required','no_ad_account','nothing_to_launch'].includes(result.status)){
   const reasons=(Array.isArray(result.reasons)&&result.reasons.length)?result.reasons:[result.detail||result.message||'The API did not launch this campaign.'];
   const heading=result.status==='no_ad_account'?'Connect your Meta ad account first':result.status==='nothing_to_launch'?'Build and approve the campaign first':'Approval needed before launch';
   show(`<span class="eyebrow">LAUNCH HELD</span><h2>${heading}</h2><ul class="campaign-report-list">${reasons.map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul><p class="fine">Nothing was published and no spend was authorised.</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
   return;
  }
  show(`<h2>Campaign launched</h2><div class="check">Meta campaign ${esc(String((result&&result.meta_campaign_id)||'created'))} created paused.</div><p class="fine">${result&&result.simulated?'Simulated mode · no live Meta calls were made.':'Created paused; you activate it in Meta Ads Manager.'}</p><div class="modal-actions"><button onclick="modal.close()">Close</button></div>`);
 }catch(e){
  show(`<h2>Launch failed</h2><p>${esc(e.message)}</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
 }
}

function campaignBrandPreview(brand){
 const image=(kind,label)=>{const source=state.brandMedia?.[brand[kind+'Id']];return source?`<img src="${esc(source)}" alt="${label}">`:''};
 return `<div class="creative-brand-strip">${image('logo','Brokerage logo')}${image('headshot','Agent headshot')}<div><strong>${esc(brand.agent||brand.brokerage||'Your agency')}</strong><small>${[brand.agent?brand.brokerage:'',brand.license?'License '+brand.license:''].filter(Boolean).map(esc).join(' · ')}</small></div></div>`;
}

function scopeResearchSources(){
 const c=[...state.campaigns,...examples][ReviewStudio.active];
 return c?.research?.sources?.length?`<details class="fine"><summary>Listing research sources</summary><ul>${c.research.sources.map(url=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a></li>`).join('')}</ul></details>`:'';
}
// Send the approved, due posts out now (POST /api/content/publish/boost/{id}) and then read
// back exactly what Meta accepted, what is still scheduled and what failed - with its error.
async function publishApprovedPosts(){
 const boostId=reviewCampaignBoostId();
 if(boostId==null||!window.RM){toast('This demo campaign isn’t linked to a backend boost yet.');return}
 show(`<span class="eyebrow">PUBLISHING</span><h2>Sending the approved posts out…</h2><p role="status">Handing the approved, due posts to the platform…</p>`);
 const progress=modal.querySelector('[role="status"]');
 try{await RM.publishNow(boostId)}catch(e){
  if(progress?.isConnected&&modal.open)show(`<h2>Publishing stopped</h2><p>${esc(e.message)}</p><div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
  return;
 }
 let status=null;
 try{status=await RM.publishStatus(boostId)}catch(e){}
 if(!modal.open)return;
 const posts=(status&&status.posts)||[];
 const counts=(status&&status.counts)||{};
 const published=posts.filter(p=>p.publish_status==='published');
 const failed=posts.filter(p=>p.publish_status==='failed');
 const waiting=posts.filter(p=>!p.publish_status||p.publish_status==='scheduled');
 const lines=posts.map(p=>`<li>Day ${p.day} · ${esc(p.kind||'post')} · <b>${esc(p.publish_status||'scheduled')}</b>${p.publish_target?' → '+esc(p.publish_target):''}${p.fb_post_id?' · FB '+esc(p.fb_post_id):''}${p.ig_media_id?' · IG '+esc(p.ig_media_id):''}${p.last_error?' · <span class="fine">'+esc(p.last_error)+'</span>':''}</li>`).join('');
 show(`<h2>${published.length?'Published':'Nothing published yet'}</h2><div class="check">${published.length} published · ${waiting.length} still scheduled · ${failed.length} failed</div>${posts.length?`<ul class="campaign-report-list">${lines}</ul>`:'<p class="fine">No posts to publish: build the campaign first.</p>'}${failed.length?'<p class="fine">A failed post is only retried after its error is fixed - fix the reason above, then publish again.</p>':''}${waiting.length&&!published.length?'<p class="fine">Posts go out on their scheduled day; the publisher also runs on its own schedule.</p>':''}<div class="modal-actions"><button class="alt" onclick="modal.close()">Close</button></div>`);
}
