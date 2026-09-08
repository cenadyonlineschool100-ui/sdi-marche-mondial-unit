(function(){
  'use strict';

  function onIntersection(entries, observer){
    entries.forEach(function(entry){
      if(entry.isIntersecting){
        const el = entry.target;
        if(el.tagName.toLowerCase() === 'img'){
          const src = el.getAttribute('data-src');
          const srcset = el.getAttribute('data-srcset');
          if(srcset){ el.setAttribute('srcset', srcset); }
          if(src){ el.src = src; }
          el.classList.add('lazy-loaded');
          observer.unobserve(el);
        } else if(el.tagName.toLowerCase() === 'source'){
          const srcset = el.getAttribute('data-srcset');
          if(srcset){ el.setAttribute('srcset', srcset); }
          // source elements don't load by themselves; img will pick them up
          observer.unobserve(el);
        }
      }
    });
  }

  function initLazyLoad() {
    if(!('IntersectionObserver' in window)){
      // Fallback: just load all images
      document.querySelectorAll('img.lazy-img').forEach(function(img){
        const src = img.getAttribute('data-src');
        if(src) img.src = src;
        const source = img.closest('picture') && img.closest('picture').querySelector('source');
        if(source){
          const ssrc = source.getAttribute('data-srcset');
          if(ssrc) source.setAttribute('srcset', ssrc);
        }
      });
      return;
    }

    const observer = new IntersectionObserver(onIntersection, {rootMargin: '200px'});
    document.querySelectorAll('img.lazy-img').forEach(function(img){
      // Also observe <source> inside picture
      const source = img.closest('picture') && img.closest('picture').querySelector('source');
      if(source){ observer.observe(source); }
      observer.observe(img);
    });
  }

  // Expose init function
  window.lazyLoadImages = initLazyLoad;

  // Auto-init on DOMContentLoaded (defer in templates still recommended)
  document.addEventListener('DOMContentLoaded', function(){
    initLazyLoad();
  });
})();
