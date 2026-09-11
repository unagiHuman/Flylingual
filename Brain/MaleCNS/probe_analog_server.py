"""Local TCP wire/E2E validation; does not claim Windows Unity execution."""
import asyncio
import json
import math
import signal
import socket
import subprocess
import sys
import time
import numpy as np
import psutil
from analog_controller import ROOT,ACTIONS


def stats(values):
    return {'count':len(values),'min':min(values),'mean':float(np.mean(values)),
            'median':float(np.median(values)),'p95':float(np.percentile(values,95)),'max':max(values)}


async def main():
    folder=ROOT/'Docs/mac/checkpoints/temporal'; samples=[]; arrivals=[]; all_frames=[]
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1',0)); port=temporary.getsockname()[1]
    log=(folder/'server.log').open('w')
    proc=subprocess.Popen([sys.executable,str(ROOT/'Brain/MaleCNS/brain_server_analog.py'),'--port',str(port)],stdout=log,stderr=subprocess.STDOUT)
    writer=None
    try:
        for _ in range(150):
            if proc.poll() is not None: raise RuntimeError('Server exited; see server.log')
            try: reader,writer=await asyncio.open_connection('127.0.0.1',port); break
            except OSError: await asyncio.sleep(.1)
        else: raise TimeoutError('Server startup')
        async def read_until(predicate):
            while True:
                line=await asyncio.wait_for(reader.readline(),10)
                if not line: raise ConnectionError('Unexpected EOF')
                m=json.loads(line)
                if m.get('type')=='brain_frame':
                    all_frames.append(m); arrivals.append(time.perf_counter())
                    for key in ('sequence','requestedAction','brainTimeMs','motor','brain','performance'): assert key in m
                    assert isinstance(m['sequence'],int) and m['requestedAction'] in ACTIONS
                    assert math.isfinite(m['brainTimeMs'])
                    assert 0<=m['motor']['forward']<=1 and -1<=m['motor']['turn']<=1
                    for key in ('DNp09_Hz','DNa02_R_Hz','DNa02_L_Hz','DNa02Difference_Hz'): assert math.isfinite(m['brain'][key])
                    assert m['metadata']['ready'] is False
                    assert m['diagnostics']['networkRebuildCount']==1 and m['diagnostics']['stateResetCount']==0
                if predicate(m): return m
                if m.get('type')=='error': raise RuntimeError('Unexpected server error: '+str(m))
        status=await read_until(lambda m:m.get('type')=='status')
        # Keep one controlling connection. A second must be rejected.
        rr,ww=await asyncio.open_connection('127.0.0.1',port)
        rejection=json.loads(await asyncio.wait_for(rr.readline(),5)); assert rejection['error']=='controller_already_connected'
        ww.close(); await ww.wait_closed()
        expected_errors=[]
        for data in ('not-json\n',json.dumps({'type':'set_action','requestId':-1,'action':'UNKNOWN'})+'\n'):
            writer.write(data.encode()); await writer.drain()
            expected_errors.append(await read_until(lambda m:m.get('type')=='error'))
        for i in range(30):
            action=list(ACTIONS)[i%6]; started=time.perf_counter()
            writer.write((json.dumps({'type':'set_action','requestId':i+1,'action':action,'clientTimeMs':started*1000})+'\n').encode()); await writer.drain()
            f=await read_until(lambda m:m.get('type')=='brain_frame' and m.get('appliedRequestId')==i+1)
            assert f['requestedAction']==action
            samples.append({'requestId':i+1,'action':action,'e2eMs':(time.perf_counter()-started)*1000,'frame':f})
        # Burst while the single owner computes: pending commands are overwritten.
        burst=''.join(json.dumps({'type':'set_action','requestId':1000+i,'action':list(ACTIONS)[i%6]})+'\n' for i in range(20))
        writer.write(burst.encode()); await writer.drain()
        last=await read_until(lambda m:m.get('type')=='brain_frame' and m.get('appliedRequestId')==1019)
        assert last['diagnostics']['supersededCommandCount']>0
        gaps=np.diff(arrivals).tolist(); before_seq=last['sequence']
        writer.close(); await writer.wait_closed(); writer=None
        await asyncio.sleep(.2)
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        reconnect=await read_until(lambda m:m.get('type')=='status')
        stopped=await read_until(lambda m:m.get('type')=='brain_frame' and m.get('requestedAction')=='STOP')
        assert stopped['sequence']>before_seq and reconnect['networkRebuildCount']==1
        sequences=[f['sequence'] for f in all_frames]; assert all(b>a for a,b in zip(sequences,sequences[1:]))
        report={'passed':True,'ready':False,'port':port,'status':status,'samples':samples,
            'e2eMs':stats([s['e2eMs'] for s in samples]),
            'brainStepMs':stats([s['frame']['performance']['stepWallTimeMs'] for s in samples]),
            'frameInterarrivalMs':stats([g*1000 for g in gaps]),'staleThresholdMs':750,
            'observedStaleGaps':sum(g>.75 for g in gaps),'expectedErrors':expected_errors,'unexpectedErrors':0,
            'singleControllerRejection':rejection,'latestWins':last['diagnostics'],
            'reconnectPreservedSequence':True,'disconnectRequestedStop':True,
            'rssBytes':psutil.Process(proc.pid).memory_info().rss,
            'protocolCheck':'Python schema checked against current BrainProtocol.cs; actual Windows JsonUtility/Unity not run',
            'limitation':'30 rapidly switched request E2Es measure transport, not settled 400ms action correctness. Stale checks are interarrival gaps, not Unity runtime.'}
        (folder/'server_e2e.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('passed','e2eMs','brainStepMs','observedStaleGaps','rssBytes')}),flush=True)
    finally:
        if writer: writer.close(); await writer.wait_closed()
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try: await asyncio.to_thread(proc.wait,10)
            except subprocess.TimeoutExpired: proc.terminate(); await asyncio.to_thread(proc.wait,5)
        log.close()


if __name__=='__main__': asyncio.run(main())
