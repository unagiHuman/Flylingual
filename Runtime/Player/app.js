/* Voice-first player. Video is an independent receiver owned by video.js. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), C=FlyCore;
  const paths={settings:'<path d="m9 3-1 3-3 1-2 3 2 2-1 3 3 3 3-1 2 2 3-2 1-3 3-1 1-3-2-2 1-3-3-2-3 1-2-2Z"/><circle cx="12" cy="12" r="3"/>',video:'<rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 10 5-3v10l-5-3"/>',play:'<path d="m8 5 11 7-11 7Z"/>',expand:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',sparkles:'<path d="m10 4 2 6 6 2-6 2-2 6-2-6-6-2 6-2Zm8-3v5m-2-2h5"/>',mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',stop:'<rect x="6" y="6" width="12" height="12" rx="2"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>'};
  document.querySelectorAll('[data-icon]').forEach(el=>{el.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[el.dataset.icon]||paths.mic)+'</svg>';});
  let state=C.initial('bridge'), socket=null, socketGeneration=0, flowGeneration=0, phase='idle', stageText='', firstState=false, everConnected=false, toastTimer=null, lastReply='', lastReplyAt=0, lastSummaryAt=0, lastReceivedRole=null, speechEpoch=null, lastMood='curious', serviceError=null;
  let settingsUI=null, settingsBusy=false, pendingSettings=null, conversationOffSequence=0;
  const waiters=new Set(), busy=()=>['connecting','preparing','microphone'].includes(phase);
  const captureAllowed=()=>state.transport==='connected' && state.conversationState==='live' && state.voiceControlAvailable && state.owner==='gpt' && C.controls(state);
  const playbackAllowed=()=>state.transport==='connected' && state.conversationState==='live' && !state.switching && !state.releaseUnknown;
  const audio=new FlyAudio(data=>send({...data,controlEpoch:state.epoch}),captureAllowed,playbackAllowed,(message)=>{if(message)toast(message);renderVoice();});
  function text(id,value){const el=$(id),next=String(value??'—');if(el.textContent!==next)el.textContent=next;}
  function toast(message){text('toast',message);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,7000);}
  function log(message){text('last-event',new Date().toLocaleTimeString('ja-JP')+' '+message);}
  function checkWaiters(){for(const check of Array.from(waiters))check();}
  function waitFor(predicate,token,timeout,label){
    return new Promise((resolve,reject)=>{
      let timer;
      const done=(error)=>{clearTimeout(timer);waiters.delete(check);error?reject(error):resolve();};
      const check=()=>{if(token!==flowGeneration)return done(new Error('cancelled'));if(serviceError)return done(new Error(serviceError));if(predicate())done();};
      timer=setTimeout(()=>done(new Error(label+'を確認できませんでした。'+(settingsBusy?'現在の設定を読み込んで確認してください。':'もう一度「話しかける」を押してください。'))),timeout);waiters.add(check);check();
    });
  }
  function send(data){
    if(!socket || socket.readyState!==WebSocket.OPEN){log('transport_send_unavailable');return false;}
    if(socket.bufferedAmount>128*1024){disconnect('音声の送信が遅れたため停止しました。');return false;}
    try{socket.send(JSON.stringify(data));return true;}catch(error){log('transport_send_failed '+String(error?.name||'Error'));disconnect('Bridgeへの送信が中断されました。');return false;}
  }
  function requireSend(data){if(!send(data))throw new Error('Bridgeとの接続を確認してください。');}
  function clearSpeech(){lastReply='';lastReplyAt=0;lastSummaryAt=0;lastReceivedRole=null;speechEpoch=null;}
  function stopVoice(reason='会話を終了しました。',emergency=true){
    ++flowGeneration;phase='stopped';stageText=reason;state.localInhibited=true;state.resumePending=false;audio.dispose();clearSpeech();
    if(emergency)send({type:'emergency_stop'});
    // Queue stop even when a previously requested start has not announced live yet.
    send({type:'conversation_stop'});
    checkWaiters();render();
  }
  function disconnect(reason='会話の接続を終了しました。'){
    ++socketGeneration;const old=socket;socket=null;
    // Detach first: a saturated socket must not recurse through stop -> send.
    stopVoice(reason);if(old){old.onmessage=old.onopen=old.onclose=old.onerror=null;old.close();}
    state=C.initial('bridge');firstState=false;settingsUI?.disconnect();checkWaiters();render();
  }
  async function connectBridge(url,token){
    if(token!==flowGeneration)throw new Error('cancelled');
    if(state.transport==='connected' && firstState && socket?.url===url)return;
    if(socket){const old=socket;socket=null;old.onmessage=old.onopen=old.onclose=old.onerror=null;old.close();}
    settingsUI?.disconnect();const generation=++socketGeneration;state=C.initial('bridge');state.transport='connecting';firstState=false;const ws=new WebSocket(url);socket=ws;render();
    ws.onopen=()=>{if(generation!==socketGeneration)return;state.transport='connected';render();};
    ws.onmessage=event=>{if(generation!==socketGeneration || typeof event.data!=='string')return;if(event.data.length>2*1024*1024){log('message_too_large');return;}try{receive(JSON.parse(event.data));}catch{log('invalid_message');}};
    ws.onerror=()=>{if(generation===socketGeneration)log('transport_error');};
    ws.onclose=event=>{if(generation!==socketGeneration)return;socket=null;state.transport='disconnected';state.brainConnected=false;state.brainReady=false;state.outputInhibited=true;state.localInhibited=true;C.clearObservation(state,true);settingsUI?.disconnect();stopVoice('接続が切れました。もう一度「話しかける」で接続します。',false);log('transport_closed '+event.code+' clean='+event.wasClean+(event.reason?' / '+event.reason.slice(0,160):''));};
    await waitFor(()=>state.transport==='connected'&&firstState,token,9000,'Bridge接続');
  }
  async function startVoice(){
    if(busy()||settingsBusy)return;
    const token=++flowGeneration;serviceError=null;phase='connecting';stageText='声の接続を準備しています…';render();
    // The user's explicit button press enables reply audio without requiring a mic first.
    try{
      const url=C.endpoint($('bridge-url').value.trim(),location.href);await audio.contextReady();
      await connectBridge(url,token);
      if(state.conversationMode!=='live')throw new Error('Bridgeの会話モードをliveに設定してください。この画面の操作は音声のみです。');
      phase='preparing';stageText='ハエとの会話を準備しています…';render();
      const profile=$('profile-select').value;
      if(state.profile!==profile){state.localInhibited=true;requireSend({type:'switch_target',profile});await waitFor(()=>state.profile===profile&&!state.switching&&state.brainConnected,token,25000,'接続先');}
      if(state.releaseUnknown)throw new Error('旧接続の解放が未確認です。Bridge側の状態を確認してください。');
      if(state.conversationState!=='off'){
        requireSend({type:'conversation_stop'});await waitFor(()=>state.conversationState==='off',token,12000,'会話の終了');
      }
      const previousEpoch=state.epoch;state.localInhibited=true;
      requireSend({type:'set_owner',owner:'gpt'});
      await waitFor(()=>state.owner==='gpt'&&state.epoch>previousEpoch&&state.outputInhibited,token,10000,'音声の操作権');
      stageText='ハエの停止確認を待っています…';render();
      await waitFor(()=>C.stopped(state),token,15000,'現在の停止要求の適用と新しい観測');
      stageText='ハエとの会話を準備しています…';render();
      requireSend({type:'conversation_start'});
      await waitFor(()=>state.conversationState==='live'&&state.voiceControlAvailable,token,35000,'会話サービス');
      const conversationEpoch=state.epoch;
      await waitFor(()=>C.stopped(state),token,15000,'ハエの停止状態');
      if(state.epoch!==conversationEpoch || !state.voiceControlAvailable)throw new Error('接続状態が変わりました。もう一度「話しかける」で音声を開始してください。');
      state.resumePending=true;requireSend({type:'resume'});
      await waitFor(()=>C.controls(state)&&state.voiceControlAvailable,token,8000,'操作の再開');
      phase='microphone';stageText='マイクを準備しています。利用を許可してください。';render();
      await audio.start();
      if(token!==flowGeneration)return;
      if(!audio.active || !captureAllowed())throw new Error('マイクを開始できませんでした。マイクの許可と接続状態を確認してください。');
      phase='listening';stageText='声を聞いています。自然に話しかけてください。';render();
    }catch(error){
      if(token!==flowGeneration)return;
      stopVoice(error.message);toast(error.message);
      if(state.transport!=='connected'){if(!$('settings-dialog').open)$('settings-dialog').showModal();text('settings-error',error.message);}
    }
  }
  async function connectSettings(){
    if(busy())throw new Error('音声の準備が終わるか、中止してから設定を読み込んでください。');
    const url=C.endpoint($('bridge-url').value.trim(),location.href);
    if(phase==='listening'&&socket?.url!==url)throw new Error('接続先を変える前に会話を終了してください。');
    serviceError=null;
    await connectBridge(url,flowGeneration);
  }
  async function applySettings({settings,expectedRevision}){
    if(busy())throw new Error('音声の準備を中止してから設定を適用してください。');
    if(state.transport!=='connected'||socket?.url!==C.endpoint($('bridge-url').value.trim(),location.href))throw new Error('接続先の設定を読み込み直してください。');
    if(!state.conversationSettings||state.conversationSettingsRevision===null)throw new Error('このBridgeは会話設定に対応していません。');
    if(expectedRevision!==state.conversationSettingsRevision)throw new Error(C.settingsReason('stale_settings_revision'));
    const requested=C.conversationSettings(settings);if(!requested)throw new Error(C.settingsReason('invalid_conversation_settings'));
    requested.personaText=requested.personaText.trim();
    const oldOffSequence=conversationOffSequence;
    serviceError=null;stopVoice('設定を適用するため、会話を終了しています…');
    const token=flowGeneration;
    try{
      // Wait for the stop operation's off event, not an earlier heartbeat that
      // happened to say off while the queued stop was still changing epochs.
      await waitFor(()=>conversationOffSequence>oldOffSequence&&state.transport==='connected'&&state.conversationState==='off'&&state.outputInhibited&&!state.switching&&!state.releaseUnknown,token,22000,'会話の終了と出力停止');
      const requestId=C.id();pendingSettings={requestId,reply:null};
      requireSend({type:'configure_conversation',requestId,controlEpoch:state.epoch,expectedRevision,settings:requested});
      await waitFor(()=>pendingSettings?.reply,token,10000,'設定の適用結果');
      const reply=pendingSettings.reply,confirmed=C.conversationSettings(reply.settings);
      if(reply.requiresExplicitStart!==true||reply.revision!==expectedRevision+1||!confirmed||state.conversationSettingsRevision!==reply.revision||JSON.stringify(confirmed)!==JSON.stringify(requested)||JSON.stringify(confirmed)!==JSON.stringify(state.conversationSettings))throw new Error('設定の適用結果が一致しません。現在の設定を読み込んで確認してください。');
      stageText='設定を適用しました。次の「話しかける」で使います。';render();return reply;
    }catch(error){if(token===flowGeneration){stageText=error.message;render();}throw error.message==='cancelled'?new Error(stageText||'設定の適用を中止しました。'):error;}
    finally{pendingSettings=null;}
  }
  function receive(msg){
    if(!msg || typeof msg.type!=='string'){log('unknown_message');return;}
    if(msg.type==='bridge_state'){
      const result=C.bridgeState(state,msg);if(!result.accepted){log('invalid_bridge_state');return;}
      firstState=true;everConnected=true;
      settingsUI?.receive(msg);
      if(result.changed){audio.stop();clearSpeech();}
      if(!playbackAllowed()&&audio.playback.size)audio.stopPlayback();
      if(!captureAllowed()&&(audio.active||audio.starting))audio.stopMic();
      if(phase==='listening'&&!captureAllowed())stopVoice('接続または観測が変わったため停止しました。「話しかける」で再開できます。');
      checkWaiters();render();return;
    }
    if(msg.type==='brain_frame'){if(C.brainFrame(state,msg)){checkWaiters();render();}return;}
    if(msg.type==='brain_summary'){
      if(msg.summary && typeof msg.summary.interpretation==='string' && (msg.summary.stale===true || msg.summary.sequence===state.frame?.sequence)){state.summary=msg.summary;lastSummaryAt=performance.now();renderMood();}return;
    }
    if(msg.type==='conversation_state'){
      if(msg.state==='off')++conversationOffSequence;
      state.conversationState=typeof msg.state==='string'?msg.state:'off';if(state.conversationState!=='live')audio.stop();
      if(phase==='listening'&&state.conversationState!=='live')stopVoice('会話が終了しました。もう一度「話しかける」で再開できます。');checkWaiters();render();return;
    }
    if(msg.type==='conversation_text'){
      if(typeof msg.text!=='string'||state.conversationState!=='live'||!['assistant','user'].includes(msg.role))return;
      if(msg.role==='assistant'){
        if(msg.append!==true||lastReceivedRole!=='assistant'||speechEpoch!==state.epoch)lastReply='';
        lastReply=(lastReply+msg.text).slice(-1000);lastReplyAt=performance.now();speechEpoch=state.epoch;
      }
      lastReceivedRole=msg.role;renderMood();return;
    }
    if(msg.type==='audio'){void audio.play(msg.audio);return;}
    if(msg.type==='discard_audio'){
      audio.stop();clearSpeech();C.clearObservation(state);state.localInhibited=true;state.resumePending=false;
      if(phase==='listening')stopVoice('音声を停止しました。「話しかける」で新しく会話を始められます。');checkWaiters();render();return;
    }
    if(msg.type==='error'){
      if(msg.requestId!=null){if(pendingSettings?.requestId===msg.requestId){serviceError=C.settingsReason(msg.error);checkWaiters();}return;}
      const explanation=C.reason(msg.error||'接続エラー');log(explanation);if(busy()||settingsBusy)serviceError=explanation;else toast(explanation);checkWaiters();render();return;
    }
    if(msg.type==='conversation_options'){settingsUI?.receive(msg);return;}
    if(msg.type==='conversation_settings'){if(pendingSettings?.requestId===msg.requestId){pendingSettings.reply=msg;checkWaiters();}return;}
    if(msg.type==='command_result'){
      if(msg.epoch!=null&&msg.epoch!==state.epoch)return;
      C.commandResult(state,msg);checkWaiters();
      const status={submitted:'音声の指示を送信しました。適用はまだ未確認です。',brain_applied:'Brainに指示が適用されました。身体動作は映像で確認してください。',rejected:'操作は適用されませんでした：'+C.reason(msg.reason)}[msg.stage];
      if(status){log(status);if(msg.stage==='rejected')toast(status);}return;
    }
    log('unknown_message_type: '+msg.type.slice(0,80));
  }
  function renderMood(){
    let mood='curious',title='きみに、きょうみしんしん。',category='HELLO, FRIEND',thought='どんな声で、話してくれるのかな。',evidence='接続前のサンプル表示',source='SAMPLE';
    if(everConnected){
      source=state.brainMode;const fresh=C.fresh(state),frame=state.frame;
      if(!fresh){mood='unknown';title='いまは、わからない。';category='WAITING';thought='新しい様子が届くまで、待っていてね。';evidence='現在の脳の観測なし';}
      else{
        const forward=frame.motor.forward,turn=frame.motor.turn;
        if(Math.abs(turn)>.02){mood='curious';title='あっちが、気になる。';category='CURIOUS';thought=turn>0?'右のほうが、なんだか気になるな。':'左のほうも、ちょっと気になるな。';evidence='旋回の神経出力からのキャラクター表現';}
        else if(forward>.02){mood='exploring';title='ちょっと、たんけん！';category='LET’S EXPLORE';thought='もう少し先に、なにがあるんだろう。';evidence='前進の神経出力からのキャラクター表現';}
        else{mood='resting';title='ここで、ひとやすみ。';category='TAKE IT EASY';thought='のんびり、きみの声を待っているよ。';evidence='運動出力がゼロ付近という観測';}
        if(audio.active&&Math.abs(forward)<=.02&&Math.abs(turn)<=.02){mood='listening';title='うん、きいてるよ。';category='I’M LISTENING';thought='ゆっくりでいいよ。話しかけてみて。';evidence='停止付近の観測＋マイク受付中の表示';}
        if(lastReply&&speechEpoch===state.epoch&&performance.now()-lastReplyAt<20000){thought=lastReply;evidence='会話サービスのキャラクター表現';}
      }
    }
    $('lcd-screen').dataset.mood=mood;$('unknown-symbol').hidden=mood!=='unknown';$('mood-icon').setAttribute('aria-label',title+(source==='SAMPLE'?' 接続前のサンプル':' 観測にもとづくキャラクター表現'));lastMood=mood;
    text('mood-title',title);text('mood-category',category);text('thought-text',thought);text('thought-evidence',evidence);text('feeling-source',source);
  }
  function renderVoice(){
    const listening=phase==='listening'&&audio.active;
    $('voice-button').disabled=settingsBusy;$('voice-confirm').disabled=settingsBusy;
    for(const id of ['bridge-url','profile-select','settings-done'])$(id).disabled=settingsBusy;
    $('voice-button').setAttribute('aria-pressed',String(listening));
    text('voice-button-label',listening?'会話を終了':busy()?'準備を中止':phase==='stopped'?'もう一度話す':'話しかける');
    text('voice-status',stageText||'開始するまでマイクはオフです。');
    $('emergency-button').disabled=state.transport!=='connected';$('bridge-disconnect').disabled=state.transport!=='connected';
    text('session-label',listening?'声でつながっています':busy()?'接続を準備中':state.transport==='connected'?'会話は停止中':'接続前');$('session-label').classList.toggle('active',listening);
  }
  function render(){
    renderVoice();renderMood();const age=C.age(state);
    text('brain-status',state.transport+' / '+String(state.brainConnected));text('brain-ready',everConnected?String(state.brainReady):'未確認');
    text('brain-profile',(state.executionOS||'—')+' / '+(state.profile||'—'));text('brain-backend',(state.backend||'—')+' / '+(state.dataset||'—'));
    text('brain-control',state.owner+' / '+state.epoch+' / 抑止 '+String(state.outputInhibited||state.localInhibited));text('brain-age',age===null?'未観測':Math.round(age)+' ms');
    text('brain-observation',C.fresh(state)&&state.summary&&!state.summary.stale&&performance.now()-lastSummaryAt<5000?state.summary.interpretation:'現在の脳の要約は未確認です。');
    text('brain-identity',JSON.stringify({target:state.target,sessionId:state.sessionId,instanceId:state.instanceId,configHash:state.configHash,graphHash:state.graphHash,sourceHash:state.sourceHash,voiceControlAvailable:state.voiceControlAvailable},null,2));
  }
  function renderVideo(detail){
    const live=detail.live,busyVideo=['connecting','signalling','connected'].includes(detail.connection);
    $('video-placeholder').hidden=live;$('video-dot').classList.toggle('live',live);$('video-live-state').classList.toggle('live',live);$('video-view-button').disabled=busyVideo;
    text('video-view-button',busyVideo?'映像を接続中…':detail.connection==='idle'?'映像をつなぐ':'映像を再接続');
    text('video-placeholder-title',detail.connection==='idle'?'小さな世界を、のぞいてみよう。':detail.connection==='stale'?'映像が途切れました。':detail.connection==='error'?'映像につながりませんでした。':busyVideo?'ハエの世界につないでいます…':'Unityからの映像を待っています。');
    text('video-placeholder-note',detail.error||'Unityの映像をここに映します。');
    text('video-brief',live?(detail.source?.kind==='diagnostic'?'診断用の映像を受信中':detail.sourceLabel+' の映像を受信中'):detail.error?'接続設定を確認して、もう一度お試しください。':'映像の接続を待っています');
  }
  window.addEventListener('flyvideochange',event=>renderVideo(event.detail));if(window.FlyVideo)renderVideo(FlyVideo.state());
  $('video-view-button').onclick=()=>$('video-connect-form').requestSubmit();
  $('video-fullscreen').onclick=()=>{const el=$('unity-video').parentElement.parentElement;if(el.requestFullscreen)el.requestFullscreen().catch(()=>toast('全画面表示を開始できませんでした。'));else if($('unity-video').webkitEnterFullscreen)$('unity-video').webkitEnterFullscreen();};
  $('settings-open').onclick=()=>{text('settings-error','');$('settings-dialog').showModal();};
  $('settings-done').onclick=()=>{
    try{new URL($('bridge-url').value);new URL($('video-endpoint').value);}catch{text('settings-error','接続先のURLを確認してください。');return;}
    if(state.transport==='connected'&&(socket?.url!==$('bridge-url').value.trim()||state.profile!==$('profile-select').value))disconnect('設定を変更しました。「話しかける」で接続します。');
    $('settings-dialog').close();
  };
  $('bridge-disconnect').onclick=()=>disconnect();
  $('voice-button').onclick=()=>{if(busy()||phase==='listening')stopVoice();else $('voice-dialog').showModal();};
  $('voice-cancel').onclick=()=>$('voice-dialog').close();$('voice-confirm').onclick=()=>{$('voice-dialog').close();void startVoice();};
  $('emergency-button').onclick=()=>{stopVoice('緊急停止しました。「話しかける」を押すまで操作を再開しません。');toast('音声を終了し、停止を要求しました。');};
  settingsUI=new FlySettings({connect:connectSettings,apply:applySettings,onBusy(value){settingsBusy=value;renderVoice();},onLanguage(language){$('voice-hint').textContent=language==='en'?'“Go forward”, “Stop”, “How are you feeling?”':'「前に進んで」「止まって」「今どんな気持ち？」';}});
  if(['http:','https:'].includes(location.protocol))$('bridge-url').value=(location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws';
  if(location.port==='4173')$('bridge-url').value='ws://127.0.0.1:8771/ws';
  const watchdog=setInterval(()=>{
    if(phase==='listening'&&(!captureAllowed()||!audio.active))stopVoice('音声または観測が途切れたため停止しました。「話しかける」で再開できます。');
    checkWaiters();render();
  },200);
  window.addEventListener('pagehide',()=>{clearInterval(watchdog);disconnect();},{once:true});
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  const context=document.modelContext,lifecycle=new AbortController();
  if(context?.registerTool){try{Promise.resolve(context.registerTool({name:'fly_read_observation',title:'Read Flylingual observation',description:'Read the current voice, video and illustrated mood state. Does not start a connection or control the fly.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute(input){if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).length)throw new Error('Expected an empty object.');return {voicePhase:phase,micActive:audio.active,conversationState:state.conversationState,conversationSettingsRevision:state.conversationSettingsRevision,conversationPresentation:state.conversationSettings?{language:state.conversationSettings.language,voice:state.conversationSettings.voice,persona:state.conversationSettings.persona}:null,outputInhibited:state.outputInhibited||state.localInhibited,mood:lastMood,moodSource:$('feeling-source').textContent,brainReady:state.brainReady,frameAgeMs:C.age(state),videoLive:window.FlyVideo?.state().live||false,bodyBrainSessionMatched:false};}},{signal:lifecycle.signal})).catch(()=>log('observation_tool_unavailable'));}catch{log('observation_tool_unavailable');}window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});}
  render();
})();
