"""Global two-axis calibration; never accepts an Action or neuron-specific gains."""
import numpy as np


class AnalogMotorDecoder:
    def __init__(self, calibration):
        self.c=calibration

    def decode(self, raw):
        x=np.asarray(raw,dtype=float)-np.asarray(self.c['baseline'])
        x=np.asarray(self.c.get('matrix',[[1,0],[0,1]]))@x
        f,t=x; df,dt=self.c['deadzone']; rf,rt=self.c['reference']
        return {'forward':float(np.clip((f-df)/(rf-df),0,1)),
                'turn':float(np.sign(t)*np.clip((abs(t)-dt)/(rt-dt),0,1))}
