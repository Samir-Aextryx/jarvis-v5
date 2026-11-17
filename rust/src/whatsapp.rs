//! Verified WhatsApp Beta contact and honest call-capability checks.
//! Jarvis never clicks the call button: automatic calls stay unavailable
//! until dialing, recipient and answered-call checks exist.

use crate::host::{self, Res};
use crate::{apps, desktop, vault};
use base64::Engine;
use base64::engine::general_purpose::STANDARD as B64;
use serde_json::{Value, json};
use std::cell::{Cell, RefCell};

const CONTACT_KEY: &str = "WHATSAPP_BOSS_NUMBER";
const AUDIO_TEST_TTL_MS: f64 = 300_000.0;
const SAMPLE_RATE: usize = 48_000;

/// Bridge handlers: registry consent, winmm virtual-cable probe and the
/// fixed-layout contact-card check. Compiled on first use.
pub const PS_HANDLERS: &str = r#####"
$script:WaSource = @'
using System;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
public static class JarvisWa {
  [StructLayout(LayoutKind.Sequential)] struct WAVEFORMATEX { public ushort tag; public ushort channels; public uint rate; public uint bytesPerSec; public ushort blockAlign; public ushort bits; public ushort cbSize; }
  [StructLayout(LayoutKind.Sequential)] struct WAVEHDR { public IntPtr data; public uint length; public uint recorded; public IntPtr user; public uint flags; public uint loops; public IntPtr next; public IntPtr reserved; }
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct WAVEINCAPS { public ushort mid; public ushort pid; public uint driver; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string name; public uint formats; public ushort channels; public ushort reserved; }
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct WAVEOUTCAPS { public ushort mid; public ushort pid; public uint driver; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string name; public uint formats; public ushort channels; public ushort reserved; public uint support; }
  [StructLayout(LayoutKind.Sequential)] struct RECT { public int left, top, right, bottom; }
  [DllImport("winmm.dll")] static extern uint waveInGetNumDevs();
  [DllImport("winmm.dll")] static extern uint waveOutGetNumDevs();
  [DllImport("winmm.dll", CharSet = CharSet.Unicode)] static extern int waveInGetDevCapsW(UIntPtr id, ref WAVEINCAPS caps, uint size);
  [DllImport("winmm.dll", CharSet = CharSet.Unicode)] static extern int waveOutGetDevCapsW(UIntPtr id, ref WAVEOUTCAPS caps, uint size);
  [DllImport("winmm.dll")] static extern int waveOutMessage(IntPtr h, uint msg, out int devId, out int flags);
  [DllImport("winmm.dll")] static extern int waveInOpen(out IntPtr h, uint id, ref WAVEFORMATEX fmt, IntPtr cb, IntPtr inst, uint flags);
  [DllImport("winmm.dll")] static extern int waveInPrepareHeader(IntPtr h, IntPtr hdr, uint size);
  [DllImport("winmm.dll")] static extern int waveInUnprepareHeader(IntPtr h, IntPtr hdr, uint size);
  [DllImport("winmm.dll")] static extern int waveInAddBuffer(IntPtr h, IntPtr hdr, uint size);
  [DllImport("winmm.dll")] static extern int waveInStart(IntPtr h);
  [DllImport("winmm.dll")] static extern int waveInReset(IntPtr h);
  [DllImport("winmm.dll")] static extern int waveInClose(IntPtr h);
  [DllImport("winmm.dll")] static extern int waveOutOpen(out IntPtr h, uint id, ref WAVEFORMATEX fmt, IntPtr cb, IntPtr inst, uint flags);
  [DllImport("winmm.dll")] static extern int waveOutPrepareHeader(IntPtr h, IntPtr hdr, uint size);
  [DllImport("winmm.dll")] static extern int waveOutUnprepareHeader(IntPtr h, IntPtr hdr, uint size);
  [DllImport("winmm.dll")] static extern int waveOutWrite(IntPtr h, IntPtr hdr, uint size);
  [DllImport("winmm.dll")] static extern int waveOutReset(IntPtr h);
  [DllImport("winmm.dll")] static extern int waveOutClose(IntPtr h);
  [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr hwnd, int attr, out RECT rect, int size);
  [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] static extern void mouse_event(uint flags, int dx, int dy, uint data, UIntPtr extra);
  [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] static extern uint GetClipboardSequenceNumber();

