#!/usr/bin/env node
'use strict';
/*
 * Deployed-UI test: the real static/api.js, over the real public URL.
 *
 * The other front-end test stubs fetch, so it can only prove the paths api.js WOULD ask
 * for. This one runs api.js unchanged in a vm sandbox whose fetch hits
 * https://sport.taila73942.ts.net for real, with document.currentScript pointing at
 * /resmara/api.js exactly as the browser sees it. That exercises the whole chain a user
 * touches: mount-prefix detection -> Command Center router -> Resmara app -> auth -> JSON.
 *
 * The router gates every project path behind the Command Center session cookie, so the
 * test mints that cookie locally with the very library the router verifies against
 * (/Users/dan/Scripts/lib/cc-session.js) - the same credential a real browser holds after
 * logging in at /cc/. Nothing secret is printed.
 *
 * Run:  node tests/test_deployed_ui.js          (needs the router + app running)
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');

const ORIGIN = 'https://sport.taila73942.ts.net';
const API_SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'api.js'), 'utf8');

let checks = 0, failures = 0;
function ok(name, cond, extra) {
  checks++;
  if (cond) console.log('  PASS  ' + name);
  else { failures++; console.log('  FAIL  ' + name + (extra ? '  (' + extra + ')' : '')); }
}

// The router's own session library: same secret, same signature, same cookie name.
let ccSession = null;
try { ccSession = require('/Users/dan/Scripts/lib/cc-session.js'); } catch (e) { ccSession = null; }

(async () => {
  if (!ccSession) { console.log('  FAIL  /Users/dan/Scripts/lib/cc-session.js is not available'); process.exit(1); }

  // 1. the session cookie a browser would hold after logging in at /cc/
  const cookie = ccSession.setCookie().split(';')[0];
  const gated = await fetch(ORIGIN + '/resmara/api/auth/me', { redirect: 'manual' });
  ok('the deployment really is gated without that cookie', gated.status === 302, 'HTTP ' + gated.status);

  // 2. run api.js exactly as the browser does, with real network underneath
  const seen = [];
  const sandbox = {
    console, JSON, Object, Array, Promise, Error, URLSearchParams, URL, FormData,
    setTimeout, clearTimeout,
    localStorage: { _m: new Map(), getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
                    setItem(k, v) { this._m.set(k, String(v)); }, removeItem(k) { this._m.delete(k); } },
    document: { currentScript: { src: ORIGIN + '/resmara/api.js' } },
    location: { pathname: '/resmara/', origin: ORIGIN },
    fetch: async (url, opts) => {
      opts = opts || {};
      const abs = new URL(url, ORIGIN).href;
      seen.push({ url, abs, method: opts.method || 'GET' });
      const headers = Object.assign({}, opts.headers || {});
      if (cookie) headers['Cookie'] = cookie;
      return fetch(abs, { method: opts.method || 'GET', headers, body: opts.body, redirect: 'manual' });
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(API_SRC, sandbox, { filename: 'static/api.js' });
  const RM = sandbox.RM;

  ok('api.js detected the /resmara mount', RM.base === '/resmara', 'base=' + JSON.stringify(RM.base));

  // 3. the wire the UI actually uses, against the live deployment
  const email = 'deployed-ui-' + Date.now() + '@example.com';
  const password = 'deployed-ui-pass-12345';
  let reg = null, regErr = null;
  try { reg = await RM.register(email, password, 'Deployed UI Check'); } catch (e) { regErr = e; }
  ok('the mounted register call reaches the app', !!reg, regErr ? regErr.message : '');
  ok('  ...and asked /resmara/api/auth/register', seen.some(s => s.url === '/resmara/api/auth/register'),
     JSON.stringify(seen.slice(-1)));

  const me0 = await RM.me().then(v => v, e => e);
  ok('a call before login answers 401 (reached the app, not the router)',
     me0 instanceof Error && me0.status === 401, me0 instanceof Error ? 'status=' + me0.status : 'no error');

  const login = await RM.login(email, password);
  ok('the mounted login sets a token', !!(login && login.access_token));
  const me = await RM.me();
  ok('the mounted /api/auth/me returns the signed-in account', me && me.email === email, JSON.stringify(me));

  const created = await RM.createBoost({ address: '1 Deployed UI Way, Austin TX', campaign_days: 14 });
  ok('the mounted boost create returns a row', !!(created && created.id), 'id=' + (created && created.id));
  const list = await RM.boosts();
  ok('the mounted boost list comes back as JSON',
     Array.isArray(list) && list.some(b => b.id === (created && created.id)),
     'type=' + (Array.isArray(list) ? 'array[' + list.length + ']' : typeof list));

  // 4. the support desk and the operator cards, over the same public URL
  const ticket = await RM.createTicket('Deployed UI question', 'Does the support desk work through the mount?');
  ok('the mounted support request reaches the app',
     !!(ticket && ticket.id && ticket.subject === 'Deployed UI question'), JSON.stringify(ticket));
  ok('  ...and asked /resmara/api/support',
     seen.some(s => s.url === '/resmara/api/support' && s.method === 'POST'), JSON.stringify(seen.slice(-1)));
  const mine = await RM.tickets();
  ok('the mounted support list returns the new request as JSON',
     Array.isArray(mine) && mine.some(t => t.id === (ticket && ticket.id)),
     'type=' + (Array.isArray(mine) ? 'array[' + mine.length + ']' : typeof mine));

  // The console is a static page in the same mount; fetch it through the router so a
  // broken mount or a missing file fails here rather than in front of the operator.
  const admin = await fetch(ORIGIN + '/resmara/admin.html', { headers: { Cookie: cookie }, redirect: 'manual' });
  const adminHtml = await admin.text();
  ok('the operator console is served through the mount', admin.status === 200 && adminHtml.includes('id="metricsBody"'),
     'HTTP ' + admin.status);
  ok('  ...and it reads the two non-overlapping endpoints',
     adminHtml.includes('/api/admin/health') && adminHtml.includes('/api/admin/metrics'), 'cards wired');

  ok('every request went to /resmara/* (never to the router root)',
     seen.every(s => s.url.startsWith('/resmara/')), JSON.stringify(seen.filter(s => !s.url.startsWith('/resmara/'))));

  console.log('\n  api.js base ' + RM.base + ' | ' + seen.length + ' real requests to ' + ORIGIN);
  console.log('\n' + checks + ' checks, ' + failures + ' failed.');
  if (failures) process.exit(1);
  console.log('DEPLOYED UI TEST PASSED');
})().catch(e => { console.error('test runner crashed:', e); process.exit(1); });
