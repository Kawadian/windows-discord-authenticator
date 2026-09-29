"""Local account password setter; never sends a password over the network."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class USER_INFO_1003(ctypes.Structure):
    _fields_ = [("usri1003_password", wintypes.LPWSTR)]


def set_local_password(username: str, secret: str) -> None:
    if not username or not secret:
        raise ValueError("username and password required")
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Windows is required")
    info = USER_INFO_1003(secret)
    api = ctypes.windll.Netapi32.NetUserSetInfo
    api.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                    ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    api.restype = wintypes.DWORD
    parameter = wintypes.DWORD()
    result = api(None, username, 1003, ctypes.byref(info), ctypes.byref(parameter))
    if result:
        raise OSError(result, f"NetUserSetInfo failed (parameter {parameter.value})")
