"""Minimal Windows Job Object ownership for the private native launcher.

The launcher joins its own job *before* creating Bridge.  Descendants inherit the
job, and KILL_ON_JOB_CLOSE then cleans only that launcher's process tree when the
launcher exits.  The handle is deliberately not closed while the launcher is
running: closing a kill-on-close job from a member can terminate the caller before
it has written its final status.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time


class JobError(RuntimeError):
    pass


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    HANDLE = wintypes.HANDLE
    BOOL = wintypes.BOOL
    DWORD = wintypes.DWORD
    ULONG_PTR = ctypes.c_size_t
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", DWORD),
            ("MinimumWorkingSetSize", ULONG_PTR),
            ("MaximumWorkingSetSize", ULONG_PTR),
            ("ActiveProcessLimit", DWORD),
            ("Affinity", ULONG_PTR),
            ("PriorityClass", DWORD),
            ("SchedulingClass", DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ULONG_PTR),
            ("JobMemoryLimit", ULONG_PTR),
            ("PeakProcessMemoryUsed", ULONG_PTR),
            ("PeakJobMemoryUsed", ULONG_PTR),
        ]

    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = HANDLE
    kernel32.SetInformationJobObject.argtypes = (HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD)
    kernel32.SetInformationJobObject.restype = BOOL
    kernel32.AssignProcessToJobObject.argtypes = (HANDLE, HANDLE)
    kernel32.AssignProcessToJobObject.restype = BOOL
    kernel32.SetHandleInformation.argtypes = (HANDLE, DWORD, DWORD)
    kernel32.SetHandleInformation.restype = BOOL
    kernel32.GetCurrentProcess.restype = HANDLE
    kernel32.CloseHandle.argtypes = (HANDLE,)
    kernel32.CloseHandle.restype = BOOL
    HANDLE_FLAG_INHERIT = 0x00000001


def _error(action: str) -> JobError:
    return JobError(f"Windows Job Object {action} failed: {ctypes.WinError(ctypes.get_last_error())}")


class KillOnCloseJob:
    """Non-inheritable job handle retained until process exit."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise JobError("Windows Job Object ownership requires Windows")
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise _error("creation")
        self.handle = handle
        try:
            # A child must never inherit a second reference: that would postpone
            # KILL_ON_JOB_CLOSE after the supervisor has exited.
            if not kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, 0):
                raise _error("handle inheritance setup")
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(handle, JobObjectExtendedLimitInformation,
                                                    ctypes.byref(info), ctypes.sizeof(info)):
                raise _error("limit setup")
        except Exception:
            kernel32.CloseHandle(handle)
            self.handle = None
            raise

    def assign_current_process(self) -> None:
        if not self.handle or not kernel32.AssignProcessToJobObject(self.handle, kernel32.GetCurrentProcess()):
            error = _error("self assignment")
            # Assignment failed before the helper joined the job, so releasing
            # this handle cannot terminate the helper.  Avoid retaining an empty
            # job until process exit on this failure path.
            if self.handle:
                kernel32.CloseHandle(self.handle)
                self.handle = None
            raise error

def _owner_probe(path: Path, grandchild_path: Path | None = None, hold: bool = False) -> int:
    """Test-only owner with an ordinary sleep child, optionally a grandchild."""
    job = KillOnCloseJob()
    job.assign_current_process()
    if grandchild_path is None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], close_fds=True)
    else:
        code = (
            "import pathlib, subprocess, sys, time; "
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], close_fds=True); "
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='ascii'); time.sleep(60)"
        )
        child = subprocess.Popen([sys.executable, "-c", code, str(grandchild_path)], close_fds=True)
    path.write_text(str(child.pid), encoding="ascii")
    # Do not close the job handle: process exit closes the last handle and kills
    # this process's job descendants, including ``child``.
    if hold:
        time.sleep(60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-probe", type=Path)
    parser.add_argument("--grandchild-pid", type=Path)
    parser.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    if args.owner_probe is None:
        parser.error("no operation selected")
    return _owner_probe(args.owner_probe, args.grandchild_pid, args.hold)


if __name__ == "__main__":
    raise SystemExit(main())
