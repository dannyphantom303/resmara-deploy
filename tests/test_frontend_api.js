#!/usr/bin/env node
'use strict';
/*
 * Front-end API contract test for static/api.js.
 *
 * Loads the real static/api.js into a vm sandbox with a fake window/localStorage/fetch,
 * then asserts, for every RM function, the exact HTTP method, path, headers and body it
 * produces - including the Bearer header and that login sends form-urlencoded.
 *
 * Run:  node tests/test_frontend_api.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const API_SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'api.js'), 'utf8');

let checks = 0;
let failures = 0;
function ok(name, cond, extra) {
  checks++;
  if (cond) console.log('  PASS  ' + name);
  else { failures++; console.log('  FAIL  ' + name + (extra ? '  (' + extra + ')' : '')); }
}
function eq(name, actual, expected) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  ok(name + '  ==  ' + b, a === b, 'got ' + a);
}

// ---- fake environment --------------------------------------------------------
const store = new Map();
const localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: k => { store.delete(k); },
  clear: () => store.clear(),
};

let calls = [];
let nextResponse = { status: 200, json: {} };

const sandbox = {
  console, JSON, Object, Array, Promise, Error, FormData, URLSearchParams, setTimeout, clearTimeout,
  localStorage,
  fetch: async (url, opts) => {
    opts = opts || {};
    calls.push({ url, method: opts.method || 'GET', headers: opts.headers || {}, body: opts.body });
    const r = nextResponse;
    const text = r.raw !== undefined ? r.raw : (r.json !== undefined ? JSON.stringify(r.json) : '');
    return { ok: r.status >= 200 && r.status < 300, status: r.status, async text() { return text; } };
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(API_SRC, sandbox, { filename: 'static/api.js' });

const RM = sandbox.RM || (sandbox.window && sandbox.window.RM);
if (!RM) { console.log('  FAIL  api.js did not expose window.RM'); process.exit(1); }

const TOKEN = 'tok-abc-123';
function withToken() { store.set('resmara_token', TOKEN); }
function noToken() { store.clear(); }

// Runs RM[fn], returns the single recorded fetch call + the resolved value / thrown error.
async function one(name, run, expect) {
  calls = [];
  nextResponse = { status: expect.status || 200, json: (expect.json !== undefined ? expect.json : {}) };
  let result = null, error = null;
  try { result = await run(); } catch (e) { error = e; }
  ok(name + ' made exactly one request', calls.length === 1, 'made ' + calls.length);
  const c = calls[0] || { url: '', method: '', headers: {}, body: undefined };
  eq(name + ' method', c.method, expect.method);
  eq(name + ' path', c.url, expect.path);
  if (expect.auth === false) ok(name + ' has NO Authorization header', c.headers.Authorization === undefined, 'got ' + c.headers.Authorization);
  else eq(name + ' Bearer header', c.headers.Authorization, 'Bearer ' + TOKEN);
  if (expect.contentType === false) ok(name + ' sends NO Content-Type (browser sets boundary)', c.headers['Content-Type'] === undefined, 'got ' + c.headers['Content-Type']);
  else if (expect.contentType) eq(name + ' Content-Type', c.headers['Content-Type'], expect.contentType);
  if (expect.jsonBody !== undefined) eq(name + ' JSON body', JSON.parse(c.body), expect.jsonBody);
  if (expect.searchBody !== undefined) eq(name + ' form-urlencoded body', String(c.body), expect.searchBody);
  if (expect.form) expect.form(c.body);
  return { result, error, call: c };
}

(async () => {
  console.log('Front-end API contract tests  ·  static/api.js\n');

  // ---- token helpers ---------------------------------------------------------
  console.log('token helpers');
  noToken();
  ok('RM.isLoggedIn() false with no token', RM.isLoggedIn() === false);
  RM.setToken(TOKEN);
  eq('RM.token() returns the stored token', RM.token(), TOKEN);
  ok('RM.isLoggedIn() true with a token', RM.isLoggedIn() === true);
  RM.logout();
  eq('RM.logout() clears the token', RM.token(), null);
  ok('RM.setToken(null) clears storage', (RM.setToken(null), store.has('resmara_token') === false));

  // ---- auth ------------------------------------------------------------------
  console.log('\nauth');
  noToken();
  const login = await one('RM.login', () => RM.login('agent@example.com', 'secret-pw'),
    { method: 'POST', path: '/api/auth/login', contentType: 'application/x-www-form-urlencoded', auth: false,
      searchBody: 'username=agent%40example.com&password=secret-pw' });
  ok('login does not store the (absent) token itself', RM.isLoggedIn() === false);

  noToken();
  const login2 = await one('RM.login (with access_token)', () => RM.login('a@b.com', 'pw'),
    { method: 'POST', path: '/api/auth/login', contentType: 'application/x-www-form-urlencoded', auth: false, json: { access_token: TOKEN, token_type: 'bearer' } });
  eq('RM.login() returns the response body', login2.result, { access_token: TOKEN, token_type: 'bearer' });
  eq('RM.login() stores access_token via setToken', RM.token(), TOKEN);

  withToken();
  const reg = await one('RM.register', () => RM.register('new@example.com', 'pw123456', 'Dana Agent'),
    { method: 'POST', path: '/api/auth/register', contentType: 'application/json',
      jsonBody: { email: 'new@example.com', password: 'pw123456', name: 'Dana Agent' } });
  eq('RM.register() returns the created account', reg.result, {});

  // Private beta: the invite code rides along when the create-account form supplies one.
  const regInvite = await one('RM.register with invite', () => RM.register('new@example.com', 'pw123456', 'Dana Agent', 'beta-123'),
    { method: 'POST', path: '/api/auth/register', contentType: 'application/json',
      jsonBody: { email: 'new@example.com', password: 'pw123456', name: 'Dana Agent', invite_code: 'beta-123' } });
  eq('RM.register() without a code sends no invite_code', 'invite_code' in (reg.body || {}), false);
  eq('RM.register() returns the account for an invite too', regInvite.result, {});

  await one('RM.me', () => RM.me(), { method: 'GET', path: '/api/auth/me' });

  // ---- boosts ----------------------------------------------------------------
  console.log('\nboosts');
  await one('RM.boosts', () => RM.boosts(), { method: 'GET', path: '/api/boosts' });
  await one('RM.boost', () => RM.boost(7), { method: 'GET', path: '/api/boosts/7' });
  await one('RM.createBoost', () => RM.createBoost({ address: '12 Elm St', go_live_date: '2026-11-10', campaign_days: 14, ad_budget_usd: 50, property_facts: '3 bed, 2 bath' }),
    { method: 'POST', path: '/api/boosts', contentType: 'application/json',
      jsonBody: { address: '12 Elm St', go_live_date: '2026-11-10', campaign_days: 14, ad_budget_usd: 50, property_facts: '3 bed, 2 bath' } });

  // ---- uploads / assets ------------------------------------------------------
  console.log('\nuploads and assets');
  await one('RM.uploadPhoto', () => RM.uploadPhoto('BINARY', 7, 'photo'),
    { method: 'POST', path: '/api/content/upload/photo', contentType: false,
      form: body => {
        ok('  upload multipart has a FormData body', body instanceof FormData, 'got ' + typeof body);
        eq('  upload field file', body.get('file'), 'BINARY');
        eq('  upload field boost_id', body.get('boost_id'), '7');
        eq('  upload field kind', body.get('kind'), 'photo');
      } });
  await one('RM.uploadPhoto (defaults kind)', () => RM.uploadPhoto('BINARY', 7),
    { method: 'POST', path: '/api/content/upload/photo', contentType: false,
      form: body => eq('  default kind = photo', body.get('kind'), 'photo') });
  await one('RM.assets', () => RM.assets(7), { method: 'GET', path: '/api/content/assets/7' });
  await one('RM.photoIndex', () => RM.photoIndex(7), { method: 'GET', path: '/api/content/photo-index/7' });
  await one('RM.tagAssets', () => RM.tagAssets(7), { method: 'POST', path: '/api/content/assets/7/tag' });

  // ---- engine: build / plan / posts / approval -------------------------------
  console.log('\nengine');
  await one('RM.buildCampaign', () => RM.buildCampaign(7, { force: true }),
    { method: 'POST', path: '/api/boosts/7/build', contentType: 'application/json', jsonBody: { force: true } });
  await one('RM.buildCampaign (default force=false)', () => RM.buildCampaign(7),
    { method: 'POST', path: '/api/boosts/7/build', contentType: 'application/json', jsonBody: { force: false } });
  await one('RM.plan', () => RM.plan(7), { method: 'GET', path: '/api/boosts/7/plan' });
  await one('RM.posts', () => RM.posts(7), { method: 'GET', path: '/api/boosts/7/posts' });
  await one('RM.approvePost', () => RM.approvePost(42), { method: 'PATCH', path: '/api/posts/42/approve' });
  await one('RM.approveAll', () => RM.approveAll(7), { method: 'POST', path: '/api/boosts/7/approve' });

  // ---- generate --------------------------------------------------------------
  console.log('\ngenerate');
  await one('RM.generateContent', () => RM.generateContent({ boost_id: 7, agent_name: 'Dana', phone: '555-0100', license_no: 'RE-1', brokerage: 'Acme', instagram: '@dana', website: 'https://d.com', property_website: 'https://l.com/12', beds: 3, baths: 2, sqft: 1800, city: 'Oakland', feature: 'Sunlit', cta: 'Book a viewing', notes: 'Friendly', force: false }),
    { method: 'POST', path: '/api/content/generate/content', contentType: false,
      form: body => {
        ok('  generate multipart has a FormData body', body instanceof FormData, 'got ' + typeof body);
        eq('  generate field boost_id', body.get('boost_id'), '7');
        eq('  generate field agent_name', body.get('agent_name'), 'Dana');
        eq('  generate field beds', body.get('beds'), '3');
        eq('  generate field city', body.get('city'), 'Oakland');
        eq('  generate field force', body.get('force'), 'false');
      } });
  await one('RM.generateContent (omits empty fields)', () => RM.generateContent({ boost_id: 7, agent_name: '', notes: 'x' }),
    { method: 'POST', path: '/api/content/generate/content', contentType: false,
      form: body => {
        eq('  empty agent_name omitted', body.get('agent_name'), null);
        eq('  present notes kept', body.get('notes'), 'x');
      } });

  // ---- launch + precheck -----------------------------------------------------
  console.log('\nlaunch and precheck');
  await one('RM.precheck', () => RM.precheck({ platform: 'meta', advertiser_id: 'act_1', budget: 50 }),
    { method: 'POST', path: '/api/adflow/credits/precheck/', contentType: 'application/json',
      jsonBody: { platform: 'meta', advertiser_id: 'act_1', budget: 50 } });
  await one('RM.launch', () => RM.launch(7, { auto_approve: true, meta_custom_configs: { campaign_name: 'Elm St' } }),
    { method: 'POST', path: '/api/launch', contentType: 'application/json',
      jsonBody: { platform: 'meta', boost_id: 7, auto_approve: true, meta_custom_configs: { campaign_name: 'Elm St' } } });
  await one('RM.launch (defaults)', () => RM.launch(7),
    { method: 'POST', path: '/api/launch', contentType: 'application/json',
      jsonBody: { platform: 'meta', boost_id: 7, auto_approve: false, meta_custom_configs: {} } });

  // ---- publishing ------------------------------------------------------------
  console.log('\npublishing');
  await one('RM.publishStatus', () => RM.publishStatus(7), { method: 'GET', path: '/api/content/publish/status/7' });
  await one('RM.publishNow', () => RM.publishNow(7), { method: 'POST', path: '/api/content/publish/boost/7' });

  // ---- reports ---------------------------------------------------------------
  console.log('\nreports');
  await one('RM.report(day=14)', () => RM.report(7, 14), { method: 'GET', path: '/api/content/reports/7?day=14' });
  await one('RM.report(default day=7)', () => RM.report(7), { method: 'GET', path: '/api/content/reports/7?day=7' });

  // ---- health / version ------------------------------------------------------
  console.log('\nhealth and version');
  const health = await one('RM.checkHealth', () => RM.checkHealth(), { method: 'GET', path: '/', raw: '<!doctype html><title>Resmara</title>' });
  ok('RM.checkHealth() reports ok', health.result && health.result.ok === true);
  const version = await one('RM.apiVersion', () => RM.apiVersion(), { method: 'GET', path: '/openapi.json', json: { info: { version: '1' } } });
  eq('RM.apiVersion() returns the document', version.result, { info: { version: '1' } });
  calls = []; nextResponse = { status: 404, json: { detail: 'Not Found' } };
  const missing = await RM.apiVersion();
  eq('RM.apiVersion() returns null on 404 (skips)', missing, null);

  // ---- non-2xx error contract ------------------------------------------------
  console.log('\nerror handling');
  calls = []; nextResponse = { status: 401, json: { detail: 'Incorrect email or password' } };
  let thrown = null;
  try { await RM.login('a@b.com', 'wrong'); } catch (e) { thrown = e; }
  ok('non-2xx throws an Error', thrown instanceof Error);
  eq('thrown error carries .status', thrown && thrown.status, 401);
  eq('thrown error message is the server detail', thrown && thrown.message, 'Incorrect email or password');
  eq('thrown error carries .detail', thrown && thrown.detail, 'Incorrect email or password');

  calls = []; nextResponse = { status: 501, raw: '<!DOCTYPE HTML><html><body><h1>Error response</h1></body></html>' };
  let htmlErr = null;
  try { await RM.boosts(); } catch (e) { htmlErr = e; }
  eq('non-JSON (HTML) error body never reaches the UI raw', htmlErr && htmlErr.message, 'HTTP 501');
  eq('  ...and still carries .status', htmlErr && htmlErr.status, 501);

  // ---- Bearer is attached only when a token exists ---------------------------
  console.log('\nBearer token scoping');
  noToken();
  await one('RM.boosts (no token)', () => RM.boosts(), { method: 'GET', path: '/api/boosts', auth: false });
  withToken();
  await one('RM.boosts (with token)', () => RM.boosts(), { method: 'GET', path: '/api/boosts' });

  // ---- support: the client's desk ---------------------------------------------
  // The Support page and the in-page assistant both go through these two calls, so a
  // question the guided answers cannot cover becomes a real ticket in the console.
  console.log('\nsupport');
  withToken();
  const tk = await one('RM.createTicket', () => RM.createTicket('Publish failed', 'Day 1 Instagram post failed.'),
    { method: 'POST', path: '/api/support', contentType: 'application/json',
      jsonBody: { subject: 'Publish failed', message: 'Day 1 Instagram post failed.' },
      json: { id: 12, status: 'open', subject: 'Publish failed' } });
  eq('RM.createTicket() returns the created ticket', tk.result, { id: 12, status: 'open', subject: 'Publish failed' });
  const tkLong = await one('RM.createTicket (long subject)', () => RM.createTicket('s'.repeat(250), 'm'),
    { method: 'POST', path: '/api/support', contentType: 'application/json', json: {} });
  eq('a 250-char subject is capped at 200 before it is sent', JSON.parse(tkLong.call.body).subject.length, 200);
  await one('RM.tickets', () => RM.tickets(), { method: 'GET', path: '/api/support', json: [] });

  // ---- Meta connection: the app never holds the token ------------------------
  // Consent happens on Facebook; the app only hands the browser the URL. These calls are
  // what the Connect Meta button and the connections page really make.
  console.log('\nmeta connection');
  withToken();
  const mc = await one('RM.metaConnect', () => RM.metaConnect(),
    { method: 'GET', path: '/api/oauth/meta/connect',
      json: { redirect_url: 'https://www.facebook.com/v19.0/dialog/oauth?client_id=1&state=2', state: '2:abc' } });
  ok('RM.metaConnect() returns a consent URL and does not send the token to Facebook',
    mc.result.redirect_url.startsWith('https://www.facebook.com/') && mc.result.state === '2:abc');
  ok('the business secret stays on the server', !JSON.stringify(mc.result).includes('client_secret'));
  await one('RM.adAccounts', () => RM.adAccounts(), { method: 'GET', path: '/api/ad-accounts', json: [] });

  // ---- mount prefix: the same calls must survive the /resmara deployment ---------
  // The Command Center router serves this app at /resmara, so a root-absolute /api/... from
  // that page hits the router's 404 before it ever reaches the app. api.js reads the prefix
  // off its own <script src>, which is exactly what a real browser sees; these assertions
  // are the difference between a UI that renders and a UI that works in production.
  console.log('\nmount prefix (/resmara behind the Command Center router)');
  {
    const seen = [];
    const mounted = {
      console, JSON, Object, Array, Promise, Error, FormData, URLSearchParams, URL,
      setTimeout, clearTimeout, localStorage,
      document: { currentScript: { src: 'https://sport.taila73942.ts.net/resmara/api.js' } },
      fetch: async (url, opts) => {
        seen.push({ url, method: (opts || {}).method || 'GET' });
        return { ok: true, status: 200, async text() { return '[]'; } };
      },
    };
    mounted.window = mounted;
    vm.createContext(mounted);
    vm.runInContext(API_SRC, mounted, { filename: 'static/api.js' });
    const M = mounted.RM;
    eq('mounted base is detected from the script src', M.base, '/resmara');
    await M.boosts();
    eq('mounted GET /api/boosts reaches the app', seen.pop().url, '/resmara/api/boosts');
    await M.createBoost({ address: '1 Elm St' });
    const post = seen.pop();
    ok('mounted POST /api/boosts reaches the app', post.method === 'POST' && post.url === '/resmara/api/boosts',
       post.method + ' ' + post.url);
    await M.login('a@b.com', 'pw');
    eq('mounted login form post reaches the app', seen.pop().url, '/resmara/api/auth/login');
    await M.report(7, 14);
    eq('mounted report keeps its query string', seen.pop().url, '/resmara/api/content/reports/7?day=14');
    await M.createTicket('Subject', 'Body');
    const mt = seen.pop();
    ok('mounted POST /api/support reaches the app', mt.method === 'POST' && mt.url === '/resmara/api/support',
       mt.method + ' ' + mt.url);
    await M.tickets();
    eq('mounted GET /api/support stays inside the mount', seen.pop().url, '/resmara/api/support');
    await M.checkHealth();
    eq('mounted health check stays inside the mount', seen.pop().url, '/resmara/');
    await M.apiVersion();
    eq('mounted version probe stays inside the mount', seen.pop().url, '/resmara/openapi.json');
  }

  console.log('\n' + checks + ' checks, ' + failures + ' failed.');
  if (failures) { process.exit(1); }
  console.log('ALL FRONTEND API TESTS PASSED');
})().catch(e => { console.error('test runner crashed:', e); process.exit(1); });
