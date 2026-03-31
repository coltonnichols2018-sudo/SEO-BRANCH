function hideProductModal() {
  const productModal = document.querySelectorAll('product-modal[open]');
  productModal && productModal.forEach((modal) => modal.hide());
}

document.addEventListener('shopify:block:select', function (event) {
  hideProductModal();
  const blockSelectedIsSlide = event.target.classList.contains('slideshow__slide');
  if (!blockSelectedIsSlide) return;

  const parentSlideshowComponent = event.target.closest('slideshow-component');
  parentSlideshowComponent.pause();

  setTimeout(function () {
    parentSlideshowComponent.slider.scrollTo({
      left: event.target.offsetLeft,
    });
  }, 200);
});

document.addEventListener('shopify:block:deselect', function (event) {
  const blockDeselectedIsSlide = event.target.classList.contains('slideshow__slide');
  if (!blockDeselectedIsSlide) return;
  const parentSlideshowComponent = event.target.closest('slideshow-component');
  if (parentSlideshowComponent.autoplayButtonIsSetToPlay) parentSlideshowComponent.play();
});

document.addEventListener('shopify:section:load', () => {
  hideProductModal();
  const zoomOnHoverScript = document.querySelector('[id^=EnableZoomOnHover]');
  if (!zoomOnHoverScript) return;
  if (zoomOnHoverScript) {
    const newScriptTag = document.createElement('script');
    newScriptTag.src = zoomOnHoverScript.src;
    zoomOnHoverScript.parentNode.replaceChild(newScriptTag, zoomOnHoverScript);
  }
});

document.addEventListener('shopify:section:unload', (event) => {
  document.querySelectorAll(`[data-section="${event.detail.sectionId}"]`).forEach((element) => {
    element.remove();
    document.body.classList.remove('overflow-hidden');
  });
});

document.addEventListener('shopify:section:reorder', () => hideProductModal());

document.addEventListener('shopify:section:select', () => hideProductModal());

document.addEventListener('shopify:section:deselect', () => hideProductModal());

document.addEventListener('shopify:inspector:activate', () => hideProductModal());

document.addEventListener('shopify:inspector:deactivate', () => hideProductModal());

// Sticky Add-to-Cart Bar
document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('product-form');
  if (form) {
    const addButton = form.querySelector('[name="add"]');
    if (addButton) {
      const stickyBar = addButton.cloneNode(true);
      stickyBar.type = 'submit';
      stickyBar.style.cssText = 'position:fixed; bottom:0; left:0; width:100%; background:#990000; color:white; padding:20px; text-align:center; font-size:18px; font-weight:bold; z-index:999; box-shadow:0 -5px 20px rgba(0,0,0,0.2); border:none;';
      stickyBar.innerText = 'Add to Cart – $' + '{{ product.price | money_without_currency }} – Tap Here';
      document.body.appendChild(stickyBar);
      window.addEventListener('scroll', () => {
        stickyBar.style.display = (window.scrollY > 600) ? 'block' : 'none';
      });
    }
  }
});

// Floating Text Us button on mobile
if (window.innerWidth < 768) {
  const btn = document.createElement('a');
  btn.href = 'sms:5024940376?&body=Hey Bubba’s! I’m looking at the ' + document.title.split(' – ')[0] + ' on your site';
  btn.innerHTML = '💬 Text Us';
  btn.style.cssText = 'position:fixed; bottom:20px; right:20px; background:#990000; color:white; padding:16px 22px; border-radius:50px; font-weight:bold; box-shadow:0 4px 20px rgba(0,0,0,0.4); z-index:9999; font-size:16px;';
  document.body.appendChild(btn);
}