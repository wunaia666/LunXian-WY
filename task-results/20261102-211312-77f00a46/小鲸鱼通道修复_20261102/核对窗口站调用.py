"""只读核对验证副本主程序创建窗口站时请求的访问方式。"""

from collections import deque
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent / "分析依赖"))
import capstone
import pefile


def main():
    target = Path(r"E:\sss\小鲸鱼QQ兼容验证\Files\QQ.exe")
    pe = pefile.PE(str(target))
    entries = list(getattr(pe,"DIRECTORY_ENTRY_IMPORT",[])) + list(getattr(pe,"DIRECTORY_ENTRY_DELAY_IMPORT",[]))
    imports = {i.address:i.name.decode() for e in entries for i in e.imports if i.name}
    base = pe.OPTIONAL_HEADER.ImageBase
    decoder = capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
    decoder.detail = True
    previous, lines = deque(maxlen=24), []
    remaining = 0
    print("相关导入", [(hex(address-base), name) for address,name in imports.items() if "WindowStation" in name or "UserObjectSecurity" in name])
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        for item in decoder.disasm(section.get_data(),base+section.VirtualAddress):
            label = ""
            for operand in item.operands:
                if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                    label = imports.get(item.address+item.size+operand.mem.disp,"")
            line = f"{item.address-base:#x} {item.mnemonic} {item.op_str} {label}"
            if label in {"CreateWindowStationW","GetUserObjectSecurity","OpenWindowStationW"}:
                lines.extend(previous)
                lines.append(line)
                remaining = 22
            elif remaining:
                lines.append(line)
                remaining -= 1
            previous.append(line)
    (Path(__file__).parent/"证据/窗口站调用.local.txt").write_text("\n".join(lines),encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
