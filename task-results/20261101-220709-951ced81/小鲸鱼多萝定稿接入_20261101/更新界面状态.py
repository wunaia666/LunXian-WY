"""按已确认声音的实际能力更新现有语音表单，保留页面样式与其他操作。"""

from pathlib import Path

path = Path(__file__).resolve().parent / "monitor/dashboard.html"
text = path.read_text(encoding="utf-8")
old = "text('voice-engine','当前候选为本地模型克隆；上方播放器是目标原声。文件来源一致不代表音色一致，仍需听感验收。');"
new = "const fixed=d.configuration?.backend==='gptsovits';state.fixedVoice=fixed;if(fixed){$('voice-profile').value='expressive';$('voice-profile').options[0].textContent='已确认声音 · 固定参数';$('voice-mood').value='normal';$('voice-tempo').value='1.0'}for(const id of ['voice-profile','voice-mood','voice-tempo']){$(id).disabled=fixed;$(id).title=fixed?'沿用已验收声音的原速与自然语气，其他档位尚未验收':''}text('voice-profile-note',fixed?'当前使用你认可的第十条声音。保持原训练配对、原速与自然语气；其他情绪和速度尚未验收。':'情绪指令会传入模型；能否自然、像原声仍需试听。');text('voice-engine',fixed?'日常合成已选用第十条声音的模型与参数；下方可继续试听新文字。':'当前候选为本地模型克隆；上方播放器是目标原声。文件来源一致不代表音色一致，仍需听感验收。');"
if text.count(old) != 1:
    raise RuntimeError("没有找到唯一的语音状态更新位置")
text = text.replace(old, new)
text = text.replace(
    "(j.profile==='stable'?'无情绪对照':'情绪指令')",
    "(j.meta?.backend_actual==='gptsovits'?'已确认声音参数':j.profile==='stable'?'无情绪对照':'情绪指令')",
)
path.write_text(text, encoding="utf-8")
print("已更新已确认声音的状态、禁用说明与真实参数标签。")
