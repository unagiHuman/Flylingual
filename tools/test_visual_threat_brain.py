"""Pure scheduling contracts, not a substitute for live neural validation."""
import copy
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Brain/MaleCNS'))
from visual_threat import VisualThreat, validate_command, merge_events
from brain_server_analog import AnalogWorker


class VisualThreatTests(unittest.TestCase):
    def pulse(self):
        cfg=json.loads((ROOT/'Brain/MaleCNS/config/visual_threat_v1.json').read_text())
        ids=np.array(sorted(cfg['inputs']['LC4']+cfg['inputs']['LPLC2']+[10001,10010]))
        return VisualThreat(cfg,ids,np.empty(0,dtype=np.int64),1701)

    def test_exact_command_validation(self):
        good={'type':'set_visual_threat','requestId':1,'active':True,'validForMs':750}
        self.assertEqual(validate_command(good),(1,True,750))
        for change in ({'requestId':True},{'active':1},{'validForMs':0},{'validForMs':751},{'extra':0}):
            with self.assertRaises(ValueError): validate_command({**good,**change})
        self.assertEqual(validate_command({**good,'active':False,'validForMs':0}),(1,False,0))

    def test_inactive_rng_and_deadline(self):
        pulse=self.pulse(); state=copy.deepcopy(pulse.rng.bit_generator.state)
        self.assertEqual(pulse.events(500,now=1)[0],0)
        pulse.command(1,True,2,now=1)
        self.assertEqual(pulse.events(500,now=2)[0],0)
        self.assertEqual(pulse.rng.bit_generator.state,state)
        pulse.command(2,True,100,now=1)
        self.assertEqual(sum(pulse.events(500,now=1)[0] for _ in range(11)),5000)
        self.assertEqual(pulse.reason,'brain_duration_elapsed')

    def test_latest_stop_and_receipt_expiration(self):
        worker=AnalogWorker(None,None,SimpleNamespace())
        pulse=self.pulse()
        controller=SimpleNamespace(visual_threat=pulse,set_action=lambda action:None)
        worker.submit_visual_threat(1,True,750)
        worker.submit_visual_threat(2,False,0)
        worker.apply_pending(controller)
        self.assertEqual(pulse.request_id,2); self.assertEqual(pulse.remaining,0)
        worker.submit_visual_threat(3,True,750)
        worker.submit(4,'STOP',None)
        worker.submit(5,'FORWARD',None)
        worker.apply_pending(controller)
        self.assertEqual(pulse.remaining,0)
        worker.latest_sensory=(6,True,0.)
        worker.apply_pending(controller)
        self.assertEqual(pulse.reason,'expired')

    def test_motor_event_identity_without_sensory(self):
        offsets=np.array([0,1,2]); events=np.array([7,8])
        result=merge_events(offsets,events,np.zeros(3,dtype=np.int64),np.empty(0,dtype=np.int64))
        self.assertIs(result[0],offsets); self.assertIs(result[1],events)
        result=merge_events(offsets,events,np.array([0,2,3]),np.array([1,2,3]))
        self.assertEqual(result[0].tolist(),[0,3,5]); self.assertEqual(result[1].tolist(),[7,1,2,8,3])


if __name__=='__main__': unittest.main()