  static bool Cable(string name, string kind) {
    string n = (name ?? "").ToLowerInvariant();
    return n.Contains(kind) && n.Contains("vb-audio");
  }
  static List<KeyValuePair<uint, string>> Inputs() {
    var list = new List<KeyValuePair<uint, string>>();
    uint count = waveInGetNumDevs();
    for (uint i = 0; i < count; i++) {
      var caps = new WAVEINCAPS();
      if (waveInGetDevCapsW(new UIntPtr(i), ref caps, (uint)Marshal.SizeOf(caps)) == 0) list.Add(new KeyValuePair<uint, string>(i, caps.name));
    }
    return list;
  }
  static List<KeyValuePair<uint, string>> Outputs() {
    var list = new List<KeyValuePair<uint, string>>();
    uint count = waveOutGetNumDevs();
    for (uint i = 0; i < count; i++) {
      var caps = new WAVEOUTCAPS();
      if (waveOutGetDevCapsW(new UIntPtr(i), ref caps, (uint)Marshal.SizeOf(caps)) == 0) list.Add(new KeyValuePair<uint, string>(i, caps.name));
    }
    return list;
  }
  // Exact, unambiguous endpoints only; never the user's physical microphone.
  public static Hashtable Devices() {
    var cableIn = Outputs().FindAll(d => Cable(d.Value, "cable input"));
    var cableOut = Inputs().FindAll(d => Cable(d.Value, "cable output"));
    int preferred, flags; string speaker = null;
    // DRVM_MAPPER_PREFERRED_GET on WAVE_MAPPER: the default playback device.
    if (waveOutMessage(new IntPtr(-1), 0x2015, out preferred, out flags) == 0 && preferred >= 0) {
      foreach (var d in Outputs()) if (d.Key == (uint)preferred) speaker = d.Value;
    }
    bool speakerIsCable = speaker != null && cableIn.Exists(d => d.Value == speaker);
    var h = new Hashtable();
    h["cable_input"] = cableIn.Count == 1 ? cableIn[0].Value : null;
    h["cable_output"] = cableOut.Count == 1 ? cableOut[0].Value : null;
    h["call_speaker"] = speakerIsCable ? null : speaker;
    // A shared-mode loopback exists for every active default speaker.
    h["call_loopback"] = speaker;
    return h;
  }
  static IntPtr Header(IntPtr data, int length) {
    var hdr = new WAVEHDR { data = data, length = (uint)length };
    IntPtr p = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WAVEHDR)));
    Marshal.StructureToPtr(hdr, p, false);
    return p;
  }
  static bool Done(IntPtr hdr) { return (((WAVEHDR)Marshal.PtrToStructure(hdr, typeof(WAVEHDR))).flags & 1) != 0; }
  // Sends a 900 Hz probe into the cable's playback side and records the
  // capture side; the caller looks for the tone. Speakers never play it.
  public static string CableProbe(int rate) {
    var cableIn = Outputs().FindAll(d => Cable(d.Value, "cable input"));
    var cableOut = Inputs().FindAll(d => Cable(d.Value, "cable output"));
    if (cableIn.Count != 1 || cableOut.Count != 1) return null;
    var fmt = new WAVEFORMATEX { tag = 1, channels = 2, rate = (uint)rate, bytesPerSec = (uint)rate * 4, blockAlign = 4, bits = 16 };
    int recordBytes = (int)(rate * 0.4) * 4, toneFrames = (int)(rate * 0.18);
    byte[] tone = new byte[toneFrames * 4];
    for (int i = 0; i < toneFrames; i++) {
      short s = (short)(0.08 * Math.Sin(2 * Math.PI * 900 * i / rate) * 32767);
      tone[i * 4] = (byte)s; tone[i * 4 + 1] = (byte)(s >> 8); tone[i * 4 + 2] = (byte)s; tone[i * 4 + 3] = (byte)(s >> 8);
    }
    uint hs = (uint)Marshal.SizeOf(typeof(WAVEHDR));
    IntPtr inH = IntPtr.Zero, outH = IntPtr.Zero;
    IntPtr inData = Marshal.AllocHGlobal(recordBytes), outData = Marshal.AllocHGlobal(tone.Length);
    IntPtr inHdr = Header(inData, recordBytes), outHdr = Header(outData, tone.Length);
    bool inPrepared = false, outPrepared = false;
    try {
      Marshal.Copy(tone, 0, outData, tone.Length);
      if (waveInOpen(out inH, cableOut[0].Key, ref fmt, IntPtr.Zero, IntPtr.Zero, 0) != 0) return null;
      if (waveInPrepareHeader(inH, inHdr, hs) != 0) return null;
      inPrepared = true;
      if (waveInAddBuffer(inH, inHdr, hs) != 0 || waveInStart(inH) != 0) return null;
      Thread.Sleep(60); // Let recording begin before sending the probe.
      if (waveOutOpen(out outH, cableIn[0].Key, ref fmt, IntPtr.Zero, IntPtr.Zero, 0) != 0) return null;
      if (waveOutPrepareHeader(outH, outHdr, hs) != 0) return null;
      outPrepared = true;
      if (waveOutWrite(outH, outHdr, hs) != 0) return null;
      var deadline = DateTime.UtcNow.AddSeconds(2);
      while (!(Done(inHdr) && Done(outHdr)) && DateTime.UtcNow < deadline) Thread.Sleep(10);
      if (!Done(inHdr) || !Done(outHdr)) return null;
      int recorded = (int)((WAVEHDR)Marshal.PtrToStructure(inHdr, typeof(WAVEHDR))).recorded;
      byte[] captured = new byte[recorded];
      Marshal.Copy(inData, captured, 0, recorded);
      return Convert.ToBase64String(captured);
    } finally {
      if (outH != IntPtr.Zero) { waveOutReset(outH); if (outPrepared) waveOutUnprepareHeader(outH, outHdr, hs); waveOutClose(outH); }
      if (inH != IntPtr.Zero) { waveInReset(inH); if (inPrepared) waveInUnprepareHeader(inH, inHdr, hs); waveInClose(inH); }
      Marshal.FreeHGlobal(inHdr); Marshal.FreeHGlobal(outHdr); Marshal.FreeHGlobal(inData); Marshal.FreeHGlobal(outData);
    }
  }

  // ---- WhatsApp Beta contact card (never the call button) ----
  public static int[] Rect(long hwnd) {
    RECT r;
    if (DwmGetWindowAttribute(new IntPtr(hwnd), 9, out r, Marshal.SizeOf(typeof(RECT))) != 0) GetWindowRect(new IntPtr(hwnd), out r);
    return new int[] { r.left, r.top, r.right, r.bottom };
  }
  static void Focused(long hwnd) { if (GetForegroundWindow() != new IntPtr(hwnd)) throw new Exception("WhatsApp Beta lost focus."); }
  static void Chord(byte vk) {
    keybd_event(0x11, 0, 0, UIntPtr.Zero);
    try { keybd_event(vk, 0, 0, UIntPtr.Zero); keybd_event(vk, 0, 2, UIntPtr.Zero); }
    finally { keybd_event(0x11, 0, 2, UIntPtr.Zero); }
  }
  public static void Click(long hwnd, int x, int y) {
    Focused(hwnd);
    SetCursorPos(x, y); mouse_event(2, 0, 0, 0, UIntPtr.Zero); mouse_event(4, 0, 0, 0, UIntPtr.Zero);
  }
  public static void SelectAll(long hwnd) { Focused(hwnd); Chord((byte)'A'); }
  public static void TypeDigits(long hwnd, string digits) {
    Focused(hwnd);
    foreach (char c in digits) {
      if (c < '0' || c > '9') throw new Exception("Only digits can be typed.");
      keybd_event((byte)c, 0, 0, UIntPtr.Zero); keybd_event((byte)c, 0, 2, UIntPtr.Zero);
    }
  }
  // Selects and copies the visible number, then restores every previous
  // clipboard format unless the user changed the clipboard meanwhile.
  public static string CopyNumber(long hwnd, int sx, int sy, int ex, int ey) {
    IDataObject original = Clipboard.GetDataObject();
    var snapshot = new DataObject();
    if (original != null) {
      foreach (string f in original.GetFormats(false)) {
        try { object d = original.GetData(f, false); if (d != null) snapshot.SetData(f, false, d); } catch { }
      }
    }
    uint before = GetClipboardSequenceNumber();
    uint copySequence = 0; string copied = ""; bool restored = false;
    try {
      Focused(hwnd);
      SetCursorPos(sx, sy); mouse_event(2, 0, 0, 0, UIntPtr.Zero);
      try {
        for (int step = 1; step <= 10; step++) { SetCursorPos(sx + (ex - sx) * step / 10, sy + (ey - sy) * step / 10); Thread.Sleep(10); }
      } finally { mouse_event(4, 0, 0, 0, UIntPtr.Zero); }
      Focused(hwnd);
      Chord((byte)'C');
      for (int i = 0; i < 10 && copySequence == 0; i++) { uint s = GetClipboardSequenceNumber(); if (s != before) copySequence = s; else Thread.Sleep(50); }
      if (copySequence == 0) throw new Exception("WhatsApp did not copy a contact number.");
      for (int i = 0; i < 10; i++) { try { copied = Clipboard.GetText(TextDataFormat.UnicodeText) ?? ""; break; } catch { Thread.Sleep(50); } }
    } finally {
      if (copySequence != 0 && GetClipboardSequenceNumber() == copySequence) {
        try { Clipboard.SetDataObject(snapshot, true, 10, 50); restored = true; } catch { }
      }
    }
    if (!restored) throw new Exception("The original clipboard could not be safely restored.");
    return copied;
  }
}
'@
function Use-Wa { if (-not $script:WaLoaded) { Add-Type -ReferencedAssemblies System.Windows.Forms -TypeDefinition $script:WaSource; $script:WaLoaded = $true } }
$HANDLERS['wa.mic'] = { param($a)
  $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\5319275A.51895FA4EA97F_cv1g1gvanyjgm'
  try { (Get-ItemProperty -LiteralPath $key -Name Value -ErrorAction Stop).Value -eq 'Allow' } catch { $false } }
