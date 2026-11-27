# Commercial Licensing Assessment — 0.1.0-rc3 (2026-11-27)

**Status: Incomplete — NO commercial redistribution or legal clearance is asserted.**
All source packages exclude binary images, model weights, video footage, and customer secrets. Final legal review is mandatory before customer distribution.

| Component | Actual Evidence & Licensing Terms | Engineering Action / Mitigation Available |
| --- | --- | --- |
| **Redis 7.4.12** (`redis:7-alpine`) | **RSALv2 / SSPLv1** (source-available, NOT OSI BSD-3-Clause). Hosting or commercial managed/redistributed offerings require legal review. | **Mitigation added:** Created [`compose.valkey.yml`](../compose.valkey.yml) using **Valkey 8** (`valkey/valkey:8-alpine`, **BSD-3-Clause** Linux Foundation fork, wire & Lua script compatible). Furthermore, when running 1 API worker without `ai-worker`, Redis is optional (`LoginLimiter` falls back to local process state). |
| **FFmpeg 5.1.9** (Debian Bookworm build) | Built with `--enable-gpl`, `--enable-libx264`, `--enable-libx265`. Do NOT label as LGPL-only. | VMS uses `-c:v copy` (stream copy) for recording (`-c:a aac` default or `-an` / `-c:a copy`), avoiding video transcoding at runtime. However, shipping the GPL-enabled binary/image triggers GPLv2+/v3 source-offer & compliance obligations (or switching to an LGPL-only custom FFmpeg build). Patent review for H.264/HEVC remains separate. |
| **PyTorch 2.11 / Torchvision 0.26 & SSDLite Weights** | Framework is BSD-3-Clause; **SSDLite320 MobileNetV3** weights carry COCO/upstream dataset & model terms that require verification for commercial analytics. CUDA wheels bundle proprietary NVIDIA runtime redistribution rules. | `ai-worker` is excluded from default runtime (`--profile ai`) and built separately (`services/ai_engine/Dockerfile`). Weights are cached at runtime (`ai_model_cache`), not embedded in source ZIPs. |
| **MediaMTX 1.21.4** | MIT License (`bluenviron/mediamtx:v1.21.4/LICENSE`). | Preserve upstream MIT copyright and license text in redistribution notices. |
| **PostgreSQL 18** | PostgreSQL License (permissive). | External DB supported by default; `compose.bundled-db.yml` optional. |
| **Frontend JS (`React`, `hls.light.mjs`)** | `React` (MIT), `hls.js` / `hls.light.mjs` (Apache-2.0). `npm audit --omit=dev` reported 0 runtime vulnerabilities earlier (see `release-evidence/javascript-audit.json`). | Preserve Apache-2.0 & MIT notices. |
| **Nginx & Debian OS Base Images** | Mixed OS licenses inside `node:24-bookworm-slim`, `python:3.12-slim-bookworm`, `nginx:stable-alpine`. | Full OS license bundle (`debian-packages.tsv`) + Trivy/Grype CVE scan of freshly built `0.1.0-rc3` images required before commercial release. |
| **Docker Desktop** | Free for personal / <250 employee & <\$10M revenue small business; **paid subscription required** for larger commercial or government deployments on Windows. Linux Docker Engine (Moby, Apache-2.0) has no Docker Desktop subscription fee. | Customer must provide licensed Docker Desktop (Windows) or Linux Docker Engine. |

## Items Requiring Formal Legal Sign-Off Before Sale

1. Confirm selection of `-Valkey` (`compose.valkey.yml`) vs licensed Redis.
2. Decide between providing Debian FFmpeg GPL corresponding source / compliance pack OR compiling an LGPL-only FFmpeg build for container images.
3. Approve SSDLite320 pretrained weight terms if AI analytics (`--profile ai`) is bundled or enabled.
4. Establish proprietary EULA/copyright ownership notice for Intelligent-VMS itself.
