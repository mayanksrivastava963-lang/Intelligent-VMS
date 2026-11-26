# AI detection module

The current implementation validates local images and recorded videos using
SSDLite320 MobileNetV3 Large. It is not a recording service or a live-camera
service. Backend and recording infrastructure remain independent.

Run these commands from the repository root in PowerShell:

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m pytest services/ai_engine/tests -q
.\services\ai_engine\.venv\Scripts\python.exe -m services.ai_engine.main image "C:\authorized\sample.jpg" --device cuda --headless
.\services\ai_engine\.venv\Scripts\python.exe -m services.ai_engine.main video "C:\authorized\sample.mp4" --device cuda --headless --sample-every 3 --max-frames 100
.\services\ai_engine\.venv\Scripts\python.exe -m services.ai_engine.benchmark --iterations 50
```

Running [main.py](main.py) without arguments preserves the interactive menu.
Without `--headless`, an OpenCV window displays annotated frames. Press `q`
to stop video processing; press any key to close the image window. Video
processing runs as fast as possible, not at the source playback frame rate.
CLI exit codes are 0 for success, 1 for processing failure, 2 for argument
parsing failure and 130 for operator interruption.

[ObjectDetector](detection/detector.py) holds the model, device, threshold and
category configuration. Construct one instance per inference worker and reuse
it across frames. Calls on a shared instance are serialized to bound concurrent
GPU inference. Multiple instances allocate multiple models. The legacy
`detect_objects(frame)` function lazily creates a shared default instance.
Importing the module does not download or initialize model weights.

Inputs must be nonempty uint8 NumPy BGR arrays with three channels. Detections
contain COCO class IDs, category names, confidence and floating-point XYXY
coordinates clipped to image bounds. Zero-area and non-finite results are
discarded. `draw_detections` modifies its input image in place.

First initialization may download official pretrained weights into the PyTorch
cache. Provision and verify this cache before offline deployment. `--device
cuda` fails if CUDA is unavailable; `auto` selects CUDA when available, otherwise
CPU. The default confidence is 0.5, configurable with `--confidence`.

The runner prints detection metadata for images and aggregate timings for
videos. It does not save footage or snapshots, contact the backend, or accept
RTSP URLs. Error logs omit raw exception messages to avoid exposing source
paths or credentials. Programmatic functions propagate exceptions for callers.

Benchmark timings include preprocessing, device transfer, inference and output
conversion, after warmup. CUDA synchronization ensures pending work completes
before timing stops. CUDA event spans include host scheduling gaps and must not
be interpreted as pure kernel time or GPU utilization percentage. Peak memory
reports PyTorch allocator usage, not total GPU memory. Synthetic random input
is repeatable but does not establish CCTV accuracy or multi-camera capacity.

Known limits:

- No real CCTV accuracy, long-duration reliability or GUI validation yet.
- OpenCV read failure after some frames cannot reliably distinguish EOF from
  corrupt/truncated input; no reconnect or retry is attempted for local files.
- Video timestamps come from the decoder and may be unreliable for some files.
  They are not yet used for temporal analytics.
- Frame sampling reduces inference work but still decodes skipped frames.
- Model initialization/inference failures propagate; no automatic GPU OOM retry.
- Zones, rules, event transport and live streams are subsequent modules.
- Production model selection, commercial license review and representative
  accuracy evaluation remain outstanding.

## Multi-object tracking

Enable tracking for local video:

```powershell
.\services\ai_engine\.venv\Scripts\python.exe -m services.ai_engine.main video "C:\authorized\sample.mp4" --track --camera-id entrance --headless --max-missing-seconds 2
```

[tracker.py](tracking/tracker.py) uses functions and dictionaries. Call
`create_tracker(camera_id)` once per camera, then call
`update_tracker(tracker, detections, timestamp)` sequentially for that camera.
Different cameras must have different tracker states. State is not thread-safe;
the camera worker owns it. `reset_tracker` clears temporal state on reconnect,
seek or a known stream interruption without recycling IDs within the session.

Data flow: decoded frame -> detector -> timestamp -> tracker -> display/summary.
Only observed tracks are drawn. Headless output includes the latest bounded
track snapshot and number of IDs created, not an unbounded per-frame event log.

Association uses class-compatible predicted-box IoU and SciPy's linear assignment
solver. Constant center velocity is measured in pixels/second from observations.
The assignment considers all candidates together instead of greedy nearest-box
selection. This is an independently implemented motion/IoU baseline, not an
implementation of SORT or ByteTrack. NumPy and SciPy are already dependencies;
tracking does not allocate a GPU model.

Approaches considered:

- [SORT](https://github.com/abewley/sort): Kalman motion prediction and assignment;
  useful benchmark for future evaluation.
- [ByteTrack](https://github.com/FoundationVision/ByteTrack): low-score detections
  help recover associations. Our current detector filters those detections, so
  adoption requires a separate tracking threshold and integration evaluation.
- The current bounded motion/IoU implementation provides an inspectable baseline
  with elapsed-time expiration. It is not the final production tracker selection.

Track fields include camera/session/track identity, class, confidence, last
observed box, first_seen, last_seen, velocity, hits, consecutive_hits, confirmed,
observed, status and bounded timestamped center history. Treat
`(camera_id, session_id, track_id)` as the identity. Numeric IDs alone are not
globally unique. Default confirmation requires three consecutive observations.
Unmatched tracks become `lost`; they are retained for at most two seconds since
last observation. Reassociation within that interval may preserve the ID.
Expired tracks are removed on the next update. Pass an empty list when a frame
has no detections. Default history is 100 points and capacity is 256 tracks and
256 detections per update; overflow raises before modifying state.

Use strictly increasing decoder seconds for recorded video and monotonic seconds
for a live session. Invalid/repeated/backward timestamps are rejected instead of
silently substituting processing time. No automatic FPS-based fallback is used,
because it can misrepresent variable-frame-rate footage. Wall-clock event time
will be added separately in the event module. `first_seen` is a track observation
time, not a zone-entry time. A retained lost track is not proof of continued
presence; history contains observations only. Rule modules must explicitly
handle gaps rather than interpreting last_seen minus first_seen as dwell time.

Limitations: no appearance re-identification, Kalman uncertainty model, camera
motion compensation or persistent state. Crowds, crossings, abrupt acceleration,
class changes, long occlusion and large sampling intervals can fragment IDs or
cause identity switches. Configure expiration relative to the sampling interval.
Run representative authorized CCTV sequences and measure ID switches/association
accuracy before enabling alerts. Synthetic tests verify logic and integration,
not real-world tracking accuracy.