$HANDLERS['wa.devices'] = { param($a) Use-Wa; [JarvisWa]::Devices() }
$HANDLERS['wa.probe'] = { param($a) Use-Wa; [JarvisWa]::CableProbe([int]$a.rate) }
$HANDLERS['wa.rect'] = { param($a) Use-Wa; ,@([JarvisWa]::Rect([long]$a.hwnd)) }
$HANDLERS['wa.click'] = { param($a) Use-Wa; [JarvisWa]::Click([long]$a.hwnd, [int]$a.x, [int]$a.y); $true }
$HANDLERS['wa.selectall'] = { param($a) Use-Wa; [JarvisWa]::SelectAll([long]$a.hwnd); $true }
$HANDLERS['wa.digits'] = { param($a) Use-Wa; [JarvisWa]::TypeDigits([long]$a.hwnd, [string]$a.digits); $true }
$HANDLERS['wa.copynumber'] = { param($a) Use-Wa; [JarvisWa]::CopyNumber([long]$a.hwnd, [int]$a.sx, [int]$a.sy, [int]$a.ex, [int]$a.ey) }
"#####;

thread_local! {
    /// (when, device names, result) of the last cable probe.
    static AUDIO_TEST: RefCell<Option<(f64, Value, bool)>> = const { RefCell::new(None) };
    static UI_BUSY: Cell<bool> = const { Cell::new(false) };
}

