/* Billing UI: one campaign, $49, bought outright.
 *
 * Replaces the credit system. A "credit" was an invented balance nobody could buy, so the
 * dashboard could advertise a number that never became a campaign. There is now exactly one
 * product — a property campaign for $49 — and Stripe Checkout takes the card.
 *
 * Loaded LAST (after homepage.js and app.js), so these same-named function declarations win
 * over the retired credit versions instead of every screen being rewritten in place.
 */
'use strict';

var BILLING_PRICE_CENTS = 4900;

function billingMoney(cents) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
    .format((Number(cents) || 0) / 100);
}

// ---- what the old credit globals now mean ---------------------------------

function creditBalance() { return 0; }               // nobody holds a balance any more
function useCampaignCredit() { return true; }         // nothing to consume: the campaign is paid for
function creditQuote(quantity) {
  return Number(quantity) === 1
    ? { count: 1, unit: BILLING_PRICE_CENTS, total: BILLING_PRICE_CENTS, savings: 0 }
    : null;                                          // there are no packs to quote
}

function creditCalculator(fromPricePage) {
  return `<div class="notice"><b>${billingMoney(BILLING_PRICE_CENTS)} per campaign</b>
    <p class="fine" style="margin:6px 0 0">One 14-day listing campaign: branded posts, digital ad
    creative, and Day 7 and Day 14 reports. No subscription and no expiry — you pay when you build
    a campaign. Meta ad spend is separate and paid to Meta.</p></div>`;
}

// ---- the paywall ----------------------------------------------------------

/* Ask for a Stripe Checkout URL and send the browser there. Returns the URL so callers can
 * open it themselves if the navigation is blocked. */
async function startCampaignCheckout(boostId) {
  if (boostId == null) { toast('Save the campaign first — there is nothing to charge for yet.'); return null; }
  try {
    var cfg = await RM.billingConfig();
    if (!cfg.enabled) {
      toast('Card payments are not switched on yet.');
      return null;
    }
    var res = await RM.checkout(boostId);
    if (res && res.status === 'already_paid') { toast('That campaign is already paid for.'); return null; }
    if (res && res.url) { window.location.href = res.url; return res.url; }
    toast('Stripe did not return a checkout page.');
  } catch (err) {
    toast((err && err.message) || 'Could not start the checkout.');
  }
  return null;
}

/* The screen a locked campaign shows: what it costs, why it is locked, one button. */
function showPaywall(boostId, detail) {
  var price = (detail && detail.price_cents) ? billingMoney(detail.price_cents)
    : billingMoney(BILLING_PRICE_CENTS);
  show(`<span class="eyebrow">CAMPAIGN CHECKOUT</span>
    <h2>This campaign is ${esc(price)}</h2>
    <p>${esc((detail && detail.message) || 'Buy the campaign to build its 14 days of posts.')}</p>
    <p class="fine">Card details go to Stripe — Resmara never stores them. Stripe will offer the card
    you used last time, so this is the last time you type it. Meta ad spend is separate.</p>
    <div class="modal-actions">
      <button class="alt" onclick="modal.close()">Not now</button>
      <button class="campaign-primary" onclick="startCampaignCheckout(${Number(boostId)})">Pay ${esc(price)} and build →</button>
    </div>`);
}

// Kept for anything still wired to the old demo button: it now starts a real checkout.
function completeDemoCreditOrder(button, quantity, resume) {
  if (button && button.disabled) return;
  var boostId = (typeof reviewCampaignBoostId === 'function' && reviewCampaignBoostId()) || null;
  if (boostId != null) { startCampaignCheckout(boostId); return; }
  toast('Open the campaign first, then pay for it.');
}

// ---- screens --------------------------------------------------------------

function pricing() {
  if (typeof stopResmaraGuide === 'function') stopResmaraGuide();
  location.hash = 'pricing';
  document.title = 'Pricing — Resmara';
  app.innerHTML = `<div class="marketing-home">${siteNav('pricing')}<main>
    <section class="home-section package-page"><div>
      <span class="home-kicker">ONE PRICE PER LISTING</span>
      <h1>${billingMoney(BILLING_PRICE_CENTS)} for<br><span>one campaign.</span></h1>
      <p>Fourteen days of branded posts for Facebook and Instagram, digital ad creative, and
      Day 7 and Day 14 seller reports — for one property.</p>
      <p>No subscription, and nothing that expires. You pay when you build the
      campaign. Meta ad spend is paid separately, straight to Meta.</p>
      <button class="campaign-primary" onclick="newCampaign()">Start a campaign · ${billingMoney(BILLING_PRICE_CENTS)}</button>
    </div>${creditCalculator(true)}</section>
  </main></div>`;
}

