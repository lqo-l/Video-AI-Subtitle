// Moon Begin
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class Program
{
    private static Process service;
    private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    // Moon Modified: keep launcher output with the rest of the user-facing diagnostics.
    private static readonly string LogPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "YouTubeBilingualAssistant", "logs", "native-service.log");

    private static void Main()
    {
        try
        {
            while (true)
            {
                string message = ReadMessage();
                if (message == null) break;
                dynamic request = Json.DeserializeObject(message);
                string action = request.ContainsKey("action") ? request["action"] as string : "";
                if (action == "start")
                {
                    StartService();
                    WriteMessage(Json.Serialize(new { ok = true, running = service != null && !service.HasExited }));
                }
                else if (action == "update")
                {
                    // Moon Add: only the registered local host may replace an unpacked extension's files.
                    string url = request.ContainsKey("url") ? request["url"] as string : "";
                    string digest = request.ContainsKey("digest") ? request["digest"] as string : "";
                    string version = request.ContainsKey("version") ? request["version"] as string : "";
                    string extensionId = request.ContainsKey("extensionId") ? request["extensionId"] as string : "";
                    InstallUpdate(url, digest, version, extensionId);
                    WriteMessage(Json.Serialize(new { ok = true, version = version }));
                }
                else
                {
                    WriteMessage(Json.Serialize(new { ok = false, error = "未知的本机操作" }));
                }
            }
        }
        catch (Exception error)
        {
            WriteMessage(Json.Serialize(new { ok = false, error = error.Message }));
        }
        finally
        {
            StopService();
        }
    }

    private static void StartService()
    {
        if (service != null && !service.HasExited) return;
        string hostDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string projectRoot = Directory.GetParent(hostDirectory.TrimEnd(Path.DirectorySeparatorChar)).FullName;
        string python = Path.Combine(projectRoot, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python)) throw new FileNotFoundException("请先运行 scripts\\install.ps1", python);
        Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-m uvicorn service.app.main:app --host 127.0.0.1 --port 18765",
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        service = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        service.OutputDataReceived += LogLine;
        service.ErrorDataReceived += LogLine;
        service.Start();
        service.BeginOutputReadLine();
        service.BeginErrorReadLine();

        // Moon Add: do not report success until the HTTP endpoint is actually healthy.
        for (int attempt = 0; attempt < 40; attempt++)
        {
            if (service.HasExited) throw new InvalidOperationException("本机服务启动失败，请查看 native-service.log");
            try
            {
                using (var client = new System.Net.WebClient())
                {
                    string response = client.DownloadString("http://127.0.0.1:18765/health");
                    if (response.Contains("\"ok\":true")) return;
                }
            }
            catch { Thread.Sleep(250); }
        }
        throw new TimeoutException("本机服务启动超时，请查看 native-service.log");
    }

    private static void LogLine(object sender, DataReceivedEventArgs args)
    {
        if (string.IsNullOrEmpty(args.Data)) return;
        try { File.AppendAllText(LogPath, DateTime.Now.ToString("s") + " " + args.Data + Environment.NewLine); }
        catch { }
    }

    private static void StopService()
    {
        if (service == null || service.HasExited) return;
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                Arguments = "/PID " + service.Id + " /T /F",
                UseShellExecute = false,
                CreateNoWindow = true
            }).WaitForExit(5000);
        }
        catch { }
    }

    private static void InstallUpdate(string url, string digest, string version, string extensionId)
    {
        Uri releaseUrl;
        if (!Uri.TryCreate(url, UriKind.Absolute, out releaseUrl) || releaseUrl.Scheme != Uri.UriSchemeHttps || releaseUrl.Host != "github.com")
            throw new InvalidOperationException("更新包地址无效");
        if (string.IsNullOrWhiteSpace(digest) || !digest.StartsWith("sha256:"))
            throw new InvalidOperationException("更新包缺少 SHA-256 校验信息");
        if (string.IsNullOrWhiteSpace(extensionId) || extensionId.Length != 32)
            throw new InvalidOperationException("扩展 ID 无效，无法完成更新后的本机启动器注册");

        string hostDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string projectRoot = Directory.GetParent(hostDirectory.TrimEnd(Path.DirectorySeparatorChar)).FullName;
        string updater = Path.Combine(projectRoot, "scripts", "update.ps1");
        if (!File.Exists(updater)) throw new FileNotFoundException("当前版本不支持一键更新，请手动安装此版本后重试", updater);

        LogText("extension_update_started version=" + version);
        ProcessStartInfo startInfo = new ProcessStartInfo
        {
            FileName = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"),
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File " + Quote(updater) + " -Url " + Quote(url) + " -Digest " + Quote(digest) + " -Version " + Quote(version) + " -HostPid " + Process.GetCurrentProcess().Id + " -ExtensionId " + Quote(extensionId),
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        using (Process updaterProcess = new Process { StartInfo = startInfo })
        {
            updaterProcess.OutputDataReceived += LogLine;
            updaterProcess.ErrorDataReceived += LogLine;
            updaterProcess.Start();
            updaterProcess.BeginOutputReadLine();
            updaterProcess.BeginErrorReadLine();
            updaterProcess.WaitForExit();
            if (updaterProcess.ExitCode != 0) throw new InvalidOperationException("更新失败，请在诊断日志中查看详细原因");
        }
        LogText("extension_update_completed version=" + version);
    }

    private static string Quote(string value)
    {
        return "\"" + (value ?? "").Replace("\"", "\\\"") + "\"";
    }

    private static void LogText(string message)
    {
        try { File.AppendAllText(LogPath, DateTime.Now.ToString("s") + " " + message + Environment.NewLine); }
        catch { }
    }

    private static string ReadMessage()
    {
        Stream input = Console.OpenStandardInput();
        byte[] lengthBytes = new byte[4];
        if (input.Read(lengthBytes, 0, 4) != 4) return null;
        int length = BitConverter.ToInt32(lengthBytes, 0);
        byte[] body = new byte[length];
        int offset = 0;
        while (offset < length)
        {
            int read = input.Read(body, offset, length - offset);
            if (read <= 0) return null;
            offset += read;
        }
        return Encoding.UTF8.GetString(body);
    }

    private static void WriteMessage(string message)
    {
        byte[] body = Encoding.UTF8.GetBytes(message);
        Stream output = Console.OpenStandardOutput();
        output.Write(BitConverter.GetBytes(body.Length), 0, 4);
        output.Write(body, 0, body.Length);
        output.Flush();
    }
}
// Moon End