/// Recognizes only an explicit request to call the owner's saved contact.
pub fn parse_call_request(text: &str) -> bool {
    crate::re!(
        r"(?i)^(?:(?:please|bitte)\s+)?(?:call|ring|ruf(?:e)?|anrufen|telefoniere(?:n)?)\s+(?:(?:mich|me|boss)(?:\s+an)?|(?:boss|mich|me)\s+(?:via|auf|mit|on)\s+whatsapp(?:\s+beta)?)(?:\s+(?:via|auf|mit|on)\s+whatsapp(?:\s+beta)?)?[.!?]*$"
    )
    .is_match(text.trim())
}

pub fn normalize_swiss_mobile(number: &str) -> Result<String, String> {
    let compact: String = number.chars().filter(|c| !c.is_whitespace() && !"().-".contains(*c)).collect();
    let digits = |s: &str| s.bytes().all(|b| b.is_ascii_digit());
    if compact.len() == 10 && compact.starts_with("07") && digits(&compact) {
        return Ok(format!("+41{}", &compact[1..]));
    }
    if compact.len() == 12 && compact.starts_with("+417") && digits(&compact[1..]) {
        return Ok(compact);
    }
    Err("Enter a Swiss mobile number beginning with 07 or +417.".into())
}

async fn saved_number() -> Option<String> {
    vault::get_password(&vault::service_name(), CONTACT_KEY).await.ok().flatten()
}

