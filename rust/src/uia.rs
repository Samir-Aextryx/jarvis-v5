//! UI Automation through the PowerShell bridge: snapshots of accessible
//! controls in one window and verified actions on them. Elements are cached
//! in the bridge by runtime id between a snapshot and an action.

use crate::host::{self, Res};
use serde_json::{Value, json};

pub const PS_HANDLERS: &str = r#####"
$script:UiaSource = @'
using System;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Windows.Automation;
public static class JarvisUia {
  static Dictionary<string, AutomationElement> cache = new Dictionary<string, AutomationElement>();
  static readonly HashSet<string> Roles = new HashSet<string> { "Edit","Document","Text","Button","Hyperlink","MenuItem","TabItem","ListItem","DataItem","TreeItem","CheckBox","RadioButton","Header","StatusBar" };
  static readonly Regex AddressBar = new Regex("^(?:address and search bar|adress- und suchleiste|adressleiste)$", RegexOptions.IgnoreCase);

  [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] struct INPUT { public int type; public UNION u; }
  [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);

  static INPUT Key(ushort vk, ushort scan, uint flags) {
    var i = new INPUT(); i.type = 1; i.u.ki = new KEYBDINPUT { wVk = vk, wScan = scan, dwFlags = flags }; return i;
  }
  static void Send(params INPUT[] inputs) {
    if (SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT))) != inputs.Length) throw new Exception("KEY_INPUT_FAILED");
  }
  public static void Enter(bool shift) {
    if (shift) Send(Key(0x10, 0, 0), Key(0x0D, 0, 0), Key(0x0D, 0, 2), Key(0x10, 0, 2));
    else Send(Key(0x0D, 0, 0), Key(0x0D, 0, 2));
  }

  public static string Role(AutomationElement e) { return e.Current.ControlType.ProgrammaticName.Replace("ControlType.", ""); }
  static string Rid(AutomationElement e) { var r = e.GetRuntimeId(); return r == null ? "" : string.Join(".", r); }
  static AutomationElement Get(string rid) {
    AutomationElement e;
    if (!cache.TryGetValue(rid, out e)) throw new Exception("ELEMENT_GONE");
    return e;
  }
  public static string ReadValue(AutomationElement e, int limit, out bool known) {
    known = true; object p;
    if (e.TryGetCurrentPattern(ValuePattern.Pattern, out p)) {
      try { string v = ((ValuePattern)p).Current.Value ?? ""; return v.Length > limit ? v.Substring(0, limit) : v; } catch { }
    }
    if (e.TryGetCurrentPattern(TextPattern.Pattern, out p)) {
      try { return ((TextPattern)p).DocumentRange.GetText(limit + 1); } catch { }
    }
    known = false; return "";
  }
  public static string[] Addresses(long hwnd) {
    var root = AutomationElement.FromHandle(new IntPtr(hwnd));
    var list = new List<string>();
    foreach (AutomationElement e in root.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit))) {
      try {
        if (!AddressBar.IsMatch(e.Current.Name ?? "")) continue;
        bool known; list.Add(ReadValue(e, 4000, out known).Trim());
      } catch { }
    }
    return list.ToArray();
  }
  static Hashtable Node(AutomationElement e, int index, bool teams, System.Windows.Rect window) {
    var c = e.Current;
    string role = Role(e);
    string name = c.Name ?? ""; if (name.Length > 220) name = name.Substring(0, 220);
    string value = ""; bool known = true;
    if (role == "Edit" || role == "Document") value = ReadValue(e, 12000, out known);
    // Teams exposes its empty composer placeholder as the edit value.
    if (role == "Edit" && value.Trim() == name.Trim()) {
      string lower = name.Trim().ToLowerInvariant();
      if (lower == "nachricht eingeben" || lower == "type a message") value = "";
    }
    var walker = TreeWalker.ControlViewWalker;
    var parent = walker.GetParent(e);
    var headingAncestors = new List<AutomationElement>();
    var hp = parent;
    for (int i = 0; i < 3 && hp != null; i++) { headingAncestors.Add(hp); hp = walker.GetParent(hp); }
    bool inList = false; var lp = parent;
    for (int i = 0; i < 5 && lp != null; i++) {
      string r = Role(lp);
      if (r == "List" || r == "ListItem" || r == "Tree" || r == "TreeItem") inList = true;
      lp = walker.GetParent(lp);
    }
    if (name.Length == 0 && role != "Edit" && role != "Document") return null;
    var rid = e.GetRuntimeId();
    var node = new Hashtable();
    node["id"] = index; node["identity"] = rid == null ? new int[0] : rid; node["role"] = role; node["name"] = name;
    node["value"] = value; node["value_known"] = known; node["in_list"] = inList; node["password"] = false;
    if (teams && role == "Text") {
      var rect = c.BoundingRectangle; bool item = false;
      foreach (var a in headingAncestors) {
        try { if (Role(a) == "ListItem" && (a.Current.AutomationId ?? "").StartsWith("listItem")) item = true; } catch { }
      }
      double top = rect.Top - window.Top;
      node["conversation_heading"] = item && top >= 0 && top < 150 && rect.Left - window.Left > 400;
    }
    object p;
    if ((role == "TabItem" || role == "ListItem" || role == "TreeItem" || role == "RadioButton") && e.TryGetCurrentPattern(SelectionItemPattern.Pattern, out p)) {
      try { node["selected"] = ((SelectionItemPattern)p).Current.IsSelected; } catch { }
    }
    if (role == "CheckBox" && e.TryGetCurrentPattern(TogglePattern.Pattern, out p)) {
      try { node["checked"] = (int)((TogglePattern)p).Current.ToggleState; } catch { }
    }
    return node;
  }
  public static Hashtable Snapshot(long hwnd, bool web, bool teams) {
    var result = SnapshotOnce(hwnd, web, teams);
    // Chromium apps enable their accessibility tree on the first UIA query.
    if (((ArrayList)result["elements"]).Count < 5) { System.Threading.Thread.Sleep(350); result = SnapshotOnce(hwnd, web, teams); }
    return result;
  }
  static Hashtable SnapshotOnce(long hwnd, bool web, bool teams) {
    cache.Clear();
    var window = AutomationElement.FromHandle(new IntPtr(hwnd));
    var root = window;
    if (web) {
      // Exclude browser toolbars, URL fields and unrelated tabs.
      root = window.FindFirst(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Document));
      if (root == null) throw new Exception("NO_DOCUMENT");
    }
    var wrect = window.Current.BoundingRectangle;
    var nodes = new ArrayList();
    var all = root.FindAll(TreeScope.Descendants, Automation.ControlViewCondition);
    int count = 0;
    foreach (AutomationElement e in all) {
      if (count++ >= 600 || nodes.Count >= 180) break;
      try {
        var c = e.Current;
        if (c.IsOffscreen || !c.IsEnabled || c.IsPassword || !Roles.Contains(Role(e))) continue;
        var node = Node(e, nodes.Count, teams, wrect);
        if (node == null) continue;
        nodes.Add(node);
        cache[Rid(e)] = e;
      } catch { }
    }
    var result = new Hashtable();
    result["title"] = window.Current.Name ?? ""; result["elements"] = nodes;
    return result;
  }
  // Fresh state of one cached control, for checks right before acting on it.
  public static Hashtable Inspect(string rid) {
    var e = Get(rid); var c = e.Current;
    var node = new Hashtable();
    string role = Role(e); bool known = true; string value = "";
    if (role == "Edit" || role == "Document") value = ReadValue(e, 12000, out known);
    node["identity"] = e.GetRuntimeId(); node["role"] = role; node["name"] = c.Name ?? ""; node["value"] = value; node["value_known"] = known;
    node["usable"] = !c.IsOffscreen && c.IsEnabled && !c.IsPassword; node["automation_id"] = c.AutomationId ?? "";
    object vp; node["has_value"] = e.TryGetCurrentPattern(ValuePattern.Pattern, out vp);
    return node;
  }
  public static void Click(string rid) {
    var e = Get(rid); string role = Role(e); object p;
    if ((role == "TabItem" || role == "ListItem" || role == "DataItem" || role == "TreeItem" || role == "RadioButton") && e.TryGetCurrentPattern(SelectionItemPattern.Pattern, out p)) ((SelectionItemPattern)p).Select();
    else if (role == "CheckBox" && e.TryGetCurrentPattern(TogglePattern.Pattern, out p)) ((TogglePattern)p).Toggle();
    else if (e.TryGetCurrentPattern(InvokePattern.Pattern, out p)) ((InvokePattern)p).Invoke();
    else if (e.TryGetCurrentPattern(SelectionItemPattern.Pattern, out p)) ((SelectionItemPattern)p).Select();
    else throw new Exception("NO_CLICK_PATTERN");
  }
  public static void SetValue(string rid, string text) {
    object p; var e = Get(rid);
    if (!e.TryGetCurrentPattern(ValuePattern.Pattern, out p)) throw new Exception("NO_VALUE_PATTERN");
    ((ValuePattern)p).SetValue(text);
  }
  public static bool Focus(string rid) {
    var e = Get(rid); e.SetFocus(); return e.Current.HasKeyboardFocus;
  }
  // Literal Unicode input while the control keeps keyboard focus; "\n" is Shift+Enter.
  public static int Keys(string rid, string text) {
    var e = Get(rid); int typed = 0;
    foreach (char ch in text) {
      if (!e.Current.HasKeyboardFocus) return typed;
      if (ch == '\n') Enter(true);
      else Send(Key(0, ch, 4), Key(0, ch, 4 | 2));
      typed++;
    }
    return typed;
  }
  public static string Value(string rid) {
    bool known; var e = Get(rid); string v = ReadValue(e, 20000, out known);
    if (!known) throw new Exception("VALUE_UNREADABLE");
    return v;
  }
  public static bool Submit(string rid) {
    var e = Get(rid);
    if (!e.Current.HasKeyboardFocus) return false;
    Enter(false); return true;
  }
}
'@
# Compiled on first use so the bridge starts fast.
function Use-Uia { if (-not $script:UiaLoaded) { Add-Type -ReferencedAssemblies UIAutomationClient, UIAutomationTypes, WindowsBase -TypeDefinition $script:UiaSource; $script:UiaLoaded = $true } }
$HANDLERS['uia.addresses'] = { param($a) Use-Uia; ,@([JarvisUia]::Addresses([long]$a.hwnd)) }
$HANDLERS['uia.snapshot'] = { param($a) Use-Uia; [JarvisUia]::Snapshot([long]$a.hwnd, [bool]$a.web, [bool]$a.teams) }
$HANDLERS['uia.inspect'] = { param($a) Use-Uia; [JarvisUia]::Inspect([string]$a.rid) }
$HANDLERS['uia.click'] = { param($a) Use-Uia; [JarvisUia]::Click([string]$a.rid); $true }
$HANDLERS['uia.setvalue'] = { param($a) Use-Uia; [JarvisUia]::SetValue([string]$a.rid, [string]$a.text); $true }
$HANDLERS['uia.focus'] = { param($a) Use-Uia; [JarvisUia]::Focus([string]$a.rid) }
$HANDLERS['uia.keys'] = { param($a) Use-Uia; [JarvisUia]::Keys([string]$a.rid, [string]$a.text) }
$HANDLERS['uia.value'] = { param($a) Use-Uia; [JarvisUia]::Value([string]$a.rid) }
$HANDLERS['uia.submit'] = { param($a) Use-Uia; [JarvisUia]::Submit([string]$a.rid) }
"#####;

