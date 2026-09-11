"""Experimental VNC analog readout, not an official MaleCNS dynamics model."""
import numpy as np


class AnalogSteering:
    """Equal cell-type weights, then equal neuron weights within each type/side."""
    def __init__(self, groups, reference_mv, deadzone_mv):
        self.groups = groups
        self.reference = float(reference_mv)
        self.deadzone = float(deadzone_mv)
        if not 0 <= self.deadzone < self.reference:
            raise ValueError('Require 0 <= deadzone < reference')

    def decode(self, delta_v):
        response = {side:float(np.mean([np.mean(delta_v[indices]) for indices in groups.values()]))
                    for side,groups in self.groups.items()}
        raw = response['R']-response['L']
        turn = float(np.sign(raw)*np.clip((abs(raw)-self.deadzone)/(self.reference-self.deadzone),0,1))
        return {'responseMv':response,'rawTurnMv':raw,'turn':turn,
                'metadata':{'motor_readout':'VNC_SUBTHRESHOLD_POPULATION',
                            'model':'MaleCNS + Shiu-compatible LIF','ready':False,
                            'forwardAvailable':False,'integration':'debug only'}}