pub async fn save_boss_number(number: &str) -> Res<()> {
    if !vault::available() {
        return Err("Windows Credential Manager is unavailable; the number was not saved.".into());
    }
    let normalized = normalize_swiss_mobile(number)?;
    vault::set_password(&vault::service_name(), CONTACT_KEY, &normalized).await?;
    if saved_number().await.as_deref() != Some(normalized.as_str()) {
        return Err("The contact number could not be verified in Windows Credential Manager.".into());
    }
    Ok(())
}

async fn boss_number_configured() -> bool {
    saved_number().await.is_some_and(|n| normalize_swiss_mobile(&n).is_ok())
}

/// The package's current Windows microphone grant, read before any dial.
async fn microphone_allowed() -> bool {
    host::ps("wa.mic", json!({})).await.ok().and_then(|v| v.as_bool()).unwrap_or(false)
}

fn exact_beta(found: Vec<apps::App>) -> Option<apps::App> {
    match found.as_slice() {
        [app] if app.name.eq_ignore_ascii_case("whatsapp beta") => Some(app.clone()),
        _ => None,
    }
}

async fn whatsapp_beta(refresh_if_missing: bool) -> Option<apps::App> {
    let found = apps::resolve_app("WhatsApp Beta", &apps::installed_apps().await);
    if found.is_empty() && refresh_if_missing {
        return exact_beta(apps::resolve_app("WhatsApp Beta", &apps::refreshed_apps().await));
    }
    exact_beta(found)
}

/// True when the captured audio carries the 900 Hz probe well above its
/// 600–1200 Hz neighbourhood (same criterion as the FFT check it replaces).
fn tone_detected(pcm: &[u8]) -> bool {
    let mono: Vec<f64> = pcm
        .chunks_exact(4)
        .map(|f| {
            let l = i16::from_le_bytes([f[0], f[1]]) as f64 / 32768.0;
            let r = i16::from_le_bytes([f[2], f[3]]) as f64 / 32768.0;
            (l + r) / 2.0
        })
        .collect();
    let n = mono.len();
    if n < SAMPLE_RATE / 5 {
        return false;
    }
    let resolution = SAMPLE_RATE as f64 / n as f64;
    let (low, high) = ((600.0 / resolution).ceil() as usize, (1200.0 / resolution).floor() as usize);
    let mut ambient = Vec::new();
    let mut target: f64 = 0.0;
    for k in low..=high {
        let w = std::f64::consts::TAU * k as f64 / n as f64;
        let (mut re, mut im) = (0.0, 0.0);
        for (i, s) in mono.iter().enumerate() {
            let a = w * i as f64;
            re += s * a.cos();
            im -= s * a.sin();
        }
        let magnitude = (re * re + im * im).sqrt();
        let frequency = k as f64 * resolution;
        if (880.0..=920.0).contains(&frequency) {
            target = target.max(magnitude);
        }
        ambient.push(magnitude);
    }
    ambient.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let median = if ambient.is_empty() {
        return false;
    } else if ambient.len() % 2 == 1 {
        ambient[ambient.len() / 2]
    } else {
        (ambient[ambient.len() / 2 - 1] + ambient[ambient.len() / 2]) / 2.0
    };
    target > (median * 12.0).max(2.0)
}

/// The cable probe result, cached for five minutes per device pair.
async fn cable_verified(devices: &Value) -> bool {
    let ids = json!([devices["cable_input"], devices["cable_output"]]);
    let now = host::monotonic();
    if let Some(result) = AUDIO_TEST.with(|c| c.borrow().as_ref().filter(|(at, seen, _)| *seen == ids && now - at < AUDIO_TEST_TTL_MS).map(|x| x.2)) {
        return result;
    }
    let verified = match host::ps("wa.probe", json!({ "rate": SAMPLE_RATE })).await {
        Ok(Value::String(b64)) => B64.decode(b64).is_ok_and(|pcm| tone_detected(&pcm)),
        _ => false,
    };
    AUDIO_TEST.with(|c| *c.borrow_mut() = Some((host::monotonic(), ids, verified)));
    verified
}

