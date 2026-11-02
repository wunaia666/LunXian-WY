"""仅供验证副本调试器使用，记录窗口站调用现场并恢复一次性断点。"""

import ctypes as c
import struct
from ctypes import wintypes as w


def token_information(process, thread=None):
    """只读取令牌类别与限制标记，不复制令牌、不改变权限。"""
    security = c.WinDLL("advapi32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    security.OpenThreadToken.argtypes = [w.HANDLE, w.DWORD, w.BOOL, c.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    result = {}
    for label in ("进程", "线程") if thread else ("进程",):
        token = w.HANDLE()
        ok = security.OpenProcessToken(process, 8, c.byref(token)) if label == "进程" else security.OpenThreadToken(thread, 8, True, c.byref(token))
        if not ok:
            result[label] = {"查询错误": c.get_last_error()}
            continue
        try:
            item = {}
            for kind, name in ((18, "提升类别"), (20, "已提升"), (21, "存在限制"),
                               (26, "界面访问"), (29, "应用容器")):
                value, needed = w.DWORD(), w.DWORD()
                if security.GetTokenInformation(token, kind, c.byref(value), 4, c.byref(needed)):
                    item[name] = value.value
            statistics, needed = c.create_string_buffer(64), w.DWORD()
            if security.GetTokenInformation(token, 10, statistics, len(statistics), c.byref(needed)):
                item["认证会话"] = hex(struct.unpack_from("<Q", statistics, 8)[0])
            result[label] = item
        finally:
            kernel.CloseHandle(token)
    return result


class WindowStationObserver:
    def __init__(self, kernel, process, memory, locate):
        self.kernel, self.process = kernel, process
        self.memory, self.locate = memory, locate
        self.breakpoints, self.records = {}, []
        kernel.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p]
        kernel.WriteProcessMemory.restype = w.BOOL
        kernel.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]
        kernel.SetThreadContext.argtypes = [w.HANDLE, c.c_void_p]
        kernel.SetThreadContext.restype = w.BOOL

    def write(self, address, value):
        source = c.create_string_buffer(value)
        if not self.kernel.WriteProcessMemory(self.process, address, source, len(value), None):
            raise c.WinError(c.get_last_error())
        self.kernel.FlushInstructionCache(self.process, address, len(value))

    def install(self, base):
        for offset, label in ((0x91BD6, "首次调用前"), (0x91BDC, "首次调用后"),
                              (0x91C6C, "重试调用前"), (0x91C72, "重试调用后")):
            address = base + offset
            self.breakpoints[address] = (self.memory(self.process, address, 1), label, base)
            self.write(address, b"\xcc")

    def handle(self, address, tid, modules):
        if address not in self.breakpoints:
            return False
        original, label, base = self.breakpoints.pop(address)
        thread = self.kernel.OpenThread(0x58, False, tid)
        if not thread:
            raise c.WinError(c.get_last_error())
        try:
            backing = c.create_string_buffer(1248)
            context_address = (c.addressof(backing) + 15) & ~15
            context = (c.c_ubyte * 1232).from_address(context_address)
            c.c_uint32.from_address(context_address + 48).value = 0x100003
            if not self.kernel.GetThreadContext(thread, context):
                raise c.WinError(c.get_last_error())
            values = {name: struct.unpack_from("<Q", bytes(context), offset)[0] for name, offset in
                      {"rax":120, "rcx":128, "rdx":136, "r8":184, "r9":192, "rip":248}.items()}
            record = {"阶段": label, "寄存器": {key: hex(value) for key, value in values.items()}}
            record["令牌"] = token_information(self.process, thread)
            if label.endswith("前"):
                attributes = self.memory(self.process, values["r9"], 24)
                record["安全属性"] = attributes.hex()
                if len(attributes) == 24:
                    descriptor = struct.unpack_from("<Q", attributes, 8)[0]
                    header = self.memory(self.process, descriptor, 40)
                    record["安全描述符头"] = header.hex()
                    if len(header) >= 20:
                        control = struct.unpack_from("<H", header, 2)[0]
                        dacl = descriptor + struct.unpack_from("<I", header, 16)[0] if control & 0x8000 else struct.unpack_from("<Q", header, 32)[0]
                        acl_header = self.memory(self.process, dacl, 8)
                        if len(acl_header) == 8:
                            acl_size = struct.unpack_from("<H", acl_header, 2)[0]
                            record["访问控制表"] = self.memory(self.process, dacl, min(acl_size, 4096)).hex()
                slot = self.memory(self.process, base + 0x17BBD8, 8)
                if len(slot) == 8:
                    record["被调函数"] = self.locate(struct.unpack("<Q", slot)[0], modules)
            native = c.WinDLL("ntdll")
            native.NtQueryInformationThread.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.ULONG, c.c_void_p]
            native.NtQueryInformationThread.restype = c.c_long
            basic = c.create_string_buffer(48)
            if native.NtQueryInformationThread(thread, 0, basic, len(basic), None) == 0:
                teb = struct.unpack_from("<Q", basic, 8)[0]
                error = self.memory(self.process, teb + 0x68, 4)
                if len(error) == 4:
                    record["最后系统错误"] = struct.unpack("<I", error)[0]
            self.records.append(record)
            self.write(address, original)
            struct.pack_into("<Q", context, 248, address)
            if not self.kernel.SetThreadContext(thread, context):
                raise c.WinError(c.get_last_error())
            return True
        finally:
            self.kernel.CloseHandle(thread)

    def restore(self):
        for address, (original, _, _) in self.breakpoints.items():
            self.write(address, original)
        self.breakpoints.clear()
