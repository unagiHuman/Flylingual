"""Experimental bilateral VNC state readout; no action-conditioned output."""
import numpy as np


class AnalogForward:
    def __init__(self, groups, reference_mv, deadzone_mv):
        self.groups=groups
        self.reference=float(reference_mv)
        self.deadzone=float(deadzone_mv)
        if not 0<=self.deadzone<self.reference:
            raise ValueError('Require 0 <= deadzone < reference')

    def decode(self, delta_v):
        sides={s:float(np.mean([np.mean(delta_v[ix]) for ix in g.values()])) for s,g in self.groups.items()}
        raw=(sides['R']+sides['L'])/2
        return {'bilateralDeltaMv':sides,'forwardRawMv':raw,
                'forward':float(np.clip((raw-self.deadzone)/(self.reference-self.deadzone),0,1)),
                'forwardReadout':'VNC_SUBTHRESHOLD_BILATERAL_POPULATION','ready':False}
