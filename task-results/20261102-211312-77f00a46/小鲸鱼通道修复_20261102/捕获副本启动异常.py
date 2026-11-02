"""仅启动获准的验证副本，记录异常现场后交还系统正常处理。"""

import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import struct
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).parent
EXE = Path(r"E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe")
OUTPUT = ROOT / "证据/副本启动调试.local.json"
K = c.WinDLL("kernel32", use_last_error=True)
D = c.WinDLL("dbghelp", use_last_error=True)
P = c.c_void_p
Q = c.c_uint64


class Startup(c.Structure):
    _fields_ = [("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
                ("title", w.LPWSTR), ("x", w.DWORD), ("y", w.DWORD),
                ("cx", w.DWORD), ("cy", w.DWORD), ("chars_x", w.DWORD),
                ("chars_y", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
                ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_ptr", P),
                ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE)]


class Process(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE),
                ("pid", w.DWORD), ("tid", w.DWORD)]


class Event(c.Structure):
    _fields_ = [("code", w.DWORD), ("pid", w.DWORD), ("tid", w.DWORD),
                ("padding", w.DWORD), ("data", c.c_ubyte * 160)]


def setup():
    signatures = {
        "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, P, P, w.BOOL, w.DWORD, P,
                            w.LPCWSTR, P, P], w.BOOL),
        "WaitForDebugEventEx": ([P, w.DWORD], w.BOOL),
        "ContinueDebugEvent": ([w.DWORD, w.DWORD, w.DWORD], w.BOOL),
        "DebugActiveProcessStop": ([w.DWORD], w.BOOL),
        "DebugSetProcessKillOnExit": ([w.BOOL], w.BOOL),
        "GetThreadContext": ([w.HANDLE, P], w.BOOL),
        "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        "CloseHandle": ([w.HANDLE], w.BOOL),
        "ReadProcessMemory": ([w.HANDLE, P, P, c.c_size_t, P], w.BOOL),
        "GetFinalPathNameByHandleW": ([w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD], w.DWORD),
    }
    for name, (args, restype) in signatures.items():
        function = getattr(K, name)
        function.argtypes, function.restype = args, restype
    D.SymInitialize.argtypes = [w.HANDLE, c.c_char_p, w.BOOL]
    D.SymInitialize.restype = w.BOOL
    D.SymCleanup.argtypes = [w.HANDLE]
    D.SymSetOptions.argtypes = [w.DWORD]
    D.StackWalk64.argtypes = [w.DWORD, w.HANDLE, w.HANDLE, P, P, P, P, P, P]
    D.StackWalk64.restype = w.BOOL
    assert c.sizeof(Startup) == 104 and c.sizeof(Process) == 24
    assert c.sizeof(Event) == 176 and Event.data.offset == 16


def memory(handle, address, size):
    buffer = c.create_string_buffer(size)
    count = c.c_size_t()
    K.ReadProcessMemory(handle, address, buffer, size, c.byref(count))
    return buffer.raw[:count.value]


def handle_path(handle):
    value = c.create_unicode_buffer(32768)
    size = K.GetFinalPathNameByHandleW(handle, value, len(value), 0)
    return value.value.removeprefix("\\\\?\\") if 0 < size < len(value) else ""


def locate(address, modules):
    for base, item in modules.items():
        if base <= address < base + item["size"]:
            return {"模块": Path(item["path"]).name, "偏移": hex(address - base)}
    return {"模块": "未确定", "地址": hex(address)}


def environment():
    user = c.WinDLL("user32",use_last_error=True)
    user.GetProcessWindowStation.restype = w.HANDLE
    user.GetThreadDesktop.argtypes = [w.DWORD]
    user.GetThreadDesktop.restype = w.HANDLE
    user.GetUserObjectInformationW.argtypes = [w.HANDLE,c.c_int,P,w.DWORD,P]
    result = {}
    for label, handle in (("窗口站",user.GetProcessWindowStation()),
                          ("桌面",user.GetThreadDesktop(K.GetCurrentThreadId()))):
        buffer = c.create_unicode_buffer(512)
        needed = w.DWORD()
        if user.GetUserObjectInformationW(handle,2,buffer,c.sizeof(buffer),c.byref(needed)):
            result[label] = buffer.value
    K.QueryInformationJobObject.argtypes = [w.HANDLE,c.c_int,P,w.DWORD,P]
    limits = w.DWORD()
    if K.QueryInformationJobObject(None,4,c.byref(limits),4,None):
        result["当前作业界面限制"] = hex(limits.value)
    K.GetCurrentPackageFullName.argtypes = [P,P]
    count = w.DWORD(512)
    package = c.create_unicode_buffer(count.value)
    result["程序包身份查询状态"] = K.GetCurrentPackageFullName(c.byref(count),package)
    result["程序包身份"] = package.value
    return result


