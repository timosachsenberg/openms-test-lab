"""Trace actual DLL load events for a Windows executable without altering DLLs."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class STARTUPINFO(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                ('x', w.DWORD), ('y', w.DWORD), ('cx', w.DWORD), ('cy', w.DWORD),
                ('xchars', w.DWORD), ('ychars', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved2size', w.WORD), ('reserved2', c.POINTER(c.c_byte)),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class PROCESSINFO(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class LOAD_DLL(c.Structure):
    _fields_ = [('file', w.HANDLE), ('base', c.c_void_p), ('offset', w.DWORD), ('size', w.DWORD),
                ('name', c.c_void_p), ('unicode', w.WORD)]


class CREATE_PROCESS(c.Structure):
    _fields_ = [('file', w.HANDLE), ('process', w.HANDLE), ('thread', w.HANDLE), ('base', c.c_void_p),
                ('offset', w.DWORD), ('size', w.DWORD), ('tls', c.c_void_p), ('start', c.c_void_p),
                ('name', c.c_void_p), ('unicode', w.WORD)]


class INFO(c.Union):
    _fields_ = [('load', LOAD_DLL), ('create', CREATE_PROCESS), ('code', w.DWORD),
                ('thread', w.HANDLE), ('padding', c.c_uint64 * 20)]


class EVENT(c.Structure):
    _fields_ = [('kind', w.DWORD), ('pid', w.DWORD), ('tid', w.DWORD), ('info', INFO)]


def trace(executable, args, output):
    assert c.sizeof(c.c_void_p) == 8 and c.sizeof(EVENT) == 176
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD,
                                c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFO), c.POINTER(PROCESSINFO)]
    k.CreateProcessW.restype = w.BOOL
    k.WaitForDebugEvent.argtypes = [c.POINTER(EVENT), w.DWORD]
    k.WaitForDebugEvent.restype = w.BOOL
    k.ContinueDebugEvent.argtypes = [w.DWORD, w.DWORD, w.DWORD]
    k.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    k.GetFinalPathNameByHandleW.restype = w.DWORD
    k.CloseHandle.argtypes = [w.HANDLE]
    k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    startup, process = STARTUPINFO(), PROCESSINFO()
    startup.cb = c.sizeof(startup)
    command = c.create_unicode_buffer(subprocess.list2cmdline([str(executable), *args]))
    # Only this disposable child is debugged; LOAD_DLL_DEBUG_EVENT provides the
    # loader's file handles even when --help exits too quickly for polling.
    if not k.CreateProcessW(str(executable), command, None, None, False, 0x2 | 0x08000000,
                            None, str(executable.parent), c.byref(startup), c.byref(process)):
        raise c.WinError(c.get_last_error())
    result = {'executable': str(executable), 'arguments': args, 'path': os.environ.get('PATH'),
              'loads': [], 'exceptions': [], 'exit_code': None}
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            event = EVENT()
            if not k.WaitForDebugEvent(c.byref(event), 1000):
                continue
            status = 0x00010002  # DBG_CONTINUE
            if event.kind in (3, 6):
                handle = event.info.create.file if event.kind == 3 else event.info.load.file
                if handle:
                    buffer = c.create_unicode_buffer(32768)
                    length = k.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
                    if length:
                        result['loads'].append(buffer.value.removeprefix('\\\\?\\'))
                    k.CloseHandle(handle)
            elif event.kind == 2 and event.info.thread:
                k.CloseHandle(event.info.thread)
            elif event.kind == 1:
                code = event.info.code
                if code != 0x80000003:  # Initial debugger breakpoint is expected.
                    result['exceptions'].append(hex(code))
                    status = 0x80010001  # Let the application's handlers run.
            elif event.kind == 5:
                result['exit_code'] = event.info.code
            k.ContinueDebugEvent(event.pid, event.tid, status)
            if event.kind == 5:
                break
        else:
            result['timeout'] = True
            k.TerminateProcess(process.process, 124)
    finally:
        k.CloseHandle(process.thread)
        k.CloseHandle(process.process)
        Path(output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    result = trace(Path(sys.argv[1]).resolve(), sys.argv[3:], sys.argv[2])
    print(json.dumps({'exit_code': result['exit_code'], 'loaded_files': len(result['loads'])}))
    sys.exit(0 if result['exit_code'] == 0 else 1)
