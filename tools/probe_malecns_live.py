"""Single-session Windows probe, based on mock_malecns_client's NDJSON contract.

No retries or additional TCP probes. Preserve all responses, including transients.
"""
import argparse, asyncio, datetime, json, math, time
from pathlib import Path

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def sign_ok(action, frame):
    f, t = frame['motor']['forward'], frame['motor']['turn']
    if action == 'STOP':
        return abs(f) <= .01 and abs(t) <= .01
    return (f > 0 if 'FORWARD' in action else abs(f) <= .15) and (
        t > 0 if action.endswith('_R') else t < 0 if action.endswith('_L') else abs(t) <= .01)

async def run(args):
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    result=dict(host=args.host,port=args.port,receiveTimeoutSeconds=15,
                connectStartedUtc=utc(),events=[],actions=[],connected=False,disconnect=False)
    writer=None
    def save():
        out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    async def receive():
        line=await asyncio.wait_for(reader.readline(),15)
        if not line: raise RuntimeError('Server closed stream')
        msg=json.loads(line)
        stamp=utc()
        result['events'].append(dict(receivedUtc=stamp,message=msg))
        result.setdefault('firstResponseUtc',stamp)
        if msg.get('type')=='brain_frame':
            result.setdefault('firstBrainFrameUtc',stamp)
            result.setdefault('connectToFirstFrameMs',(time.perf_counter()-connected_at)*1000)
        save()
        if msg.get('type')=='error': raise RuntimeError('Server error: '+json.dumps(msg))
        return msg,stamp
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection(args.host,args.port,limit=4*1024*1024),15)
        connected_at=time.perf_counter()
        result.update(connected=True,connectedUtc=utc())
        print('CONNECTED '+result['connectedUtc'],flush=True);save()
        status,_=await receive()
        if status.get('type')!='status': raise RuntimeError('Expected initial status')
        result['status']=status
        for request_id,action in enumerate(('STOP','FORWARD','TURN_R','TURN_L','FORWARD_R','FORWARD_L','STOP'),1):
            started=time.perf_counter()
            sample=dict(action=action,requestId=request_id,sentUtc=utc(),frames=[])
            result['actions'].append(sample);save()
            command=dict(type='set_action',requestId=request_id,action=action,clientTimeMs=started*1000)
            writer.write((json.dumps(command)+'\n').encode());await writer.drain()
            sample['sendSucceeded']=True;save()
            while len(sample['frames'])<8:
                if time.perf_counter()-started>30: raise TimeoutError('Action observation exceeded 30 seconds: '+action)
                msg,stamp=await receive()
                if msg.get('type')!='brain_frame' or msg.get('requestedAction')!=action: continue
                # First matching frame must acknowledge this request, preventing stale STOP attribution.
                if not sample['frames'] and msg.get('appliedRequestId')!=request_id: continue
                for key in ('forward','turn'):
                    value=msg['motor'][key]
                    if not isinstance(value,(float,int)) or not math.isfinite(value): raise RuntimeError('Invalid motor '+key)
                metadata=msg.get('metadata',{})
                row=dict(receivedUtc=stamp,latencyMs=(time.perf_counter()-started)*1000,
                         sequence=msg['sequence'],requestedAction=msg['requestedAction'],
                         forward=msg['motor']['forward'],turn=msg['motor']['turn'],
                         backend=metadata.get('backendId'),ready=metadata.get('ready'),signPass=sign_ok(action,msg))
                sample['frames'].append(row);save()
            sample['firstFrameLatencyMs']=sample['frames'][0]['latencyMs']
            sample['stableLast4SignPass']=all(r['signPass'] for r in sample['frames'][-4:])
            print(action+' first_ms='+str(round(sample['firstFrameLatencyMs'],2))+' stable_sign='+str(sample['stableLast4SignPass']),flush=True)
            save()
            if request_id==1 and not sample['stableLast4SignPass']: raise RuntimeError('Initial STOP gate failed; no further actions sent')
        sequences=[r['sequence'] for s in result['actions'] for r in s['frames']]
        result['sequenceIncreasing']=all(b>a for a,b in zip(sequences,sequences[1:]))
        result['allActionSignsPass']=all(s['stableLast4SignPass'] for s in result['actions'])
        result['completed']=True
    except Exception as exc:
        result['failure']=type(exc).__name__+': '+str(exc)
        print(result['failure'],flush=True)
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(),15)
                result['disconnect']=True
            except Exception as exc: result['disconnectError']=str(exc)
        result['finishedUtc']=utc();save()
        print('LOG '+str(out),flush=True)
    return 0 if result.get('completed') and result.get('allActionSignsPass') and result['disconnect'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True);parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--output',required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
