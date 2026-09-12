/*
 * Keep the Acima lease estimate in step with the selected variant.
 *
 * The product template passes initItemPrice to AcimaCalculator.init() once,
 * from Liquid, at page render. Nothing told Acima the price had changed, so on
 * a multi-variant item (sectional configurations, mattress sizes) the estimate
 * kept quoting the FIRST variant's price after the shopper picked another one.
 * On a lease-to-own quote that is a wrong number, not a cosmetic bug.
 *
 * Strategy: watch the real price element, and on change prefer an official
 * update method if the Acima library exposes one; otherwise rebuild the widget
 * from a clean button so repeated inits cannot stack duplicate buttons.
 */
(function () {
  var LOCATION = 'loca-7994c60f-5bc9-4c77-a304-41a998197eaa';
  var BTN_HTML =
    '<button style="border:0" type="button" aria-label="Estimate Leasing Costs" class="open-acima-calculator"></button>';

  var info = document.querySelector('.product__info-container');
  var wrap = document.querySelector('.acima-wrap');
  if (!info || !wrap) return;

  /* Dawn renders the struck-through regular price BEFORE the sale price, so
     read the sale node when the product is actually on sale. */
  function currentPrice() {
    var pb = info.querySelector('.price');
    if (!pb) return null;
    var node = pb.classList.contains('price--on-sale')
      ? pb.querySelector('.price-item--sale')
      : pb.querySelector('.price-item--regular');
    if (!node) node = pb.querySelector('.price-item--sale, .price-item--regular');
    if (!node) return null;
    var val = parseFloat(node.textContent.replace(/[^0-9.]/g, ''));
    return isFinite(val) && val > 0 ? val : null;
  }

  function ready() {
    return typeof window.AcimaCalculator !== 'undefined' && window.AcimaCalculator;
  }

  function apply(price) {
    if (!ready()) return;
    var A = window.AcimaCalculator;

    // Use a documented update call if this version of the library has one.
    var names = ['updatePrice', 'setPrice', 'updateItemPrice', 'update'];
    for (var i = 0; i < names.length; i++) {
      if (typeof A[names[i]] === 'function') {
        try {
          A[names[i]](price);
          return;
        } catch (e) {
          /* fall through to rebuild */
        }
      }
    }

    // Fallback: tear down and rebuild from a fresh button.
    try {
      if (typeof A.destroy === 'function') A.destroy();
    } catch (e) {}
    wrap.innerHTML = BTN_HTML;
    try {
      A.init({
        location: LOCATION,
        env: 'production',
        initItemPrice: price,
        useDynamicCta: true,
        Language: 'en'
      });
    } catch (e) {}
  }

  var last = currentPrice();
  var busy = false;

  function sync() {
    if (busy) return;
    var p = currentPrice();
    if (p === null || p === last) return;
    last = p;
    busy = true;
    try {
      apply(p);
    } finally {
      // apply() writes inside .acima-wrap, which sits inside the observed
      // container. Release on the next tick so that write cannot re-enter.
      setTimeout(function () {
        busy = false;
      }, 0);
    }
  }

  new MutationObserver(sync).observe(info, {
    subtree: true,
    childList: true,
    characterData: true
  });

  // Acima's library loads from their CDN; don't assume it is ready yet.
  if (!ready()) {
    var tries = 0;
    var t = setInterval(function () {
      if (ready() || ++tries > 40) {
        clearInterval(t);
        if (ready()) sync();
      }
    }, 250);
  }
})();