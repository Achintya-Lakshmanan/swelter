/* Real facilities selected by the trained heat/cold risk models. */
(() => {
  const $=s=>document.querySelector(s);
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let selected=null;
  const app=()=>window.swelter;
  const sites=()=>app()?.state.iv==='refuge' ? app().summary().result.sites.slice(0,app().state.siteBudget) : [];
  // Cache displayed sites: map redraws every frame and must not recompute population summaries.
  let displayed=[];
  window.swelterShelters={get sites(){return displayed;},get selected(){return selected;},get active(){return true;},select:selectSite};
  function selectSite(id){const site=displayed.find(s=>s.id===id);if(!site)return;selected=id;app().focusSite(site.lon,site.lat);render();document.querySelectorAll('[data-site]').forEach(b=>{if(b.dataset.site===id)b.focus({preventScroll:true});});app().refreshMap();}
  function render(){
    if(!app()?.run)return;
    displayed=sites();
    const state=app().state;
    const body=$('#shelter-body');
    $('#shelter-panel').hidden=state.iv!=='refuge';
    $('#shelter-budget').value=String(state.siteBudget);
    $('#shelter-budget').closest('label').hidden=state.iv!=='refuge';
    const rows=displayed.map(s=>'<li><button class="shelter-site '+(selected===s.id?'selected':'')+'" data-site="'+escape(s.id)+'" aria-pressed="'+(selected===s.id)+'"><span class="shelter-rank">'+s.rank+'</span><span><strong>'+escape(s.name)+'</strong><span class="muted site-address">'+escape(s.address)+' · '+escape(s.hours_text)+'</span></span></button><p class="shelter-site-metrics">'+s.additional_expected_risk_hours.toLocaleString()+' additional predicted risk-hours within reach<br>'+s.at_risk_residents+' at-risk synthetic residents · '+s.no_car+' without cars · '+s.no_ac_or_heat+' without '+(state.hazard==='heat'?'AC':'reliable heat')+'</p></li>').join('');
    body.innerHTML=state.iv==='refuge'?'<ol class="shelter-list">'+(rows||'<li>No sites add coverage under the current assumptions.</li>')+'</ol>':'';
    document.querySelectorAll('[data-site]').forEach(b=>b.onclick=()=>selectSite(b.dataset.site));
  }
  $('#shelter-budget').onchange=e=>{selected=null;app().setBudget(+e.target.value);};
  document.addEventListener('swelter:scenario',()=>{selected=null;render();app().refreshMap();});
})();
