# Roadmap: 2026-10-12 to 2027-10-12

This is the intended direction for the next year, not a delivery guarantee.
The maintainer may revise priorities through public issues and pull requests.
[Completed releases](https://github.com/4alvit/mcp-venus-os/releases) and
[CHANGELOG.md](CHANGELOG.md) describe achievements; the older [TODO.md](TODO.md)
is historical implementation context rather than a future commitment.

## Intended work

1. Preserve reliable read-only MQTT and optional local D-Bus telemetry, with
   bounded caches, explicit stale-data reporting and predictable reconnects.
2. Keep control disabled by default. Improve evidence for target-specific
   firmware/BMS write contracts and failure-path tests before expanding writes.
3. Maintain current supported Python, FastMCP, Paho and AsyncSSH integration;
   update locked dependencies and keep certificate/SSH-key checks fail closed.
4. Measure the complete Python runtime and operational-tooling coverage,
   strengthen regression tests, and keep builds and release verification
   reproducible from documented inputs.
5. Make installation, upgrade, credential rotation and recovery procedures
   easier to reproduce with local fixtures and clearly separated target-device
   acceptance. Add signed-release verification evidence as it becomes available.
6. Establish real maintainer succession/access recovery, improve contribution
   onboarding, and close the remaining OpenSSF evidence gaps honestly.

## Outside the intended scope

The project will not become a firmware implementation, a replacement BMS,
a certified hardware safety controller, or an autonomous energy-management
policy. It will not infer permission to operate equipment from a chat response,
a telemetry echo or a successful CI build. Supporting arbitrary device writes,
unreviewed firmware command mappings, unknown SSH hosts, weak cryptography or
public unauthenticated control endpoints is not a roadmap goal.
