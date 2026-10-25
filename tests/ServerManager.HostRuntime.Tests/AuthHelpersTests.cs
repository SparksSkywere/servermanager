using ServerManager.Security;
using Xunit;

namespace ServerManager.HostRuntime.Tests;

public class AuthHelpersTests
{
    [Fact]
    public void GenerateTotpSecret_IsBase32()
    {
        var secret = AuthService.GenerateTotpSecret();
        Assert.False(string.IsNullOrWhiteSpace(secret));
        Assert.Matches("^[A-Z2-7]+$", secret);
    }

    [Fact]
    public void RateLimiter_BlocksAfterLimit()
    {
        var limiter = new RateLimiter();
        Assert.True(limiter.Allow("k", 2, TimeSpan.FromMinutes(1)));
        Assert.True(limiter.Allow("k", 2, TimeSpan.FromMinutes(1)));
        Assert.False(limiter.Allow("k", 2, TimeSpan.FromMinutes(1)));
    }

    [Fact]
    public void AccountLockout_LocksAfterFailures()
    {
        var lockout = new AccountLockoutService();
        for (var i = 0; i < 5; i++) lockout.RegisterFailure("admin");
        Assert.True(lockout.IsLocked("admin"));
        lockout.Reset("admin");
        Assert.False(lockout.IsLocked("admin"));
    }
}
