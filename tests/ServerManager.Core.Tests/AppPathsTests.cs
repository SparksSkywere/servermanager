using ServerManager.Core;
using ServerManager.Core.Configuration;
using ServerManager.Core.Paths;
using ServerManager.Core.Process;
using Microsoft.Extensions.Options;
using Xunit;

namespace ServerManager.Core.Tests;

public class AppPathsTests
{
    [Fact]
    public void EnsureDirectories_CreatesRuntimeTree()
    {
        var root = Path.Combine(Path.GetTempPath(), "sm-dotnet-test-" + Guid.NewGuid().ToString("N"));
        var paths = new AppPaths(Options.Create(new ServerManagerOptions { RootPath = root }));
        paths.EnsureDirectories();
        Assert.True(Directory.Exists(paths.Db));
        Assert.True(Directory.Exists(paths.Temp));
        Assert.True(Directory.Exists(paths.ComponentsLogs));
        Directory.Delete(root, true);
    }
}

public class PidFileManagerTests
{
    [Fact]
    public void WriteReadRemove_RoundTrips()
    {
        var root = Path.Combine(Path.GetTempPath(), "sm-dotnet-pid-" + Guid.NewGuid().ToString("N"));
        var paths = new AppPaths(Options.Create(new ServerManagerOptions { RootPath = root }));
        paths.EnsureDirectories();
        var pids = new PidFileManager(paths);
        pids.Write("testcomp", Environment.ProcessId);
        Assert.Equal(Environment.ProcessId, pids.Read("testcomp"));
        Assert.True(pids.IsComponentRunning("testcomp"));
        pids.Remove("testcomp");
        Assert.Null(pids.Read("testcomp"));
        Directory.Delete(root, true);
    }
}

public class ProcessIdentityTests
{
    [Fact]
    public void IsRunning_CurrentProcess_True()
    {
        var svc = new ProcessIdentityService(new Microsoft.Extensions.Logging.Abstractions.NullLogger<ProcessIdentityService>());
        Assert.True(svc.IsRunning(Environment.ProcessId));
    }
}
