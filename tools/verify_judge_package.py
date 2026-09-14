"""Verify an extracted Judge package; same-machine automation, not clean-machine acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import psutil
from windows_native import Owned, owner_alive, scrubbed_environment, assert_ports_free


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def run(package, output, mode):
    package=package.resolve(); output=output.resolve()
    if output == package or package in output.parents:
        raise ValueError('output must be outside the package')
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic(); owned=None; process=None; ports=[]; peaks={}
    result={'status':'incomplete','mode':mode,'package':str(package),
            'limitation':'Same-machine extracted-package automation; not clean-machine or human play acceptance.',
            'importStatus':'not_run','timeout':False}
    result['numbaCacheFilesBefore']=sum(1 for p in package.rglob('*') if p.is_file() and p.suffix in ('.nbc','.nbi'))
    try:
        python=package/'runtime/python/python.exe'
        exe=package/'FlylingualConversation.exe'
        dll=package/'FlylingualConversation_Data/Managed/Assembly-CSharp.dll'
        result['hashes']={str(p.relative_to(package)):digest(p) for p in (python,exe,dll)}
        # Resolve the actual merged package config inside isolated bundled Python.
        # Print only version, ports, and non-secret identity, never the full config.
        code=("import sys,json,importlib.metadata as m; import brain_server_bridge; "
              "from Runtime.Bridge.config import load_config; "
              "c=load_config(profile='windows-local',local='Runtime/Config/judge.json'); "
              "print(json.dumps({'marker':'IMPORT_AND_CONFIG_OK','python':sys.version,"
              "'packages':{n:m.version(n) for n in ('numpy','numba','llvmlite','psutil','aiohttp')},"
              "'ports':[c['brain']['port'],c['bridge']['tcpPort'],c['bridge']['controlPort']],"
              "'sourceHash':c['brain'].get('expectedSourceHash'),'graphHash':c['brain'].get('expectedGraphHash')}))")
        check=subprocess.run([str(python),'-B','-I','-c',code],cwd=package,
                             env=scrubbed_environment(),capture_output=True,text=True,timeout=60,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (output/'import.stdout.log').write_text(check.stdout,encoding='utf-8')
        (output/'import.stderr.log').write_text(check.stderr,encoding='utf-8')
        result['importExitCode']=check.returncode
        if check.returncode: raise RuntimeError('bundled_import_or_config_failed')
        evidence=json.loads(check.stdout.strip().splitlines()[-1])
        if evidence.get('marker') != 'IMPORT_AND_CONFIG_OK': raise ValueError('import_evidence_missing')
        ports=evidence['ports']
        if any(type(port) is not int or not 1 <= port <= 65535 for port in ports): raise ValueError('invalid_config_ports')
        result['importStatus']='pass'; result['runtime']=evidence
        port_wait=time.monotonic()
        while True:
            try:
                assert_ports_free(ports)
                break
            except ValueError:
                connections=[c for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port in ports]
                # Do not touch another server. Only wait for Windows to retire
                # the previous run's TCP TIME_WAIT before starting this trial.
                if (any(c.status==psutil.CONN_LISTEN for c in connections)
                        or not any(c.status==psutil.CONN_TIME_WAIT for c in connections)
                        or time.monotonic()-port_wait>=90):
                    raise
                time.sleep(.5)
        result['tcpReleaseWaitSeconds']=time.monotonic()-port_wait
        player_log=output/'player.log'
        command=[str(exe),'-flyConversationNoMicrophone','-logFile',str(player_log),
                 '-screen-fullscreen','0','-screen-width','1280','-screen-height','800']
        if mode == 'submission':
            report_path=output/'result.json'
            command += ['-judgeRuntimeProbe',str(report_path),'-judgeSubmissionProbe']
        else:
            report_path=output/'course/report.json'
            command += ['-flyCourseProbe',str(output/'course'),'-flyCourseText','-flyCourseProbeQuit']
        result['command']=command
        with (output/'player.stdout.log').open('w',encoding='utf-8') as stream:
            process=subprocess.Popen(command,cwd=package,env=scrubbed_environment(),stdin=subprocess.DEVNULL,
                                     stdout=stream,stderr=subprocess.STDOUT,text=True,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            owned=Owned(process)
            deadline=time.monotonic()+(350 if mode == 'submission' else 540)
            tree_max=0
            while process.poll() is None and time.monotonic()<deadline:
                owned.refresh(); total=0
                for pid,created in owned.identity.items():
                    if not owner_alive(pid,created): continue
                    try:
                        child=psutil.Process(pid); rss=child.memory_info().rss; total+=rss
                        item=peaks.setdefault(pid,{'pid':pid,'created':created,'name':child.name(),'maxSampledRssBytes':0})
                        item['maxSampledRssBytes']=max(item['maxSampledRssBytes'],rss)
                    except psutil.Error: pass
                tree_max=max(tree_max,total); time.sleep(.25)
            result['timeout']=process.poll() is None
            result['maxSampledSummedTreeRssBytes']=tree_max
        if report_path.is_file(): result['probe']=json.loads(report_path.read_text(encoding='utf-8-sig'))
        else: result['probe']={'result':'incomplete','reason':'probe_report_missing'}
        result['playerExceptionCount']=len(re.findall(r'^[\w.]*Exception:',player_log.read_text(encoding='utf-8',errors='replace'),re.MULTILINE)) if player_log.is_file() else None
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error)
    finally:
        if owned is not None:
            release_until=time.monotonic()+15
            while process is not None and process.poll() is not None and time.monotonic()<release_until:
                owned.refresh()
                if not any(owner_alive(p,c) for p,c in owned.identity.items()): break
                time.sleep(.25)
            owned.refresh()
            result['forcedCleanupRequired']=any(owner_alive(p,c) for p,c in owned.identity.items())
            owned.stop()
            if process is not None:
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: pass
        if owned is None and process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        result['exitCode']=process.returncode if process else None
        result['remainingOwnedPids']=[] if owned is None else [p for p,c in owned.identity.items() if owner_alive(p,c)]
        result['portsFreeAfterCleanup']=False
        if ports:
            try: assert_ports_free(ports); result['portsFreeAfterCleanup']=True
            except Exception as error: result['cleanupError']=type(error).__name__
        probe=result.get('probe',{})
        probe_pass=probe.get('result') == ('submission_path_pass' if mode == 'submission' else 'pass')
        result['status']='pass' if (probe_pass and not result.get('error') and result['importStatus']=='pass'
            and not result['timeout'] and result['exitCode']==0 and result.get('playerExceptionCount')==0
            and not result.get('forcedCleanupRequired',False)
            and not result['remainingOwnedPids'] and result['portsFreeAfterCleanup']) else 'incomplete'
        result['processRss']=list(peaks.values()); result['wallSeconds']=time.monotonic()-started
        result['numbaCacheFilesAfter']=sum(1 for p in package.rglob('*') if p.is_file() and p.suffix in ('.nbc','.nbi'))
        result['rssLimitation']='Sampled process RSS; summed tree RSS may double-count shared pages.'
        (output/'runner-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'report':str(output/'runner-summary.json')}))
    return 0 if result['status']=='pass' else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('submission','course'),required=True)
    args=parser.parse_args()
    return run(args.package,args.output,args.mode)


if __name__=='__main__': raise SystemExit(main())
