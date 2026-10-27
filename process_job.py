"""Ties the app's helper servers to the app's lifetime with a Windows Job Object. No UI code.

Every server the app starts (llama-server, speech recognition, voice, ComfyUI) is added to one job that
Windows kills when its last handle closes, which happens when this process ends in any way: a normal exit,
a crash or Task Manager. Programs the user asked to open are not added, so they keep running.
"""
from __future__ import annotations

import ctypes
import sys
import threading

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

_lock = threading.Lock()
_job = None


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("per_process_time", ctypes.c_longlong), ("per_job_time", ctypes.c_longlong), ("flags", ctypes.c_uint32),
                ("min_working_set", ctypes.c_size_t), ("max_working_set", ctypes.c_size_t), ("active_processes", ctypes.c_uint32),
                ("affinity", ctypes.c_size_t), ("priority_class", ctypes.c_uint32), ("scheduling_class", ctypes.c_uint32)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _IoCounters), ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


def _get_job():
    global _job
    with _lock:
        if _job is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                return None
            limits = _ExtendedLimits()
            limits.basic.flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            kernel32.SetInformationJobObject(ctypes.c_void_p(handle), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                             ctypes.byref(limits), ctypes.sizeof(limits))
            _job = handle  # kept open on purpose: Windows closes it, and kills the job, when this process ends
        return _job


def own(process):
    """Make `process` (a subprocess.Popen) end together with this app. Returns the process; never raises."""
    if sys.platform != "win32" or process is None:
        return process
    try:
        job = _get_job()
        if job:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            handle = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, process.pid)
            if handle:
                kernel32.AssignProcessToJobObject(ctypes.c_void_p(job), ctypes.c_void_p(handle))
                kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass
    return process
