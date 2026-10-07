// Owner-requested availability guard. This is not a security boundary and
// cannot veto forced/critical shutdown, firmware power-off or a held power key.
using System;
using System.ComponentModel;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Threading;
using System.Windows.Forms;

sealed class ShutdownGuard : Form
{
    const int QueryEndSession = 0x0011;
    const long Critical = 0x40000000L;
    NotifyIcon tray;
    bool allowMaintenance;
    readonly string state = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "OracovaShutdownGuard");

    public static bool Blocks(long flags) { return (flags & Critical) == 0; }

    [STAThread] static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--self-test") {
            if (!Blocks(0) || !Blocks(0x80000000L) || !Blocks(1) || Blocks(Critical) || Blocks(Critical | 1)) return 1;
            Console.WriteLine("5 shutdown policy checks passed; no shutdown requested"); return 0;
        }
        if (args.Length != 0) return 2;
        using (var identity = WindowsIdentity.GetCurrent()) {
            if (identity.User == null || identity.User.Value != "S-1-5-21-71459778-1164188569-2276148161-1001") return 3;
            if (new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) return 4;
        }
        bool created;
        using (var mutex = new Mutex(true, "Local\\OracovaShutdownGuard", out created)) {
            if (!created) return 0;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            using (var form = new ShutdownGuard()) Application.Run(form);
        }
        return 0;
    }

    ShutdownGuard()
    {
        Text = "Oracova remote PC shutdown guard";
        // A real top-level window with a registered reason, not a console or
        // message-only window (which Windows may exclude from shutdown veto).
        ShowInTaskbar = false; FormBorderStyle = FormBorderStyle.FixedToolWindow;
        StartPosition = FormStartPosition.Manual; Location = new Point(-32000, -32000);
        Size = new Size(1, 1); Opacity = 0;
        var menu = new ContextMenuStrip();
        menu.Items.Add("Allow maintenance for 10 minutes", null, delegate {
            Directory.CreateDirectory(state);
            File.WriteAllText(Path.Combine(state, "maintenance-until.txt"), DateTime.UtcNow.AddMinutes(10).ToString("o"));
            allowMaintenance = true; ShutdownBlockReasonDestroy(Handle); Close();
        });
        tray = new NotifyIcon { Icon = SystemIcons.Shield, Text = "Oracova: ordinary shutdown blocked", ContextMenuStrip = menu, Visible = true };
    }
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        if (!ShutdownBlockReasonCreate(Handle, "Remote services must stay online. Use the Oracova tray icon to allow maintenance."))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        Log("started");
    }
    protected override void WndProc(ref Message message)
    {
        if (message.Msg == QueryEndSession) {
            bool blocked = !allowMaintenance && Blocks(message.LParam.ToInt64());
            Log(blocked ? "ordinary-shutdown-vetoed" : "critical-or-maintenance-shutdown-not-blocked");
            message.Result = blocked ? IntPtr.Zero : new IntPtr(1); return;
        }
        base.WndProc(ref message);
    }
    void Log(string label)
    {
        // Best-effort bounded diagnostics must never delay the shutdown reply.
        try {
            Directory.CreateDirectory(state); var path = Path.Combine(state, "guard.log");
            if (File.Exists(path) && new FileInfo(path).Length > 262144) {
                if (File.Exists(path + ".1")) File.Delete(path + ".1"); File.Move(path, path + ".1");
            }
            File.AppendAllText(path, DateTime.UtcNow.ToString("o") + " " + label + Environment.NewLine);
        } catch (IOException) {} catch (UnauthorizedAccessException) {}
    }
    protected override void Dispose(bool disposing)
    {
        if (disposing) { if (IsHandleCreated) ShutdownBlockReasonDestroy(Handle); if (tray != null) tray.Dispose(); }
        base.Dispose(disposing);
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool ShutdownBlockReasonCreate(IntPtr window, string reason);
    [DllImport("user32.dll", SetLastError = true)] static extern bool ShutdownBlockReasonDestroy(IntPtr window);
}
