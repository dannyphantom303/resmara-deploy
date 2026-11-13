/* Resmara API client.
 *
 * One small, dependency-free ES2020 browser client for the Resmara backend.
 * Loaded before the UI scripts (see index.html); exposes window.RM.
 *
 * Rules this file lives by:
 *  - every path is written WITHOUT the mount prefix ("/api/boosts") and the prefix is
 *    detected at load time from where this file itself was served. Behind the Command
 *    Center router the app lives at /resmara, so a root-absolute "/api/boosts" resolves to
 *    the router's 404 long before it reaches this app: the request must go to
 *    "/resmara/api/boosts". Serving the app directly (127.0.0.1:8083) detects an empty
 *    prefix and the same call is right there too, so the deployment is never hard-coded;
 *  - the bearer token lives in localStorage and is sent only in the
 *    Authorization header - never in a URL or a query string;
 *  - a non-2xx response throws an Error carrying .status and the server's
 *    detail, so callers can tell a 401 from an offline failure;
 *  - nothing here touches the DOM or the app's state: it is transport only.
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'resmara_token';

  // ---- mount prefix -------------------------------------------------------

  /* Where this app is mounted, so that "/api/..." reaches IT and not the router.
   * Read from api.js's own <script src>, falling back to the page location. Both forms
   * are handled: the browser's absolute URL and a plain path. Returns "" (served at the
   * root) or "/resmara" - no trailing slash, no guessing.
   */
  function detectBase() {
    var raw = '';
    try {
      if (typeof document !== 'undefined') {
        if (document.currentScript && document.currentScript.src) {
          raw = document.currentScript.src;
        } else if (document.scripts) {
          for (var i = document.scripts.length - 1; i >= 0; i--) {
            var src = (document.scripts[i] && document.scripts[i].src) || '';
            if (/\/api\.js(\?|$)/.test(src)) { raw = src; break; }
          }
        }
      }
    } catch (e) { raw = ''; }
    var isScript = !!raw;
    if (!raw) {
      try { raw = (typeof location !== 'undefined' && location.pathname) || ''; } catch (e) { raw = ''; }
    }
    var pathname = raw;
    try { pathname = new URL(raw, 'http://x/').pathname; } catch (e) { /* keep raw */ }
    pathname = isScript
      ? pathname.replace(/\/[^/]*$/, '')                     // .../api.js -> the directory
      : pathname.replace(/\/[^/]*\.[A-Za-z0-9]+$/, '');       // a page file -> its directory
    return pathname.replace(/\/+$/, '');
  }

  var BASE = detectBase();

  // ---- session / token ----------------------------------------------------

  function token() {
    try { return localStorage.getItem(TOKEN_KEY) || null; } catch (e) { return null; }
  }

  function setToken(t) {
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* storage unavailable: stay logged out */ }
    return t || null;
  }

  function logout() {
    setToken(null);
    return true;
  }

  /* A token that is past its own exp is not a session.
   *
   * Checking only "is there a string in localStorage?" meant a browser could sit for hours
   * holding a dead token, still call itself signed in, and hand the customer the server's
   * "Could not validate credentials" as though they had typed something wrong. Reading exp
   * here turns that into an honest sign-in prompt the caller can act on.
   */
  function payload(t) {
    try {
      var part = String(t || '').split('.')[1];
      if (!part) return null;
      var b64 = part.replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) { b64 += '='; }
      return JSON.parse(atob(b64));
    } catch (e) { return null; }
  }

  function expired(t) {
    var p = payload(t || token());
    if (!p || !p.exp) return false;        // unreadable: let the server be the judge
    return p.exp * 1000 <= Date.now();
  }

  // One listener, so the UI can say "your session ended" in its own words and in its own place.
  var sessionLost = null;
  function onSessionLost(fn) { sessionLost = typeof fn === 'function' ? fn : null; }

  function endSession(notify) {
    var had = !!token();
    setToken(null);
    if (had && notify !== false) { try { if (sessionLost) sessionLost(); } catch (e) { /* a UI hook must never eat the error */ } }
    return true;
  }

  function isLoggedIn() {
    var t = token();
    if (!t) return false;
    // A token that has merely aged out is dropped quietly: the caller is about to say
    // "sign in" in its own words, and a toast on every page load is noise.
    if (expired(t)) { endSession(false); return false; }
    return true;
  }

  // The expiry this browser holds, so a screen can say when the session ends without guessing.
  function sessionExpiresAt() {
    var p = payload(token());
    return (p && p.exp) ? new Date(p.exp * 1000) : null;
  }

  // ---- low level ----------------------------------------------------------

  function authHeaders(extra) {
    var headers = Object.assign({}, extra || {});
    var t = token();
    if (t) headers['Authorization'] = 'Bearer ' + t;
    return headers;
  }

  async function parse(res) {
    var text = '';
    try { text = await res.text(); } catch (e) { text = ''; }
    var body = null;
    if (text) {
      try { body = JSON.parse(text); } catch (e) { body = text; }
    }
    if (!res.ok) {
      var detail;
      if (body && typeof body === 'object' && body.detail !== undefined) {
        detail = body.detail;                       // FastAPI's shaped error
      } else if (typeof body === 'string' && body && body.length <= 300 && body.indexOf('<') === -1) {
        detail = body;                              // a plain-text message
      } else {
        detail = 'HTTP ' + res.status;              // HTML/empty body: never dump markup at the user
      }
      var message = typeof detail === 'string' ? detail : JSON.stringify(detail);
      var err = new Error(message);
      err.status = res.status;
      err.detail = detail;
      err.body = body;
      throw err;
    }
    return body;
  }

  // opts: {method, headers, body}. Content-Type is set by the caller so that
  // multipart uploads let the browser choose the boundary.
  // The app's own page root, prefix included, so the health probe of a mounted deployment
  // asks the app for the app and not the router for '/'.
  function home() {
    return BASE + '/';
  }

  function request(path, opts) {
    opts = opts || {};
    var sentSession = !!token();
    return fetch(BASE + path, {
      method: opts.method || 'GET',
      headers: authHeaders(opts.headers),
      body: opts.body,
    }).then(parse).catch(function (err) {
      // A 401 on the login call is "wrong password", not "your session ended" - the two
      // must never be confused, because only one of them is the customer's to fix.
      if (err && err.status === 401 && sentSession && path !== '/api/auth/login') {
        // The server no longer accepts the token this browser holds. Drop it and say what
        // actually happened, instead of passing "Could not validate credentials" on as if
        // the customer had done something wrong.
        endSession();
        err.message = 'Your session ended — sign in again.';
      }
      throw err;
    });
  }

  function json(path, method, payload) {
    return request(path, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  function segment(value) {
    return encodeURIComponent(value);
  }

  // ---- auth ---------------------------------------------------------------

  async function login(email, password) {
    var form = new URLSearchParams();
    form.set('username', email);
    form.set('password', password);
    var body = await request('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    });
    if (body && body.access_token) setToken(body.access_token);
    return body;
  }

  function register(email, password, name, inviteCode) {
    // invite_code is only sent when there is one: the open-signup path keeps the exact body
    // it always had, and the beta gate treats a missing code the same as an empty one.
    var body = { email: email, password: password, name: name };
    if (inviteCode) body.invite_code = inviteCode;
    return json('/api/auth/register', 'POST', body);
  }

  function me() {
    return request('/api/auth/me');
  }

  // ---- boosts (campaigns) -------------------------------------------------

  function boosts() {
    return request('/api/boosts');
  }

  function boost(id) {
    return request('/api/boosts/' + segment(id));
  }

  // Hiding and deleting are the two ways a customer clears their list. Hiding is reversible and
  // keeps the campaign and its report; deleting removes Resmara's copy of the campaign.
  function hideBoost(id, hidden) {
    return request('/api/boosts/' + segment(id) + '/hide?hidden=' + (hidden === false ? 'false' : 'true'),
      { method: 'POST' });
  }

  function deleteBoost(id) {
    return request('/api/boosts/' + segment(id), { method: 'DELETE' });
  }

  function createBoost(data) {
    data = data || {};
    return json('/api/boosts', 'POST', {
      address: data.address,
      go_live_date: data.go_live_date,
      campaign_days: data.campaign_days,
      ad_budget_usd: data.ad_budget_usd,
      property_facts: data.property_facts,
      ad_account_id: data.ad_account_id,
    });
  }

  // ---- content: uploads, assets, photo index ------------------------------

  function uploadPhoto(file, boostId, kind) {
    var form = new FormData();
    form.append('file', file);
    if (boostId !== undefined && boostId !== null) form.append('boost_id', String(boostId));
    form.append('kind', kind || 'photo');
    // No Content-Type: the browser adds the multipart boundary itself.
    return request('/api/content/upload/photo', { method: 'POST', body: form });
  }

  function assets(boostId) {
    return request('/api/content/assets/' + segment(boostId));
  }

  function photoIndex(boostId) {
    return request('/api/content/photo-index/' + segment(boostId));
  }

  // The gallery in the order the engine uses it (strongest-selling photo first), with the space
  // each photo shows — the photos panel reads this instead of raw upload order.
  function gallery(boostId) {
    return request('/api/content/gallery/' + segment(boostId));
  }

  // Pull a listing's gallery (or direct image URLs) into the campaign.
  function importPhotos(boostId, opts) {
    opts = opts || {};
    return json('/api/content/import/photos', 'POST', {
      boost_id: boostId,
      listing_url: opts.listingUrl || null,
      urls: opts.urls || [],
      limit: opts.limit || 20,
    });
  }

  function tagAssets(boostId) {
    return request('/api/content/assets/' + segment(boostId) + '/tag', { method: 'POST' });
  }

  // ---- content generation -------------------------------------------------

  var GENERATE_FIELDS = [
    'boost_id', 'agent_name', 'phone', 'license_no', 'brokerage', 'instagram',
    'website', 'property_website', 'beds', 'baths', 'sqft', 'city', 'feature',
    'cta', 'notes', 'force',
  ];

  function generateContent(fields) {
    fields = fields || {};
    var form = new FormData();
    GENERATE_FIELDS.forEach(function (key) {
      var value = fields[key];
      if (value === undefined || value === null || value === '') return;
      form.append(key, String(value));
    });
    return request('/api/content/generate/content', { method: 'POST', body: form });
  }

  // ---- engine: build / plan / posts / approval ----------------------------

  function buildCampaign(boostId, opts) {
    opts = opts || {};
    return json('/api/boosts/' + segment(boostId) + '/build', 'POST', { force: !!opts.force });
  }

  function buildStatus(boostId) {
    return request('/api/boosts/' + segment(boostId) + '/build-status');
  }

  function plan(boostId) {
    return request('/api/boosts/' + segment(boostId) + '/plan');
  }

  function posts(boostId) {
    return request('/api/boosts/' + segment(boostId) + '/posts');
  }

  function approvePost(postId) {
    return request('/api/posts/' + segment(postId) + '/approve', { method: 'PATCH' });
  }

  function approveAll(boostId) {
    return request('/api/boosts/' + segment(boostId) + '/approve', { method: 'POST' });
  }

  // ---- billing ------------------------------------------------------------
  // One campaign costs $49 and is bought outright: there is no credit balance to check, so
  // the old /adflow/credits/precheck/ call is gone with the credit system.

  function billingConfig() {
    return request('/api/billing/config');
  }

  function savedCards() {
    // The cards Stripe already holds for this account, masked. Read-only.
    return request('/api/billing/cards');
  }

  function checkout(boostId) {
    return json('/api/billing/checkout', 'POST', { boost_id: boostId });
  }

  function orders() {
    return request('/api/billing/orders');
  }

  function boostBilling(boostId) {
    return request('/api/billing/boost/' + segment(boostId));
  }

  function launch(boostId, opts) {
    opts = opts || {};
    return json('/api/launch', 'POST', {
      platform: 'meta',
      boost_id: boostId,
      auto_approve: !!opts.auto_approve,
      meta_custom_configs: opts.meta_custom_configs || {},
    });
  }

  // ---- publishing ---------------------------------------------------------

  function publishStatus(boostId) {
    return request('/api/content/publish/status/' + segment(boostId));
  }

  function publishNow(boostId) {
    return request('/api/content/publish/boost/' + segment(boostId), { method: 'POST' });
  }

  // ---- Meta connection ----------------------------------------------------
  // Consent happens on Facebook, so metaConnect() only hands back the URL to visit;
  // the app never sees the token — Meta redirects to /api/oauth/meta/callback.

  function metaConnect() {
    return request('/api/oauth/meta/connect');
  }

  // The customer's brand profile, kept on the account so it is not lost with a browser.
  function brandProfile() {
    return request('/api/auth/me/brand').then(function (r) { return (r && r.brand) || {}; });
  }

  function saveBrandProfile(brand) {
    return request('/api/auth/me/brand', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brand: brand || {} }),
    }).then(function (r) { return (r && r.brand) || {}; });
  }

  function adAccounts() {
    return request('/api/ad-accounts');
  }

  /* Re-check every connected ad account against Meta right now.
   * This is a POST with no body: it makes the app go and ask Meta, and it can refresh a
   * token that is close to expiring, so it must never be cached or done on page load. */
  function checkConnections() {
    return request('/api/ad-accounts/check-all', { method: 'POST' });
  }

  // ---- reports ------------------------------------------------------------

  function report(boostId, day) {
    var d = (day === undefined || day === null) ? 7 : day;
    return request('/api/content/reports/' + segment(boostId) + '?day=' + segment(d));
  }

  // ---- support ------------------------------------------------------------

  // The client's own support desk: raising a request and reading the replies are the
  // same two calls the Support page and the "Ask Resmara" assistant both use, so a
  // question asked in the chat lands in the operator console as a real ticket.
  async function createTicket(subject, message) {
    return request('/api/support', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: String(subject || '').slice(0, 200), message: String(message || '') }),
    });
  }

  async function tickets() {
    return request('/api/support');
  }

  // ---- health / version ---------------------------------------------------

  async function checkHealth() {
    var res = await fetch(home(), { method: 'GET', headers: authHeaders() });
    if (!res.ok) {
      var err = new Error('UI returned HTTP ' + res.status);
      err.status = res.status;
      throw err;
    }
    return { ok: true, status: res.status };
  }

  async function apiVersion() {
    // The app's own OpenAPI document carries its version and always exists; there is no
    // /api/status endpoint, so asking for one only ever produced a 404 to swallow.
    var res = await fetch(BASE + '/openapi.json', { method: 'GET', headers: authHeaders() });
    if (res.status === 404) return null; // deployment without docs - skip, not an error
    return parse(res);
  }

  // ---- export -------------------------------------------------------------

  window.RM = {
    base: BASE,           // the detected mount prefix ('' or '/resmara'); read-only

    token: token,
    setToken: setToken,
    logout: logout,
    isLoggedIn: isLoggedIn,
    sessionExpiresAt: sessionExpiresAt,
    onSessionLost: onSessionLost,
    login: login,
    register: register,
    me: me,
    boosts: boosts,
    boost: boost,
    hideBoost: hideBoost,
    deleteBoost: deleteBoost,
    createBoost: createBoost,
    uploadPhoto: uploadPhoto,
    assets: assets,
    buildCampaign: buildCampaign,
    buildStatus: buildStatus,
    plan: plan,
    posts: posts,
    approvePost: approvePost,
    approveAll: approveAll,
    generateContent: generateContent,
    billingConfig: billingConfig,
    savedCards: savedCards,
    checkout: checkout,
    orders: orders,
    boostBilling: boostBilling,
    launch: launch,
    publishStatus: publishStatus,
    publishNow: publishNow,
    report: report,
    photoIndex: photoIndex,
    gallery: gallery,
    importPhotos: importPhotos,
    tagAssets: tagAssets,
    createTicket: createTicket,
    tickets: tickets,
    metaConnect: metaConnect,
    brandProfile: brandProfile,
    saveBrandProfile: saveBrandProfile,
    adAccounts: adAccounts,
    checkConnections: checkConnections,
    checkHealth: checkHealth,
    apiVersion: apiVersion,
  };
})();
