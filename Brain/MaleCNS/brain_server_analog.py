"""Experimental temporal MaleCNS server; reuses existing NDJSON transport."""
import argparse
import asyncio
import time
from pathlib import Path
from brain_server_malecns import Server,Worker
from analog_controller import MaleCNSAnalogController,ROOT


class AnalogWorker(Worker):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.latest_sensory=None

    def submit(self,request_id,action,client_time_ms):
        with self.lock:
            self.received+=1
            if self.latest_command is not None: self.superseded+=1
            self.latest_command=(request_id,action,client_time_ms)
            if str(getattr(action,'value',action)) == 'STOP':
                self.latest_sensory=(None,False,0.)

    def submit_visual_threat(self,request_id,active,valid_for_ms):
        with self.lock:
            self.latest_sensory=(request_id,active,time.monotonic()+valid_for_ms/1000)

    def apply_pending(self,c):
        # Same lock makes STOP and the separate latest sensory slot atomic.
        with self.lock:
            command=self.latest_command; self.latest_command=None
            sensory=self.latest_sensory; self.latest_sensory=None
            if command is not None: c.set_action(command[1])
            if sensory is not None and c.visual_threat is not None:
                c.visual_threat.command(*sensory)
        return command

    def post(self,frame):
        def deliver():
            if self.queue.full(): self.queue.get_nowait()
            self.queue.put_nowait(frame)
        self.loop.call_soon_threadsafe(deliver)

    def run(self):
        try:
            c=MaleCNSAnalogController(self.args.graph,self.args.config,self.args.seed,self.args.window_ms,
                                      getattr(self.args,'visualization_atlas',None),
                                      getattr(self.args,'visual_threat_config',None)).initialize()
            if not c.config.get('sixActionValidationPassed') or not c.temporal:
                raise RuntimeError('Validated temporal config required')
            self.controller=c; self.ready_event.set()
            while not self.stop_event.is_set():
                command=self.apply_pending(c)
                frame=c.step()
                if command is not None:
                    frame['appliedRequestId']=command[0]; frame['appliedClientTimeMs']=command[2]
                frame['diagnostics'].update({'receivedCommandCount':self.received,'supersededCommandCount':self.superseded})
                self.post(frame)
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}'; self.ready_event.set()
            self.post({'type':'error','error':'brain_worker_failed','message':self.error,'ready':False})


class AnalogServer(Server):
    worker_class=AnalogWorker
    supports_visual_threat=False
    def __init__(self,args):
        super().__init__(args); self.queue=asyncio.Queue(maxsize=1)

    def status_payload(self):
        return {'type':'status','state':'READY','backend':'MALECNS_EXPERIMENTAL',
                'backendId':'MALECNS_EXPERIMENTAL','model':'MaleCNS + Shiu-compatible LIF',
                'motor_readout':'VNC_ANALOG_POPULATION','windowMs':self.args.window_ms,'dtMs':.1,
                'networkRebuildCount':1,'stateResetCount':0,'ready':False,
                'capabilities':['visual_threat_v1'] if self.supports_visual_threat and self.worker and getattr(self.worker.controller,'visual_threat',None) is not None else [],
                'experimentalRuntimeAvailable':True,'windowsCompatibilityVerified':False}

    async def send(self,writer,payload):
        await asyncio.wait_for(super().send(writer,payload),timeout=2)

    async def publish(self):
        while True:
            frame=await self.queue.get()
            for writer in list(self.sessions):
                try: await self.send(writer,frame)
                except (ConnectionError,asyncio.TimeoutError):
                    writer.close(); self.sessions.discard(writer)


def parse_args():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph',type=Path,default=ROOT/'artifacts/neuron_checkpoint')
    p.add_argument('--config',type=Path,default=ROOT/'Brain/MaleCNS/config/analog_temporal_v1.json')
    p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8766)
    p.add_argument('--seed',type=int,default=20270101)
    p.add_argument('--window-ms',type=float,choices=[50],default=50)
    p.add_argument('--visual-threat-config',type=Path,default=ROOT/'Brain/MaleCNS/config/visual_threat_v1.json')
    p.add_argument('--visualization-atlas',type=Path,default=None,
                   help='optional validated MaleCNS soma atlas; emits window spike counts in atlas order')
    return p.parse_args()


if __name__=='__main__':
    try: asyncio.run(AnalogServer(parse_args()).run())
    except KeyboardInterrupt: pass
