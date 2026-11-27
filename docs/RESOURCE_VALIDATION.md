# Resource-Policy Validation & Server Readiness — 0.1.0-rc3 (2026-11-27)

## Current Host Observation (Development Laptop Only)

- **Laptop hardware:** 16 logical cores, 15.82 GiB RAM, RTX 3050 Laptop (4096 MiB VRAM).
- **Observed host state:** RAM at **89–96%** (mostly desktop IDE + browsers; running validation containers consume ~312 MiB total).
- **Deployed validation stack:** Remains on earlier `intelligent-vms-api:0.1.0` (`sha256:116207296979`, built `2026-11-27 10:53 +0530`, confirmed via live probe `GET /api/version` returning `404` while `GET /api/health` returns `200`).
- **Safety guard respected:** `scripts/start.ps1` (`StartupBlockPercent=85`) intentionally blocks rebuilding/restarting heavy container workloads on an overloaded laptop rather than bypassing memory protection. All 4 historical synthetic publishers (`vms-validation-publisher-1795756358-0..3`) are already exited (`Exited (255)`).

## Validated in `0.1.0-rc3` Source Tree

- All 6 Docker Compose configurations parse cleanly (`docker compose config --quiet` exit `0`):
  - `compose.production.yml`
  - `compose.production.yml` + `compose.validation.yml`
  - `compose.production.yml` + `compose.bundled-db.yml`
  - `compose.production.yml` + `compose.ai-gpu.yml --profile ai`
  - `compose.production.yml` + `compose.valkey.yml`
  - `compose.production.yml` + `compose.distributed-recorders.yml`
- Frontend TypeScript check + Vite build passes with 0 warnings (`hls.light` async chunk = `361.95 kB`).
- Validation tooling dry checks pass (`rotation_test.py --help`, `progressive_load_test.py --dry-run` respecting live ResourceGuard block).

## Commands to Execute on Dedicated Production Server

1. **Build and deploy `0.1.0-rc3`:**
   ```powershell
   ./scripts/setup.ps1 -TlsDirectory 'C:\VMS-Certificates'
   ./scripts/start.ps1 -Build -Profile enterprise -DistributedRecorders -AiGpu
   curl.exe -sk https://localhost:8443/api/version
   ```
2. **Verify 30-minute (`1800s`) rotation continuity:**
   ```powershell
   python scripts/rotation_test.py --env-file .env.production --segment-seconds 1800 --report rotation-report.json
   ```
3. **Run progressive load test (`4 -> 8 -> 16 -> 32 -> 48 -> 60`):**
   ```powershell
   python scripts/progressive_load_test.py --tiers 4,8,16,32,48,60 --duration 120
   ```
4. **Run sustained 2h / 8h / 24h / 72h soaks:**
   ```powershell
   python scripts/progressive_load_test.py --tiers 60 --soak integration   # 2h
   python scripts/progressive_load_test.py --tiers 60 --soak operational   # 8h
   python scripts/progressive_load_test.py --tiers 60 --soak day           # 24h
   python scripts/progressive_load_test.py --tiers 60 --soak stability     # 72h
   ```
