"""Opt-in live production Brain transport checks; owns only its child process."""
import argparse
import asyncio
import json
import hashlib
import math
import platform
from importlib.metadata import version
import numpy as np
import psutil
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from Runtime.Bridge.brain_adapter import BrainAdapter


def sample_owned_rss(root_process, peaks):
    """Sample only the owned process tree; summed RSS can double-count shared pages."""
    try:
        processes=[root_process]+root_process.children(recursive=True)
    except psutil.Error:
        return None
    total=0; observed=0
    for process in processes:
        try:
            with process.oneshot():
                created=process.create_time(); name=process.name(); value=process.memory_info().rss
            key=(process.pid,created)
            row=peaks.setdefault(key,{'pid':process.pid,'name':name,'createdAtUnixSeconds':created,
                                     'sampleCount':0,'maxSampledRssBytes':0})
            row['sampleCount']+=1
            row['maxSampledRssBytes']=max(row['maxSampledRssBytes'],value)
            total+=value; observed+=1
        except psutil.Error:
            continue
    return total if observed else None


async def trial(port, output, report):
    frames=asyncio.Queue(); adapter=None; label='connect'
    sent={}; sequences=[]; step_times=[]; rss=[]; rss_processes={}
    owned_process=psutil.Process(report['ownedChildPid'])
    report['inputE2E']=[]
    with (output/'messages.ndjson').open('w',encoding='utf-8') as log:
        async def received(message):
            log.write(json.dumps({'phase':label,'wallTime':time.time(),'message':message},allow_nan=False)+'\n')
            log.flush()
            if message.get('type') == 'brain_frame':
                sequences.append(message['sequence'])
                elapsed=message.get('performance',{}).get('stepWallTimeMs')
                if isinstance(elapsed,(float,int)) and math.isfinite(elapsed): step_times.append(elapsed)
                sampled_rss=sample_owned_rss(owned_process,rss_processes)
                if sampled_rss is not None: rss.append(sampled_rss)
                sensory=message.get('raw',{}).get('visualThreat',{})
                stamp=sent.pop(sensory.get('requestId'),None) if sensory.get('inputEventCount',0)>0 else None
                if stamp is not None:
                    report['inputE2E'].append({'requestId':sensory['requestId'],'phase':stamp[2],
                                              'sentAtUnixSeconds':stamp[1],'firstInputSequence':message['sequence'],
                                              'milliseconds':(time.monotonic()-stamp[0])*1000})
                frames.put_nowait(message)
            elif message.get('type') == 'error':
                report.setdefault('protocolErrors',[]).append(message)

        async def connect():
            current=BrainAdapter(received,timeout=10)
            await current.connect({'host':'127.0.0.1','port':port,'expectedBackend':'MALECNS_EXPERIMENTAL',
                                   'expectedDataset':'male-cns:v1.0'})
            report.setdefault('statuses',[]).append(current.status)
            if 'visual_threat_v1' not in current.status.get('capabilities',[]):
                await current.close(); raise RuntimeError('missing_visual_threat_capability')
            return current

        async def observe(name,predicate,timeout=10):
            async def wait():
                while True:
                    frame=await frames.get()
                    if predicate(frame): return frame
            frame=await asyncio.wait_for(wait(),timeout)
            report['checks'].append({'name':name,'passed':True,'sequence':frame['sequence'],
                                    'raw':frame['raw']['visualThreat'],'motor':frame.get('motor'),
                                    'requestedAction':frame.get('requestedAction')})
            return frame

        def raw(frame): return frame.get('raw',{}).get('visualThreat',{})
        async def pulse():
            stamp=(time.monotonic(),time.time(),label)
            request=await adapter.send_visual_threat(True,750,source={'diagnostic':'visual_threat_server_trial'})
            if request is None: raise RuntimeError('sensory_not_sent')
            sent[request]=stamp
            return request

        try:
            adapter=await connect()
            label='inactive'
            await observe('inactive_no_input',lambda f:not raw(f).get('active') and raw(f).get('inputEventCount') == 0)
            label='pulse_expiry'
            request=await pulse()
            applied=await observe('pulse_applied',lambda f:raw(f).get('requestId') == request and raw(f).get('active')
                          and raw(f).get('inputEventCount',0)>0)
            if any(v.get('spikeCount',0)>0 for v in raw(applied).get('readouts',{}).values()):
                report['checks'].append({'name':'DNp01_downstream_spikes','passed':True,
                                        'sequence':applied['sequence'],'raw':raw(applied)})
            else:
                await observe('DNp01_downstream_spikes',lambda f:raw(f).get('requestId') == request
                              and any(v.get('spikeCount',0)>0 for v in raw(f).get('readouts',{}).values()))
            await observe('bounded_expiry',lambda f:raw(f).get('requestId') == request
                          and raw(f).get('reason') in ('expired','brain_duration_elapsed') and not raw(f).get('active')
                          and raw(f).get('inputEventCount') == 0)
            label='stop'
            request=await pulse()
            await observe('second_pulse_applied',lambda f:raw(f).get('requestId') == request and raw(f).get('active'))
            await adapter.send_action('STOP',101)
            await observe('STOP_cancels',lambda f:f.get('appliedRequestId') == 101 and not raw(f).get('active')
                          and raw(f).get('inputEventCount') == 0)
            label='stop_then_newer_action'
            await pulse()
            await adapter.send_action('STOP',102)
            await adapter.send_action('FORWARD',103)
            await observe('newer_action_does_not_revive_sensory',lambda f:f.get('appliedRequestId') == 103
                          and not raw(f).get('active') and raw(f).get('inputEventCount') == 0)
            await adapter.send_action('STOP',104)
            await observe('forward_test_stopped',lambda f:f.get('appliedRequestId') == 104)
            label='forward_coexist'
            await adapter.send_action('FORWARD',105)
            await observe('coexist_forward_started',lambda f:f.get('appliedRequestId') == 105
                          and f.get('requestedAction') == 'FORWARD')
            request=await pulse()
            def finite_response(frame):
                values=list(frame.get('motor',{}).values())
                values += [v.get('rateHz') for v in raw(frame).get('readouts',{}).values()]
                return len(values) == 4 and all(type(v) in (int,float) and math.isfinite(v) for v in values)
            await observe('forward_with_sensory_finite',lambda f:raw(f).get('requestId') == request
                          and raw(f).get('active') and raw(f).get('inputEventCount',0)>0
                          and f.get('requestedAction') == 'FORWARD' and finite_response(f))
            off_request=await adapter.send_visual_threat(False,0,source={'diagnostic':'forward_coexist_off'})
            if off_request is None: raise RuntimeError('sensory_off_not_sent')
            await observe('forward_preserved_after_sensory_off',lambda f:raw(f).get('requestId') == off_request
                          and not raw(f).get('active') and raw(f).get('inputEventCount') == 0
                          and f.get('requestedAction') == 'FORWARD' and finite_response(f))
            await adapter.send_action('STOP',106)
            await observe('coexist_STOP',lambda f:f.get('appliedRequestId') == 106
                          and f.get('requestedAction') == 'STOP' and not raw(f).get('active'))
            label='disconnect'
            request=await pulse()
            await observe('disconnect_pulse_applied',lambda f:raw(f).get('requestId') == request and raw(f).get('active'))
            await adapter.close(); adapter=None
            # Closing wakes server cleanup; reconnect only after that bounded handoff.
            await asyncio.sleep(.25)
            while not frames.empty(): frames.get_nowait()
            label='reconnect'; adapter=await connect()
            await observe('reconnect_no_stimulus',lambda f:not raw(f).get('active') and raw(f).get('inputEventCount') == 0)
            report['release']=await adapter.release()
            report['completed']=not report.get('protocolErrors')
        finally:
            report['frameStatistics']={'receivedCount':len(sequences),'uniqueSequenceCount':len(set(sequences)),
                'firstSequence':sequences[0] if sequences else None,'lastSequence':sequences[-1] if sequences else None,
                'sequenceGapCount':sum(b != a+1 for a,b in zip(sequences,sequences[1:])),
                'gapNote':'Disconnect/reconnect can skip unpublished windows; adapter validates each connection.',
                'stepWallMs':{'count':len(step_times),'median':float(np.median(step_times)),
                              'p95':float(np.percentile(step_times,95)),'max':max(step_times)} if step_times else None,
                'rssSampleCount':len(rss),'maxSampledProcessTreeSummedRssBytes':max(rss) if rss else None,
                'rssProcesses':list(rss_processes.values()),
                'rssScope':'Owned launcher plus recursive descendants sampled at received frames; per-process maxima are sampled, not OS lifetime peaks. Summed RSS may double-count shared pages.'}
            if adapter is not None: await adapter.close()


