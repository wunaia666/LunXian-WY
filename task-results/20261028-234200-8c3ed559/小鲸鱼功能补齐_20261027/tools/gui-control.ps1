# gui-control.ps1 - keyboard & mouse control for Windows (Win32 SendInput, zero dependencies)
# Output: one-line JSON on stdout, ASCII-escaped (\uXXXX) so any console codepage can read it.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File gui-control.ps1 -Action info
#   ... -Action cursor
#   ... -Action foreground
#   ... -Action windows
#   ... -Action screenshot [-Path out.png] [-Region "x,y,w,h"]
#   ... -Action move -X 100 -Y 200
#   ... -Action click [-X 100 -Y 200] [-Button left|right|middle] [-Count 2]
#   ... -Action down|up [-Button left]
#   ... -Action drag -X 10 -Y 10 -ToX 500 -ToY 300 [-DurationMs 400]
#   ... -Action scroll [-Delta 3] [(-X -Y)]        # +1 = one notch up, -1 = down
#   ... -Action type -Text "hello" [-DelayMs 5] [-ExpectTitle "*Notepad*"]
#   ... -Action key -Key ENTER [-ExpectTitle *]
#   ... -Action hotkey -Keys "ctrl+shift+s" [-ExpectTitle *]
#   ... -Action activate -Window "*Notepad*"  |  -Action activate -ProcessId 1234
#   ... -Action sleep -Ms 500
#   ... -Action selftest
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('info','selftest','cursor','foreground','windows','screenshot','move','click','down','up','drag','scroll','type','key','hotkey','activate','sleep')]
  [string]$Action,

  [int]$X,
  [int]$Y,
  [int]$ToX,
  [int]$ToY,
  [ValidateSet('left','right','middle')][string]$Button = 'left',
  [int]$Count = 1,
  [int]$Delta = 1,
  [int]$DurationMs = 300,
  [int]$DelayMs = 5,
  [int]$Ms = 500,
  [string]$Text,
  [string]$Key,
  [string]$Keys,
  [string]$Path,
  [string]$Region,
  [string]$ExpectTitle,
  [int]$ExpectProcessId,
  [string]$LiteralTitle,
  [string]$Window,
  [int]$ProcessId
)

$ErrorActionPreference = 'Stop'

