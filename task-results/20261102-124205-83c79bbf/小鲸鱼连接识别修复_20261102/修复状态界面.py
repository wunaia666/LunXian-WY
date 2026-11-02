"""区分已识别客户端和机器人通道，不把任何一端上线伪装为另一端成功。"""

import re
from pathlib import Path


def main():
    path = Path(__file__).resolve().parent / "monitor/dashboard.html"
    text = path.read_text(encoding="utf-8")
    replacement = """async function status(){
const [s,d]=await Promise.all([api('/api/status'),api('/api/database')]);
const connection=s.connection||{},ready=connection.phase==='client_ready',known=connection.account==='3768021466';
text('account-status',s.qq?'机器人已连接':ready?'客户端已识别':connection.phase==='waiting_bridge'?'通道待就绪':'等待连接');
$('account-status').className=s.qq?'good':'warn';
text('account-sub',s.qq?'账号 3768021466 · 机器人通道在线':known?'账号 3768021466 · 机器人尚未接入':connection.message||s.qq_state||'等待核对连接');
text('robot-status',s.astrbot?'正常运行':'尚未就绪');$('robot-status').className=s.astrbot?'good':'warn';
text('memory-total',d.total===undefined?'—':d.total+' 条');text('memory-sub',(d.permanent||0)+' 条长期保存 · '+(d.pinned||0)+' 条已锁定');
text('request-time',s.request_at||'尚无新请求');text('updated','更新于 '+s.at);
const info=s.chat_start||{},phase=s.qq?'online':info.phase;
const message=s.qq?'小鲸鱼机器人通道已连接，数据检查结果见下方。':phase==='starting'?info.message:connection.message||info.message||'点击连接，核对小鲸鱼账号。';
text('start-note',message);text('login-state',message);
$('login-start').disabled=phase==='starting';$('login-start').textContent=s.qq?'重新核对连接':ready?'连接已登录账号':'启动或核对连接';
document.querySelectorAll('.login-trigger').forEach(button=>button.textContent=s.qq?'查看连接状态':ready?'连接已登录账号':'登录或连接小鲸鱼');
if(s.qq&&state.lastOnline!==true)post('/api/checks/run').catch(error=>tell(error.message));state.lastOnline=s.qq;return d;
}
"""
    text, count = re.subn(
        r"async function status\(\).*?\n", lambda _: replacement, text, count=1
    )
    if count != 1:
        raise RuntimeError("未找到唯一状态更新函数")
    text = text.replace("<h2>登录小鲸鱼账号</h2>", "<h2>连接小鲸鱼账号</h2>")
    text = text.replace("正在启动登录并核对目标账号……", "正在连接并核对小鲸鱼账号……")
    text = text.replace(
        "<li>从这里启动小鲸鱼专用账号。当前有其他账号运行时，会先提示你核对。</li><li>在小鲸鱼登录窗口完成扫码或验证。本页不会代填密码或验证码。</li><li>账号核对成功后，自动检查机器人、记忆数据库、会话绑定和指定原声。</li>",
        "<li>已经登录时，核对小鲸鱼账号并连接现有窗口。</li><li>账号未核实或不一致时会停下，不关闭或切换其他账号。</li><li>机器人通道连接成功后，自动检查服务、记忆、会话绑定和声音。</li>",
    )
    path.write_text(text, encoding="utf-8")
    print("客户端识别与机器人连接状态已分开显示。")


if __name__ == "__main__":
    main()
