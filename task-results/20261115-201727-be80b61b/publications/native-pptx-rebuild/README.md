# 截图分层复刻与原生可编辑精修

版本 1.4。给编码助手一张幻灯片截图，它会按原图重建文字、色框、背景和插画，并交付可编辑演示文稿。随包的两个脚本用于检查文稿和对照渲染结果。

## 下载与安装

1. 打开[发布页](https://github.com/wunaia666/LunXian-WY/releases/tag/native-pptx-rebuild-v1.4)，下载 `native-pptx-rebuild-v1.4.zip` 并解压。
2. 把解压得到的整个 `native-pptx-rebuild` 目录放到项目下的 `.agents/skills/`，或放到用户主目录下的 `.agents/skills/` 供多个项目使用。保留目录结构，确保 `SKILL.md` 直接位于 `native-pptx-rebuild` 里。
3. 回到编码助手，输入 `$native-pptx-rebuild` 选中技能。若列表中未出现，重启应用后再试。[查看官方技能安装说明](https://learn.chatgpt.com/docs/build-skills)

## 复刻自己的截图

上传清晰的原始截图。有对应原稿时可以一并上传，便于提取原始插画和核对字体。需要把结果放回现有演示文稿时，附上最新底稿和目标页码。

复制下面这段指令，连同截图一起发送。

```text
使用 $native-pptx-rebuild，按我上传的截图复刻这一页。
保留原图的文字、布局和配色。文字和色框用原生对象，背景可在「设置背景格式」里换色。
带文字的斜边色框需要在同一个形状上改字、改填色和编辑顶点。
复杂插画保留为完整的透明图片，移开文字、色框和插画后逐层检查残字、残片。
交付可编辑演示文稿、预览、对象登记表和验收记录，列出仍有差异的区域。
```

## 试用演示文稿

在[发布页](https://github.com/wunaia666/LunXian-WY/releases/tag/native-pptx-rebuild-v1.4)下载 `editable-slide-demo.pptx`，用微软演示文稿软件打开并另存一份练习。样例是一页专为发布制作的《潮汐灯塔》。`sample-reference.jpg` 是从样例导出的练习图，可用于体验从截图开始复刻。完整样例包还附透明素材、对象登记和检查记录。

| 想验证什么 | 在样例中怎么操作 |
| --- | --- |
| 原生文字 | 双击「潮汐灯塔」修改文字或字体。 |
| 斜边色框 | 选中「夜间观察」色框。双击改字，在「形状填充」中换色，右键选「编辑顶点」后拖动右侧节点。 |
| 整页背景 | 在页面空白处右键，打开「设置背景格式」，确认页边和留白区域一起变色。 |
| 透明插画与无残留 | 选中灯塔插画，拖到新的位置，或从「图片格式」中更换图片。再依次移开文字和色框，查看原位置。插画可作为一个整体移动、缩放和替换。 |

样例已完成包结构、格式检查、本机原生打开与渲染。实际改字、换色、编辑顶点、替图和移开无残留操作尚待验证，检查记录逐项标明了状态。

## 运行验收工具

以下命令在解压后的技能目录中运行。验收脚本使用第三版脚本解释器，发布版在 3.11 上验证。同尺寸原生导出需要视窗系统和已安装的微软桌面演示文稿软件。其他系统可运行静态检查及图像对照。

```powershell
python -m pip install -r requirements.txt
python -X utf8 scripts/audit_pptx.py ./复刻稿.pptx --output ./检查/对象检查.json --office --preview-dir ./预览 --reference-image ./原图.png --reference-page 1
python -X utf8 scripts/compare_visual.py ./原图.png ./预览/原尺寸对照/page_001.png --pptx ./复刻稿.pptx --output-dir ./对照 --audit-record ./检查/对象检查.json
```

如需静态检查，只传入文稿路径和 `--output`。如需按对象定位差异，可加上 `--objects` 和登记表路径，再用 `--crop-ids` 指定要放大的对象编号。改字、换色、编辑顶点及移开后无残留，仍需在文稿副本中实际操作验证。

- [技能正文](SKILL.md)
- [对象登记模板](assets/对象登记模板.json)
- [复刻与动效故障排查](references/复刻与动效故障排查.md)
- [版本修改记录](修改说明.md)
