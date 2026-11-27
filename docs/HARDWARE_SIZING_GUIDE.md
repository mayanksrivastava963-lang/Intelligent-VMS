# Hardware Sizing Guide

## Reference Architectures

### Small Deployment (1-16 cameras)

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Storage | 500 GB SSD | 1 TB NVMe |
| Network | 100 Mbps | 1 Gbps |
| GPU | Not required | Optional for AI |

### Medium Deployment (16-32 cameras)

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 8 cores | 16 cores |
| RAM | 16 GB | 32 GB |
| Storage | 2 TB NVMe | 4 TB NVMe RAID |
| Network | 1 Gbps | 2.5 Gbps |
| GPU | Not required | GTX 1660+ for AI |

### Enterprise Deployment (32-60+ cameras)

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 16 cores | 32+ cores |
| RAM | 32 GB | 64 GB |
| Storage | 8 TB NVMe RAID | 16+ TB NVMe RAID |
| Network | 2.5 Gbps | 10 Gbps |
| GPU | RTX 3060 6GB | RTX 4070+ 12GB |

## Storage Calculations

Each camera stream consumes approximately:
- **1080p @ 4Mbps**: ~1.7 GB/hour, ~41 GB/day
- **4K @ 8Mbps**: ~3.4 GB/hour, ~82 GB/day
- **720p @ 2Mbps**: ~0.86 GB/hour, ~20 GB/day

### 30-Day Retention Examples

| Cameras | Resolution | Daily Storage | 30-Day Total |
|---|---|---|---|
| 16 | 1080p | 656 GB | 19.2 TB |
| 32 | 1080p | 1.3 TB | 38.4 TB |
| 60 | 1080p | 2.4 TB | 72 TB |
| 60 | Mixed | ~1.8 TB | ~54 TB |

## Network Bandwidth

Each camera requires sustained bandwidth for its stream bitrate plus ~10% overhead.

| Cameras | Avg Bitrate | Required Bandwidth |
|---|---|---|
| 16 | 4 Mbps | ~70 Mbps |
| 32 | 4 Mbps | ~140 Mbps |
| 60 | 4 Mbps | ~264 Mbps |

## AI Processing Requirements

The AI worker uses SSDLite320 MobileNetV3 for object detection:
- **CPU mode**: ~100-200ms per frame, suitable for 2-4 cameras
- **GPU mode (GTX 1660)**: ~15-30ms per frame, suitable for 8-16 cameras
- **GPU mode (RTX 3060+)**: ~8-15ms per frame, suitable for 16-32 cameras
- **GPU mode (RTX 4070+)**: ~5-10ms per frame, suitable for 32-60 cameras

AI is independently toggled per camera and does not affect recording.

## Configuration Parameters

Key environment variables for tuning:

| Variable | Default | Description |
|---|---|---|
| `VMS_MAX_RECORDERS` | 16 | Maximum concurrent recording processes |
| `VMS_API_WORKERS` | 2 | API server worker processes |
| `VMS_API_MEMORY` | 768m | API container memory limit |
| `VMS_RECORDER_MEMORY` | 2g | Recorder container memory limit |
| `VMS_AI_MEMORY` | 4g | AI worker container memory limit |
| `VMS_RESOURCE_WARN` | 75 | Resource warning threshold (%) |
| `VMS_RESOURCE_REDUCE` | 80 | Resource reduction threshold (%) |
| `VMS_RESOURCE_BLOCK` | 85 | New admission block threshold (%) |
| `RECORDING_SEGMENT_SECONDS` | 1800 | Segment rotation interval (seconds) |
| `RECORDING_RETENTION_DAYS` | 30 | Days to retain recordings |
