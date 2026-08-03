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
    private static readonly string LogPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "YouTubeBilingualAssistant", "native-service.log");

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
                if (action == "start") StartService();
                WriteMessage(Json.Serialize(new { ok = true, running = service != null && !service.HasExited }));
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
        Directory.CreateDirectory(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "YouTubeBilingualAssistant"));
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
