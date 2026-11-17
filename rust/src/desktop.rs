//! Windows desktop access through the PowerShell bridge: top-level windows,
//! focus, screenshots, the Start-menu app catalog and registry app paths.

use crate::host::{self, Res};
use serde::Deserialize;
use serde_json::{Value, json};

/// Bridge handlers for this module (PowerShell, appended to the bridge).
pub const PS_HANDLERS: &str = r#####"
Add-Type -ReferencedAssemblies System.Drawing, System.Windows.Forms -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class JarvisWindow {
  public long hwnd; public string title; public int pid; public string path; public bool foreground; public bool iconic;
}
public static class JarvisWin {
  delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc proc, IntPtr lParam);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextW(IntPtr hwnd, StringBuilder text, int max);
  [DllImport("user32.dll")] static extern int GetWindowTextLengthW(IntPtr hwnd);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out int pid);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
  [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr hwnd);
  [DllImport("user32.dll")] static extern IntPtr SetActiveWindow(IntPtr hwnd);
  [DllImport("user32.dll")] static extern IntPtr SetFocus(IntPtr hwnd);
  [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
  [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(int access, bool inherit, int pid);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern bool QueryFullProcessImageNameW(IntPtr process, int flags, StringBuilder name, ref int size);

  public static string ProcessPath(int pid) {
    IntPtr h = OpenProcess(0x1000, false, pid);
    if (h == IntPtr.Zero) return null;
    try {
      var buffer = new StringBuilder(32768); int size = buffer.Capacity;
      return QueryFullProcessImageNameW(h, 0, buffer, ref size) ? buffer.ToString() : null;
    } finally { CloseHandle(h); }
  }
  public static JarvisWindow[] List(bool titledOnly) {
    var result = new List<JarvisWindow>();
    IntPtr fg = GetForegroundWindow();
    var paths = new Dictionary<int, string>();
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      int length = GetWindowTextLengthW(h);
      if (titledOnly && length == 0) return true;
      var text = new StringBuilder(length + 1);
      GetWindowTextW(h, text, length + 1);
      int pid; GetWindowThreadProcessId(h, out pid);
      string path;
      if (!paths.TryGetValue(pid, out path)) { path = ProcessPath(pid); paths[pid] = path; }
      result.Add(new JarvisWindow { hwnd = h.ToInt64(), title = text.ToString(), pid = pid, path = path, foreground = h == fg, iconic = IsIconic(h) });
      return true;
    }, IntPtr.Zero);
    return result.ToArray();
  }
  public static long Foreground() { return GetForegroundWindow().ToInt64(); }
  public static bool Focus(long handle) {
    IntPtr hwnd = new IntPtr(handle);
    try {
      if (IsIconic(hwnd)) ShowWindow(hwnd, 9);
      SetForegroundWindow(hwnd);
      if (GetForegroundWindow() == hwnd) return true;
    } catch { }
    // Join both input queues involved in the foreground switch.
    IntPtr fg = GetForegroundWindow();
    uint own = GetCurrentThreadId(); int ignored;
    uint fgThread = fg == IntPtr.Zero ? 0 : GetWindowThreadProcessId(fg, out ignored);
    uint target = GetWindowThreadProcessId(hwnd, out ignored);
    var attached = new List<uint>();
    try {
      foreach (uint t in new uint[] { fgThread, target }) {
        if (t != 0 && t != own && !attached.Contains(t) && AttachThreadInput(own, t, true)) attached.Add(t);
      }
      if (IsIconic(hwnd)) ShowWindow(hwnd, 9);
      BringWindowToTop(hwnd); SetForegroundWindow(hwnd); SetActiveWindow(hwnd); SetFocus(hwnd);
      return GetForegroundWindow() == hwnd;
    } catch { return false; }
    finally { attached.Reverse(); foreach (uint t in attached) AttachThreadInput(own, t, false); }
  }
  public static string Screenshot(bool allScreens) {
    try { SetProcessDPIAware(); } catch { }
    System.Drawing.Rectangle bounds = allScreens ? System.Windows.Forms.SystemInformation.VirtualScreen
                                                 : System.Windows.Forms.Screen.PrimaryScreen.Bounds;
    using (var bitmap = new System.Drawing.Bitmap(bounds.Width, bounds.Height))
    using (var g = System.Drawing.Graphics.FromImage(bitmap))
    using (var stream = new System.IO.MemoryStream()) {
      g.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, bounds.Size);
      bitmap.Save(stream, System.Drawing.Imaging.ImageFormat.Png);
      return Convert.ToBase64String(stream.ToArray());
    }
  }
}
'@
$HANDLERS['win.list'] = { param($a) ,@([JarvisWin]::List([bool]$a.titled)) }
$HANDLERS['win.foreground'] = { param($a) [JarvisWin]::Foreground() }
$HANDLERS['win.focus'] = { param($a) [JarvisWin]::Focus([long]$a.hwnd) }
$HANDLERS['screen.capture'] = { param($a) [JarvisWin]::Screenshot([bool]$a.all) }
$HANDLERS['reg.classes'] = { param($a) Test-Path -LiteralPath ('Registry::HKEY_CLASSES_ROOT\' + [string]$a.key) }
$HANDLERS['apps.apppath'] = { param($a)
  foreach ($hive in 'HKCU:', 'HKLM:') {
    try {
      $value = (Get-Item -LiteralPath ($hive + '\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\' + [string]$a.exe)).GetValue('')
      if ($value) { return ([string]$value).Trim('"') }
    } catch { }
  }
  $null }
"#####;

#[derive(Debug, Clone, Deserialize)]
pub struct Window {
    pub hwnd: i64,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub pid: i64,
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub foreground: bool,
    #[serde(default)]
    pub iconic: bool,
}

impl Window {
    /// Lower-case executable file name of the owning process.
    pub fn image_name(&self) -> Option<String> {
        self.path.as_deref().map(|p| host::fs::file_name(p).to_lowercase())
    }
}

/// Visible top-level windows with their owning process paths.
pub async fn windows(titled_only: bool) -> Res<Vec<Window>> {
    let value = host::ps("win.list", json!({ "titled": titled_only })).await?;
    let list = match value {
        Value::Array(items) => items,
        Value::Null => Vec::new(),
        other => vec![other],
    };
    Ok(list.into_iter().filter_map(|w| serde_json::from_value(w).ok()).collect())
}

pub async fn focus(hwnd: i64) -> bool {
    host::ps("win.focus", json!({ "hwnd": hwnd })).await.ok().and_then(|v| v.as_bool()).unwrap_or(false)
}

pub async fn foreground() -> i64 {
    host::ps("win.foreground", json!({})).await.ok().and_then(|v| v.as_i64()).unwrap_or(0)
}

/// PNG screenshot as base64 (primary display unless `all_screens`).
pub async fn screenshot(all_screens: bool) -> Option<String> {
    host::ps("screen.capture", json!({ "all": all_screens })).await.ok().and_then(|v| v.as_str().map(str::to_string))
}

/// Registered executable path from `App Paths`, if present.
pub async fn app_path(exe: &str) -> Option<String> {
    let value = host::ps("apps.apppath", json!({ "exe": exe })).await.ok()?;
    value.as_str().filter(|p| host::fs::stat(p).is_some_and(|s| s.file)).map(str::to_string)
}

fn powershell() -> String {
    format!("{}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", crate::config::get_or("SYSTEMROOT", "C:\\Windows"))
}

/// Runs a self-contained PowerShell command in its own process (slow commands
/// that must not block the shared bridge).
pub async fn run_powershell(command: &str, timeout_ms: u32) -> Res<String> {
    let script = format!("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; {command}");
    let out = host::run(
        &powershell(),
        &["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", &script],
        json!({ "timeoutMs": timeout_ms }),
    )
    .await;
    if out.code != 0 {
        return Err(crate::util::take(out.stderr.trim(), 300));
    }
    Ok(out.stdout.trim_start_matches('\u{feff}').to_string())
}

pub fn powershell_path() -> String {
    powershell()
}
