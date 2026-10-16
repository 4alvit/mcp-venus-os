# HTTP session lifecycle

MCP Venus OS 0.2.15 requires MCP Python SDK 1.30.0 or newer in the 1.x series.
This addresses [CVE-2026-59951](https://github.com/advisories/GHSA-84m7-p3x7-pcfv)
in stateful Streamable HTTP, including the `--transport http` deployment.

The SDK removes sessions after deletion, expiry or a rejected opening request.
Sessions expire after 30 minutes with no active request. Open streams remain
active. At 10,000 sessions, new sessions receive HTTP 503 until capacity becomes
available. An expired session receives HTTP 404; the client must initialize a
new session. These defaults do not affect stdio transport.

Upgrade the package or replace the container and retain existing configuration.
A restart ends existing HTTP sessions. Authentication, network restrictions and
resource limits remain necessary; lifecycle limits do not grant access or change
hardware write permissions. Automated lifecycle tests use the real HTTP stack
with synthetic device startup and never connect to hardware.
