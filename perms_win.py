"""Windows named pipe access probe.

  perms_win.py sddl <pipe>   print the pipe's security descriptor as SDDL
  perms_win.py open <pipe>   try opening the pipe read-write, read-only, write-only
"""

import ctypes
import getpass
import sys
from ctypes import wintypes


def print_sddl(pipe):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    generic_read_write = 0x80000000 | 0x40000000
    open_existing = 3
    handle = kernel32.CreateFileW(pipe, generic_read_write, 0, None, open_existing, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    se_kernel_object = 6
    owner_group_dacl = 0x1 | 0x2 | 0x4
    descriptor = ctypes.c_void_p()
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    err = advapi32.GetSecurityInfo(
        handle, se_kernel_object, owner_group_dacl, None, None, None, None,
        ctypes.byref(descriptor),
    )
    if err:
        raise ctypes.WinError(err)

    sddl = wintypes.LPWSTR()
    convert = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.c_void_p,
    ]
    convert.restype = wintypes.BOOL
    if not convert(descriptor, 1, owner_group_dacl, ctypes.byref(sddl), None):
        raise ctypes.WinError(ctypes.get_last_error())
    print("SDDL: %s" % sddl.value)
    kernel32.CloseHandle(handle)


def try_opens(pipe):
    print("user: %s" % getpass.getuser())
    for label, mode in (("read-write", "r+b"), ("read-only", "rb"), ("write-only", "wb")):
        try:
            with open(pipe, mode, buffering=0):
                print("open %s: OK" % label)
        except OSError as exc:
            print("open %s: FAILED %s %s" % (label, type(exc).__name__, exc))


if __name__ == "__main__":
    action, pipe_path = sys.argv[1], sys.argv[2]
    if action == "sddl":
        print_sddl(pipe_path)
    else:
        try_opens(pipe_path)
