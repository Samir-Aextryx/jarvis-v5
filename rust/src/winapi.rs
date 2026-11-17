//! The PowerShell bridge: one long-lived `powershell.exe` (signed by
//! Microsoft, allowed by Smart App Control) that exposes the Win32, COM and
//! UI Automation calls WebAssembly cannot make. Requests and replies are JSON
//! lines; every command is listed in `HANDLERS` below and nothing else runs.

pub const BRIDGE_SCRIPT: &str = r#####"
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
# Input is UTF-8: host.cjs sets it before the first read (resetting it later drops buffered lines).
[Console]::OutputEncoding = $utf8
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class JarvisCred {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  struct CREDENTIAL {
    public int Flags; public int Type; public string TargetName; public string Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public int CredentialBlobSize; public IntPtr CredentialBlob; public int Persist;
    public int AttributeCount; public IntPtr Attributes; public string TargetAlias; public string UserName;
  }
  [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool CredRead(string target, int type, int flags, out IntPtr credential);
  [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool CredWrite(ref CREDENTIAL credential, int flags);
  [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool CredDelete(string target, int type, int flags);
  [DllImport("advapi32.dll")] static extern void CredFree(IntPtr buffer);
  public static string[] Read(string target) {
    IntPtr p;
    if (!CredRead(target, 1, 0, out p)) {
      int error = Marshal.GetLastWin32Error();
      if (error == 1168) return null;
      throw new System.ComponentModel.Win32Exception(error);
    }
    try {
      CREDENTIAL c = (CREDENTIAL)Marshal.PtrToStructure(p, typeof(CREDENTIAL));
      string secret = c.CredentialBlobSize > 0 ? Marshal.PtrToStringUni(c.CredentialBlob, c.CredentialBlobSize / 2) : "";
      return new string[] { c.UserName ?? "", secret };
    } finally { CredFree(p); }
  }
  public static void Write(string target, string user, string secret) {
    byte[] blob = Encoding.Unicode.GetBytes(secret);
    CREDENTIAL c = new CREDENTIAL();
    c.Type = 1; c.TargetName = target; c.UserName = user; c.Persist = 3;
    c.Comment = "Stored using python-keyring";
    c.CredentialBlobSize = blob.Length;
    c.CredentialBlob = Marshal.AllocHGlobal(Math.Max(1, blob.Length));
    try {
      Marshal.Copy(blob, 0, c.CredentialBlob, blob.Length);
      if (!CredWrite(ref c, 0)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    } finally { Marshal.FreeHGlobal(c.CredentialBlob); }
  }
  public static bool Delete(string target) { return CredDelete(target, 1, 0); }
}
'@

$HANDLERS = @{
  'ping' = { param($a) 'pong' }
  'cred.read' = { param($a)
    $c = [JarvisCred]::Read([string]$a.target)
    if ($null -eq $c) { $null } else { @{ user = $c[0]; secret = $c[1] } } }
  'cred.write' = { param($a) [JarvisCred]::Write([string]$a.target, [string]$a.user, [string]$a.secret); $true }
  'cred.delete' = { param($a) [JarvisCred]::Delete([string]$a.target) }
  # Current-user DPAPI; compatible with win32crypt.CryptProtectData(flags 0).
  'dpapi.protect' = { param($a)
    Add-Type -AssemblyName System.Security
    [Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Protect(
      [Convert]::FromBase64String([string]$a.data), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)) }
  'dpapi.unprotect' = { param($a)
    Add-Type -AssemblyName System.Security
    [Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Unprotect(
      [Convert]::FromBase64String([string]$a.data), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)) }
}
#EXTRA_HANDLERS#

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  $id = $null
  try {
    $request = $line | ConvertFrom-Json
    $id = $request.id
    $handler = $HANDLERS[[string]$request.cmd]
    if ($null -eq $handler) { throw "Unknown bridge command" }
    $result = & $handler $request.args
    $reply = @{ id = $id; ok = $true; result = $result }
  } catch {
    $reply = @{ id = $id; ok = $false; error = $_.Exception.Message }
  }
  [Console]::Out.WriteLine(($reply | ConvertTo-Json -Compress -Depth 10))
  [Console]::Out.Flush()
}
"#####;

/// The full script with the handler modules of the other Rust files.
pub fn script() -> String {
    let extra = [crate::desktop::PS_HANDLERS, crate::uia::PS_HANDLERS, crate::whatsapp::PS_HANDLERS].join("\n");
    BRIDGE_SCRIPT.replace("#EXTRA_HANDLERS#", &extra)
}
