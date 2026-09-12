/* Independent, local-only Unity video receiver. It never controls the Brain or Bridge. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const video=$('unity-video'), layer=$('unity-video-layer'), form=$('video-connect-form');
  const endpointInput=$('video-endpoint'), streamSelect=$('video-stream-select'), connectButton=$('video-connect'), disconnectButton=$('video-disconnect');
  const LOOPBACK=new Set(['localhost','127.0.0.1','[::1]','::1']), MAX_STALE_MS=2000;
  let generation=0, peer=null, sessionId=null, pollTimer=null, peerConnectTimer=null, freshnessWatchdog=null, fallbackWatchdog=null, frameCallbackId=null, fallbackFrames=-1, lastPresentedAt=0, lastPresentedFrames=0, lastPublisherId=null, pollInFlightGeneration=null;
  let current={endpoint:null,streamId:null,connection:'idle',streamState:'unavailable',sequence:null,frameAgeMs:null,statusReceivedAt:0,statusGeneration:0,staleAfterMs:MAX_STALE_MS,publisherId:null,source:null,width:null,height:null,viewers:null,peerConnected:false,live:false,error:''};
  const state=()=>Object.freeze({...current,source:current.source?Object.freeze({...current.source}):null,sourceLabel:current.source?.label||current.streamId||'未接続'});
  const setText=(id,value)=>{const el=$(id),text=String(value??'—');if(el.textContent!==text)el.textContent=text;};
  const now=()=>performance.now();
  const serviceError=code=>({publisher_not_live:'Unityの映像がまだ届いていません。Unityを起動してから再接続してください。',viewer_limit:'映像の視聴数が上限に達しています。別の映像接続を閉じてから再接続してください。',unknown_stream:'選んだUnityの映像が登録されていません。接続設定を確認してください。',origin_not_allowed:'この画面からの映像接続が許可されていません。映像サービスの接続設定を確認してください。',invalid_offer_or_ice_timeout:'映像接続を確立できませんでした。ネットワークと映像サービスを確認してください。'}[code]||'映像サービスへの接続に失敗しました。接続設定を確認してください。');
  function endpoint(raw) {
    const value=String(raw||'').trim();
    const url=new URL(value);
    if(!['http:','https:'].includes(url.protocol) || !LOOPBACK.has(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname!=='/') throw new Error('映像接続先は http(s)://localhost:ポート のみ指定できます。path・認証情報・query・hash は使えません。');
    return url.origin;
  }
  function streamUrl(path) { return current.endpoint+path; }
  function resetFrameProof() { lastPresentedAt=0;lastPresentedFrames=0;fallbackFrames=-1; }
  function staleAfterMs() { return Math.min(MAX_STALE_MS,current.staleAfterMs); }
  function currentFrameAge() { return current.statusGeneration===generation&&Number.isFinite(current.frameAgeMs)?Math.max(0,current.frameAgeMs+now()-current.statusReceivedAt):Infinity; }
  function frameFresh() { return lastPresentedAt>0 && now()-lastPresentedAt<=staleAfterMs(); }
  function providerLive() { return current.peerConnected&&current.streamState==='live'&&currentFrameAge()<=staleAfterMs(); }
  function updateVisibility() { current.live=providerLive()&&frameFresh();layer.hidden=false;layer.style.opacity=current.live?'1':'0';layer.style.pointerEvents='none';layer.dataset.videoVisibility=current.live?'live':'waiting'; }
  function render() {
    updateVisibility();
    const active=['connecting','signalling','connected','waiting','live','stale'].includes(current.connection);
    setText('video-live-state',current.live?'LIVE':current.connection==='idle'?'未接続':current.connection==='error'?'エラー':current.streamState==='stale'?'STALE':current.streamState==='waiting'?'WAITING':'接続中');
    setText('video-connection-status',current.connection==='idle'?'明示接続を待っています':current.connection==='connecting'?'設定を取得中':current.connection==='signalling'?'WebRTCを確立中':current.connection==='connected'?'受信待機中':current.connection==='waiting'?'Unity配信を待っています':current.connection==='live'?(current.live?'ブラウザで映像を描画中':'映像フレームを確認中'):current.connection==='stale'?'映像が古いため非表示':current.connection==='error'?'接続できませんでした':current.connection);
    const age=currentFrameAge();
    setText('video-stream-status',current.streamState==='live'?(current.sequence==null?'live':'live / #'+current.sequence)+(Number.isFinite(age)?' / '+Math.round(age)+' ms':''):current.streamState==='stale'?'stale（古いフレームは非表示）':current.streamState==='waiting'?'waiting':'—');
    setText('video-execution-os',current.source?.executionOs||'—');
    setText('video-source-detail',current.source?(current.source.kind||'unity-game')+' / '+(current.source.label||'—'):'—');
    setText('video-note',current.live?'Unity映像を表示しています。Brain・制御・デモとは独立し、Brain と同じ session の対応は未確認です。':'LIVE は配信元が live で、ブラウザで新しい映像フレームを描画できたときだけ表示します。Brain と同じ session の対応は未確認です。');
    $('video-error').textContent=current.error||'';
    disconnectButton.disabled=!active && !sessionId;
    connectButton.disabled=current.connection==='connecting'||current.connection==='signalling';
    streamSelect.disabled=!current.endpoint || !streamSelect.options.length || current.connection==='connecting'||current.connection==='signalling';
    window.dispatchEvent(new CustomEvent('flyvideochange',{detail:state()}));
  }
  function error(message) { current.error=message;current.connection='error';current.streamState='stale';resetFrameProof();render(); }
  async function requestJson(url,options={},timeoutMs=8000) {
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
    try {
      const response=await fetch(url,{...options,credentials:'omit',cache:'no-store',signal:controller.signal});
      const body=await response.json().catch(()=>null);
      if(!response.ok) throw new Error(serviceError(body?.error));
      if(!body || typeof body!=='object' || Array.isArray(body)) throw new Error('映像サービスの応答が不正です。');
      return body;
    } catch (cause) {
      if(cause?.name==='AbortError') throw new Error('映像サービスの応答がタイムアウトしました。');
      throw cause;
    } finally { clearTimeout(timer); }
  }
  async function deleteSession(id,origin=current.endpoint) {
    if(!id || !origin) return;
    try { await fetch(origin+'/api/video/sessions/'+encodeURIComponent(id),{method:'DELETE',credentials:'omit',cache:'no-store',keepalive:true}); } catch {}
  }
  function clearPeer() {
    if(pollTimer){clearTimeout(pollTimer);pollTimer=null;}
    if(peerConnectTimer){clearTimeout(peerConnectTimer);peerConnectTimer=null;}
    if(fallbackWatchdog){clearInterval(fallbackWatchdog);fallbackWatchdog=null;}
    if(frameCallbackId!==null && typeof video.cancelVideoFrameCallback==='function')video.cancelVideoFrameCallback(frameCallbackId);
    frameCallbackId=null;video.onloadeddata=null;video.onpause=null;
    const old=peer;peer=null;if(old){old.ontrack=old.onconnectionstatechange=null;try{old.close();}catch{}}
    try{video.pause();}catch{};video.srcObject=null;resetFrameProof();layer.hidden=false;layer.style.opacity='0';layer.style.pointerEvents='none';layer.dataset.videoVisibility='waiting';
  }
  function disconnect() {
    ++generation;const oldSession=sessionId,oldEndpoint=current.endpoint;sessionId=null;clearPeer();
    lastPublisherId=null;
    current={...current,connection:'idle',streamState:'unavailable',sequence:null,frameAgeMs:null,statusReceivedAt:0,statusGeneration:0,publisherId:null,source:null,width:null,height:null,viewers:null,peerConnected:false,live:false,error:''};
    render();void deleteSession(oldSession,oldEndpoint);
  }
  function markFrame(metadata) {
    const frames=Number(metadata?.presentedFrames);
    if(!Number.isFinite(frames) || frames>lastPresentedFrames){lastPresentedFrames=Number.isFinite(frames)?frames:lastPresentedFrames+1;lastPresentedAt=now();}
    render();
  }
  function observeFrames(expectedGeneration,expectedPeer) {
    if(frameCallbackId!==null && typeof video.cancelVideoFrameCallback==='function')video.cancelVideoFrameCallback(frameCallbackId);
    if(fallbackWatchdog){clearInterval(fallbackWatchdog);fallbackWatchdog=null;}
    if(typeof video.requestVideoFrameCallback==='function') {
      const next=(_,metadata)=>{if(expectedGeneration!==generation||peer!==expectedPeer)return;markFrame(metadata);frameCallbackId=video.requestVideoFrameCallback(next);};
      frameCallbackId=video.requestVideoFrameCallback(next);return;
    }
    video.onloadeddata=()=>{if(expectedGeneration!==generation||peer!==expectedPeer)return;const quality=video.getVideoPlaybackQuality?.(),frames=quality?.totalVideoFrames;if(Number.isFinite(frames)&&frames>fallbackFrames){fallbackFrames=frames;markFrame({presentedFrames:frames});}};
    const interval=setInterval(()=>{if(expectedGeneration!==generation||peer!==expectedPeer){clearInterval(interval);if(fallbackWatchdog===interval)fallbackWatchdog=null;return;}const quality=video.getVideoPlaybackQuality?.(),frames=quality?.totalVideoFrames;if(Number.isFinite(frames)&&frames>fallbackFrames){fallbackFrames=frames;markFrame({presentedFrames:frames});}else render();},250);fallbackWatchdog=interval;
  }
  function waitForIceComplete(pc,expectedGeneration) {
    return new Promise((resolve,reject)=>{
      let done=false;const finish=()=>{if(done)return;done=true;clearTimeout(timer);pc.removeEventListener('icegatheringstatechange',check);if(expectedGeneration!==generation)reject(new Error('映像接続は新しい要求に置き換えられました。'));else resolve(pc.localDescription);};
      const check=()=>{if(pc.iceGatheringState==='complete')finish();};
      const timer=setTimeout(()=>{if(done)return;done=true;pc.removeEventListener('icegatheringstatechange',check);reject(new Error('ICE candidate の収集が12秒以内に完了しませんでした。'));},12000);pc.addEventListener('icegatheringstatechange',check);check();
    });
  }
  function populateStreams(streams) {
    const previous=streamSelect.value;streamSelect.replaceChildren();
    for(const id of streams){const option=document.createElement('option');option.value=id;option.textContent=id;streamSelect.append(option);}
    if(streams.includes(previous))streamSelect.value=previous;
    else if(streams.includes(current.streamId))streamSelect.value=current.streamId;
  }
  function validateConfig(config) {
    if(!Array.isArray(config.iceServers)||!Array.isArray(config.streams)||!config.streams.every(id=>typeof id==='string'&&id.length>0&&id.length<=128)) throw new Error('映像サービスの設定が不正です。');
    const stale=Number(config.staleAfterMs);current.staleAfterMs=Number.isFinite(stale)&&stale>0?Math.min(stale,MAX_STALE_MS):MAX_STALE_MS;return config;
  }
  function stopForPublisherChange() {
    ++generation;const oldSession=sessionId,oldEndpoint=current.endpoint;sessionId=null;clearPeer();lastPublisherId=null;
    current={...current,connection:'stale',streamState:'stale',sequence:null,frameAgeMs:null,statusReceivedAt:0,statusGeneration:0,publisherId:null,source:null,width:null,height:null,viewers:null,peerConnected:false,live:false,error:'Unity配信元が切り替わりました。古い映像を破棄しました。明示的に再接続してください。'};
    render();void deleteSession(oldSession,oldEndpoint);
  }
  function applyStatus(payload) {
    if(payload.streamId!==current.streamId || !['waiting','live','stale'].includes(payload.state)) throw new Error('映像streamの状態が不正です。');
    const publisher=typeof payload.publisherId==='string'?payload.publisherId:null;
    if(lastPublisherId!==null&&publisher!==lastPublisherId){stopForPublisherChange();return;}
    lastPublisherId=publisher;current.streamState=payload.state;current.sequence=Number.isSafeInteger(payload.sequence)?payload.sequence:null;current.frameAgeMs=Number.isFinite(payload.frameAgeMs)?Math.max(0,payload.frameAgeMs):null;current.statusReceivedAt=now();current.statusGeneration=generation;current.publisherId=publisher;
    current.source=payload.source&&typeof payload.source==='object'?{kind:typeof payload.source.kind==='string'?payload.source.kind:'unity-game',label:typeof payload.source.label==='string'?payload.source.label:'—',executionOs:typeof payload.source.executionOs==='string'?payload.source.executionOs:'—'}:null;
    current.width=Number.isFinite(payload.width)?payload.width:null;current.height=Number.isFinite(payload.height)?payload.height:null;current.viewers=Number.isFinite(payload.viewers)?payload.viewers:null;
    current.connection=payload.state==='waiting'?'waiting':payload.state==='stale'?'stale':'live';current.error='';render();
  }
  async function pollStatus(expectedGeneration) {
    if(expectedGeneration!==generation || !current.endpoint || !current.streamId || pollInFlightGeneration===expectedGeneration)return;
    pollInFlightGeneration=expectedGeneration;
    try { const payload=await requestJson(streamUrl('/api/video/streams/'+encodeURIComponent(current.streamId)),{},5000);if(expectedGeneration===generation)applyStatus(payload); }
    catch(cause){if(expectedGeneration===generation){current.streamState='stale';current.connection='stale';current.error='映像状態を確認できません: '+cause.message;render();}}
    finally { if(pollInFlightGeneration===expectedGeneration)pollInFlightGeneration=null;if(expectedGeneration===generation&&peer)pollTimer=setTimeout(()=>pollStatus(expectedGeneration),500); }
  }
  async function connect() {
    let origin;
    try { origin=endpoint(endpointInput.value); } catch(cause) { current.error=cause.message;render();return; }
    disconnect();const expectedGeneration=++generation;current={...current,endpoint:origin,streamId:null,connection:'connecting',streamState:'unavailable',error:''};render();
    try {
      const config=validateConfig(await requestJson(origin+'/api/video/config',{},8000));
      if(expectedGeneration!==generation)return;populateStreams(config.streams);if(!config.streams.length)throw new Error('利用できるUnity streamがありません。');
      const streamId=streamSelect.value;if(!config.streams.includes(streamId))throw new Error('選択したUnity streamは映像サービスにありません。');
      if(typeof RTCPeerConnection!=='function')throw new Error('このブラウザはWebRTC映像受信に対応していません。');
      current.streamId=streamId;current.connection='signalling';render();
      const pc=new RTCPeerConnection({iceServers:config.iceServers});peer=pc;pc.addTransceiver('video',{direction:'recvonly'});
      pc.ontrack=event=>{if(expectedGeneration!==generation||peer!==pc)return;video.srcObject=event.streams[0]||new MediaStream([event.track]);void video.play().catch(()=>{});observeFrames(expectedGeneration,pc);};
      pc.onconnectionstatechange=()=>{if(expectedGeneration!==generation||peer!==pc)return;const value=pc.connectionState;if(value==='connected'){current.peerConnected=true;if(peerConnectTimer){clearTimeout(peerConnectTimer);peerConnectTimer=null;}render();return;}if(['failed','disconnected','closed'].includes(value)){const oldSession=sessionId;sessionId=null;clearPeer();current.connection='stale';current.streamState='stale';current.peerConnected=false;current.error='WebRTC映像接続が切れました。再接続は自動では行いません。';render();void deleteSession(oldSession);}};
      await pc.setLocalDescription(await pc.createOffer());const offer=await waitForIceComplete(pc,expectedGeneration);
      const answer=await requestJson(origin+'/api/video/streams/'+encodeURIComponent(streamId)+'/offer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:offer.type,sdp:offer.sdp})},25000);
      if(typeof answer.sdp!=='string'||answer.type!=='answer'||typeof answer.sessionId!=='string')throw new Error('映像サービスのanswerが不正です。');
      if(expectedGeneration!==generation||peer!==pc){void deleteSession(answer.sessionId,origin);return;}
      sessionId=answer.sessionId;await pc.setRemoteDescription({type:'answer',sdp:answer.sdp});if(expectedGeneration!==generation||peer!==pc){void deleteSession(answer.sessionId,origin);return;}
      current.connection='connected';current.peerConnected=pc.connectionState==='connected';render();
      if(!current.peerConnected)peerConnectTimer=setTimeout(()=>{if(expectedGeneration!==generation||peer!==pc||pc.connectionState==='connected')return;const oldSession=sessionId;sessionId=null;clearPeer();current.connection='error';current.streamState='stale';current.peerConnected=false;current.error='WebRTC映像接続が確立しませんでした。再接続は自動では行いません。';render();void deleteSession(oldSession,origin);},15000);
      void pollStatus(expectedGeneration);
    } catch(cause) { if(expectedGeneration===generation){const oldSession=sessionId;sessionId=null;clearPeer();error(cause?.message||'映像を接続できませんでした。');void deleteSession(oldSession,origin);} }
  }
  form.onsubmit=event=>{event.preventDefault();void connect();};
  disconnectButton.onclick=disconnect;
  streamSelect.onchange=()=>{if(peer){current.error='streamの選択を変更しました。反映するには「映像を接続」を押してください。';render();}};
  freshnessWatchdog=setInterval(()=>{if(current.endpoint&&current.connection!=='idle')render();},200);
  window.addEventListener('pagehide',()=>{clearInterval(freshnessWatchdog);disconnect();},{once:true});
  window.FlyVideo=Object.freeze({state,disconnect});render();
})();
