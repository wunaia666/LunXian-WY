"""提取本页内联脚本进行语法检查，不运行网页动作。"""

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parent
html = (ROOT/"修复代码/dashboard.html").read_text(encoding="utf-8")
scripts = [match.group(1) for match in re.finditer(r"<script(?:\s[^>]*)?>(.*?)</script>",html,re.S)
           if match.group(1).strip()]
output = ROOT/"证据/网页内联检查.local.js"
output.write_text("\n".join(scripts),encoding="utf-8")
subprocess.run([r"D:\deepseek\Yu\SnowLuma\node.exe","--check",str(output)],check=True)
print("网页内联脚本语法检查通过")