async function myCredits() {
  // Same route the sidebar has always used ('credits'); the page is now Billing.
  // The shell paints first: an await before innerHTML leaves the previous screen on the page
  // when the network is slow, which on a free instance is most of the time.
  $('#content').innerHTML = `<div class="welcome"><h1>Billing</h1>
      <p>One property campaign costs ${billingMoney(BILLING_PRICE_CENTS)}, paid when you build it.
      No subscription and nothing to top up.</p></div>
    <section class="panel"><h2>Purchases</h2>
      <div id="billing-orders"><p class="fine">Loading your purchases…</p></div></section>
    <section class="panel"><h2>Payment method</h2>
      <div id="billing-cards"><p class="fine">Checking your saved card…</p></div></section>
    <section class="panel"><h2>How it works</h2>
      <p>You pay ${billingMoney(BILLING_PRICE_CENTS)} when you build a campaign. Card details go to
      Stripe; Resmara never stores them. Meta ad spend is separate and paid to Meta from your own
      ad account.</p></section>`;

  // Saved card: Stripe keeps it on your customer record, so the next campaign is one click.
  var cardBox = document.getElementById('billing-cards');
  if (cardBox && RM.savedCards) {
    RM.savedCards().then(function (res) {
      var cards = (res && res.cards) || [];
      cardBox.innerHTML = cards.length
        ? '<ul class="campaign-report-list">' + cards.map(function (c) {
            return '<li><strong>' + esc(c.label) + '</strong><span class="fine">Stored by Stripe — ' +
              'checkout will offer it, no number to retype.</span></li>';
          }).join('') + '</ul><p class="fine">Your card number never reaches Resmara.</p>'
        : '<p class="fine">' + esc((res && res.note) || 'No card saved yet.') +
          ' Your first campaign saves it for next time.</p>';
    }).catch(function () {
      cardBox.innerHTML = '<p class="fine">Could not read your saved card right now.</p>';
    });
  }

  var box = document.getElementById('billing-orders');
  if (!box) return;
  var rows = [];
  try { rows = (await RM.orders()) || []; } catch (err) {
    box.innerHTML = '<p class="fine">Could not load your purchases. Check your connection and reload.</p>';
    return;
  }
  var date = function (v) {
    return v ? new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
  };
  box.innerHTML = rows.length
    ? `<ul class="campaign-report-list">${rows.map(function (o) {
        var what = o.address || (o.boost_id ? 'Campaign #' + o.boost_id : 'Campaign');
        return `<li><strong>${esc(what)}</strong>
          <span class="fine">${esc(o.amount_label || billingMoney(o.amount_cents))} · ${esc(o.status)} · ${date(o.paid_at || o.created_at)}</span></li>`;
      }).join('')}</ul>`
    : '<p class="fine">No purchases yet. A campaign is charged when you build it.</p>';
}

// ---- returning from Stripe ------------------------------------------------

(function handleCheckoutReturn() {
  if (typeof location === 'undefined') return;
  var params = new URLSearchParams(location.search || '');
  var state_ = params.get('checkout');
  if (!state_) return;
  var boostId = Number(params.get('boost')) || null;
  // Clean the query so a refresh does not re-announce an old payment.
  var clean = location.pathname + (location.hash || '');
  window.history.replaceState({}, document.title, clean);
  if (state_ === 'success') {
    toast('Payment received — your campaign is unlocked.');
    if (typeof dashboard === 'function') setTimeout(function () { dashboard('campaigns'); }, 400);
    if (boostId && window.RM && RM.boostBilling) {
      RM.boostBilling(boostId).then(function (b) {
        if (!b || !b.paid) toast('Stripe has not confirmed the payment yet — refresh in a moment.');
      }).catch(function () {});
    }
  } else if (state_ === 'cancelled') {
    toast('Checkout cancelled — nothing was charged.');
  }
})();
