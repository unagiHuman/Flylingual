"""Bounded environmental event proxy; not a calibrated retinal model."""
import json
import hashlib
import time
from pathlib import Path
import numpy as np


def validate_command(payload):
    if (not isinstance(payload, dict) or set(payload) != {'type','requestId','active','validForMs'}
            or payload['type'] != 'set_visual_threat' or type(payload['requestId']) is not int
            or type(payload['active']) is not bool or type(payload['validForMs']) is not int
            or not (1 <= payload['validForMs'] <= 750 if payload['active'] else payload['validForMs'] == 0)):
        raise ValueError('invalid_visual_threat')
    return payload['requestId'], payload['active'], payload['validForMs']


class VisualThreat:
    def __init__(self, config, ids, motor_indices, seed):
        cfg=json.loads(Path(config).read_text()) if isinstance(config,(str,Path)) else config
        groups=cfg.get('inputs',{})
        if (cfg.get('schemaVersion') != 1 or cfg.get('stimulusModel') != 'event_proxy_v1'
                or cfg.get('stimulusRateHz') != 100 or cfg.get('maxBrainMs') != 500
                or set(groups) != {'LC4','LPLC2'} or len(groups['LC4']) != 126 or len(groups['LPLC2']) != 185
                or cfg.get('readouts') != {'R':10001,'L':10010}):
            raise ValueError('invalid_visual_threat_config')
        # Pin the audited exact-type set; configuration cannot select arbitrary cells.
        if (cfg.get('annotationSha256') != '2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2'
                or hashlib.sha256(json.dumps(groups,sort_keys=True,separators=(',',':')).encode()).hexdigest() != '50ce74d2a6f24587f61bd72ef6b025ebfb63f9cca2fe44d72757afd52dd11dd6'):
            raise ValueError('visual_threat_audited_selection_mismatch')
        values=groups['LC4']+groups['LPLC2']
        if any(type(v) is not int or v <= 0 for v in values) or len(set(values)) != 311:
            raise ValueError('invalid_visual_threat_ids')
        def resolve(values):
            at=np.searchsorted(ids,values)
            if np.any(at >= len(ids)) or not np.array_equal(ids[at],values):
                raise ValueError('unknown_visual_threat_ids')
            return at.astype(np.int64)
        self.indices=resolve(sorted(values))
        self.readouts={side:(body,int(resolve([body])[0])) for side,body in cfg['readouts'].items()}
        if np.intersect1d(self.indices,np.r_[motor_indices,[v[1] for v in self.readouts.values()]]).size:
            raise ValueError('visual_threat_input_overlap')
        self.rng=np.random.default_rng(np.random.SeedSequence([seed, 0x564953]))
        self.request_id=None; self.deadline=0.; self.remaining=0; self.reason='inactive'

    def command(self, request_id, active, deadline, now=None):
        now=time.monotonic() if now is None else now
        self.request_id=request_id
        self.deadline=deadline
        self.remaining=5000 if active and deadline > now else 0
        self.reason='active' if self.remaining else 'expired' if active else 'cancelled'

    def events(self, ticks, now=None):
        now=time.monotonic() if now is None else now
        if self.remaining and now >= self.deadline:
            self.remaining=0; self.reason='expired'
        active_ticks=min(ticks,self.remaining)
        offsets=np.zeros(ticks+1,dtype=np.int64); batches=[]
        for tick in range(active_ticks):
            batches.append(self.indices[self.rng.random(len(self.indices)) < .01])
            offsets[tick+1]=offsets[tick]+len(batches[-1])
        offsets[active_ticks+1:]=offsets[active_ticks]
        self.remaining-=active_ticks
        if active_ticks and not self.remaining:
            self.reason="brain_duration_elapsed"
        events=np.concatenate(batches).astype(np.int64,copy=False) if batches else np.empty(0,dtype=np.int64)
        return active_ticks, offsets, events

    def metadata(self, active_ticks, event_count, counts, window_ms):
        return {'schemaVersion':1,'stimulusModel':'event_proxy_v1','active':active_ticks > 0,
                'inputEventCount':int(event_count),'requestId':self.request_id,
                'reason':'active' if active_ticks else self.reason,
                'readouts':{side:{'bodyId':body,'spikeCount':int(counts[index]),
                                  'rateHz':float(counts[index]*1000/window_ms)}
                            for side,(body,index) in self.readouts.items()}}


def merge_events(offsets, events, sensory_offsets, sensory_events):
    if not len(sensory_events):
        return offsets, events
    batches=[np.r_[events[offsets[t]:offsets[t+1]], sensory_events[sensory_offsets[t]:sensory_offsets[t+1]]]
             for t in range(len(offsets)-1)]
    return offsets+sensory_offsets, np.concatenate(batches).astype(np.int64,copy=False)