$cs = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class Gui
{
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }

    [StructLayout(LayoutKind.Sequential)]
    public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }

    [StructLayout(LayoutKind.Sequential)]
    public struct HARDWAREINPUT { public uint uMsg; public ushort wParamL; public ushort wParamH; }

    [StructLayout(LayoutKind.Explicit)]
    public struct InputUnion
    {
        [FieldOffset(0)] public MOUSEINPUT mi;
        [FieldOffset(0)] public KEYBDINPUT ki;
        [FieldOffset(0)] public HARDWAREINPUT hi;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT { public uint type; public InputUnion U; }

    public const int SM_CXSCREEN = 0;
    public const int SM_CYSCREEN = 1;
    public const int SM_XVIRTUALSCREEN = 76;
    public const int SM_YVIRTUALSCREEN = 77;
    public const int SM_CXVIRTUALSCREEN = 78;
    public const int SM_CYVIRTUALSCREEN = 79;

    public const uint MOUSEEVENTF_MOVE = 0x0001;
    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;
    public const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    public const uint MOUSEEVENTF_RIGHTUP = 0x0010;
    public const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020;
    public const uint MOUSEEVENTF_MIDDLEUP = 0x0040;
    public const uint MOUSEEVENTF_WHEEL = 0x0800;
    public const uint MOUSEEVENTF_HWHEEL = 0x1000;
    public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
    public const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;

    public const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public const uint KEYEVENTF_UNICODE = 0x0004;

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern IntPtr WindowFromPoint(POINT point);

    [DllImport("user32.dll")]
    public static extern IntPtr GetAncestor(IntPtr window, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);

    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();

    [DllImport("user32.dll")]
    public static extern short VkKeyScan(char ch);

    public static int[] CursorPos()
    {
        POINT p;
        GetCursorPos(out p);
        return new int[] { p.X, p.Y };
    }

    public static uint SendMouse(uint flags, uint data)
    {
        INPUT[] a = new INPUT[1];
        a[0].type = 0;
        a[0].U.mi.dwFlags = flags;
        a[0].U.mi.mouseData = data;
        return SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
    }

    public static uint SendMouseAbs(uint flags, int x, int y)
    {
        int vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
        int vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
        int vw = Math.Max(GetSystemMetrics(SM_CXVIRTUALSCREEN) - 1, 1);
        int vh = Math.Max(GetSystemMetrics(SM_CYVIRTUALSCREEN) - 1, 1);
        INPUT[] a = new INPUT[1];
        a[0].type = 0;
        a[0].U.mi.dx = (int)Math.Round((x - vx) * 65535.0 / vw);
        a[0].U.mi.dy = (int)Math.Round((y - vy) * 65535.0 / vh);
        a[0].U.mi.dwFlags = flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
        return SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
    }

    public static uint SendWheel(int delta, bool horizontal)
    {
        return SendMouse(horizontal ? MOUSEEVENTF_HWHEEL : MOUSEEVENTF_WHEEL, (uint)delta);
    }

    public static uint SendVk(ushort vk, bool up, bool extended)
    {
        INPUT[] a = new INPUT[1];
        a[0].type = 1;
        a[0].U.ki.wVk = vk;
        a[0].U.ki.dwFlags = (up ? KEYEVENTF_KEYUP : 0u) | (extended ? KEYEVENTF_EXTENDEDKEY : 0u);
        return SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
    }

    public static uint SendUnicode(ushort scan, bool up)
    {
        INPUT[] a = new INPUT[1];
        a[0].type = 1;
        a[0].U.ki.wScan = scan;
        a[0].U.ki.dwFlags = KEYEVENTF_UNICODE | (up ? KEYEVENTF_KEYUP : 0u);
        return SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
    }

    public static string ForegroundTitle()
    {
        StringBuilder sb = new StringBuilder(512);
        GetWindowText(GetForegroundWindow(), sb, sb.Capacity);
        return sb.ToString();
    }

    public static uint ForegroundProcessId()
    {
        uint pid;
        GetWindowThreadProcessId(GetForegroundWindow(), out pid);
        return pid;
    }
}
'@

if (-not ('Gui' -as [type])) {
  Add-Type -TypeDefinition $cs -Language CSharp | Out-Null
}
try { [void][Gui]::SetProcessDPIAware() } catch { }

$script:VkMap = @{
  'ENTER' = 0x0D; 'RETURN' = 0x0D; 'TAB' = 0x09; 'ESC' = 0x1B; 'ESCAPE' = 0x1B;
  'SPACE' = 0x20; 'BACKSPACE' = 0x08; 'BKSP' = 0x08; 'DELETE' = 0x2E; 'DEL' = 0x2E;
  'INSERT' = 0x2D; 'INS' = 0x2D; 'HOME' = 0x24; 'END' = 0x23;
  'PGUP' = 0x21; 'PAGEUP' = 0x21; 'PGDN' = 0x22; 'PAGEDOWN' = 0x22;
  'UP' = 0x26; 'DOWN' = 0x28; 'LEFT' = 0x25; 'RIGHT' = 0x27;
  'CTRL' = 0x11; 'CONTROL' = 0x11; 'SHIFT' = 0x10; 'ALT' = 0x12;
  'WIN' = 0x5B; 'LWIN' = 0x5B; 'RWIN' = 0x5C;
  'CAPSLOCK' = 0x14; 'NUMLOCK' = 0x90; 'SCROLLLOCK' = 0x91;
  'PRINTSCREEN' = 0x2C; 'PRTSC' = 0x2C; 'PAUSE' = 0x13; 'APPS' = 0x5D; 'MENU' = 0x5D
}

