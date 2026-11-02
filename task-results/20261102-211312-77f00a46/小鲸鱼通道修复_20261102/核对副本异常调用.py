"""只读核对实测异常调用栈附近的指令及文字引用。"""

import bisect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "分析依赖"))
import capstone
import pefile


ROOT = Path(__file__).parent
TARGET = Path(r"E:\sss\小鲸鱼QQ兼容验证\Files\versions\9.9.33-52230\QQNT.dll")


def main():
    pe = pefile.PE(str(TARGET), fast_load=True)
    pe.parse_data_directories(directories=[1, 3])
    base = pe.OPTIONAL_HEADER.ImageBase
    functions = pe.DIRECTORY_ENTRY_EXCEPTION
    starts = [f.struct.BeginAddress for f in functions]
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    imports = {i.address:i.name.decode() for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports if i.name}
    lines = []
    for location in (0x26b6e3a,0x5149a6,0x509338,0x509833,0x211717):
        function = functions[bisect.bisect_right(starts, location)-1].struct
        start, end = function.BeginAddress, function.EndAddress
        lines.append(f"实测栈偏移 {location:#x}，函数 {start:#x} 至 {end:#x}")
        if end-start > 3000:
            start = max(start, location-160)
            end = min(end, location+160)
        for instruction in decoder.disasm(pe.get_data(start,end-start),base+start):
            notes = []
            for operand in instruction.operands:
                if operand.type == capstone.CS_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP:
                    address = instruction.address+instruction.size+operand.mem.disp
                    if address in imports:
                        notes.append(imports[address])
                    elif 0 < address-base < pe.OPTIONAL_HEADER.SizeOfImage:
                        data = pe.get_data(address-base,220)
                        text = data.split(b"\0",1)[0]
                        if len(text)>3 and all(32<=b<127 for b in text):
                            notes.append(text.decode("ascii"))
            lines.append(f"{instruction.address-base:#x} {instruction.mnemonic} {instruction.op_str} {'; '.join(notes)}")
    path = ROOT / "证据/副本异常调用.local.txt"
    path.write_text("\n".join(lines),encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
