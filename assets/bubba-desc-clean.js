/* Bubba's: split Wondersign description into Overview paragraph + Dimensions table */
(function(){
  var ov=document.getElementById('tab-overview'), dim=document.getElementById('tab-dimensions');
  if(!ov) return;
  var html=ov.innerHTML;
  var firstB=html.search(/<b>|<strong>/i);
  if(firstB<0) return;
  var intro=html.slice(0,firstB), rest=html.slice(firstB);
  var rows=[];
  rest.split(/<(?:b|strong)>/i).forEach(function(chunk){
    var i=chunk.search(/<\/(?:b|strong)>/i); if(i<0) return;
    var name=chunk.slice(0,i).replace(/<[^>]+>/g,'').trim();
    var spec=chunk.slice(i).replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
    if(!name||!/\d+(?:\.\d+)?\s*in\b/i.test(spec)) return;
    rows.push({name:name,spec:spec});
  });
  if(rows.length<2) return;
  var pTitle=(document.querySelector('.bb-ptitle')||{}).textContent||'';
  function clean(n){
    var parts=n.split(' - ');
    if(parts.length>=3) return parts.slice(1,-1).join(' ');
    if(parts.length==2) return parts[1];
    return n;
  }
  function dims(s){
    var L=(s.match(/([\d.]+)\s*in\s*L/i)||[])[1], W=(s.match(/([\d.]+)\s*in\s*W/i)||[])[1], H=(s.match(/([\d.]+)\s*in\s*H/i)||[])[1], wt=(s.match(/([\d.]+)\s*lb/i)||[])[1];
    var f=function(x){return x?Math.round(parseFloat(x))+'"':'—';};
    return [f(L),f(W),f(H),wt?Math.round(parseFloat(wt))+' lb':'—'];
  }
  // current configuration from variant picker
  var sels=[].slice.call(document.querySelectorAll('.product-form__input--dropdown select, variant-selects select'));
  var sel=sels.filter(function(s){return /pc|piece|sectional|sofa|chaise/i.test(s.value)})[0]||sels[sels.length-1];
  function norm(s){s=(s||'').toLowerCase();s=s.replace(/\b(\d+)\s*(?:pc\.?|piece)\b/g,'$1pc').replace(/left arm facing/g,'laf').replace(/right arm facing/g,'raf').replace(/[^a-z0-9 ]/g,' ').replace(/\s+/g,' ').trim();return s;}
  function score(a,b){a=norm(a);b=norm(b);var pa=(a.match(/(\d+)pc/)||[])[1],pb=(b.match(/(\d+)pc/)||[])[1];if(pa&&pb&&pa!==pb)return -1;var s=pa&&pb?2:0;['laf','raf','double','armless','sofa','chaise','corner','wedge','cuddler','console','power','recliner','chair'].forEach(function(k){var ia=a.indexOf(k)>-1,ib=b.indexOf(k)>-1;if(ia&&ib)s+=1;else if(ia!==ib)s-=0.5;});return s;}
  function bestIdx(v,list){var bi=-1,bs=0.5;list.forEach(function(n,i){var sc=score(v,n);if(sc>bs){bs=sc;bi=i;}});return bi;}
  var cur=sel?sel.value:'';
  var head='<table class="bb-dims"><thead><tr><th>Configuration</th><th>Length</th><th>Width</th><th>Height</th><th>Weight</th></tr></thead><tbody>';
  var names=rows.map(function(r){return clean(r.name)});
  var ci=cur?bestIdx(cur,names):-1;
  var curRows='',otherRows='';
  rows.forEach(function(r,i){
    var d=dims(r.spec), c=names[i];
    var tr='<tr data-i="'+i+'"'+(i===ci?' class="bb-dims__cur"':'')+'><td>'+c+'</td><td>'+d[0]+'</td><td>'+d[1]+'</td><td>'+d[2]+'</td><td>'+d[3]+'</td></tr>';
    if(i===ci) curRows+=tr; else otherRows+=tr;
  });
  var out='';
  if(curRows){ out+='<p class="bb-dims__label">Selected configuration</p>'+head+curRows+'</tbody></table>'; }
  if(otherRows){ out+='<details class="bb-dims__more"'+(curRows?'':' open')+'><summary>'+(curRows?'All '+rows.length+' configurations':'Configurations')+'</summary>'+head+(curRows?curRows:'')+otherRows+'</tbody></table></details>'; }
  var style='<style>.bb-dims{width:100%;border-collapse:collapse;font-size:1.35rem;margin:0 0 1.2rem}.bb-dims th{text-align:left;font-weight:600;color:#6b6b6b;font-size:1.15rem;text-transform:uppercase;letter-spacing:.05em;padding:.6rem .4rem;border-bottom:1px solid #e8e8e8}.bb-dims td{padding:.8rem .4rem;border-bottom:1px solid #f0f0f0;vertical-align:top}.bb-dims__cur td{font-weight:600;background:#faf7f2}.bb-dims__label{margin:0 0 .6rem;font-size:1.2rem;text-transform:uppercase;letter-spacing:.06em;color:#6b6b6b}.bb-dims__more summary{cursor:pointer;font-weight:600;font-size:1.4rem;padding:.8rem 0;color:#1a56db}.bb-dims__more[open] summary{margin-bottom:.6rem}</style>';
  ov.innerHTML=intro;
  if(dim){
    var old=dim.querySelector('table'); if(old) old.style.display='none';
    var cta=dim.querySelector('.product-tabs__cta');
    if(cta) cta.insertAdjacentHTML('beforebegin',style+out); else dim.insertAdjacentHTML('afterbegin',style+out);
  }
  // re-highlight on variant change
  if(sel){ sel.addEventListener('change',function(){ var bi=bestIdx(sel.value,names); document.querySelectorAll('.bb-dims tr[data-i]').forEach(function(tr){ tr.classList.toggle('bb-dims__cur', parseInt(tr.getAttribute('data-i'))===bi); }); var lbl=document.querySelector('.bb-dims__label'); if(lbl) lbl.textContent = bi>-1 ? 'Selected configuration: '+names[bi] : 'Configurations'; }); }
})();
