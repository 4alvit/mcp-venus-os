# Hardware write qualification

`SAFETY_ENABLE_WRITES=true` and confirmation are necessary but do not qualify a
new device. MQTT control writes also require exactly one entry in
`SAFETY_HARDWARE_WRITE_CONTRACTS` (a JSON array). The default is an empty array.
Existing installations without reviewed contracts will reject control writes
after upgrading; collect and review target evidence before enabling them.

Each contract binds an exact portal ID, device type, instance and path to five
fresh identity observations: Venus firmware, target product and firmware, BMS
product and firmware. Configure the actual identity topic paths exposed by the
qualified device; there is no discovery-based approval or wildcard matching.
Missing, changed or stale identities block publication. The schema is generated
from `HardwareWriteContract` in `hardware_contracts.py`.

For `/Mode`, the reviewed contract maps semantic mode names to their observed,
documented numeric codes. A mismatch with the implementation's mapping is denied;
the contract does not silently change that mapping. For charge current and
`/SocLimit`, the contract records units and the hardware-qualified numeric range.
All existing global parameter and confirmation checks still apply.

Qualification evidence must include the exact firmware/BMS tuple, authoritative
path semantics, the operator-reviewed test procedure, raw before/after observations
and physical response, failure/rollback behavior, reviewer identity and the SHA-256
of the retained evidence bundle. Set `reviewed_by`, `semantics` and
`evidence_sha256` only after that review. These are trusted operator configuration;
the server does not certify the external physical experiment or fetch evidence.
Never produce a contract merely because an MQTT value echoed successfully.

Successful calls report `verification: fresh_read_back`, the contract ID and the
evidence digest. A cached value received before the write cannot acknowledge it,
even if the decoder processes it after publication: freshness uses the network
receive timestamp, including time spent waiting in the inbox. Empty device-removal
notifications invalidate the cached value and identity.
Even a fresh echo only proves the reported value: it does not prove the physical
meaning of the operation. The server publishes only to the exact qualified path,
without periodic writes to an additional `/Keepalive` path.

There is no automatic rollback. A command may persist after disconnect, shutdown
or a read-back timeout; the qualified device owns that behavior. A timeout does
not prove the device rejected the write. Successful calls explicitly report
`automatic_rollback: false`. Any required watchdog or expiry must be qualified
for the actual target; this server does not create that mechanism.

The gateway's [MQTT keep-alive](https://github.com/victronenergy/dbus-flashmq#keep-alive)
at `R/<portalId>/keepalive` controls telemetry publication. Its 60-second timer
does not establish an expiry guarantee for arbitrary `W/` control values.

The unit suite uses explicitly synthetic records. No production target or BMS is
approved by the repository, and the existing mode table is not expanded here.
