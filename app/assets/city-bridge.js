/* Same-origin scene bridge. Energy values are fetched from the Python result API. */
window.dash_clientside=Object.assign({},window.dash_clientside,{
  vppCity:{sync:function(run,step,asset,layer){
    const state={type:'vpp-city-state',run:run,step:step||0,asset:asset||0,layer:layer||'assets'};
    window.VPP_CITY_STATE=state;
    const frame=document.getElementById('district-world');
    if(frame?.contentWindow)frame.contentWindow.postMessage(state,location.origin);
    return state;
  }}
});
window.addEventListener('message',function(event){
  if(event.origin!==location.origin)return;
  const frame=document.getElementById('district-world');
  if(!frame||event.source!==frame.contentWindow)return;
  if(event.data?.type==='vpp-city-ready'&&window.VPP_CITY_STATE)frame.contentWindow.postMessage(window.VPP_CITY_STATE,location.origin);
  if(event.data?.type==='vpp-city-select'&&Number.isInteger(event.data.index))window.dash_clientside.set_props('asset',{value:event.data.index});
});
