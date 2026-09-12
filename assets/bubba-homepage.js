(function(){if(window.location.pathname!=='/') return;
var ps=document.querySelectorAll('.section-rich-text p, .rich-text__text p');
ps.forEach(function(p){
var t=p.innerHTML;
if(t.indexOf('💳')!==-1){
p.innerHTML=t.replace(/💳\s*/g,'').replace(/(<strong>Acima)/,'<br/>$1').replace(/(<strong>Koalifi)/,'<br/>$1').replace(/(<strong>Synchrony)/,'<br/>$1');
}
});
var banners=document.querySelectorAll('.banner__heading, .image-banner h1, .image-banner h2, .image-banner .banner__heading');
var map={'Comfort Every Day':'Living Room','Dining Done Right':'Dining Room','Nightly Comfort':'Bedroom','Rest Made Simple':'Mattresses'};
banners.forEach(function(h){
var txt=h.textContent.trim();
if(map[txt]) h.textContent=map[txt];
});
})();
