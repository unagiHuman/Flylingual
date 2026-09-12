"""Experimental temporal MaleCNS server; reuses existing NDJSON transport."""
import argparse
import asyncio
from pathlib import Path
from brain_server_malecns import Server,Worker
from analog_controller import MaleCNSAnalogController,ROOT


class AnalogWorker(Worker):
    def post(self,frame):
        def deliver():
            if self.queue.full(): self.queue.get_nowait()
            self.queue.put_nowait(frame)
        self.loop.call_soon_threadsafe(deliver)

    def run(self):
        try:
            c=MaleCNSAnalogController(self.args.graph,self.args.config,self.args.seed,self.args.window_ms,
                                      getattr(self.args,'visualization_atlas',None)).initialize()
            if not c.config.get('sixActionValidationPassed') or not c.temporal:
                raise RuntimeError('Validated temporal config required')
            self.controller=c; self.ready_event.set()
            while not self.stop_event.is_set():
                with self.lock:
                    command=self.latest_command; self.latest_command=None
                if command is not None: c.set_action(command[1])
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
    def __init__(self,args):
        super().__init__(args); self.queue=asyncio.Queue(maxsize=1)

    def status_payload(self):
        return {'type':'status','state':'READY','backend':'MALECNS_EXPERIMENTAL',
                'backendId':'MALECNS_EXPERIMENTAL','model':'MaleCNS + Shiu-compatible LIF',
                'motor_readout':'VNC_ANALOG_POPULATION','windowMs':self.args.window_ms,'dtMs':.1,
                'networkRebuildCount':1,'stateResetCount':0,'ready':False,
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
    p.add_argument('--visualization-atlas',type=Path,default=None,
                   help='optional validated MaleCNS soma atlas; emits window spike counts in atlas order')
    return p.parse_args()


if __name__=='__main__':
    try: asyncio.run(AnalogServer(parse_args()).run())
    except KeyboardInterrupt: pass