/// Runtime id as the bridge's cache key.
pub fn rid(identity: &Value) -> String {
    identity.as_array().map(|a| a.iter().map(|v| v.to_string()).collect::<Vec<_>>().join(".")).unwrap_or_default()
}

/// Address bar values of a Chrome window.
pub async fn addresses(hwnd: i64) -> Vec<String> {
    match host::ps("uia.addresses", json!({ "hwnd": hwnd })).await {
        Ok(Value::Array(a)) => a.into_iter().filter_map(|v| v.as_str().map(str::to_string)).collect(),
        Ok(Value::String(s)) => vec![s],
        _ => Vec::new(),
    }
}

pub async fn snapshot(hwnd: i64, web: bool, teams: bool) -> Res<Value> {
    let mut v = host::ps("uia.snapshot", json!({ "hwnd": hwnd, "web": web, "teams": teams })).await?;
    // ConvertTo-Json writes a one-item array as an object and an empty one as null.
    v["elements"] = match v["elements"].take() {
        Value::Array(a) => Value::Array(a),
        Value::Null => json!([]),
        other => json!([other]),
    };
    Ok(v)
}

pub async fn inspect(rid: &str) -> Res<Value> {
    host::ps("uia.inspect", json!({ "rid": rid })).await
}

pub async fn call(cmd: &str, rid: &str, text: Option<&str>) -> Res<Value> {
    host::ps(cmd, json!({ "rid": rid, "text": text.unwrap_or("") })).await
}