def capture(process, tid, modules):
    thread = K.OpenThread(0x48, False, tid)
    if not thread:
        return {"读取线程失败": c.get_last_error()}
    try:
        # 六十四位线程上下文必须按十六字节对齐。
        backing = c.create_string_buffer(1248)
        address = (c.addressof(backing) + 15) & ~15
        context = (c.c_ubyte * 1232).from_address(address)
        c.c_uint32.from_address(address + 48).value = 0x100003
        if not K.GetThreadContext(thread, context):
            return {"读取上下文失败": c.get_last_error()}
        raw = bytes(context)
        registers = {name: struct.unpack_from("<Q", raw, offset)[0] for name, offset in
                     {"rax":120,"rcx":128,"rdx":136,"rbx":144,"rsp":152,"rbp":160,
                      "rsi":168,"rdi":176,"r8":184,"r9":192,"rip":248}.items()}
        stack = memory(process, registers["rsp"], 8192)
        result = {"寄存器": {key:hex(value) for key,value in registers.items()}, "调用栈": []}
        native = c.WinDLL("ntdll")
        native.NtQueryInformationThread.argtypes = [w.HANDLE,w.DWORD,P,w.ULONG,P]
        native.NtQueryInformationThread.restype = c.c_long
        basic = c.create_string_buffer(48)
        if native.NtQueryInformationThread(thread,0,basic,len(basic),None) == 0:
            teb = struct.unpack_from("<Q",basic,8)[0]
            error = memory(process,teb+0x68,4)
            if len(error) == 4:
                number = struct.unpack("<I",error)[0]
                result["线程最后系统错误"] = {"编号":number,"含义":c.FormatError(number).strip()}
        # 原始栈只保存在本机，避免把账号或认证内容带入上传结果。
        OUTPUT.with_suffix(".stack.bin").write_bytes(stack)
        D.SymSetOptions(0x10 | 0x200 | 0x80000)
        if D.SymInitialize(process, b"", True):
            try:
                frame = c.create_string_buffer(512)
                for offset, name in ((0,"rip"),(32,"rbp"),(48,"rsp")):
                    struct.pack_into("<Q", frame, offset, registers[name])
                    struct.pack_into("<I", frame, offset + 12, 3)
                for _ in range(32):
                    if not D.StackWalk64(0x8664, process, thread, frame, context, None,
                                         c.cast(D.SymFunctionTableAccess64,P),
                                         c.cast(D.SymGetModuleBase64,P), None):
                        break
                    pc, sp = struct.unpack_from("<Q", frame, 0)[0], struct.unpack_from("<Q", frame, 48)[0]
                    if not pc:
                        break
                    result["调用栈"].append({**locate(pc, modules), "栈位置": hex(sp)})
            finally:
                D.SymCleanup(process)
        return result
    finally:
        K.CloseHandle(thread)


def main():
    setup()
    # 只允许这一处验证副本，不接受任意程序或现有进程作为调试目标。
    if not EXE.is_file() or EXE.resolve() != EXE:
        raise RuntimeError("验证副本路径不符合授权范围")
    for item in psutil.process_iter(["name"]):
        if (item.info["name"] or "").lower() == "qq.exe":
            raise RuntimeError("已有聊天客户端进程，停止多开")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    startup, process = Startup(), Process()
    startup.cb = c.sizeof(startup)
    command = c.create_unicode_buffer('"' + str(EXE) + '" --enable-logging')
    if not K.CreateProcessW(str(EXE), command, None, None, False, 2, None,
                            str(EXE.parent), c.byref(startup), c.byref(process)):
        raise c.WinError(c.get_last_error())
    K.DebugSetProcessKillOnExit(False)
    modules, events, debug_strings = {}, [], []
    loader_breakpoint = False
    exited = False
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            event = Event()
            if not K.WaitForDebugEventEx(c.byref(event), 500):
                continue
            status = 0x00010002
            raw = bytes(event.data)
            try:
                if event.code in (3, 6):
                    file = struct.unpack_from("<Q", raw)[0]
                    base = struct.unpack_from("<Q",raw,24 if event.code == 3 else 8)[0]
                    path = handle_path(file) if file else ""
                    header = memory(process.process, base, 4096)
                    size = 0
                    if len(header) > 256 and header[:2] == b"MZ":
                        pe = struct.unpack_from("<I",header,60)[0]
                        if pe + 84 <= len(header):
                            size = struct.unpack_from("<I",header,pe + 80)[0]
                    modules[base] = {"path":path,"size":size}
                    if file:
                        K.CloseHandle(file)
                elif event.code == 8:
                    pointer, unicode, size = struct.unpack_from("<QHH",raw)
                    if len(debug_strings) < 100:
                        data = memory(process.process,pointer,min(size*(2 if unicode else 1),8192))
                        debug_strings.append(data.decode("utf-16-le" if unicode else "utf-8",errors="replace").strip("\0"))
                elif event.code == 1:
                    code = struct.unpack_from("<I",raw)[0]
                    location = struct.unpack_from("<Q",raw,16)[0]
                    first = struct.unpack_from("<I",raw,152)[0]
                    if code == 0x80000003 and not loader_breakpoint and locate(location,modules)["模块"].lower() == "ntdll.dll":
                        loader_breakpoint = True
                    else:
                        entry = {"异常码":hex(code),"首次通知":bool(first),**locate(location,modules)}
                        if code == 0x80000003 or not first:
                            entry["现场"] = capture(process.process,event.tid,modules)
                        events.append(entry)
                        status = 0x80010001
                elif event.code == 5:
                    events.append({"退出码":hex(struct.unpack_from("<I",raw)[0])})
                    exited = True
            finally:
                K.ContinueDebugEvent(event.pid,event.tid,status)
            if exited:
                break
    finally:
        if not exited:
            K.DebugActiveProcessStop(process.pid)
        K.CloseHandle(process.thread)
        K.CloseHandle(process.process)
        result = {"目标":str(EXE),"主程序摘要":hashlib.sha256(EXE.read_bytes()).hexdigest(),
                  "进程号":process.pid,"正常退出事件":exited,"事件":events,"调试输出":debug_strings,
                  "启动器环境":environment(),
                  "边界":"只启动验证副本；未改二进制、注册表或安全设置；未加载机器人；未操作登录"}
        OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"记录":str(OUTPUT),"进程号":process.pid,"已退出":exited,
                          "异常":events},ensure_ascii=False))


if __name__ == "__main__":
    main()