def execute(output):
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic(); child=None
    report={'completed':False,'checks':[],'ready':False,'mode':'LIVE',
            'scope':'Real production server sensory transport; no Unity/avoidance or baseline equivalence claim.'}
    report['dependencies']={'python':platform.python_version(),**{name:version(name) for name in
                            ('numpy','numba','llvmlite','psutil')}}
    report['localHashes']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                          ('tools/visual_threat_server_trial.py','Runtime/Bridge/brain_adapter.py',
                           'Brain/MaleCNS/config/visual_threat_v1.json')}
    report['identityEvidence']='statuses contain real server graphHash/configHash/sourceHash and instance/session IDs'
    with (output/'server.stdout.log').open('w',encoding='utf-8') as stdout, (output/'server.stderr.log').open('w',encoding='utf-8') as stderr:
        try:
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1',0)); port=reservation.getsockname()[1]
            command=[sys.executable,str(ROOT/'Brain/MaleCNS/brain_server_bridge.py'),'--host','127.0.0.1','--port',str(port)]
            report.update(command=command,endpoint=f'127.0.0.1:{port}')
            child=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=stderr,text=True,
                                   env={**os.environ,'PYTHONUNBUFFERED':'1'},
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            report['ownedChildPid']=child.pid
            ready=queue.Queue()
            def capture():
                for line in child.stdout:
                    stdout.write(line); stdout.flush()
                    if 'brain server READY at ' in line: ready.put(True)
                ready.put(False)
            threading.Thread(target=capture,daemon=True).start()
            if not ready.get(timeout=60): raise RuntimeError('server_exited_before_ready')
            asyncio.run(asyncio.wait_for(trial(port,output,report),timeout=90))
        except Exception as error:
            report['completed']=False; report['error']=type(error).__name__+': '+str(error)
        finally:
            if child is not None:
                if child.poll() is None: child.terminate()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
                report['ownedChildExitCode']=child.returncode
            report['wallSeconds']=time.monotonic()-started
            (output/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'completed':report['completed'],'output':str(output),'error':report.get('error')}))
    return 0 if report['completed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/neural-feedback/visual-threat-server-trial')
    args=parser.parse_args()
    if args.execute: return execute(args.output.resolve())
    print('Use --execute for one owned production Brain and a bounded live sensory trial.'); return 0


if __name__=='__main__': raise SystemExit(main())