$script:ModMap = @{
  'CTRL' = 0x11; 'CONTROL' = 0x11; 'LCTRL' = 0xA2; 'RCTRL' = 0xA3;
  'SHIFT' = 0x10; 'LSHIFT' = 0xA0; 'RSHIFT' = 0xA1;
  'ALT' = 0x12; 'LALT' = 0xA4; 'RALT' = 0xA5;
  'WIN' = 0x5B; 'LWIN' = 0x5B; 'RWIN' = 0x5C; 'CMD' = 0x5B
}

function To-AsciiJson($obj) {
  $json = $obj | ConvertTo-Json -Depth 8 -Compress
  $sb = New-Object System.Text.StringBuilder
  foreach ($ch in $json.ToCharArray()) {
    $code = [int]$ch
    if ($code -ge 32 -and $code -le 126) { [void]$sb.Append($ch) }
    else { [void]$sb.AppendFormat('\u{0:x4}', $code) }
  }
  return $sb.ToString()
}

function Emit($obj) {
  Write-Output (To-AsciiJson $obj)
}

function Test-Extended([int]$vk) {
  if ($vk -ge 0x21 -and $vk -le 0x2E) { return $true }
  if (@(0x5B, 0x5C, 0x5D, 0x90, 0xA3, 0xA5) -contains $vk) { return $true }
  return $false
}

function Send-KeyVk([int]$vk) {
  $ext = Test-Extended $vk
  $r1 = [int][Gui]::SendVk([uint16]$vk, $false, $ext)
  $r2 = [int][Gui]::SendVk([uint16]$vk, $true, $ext)
  return @($r1, $r2)
}

function Get-Vk([string]$name) {
  $n = $name.Trim().ToUpperInvariant()
  if ($script:VkMap.ContainsKey($n)) { return [int]$script:VkMap[$n] }
  if ($n -match '^F([1-9]|1[0-9]|2[0-4])$') { return (0x6F + [int]$Matches[1]) }
  if ($n.Length -eq 1) {
    $c = [char]$n[0]
    if ($c -match '[A-Za-z0-9]') { return [int]([char]::ToUpper($c)) }
    $v = [Gui]::VkKeyScan($c)
    if ($v -ne -1) { return ($v -band 0xFF) }
  }
  throw "Unknown key name: $name"
}

function Get-ForegroundInfo {
  $pidFg = [Gui]::ForegroundProcessId()
  $procName = ''
  try { $procName = (Get-Process -Id $pidFg -ErrorAction Stop).ProcessName } catch { }
  return [ordered]@{
    pid = [int]$pidFg
    process = $procName
    title = [Gui]::ForegroundTitle()
  }
}

function Assert-Foreground([string]$pattern) {
  if (-not $pattern) { return }
  $fg = Get-ForegroundInfo
  if ($ExpectProcessId -and $fg.pid -ne $ExpectProcessId) { throw '前台进程已改变，未输入' }
  if ($fg.process -in @('QQ','Weixin','WeChat','WXWork','dnplayer','ldplayer')) { throw '此窗口不属于电脑操作目标' }
  $matches = if ($LiteralTitle -eq 'true') { $fg.title -ceq $pattern } else { $fg.title -like $pattern }
  if (-not $matches) {
    throw "Foreground mismatch: current='$($fg.title)' expected-like='$pattern'"
  }
}

$hasXY = $PSBoundParameters.ContainsKey('X') -and $PSBoundParameters.ContainsKey('Y')

function Assert-PointTarget([int]$pointX, [int]$pointY) {
  if (-not $ExpectProcessId) { return }
  $point = New-Object 'Gui+POINT'
  $point.X = $pointX; $point.Y = $pointY
  $handle = [Gui]::GetAncestor([Gui]::WindowFromPoint($point), 2)
  [uint32]$pointProcess = 0
  [void][Gui]::GetWindowThreadProcessId($handle, [ref]$pointProcess)
  if ($pointProcess -ne $ExpectProcessId) { throw '坐标落在其他窗口，本次没有输入' }
}

