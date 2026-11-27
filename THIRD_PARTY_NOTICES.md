# Third-Party Notices & Component Inventory — 0.1.0-rc3 (2026-11-27)

**Not legal redistribution clearance.** No prebuilt binaries, AI model weights, or customer secrets are included in the source release archive.

## Key Runtime Components

- **Python Backend (`backend/requirements.lock.txt`):** FastAPI, Starlette, Uvicorn, SQLAlchemy, Alembic, psycopg / psycopg-binary, PyAV (`av`), imageio-ffmpeg, Argon2 (`argon2-cffi`), cryptography, Pillow, psutil, itsdangerous, python-dotenv, redis (`redis-py`).
- **Frontend (`frontend/package-lock.json`):** React (`^19.3.1`), React DOM, `hls.js` (`hls.light.mjs`, Apache-2.0).
- **Streaming & Storage:**
  - MediaMTX `1.21.4` (MIT License)
  - PostgreSQL `18` (PostgreSQL License)
  - Nginx (`nginx:stable-alpine`, 2-clause BSD + Alpine packages)
  - **Cache / Rate-Limit Broker:** Redis `7-alpine` (RSALv2/SSPLv1) by default, OR **Valkey 8** (`compose.valkey.yml`, **BSD-3-Clause**) as an open-source drop-in replacement.
  - **FFmpeg (`5.1.9` Debian build):** Built with `--enable-gpl --enable-libx264 --enable-libx265`. Treated as GPLv2+/v3 when distributing container images; recording uses `-c:v copy` (stream copy).
- **Optional AI Engine (`--profile ai`):** PyTorch `2.11.0`, Torchvision `0.26.0`, OpenCV (`opencv-python-headless`), SciPy, NumPy, and Torchvision `SSDLite320_MobileNet_V3_Large` weights cached outside source bundles (`ai_model_cache`).

See [`COMMERCIAL_LICENSING.md`](docs/COMMERCIAL_LICENSING.md) and [`docs/release-evidence/`](docs/release-evidence/) for resolved package metadata and partial CycloneDX SBOM (`sbom.cdx.json`).
