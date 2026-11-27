# Resource policy and production scaling — 0.1.0-rc2

The laptop is a development environment, not a product capacity specification.
No sustained production-server capacity has been measured. Allocation templates
are starting configurations, never certified camera counts or hardware purchases.

## Preventive policy

All measured resource dimensions use configurable warning/reduction/admission
thresholds, default 75/80/85 percent. CPU, RAM, storage, GPU utilization, VRAM and
network are sampled at most every five seconds per process. CPU/RAM consider both
process-visible host and cgroup v2 allocation. Recovery uses a three-point margin
to avoid repeated pause/resume around a boundary. Adjust via VMS_RESOURCE_WARN,
VMS_RESOURCE_REDUCE, VMS_RESOURCE_BLOCK and VMS_RESOURCE_HYSTERESIS.

- Warning: log a state transition and show a System Monitor alert.
- Reduction: AI stops its optional samplers, discards queued frames, and releases
  its detector/CUDA cache. Load tests suspend optional playlist polling.
- Admission block: reject new camera starts with retryable HTTP 503, refuse new
  recorder allocations and initial preview manifests/WHEP requests. Existing HLS
  clients that reload the initial manifest can also lose preview under pressure.
  Recording has priority over preview. A configured recorder count returns 409.

Existing recorder processes are not stopped for utilization warnings. Desired
recordings already present at supervisor startup, and admitted cameras reconnecting
after a fault, retain recovery priority. Actual minimum free-byte exhaustion still
finalizes recording safely to avoid disk corruption; this is separate from the
utilization warning. Storage retention/deletion remains disabled. Graceful test
cleanup stops only synthetic publishers/cameras created by that test run.

Unknown metrics are reported explicitly, never represented as zero. GPU readings
need nvidia-smi visibility. Network usage needs VMS_NETWORK_INTERFACE and accurate
VMS_NETWORK_MBPS for that interface; utilization uses the larger transmit/receive
rate for a full-duplex link. VMS_REQUIRED_METRICS can require comma-separated
cpu,ram,storage,gpu,vram,network; missing required readings block admission.
Metrics should represent the recorder node, not a remote operator's browser.

Docker Desktop cannot see Windows host pressure completely. For host-aware control,
run the developer host_resources.py publisher with an administrator-owned output
directory and mount it read-only using compose.host-monitor.yml. Set
VMS_HOST_METRICS_DIRECTORY to the directory and run the publisher with output
resources.json every five seconds. Consumers reject new work when configured host
telemetry is missing or older than 15 seconds. An absent optional host feed does
not imply host coverage. Installing an unattended host monitoring agent for customer
machines remains deployment engineering work; no privileged container is required.

The start script accepts `-HostMonitor` to add that overlay, after the private
configuration defines VMS_HOST_METRICS_DIRECTORY and the host feed is running.
The supplied Python publisher is an integrator/development tool; an unattended
customer host-agent installer is not yet supplied.

## Profiles and overrides

Run `./scripts/start.ps1 -Profile development|small|medium|enterprise` (choose one).
Status/stop accept the same profile. The profile file is loaded first, then private
installation configuration; explicit installation values take precedence. Existing
configurations containing VMS_MAX_RECORDERS=16 retain that administrator override;
change it explicitly when qualifying a larger deployment. New setup does not impose
that value. The application no longer imposes a 256-camera/8-item AI batch ceiling.

| Template | Recorder admission guard | API processes | Recorder CPU / RAM |
| --- | ---: | ---: | --- |
| development | 4 | 1 | 2 / 1 GiB |
| small | 16 | 2 | 4 / 2 GiB |
| medium | 64 | 4 | 8 / 8 GiB |
| enterprise | 512 | 8 | 32 / 32 GiB |

All are unqualified allocations. Tune VMS_MAX_RECORDERS, VMS_API_WORKERS,
VMS_API_MEMORY/CPUS/PIDS, VMS_RECORDER_MEMORY/CPUS/PIDS, VMS_MEDIA_MEMORY/CPUS,
VMS_DB_POOL_SIZE/MAX_OVERFLOW, VMS_AI_MAX_CAMERAS/BATCH_SIZE/SAMPLE_INTERVAL_MS,
MIN_FREE_BYTES and the recording volume/mount. Budget DB connections across API
processes and nodes; recorder supervision keeps one dedicated ownership connection.
Do not launch enterprise allocations on the laptop. Profile files contain no secrets.

On Windows the start script checks host CPU/RAM before building or starting
services and refuses at 85 percent by default. The separately configurable
StartupBlockPercent parameter controls this preflight. It leaves already running
services unchanged. Runtime thresholds come from the deployment configuration;
this preflight does not replace ongoing host telemetry or GPU/storage monitoring.

## Horizontal scale and multiple media/recording servers

The supported composition boundary is a camera partition: API, media distribution,
recorder, metadata database and recording volume. Multiple API processes share
the database and Redis; camera admission is serialized by a PostgreSQL transaction
lock. Media pulls each configured main/substream once and distributes it to clients.
Recorder uses stream-copy video; AI uses one latest-frame slot per admitted camera,
not an unbounded queue. Stopped AI decoders must exit before replacement starts.

For multiple servers, deploy separate partitions with unique project names,
databases, storage volumes, camera assignments, TLS hostnames and approved CIDRs.
Use [partition examples](../deployment/multiserver/README.md). This supplies multiple
recording/streaming servers without pretending a laptop sets the system ceiling.
Each partition has its own operator endpoint and administrator setup. A federated
single dashboard, automatic camera placement, shared-database recorder sharding,
cross-node playback routing and automatic recorder failover are **not implemented**.
Do not scale recorder replicas against one database: ownership deliberately rejects
duplicates. Proper unified multi-server management remains a release requirement,
not something established by a Compose profile or a diagram.

## Capacity and future tests

Laptop evidence remains four temporary 320x180/5 fps H.264 streams with a safety
stop, not a sustained supported count. Previous 90% cutoff evidence is historical;
the harness now checks 75/80/85 policy before launch, before each extra publisher,
and throughout measurement. It accepts positive camera counts including 32/64/128
on qualified infrastructure. Soak profiles cover 31 minutes and 2/8/24/72 hours.
GPU/network/storage policy readings and unknowns are included in results.

The synthetic harness still targets the isolated validation project. Run it on a
dedicated benchmark host per partition; changing a camera count is not permission
to discover or stress customer networks. Separate recording-only, viewers, playback
and AI workloads; record codec/resolution/bitrate/FPS/GOP, resource trends, recording
gaps, viewer decode latency and errors. Arithmetic storage estimates are separate
from measured capacity. No production-server benchmark or multi-server failover
test has been completed on this development laptop.