try {
  switch ($Action) {

    'info' {
      $c = [Gui]::CursorPos()
      Emit @{
        ok = $true; action = 'info'
        primary = @{ width = [Gui]::GetSystemMetrics(0); height = [Gui]::GetSystemMetrics(1) }
        virtualDesktop = @{ x = [Gui]::GetSystemMetrics(76); y = [Gui]::GetSystemMetrics(77); width = [Gui]::GetSystemMetrics(78); height = [Gui]::GetSystemMetrics(79) }
        cursor = @{ x = $c[0]; y = $c[1] }
        foreground = (Get-ForegroundInfo)
      }
    }

    'selftest' {
      $checks = [ordered]@{}
      $sz = [System.Runtime.InteropServices.Marshal]::SizeOf([type]'Gui+INPUT')
      $expected = 40; if ([IntPtr]::Size -eq 4) { $expected = 28 }
      $checks['inputStructSize'] = @{ value = $sz; expected = $expected; pass = ($sz -eq $expected) }
      $vk = [Gui]::VkKeyScan('a')
      $checks['vkScanA'] = @{ value = ($vk -band 0xFF); expected = 0x41; pass = (($vk -band 0xFF) -eq 0x41) }
      $c = [Gui]::CursorPos()
      $checks['cursorRead'] = @{ value = "$($c[0]),$($c[1])"; pass = $true }
      $checks['screenRead'] = @{ value = "$([Gui]::GetSystemMetrics(0))x$([Gui]::GetSystemMetrics(1))"; pass = ([Gui]::GetSystemMetrics(0) -gt 0) }
      $all = $true
      foreach ($k in @($checks.Keys)) { if (-not $checks[$k].pass) { $all = $false } }
      Emit @{ ok = $all; action = 'selftest'; checks = $checks; note = 'read-only checks; no input events were sent' }
    }

    'cursor' {
      $c = [Gui]::CursorPos()
      Emit @{ ok = $true; action = 'cursor'; x = $c[0]; y = $c[1] }
    }

    'foreground' {
      Emit (@{ ok = $true; action = 'foreground' } + (Get-ForegroundInfo))
    }

    'windows' {
      $list = @()
      Get-Process | Where-Object { $_.MainWindowTitle } | ForEach-Object {
        $list += [ordered]@{ pid = $_.Id; process = $_.ProcessName; title = $_.MainWindowTitle }
      }
      Emit @{ ok = $true; action = 'windows'; count = @($list).Count; windows = @($list) }
    }

    'screenshot' {
      Add-Type -AssemblyName System.Drawing
      Add-Type -AssemblyName System.Windows.Forms
      $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
      if ($Region) {
        $r = @(($Region -split ',') | ForEach-Object { [int]$_.Trim() })
        if ($r.Count -ne 4) { throw 'Region must be x,y,w,h' }
        $srcX = $r[0]; $srcY = $r[1]; $w = $r[2]; $h = $r[3]
      } else {
        $srcX = $vs.X; $srcY = $vs.Y; $w = $vs.Width; $h = $vs.Height
      }
      if ($w -le 0 -or $h -le 0) { throw "Bad capture size: ${w}x${h}" }
      $bmp = New-Object -TypeName System.Drawing.Bitmap -ArgumentList $w, $h
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($srcX, $srcY, 0, 0, (New-Object -TypeName System.Drawing.Size -ArgumentList $w, $h))
      $g.Dispose()
      if (-not $Path) {
        $dir = Join-Path (Split-Path $PSScriptRoot -Parent) 'tmp\screenshots'
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $Path = Join-Path $dir ('shot-{0:yyyyMMdd-HHmmss}.png' -f (Get-Date))
      } else {
        $dir = Split-Path $Path -Parent
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
      }
      $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
      $bmp.Dispose()
      Emit @{ ok = $true; action = 'screenshot'; path = $Path; width = $w; height = $h; bytes = [int](Get-Item $Path).Length }
    }

    'move' {
      Assert-Foreground $ExpectTitle
      if (-not $hasXY) { throw 'move requires -X and -Y' }
      $okSet = [Gui]::SetCursorPos($X, $Y)
      Start-Sleep -Milliseconds 20
      $c = [Gui]::CursorPos()
      Emit @{ ok = [bool]$okSet; action = 'move'; requested = @{ x = $X; y = $Y }; cursor = @{ x = $c[0]; y = $c[1] } }
    }

    'click' {
      Assert-Foreground $ExpectTitle
      if ($hasXY) { Assert-PointTarget $X $Y }
      if ($hasXY) { [void][Gui]::SetCursorPos($X, $Y); Start-Sleep -Milliseconds 30 }
      $flags = @(2, 4)
      if ($Button -eq 'right') { $flags = @(8, 16) }
      elseif ($Button -eq 'middle') { $flags = @(32, 64) }
      $rcs = @()
      $allOk = $true
      for ($i = 0; $i -lt $Count; $i++) {
        $r1 = [int]([Gui]::SendMouse([uint32]$flags[0], 0))
        Start-Sleep -Milliseconds 15
        $r2 = [int]([Gui]::SendMouse([uint32]$flags[1], 0))
        $rcs += @($r1, $r2)
        if ($r1 -ne 1 -or $r2 -ne 1) { $allOk = $false }
        if ($i -lt $Count - 1) { Start-Sleep -Milliseconds 80 }
      }
      $c = [Gui]::CursorPos()
      Emit @{ ok = $allOk; action = 'click'; button = $Button; count = $Count; sendResults = $rcs; cursor = @{ x = $c[0]; y = $c[1] } }
    }

    'down' {
      Assert-Foreground $ExpectTitle
      $f = @{ left = 2; right = 8; middle = 32 }[$Button]
      [void][Gui]::SendMouse([uint32]$f, 0)
      Emit @{ ok = $true; action = 'down'; button = $Button }
    }

    'up' {
      Assert-Foreground $ExpectTitle
      $f = @{ left = 4; right = 16; middle = 64 }[$Button]
      [void][Gui]::SendMouse([uint32]$f, 0)
      Emit @{ ok = $true; action = 'up'; button = $Button }
    }

    'drag' {
      Assert-PointTarget $X $Y
      Assert-PointTarget $ToX $ToY
      if (-not ($hasXY -and $PSBoundParameters.ContainsKey('ToX') -and $PSBoundParameters.ContainsKey('ToY'))) {
        throw 'drag requires -X -Y -ToX -ToY'
      }
      Assert-Foreground $ExpectTitle
      $dn = @{ left = 2; right = 8; middle = 32 }[$Button]
      $upf = @{ left = 4; right = 16; middle = 64 }[$Button]
      [void][Gui]::SetCursorPos($X, $Y)
      Start-Sleep -Milliseconds 60
      $allOk = ([Gui]::SendMouse([uint32]$dn, 0) -eq 1)
      Start-Sleep -Milliseconds 60
      $dist = [Math]::Sqrt([Math]::Pow($ToX - $X, 2) + [Math]::Pow($ToY - $Y, 2))
      $steps = [int][Math]::Max(10, [Math]::Min(60, $dist / 15))
      $perMs = [Math]::Max(1, [int]($DurationMs / $steps))
      for ($i = 1; $i -le $steps; $i++) {
        $nx = [int][Math]::Round($X + ($ToX - $X) * $i / $steps)
        $ny = [int][Math]::Round($Y + ($ToY - $Y) * $i / $steps)
        if ([Gui]::SendMouseAbs(0x0001, $nx, $ny) -ne 1) { $allOk = $false }
        Start-Sleep -Milliseconds $perMs
      }
      Start-Sleep -Milliseconds 40
      if ([Gui]::SendMouse([uint32]$upf, 0) -ne 1) { $allOk = $false }
      $c = [Gui]::CursorPos()
      Emit @{ ok = $allOk; action = 'drag'; from = @{ x = $X; y = $Y }; to = @{ x = $ToX; y = $ToY }; cursor = @{ x = $c[0]; y = $c[1] } }
    }

    'scroll' {
      Assert-Foreground $ExpectTitle
      if ($hasXY) { Assert-PointTarget $X $Y }
      if ($hasXY) { [void][Gui]::SetCursorPos($X, $Y); Start-Sleep -Milliseconds 30 }
      $sent = [Gui]::SendWheel(($Delta * 120), $false)
      Emit @{ ok = ($sent -eq 1); action = 'scroll'; delta = $Delta }
    }

    'type' {
      if (-not $PSBoundParameters.ContainsKey('Text')) { throw 'type requires -Text' }
      Assert-Foreground $ExpectTitle
      $n = 0
      $allOk = $true
      foreach ($ch in $Text.ToCharArray()) {
        $code = [int]$ch
        if ($code -eq 13) { continue }
        if ($code -eq 10) { if (@(Send-KeyVk 0x0D) -contains 0) { $allOk = $false } }
        elseif ($code -eq 9) { if (@(Send-KeyVk 0x09) -contains 0) { $allOk = $false } }
        else {
          if ([Gui]::SendUnicode([uint16]$code, $false) -ne 1) { $allOk = $false }
          if ([Gui]::SendUnicode([uint16]$code, $true) -ne 1) { $allOk = $false }
        }
        if ($DelayMs -gt 0) { Start-Sleep -Milliseconds $DelayMs }
        $n++
      }
      Emit @{ ok = $allOk; action = 'type'; chars = $n }
    }

    'key' {
      if (-not $Key) { throw 'key requires -Key' }
      Assert-Foreground $ExpectTitle
      $vk = Get-Vk $Key
      $rcs = Send-KeyVk $vk
      $allOk = $true
      foreach ($r in $rcs) { if ($r -ne 1) { $allOk = $false } }
      Emit @{ ok = $allOk; action = 'key'; key = $Key; vk = $vk; sendResults = $rcs }
    }

    'hotkey' {
      if (-not $Keys) { throw 'hotkey requires -Keys (e.g. ctrl+shift+s)' }
      Assert-Foreground $ExpectTitle
      $parts = @($Keys -split '\+' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
      $mods = @()
      $mainKey = -1
      foreach ($p in $parts) {
        $u = $p.ToUpperInvariant()
        if ($script:ModMap.ContainsKey($u)) { $mods += [int]$script:ModMap[$u] }
        else { $mainKey = Get-Vk $p }
      }
      if ($mainKey -lt 0) { throw 'hotkey: no main key found' }
      $allOk = $true
      foreach ($m in $mods) { if ([Gui]::SendVk([uint16]$m, $false, (Test-Extended $m)) -ne 1) { $allOk = $false } }
      Start-Sleep -Milliseconds 15
      if ([Gui]::SendVk([uint16]$mainKey, $false, (Test-Extended $mainKey)) -ne 1) { $allOk = $false }
      Start-Sleep -Milliseconds 15
      if ([Gui]::SendVk([uint16]$mainKey, $true, (Test-Extended $mainKey)) -ne 1) { $allOk = $false }
      for ($i = $mods.Count - 1; $i -ge 0; $i--) {
        if ([Gui]::SendVk([uint16]$mods[$i], $true, (Test-Extended $mods[$i])) -ne 1) { $allOk = $false }
        Start-Sleep -Milliseconds 10
      }
      Emit @{ ok = $allOk; action = 'hotkey'; keys = $Keys }
    }

    'activate' {
      $target = $null
      if ($PSBoundParameters.ContainsKey('ProcessId')) {
        $target = Get-Process -Id $ProcessId -ErrorAction Stop
      } elseif ($Window) {
        $cands = @(Get-Process | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle -like $Window })
        if ($cands.Count -eq 0) { throw "No window matches: $Window" }
        $target = $cands[0]
      } else { throw 'activate requires -Window or -ProcessId' }
      $ws = New-Object -ComObject WScript.Shell
      $did = $ws.AppActivate($target.Id)
      Start-Sleep -Milliseconds 250
      $actual = Get-ForegroundInfo
      Emit @{ ok = ([bool]$did -and $actual.pid -eq $target.Id); action = 'activate'; target = @{ pid = $target.Id; process = $target.ProcessName; title = $target.MainWindowTitle }; foreground = $actual }
    }

    'sleep' {
      Start-Sleep -Milliseconds $Ms
      Emit @{ ok = $true; action = 'sleep'; ms = $Ms }
    }
  }
} catch {
  Emit @{ ok = $false; action = $Action; error = $_.Exception.Message }
}
