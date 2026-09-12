/* Local Unity video receiver. It never controls the Brain, Bridge, microphone, or demo. */
(() => {
  'use strict';

  const $=id=>document.getElementById(id), LOOPBACK=new Set(['localhost','127.0.0.1','[::1]','::1']), MAX_STALE_MS=2000, BRAIN_STALE_MS=750, MAX_RETRIES=6, HISTORY_LIMIT=600;

  const video=$('unity-video'), layer=$('unity-video-layer'), form=$('video-connect-form'), endpointInput=$('video-endpoint'), streamSelect=$('video-stream-select'), connectButton=$('video-connect'), disconnectButton=$('video-disconnect');

  let generation=0, peer=null, sessionId=null, workAbort=null, pollTimer=null, freshnessTimer=null, retryTimer=null, peerConnectTimer=null, statsTimer=null, frameCallbackId=null, fallbackTimer=null, probeTimer=null, pollInFlightGeneration=null, fallbackFrames=-1, lastPresentedAt=0, lastPresentedFrames=0, firstFrameDueAt=0, liveSince=0, lastPublisherId=null, staleSince=0, retryCount=0, retryIntent=null, expectedIdentity=null, expectedIdentityAt=0, signallingIdentity=null, signallingBindingAvailable=false, statsPrevious=null, probePending=null, lastProbeAt=0;

  let history=[];
  let expectedFrames=[];

  const blankMetrics=()=>({browser:{fps:null,receivedKbps:null,packetLossDelta:null,jitterMs:null,rttMs:null,decodeMsPerFrame:null,framesDropped:null,framesDroppedDelta:null,visualRoundTripMs:null},backend:null});

  let current={endpoint:null,streamId:null,connection:'idle',streamState:'unavailable',sequence:null,frameAgeMs:null,statusReceivedAt:0,statusGeneration:0,staleAfterMs:MAX_STALE_MS,publisherId:null,source:null,width:null,height:null,viewers:null,peerConnected:false,identityState:'unknown',bodyBrainSessionMatched:false,metrics:blankMetrics(),retryAttempt:0,live:false,error:''};

  const now=()=>performance.now(), nonEmpty=value=>typeof value==='string'&&value.length>0, finite=value=>typeof value==='number'&&Number.isFinite(value);

  function clone(value) { if(Array.isArray(value))return value.map(clone);
if(value&&typeof value==='object'){const copy={};
for(const [key,item] of Object.entries(value))copy[key]=clone(item);
return copy;
}return value;
 }
  function freeze(value) { if(value&&typeof value==='object'&&!Object.isFrozen(value)){for(const item of Object.values(value))freeze(item);
Object.freeze(value);
}return value;
 }
  const state=()=>freeze({...current,source:clone(current.source),metrics:clone(current.metrics),expectedIdentity:clone(expectedIdentity),sourceLabel:current.source?.label||current.streamId||'未接続'});

  const measurements=()=>freeze(history.map(row=>clone(row)));

  const setText=(id,value)=>{const el=$(id),text=String(value??'—');
if(el&&el.textContent!==text)el.textContent=text;
};

  const serviceError=code=>({publisher_not_live:'Unityの映像がまだ届いていません。',viewer_limit:'映像の視聴数が上限に達しています。',unknown_stream:'選んだUnity streamが登録されていません。',origin_not_allowed:'この画面からの映像接続は許可されていません。',invalid_offer_or_ice_timeout:'映像接続を確立できませんでした。'}[code]||'映像サービスへの接続に失敗しました。');

  function failure(message,{retryable=true,code=null}={}) { const error=new Error(message);
error.retryable=retryable;
error.code=code;
return error;
 }
  function endpoint(raw) { const url=new URL(String(raw||'').trim());
if(!['http:','https:'].includes(url.protocol)||!LOOPBACK.has(url.hostname)||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw failure('映像接続先は http(s)://localhost:ポート のみ指定できます。path・認証情報・query・hash は使えません。',{retryable:false});
return url.origin;
 }
  function streamUrl(path) { return current.endpoint+path;
 }
  function staleAfterMs() { return Math.min(MAX_STALE_MS,current.staleAfterMs);
 }
  function currentFrameAge() { return current.statusGeneration===generation&&finite(current.frameAgeMs)?Math.max(0,current.frameAgeMs+now()-current.statusReceivedAt):Infinity;
 }
  function frameFresh() { return lastPresentedAt>0&&now()-lastPresentedAt<=staleAfterMs();
 }
  function normalizeIdentity(value) { if(!value||typeof value!=='object'||Array.isArray(value))return null;
const identity={};
for(const key of ['instanceId','sessionId','backendId','datasetId','configHash','graphHash','sourceHash'])if(nonEmpty(value[key]))identity[key]=value[key];
identity.brainConnected=value.brainConnected!==false;
identity.frameAgeMs=finite(value.frameAgeMs)?Math.max(0,value.frameAgeMs):null;
identity.frameSequence=Number.isSafeInteger(value.frameSequence)&&value.frameSequence>=0?value.frameSequence:null;
return identity;
 }
  function sameBinding(left,right) { if(!left||!right)return left===right;
for(const key of ['instanceId','sessionId','backendId','datasetId','configHash','graphHash','sourceHash'])if((left[key]||null)!==(right[key]||null))return false;
return true;
 }
  function brainIdentityFresh(identity) { return !!identity&&identity.brainConnected===true&&finite(identity.frameAgeMs)&&current.statusGeneration===generation&&identity.frameAgeMs+now()-current.statusReceivedAt<=BRAIN_STALE_MS;
}
  function expectedIdentityFresh() { return !!expectedIdentity&&finite(expectedIdentity.frameAgeMs)&&expectedIdentityAt>0&&expectedIdentity.frameAgeMs+now()-expectedIdentityAt<=BRAIN_STALE_MS;
}
  function assessIdentity() { const observed=current.source?.brainIdentity;
if(!expectedIdentity||!signallingIdentity||!observed)return 'unknown';
if(!sameBinding(signallingIdentity,observed))return 'mismatch';
if(observed.instanceId!==expectedIdentity.instanceId||observed.sessionId!==expectedIdentity.sessionId)return 'mismatch';
for(const key of ['backendId','datasetId','configHash','graphHash','sourceHash'])if(nonEmpty(expectedIdentity[key])&&observed[key]!==expectedIdentity[key])return 'mismatch';
if(['instanceId','sessionId','backendId','datasetId','configHash','graphHash','sourceHash'].some(key=>!nonEmpty(expectedIdentity[key])||!nonEmpty(observed[key])))return 'unknown';
if(!brainIdentityFresh(observed)||!expectedIdentityFresh()||expectedIdentity.brainConnected!==true)return 'unknown';
if(!Number.isSafeInteger(observed.frameSequence)||!expectedFrames.some(frame=>frame.sequence===observed.frameSequence&&now()-frame.receivedAt<=BRAIN_STALE_MS))return 'unknown';
return 'matched';
 }
  function updateVisibility() { current.identityState=assessIdentity();
current.live=current.peerConnected&&current.streamState==='live'&&currentFrameAge()<=staleAfterMs()&&frameFresh()&&current.identityState!=='mismatch';
current.bodyBrainSessionMatched=current.identityState==='matched'&&current.live;
layer.hidden=false;
layer.style.opacity=current.live?'1':'0';
layer.style.pointerEvents='none';
layer.dataset.videoVisibility=current.live?'live':'waiting';
 }
  function note() { const visual=finite(current.metrics.browser.visualRoundTripMs)?' 診断stripの要求から表示まで '+Math.round(current.metrics.browser.visualRoundTripMs)+' ms（片方向E2Eではない上限値）。':'';
if(current.identityState==='matched')return 'Unity映像と現在のBrain identity は一致しています。映像経路は操作・マイクから独立です。'+visual;
if(current.identityState==='mismatch')return '現在のBrainと映像の接続先が一致しません。設定でUnityの映像を選び直してください。';
if(current.live)return 'Unity映像を表示中。Brain identity は未照合です。映像経路は操作・マイクから独立です。'+visual;
return 'LIVE は配信元・WebRTC・新しい描画 frame を確認したときだけ表示します。Brain identity は未照合のまま表示されることがあります。';
 }
  function render() { updateVisibility();
const active=!['idle','error'].includes(current.connection),age=currentFrameAge(),browser=current.metrics.browser;
setText('video-live-state',current.live?'LIVE':current.connection==='idle'?'未接続':current.connection==='recovering'?'再接続中':current.connection==='error'?'エラー':current.streamState==='stale'?'STALE':current.streamState==='waiting'?'WAITING':'接続中');
setText('video-connection-status',current.connection==='idle'?'明示接続を待っています':current.connection==='recovering'?'映像を再接続中（'+current.retryAttempt+'/'+MAX_RETRIES+'）':current.connection==='connecting'?'設定を取得中':current.connection==='signalling'?'WebRTCを確立中':current.connection==='connected'?'受信待機中':current.connection==='waiting'?'Unity配信を待っています':current.connection==='live'?(current.live?'ブラウザで映像を描画中':'映像フレームを確認中'):current.connection==='stale'?'映像が古いため非表示':current.connection==='error'?'接続できませんでした':current.connection);
setText('video-stream-status',current.streamState==='live'?(current.sequence==null?'live':'live / #'+current.sequence)+(finite(age)?' / '+Math.round(age)+' ms':''):current.streamState==='stale'?'stale（古いフレームは非表示）':current.streamState==='waiting'?'waiting':'—');
setText('video-execution-os',current.source?.executionOs||'—');
setText('video-source-detail',current.source?(current.source.kind||'unity-game')+' / '+(current.source.label||'—'):'—');
setText('video-note',note()+(finite(browser.fps)?' 受信 '+browser.fps.toFixed(1)+' fps。':''));
setText('video-error',current.error||'');
if(disconnectButton)disconnectButton.disabled=!active&&!sessionId;
if(connectButton)connectButton.disabled=['connecting','signalling'].includes(current.connection);
if(streamSelect)streamSelect.disabled=!current.endpoint||!streamSelect.options.length||['connecting','signalling'].includes(current.connection);
window.dispatchEvent(new CustomEvent('flyvideochange',{detail:state()}));
 }
  function cancelTimer(timer) { if(timer)clearTimeout(timer);
return null;
 }
  function clearMediaObservers() { if(frameCallbackId!==null&&typeof video.cancelVideoFrameCallback==='function')video.cancelVideoFrameCallback(frameCallbackId);
frameCallbackId=null;
if(fallbackTimer){clearInterval(fallbackTimer);
fallbackTimer=null;
} }
  function clearProbe() { if(probeTimer){clearTimeout(probeTimer);
probeTimer=null;
}probePending=null;
 }
  function resetMetrics() { if(statsTimer){clearInterval(statsTimer);
statsTimer=null;
}statsPrevious=null;
history=[];
current.metrics=blankMetrics();
 }
  function clearPeer() { pollTimer=cancelTimer(pollTimer);
peerConnectTimer=cancelTimer(peerConnectTimer);
if(freshnessTimer){clearInterval(freshnessTimer);
freshnessTimer=null;
}clearMediaObservers();
clearProbe();
resetMetrics();
video.onloadeddata=null;
const old=peer;
peer=null;
if(old){old.ontrack=old.onconnectionstatechange=null;
try{old.close();
}catch{}}try{video.pause();
}catch{}video.srcObject=null;
fallbackFrames=-1;
lastPresentedAt=0;
lastPresentedFrames=0;
firstFrameDueAt=0;
liveSince=0;
layer.hidden=false;
layer.style.opacity='0';
layer.style.pointerEvents='none';
layer.dataset.videoVisibility='waiting';
 }
  function teardown({preserveIntent=false}={}) { ++generation;
workAbort?.abort();
workAbort=null;
retryTimer=cancelTimer(retryTimer);
if(!preserveIntent){retryTimer=cancelTimer(retryTimer);
retryIntent=null;
retryCount=0;
}const oldSession=sessionId,oldEndpoint=current.endpoint;
sessionId=null;
clearPeer();
lastPublisherId=null;
staleSince=0;
signallingIdentity=null;
signallingBindingAvailable=false;
current={...current,endpoint:preserveIntent?oldEndpoint:null,streamId:preserveIntent?current.streamId:null,connection:'idle',streamState:'unavailable',sequence:null,frameAgeMs:null,statusReceivedAt:0,statusGeneration:0,publisherId:null,source:null,width:null,height:null,viewers:null,peerConnected:false,identityState:'unknown',bodyBrainSessionMatched:false,metrics:blankMetrics(),retryAttempt:0,live:false,error:''};
void deleteSession(oldSession,oldEndpoint);
 }
  function disconnect() { teardown();
render();
 }
  async function deleteSession(id,origin) { if(!id||!origin)return;
try{await fetch(origin+'/api/video/sessions/'+encodeURIComponent(id),{method:'DELETE',credentials:'omit',cache:'no-store',keepalive:true});
}catch{} }
  async function requestJson(url,options={},timeoutMs=8000,expectedGeneration=generation) { if(expectedGeneration!==generation||!workAbort)throw failure('映像接続は新しい要求に置き換えられました。');
const controller=new AbortController(),external=workAbort.signal,abort=()=>controller.abort(),timer=setTimeout(abort,timeoutMs);
external.addEventListener('abort',abort,{once:true});
try{const response=await fetch(url,{...options,credentials:'omit',cache:'no-store',redirect:'error',signal:controller.signal}),body=await response.json().catch(()=>null);
if(!response.ok){const code=body?.error;
throw failure(serviceError(code),{retryable:response.status>=500||['publisher_not_live','invalid_offer_or_ice_timeout'].includes(code),code});
}if(!body||typeof body!=='object'||Array.isArray(body))throw failure('映像サービスの応答が不正です。');
return body;
}catch(cause){if(cause?.name==='AbortError')throw failure('映像サービスの応答がタイムアウトまたは中止されました。');
throw cause;
}finally{clearTimeout(timer);
external.removeEventListener('abort',abort);
}}
  function waitForIceComplete(pc,expectedGeneration) { return new Promise((resolve,reject)=>{const external=workAbort?.signal;
let done=false;
const finish=result=>{if(done)return;
done=true;
clearTimeout(timer);
pc.removeEventListener('icegatheringstatechange',check);
external?.removeEventListener('abort',abort);
result?resolve(pc.localDescription):reject(failure('ICE candidate の収集が12秒以内に完了しませんでした。'));
},check=()=>{if(pc.iceGatheringState==='complete')finish(true);
},abort=()=>finish(false),timer=setTimeout(()=>finish(false),12000);
external?.addEventListener('abort',abort,{once:true});
pc.addEventListener('icegatheringstatechange',check);
check();
});
 }
  function populateStreams(streams,selected) { const previous=selected||streamSelect.value;
streamSelect.replaceChildren();
for(const id of streams){const option=document.createElement('option');
option.value=id;
option.textContent=id;
streamSelect.append(option);
}if(streams.includes(previous))streamSelect.value=previous;
 }
  function validateConfig(config) { if(!Array.isArray(config.iceServers)||!Array.isArray(config.streams)||!config.streams.every(id=>nonEmpty(id)&&id.length<=128))throw failure('映像サービスの設定が不正です。',{retryable:false});
const stale=Number(config.staleAfterMs);
current.staleAfterMs=finite(stale)&&stale>0?Math.min(stale,MAX_STALE_MS):MAX_STALE_MS;
return config;
 }
  function normalizeBackendMetrics(value) { if(!value||typeof value!=='object'||Array.isArray(value))return null;
const out={};
for(const key of ['receivedFrames','receivedBytes','decodeMs','ingressFps','ingressKbps'])if(finite(value[key]))out[key]=value[key];
if(value.publisher&&typeof value.publisher==='object'){out.publisher={};
for(const key of ['captureMs','encodeMs','uploadMs','gameFps','videoFps','jpegBytes'])if(finite(value.publisher[key]))out.publisher[key]=value.publisher[key];
out.publisher.diagnosticsOverlay=value.publisher.diagnosticsOverlay===true;
}return out;
 }
  function scheduleReconnect(reason) { if(!retryIntent)return;
teardown({preserveIntent:true});
if(retryCount>=MAX_RETRIES){retryIntent=null;
current.connection='error';
current.streamState='stale';
current.error=reason+' 自動再接続の上限に達しました。映像を接続し直してください。';
render();
return;
}const attempt=++retryCount,delay=Math.min(8000,500*2**(attempt-1));
current={...current,endpoint:retryIntent.endpoint,streamId:retryIntent.streamId,connection:'recovering',streamState:'stale',retryAttempt:attempt,error:reason+' '+Math.round(delay/1000*10)/10+'秒後に再接続します。'};
render();
retryTimer=setTimeout(()=>{retryTimer=null;
if(retryIntent)void connect(true);
},delay);
 }
  function applyStatus(payload) { if(payload.streamId!==current.streamId||!['waiting','live','stale'].includes(payload.state))throw failure('映像streamの状態が不正です。');
const publisher=nonEmpty(payload.publisherId)?payload.publisherId:null,source=payload.source&&typeof payload.source==='object'?{kind:nonEmpty(payload.source.kind)?payload.source.kind:'unity-game',label:nonEmpty(payload.source.label)?payload.source.label:'—',executionOs:nonEmpty(payload.source.executionOs)?payload.source.executionOs:'—',brainIdentity:normalizeIdentity(payload.source.brainIdentity)}:null;
if(lastPublisherId!==null&&publisher!==lastPublisherId){scheduleReconnect('Unity配信元が切り替わりました。古い映像を破棄します。');
return;
}if(signallingBindingAvailable&&!sameBinding(signallingIdentity,source?.brainIdentity)){scheduleReconnect('映像のBrain identity bindingが変わりました。古い映像を破棄します。');
return;
}lastPublisherId=publisher;
current.streamState=payload.state;
current.sequence=Number.isSafeInteger(payload.sequence)?payload.sequence:null;
current.frameAgeMs=finite(payload.frameAgeMs)?Math.max(0,payload.frameAgeMs):null;
current.statusReceivedAt=now();
current.statusGeneration=generation;
current.publisherId=publisher;
current.source=source;
current.width=finite(payload.width)?payload.width:null;
current.height=finite(payload.height)?payload.height:null;
current.viewers=finite(payload.viewers)?payload.viewers:null;
current.metrics={...current.metrics,backend:normalizeBackendMetrics(payload.metrics)};
current.connection=payload.state==='waiting'?'waiting':payload.state==='stale'?'stale':'live';
current.error='';
if(payload.state==='stale'){if(!staleSince)staleSince=now();
else if(now()-staleSince>=MAX_STALE_MS){scheduleReconnect('Unity映像が古い状態のままです。');
return;
}}else staleSince=0;
render();
maybeProbe(generation);
 }
  async function pollStatus(expectedGeneration) { if(expectedGeneration!==generation||!current.endpoint||!current.streamId||pollInFlightGeneration===expectedGeneration)return;
pollInFlightGeneration=expectedGeneration;
try{const payload=await requestJson(streamUrl('/api/video/streams/'+encodeURIComponent(current.streamId)),{},5000,expectedGeneration);
if(expectedGeneration===generation)applyStatus(payload);
}catch(cause){if(expectedGeneration===generation)scheduleReconnect('映像状態を確認できません: '+cause.message);
}finally{if(pollInFlightGeneration===expectedGeneration)pollInFlightGeneration=null;
if(expectedGeneration===generation&&peer)pollTimer=setTimeout(()=>pollStatus(expectedGeneration),500);
}}
  function pushMeasurement(value) { history.push(Object.freeze(value));
if(history.length>HISTORY_LIMIT)history.splice(0,history.length-HISTORY_LIMIT);
 }
  async function sampleStats(expectedGeneration,expectedPeer) { if(expectedGeneration!==generation||peer!==expectedPeer)return;
try{const reports=await expectedPeer.getStats();
if(expectedGeneration!==generation||peer!==expectedPeer)return;
let inbound=null,remote=null,candidate=null;
reports.forEach(report=>{if(report.type==='inbound-rtp'&&(report.kind==='video'||report.mediaType==='video'))inbound=report;
if(report.type==='remote-inbound-rtp'&&(report.kind==='video'||report.mediaType==='video'))remote=report;
if(report.type==='candidate-pair'&&report.state==='succeeded'&&(report.nominated||report.selected))candidate=report;
});
if(!inbound)return;
const stamp=now(),previous=statsPrevious,frames=inbound.framesDecoded,bytes=inbound.bytesReceived,lost=inbound.packetsLost,dropped=inbound.framesDropped,decode=inbound.totalDecodeTime;
let browser={...current.metrics.browser,jitterMs:finite(inbound.jitter)?inbound.jitter*1000:null,rttMs:finite(remote?.roundTripTime)?remote.roundTripTime*1000:finite(candidate?.currentRoundTripTime)?candidate.currentRoundTripTime*1000:null,framesDropped:finite(dropped)?dropped:null};
if(previous){const elapsed=Math.max(1,stamp-previous.at),delta=(value,prior)=>finite(value)&&finite(prior)&&value>=prior?value-prior:null,decodedDelta=delta(frames,previous.frames),bytesDelta=delta(bytes,previous.bytes),decodeDelta=delta(decode,previous.decode);
browser={...browser,fps:decodedDelta!==null?decodedDelta*1000/elapsed:null,receivedKbps:bytesDelta!==null?bytesDelta*8/elapsed:null,packetLossDelta:delta(lost,previous.lost),decodeMsPerFrame:decodedDelta>0&&decodeDelta!==null?decodeDelta*1000/decodedDelta:null,framesDroppedDelta:delta(dropped,previous.dropped)};
pushMeasurement({at:stamp,type:'webrtc',...browser});
}statsPrevious={at:stamp,frames,bytes,lost,dropped,decode};
current.metrics={...current.metrics,browser};
render();
}catch{}}
  function startStats(expectedGeneration,expectedPeer) { if(statsTimer)clearInterval(statsTimer);
void sampleStats(expectedGeneration,expectedPeer);
statsTimer=setInterval(()=>void sampleStats(expectedGeneration,expectedPeer),1000);
 }
  function markerNonce() { const bytes=new Uint32Array(1);
crypto.getRandomValues(bytes);
return bytes[0]||1;
 }
  let markerCanvas=null, markerContext=null;
  function decodeMarker() { if(video.videoWidth<256||video.videoHeight<8)return null;
if(!markerCanvas){markerCanvas=document.createElement('canvas');markerCanvas.width=256;markerCanvas.height=8;markerContext=markerCanvas.getContext('2d',{willReadFrequently:true});}
const context=markerContext;
if(!context)return null;
try{for(const y of [0,video.videoHeight-8]){context.drawImage(video,0,y,256,8,0,0,256,8);const pixels=context.getImageData(0,0,256,8).data;
let bits='';
for(let block=0;
block<64;
block++){let sum=0,count=0;
for(let xx=block*4+1;
xx<block*4+3;
xx++)for(let yy=2;
yy<6;
yy++){const index=(yy*256+xx)*4;
sum+=pixels[index]+pixels[index+1]+pixels[index+2];
count+=3;
}bits+=sum/count>=128?'1':'0';
}const read=(offset,length)=>parseInt(bits.slice(offset,offset+length),2)>>>0,magic=read(0,16),nonce=read(16,32),checksum=read(48,16);
if(magic===0xD3A5&&nonce!==0&&checksum===(((nonce>>>16)^(nonce&65535)^0x6B4D)&65535))return nonce;
}}catch{}return null;
 }
  function maybeMeasureProbe() { if(!probePending||probePending.generation!==generation||!probePending.accepted)return;
const nonce=decodeMarker();
if(nonce!==probePending.nonce)return;
const roundTrip=now()-probePending.startedAt;
current.metrics={...current.metrics,browser:{...current.metrics.browser,visualRoundTripMs:roundTrip}};
pushMeasurement({at:now(),type:'visual-roundtrip-upper-bound',visualRoundTripMs:roundTrip,nonce});
clearProbe();
render();
 }
  async function maybeProbe(expectedGeneration) { if(expectedGeneration!==generation||probePending||!current.live||current.metrics.backend?.publisher?.diagnosticsOverlay!==true||now()-lastProbeAt<5000)return;
const nonce=markerNonce();
lastProbeAt=now();
probePending={nonce,startedAt:now(),generation:expectedGeneration,accepted:false};
probeTimer=setTimeout(()=>{if(probePending?.generation===expectedGeneration)clearProbe();
},10000);
try{const answer=await requestJson(streamUrl('/api/video/streams/'+encodeURIComponent(current.streamId)+'/probe'),{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({nonce})},5000,expectedGeneration);
if(expectedGeneration!==generation||!probePending||answer.probeNonce!==nonce)throw failure('診断probeが受理されませんでした。');
probePending.accepted=true;
}catch{if(probePending?.generation===expectedGeneration)clearProbe();
}}
  function markFrame(metadata) { const frames=Number(metadata?.presentedFrames);
if(!finite(frames)||frames>lastPresentedFrames){lastPresentedFrames=finite(frames)?frames:lastPresentedFrames+1;
lastPresentedAt=now();
}render();
if(current.live){if(!liveSince)liveSince=now();
else if(now()-liveSince>=3000)retryCount=0;
}else liveSince=0;
maybeMeasureProbe();
maybeProbe(generation);
 }
  function observeFrames(expectedGeneration,expectedPeer) { clearMediaObservers();
if(typeof video.requestVideoFrameCallback==='function'){const next=(_,metadata)=>{if(expectedGeneration!==generation||peer!==expectedPeer)return;
markFrame(metadata);
frameCallbackId=video.requestVideoFrameCallback(next);
};
frameCallbackId=video.requestVideoFrameCallback(next);
return;
}const interval=setInterval(()=>{if(expectedGeneration!==generation||peer!==expectedPeer){clearInterval(interval);
return;
}const frames=video.getVideoPlaybackQuality?.().totalVideoFrames;
if(finite(frames)&&frames>fallbackFrames){fallbackFrames=frames;
markFrame({presentedFrames:frames});
}else render();
},250);
fallbackTimer=interval;
 }
  async function connect(automatic=false) { let origin,requestedStream;
try{if(automatic){if(!retryIntent)return;
origin=retryIntent.endpoint;
requestedStream=retryIntent.streamId;
}else{origin=endpoint(endpointInput.value);
requestedStream=streamSelect.value||null;
retryIntent={endpoint:origin,streamId:requestedStream};
retryCount=0;
retryTimer=cancelTimer(retryTimer);
}}catch(cause){current.error=cause.message;
render();
return;
}teardown({preserveIntent:true});
const expectedGeneration=++generation;
workAbort=new AbortController();
current={...current,endpoint:origin,streamId:null,connection:'connecting',streamState:'unavailable',retryAttempt:automatic?retryCount:0,error:''};
render();
try{const config=validateConfig(await requestJson(origin+'/api/video/config',{},8000,expectedGeneration));
if(expectedGeneration!==generation)return;
populateStreams(config.streams,requestedStream);
const streamId=requestedStream||streamSelect.value;
if(!config.streams.includes(streamId))throw failure('選択したUnity streamは映像サービスにありません。',{retryable:false});
retryIntent={endpoint:origin,streamId};
current.streamId=streamId;
current.connection='signalling';
render();
if(typeof RTCPeerConnection!=='function')throw failure('このブラウザはWebRTC映像受信に対応していません。',{retryable:false});
const pc=new RTCPeerConnection({iceServers:config.iceServers});
peer=pc;
pc.addTransceiver('video',{direction:'recvonly'});
pc.ontrack=event=>{if(expectedGeneration!==generation||peer!==pc)return;
video.srcObject=event.streams[0]||new MediaStream([event.track]);
void video.play().catch(()=>{});
observeFrames(expectedGeneration,pc);
};
pc.onconnectionstatechange=()=>{if(expectedGeneration!==generation||peer!==pc)return;
if(pc.connectionState==='connected'){current.peerConnected=true;
firstFrameDueAt=now()+staleAfterMs();
peerConnectTimer=cancelTimer(peerConnectTimer);
startStats(expectedGeneration,pc);
render();
return;
}if(['failed','disconnected','closed'].includes(pc.connectionState))scheduleReconnect('WebRTC映像接続が切れました。');
};
await pc.setLocalDescription(await pc.createOffer());
const offer=await waitForIceComplete(pc,expectedGeneration),answer=await requestJson(origin+'/api/video/streams/'+encodeURIComponent(streamId)+'/offer',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:offer.type,sdp:offer.sdp})},25000,expectedGeneration);
if(answer.type!=='answer'||!nonEmpty(answer.sdp)||!nonEmpty(answer.sessionId))throw failure('映像サービスのanswerが不正です。');
if(expectedGeneration!==generation||peer!==pc){void deleteSession(answer.sessionId,origin);
return;
}sessionId=answer.sessionId;
signallingIdentity=normalizeIdentity(answer.source?.brainIdentity);
signallingBindingAvailable=!!answer.source&&Object.hasOwn(answer.source,'brainIdentity');
lastPublisherId=nonEmpty(answer.publisherId)?answer.publisherId:null;
await pc.setRemoteDescription({type:'answer',sdp:answer.sdp});
if(expectedGeneration!==generation||peer!==pc){
void deleteSession(answer.sessionId,origin);
return;
}current.connection='connected';
current.peerConnected=pc.connectionState==='connected';
firstFrameDueAt=now()+staleAfterMs();
render();
if(current.peerConnected)startStats(expectedGeneration,pc);
else peerConnectTimer=setTimeout(()=>{if(expectedGeneration===generation&&peer===pc&&pc.connectionState!=='connected')scheduleReconnect('WebRTC映像接続が確立しませんでした。');
},15000);
void pollStatus(expectedGeneration);
const timer=setInterval(()=>{if(expectedGeneration!==generation){clearInterval(timer);
if(freshnessTimer===timer)freshnessTimer=null;
return;
}if(current.peerConnected&&current.streamState==='live'&&((lastPresentedAt>0&&!frameFresh())||(lastPresentedAt===0&&now()>=firstFrameDueAt)||currentFrameAge()>staleAfterMs()))scheduleReconnect('映像の新しいフレームを確認できません。');
else{render();
maybeProbe(expectedGeneration);
}},200);
freshnessTimer=timer;
}catch(cause){if(expectedGeneration===generation){if(cause?.retryable===false){teardown({preserveIntent:true});
retryIntent=null;
current.connection='error';
current.streamState='stale';
current.error=cause.message;
render();
}else scheduleReconnect(cause?.message||'映像を接続できませんでした。');
}} }
  function setExpectedIdentity(value) { if(value==null){expectedIdentity=null;
expectedIdentityAt=0;
expectedFrames=[];
render();
return;
}if(typeof value!=='object'||Array.isArray(value)||!nonEmpty(value.instanceId)||!nonEmpty(value.sessionId)){expectedIdentity=null;expectedIdentityAt=0;expectedFrames=[];render();return;}
if(!sameBinding(expectedIdentity,value))expectedFrames=[];
expectedIdentity=freeze({instanceId:value.instanceId,sessionId:value.sessionId,backendId:nonEmpty(value.backendId)?value.backendId:null,datasetId:nonEmpty(value.datasetId)?value.datasetId:null,configHash:nonEmpty(value.configHash)?value.configHash:null,graphHash:nonEmpty(value.graphHash)?value.graphHash:null,sourceHash:nonEmpty(value.sourceHash)?value.sourceHash:null,brainConnected:value.brainConnected===true,frameAgeMs:finite(value.frameAgeMs)?Math.max(0,value.frameAgeMs):null,frameSequence:Number.isSafeInteger(value.frameSequence)&&value.frameSequence>=0?value.frameSequence:null});
expectedIdentityAt=now();
expectedFrames=expectedFrames.filter(frame=>expectedIdentityAt-frame.receivedAt<=BRAIN_STALE_MS);
if(expectedIdentity.brainConnected&&finite(expectedIdentity.frameAgeMs)&&expectedIdentity.frameAgeMs<=BRAIN_STALE_MS&&Number.isSafeInteger(expectedIdentity.frameSequence)){
const receivedAt=expectedIdentityAt-expectedIdentity.frameAgeMs;
const existing=expectedFrames.find(frame=>frame.sequence===expectedIdentity.frameSequence);
if(existing)existing.receivedAt=Math.min(existing.receivedAt,receivedAt);
else expectedFrames.push({sequence:expectedIdentity.frameSequence,receivedAt});
if(expectedFrames.length>128)expectedFrames.shift();
}
render();
 }
  form.onsubmit=event=>{event.preventDefault();
void connect(false);
};
disconnectButton.onclick=disconnect;
streamSelect.onchange=()=>{if(peer){current.error='streamの選択を変更しました。反映するには「映像を接続」を押してください。';
render();
}};
window.addEventListener('pagehide',disconnect,{once:true});
window.FlyVideo=Object.freeze({state,measurements,setExpectedIdentity,disconnect});
render();

})();
