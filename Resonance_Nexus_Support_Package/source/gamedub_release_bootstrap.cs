using System;
using System.IO;
using System.IO.Compression;
using System.Diagnostics;
using System.Drawing;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal sealed class ColdVoiceBootstrap : Form {
    const string Magic = "COLDVOICEZIPV01";
    readonly Label title = new Label();
    readonly Label caption = new Label();
    readonly PictureBox picture = new PictureBox();
    string temporary;

    [STAThread]
    static void Main(string[] args) {
        if (args.Length == 2 && args[0] == "--verify-icon") {
            Environment.ExitCode = VerifyIcon(args[1]) ? 0 : 3;
            return;
        }
        if (args.Length == 1 && args[0] == "--verify-host") {
            try {
                string error = RunPowerShellScript("Add-Type -AssemblyName System.Windows.Forms; $f = New-Object Windows.Forms.Form; $f.Dispose()");
                Environment.ExitCode = String.IsNullOrEmpty(error) ? 0 : 4;
            } catch { Environment.ExitCode = 4; }
            return;
        }
        if (args.Length == 2 && args[0] == "--verify-installer") {
            try {
                // Parse all PowerShell and compile only its C# helpers; no game writes or wizard.
                string probe = "$text = [IO.File]::ReadAllText($env:COLDVOICE_VERIFY_SCRIPT); " +
                    "$tokens = $null; $errors = $null; " +
                    "[void][System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors); " +
                    "if ($errors.Count) { throw ($errors -join [Environment]::NewLine) }; " +
                    "$end = $text.IndexOf('$base = ', [StringComparison]::Ordinal); " +
                    "if ($end -lt 0) { throw 'Installer helper boundary missing' }; " +
                    "& ([ScriptBlock]::Create($text.Substring(0, $end)))";
                Environment.SetEnvironmentVariable("COLDVOICE_VERIFY_SCRIPT", Path.GetFullPath(args[1]));
                string error = RunPowerShellScript(probe);
                Environment.ExitCode = String.IsNullOrEmpty(error) ? 0 : 5;
            } catch { Environment.ExitCode = 5; }
            finally { Environment.SetEnvironmentVariable("COLDVOICE_VERIFY_SCRIPT", null); }
            return;
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new ColdVoiceBootstrap());
    }
    static bool VerifyIcon(string source) {
        try {
            using (var embedded = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location))
            using (var requested = new Icon(source, new Size(32, 32))) {
                if (embedded == null) return false;
                using (var actual = new Bitmap(embedded.ToBitmap(), new Size(32, 32)))
                using (var expected = new Bitmap(requested.ToBitmap(), new Size(32, 32))) {
                    long difference = 0;
                    for (int y = 0; y < 32; ++y)
                        for (int x = 0; x < 32; ++x) {
                            Color a = actual.GetPixel(x, y), b = expected.GetPixel(x, y);
                            difference += Math.Abs(a.R - b.R) + Math.Abs(a.G - b.G) + Math.Abs(a.B - b.B) + Math.Abs(a.A - b.A);
                        }
                    return difference < 32L * 32L * 4L * 18L;
                }
            }
        } catch { return false; }
    }
    ColdVoiceBootstrap() {
        Text = "ColdVoice — українська локалізація";
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.None;
        BackColor = Color.FromArgb(12, 14, 18);
        ClientSize = new Size(900, 510);
        TopMost = true;
        var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("SplashImage");
        if (stream != null) {
            using (stream) using (var raw = Image.FromStream(stream)) {
                picture.Image = new Bitmap(raw);
            }
        }
        picture.Dock = DockStyle.Fill;
        picture.BackColor = BackColor;
        picture.SizeMode = PictureBoxSizeMode.Zoom;
        Controls.Add(picture);
        var band = new Panel();
        band.Dock = DockStyle.Bottom;
        band.Height = 102;
        band.BackColor = Color.FromArgb(15, 18, 24);
        Controls.Add(band);
        band.BringToFront();
        title.Text = "COLDVOICE";
        title.ForeColor = Color.FromArgb(244, 246, 248);
        title.Font = new Font("Segoe UI", 23, FontStyle.Bold);
        title.Location = new Point(38, 13);
        title.Size = new Size(700, 46);
        band.Controls.Add(title);
        caption.Text = "Підготовка інсталятора…";
        caption.ForeColor = Color.FromArgb(160, 176, 190);
        caption.Font = new Font("Segoe UI", 11);
        caption.Location = new Point(40, 60);
        caption.Size = new Size(750, 30);
        band.Controls.Add(caption);
        Shown += async (s, e) => await StartInstaller();
        FormClosing += (s, e) => { if (!closeAllowed) e.Cancel = true; };
    }
    bool closeAllowed = false;
    async Task StartInstaller() {
        var clock = Stopwatch.StartNew();
        try {
            temporary = Path.Combine(Path.GetTempPath(), "ColdVoiceSetup_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temporary);
            await Task.Run(() => ExtractPayload(temporary));
            if (clock.ElapsedMilliseconds < 2000)
                await Task.Delay((int)(2000 - clock.ElapsedMilliseconds));
            caption.Text = "Запуск майстра…";
            Hide();
            await Task.Delay(1000);
            Environment.SetEnvironmentVariable("COLDVOICE_INSTALL_ROOT", temporary);
            string wizardError = null;
            var wizardThread = new Thread(() => {
                try { wizardError = RunPowerShellScript(File.ReadAllText(Path.Combine(temporary, "INSTALL.ps1"), Encoding.UTF8)); }
                catch (Exception ex) { wizardError = ex.ToString(); }
            });
            wizardThread.SetApartmentState(ApartmentState.STA);
            wizardThread.Start();
            await Task.Run(() => wizardThread.Join());
            if (!String.IsNullOrWhiteSpace(wizardError))
                MessageBox.Show("Майстер не запустився:\n" + wizardError, "ColdVoice", MessageBoxButtons.OK, MessageBoxIcon.Error);
        } catch (Exception ex) {
            Hide();
            MessageBox.Show(ex.Message, "ColdVoice — помилка запуску", MessageBoxButtons.OK, MessageBoxIcon.Error);
        } finally {
            Environment.SetEnvironmentVariable("COLDVOICE_INSTALL_ROOT", null);
            try { if (temporary != null) Directory.Delete(temporary, true); } catch { }
            closeAllowed = true;
            Close();
        }
    }
    [DllImport("ole32.dll")]
    static extern int OleInitialize(IntPtr reserved);
    [DllImport("ole32.dll")]
    static extern void OleUninitialize();
    static string RunPowerShellScript(string script) {
        // STA alone does not explicitly initialize the OLE shell services.
        int result = OleInitialize(IntPtr.Zero);
        if (result < 0) Marshal.ThrowExceptionForHR(result);
        try { return RunPowerShellScriptCore(script); }
        finally { OleUninitialize(); } // Balance both S_OK and S_FALSE.
    }
    static string RunPowerShellScriptCore(string script) {
        var automation = Assembly.Load("System.Management.Automation, Version=3.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35");
        Type factory = automation.GetType("System.Management.Automation.Runspaces.RunspaceFactory", true);
        object runspace = factory.GetMethod("CreateRunspace", Type.EmptyTypes).Invoke(null, null);
        try {
            Type rsType = runspace.GetType();
            rsType.GetProperty("ApartmentState").SetValue(runspace, ApartmentState.STA, null);
            Type optionType = automation.GetType("System.Management.Automation.Runspaces.PSThreadOptions", true);
            rsType.GetProperty("ThreadOptions").SetValue(runspace, Enum.Parse(optionType, "UseCurrentThread"), null);
            rsType.GetMethod("Open", Type.EmptyTypes).Invoke(runspace, null);
            Type psType = automation.GetType("System.Management.Automation.PowerShell", true);
            object pipeline = psType.GetMethod("Create", Type.EmptyTypes).Invoke(null, null);
            try {
                psType.GetProperty("Runspace").SetValue(pipeline, runspace, null);
                psType.GetMethod("AddScript", new Type[] { typeof(string) }).Invoke(pipeline, new object[] { script });
                MethodInfo invoke = null;
                foreach (var method in psType.GetMethods())
                    if (method.Name == "Invoke" && !method.IsGenericMethod && method.GetParameters().Length == 0) {
                        invoke = method; break;
                    }
                if (invoke == null) throw new MissingMethodException("PowerShell.Invoke");
                invoke.Invoke(pipeline, null);
                var streams = psType.GetProperty("Streams").GetValue(pipeline, null);
                var errors = streams.GetType().GetProperty("Error").GetValue(streams, null);
                var result = new StringBuilder();
                foreach (object item in (System.Collections.IEnumerable)errors) result.AppendLine(item.ToString());
                return result.ToString();
            } finally { ((IDisposable)pipeline).Dispose(); }
        } finally { ((IDisposable)runspace).Dispose(); }
    }
    static void ExtractPayload(string destination) {
        string executable = Assembly.GetExecutingAssembly().Location;
        string archive = Path.Combine(destination, "bundle.zip");
        byte[] magic = Encoding.ASCII.GetBytes(Magic);
        using (var source = File.OpenRead(executable)) {
            if (source.Length < magic.Length + 8) throw new InvalidDataException("EXE не містить комплекту локалізації.");
            source.Seek(-magic.Length, SeekOrigin.End);
            byte[] end = new byte[magic.Length];
            if (source.Read(end, 0, end.Length) != end.Length || Encoding.ASCII.GetString(end) != Magic)
                throw new InvalidDataException("Контейнер EXE пошкоджений.");
            source.Seek(-magic.Length - 8, SeekOrigin.End);
            byte[] size = new byte[8];
            if (source.Read(size, 0, 8) != 8) throw new InvalidDataException("Некоректна довжина комплекту.");
            long count = BitConverter.ToInt64(size, 0);
            long offset = source.Length - magic.Length - 8 - count;
            if (count < 100 || offset < 0) throw new InvalidDataException("Некоректний комплект у EXE.");
            source.Seek(offset, SeekOrigin.Begin);
            using (var target = File.Create(archive)) {
                byte[] buffer = new byte[4 * 1024 * 1024];
                while (count > 0) {
                    int requested = (int)Math.Min(count, buffer.Length);
                    int received = source.Read(buffer, 0, requested);
                    if (received <= 0) throw new EndOfStreamException("Комплект обірвано.");
                    target.Write(buffer, 0, received);
                    count -= received;
                }
            }
        }
        using (var z = ZipFile.OpenRead(archive)) {
            foreach (var entry in z.Entries) {
                string full = Path.GetFullPath(Path.Combine(destination, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                if (!full.StartsWith(Path.GetFullPath(destination) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Небезпечний шлях у комплекті.");
            }
        }
        ZipFile.ExtractToDirectory(archive, destination);
        File.Delete(archive);
        if (!File.Exists(Path.Combine(destination, "INSTALL.ps1")))
            throw new InvalidDataException("Бракує майстра встановлення.");
    }
}
