"""Load the pinned pre-optimization implementation for repeatable diagnostics."""
import pathlib,subprocess,linecache
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[1]
source=subprocess.check_output(['git','-c','safe.directory='+str(ROOT).replace('\\','/'),'show','5d741284f9633c8667c258184893b3aafaa5b5a2:Brain/MaleCNS/shiu_compatible.py'],cwd=ROOT,text=True)
name='<malecns-reference-5d74128>'
linecache.cache[name]=(len(source),None,source.splitlines(True),name)
ns={'np':np};exec(compile(source,name,'exec'),ns)
Original=ns['MaleCNSShiuCompatibleLIF']

# Pinned controller keeps old diagnostic candidates independent of production optimizations.
import types,analog_controller
reference_ac=types.ModuleType('malecns_reference_controller')
reference_ac.__dict__.update(analog_controller.__dict__)
controller_source=subprocess.check_output(['git','-c','safe.directory='+str(ROOT).replace('\\','/'),'show','5d741284f9633c8667c258184893b3aafaa5b5a2:Brain/MaleCNS/analog_controller.py'],cwd=ROOT,text=True)
controller_name='<malecns-controller-reference-5d74128>'
linecache.cache[controller_name]=(len(controller_source),None,controller_source.splitlines(True),controller_name)
exec(compile(controller_source,controller_name,'exec'),reference_ac.__dict__)
reference_ac.MaleCNSShiuCompatibleLIF=Original
