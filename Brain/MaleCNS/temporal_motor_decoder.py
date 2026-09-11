"""Causal, Action-blind EMA with optional globally symmetric hysteresis."""
import numpy as np


class TemporalMotorDecoder:
    def __init__(self, config):
        self.config=config
        self.state=np.zeros(2,dtype=float)
        self.active=np.zeros(2,dtype=int)

    def decode(self, raw, dt_ms=50):
        if dt_ms<=0: raise ValueError('dt_ms must be positive')
        raw=np.asarray(raw,dtype=float)
        if raw.shape!=(2,) or not np.isfinite(raw).all(): raise ValueError('Two finite raw values required')
        alpha=1-np.exp(-dt_ms/np.asarray(self.config['tauMs']))
        self.state+=alpha*(raw-self.state)
        z=np.asarray(self.config['matrix'])@self.state
        reference=np.asarray(self.config['reference'])
        on=np.asarray(self.config['on']); off=np.asarray(self.config['off'])
        if self.config['mode']=='ema_only':
            motor=[np.clip(z[0]/reference[0],0,1),np.clip(z[1]/reference[1],-1,1)]
        elif self.config['mode']=='ema_hysteresis':
            if self.active[0] and z[0]<=off[0]: self.active[0]=0
            if z[0]>on[0]: self.active[0]=1
            if self.active[1] and z[1]*self.active[1]<=off[1]: self.active[1]=0
            if abs(z[1])>on[1]: self.active[1]=int(np.sign(z[1]))
            motor=[np.clip((z[0]-off[0])/(reference[0]-off[0]),0,1) if self.active[0] else 0,
                   self.active[1]*np.clip((abs(z[1])-off[1])/(reference[1]-off[1]),0,1) if self.active[1] else 0]
            if self.config.get('hysteresisAxes')==['turn']:
                motor[0]=np.clip((z[0]-on[0])/(reference[0]-on[0]),0,1)
        else:
            motor=[np.clip((z[0]-on[0])/(reference[0]-on[0]),0,1),
                   np.sign(z[1])*np.clip((abs(z[1])-on[1])/(reference[1]-on[1]),0,1)]
        return {'forward':float(motor[0]),'turn':float(motor[1]),
                'filteredRaw':self.state.tolist(),'transformed':z.tolist()}
