"""Pure history/commentary lifecycle contracts; no API or live neural execution."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from tools.test_blind_run_script import cue, CATALOG
from Runtime.Bridge.control import ControlError
from tools import test_visual_threat_feedback as fixtures
from tools.test_environment_feedback import event


class CommentaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.IntegrationContractTests.asyncSetUp
    asyncTearDown=fixtures.IntegrationContractTests.asyncTearDown
    settle=fixtures.IntegrationContractTests.settle
    sensory=fixtures.IntegrationContractTests.sensory
    frame=fixtures.IntegrationContractTests.frame

    async def history(self):
        b=self.b
        b.accept_environment_event(event('threat_started',2))
        await self.settle()
        b.observe_visual_threat(self.frame(self.sensory()[0]['requestId']))
        await self.settle()
        self.assertIsNotNone(b.visual_threat_history)
        b.conversation.append.reset_mock()
        b.environment.threat=False
        b.conversation.state='live'
        b.neural.enabled=True
        b.neural_scheduler.spontaneous=True
        b.neural_scheduler.reduced=False
        b.neural_scheduler.blocked_until_ms=0
        b.neural_output_at=-1e15
        b.conversation.last_voice_end_at=-1e15
        return b.visual_threat_history

    async def test_stop_bilingual_once(self):
        h=await self.history(); b=self.b
        b.cancel_visual_threat(send_off=False)
        self.assertIs(b.visual_threat_history,h)
        for lang in ('ja','en'):
            b.conversation.settings['language']=lang; b.visual_threat_history_sent=None
            scene=CATALOG['swatter_escaped'][lang]
            text,trace=b.visual_threat_cue_context('swatter_escaped',scene)
            for value in ('DNp01','40','0'): self.assertIn(value,text)
            self.assertIn('予告は解除された' if lang=='ja' else 'warning cleared',text)
            self.assertIn('現在値' if lang=='ja' else 'not current',text)
            self.assertEqual(trace['language'],lang); self.assertEqual(trace['brainSequence'],11)
            self.assertIsNone(b.visual_threat_cue_context('swatter_escaped',scene))
        b.conversation.append.assert_not_awaited()

    async def test_scope_stale_clear(self):
        h=await self.history(); b=self.b
        for change in ('epoch','identity','stale','clear'):
            b.visual_threat_history=h
            if change=='epoch': b.arbiter.epoch+=1
            if change=='identity': b.adapter.status['sessionId']='other'
            if change=='stale': b.summary.return_value={'stale':True}
            if change=='clear': b.clear_neural()
            self.assertIsNone(b.visual_threat_cue_context('swatter_escaped','scene'))
            self.assertIsNone(b.visual_threat_history)
            b.arbiter.epoch=1; b.adapter.status['sessionId']='session'; b.summary.return_value={'stale':False}

    async def test_warning_operation_and_disabled_not_augmented(self):
        h=await self.history(); b=self.b
        for name in ('intro','book','swatter_warning','right_edge_urgent','FORWARD','STOP'):
            self.assertIsNone(b.visual_threat_cue_context(name,'scene'))
            self.assertIsNone(b.visual_threat_history_sent)
        for owner,key,value in ((b.neural,'enabled',False),(b.neural_scheduler,'reduced',True),
                                 (b.neural_scheduler,'spontaneous',False),(b.conversation,'state','text')):
            old=getattr(owner,key); setattr(owner,key,value)
            self.assertIsNone(b.visual_threat_cue_context('swatter_escaped','scene'))
            self.assertIs(b.visual_threat_history,h); setattr(owner,key,old)

    async def test_eight_seconds_not_refreshed(self):
        h=await self.history(); b=self.b
        b.observe_visual_threat(self.frame(self.sensory()[0]['requestId'],sequence=12))
        self.assertIs(b.visual_threat_history,h)
        with patch('Runtime.Bridge.visual_threat_feedback.time',SimpleNamespace(monotonic=lambda:(h['observedMs']+8001)/1000)):
            self.assertIsNone(b.visual_threat_cue_context('swatter_escaped','scene'))
        self.assertIsNone(b.visual_threat_history)

    async def test_accepted_blind_cue_single_append(self):
        await self.history(); b=self.b
        b.conversation.mode='live'; b.emit=Mock()
        b.blind_script.accept(cue('intro'),'ja',now=0)
        await b.blind_run_cue(cue('swatter_escaped',2))
        b.conversation.append.assert_awaited_once()
        call=b.conversation.append.await_args
        self.assertEqual(call.args[0],'commentary'); self.assertIn('DNp01',call.args[1])
        self.assertIn('trace',call.kwargs)
        self.assertEqual(b.blind_script.last_cue,'swatter_escaped')
        self.assertGreater(b.blind_script.last_spoken_at,0)
        _, speak=b.blind_script.accept(cue('book',3),'ja',now=b.blind_script.last_spoken_at+1)
        self.assertFalse(speak, 'promoted commentary must retain the ordinary 3-second cue interval')

    async def test_warning_rejected_cue_preserve_history(self):
        h=await self.history(); b=self.b
        b.conversation.mode='live'; b.emit=Mock()
        b.blind_script.accept(cue('intro'),'ja',now=0)
        await b.blind_run_cue(cue('right_edge_urgent',2))
        b.conversation.append.assert_awaited_once()
        self.assertNotIn('DNp01',b.conversation.append.await_args.args[1])
        self.assertIsNone(b.visual_threat_history_sent)
        b.conversation.append.reset_mock()
        with self.assertRaises(ControlError): await b.blind_run_cue(cue('swatter_escaped',2))
        b.conversation.append.assert_not_awaited()
        self.assertIs(b.visual_threat_history,h)


if __name__=='__main__': unittest.main()
