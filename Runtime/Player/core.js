/* Browser-only state and Bridge v1 validation. No neural model or motor decoder. */
(() => {
  'use strict';
  const ACTIONS = Object.freeze({FORWARD_L:'左前に進んで',FORWARD:'前に進んで',FORWARD_R:'右前に進んで',TURN_L:'左に曲がって',STOP:'止まって',TURN_R:'右に曲がって'});
  const PHRASES = Object.freeze({'前へ':'FORWARD','前に進んで':'FORWARD','止まって':'STOP','停止':'STOP','右に曲がって':'TURN_R','左に曲がって':'TURN_L','右前に進んで':'FORWARD_R','左前に進んで':'FORWARD_L'});
  const REASONS = Object.freeze({explicit_resume_required:'再開操作を待っています',owner_changed:'操作方法が変わりました',emergency_stop:'緊急停止中',stale_brain:'脳の観測が古くなりました',command_expired:'操作の有効期限が切れました',control_client_disconnected:'制御接続が切れました',conversation_disconnected:'会話接続が切れました',conversation_stopped:'会話を終了しました',brain_disconnected:'脳サーバーが未接続です',fresh_brain_required:'新しい脳の観測が必要です',fresh_stopped_brain_required:'停止状態の新しい観測を待っています',not_control_owner:'操作方法を確認してください',output_inhibited:'出力停止中です。操作を再開してください',old_epoch:'接続状態が更新されました。もう一度入力してください',old_control_epoch:'操作の世代が変わりました',conversation_not_started:'先に会話を開始してください',conversation_disabled:'Bridgeの会話機能がオフです',conversation_not_connected:'会話サービスに接続していません',api_key_missing:'Bridge側でAPIキーを設定してください',live_connect_failed:'会話サービスに接続できませんでした',release_unknown:'旧接続の解放が未確認です',switch_unavailable:'接続先を変更できません',manual_tcp_has_input_slot:'別のクライアントが手動操作中です',observer_cannot_control:'観察モードでは操作できません',invalid_text:'1〜2000文字で入力してください',duplicate_command:'この操作はすでに受け付けています',intent_service_failed:'会話の処理が中断されました',client_stale:'観測が途切れたため停止しています',client_pending:'Bridgeの確認を待っています',transport_closed:'Bridgeとの接続が切れました'});
  const reason = value => REASONS[value] || (value ? String(value) : '—');
  const SETTINGS_REASONS=Object.freeze({stale_settings_revision:'設定が別の操作で更新されています。「設定を読み込む」で確認し直してください。',conversation_settings_require_stopped:'会話の終了と出力停止を確認してから適用してください。',invalid_conversation_settings:'会話設定の形式を確認してください。',invalid_language:'対応する会話言語を選んでください。',invalid_voice:'サーバーが対応する声を選んでください。',invalid_persona:'対応する話し方を選んでください。',invalid_persona_text:'話し方の説明を確認してください。',persona_text_too_long:'話し方の説明は800文字以内にしてください。',persona_text_has_control_character:'話し方の説明に使用できない制御文字があります。',custom_persona_text_required:'カスタムの話し方を入力してください。',duplicate_settings_request:'この設定要求は適用済みです。現在の設定を読み込んでください。'});
  const settingsReason=value=>SETTINGS_REASONS[value]||reason(value);
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  function initial(mode='demo') {
    return {mode,transport:'disconnected',epoch:0,owner:'observer',outputInhibited:true,localInhibited:true,reason:'explicit_resume_required',brainConnected:false,brainReady:false,conversationState:'off',conversationMode:'off',voiceControlAvailable:false,brainMode:'UNKNOWN',frame:null,frameAt:null,serverAge:null,serverAgeAt:null,lastSequence:-1,sessionId:null,instanceId:null,summary:null,releaseUnknown:false,switching:false,stopRequestId:null,stopApplied:false,conversationSettings:null,conversationSettingsRevision:null};
  }
  function clearObservation(s, newSession=false) {
    s.frame=null; s.frameAt=null; s.summary=null; s.serverAge=null; s.serverAgeAt=null;
    if (newSession) s.lastSequence=-1;
  }
  function age(s, now=performance.now()) {
    if (!s.frame || s.frameAt===null) return null;
    return Math.max(0,now-s.frameAt,s.serverAge===null?0:s.serverAge+now-s.serverAgeAt);
  }
  function fresh(s, now) { const ms=age(s,now); return s.transport==='connected' && s.brainConnected && ms!==null && ms<=750; }
  function controls(s, now) { return fresh(s,now) && !s.outputInhibited && !s.localInhibited && !s.switching && !s.releaseUnknown; }
  function bridgeState(s, msg, now=performance.now()) {
    if (!Number.isSafeInteger(msg.epoch) || msg.epoch<0 || !['manual','gpt','observer'].includes(msg.owner) || typeof msg.outputInhibited!=='boolean') return {accepted:false};
    if (msg.epoch<s.epoch) return {accepted:false};
    const sessionChanged=s.sessionId!==msg.sessionId || s.instanceId!==msg.instanceId;
    const changed=sessionChanged || s.epoch!==msg.epoch;
    if (changed) { clearObservation(s,sessionChanged); s.stopRequestId=null; s.stopApplied=false; }
    for (const key of ['epoch','owner','reason','profile','target','backend','dataset','configHash','graphHash','sourceHash','sessionId','instanceId','executionOS','activeControllerCount','conversationMode','conversationState']) if (Object.hasOwn(msg,key)) s[key]=msg[key];
    s.outputInhibited=msg.outputInhibited;
    s.conversationSettings=conversationSettings(msg.conversationSettings);
    s.conversationSettingsRevision=Number.isSafeInteger(msg.conversationSettingsRevision)&&msg.conversationSettingsRevision>=0?msg.conversationSettingsRevision:null;
    for(const key of ['brainConnected','brainReady','switching','releaseUnknown','voiceControlAvailable']) s[key]=msg[key]===true;
    s.brainMode=['LIVE','MOCK','REPLAY'].includes(msg.brainMode)?msg.brainMode:'UNKNOWN';
    s.serverAge=finite(msg.frameAgeMs)?Math.max(0,msg.frameAgeMs):null; s.serverAgeAt=now;
    if (!s.brainConnected) clearObservation(s);
    // A heartbeat cannot release the client's own stop latch. Only a pending
    // explicit resume followed by a current, uninhibited server state can.
    if (s.outputInhibited || changed) s.localInhibited=true;
    if (s.resumePending && !changed && !s.outputInhibited && fresh(s,now)) { s.localInhibited=false; s.resumePending=false; }
    if (changed) s.resumePending=false;
    return {accepted:true,changed};
  }
  function brainFrame(s,msg,now=performance.now()) {
    if(!s.brainConnected || !s.sessionId || !s.instanceId || !Number.isSafeInteger(msg.sequence) || msg.sequence<=s.lastSequence || !finite(msg.motor?.forward) || !finite(msg.motor?.turn)) return false;
    if(msg.metadata?.sessionId!==s.sessionId || msg.metadata?.instanceId!==s.instanceId) return false;
    s.frame=msg; s.frameAt=now; s.lastSequence=msg.sequence;
    if(s.stopRequestId!==null && msg.appliedRequestId===s.stopRequestId) s.stopApplied=true;
    return true;
  }
  function commandResult(s,msg) {
    if(msg.epoch!=null && msg.epoch!==s.epoch) return;
    if(msg.stage==='submitted' && msg.action==='STOP' && msg.epoch===s.epoch && Number.isSafeInteger(msg.requestId)) {
      s.stopRequestId=msg.requestId; s.stopApplied=s.frame?.appliedRequestId===msg.requestId;
    }
    // Older Bridges omit epoch on applied events; match only the STOP request
    // that was submitted in the current epoch, never a generic acceptance ack.
    if(msg.stage==='brain_applied' && msg.action==='STOP' && s.stopRequestId!==null && msg.requestId===s.stopRequestId) s.stopApplied=true;
  }
  function stopped(s,now) {
    return s.stopApplied && fresh(s,now) && Math.abs(s.frame.motor.forward)<=.02 && Math.abs(s.frame.motor.turn)<=.02;
  }
  function conversationSettings(value) {
    if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==4) return null;
    if(!['ja','en'].includes(value.language)||!['friendly','curious','calm','custom'].includes(value.persona)||typeof value.voice!=='string'||!value.voice||value.voice.length>80||typeof value.personaText!=='string'||Array.from(value.personaText).length>800) return null;
    return {language:value.language,voice:value.voice,persona:value.persona,personaText:value.personaText};
  }
  function endpoint(raw, pageHref) {
    const url=new URL(raw), page=new URL(pageHref);
    if(!['ws:','wss:'].includes(url.protocol) || url.username || url.password || url.hash || url.search || url.pathname!=='/ws') throw new Error('接続先は ws://localhost:ポート/ws の形式で入力してください。');
    if(!['localhost','127.0.0.1','[::1]'].includes(url.hostname)) throw new Error('ローカルBridgeのアドレスを指定してください。遠隔BrainはBridgeのトンネル設定で選びます。');
    if(page.protocol!=='http:' && page.protocol!=='https:') throw new Error('実接続には、Bridgeから配信された画面を開いてください。ファイルを直接開いた状態ではデモが使えます。');
    if((url.protocol==='ws:'?'http:':'https:')!==page.protocol || url.host!==page.host) throw new Error('実接続には、このHTMLをBridgeと同じオリジンで配信する必要があります。現在はデモ用の画面です。');
    return url.href;
  }
  function id() {
    if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
    const bytes=new Uint8Array(16); crypto.getRandomValues(bytes);
    return 'ui-'+Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
  }
  globalThis.FlyCore=Object.freeze({ACTIONS,PHRASES,reason,settingsReason,finite,initial,clearObservation,age,fresh,controls,bridgeState,brainFrame,commandResult,stopped,conversationSettings,endpoint,id});
})();
