/* Optional PCM16 / 24 kHz audio over the local Bridge. Explicit mic opt-in. */
(() => {
  'use strict';
  const workletSource=`class FlyMic extends AudioWorkletProcessor {
    process(inputs) { const channel=inputs[0]?.[0]; if(channel) this.port.postMessage(channel.slice()); return true; }
  } registerProcessor('fly-mic',FlyMic);`;
  class FlyAudio {
    constructor(send,allowed,playbackAllowed,notify) { this.send=send; this.allowed=allowed; this.playbackAllowed=playbackAllowed; this.notify=notify; this.context=null; this.stream=null; this.node=null; this.source=null; this.silent=null; this.active=false; this.starting=false; this.muted=false; this.generation=0; this.playback=new Set(); this.audiblePlayback=new Map(); this.nextTime=0; this.echoUntil=0; this.pending=[]; this.carry=new Float32Array(0); this.position=0; this.resetDiagnostics(); }
    async contextReady() { if(!this.context) this.context=new (window.AudioContext||window.webkitAudioContext)(); await this.context.resume(); return this.context; }
    async start() {
      if(this.active || this.starting || !this.allowed()) return;
      this.resetDiagnostics(); const generation=++this.generation; this.starting=true; this.notify();
      let stream=null;
      try {
        if(!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error('このブラウザでは音声入力を利用できません。マイク対応のブラウザで開いてください。');
        stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false}});
        if(generation!==this.generation || !this.allowed()) { stream.getTracks().forEach(t=>t.stop()); return; }
        const ctx=await this.contextReady();
        const blobUrl=URL.createObjectURL(new Blob([workletSource],{type:'text/javascript'}));
        try { await ctx.audioWorklet.addModule(blobUrl); } finally { URL.revokeObjectURL(blobUrl); }
        if(generation!==this.generation || !this.allowed()) { stream.getTracks().forEach(t=>t.stop()); return; }
        this.stream=stream; this.source=ctx.createMediaStreamSource(stream); this.node=new AudioWorkletNode(ctx,'fly-mic'); this.silent=ctx.createGain(); this.silent.gain.value=0;
        this.node.port.onmessage=event=>{
          this._captureInput(event.data,ctx.sampleRate);
          if(this._suppression(ctx)!=='none') { this.pending=[]; this.carry=new Float32Array(0); this.position=0; return; }
          this.capture(event.data,ctx.sampleRate);
        };
        this.source.connect(this.node); this.node.connect(this.silent); this.silent.connect(ctx.destination); this.active=true;
        for(const track of stream.getTracks()) track.onended=()=>{if(generation!==this.generation)return;this.stop();this.notify('マイク入力が終了しました。');};
      } catch(error) {
        stream?.getTracks().forEach(t=>t.stop());
        if(generation===this.generation) this.stop();
        const messages={
          NotAllowedError:'マイクの利用が許可されませんでした。ブラウザでマイクを許可してから再開してください。',
          NotFoundError:'利用できるマイクが見つかりませんでした。マイクの接続を確認してください。',
          NotReadableError:'マイクを使用できませんでした。他のアプリが使用していないか確認してください。'
        };
        throw new Error(messages[error?.name]||error?.message||'マイク入力を開始できませんでした。');
      } finally { this.starting=false; this.notify(); }
    }
    capture(input,rate) {
      const joined=new Float32Array(this.carry.length+input.length); joined.set(this.carry); joined.set(input,this.carry.length); const step=rate/24000;
      while(this.position+1<joined.length) {
        const index=Math.floor(this.position), fraction=this.position-index;
        this.pending.push(joined[index]*(1-fraction)+joined[index+1]*fraction); this.position+=step;
      }
      const consumed=Math.floor(this.position); this.carry=joined.slice(consumed); this.position-=consumed;
      while(this.pending.length>=2400) {
        const samples=this.pending.splice(0,2400), bytes=new Uint8Array(4800), view=new DataView(bytes.buffer);
        samples.forEach((sample,i)=>{const v=Math.max(-1,Math.min(1,sample));view.setInt16(i*2,Math.round(v*(v<0?32768:32767)),true);});
        if(this.send({type:'audio',audio:btoa(String.fromCharCode(...bytes))})===true){this._sentChunks++;this._sentBytes+=bytes.length;this._lastSentAt=performance.now();}
      }
    }
    resetDiagnostics() { this._meterBlocks=[];this._meterSamples=0;this._meterSquares=0;this._inputRms=0;this._capturedBlocks=0;this._sentChunks=0;this._sentBytes=0;this._lastInputAt=null;this._lastSentAt=null; }
    _captureInput(input,rate) { let squares=0;for(let i=0;i<input.length;i++)squares+=input[i]*input[i];const samples=input.length;this._capturedBlocks++;this._lastInputAt=performance.now();this._meterBlocks.push({samples,squares});this._meterSamples+=samples;this._meterSquares+=squares;const windowSamples=Math.max(1,Math.round(rate*.1));while(this._meterBlocks.length>1&&this._meterSamples-this._meterBlocks[0].samples>=windowSamples){const oldest=this._meterBlocks.shift();this._meterSamples-=oldest.samples;this._meterSquares-=oldest.squares;}this._inputRms=this._meterSamples?Math.sqrt(Math.max(0,this._meterSquares)/this._meterSamples):0; }
    _suppression(ctx=this.context) { if(!this.active)return this.starting?'starting':'off';if(!this.allowed())return 'gate';const now=ctx?.currentTime;if(now!==undefined){for(const window of this.audiblePlayback.values())if(now>=window.start&&now<window.end+.2)return 'playback';if(now<this.echoUntil)return 'playback';}return 'none'; }
    diagnostics() { const now=performance.now(),inputAge=this._lastInputAt===null?null:Math.max(0,now-this._lastInputAt),sentAge=this._lastSentAt===null?null:Math.max(0,now-this._lastSentAt),fresh=this.active&&inputAge!==null&&inputAge<=1000,rms=fresh?Math.max(0,Math.min(1,this._inputRms)):0;return {active:this.active,starting:this.starting,inputLevel:rms,inputDbfs:fresh?20*Math.log10(Math.max(rms,1e-6)):null,capturedBlocks:this._capturedBlocks,sentChunks:this._sentChunks,sentBytes:this._sentBytes,lastInputAgeMs:inputAge,lastSentAgeMs:sentAge,suppression:this._suppression(),trackMuted:this.stream?.getAudioTracks().some(track=>track.muted)===true,contextState:this.context?.state||'none'}; }
    stopPlayback() { for(const node of this.playback){node.onended=null;try{node.stop();node.disconnect();}catch{}}this.playback.clear();this.audiblePlayback.clear();this.nextTime=0;this.echoUntil=(this.context?.currentTime||0)+.2; }
    stopMic() {
      ++this.generation; this.active=false;
      if(this.node){this.node.port.onmessage=null;this.node.disconnect();this.node=null;}
      this.source?.disconnect();this.source=null;this.silent?.disconnect();this.silent=null;
      this.stream?.getTracks().forEach(track=>{track.onended=null;track.stop();});this.stream=null;
      this.pending=[];this.carry=new Float32Array(0);this.position=0;this._meterBlocks=[];this._meterSamples=0;this._meterSquares=0;this._inputRms=0;this.notify();
    }
    stop() { this.stopMic(); this.stopPlayback(); }
    dispose() { this.stop(); const ctx=this.context;this.context=null;ctx?.close().catch(()=>{}); }
    setMuted(muted) {this.muted=muted;if(muted)this.stopPlayback();}
    async play(encoded) {
      if(this.muted || !this.playbackAllowed()) return;
      const generation=this.generation;
      try {
        if(typeof encoded!=='string' || encoded.length>128000) throw new Error('音声データのサイズが不正です。');
        const binary=atob(encoded); if(!binary.length || binary.length%2) throw new Error('音声データの形式が不正です。');
        // Do not start unsolicited audio before the user has activated audio.
        if(!this.context || this.context.state!=='running') return;
        const ctx=this.context, duration=binary.length/2/24000;
        if(Math.max(0,this.nextTime-ctx.currentTime)+duration>5){this.stopPlayback();this.notify('音声が遅れたため再生をリセットしました。');return;}
        if(generation!==this.generation || !this.playbackAllowed()) return;
        const bytes=Uint8Array.from(binary,c=>c.charCodeAt(0)),view=new DataView(bytes.buffer),buffer=ctx.createBuffer(1,bytes.length/2,24000),channel=buffer.getChannelData(0);let audible=false;
        for(let i=0;i<channel.length;i++){const sample=view.getInt16(i*2,true);if(sample!==0)audible=true;channel[i]=sample/32768;}
        const node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);this.playback.add(node);
        const start=Math.max(ctx.currentTime,this.nextTime),end=start+duration;this.nextTime=end;
        if(audible)this.audiblePlayback.set(node,{start,end});
        node.onended=()=>{node.disconnect();this.playback.delete(node);const window=this.audiblePlayback.get(node);if(window){this.audiblePlayback.delete(node);this.echoUntil=Math.max(this.echoUntil,window.end+.2);}};node.start(start);
      } catch { this.notify('返答の音声を再生できませんでした。'); }
    }
  }
  globalThis.FlyAudio=FlyAudio;
})();