/// Does not claim a callable path until the voice bridge and call UI exist.
pub async fn call_readiness() -> Value {
    let installed = whatsapp_beta(true).await.is_some();
    let contact_saved = boss_number_configured().await;
    let microphone = microphone_allowed().await;
    let devices = host::ps("wa.devices", json!({})).await.unwrap_or(Value::Null);
    let present = |k: &str| devices[k].as_str().is_some_and(|s| !s.is_empty());
    let virtual_audio_present = present("cable_input") && present("cable_output");
    let call_loopback_present = present("call_speaker") && present("call_loopback");
    let audio_bridge_ready = virtual_audio_present && call_loopback_present && cable_verified(&devices).await;
    let reason = if !installed {
        "WhatsApp Beta is not installed or cannot be identified uniquely."
    } else if !contact_saved {
        "Boss's contact number is not saved in Windows Credential Manager."
    } else if !microphone {
        "Windows has not granted WhatsApp Beta microphone access."
    } else if !virtual_audio_present {
        "A virtual microphone is missing. Jarvis cannot send its voice into a WhatsApp call."
    } else if !audio_bridge_ready {
        "The virtual audio cable has not passed its playback and capture check."
    } else {
        "Audio is ready, but WhatsApp contact, call connection and conversation controls are not verified yet."
    };
    json!({
        "contact_saved": contact_saved, "whatsapp_beta_installed": installed, "microphone_permission_granted": microphone,
        "virtual_audio_present": virtual_audio_present, "call_loopback_present": call_loopback_present,
        "audio_bridge_ready": audio_bridge_ready, "automatic_call_ready": false, "reason": reason,
    })
}

struct Layout {
    search: (i32, i32),
    first_result: (i32, i32),
    contact_header: (i32, i32),
    number_start: (i32, i32),
    number_end: (i32, i32),
}

/// The supported WhatsApp Beta layout; unfamiliar window sizes are rejected.
fn contact_layout(width: i32, height: i32) -> Res<Layout> {
    if !(850..=2000).contains(&width) || !(560..=1200).contains(&height) {
        return Err("WhatsApp Beta window layout is unsupported.".into());
    }
    let round = |v: f64| v.round_ties_even() as i32;
    let sidebar = round(width as f64 * 0.415).min(444);
    // Contact info opens in a fixed-width panel on the right.
    let number_center = width - round(width as f64 * 0.45).min(462) / 2;
    Ok(Layout {
        search: (round(sidebar as f64 * 0.58), 123),
        first_result: (150, 273),
        contact_header: (sidebar + 90, 70),
        number_start: (number_center - 85, 309),
        number_end: (number_center + 85, 309),
    })
}

async fn verify_contact_ui(expected: &str) -> Res<bool> {
    let expected = normalize_swiss_mobile(expected)?;
    let digits = format!("0{}", &expected[3..]);
    let app = whatsapp_beta(false).await.ok_or("One exact WhatsApp Beta installation is required.")?;
    let handles = apps::app_windows(&app).await;
    let [window] = handles.as_slice() else { return Err("One focused WhatsApp Beta window is required.".into()) };
    let hwnd = window.hwnd;
    if !apps::focus_existing(&app).await.is_some_and(|r| r.success) || desktop::foreground().await != hwnd {
        return Err("WhatsApp Beta is not the foreground window.".into());
    }
    let rect = host::ps("wa.rect", json!({ "hwnd": hwnd })).await?;
    let r: Vec<i32> = rect.as_array().into_iter().flatten().filter_map(|v| v.as_i64().map(|x| x as i32)).collect();
    let [left, top, right, bottom] = r.as_slice() else { return Err("WhatsApp Beta window size is unknown.".into()) };
    let (left, top) = (*left, *top);
    let layout = contact_layout(right - left, bottom - top)?;
    let click = |p: (i32, i32)| host::ps("wa.click", json!({ "hwnd": hwnd, "x": left + p.0, "y": top + p.1 }));
    click(layout.search).await?;
    host::ps("wa.selectall", json!({ "hwnd": hwnd })).await?;
    host::ps("wa.digits", json!({ "hwnd": hwnd, "digits": digits })).await?;
    host::sleep(350.0).await;
    click(layout.first_result).await?;
    host::sleep(200.0).await;
    click(layout.contact_header).await?;
    host::sleep(200.0).await;
    let copied = host::ps(
        "wa.copynumber",
        json!({ "hwnd": hwnd, "sx": left + layout.number_start.0, "sy": top + layout.number_start.1,
                "ex": left + layout.number_end.0, "ey": top + layout.number_end.1 }),
    )
    .await?;
    Ok(normalize_swiss_mobile(copied.as_str().unwrap_or("")).is_ok_and(|n| n == expected))
}

