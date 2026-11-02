"""检查桌面环境与临时窗口站创建结果，不打开客户端或修改现有权限。"""

import ctypes as c
import json
import os
from ctypes import wintypes as w
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent


class SecurityAttributes(c.Structure):
    _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]


def inspect():
    kernel = c.WinDLL("kernel32", use_last_error=True)
    user = c.WinDLL("user32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetCurrentThreadId.restype = w.DWORD
    user.GetProcessWindowStation.restype = w.HANDLE
    user.GetThreadDesktop.argtypes = [w.DWORD]
    user.GetThreadDesktop.restype = w.HANDLE
    user.GetUserObjectInformationW.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    user.GetUserObjectSecurity.argtypes = [w.HANDLE, c.POINTER(w.DWORD), c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    user.CreateWindowStationW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(SecurityAttributes)]
    user.CreateWindowStationW.restype = w.HANDLE
    user.CloseWindowStation.argtypes = [w.HANDLE]
    user.CloseWindowStation.restype = w.BOOL
    kernel.ProcessIdToSessionId.argtypes = [w.DWORD, c.POINTER(w.DWORD)]
    kernel.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
    kernel.GetCurrentPackageFullName.argtypes = [c.POINTER(w.DWORD), w.LPWSTR]

    def name(handle):
        value, needed = c.create_unicode_buffer(512), w.DWORD()
        if user.GetUserObjectInformationW(handle, 2, value, c.sizeof(value), c.byref(needed)):
            return value.value
        return "读取失败"

    station = user.GetProcessWindowStation()
    result = {"时间": datetime.now().isoformat(timespec="seconds"), "进程": os.getpid(),
              "窗口站": name(station), "桌面": name(user.GetThreadDesktop(kernel.GetCurrentThreadId()))}
    from 观察窗口站调用 import token_information

    result["令牌"] = token_information(kernel.GetCurrentProcess())
    session = w.DWORD()
    kernel.ProcessIdToSessionId(os.getpid(), c.byref(session))
    result["会话"] = session.value
    restrictions = w.DWORD()
    if kernel.QueryInformationJobObject(None, 4, c.byref(restrictions), 4, None):
        result["当前作业界面限制"] = hex(restrictions.value)
    length = w.DWORD(512)
    package = c.create_unicode_buffer(512)
    result["程序包身份查询"] = kernel.GetCurrentPackageFullName(c.byref(length), package)
    result["程序包身份"] = package.value

    flag, needed = w.DWORD(4), w.DWORD()
    user.GetUserObjectSecurity(station, c.byref(flag), None, 0, c.byref(needed))
    descriptor = c.create_string_buffer(needed.value)
    if not user.GetUserObjectSecurity(station, c.byref(flag), descriptor, len(descriptor), c.byref(needed)):
        raise c.WinError(c.get_last_error())
    relative = bytes(descriptor)
    dacl_offset = int.from_bytes(relative[16:20], "little")
    acl_size = int.from_bytes(relative[dacl_offset + 2:dacl_offset + 4], "little")
    result["原窗口站访问控制表"] = relative[dacl_offset:dacl_offset + acl_size].hex()
    result["原安全描述符控制"] = hex(int.from_bytes(relative[2:4], "little"))
    attributes = SecurityAttributes(c.sizeof(SecurityAttributes), c.cast(descriptor, c.c_void_p), False)
    security = c.WinDLL("advapi32", use_last_error=True)
    security.InitializeSecurityDescriptor.argtypes = [c.c_void_p, w.DWORD]
    security.SetSecurityDescriptorDacl.argtypes = [c.c_void_p, w.BOOL, c.c_void_p, w.BOOL]
    absolute = c.create_string_buffer(40)
    if not security.InitializeSecurityDescriptor(absolute, 1) or not security.SetSecurityDescriptorDacl(
            absolute, True, c.addressof(descriptor) + dacl_offset, False):
        raise c.WinError(c.get_last_error())
    absolute_attributes = SecurityAttributes(c.sizeof(SecurityAttributes), c.cast(absolute, c.c_void_p), False)
    result["临时窗口站"] = []
    for kind, selected in (("原相对描述符", attributes), ("复制为绝对描述符", absolute_attributes)):
        for access in (0x80000008, 0xA):
            c.set_last_error(0)
            handle = user.CreateWindowStationW(None, 0, access, c.byref(selected))
            error = c.get_last_error() if not handle else 0
            item = {"描述方式": kind, "访问方式": hex(access), "成功": bool(handle), "系统错误": error}
            if handle:
                item["临时对象名"] = name(handle)
                item["已关闭临时对象"] = bool(user.CloseWindowStation(handle))
            result["临时窗口站"].append(item)
    return result


if __name__ == "__main__":
    try:
        value = inspect()
    except Exception as error:
        value = {"核对失败": str(error), "类型": type(error).__name__}
    output = ROOT / "桌面环境核对.local.json"
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