/// Opens Boss's contact card and compares its number; one check at a time.
async fn verify_boss_contact(expected: &str) -> bool {
    if UI_BUSY.with(|b| b.replace(true)) {
        return false;
    }
    let result = verify_contact_ui(expected).await;
    UI_BUSY.with(|b| b.set(false));
    match result {
        Ok(matched) => matched,
        Err(e) => {
            // The desktop UI can change without notice; a failed check never
            // becomes permission to call an unverified contact.
            host::log("warn", &format!("Boss contact verification failed: {}", crate::util::take(&e, 120)));
            false
        }
    }
}

/// Opens the exact desktop app, but never presents an unplaced call as placed.
pub async fn prepare_call_to_boss() -> String {
    if !boss_number_configured().await {
        return "Boss's contact number is not saved in Windows Credential Manager. I did not place a call.".into();
    }
    if whatsapp_beta(true).await.is_none() {
        return "WhatsApp Beta is not installed or cannot be identified uniquely. I did not place a call.".into();
    }
    let options = apps::OpenOptions { wait_until_ready: true, ..Default::default() };
    if !apps::open_app("WhatsApp Beta", options).await.success {
        return "I could not verify the WhatsApp Beta window. I did not place a call.".into();
    }
    let number = saved_number().await.unwrap_or_default();
    if !verify_boss_contact(&number).await {
        return "WhatsApp Beta is open, but I could not verify Boss's exact contact number. I did not place a call.".into();
    }
    "I verified Boss's exact WhatsApp contact. I cannot place or speak in the call yet because the two-way audio bridge and answered-call controls are not ready. I did not place a call.".into()
}

/// Fails closed until dialing, recipient and answered-call checks exist.
pub async fn attempt_urgent_call(alert: &Value) -> Value {
    let not_ready = json!({ "state": "not_ready" });
    if !matches!(alert["source"].as_str(), Some("gmail" | "outlook")) || alert["id"].as_str().is_none_or(str::is_empty) {
        return not_ready;
    }
    let readiness = call_readiness().await;
    if readiness["contact_saved"] != true || readiness["whatsapp_beta_installed"] != true || readiness["microphone_permission_granted"] != true {
        return not_ready;
    }
    // Devices alone are insufficient. A caller must also verify Boss, place
    // the call, detect an answer and finish speaking before reporting success.
    not_ready
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn call_requests_are_explicit() {
        for yes in ["call me", "Bitte ruf mich an", "call boss on WhatsApp Beta", "ring me via whatsapp!"] {
            assert!(parse_call_request(yes), "{yes}");
        }
        for no in ["call mom", "call me maybe later", "please call the office"] {
            assert!(!parse_call_request(no), "{no}");
        }
    }

    #[test]
    fn swiss_numbers_normalize() {
        assert_eq!(normalize_swiss_mobile("079 123 45 67").unwrap(), "+41791234567");
        assert_eq!(normalize_swiss_mobile("+41 (79) 123-45-67").unwrap(), "+41791234567");
        assert!(normalize_swiss_mobile("044 123 45 67").is_err());
    }

    #[test]
    fn layout_matches_python() {
        let l = contact_layout(1200, 800).unwrap();
        assert_eq!((l.search, l.contact_header, l.number_start, l.number_end), ((258, 123), (534, 70), (884, 309), (1054, 309)));
        assert!(contact_layout(800, 800).is_err());
    }

    #[test]
    fn detects_probe_tone() {
        let n = SAMPLE_RATE * 2 / 5;
        let pcm: Vec<u8> = (0..n)
            .flat_map(|i| {
                let s = if (2880..2880 + 8640).contains(&i) { (0.08 * (std::f64::consts::TAU * 900.0 * i as f64 / SAMPLE_RATE as f64).sin() * 32767.0) as i16 } else { 0 };
                let b = s.to_le_bytes();
                [b[0], b[1], b[0], b[1]]
            })
            .collect();
        assert!(tone_detected(&pcm));
        assert!(!tone_detected(&vec![0u8; n * 4]));
    }
}
