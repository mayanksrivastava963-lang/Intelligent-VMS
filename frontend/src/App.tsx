import { useEffect, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import type Hls from "hls.js";
import { api, uploadVideo } from "./api";
import CommandPalette, { buildCommandItems } from "./components/CommandPalette";
import Icon from "./components/Icon";
import LoginPage from "./components/LoginPage";
import SystemMonitor from "./components/SystemMonitor";
import type { AccessRole, AuditEvent, Camera, CameraAlert, DetectionResult, Recording, RecordingDetail, Segment, Session, UserAccount } from "./api";

type UserDialog = {
  mode: "create" | "edit" | "password";
  user: UserAccount | null;
};

function duration(seconds: number | null) {
  if (seconds === null) return "—";
  const value = Math.floor(seconds);
  return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

function size(bytes: number) {
  return bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark">◈</span>
      <div>
        INTELLIGENT<span>VIDEO MANAGEMENT SYSTEM</span>
      </div>
    </div>
  );
}

function greetingFor(date: Date) {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function CameraFeed({
  camera,
  index = 0,
  onControl,
  onRemove,
  onSnapshot,
  onToggleAI,
  canManage,
  sampleIntervalMs,
  alertCount,
  streamingMode,
}: {
  camera: Camera & { playback_revision?: number };
  index?: number;
  onControl: (action: "start" | "stop" | "restart") => void;
  onRemove: () => void;
  onSnapshot: (message: string) => void;
  onToggleAI: () => void;
  canManage: boolean;
  sampleIntervalMs: number;
  alertCount: number;
  streamingMode: "mediamtx" | "mjpeg";
}) {
  const [segmentIndex, setSegmentIndex] = useState(0);
  const [playbackCycle, setPlaybackCycle] = useState(0);
  const [loop, setLoop] = useState(true);
  const video = useRef<HTMLVideoElement>(null);
  const streamImage = useRef<HTMLImageElement>(null);
  const screen = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [streamError, setStreamError] = useState(false);
  const [streamRetry, setStreamRetry] = useState(0);
  const [playbackState, setPlaybackState] = useState<"loading" | "playing" | "paused">("loading");
  const [aiResult, setAiResult] = useState<DetectionResult | null>(null);
  const [aiError, setAiError] = useState("");
  const currentSegment = camera.segments[segmentIndex];
  const feedState = camera.status === "stopped" ? "stopped"
    : camera.source_type === "rtsp" ? (streamError ? "error" : camera.connection_status ?? "connecting")
    : playbackState;

  useEffect(() => {
    setStreamError(false);
    setPlaybackState("loading");
    setAiResult(null);
  }, [camera.id, camera.status, camera.playback_revision]);

  useEffect(() => {
    if (camera.source_type !== "rtsp" || streamingMode !== "mediamtx" || camera.status !== "running" || !video.current) return;
    const player = video.current;
    const streamName = camera.has_substream && !expanded ? `${camera.id}-preview` : camera.id;
    const source = `/live/${streamName}/index.m3u8`;
    let hls: Hls | null = null;
    let retryTimer: number | undefined;
    let cancelled = false;
    const retry = () => {
      if (retryTimer || cancelled) return;
      setStreamError(true);
      retryTimer = window.setTimeout(() => setStreamRetry((value) => value + 1), 3000);
    };
    if (player.canPlayType("application/vnd.apple.mpegurl")) {
      player.src = source;
      player.addEventListener("error", retry, { once: true });
    } else {
      void import("hls.js").then(({ default: HlsPlayer }) => {
        if (cancelled) return;
        if (!HlsPlayer.isSupported()) { retry(); return; }
        hls = new HlsPlayer({ enableWorker: true, lowLatencyMode: true, maxBufferLength: 4 });
        hls.loadSource(source);
        hls.attachMedia(player);
        hls.on(HlsPlayer.Events.ERROR, (_event, data) => {
          if (data.fatal) retry();
        });
        void player.play().catch(() => {});
      }).catch(() => {
        if (!cancelled) retry();
      });
    }
    if (player.src) void player.play().catch(() => {});
    return () => {
      cancelled = true;
      window.clearTimeout(retryTimer);
      player.removeEventListener("error", retry);
      hls?.destroy();
      player.removeAttribute("src");
      player.load();
    };
  }, [camera.id, camera.source_type, camera.status, camera.has_substream, camera.playback_revision, streamRetry, expanded, streamingMode]);

  useEffect(() => {
    const onFullscreen = () => setExpanded(document.fullscreenElement === screen.current);
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => document.removeEventListener("fullscreenchange", onFullscreen);
  }, []);

  useEffect(() => {
    setAiResult(null);
    setAiError("");
    if (!camera.ai_enabled || camera.status !== "running") return;
    let cancelled = false;
    let busy = false;
    let clearResult: number | undefined;

    async function sampleFrame() {
      if (busy || cancelled) return;
      if (camera.source_type === "rtsp" && camera.connection_status !== "online") return;
      if (camera.source_type === "rtsp" && streamingMode === "mediamtx") {
        busy = true;
        try {
          const result = await api<DetectionResult>(`/cameras/${camera.id}/ai/detections`);
          if (!cancelled && result.processed_at > 0 && Date.now() / 1000 - result.processed_at < 10) {
            setAiResult(result);
            setAiError("");
          }
        } catch {
          if (!cancelled) setAiError("AI unavailable");
        } finally {
          busy = false;
        }
        return;
      }
      if (camera.source_type === "virtual" && video.current?.paused) return;
      const source = camera.source_type === "rtsp" ? streamImage.current : video.current;
      const width = source instanceof HTMLVideoElement ? source.videoWidth : source?.naturalWidth ?? 0;
      const height = source instanceof HTMLVideoElement ? source.videoHeight : source?.naturalHeight ?? 0;
      if (!source || !width || !height) return;
      busy = true;
      const capturedAt = Date.now();
      const videoTime = video.current?.currentTime ?? 0;
      try {
        const canvas = document.createElement("canvas");
        canvas.width = Math.min(width, 640);
        canvas.height = Math.round((canvas.width * height) / width);
        canvas.getContext("2d")?.drawImage(source, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.78));
        if (!blob || cancelled) return;
        const result = await api<DetectionResult>(`/cameras/${camera.id}/ai/detections`, {
          method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob,
        });
        if (cancelled || Date.now() - capturedAt > 1500) return;
        if (camera.source_type === "virtual" && Math.abs((video.current?.currentTime ?? 0) - videoTime) > 0.8) return;
        setAiResult(result);
        setAiError("");
        window.clearTimeout(clearResult);
        clearResult = window.setTimeout(() => setAiResult(null), 1100);
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : "AI unavailable";
        if (!cancelled && !message.includes("AI processor is busy") && !message.includes("Wait before"))
          setAiError("AI unavailable");
      } finally {
        busy = false;
      }
    }

    const initial = window.setTimeout(() => void sampleFrame(), 500);
    const timer = window.setInterval(() => void sampleFrame(), sampleIntervalMs);
    return () => {
      cancelled = true;
      window.clearTimeout(initial);
      window.clearTimeout(clearResult);
      window.clearInterval(timer);
    };
  }, [camera.ai_enabled, camera.connection_status, camera.id, camera.source_type, camera.status, camera.playback_revision, sampleIntervalMs, streamingMode]);

  function playNextSegment() {
    if (segmentIndex + 1 < camera.segments.length) {
      setSegmentIndex(segmentIndex + 1);
    } else if (loop) {
      setSegmentIndex(0);
      setPlaybackCycle((current) => current + 1);
    }
  }

  function captureSnapshot() {
    const el = video.current;
    if (!el || !el.videoWidth || !el.videoHeight) {
      onSnapshot("Wait for video frame to load before capturing snapshot.");
      return;
    }
    try {
      const canvas = document.createElement("canvas");
      canvas.width = el.videoWidth;
      canvas.height = el.videoHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(el, 0, 0, canvas.width, canvas.height);
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const safeName = camera.name.replace(/[^a-z0-9_-]+/gi, "-").toLowerCase();
      const link = document.createElement("a");
      link.download = `${safeName}-${stamp}.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
      onSnapshot(`Snapshot saved for ${camera.name}`);
    } catch {
      onSnapshot("Snapshot unavailable for this video stream.");
    }
  }

  return (
    <article
      className="camera-card"
      style={{ "--stagger": index } as CSSProperties}
    >
      <div className="camera-screen" ref={screen}>
        {camera.status === "running" && camera.source_type === "rtsp" && streamingMode === "mjpeg" ? (
          <><img ref={streamImage} className="rtsp-stream" src={`/api/cameras/${camera.id}/stream?revision=${camera.playback_revision ?? 0}`} alt={`${camera.name} live feed`} onLoad={() => setStreamError(false)} onError={() => setStreamError(true)} />{feedState !== "online" && <div className="rtsp-connecting">{feedState === "offline" ? "Camera offline · retrying" : "Connecting to camera…"}</div>}</>
        ) : camera.status === "running" && camera.source_type === "rtsp" ? (
          <><video ref={video} className="rtsp-stream" autoPlay muted playsInline onPlaying={() => setStreamError(false)} />{feedState !== "online" && <div className="rtsp-connecting">{feedState === "offline" ? "Camera offline · retrying" : feedState === "reconnecting" ? "Reconnecting to camera…" : feedState === "error" ? "Preview unavailable · retrying" : "Connecting to camera…"}</div>}</>
        ) : camera.status === "running" && currentSegment ? (
          <video
            ref={video}
            key={`${camera.id}-${camera.playback_revision ?? 0}-${segmentIndex}-${playbackCycle}`}
            src={currentSegment.playback_url}
            autoPlay
            muted
            controls
            playsInline
            onPlaying={() => setPlaybackState("playing")}
            onWaiting={() => setPlaybackState("loading")}
            onPause={() => setPlaybackState("paused")}
            onEnded={playNextSegment}
            onError={() => onControl("stop")}
          />
        ) : (
          <div className="camera-placeholder">
            <span className="camera-placeholder-icon">◉</span>
            <strong>{camera.status === "stopped" ? "Feed stopped" : "No playable video"}</strong>
            <small>{camera.filename}</small>
          </div>
        )}
        {camera.ai_enabled && aiResult && <svg className="detection-overlay" viewBox={`0 0 ${aiResult.width} ${aiResult.height}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${aiResult.detections.length} detected objects`}>
          {aiResult.detections.map((detection, detectionIndex) => {
            const [x1, y1, x2, y2] = detection.bbox;
            return <g key={detectionIndex}>
              <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} />
              <text x={x1} y={Math.max(16, y1 - 5)}>{detection.class_name} {Math.round(detection.confidence * 100)}%</text>
            </g>;
          })}
        </svg>}
        <span className={`camera-live ${feedState}`}>
          <i /> {feedState === "online" ? "LIVE" : feedState === "playing" ? "SIMULATED LIVE" : feedState.toUpperCase()}
        </span>
        {camera.status === "running" && (
          <>
            {camera.source_type === "virtual" && <button
              type="button"
              className="snapshot-button"
              title="Capture PNG snapshot"
              onClick={captureSnapshot}
            >
              Snapshot
            </button>}
            <button className="fullscreen-button" title="Fullscreen" onClick={() => void (camera.source_type === "rtsp" ? screen.current : video.current)?.requestFullscreen()}>
              ⛶
            </button>
            {camera.source_type === "rtsp" && streamingMode === "mediamtx" && <button className="webrtc-button" type="button" title="Open low-latency WebRTC view" onClick={() => window.open(`/live-webrtc/${camera.id}`, "_blank", "noopener,noreferrer")}>WebRTC ↗</button>}
          </>
        )}
        {camera.ai_enabled && <span className="ai-indicator">{aiError || `AI ON · ${aiResult?.detections.length ?? 0} objects`}</span>}
        {alertCount > 0 && <span className="camera-alert-indicator">{alertCount} alert{alertCount === 1 ? "" : "s"} to review</span>}
      </div>
      <div className="camera-card-info">
        <div>
          <strong>{camera.name}</strong>
          <small>{camera.location || "Location not set"} · {camera.source_type === "rtsp" ? "RTSP camera" : "Virtual camera"}</small>
        </div>
        <span className="camera-id">{camera.id.slice(0, 8).toUpperCase()}</span>
      </div>
      <div className="camera-card-actions">
        {canManage && (camera.status === "running" ? (
          <button className="secondary" onClick={() => onControl("stop")}>Stop</button>
        ) : (
          <button className="secondary" onClick={() => onControl("start")}>Start feed</button>
        ))}
        {canManage && <button className="text-button" onClick={() => onControl("restart")}>Restart</button>}
        {canManage && <button className="text-button" onClick={onToggleAI}>{camera.ai_enabled ? "Disable AI" : "Enable AI"}</button>}
        {camera.source_type === "virtual" && <label className="loop-toggle"><input type="checkbox" checked={loop} onChange={(event) => setLoop(event.target.checked)} /> Loop</label>}
        {canManage && <button className="remove-camera" onClick={onRemove} title="Remove camera" aria-label={`Remove ${camera.name}`}>×</button>}
      </div>
    </article>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState("");
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [alerts, setAlerts] = useState<CameraAlert[]>([]);
  const [activePage, setActivePage] = useState<"dashboard" | "system" | "cameras" | "recordings" | "users" | "roles" | "audit">("dashboard");
  const [clock, setClock] = useState(new Date());
  const [cameraSearch, setCameraSearch] = useState("");
  const [cameraFilter, setCameraFilter] = useState("all");
  const [cameraSourceFilter, setCameraSourceFilter] = useState("all");
  const [cameraLocationFilter, setCameraLocationFilter] = useState("all");
  const [gridColumns, setGridColumns] = useState("auto");
  const [cameraPage, setCameraPage] = useState(0);
  const [camerasPerPage, setCamerasPerPage] = useState<9 | 16>(9);
  const [cameraDialog, setCameraDialog] = useState(false);
  const [rtspDialog, setRtspDialog] = useState(false);
  const [addCameraDialog, setAddCameraDialog] = useState(false);
  const [rtspUrl, setRtspUrl] = useState("");
  const [rtspPreviewUrl, setRtspPreviewUrl] = useState("");
  const [cameraName, setCameraName] = useState("");
  const [cameraLocation, setCameraLocation] = useState("");
  const [cameraSaving, setCameraSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RecordingDetail | null>(null);
  const [segment, setSegment] = useState<Segment | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [uploadName, setUploadName] = useState("");
  const [dragging, setDragging] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [retrying, setRetrying] = useState(false);
  const [playerError, setPlayerError] = useState("");
  const [userAccounts, setUserAccounts] = useState<UserAccount[]>([]);
  const [accessRoles, setAccessRoles] = useState<AccessRole[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [userSearch, setUserSearch] = useState("");
  const [userDialog, setUserDialog] = useState<UserDialog | null>(null);
  const [userForm, setUserForm] = useState({ full_name: "", username: "", email: "", password: "", role_id: "viewer" });
  const [userSaving, setUserSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [commandOpen, setCommandOpen] = useState(false);
  const [toasts, setToasts] = useState<Array<{ id: number; text: string }>>([]);
  const [recordingFilter, setRecordingFilter] = useState<"all" | "ready" | "processing" | "failed">("all");
  const [auditFilter, setAuditFilter] = useState<"all" | "success" | "failure">("all");
  const [auditSearch, setAuditSearch] = useState("");
  const [playbackRate, setPlaybackRate] = useState<1 | 1.5 | 2>(1);
  const [autoAdvance, setAutoAdvance] = useState(true);
  const [batchBusy, setBatchBusy] = useState(false);
  const [virtualVideoId, setVirtualVideoId] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const detailVideo = useRef<HTMLVideoElement>(null);
  const uploadRequest = useRef<XMLHttpRequest | null>(null);
  const uploadQueue = useRef<File[]>([]);
  const uploadingRef = useRef(false);

  function pushToast(text: string) {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-3), { id, text }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 3800);
  }

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (detailVideo.current) {
      detailVideo.current.playbackRate = playbackRate;
    }
  }, [playbackRate, segment]);

  useEffect(() => {
    if (!detail || detail.status !== "ready" || !detail.segments.length) return;
    setSegment((current) => {
      if (current && detail.segments.some((item) => item.id === current.id)) {
        return current;
      }
      return detail.segments[0];
    });
  }, [detail]);

  useEffect(() => {
    setCameraPage(0);
  }, [cameraSearch, cameraFilter, cameraSourceFilter, cameraLocationFilter, camerasPerPage]);

  useEffect(() => {
    const expired = () => {
      setSession(null);
      setRecordings([]);
      setCameras([]);
      setDetail(null);
      setSegment(null);
    };
    window.addEventListener("session-expired", expired);
    api<Session>("/auth/session")
      .then(setSession)
      .catch(() => {})
      .finally(() => setChecking(false));
    return () => {
      window.removeEventListener("session-expired", expired);
    };
  }, []);

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    let timer: number;
    async function refresh() {
      try {
        const [items, cameraItems] = await Promise.all([
          api<Recording[]>(`/videos?limit=50&offset=${offset}`, { signal: controller.signal }),
          api<Camera[]>("/cameras", { signal: controller.signal }),
        ]);
        setRecordings(items);
        setCameras(cameraItems);
        if (selectedId) {
          const item = await api<RecordingDetail>(`/videos/${selectedId}`, {
            signal: controller.signal,
          });
          setDetail(item);
        }
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not refresh recordings",
          );
      } finally {
        if (!controller.signal.aborted)
          timer = window.setTimeout(refresh, 2500);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [session, selectedId, offset]);

  useEffect(() => {
    if (!session?.permissions.includes("alerts.read")) return;
    let cancelled = false;
    async function refreshAlerts() {
      try {
        const items = await api<CameraAlert[]>("/alerts?limit=50");
        if (!cancelled) setAlerts(items);
      } catch {
        if (!cancelled) setAlerts([]);
      }
    }
    void refreshAlerts();
    const timer = window.setInterval(() => void refreshAlerts(), 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [session]);

  async function acknowledgeAlert(alertId: string) {
    try {
      await api(`/alerts/${alertId}/acknowledge`, { method: "POST" });
      setAlerts((items) => items.filter((item) => item.id !== alertId));
    } catch {
      pushToast("Could not acknowledge alert");
    }
  }

  useEffect(() => {
    if (!session) return;
    const activeSession = session;
    let cancelled = false;
    async function loadAdminPage() {
      try {
        if (activePage === "users" && activeSession.permissions.includes("user.read")) {
          const [accounts, roles] = await Promise.all([
            api<UserAccount[]>("/users"),
            api<AccessRole[]>("/roles"),
          ]);
          if (!cancelled) {
            setUserAccounts(accounts);
            setAccessRoles(roles);
          }
        } else if (activePage === "roles" && activeSession.permissions.includes("role.read")) {
          setAccessRoles(await api<AccessRole[]>("/roles"));
        } else if (activePage === "audit" && activeSession.permissions.includes("audit.read")) {
          setAuditEvents(await api<AuditEvent[]>("/audit-logs?limit=200"));
        }
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load administration data");
      }
    }
    void loadAdminPage();
    return () => { cancelled = true; };
  }, [session, activePage]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setSigningIn(true);
    setError("");
    try {
      await api("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      setSession(await api<Session>("/auth/session"));
      setPassword("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed");
    } finally {
      setSigningIn(false);
    }
  }

  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      setSession(null);
      setDetail(null);
      setSegment(null);
      setSelectedId(null);
      setRecordings([]);
      setCameras([]);
      setUserAccounts([]);
      setAuditEvents([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-out failed");
    }
  }

  function openUserDialog(mode: UserDialog["mode"], user: UserAccount | null = null) {
    setUserForm({
      full_name: user?.full_name ?? "",
      username: user?.username ?? "",
      email: user?.email ?? "",
      password: "",
      role_id: user?.role_id ?? "viewer",
    });
    setUserDialog({ mode, user });
    setError("");
    setNotice("");
  }

  async function saveUser(event: FormEvent) {
    event.preventDefault();
    if (!userDialog) return;
    setUserSaving(true);
    setError("");
    try {
      if (userDialog.mode === "password" && userDialog.user) {
        await api(`/users/${userDialog.user.id}/password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: userForm.password }),
        });
      } else if (userDialog.mode === "edit" && userDialog.user) {
        const changes: { full_name: string; email: string; role_id?: string } = {
          full_name: userForm.full_name.trim(),
          email: userForm.email.trim(),
        };
        if (userDialog.user.id !== session?.id) changes.role_id = userForm.role_id;
        const updated = await api<UserAccount>(`/users/${userDialog.user.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(changes),
        });
        setUserAccounts((current) => current.map((user) => user.id === updated.id ? updated : user));
      } else {
        const created = await api<UserAccount>("/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(userForm),
        });
        setUserAccounts((current) => [created, ...current]);
      }
      setUserDialog(null);
      setUserForm({ full_name: "", username: "", email: "", password: "", role_id: "viewer" });
      if (userDialog.mode === "password") setNotice("Password reset complete. The user's other sessions were signed out.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "User update failed");
    } finally {
      setUserSaving(false);
    }
  }

  async function toggleUserActive(user: UserAccount) {
    try {
      const updated = await api<UserAccount>(`/users/${user.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !user.is_active }),
      });
      setUserAccounts((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account status update failed");
    }
  }

  function upload(file: File | undefined) {
    if (!file || !session) return;
    if (!/\.(mp4|mov|mkv|avi|webm|m4v)$/i.test(file.name)) {
      setError("Choose an MP4, MOV, MKV, AVI, WEBM or M4V video.");
      return;
    }
    if (!file.size || file.size > session.max_upload_bytes) {
      setError(
        `Choose a nonempty video under ${size(session.max_upload_bytes)}.`,
      );
      return;
    }
    if (uploadingRef.current) {
      uploadQueue.current.push(file);
      return;
    }
    setError("");
    uploadingRef.current = true;
    setUploading(true);
    setUploadName(file.name);
    setUploadPercent(0);
    uploadRequest.current = uploadVideo(
      file,
      setUploadPercent,
      (recording, message) => {
        uploadingRef.current = false;
        setUploading(false);
        uploadRequest.current = null;
        if (message) setError(message);
        if (recording) {
          setOffset(0);
          setSelectedId(recording.id);
          setDetail(null);
          setSegment(null);
          setRecordings((current) => [
            recording,
            ...current.filter((item) => item.id !== recording.id),
          ]);
        }
        if (input.current) input.current.value = "";
        const nextFile = uploadQueue.current.shift();
        if (nextFile) window.setTimeout(() => upload(nextFile), 0);
      },
    );
  }

  function selectRecording(recording: Recording) {
    setSelectedId(recording.id);
    setDetail(null);
    setSegment(null);
    setPlayerError("");
  }

  async function createVirtualCamera() {
    const targetVideoId = virtualVideoId || detail?.id;
    if (!targetVideoId || !cameraName.trim()) return;
    setCameraSaving(true);
    setError("");
    try {
      const camera = await api<Camera>("/cameras", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_id: targetVideoId,
          name: cameraName.trim(),
          location: cameraLocation.trim(),
        }),
      });
      setCameras((current) => [...current, camera]);
      setCameraDialog(false);
      setVirtualVideoId("");
      setCameraName("");
      setCameraLocation("");
      setActivePage("cameras");
      pushToast(`Added camera "${camera.name}"`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Camera creation failed");
    } finally {
      setCameraSaving(false);
    }
  }

  async function createRtspCamera() {
    setCameraSaving(true);
    setError("");
    try {
      const camera = await api<Camera>("/cameras/rtsp", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: cameraName.trim(), location: cameraLocation.trim(), url: rtspUrl.trim(), preview_url: rtspPreviewUrl.trim() }),
      });
      setCameras((current) => [...current, camera]);
      setRtspDialog(false);
      setRtspUrl("");
      setRtspPreviewUrl("");
      setCameraName("");
      setCameraLocation("");
      pushToast("Camera added. Start the feed to connect.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add camera");
    } finally { setCameraSaving(false); }
  }

  async function controlCamera(cameraId: string, action: "start" | "stop" | "restart") {
    try {
      const camera = await api<Camera>(`/cameras/${cameraId}/${action}`, { method: "POST" });
      setCameras((current) => current.map((item) => item.id === cameraId
        ? { ...camera, playback_revision: action === "restart" ? Date.now() : item.playback_revision }
        : item));
      pushToast(
        action === "start"
          ? `${camera.name} feed started`
          : action === "stop"
            ? `${camera.name} feed stopped`
            : `${camera.name} feed restarted`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Camera control failed");
    }
  }

  async function toggleCameraAI(camera: Camera) {
    try {
      const response = await api<{ ai_enabled: boolean }>(`/cameras/${camera.id}/ai`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !camera.ai_enabled }),
      });
      setCameras((current) => current.map((item) =>
        item.id === camera.id ? { ...item, ai_enabled: response.ai_enabled } : item
      ));
      pushToast(`${camera.name}: AI ${response.ai_enabled ? "enabled" : "disabled"}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "AI setting failed");
    }
  }

  async function batchControlCameras(action: "start" | "stop") {
    const targets = cameras.filter((cam) =>
      action === "start" ? cam.status === "stopped" : cam.status === "running",
    );
    if (!targets.length) {
      pushToast(action === "start" ? "All camera feeds are already live." : "All camera feeds are already stopped.");
      return;
    }
    setBatchBusy(true);
    setError("");
    try {
      const updated = await Promise.all(
        targets.map((cam) => api<Camera>(`/cameras/${cam.id}/${action}`, { method: "POST" })),
      );
      const map = new Map(updated.map((cam) => [cam.id, cam]));
      setCameras((current) => current.map((item) => map.get(item.id) ?? item));
      pushToast(
        action === "start"
          ? `Started ${updated.length} camera feed${updated.length > 1 ? "s" : ""}`
          : `Stopped ${updated.length} camera feed${updated.length > 1 ? "s" : ""}`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Batch camera update failed");
    } finally {
      setBatchBusy(false);
    }
  }

  async function removeCamera(cameraId: string) {
    try {
      await api(`/cameras/${cameraId}`, { method: "DELETE" });
      setCameras((current) => current.filter((item) => item.id !== cameraId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Camera removal failed");
    }
  }

  async function retry() {
    if (!detail) return;
    setRetrying(true);
    setError("");
    try {
      setDetail(
        await api<RecordingDetail>(`/videos/${detail.id}/retry`, {
          method: "POST",
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  }

  if (checking)
    return (
      <div className="loading-screen">
        <div className="loading-pulse">
          <div className="loading-emblem" aria-hidden="true">◈</div>
          <span>Connecting to your VMS workspace…</span>
        </div>
      </div>
    );
  if (!session)
    return (
      <LoginPage
        username={username}
        password={password}
        showPassword={showPassword}
        signingIn={signingIn}
        error={error}
        onUsernameChange={setUsername}
        onPasswordChange={setPassword}
        onTogglePassword={() => setShowPassword(!showPassword)}
        onSubmit={login}
      />
    );

  const filtered = recordings.filter((item) => {
    const matchesSearch = item.filename.toLowerCase().includes(search.toLowerCase());
    if (!matchesSearch) return false;
    if (recordingFilter === "all") return true;
    if (recordingFilter === "processing") {
      return ["processing", "queued", "uploading"].includes(item.status);
    }
    return item.status === recordingFilter;
  });
  const processing = recordings.filter((item) =>
    ["processing", "queued", "uploading"].includes(item.status),
  ).length;
  const ready = recordings.filter((item) => item.status === "ready").length;
  const runningCamerasCount = cameras.filter((camera) => camera.status === "running").length;
  const cameraLocations = Array.from(new Set(cameras.map((camera) => camera.location).filter(Boolean))).sort();
  const totalBytes = recordings.reduce((total, item) => total + item.bytes, 0);
  const filteredUsers = userAccounts.filter((user) =>
    `${user.full_name} ${user.username} ${user.email}`.toLowerCase().includes(userSearch.toLowerCase()),
  );
  const filteredAudit = auditEvents.filter((event) => {
    const q = auditSearch.trim().toLowerCase();
    const matchesSearch = !q || `${event.action} ${event.actor_username ?? ""} ${event.remote_address ?? ""}`.toLowerCase().includes(q);
    if (!matchesSearch) return false;
    if (auditFilter === "all") return true;
    if (auditFilter === "success") return event.outcome.toLowerCase() === "success";
    return event.outcome.toLowerCase() !== "success";
  });
  const pageTitle = {
    dashboard: "Your surveillance workspace",
    system: "System health",
    cameras: "Live camera monitor",
    recordings: "Recording playback",
    users: "User management",
    roles: "Roles & permissions",
    audit: "Security audit log",
  }[activePage];
  const readyRecordings = recordings.filter((item) => item.status === "ready");
  const visibleCameras = cameras.filter((camera) =>
    `${camera.name} ${camera.location} ${camera.id}`.toLowerCase().includes(cameraSearch.toLowerCase()) &&
    (cameraFilter === "all" || camera.status === cameraFilter) &&
    (cameraSourceFilter === "all" || camera.source_type === cameraSourceFilter) &&
    (cameraLocationFilter === "all" || camera.location === cameraLocationFilter),
  );
  const totalCameraPages = Math.max(1, Math.ceil(visibleCameras.length / camerasPerPage));
  const safeCameraPage = Math.min(cameraPage, totalCameraPages - 1);
  const pagedCameras = visibleCameras.slice(safeCameraPage * camerasPerPage, (safeCameraPage + 1) * camerasPerPage);
  const navigation = [
    { id: "dashboard" as const, label: "Overview", permission: "camera.read" },
    { id: "cameras" as const, label: "Live view", permission: "camera.read" },
    { id: "recordings" as const, label: "Playback library", permission: "recording.read" },
    { id: "system" as const, label: "System health", permission: "health.read" },
    { id: "users" as const, label: "Users", permission: "user.read" },
    { id: "roles" as const, label: "Roles & permissions", permission: "role.read" },
    { id: "audit" as const, label: "Audit logs", permission: "audit.read" },
  ];
  const permittedNavigation = navigation.filter((item) => session.permissions.includes(item.permission));
  const commandItems = buildCommandItems({
    pages: permittedNavigation,
    cameras,
    recordings,
    canUpload: session.permissions.includes("recording.manage") && !uploading,
    onNavigate: (pageId) => setActivePage(pageId as typeof activePage),
    onSelectCamera: (camera) => {
      setCameraSearch(camera.name);
      setCameraFilter("all");
      setActivePage("cameras");
    },
    onSelectRecording: (recording) => {
      setActivePage("recordings");
      selectRecording(recording);
    },
    onUpload: () => input.current?.click(),
    onLogout: () => void logout(),
  });

  return (
    <div className="workspace">
      <aside className="sidebar">
        <Brand />
        <div className="sidebar-label">WORKSPACE</div>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {navigation.filter((item) => session.permissions.includes(item.permission)).map((item) => <button key={item.id} aria-current={activePage === item.id ? "page" : undefined} className={activePage === item.id ? "nav-active" : "nav-link"} onClick={() => setActivePage(item.id)}><Icon name={item.id} />{item.label}{item.id === "cameras" && <small className="nav-count">{cameras.length}</small>}</button>)}
        </nav>
        <div className="sidebar-note">
          <Icon name="roles" /> Private workspace
          <p>Local footage. Controlled access.</p>
        </div>
        <div className="operator">
          <span className="avatar">{session.full_name.slice(0, 2).toUpperCase()}</span>
          <div>
            {session.full_name}<small>{session.role_name}</small>
          </div>
          <button
            onClick={logout}
            disabled={uploading}
            title="Sign out"
            aria-label="Sign out"
          >
            ↗
          </button>
        </div>
      </aside>
      <main className="main">
        <input ref={input} type="file" accept=".mp4,.mov,.mkv,.avi,.webm,.m4v" multiple hidden aria-label="Choose video" onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length) {
            setActivePage("recordings");
            files.forEach(upload);
          }
          event.target.value = "";
        }} />
        <header>
          <span>
            Intelligent VMS <span className="slash">/</span>{" "}
            <strong>{navigation.find((item) => item.id === activePage)?.label}</strong>
          </span>
          <div className="header-tools">
            <button
              type="button"
              className="command-trigger"
              onClick={() => setCommandOpen(true)}
              title="Open quick command palette (Ctrl+K)"
            >
              <span>Quick jump…</span>
              <kbd className="command-kbd">Ctrl K</kbd>
            </button>
            <time dateTime={clock.toISOString()}>{clock.toLocaleDateString(undefined, { day: "numeric", month: "short" })}<strong>{clock.toLocaleTimeString()}</strong></time>
            <span className="private-label"><i className="private-label-dot" aria-hidden="true" />Local workspace</span>
          </div>
        </header>
        <div className="page-stage" key={activePage}>
        <div className="page-heading">
          <div>
            <div className="eyebrow">{activePage === "dashboard" ? "HOME" : activePage === "system" ? "SYSTEM HEALTH" : activePage === "cameras" ? "LIVE MONITORING" : activePage === "recordings" ? "VIDEO LIBRARY" : "ADMINISTRATION"}</div>
            <h1>{pageTitle}</h1>
            <p>{activePage === "dashboard" ? `Welcome back, ${session.full_name}. Everything you need to watch cameras and manage videos.` : activePage === "system" ? "Live CPU, memory, and disk storage on your server." : activePage === "cameras" ? "Watch live cameras, capture snapshots, or add a new feed in seconds." : activePage === "recordings" ? `Upload videos and watch them as ${session.segment_seconds / 60}-minute clips.` : `Manage team access as ${session.role_name}.`}</p>
          </div>
          <div className="page-heading-actions">
            {activePage === "users" && session.permissions.includes("user.manage") && <button className="primary" onClick={() => openUserDialog("create")}>＋ Add user</button>}
            {activePage === "cameras" && session.permissions.includes("camera.manage") && <button className="primary" onClick={() => setAddCameraDialog(true)}>＋ Add camera</button>}
            {(activePage === "dashboard" || activePage === "cameras" || activePage === "recordings") && session.permissions.includes("recording.manage") && <button
              className={activePage === "cameras" ? "secondary" : "primary"}
              onClick={() => input.current?.click()}
              disabled={uploading}
            >
              ＋ Upload video
            </button>}
          </div>
        </div>
        {notice && (
          <div className="success-note dismiss" role="status">
            <span>{notice}</span>
            <button type="button" aria-label="Dismiss message" onClick={() => setNotice("")}>×</button>
          </div>
        )}
        {error && (
          <div className="error dismiss" role="alert">
            <span>{error}</span>
            <button
              aria-label="Dismiss notification"
              onClick={() => setError("")}
            >
              ×
            </button>
          </div>
        )}
        {activePage === "dashboard" && <>
          <section className="hero-boost-banner" aria-label="Workspace summary">
            <div className="hero-boost-copy">
              <div className="hero-boost-status">
                <i aria-hidden="true" />
                PRIVATE WORKSPACE · STATUS BELOW
              </div>
              <h2>
                {greetingFor(clock)}, {session.full_name}
              </h2>
              <p>
                {runningCamerasCount > 0
                  ? `${runningCamerasCount} camera feed${runningCamerasCount > 1 ? "s" : ""} requested to run and ${ready} recording${ready === 1 ? "" : "s"} ready for review.`
                  : ready > 0
                    ? `${ready} processed recording${ready === 1 ? "" : "s"} ready in your library. Launch a virtual camera feed anytime.`
                    : "Your intelligent surveillance center is online. Upload a video to start streaming and analyzing."}
              </p>
            </div>
            <div className="hero-boost-actions">
              {session.permissions.includes("camera.read") && (
                <button type="button" className="secondary" onClick={() => setActivePage("cameras")}>
                  Open camera wall ↗
                </button>
              )}
              {session.permissions.includes("health.read") && (
                <button type="button" className="secondary" onClick={() => setActivePage("system")}>
                  System telemetry
                </button>
              )}
            </div>
          </section>
          <div className="overview-summary">
            <button className="overview-tile blue" style={{ "--stagger": 0 } as CSSProperties} onClick={() => setActivePage("cameras")}><Icon name="cameras" /><span>Total cameras</span><strong>{cameras.length.toString().padStart(2, "0")}</strong><small>View all cameras <b>↗</b></small></button>
            <button className="overview-tile mint" style={{ "--stagger": 1 } as CSSProperties} onClick={() => { setCameraFilter("running"); setActivePage("cameras"); }}><Icon name="dashboard" /><span>Live right now</span><strong>{cameras.filter((camera) => camera.status === "running").length.toString().padStart(2, "0")}</strong><small>Open live view <b>↗</b></small></button>
            <button className="overview-tile violet" style={{ "--stagger": 2 } as CSSProperties} onClick={() => setActivePage("recordings")}><Icon name="recordings" /><span>Saved videos</span><strong>{recordings.length.toString().padStart(2, "0")}</strong><small>{ready} ready to watch <b>↗</b></small></button>
            <button className="overview-tile amber" style={{ "--stagger": 3 } as CSSProperties} onClick={() => setActivePage("recordings")}><Icon name="system" /><span>Processing now</span><strong>{processing.toString().padStart(2, "0")}</strong><small>Preparing playback <b>↗</b></small></button>
          </div>
          {session.permissions.includes("health.read") && <SystemMonitor compact />}
          <div className="overview-bottom">
            <section className="panel recent-panel"><div className="section-title"><div><h2>Recording library</h2><p>Files on the current library page</p></div><button className="text-button" onClick={() => setActivePage("recordings")}>View library →</button></div>
              {recordings.slice(0, 4).map((recording) => <button className="recent-recording" key={recording.id} onClick={() => { setActivePage("recordings"); void selectRecording(recording); }}><span className="recent-icon"><Icon name="recordings" /></span><span><strong>{recording.filename}</strong><small>{size(recording.bytes)} · {new Date(recording.created_at * 1000).toLocaleDateString()}</small></span><span className={`status ${recording.status}`}>{recording.status}</span></button>)}
              {!recordings.length && <div className="empty"><Icon name="recordings" /><h3>Your footage belongs here</h3><p>Upload your first video to get started.</p></div>}
            </section>
            <section className="workflow-card"><span className="eyebrow">START MONITORING</span><h2>From video to virtual camera.</h2><p>Bring your recorded footage into a single monitoring workspace.</p><ol><li><b>01</b><span>Upload your videos<small>MP4, AVI, MOV and more</small></span></li><li><b>02</b><span>Wait for processing<small>Browser-compatible playback</small></span></li><li><b>03</b><span>Add a virtual camera<small>Name it and open Live view</small></span></li></ol><button className="secondary" onClick={() => setActivePage("recordings")}>Open playback library →</button></section>
          </div>
        </>}
        {activePage === "system" && session.permissions.includes("health.read") && <SystemMonitor />}
        {activePage === "cameras" && (
          <>
            <section className="stats camera-stats" aria-label="Camera statistics">
              <div><span>TOTAL CAMERAS</span><strong>{cameras.length.toString().padStart(2, "0")}</strong><small>Connected feeds</small></div>
              <div><span>LIVE NOW</span><strong>{cameras.filter((camera) => camera.status === "running").length.toString().padStart(2, "0")}</strong><small>Active feeds</small></div>
              <div><span>STOPPED</span><strong>{cameras.filter((camera) => camera.status === "stopped").length.toString().padStart(2, "0")}</strong><small>Ready to start</small></div>
              <div><span>RTSP ONLINE</span><strong>{cameras.filter((camera) => camera.source_type === "rtsp" && camera.connection_status === "online").length.toString().padStart(2, "0")}</strong><small>Streaming live</small></div>
            </section>
            {session.permissions.includes("alerts.read") && alerts.some((alert) => !alert.acknowledged_at) && <section className="camera-alert-list" aria-label="AI alerts"><strong>AI alerts for review</strong>{alerts.filter((alert) => !alert.acknowledged_at).slice(0, 5).map((alert) => <div key={alert.id}><span>{alert.message} · {new Date(alert.occurred_at * 1000).toLocaleTimeString()}</span>{session.permissions.includes("alerts.manage") && <button className="secondary" onClick={() => void acknowledgeAlert(alert.id)}>Acknowledge</button>}</div>)}</section>}
            <div className="camera-toolbar">
              <input type="search" placeholder="Search camera or location…" aria-label="Search cameras" value={cameraSearch} onChange={(event) => setCameraSearch(event.target.value)} />
              <select className="camera-filter-select" aria-label="Filter by camera source" value={cameraSourceFilter} onChange={(event) => setCameraSourceFilter(event.target.value)}>
                <option value="all">All types</option><option value="virtual">Uploaded video</option><option value="rtsp">RTSP camera</option>
              </select>
              {cameraLocations.length > 0 && (
                <select className="camera-filter-select" aria-label="Filter by location" value={cameraLocationFilter} onChange={(event) => setCameraLocationFilter(event.target.value)}>
                  <option value="all">All locations</option>{cameraLocations.map((location) => <option key={location} value={location}>{location}</option>)}
                </select>
              )}
              <div className="camera-toolbar-actions">
                <div className="pill-group" role="group" aria-label="Filter cameras by status">
                  {(["all", "running", "stopped"] as const).map((status) => (
                    <button
                      key={status}
                      type="button"
                      className={`pill-btn ${cameraFilter === status ? "active" : ""}`}
                      onClick={() => setCameraFilter(status)}
                    >
                      {status === "all" ? `All (${cameras.length})` : status === "running" ? `Live (${runningCamerasCount})` : `Stopped (${cameras.length - runningCamerasCount})`}
                    </button>
                  ))}
                </div>
                <div className="pill-group" role="group" aria-label="Grid layout columns">
                  {(["auto", "1", "2", "3", "4"] as const).map((cols) => (
                    <button
                      key={cols}
                      type="button"
                      className={`pill-btn ${gridColumns === cols ? "active" : ""}`}
                      onClick={() => setGridColumns(cols)}
                    >
                      {cols === "auto" ? "Auto" : `${cols}x`}
                    </button>
                  ))}
                </div>
                {cameras.length > 0 && session.permissions.includes("camera.manage") && (
                  <>
                    <button type="button" className="secondary" disabled={batchBusy} onClick={() => void batchControlCameras("start")}>Start all</button>
                    <button type="button" className="secondary" disabled={batchBusy} onClick={() => void batchControlCameras("stop")}>Stop all</button>
                  </>
                )}
              </div>
            </div>
            <section className={`camera-wall grid-${gridColumns}`} aria-label="Camera feeds">
              {pagedCameras.map((camera, index) => (
                <CameraFeed key={camera.id + (camera.playback_revision ?? "")} camera={camera} index={index} canManage={session.permissions.includes("camera.manage")} sampleIntervalMs={session.ai_sample_interval_ms} streamingMode={session.streaming_mode} alertCount={alerts.filter((alert) => alert.camera_id === camera.id && !alert.acknowledged_at).length} onControl={(action) => void controlCamera(camera.id, action)} onToggleAI={() => void toggleCameraAI(camera)} onSnapshot={pushToast} onRemove={() => { if (window.confirm(`Remove ${camera.name} from the dashboard?`)) void removeCamera(camera.id); }} />
              ))}
              {!cameras.length && <div className="camera-empty"><span>◉</span><h2>No cameras yet</h2><p>Add a live RTSP camera or turn an uploaded video into a camera in one click.</p>{session.permissions.includes("camera.manage") && <button className="primary" onClick={() => setAddCameraDialog(true)}>＋ Add your first camera</button>}</div>}
              {!!cameras.length && !visibleCameras.length && <div className="camera-empty"><h2>No matching cameras</h2><p>Try another name, location or filter.</p><button className="secondary" onClick={() => { setCameraSearch(""); setCameraFilter("all"); setCameraSourceFilter("all"); setCameraLocationFilter("all"); }}>Reset filters</button></div>}
            </section>
            {visibleCameras.length > 9 && (
              <div className="camera-pagination">
                <span>
                  Showing {safeCameraPage * camerasPerPage + 1}–{Math.min(visibleCameras.length, (safeCameraPage + 1) * camerasPerPage)} of {visibleCameras.length} cameras
                </span>
                <div>
                  <div className="pill-group" role="group" aria-label="Cameras per page">
                    {([9, 16] as const).map((limit) => (
                      <button
                        key={limit}
                        type="button"
                        className={`pill-btn ${camerasPerPage === limit ? "active" : ""}`}
                        onClick={() => setCamerasPerPage(limit)}
                      >
                        {limit}/page
                      </button>
                    ))}
                  </div>
                  {totalCameraPages > 1 && (
                    <>
                      <button type="button" className="text-button" disabled={safeCameraPage === 0} onClick={() => setCameraPage((p) => Math.max(0, p - 1))}>← Prev</button>
                      <span>Page {safeCameraPage + 1}/{totalCameraPages}</span>
                      <button type="button" className="text-button" disabled={safeCameraPage + 1 >= totalCameraPages} onClick={() => setCameraPage((p) => Math.min(totalCameraPages - 1, p + 1))}>Next →</button>
                    </>
                  )}
                </div>
              </div>
            )}
            <p className="camera-note">Tip: Use Auto grid or 9/page for smooth viewing. Click any camera’s fullscreen icon to inspect in detail.</p>
          </>
        )}
        {activePage === "recordings" && (
          <>
        <section className="stats" aria-label="Current page statistics">
          <div>
            <span>RECORDINGS ON THIS PAGE</span>
            <strong>{recordings.length.toString().padStart(2, "0")}</strong>
            <small>Uploaded sources</small>
          </div>
          <div>
            <span>READY TO REVIEW</span>
            <strong>
              {ready.toString().padStart(2, "0")}
              <i className="small-dot" />
            </strong>
            <small>Segmented and available</small>
          </div>
          <div>
            <span>IN PROGRESS</span>
            <strong>{processing.toString().padStart(2, "0")}</strong>
            <small>Uploading, queued or processing</small>
          </div>
          <div>
            <span>SOURCE STORAGE · THIS PAGE</span>
            <strong>{size(totalBytes)}</strong>
            <small>Original upload sizes</small>
          </div>
        </section>
        <section
          className={`upload-zone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            Array.from(event.dataTransfer.files).forEach(upload);
          }}
        >
          <div className="upload-icon">↑</div>
          <div className="upload-copy">
            <h2>
              {uploading ? uploadName : "Drop videos here to upload"}
            </h2>
            <p>
              {uploading
                ? uploadPercent === 100
                  ? "Upload finished. Preparing video for playback…"
                  : `Uploading… ${uploadPercent}%`
                : "Drag and drop a file here, or click Browse files. Videos are automatically split into playable clips."}
            </p>
            {uploading && (
              <progress
                value={uploadPercent}
                max={100}
                aria-label="Upload progress"
              />
            )}
          </div>
          <button
            className="secondary"
            onClick={() => {
              if (uploading) {
                uploadQueue.current = [];
                uploadRequest.current?.abort();
              } else {
                input.current?.click();
              }
            }}
          >
            {uploading ? "Cancel upload" : "Browse files"}
          </button>
          <div className="upload-caption">
            MP4, MOV, MKV, AVI, WEBM, M4V{" "}
            <span>Up to {size(session.max_upload_bytes)} per file</span>
          </div>
        </section>
        <div className="library-layout">
          <section className="library panel">
            <div className="panel-heading">
              <h2>
                Recording library{" "}
                <span className="count">{filtered.length}</span>
              </h2>
              <div className="recordings-tools">
                <div className="pill-group" role="group" aria-label="Filter recordings by status">
                  {(["all", "ready", "processing", "failed"] as const).map((status) => (
                    <button
                      key={status}
                      type="button"
                      className={`pill-btn ${recordingFilter === status ? "active" : ""}`}
                      onClick={() => setRecordingFilter(status)}
                    >
                      {status === "all" ? "All" : status[0].toUpperCase() + status.slice(1)}
                    </button>
                  ))}
                </div>
                <input
                  className="search"
                  type="search"
                  placeholder="Search this page…"
                  aria-label="Search recordings on current page"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>RECORDING</th>
                    <th>DURATION</th>
                    <th>STATUS</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((recording) => (
                    <tr
                      key={recording.id}
                      className={
                        selectedId === recording.id ? "selected-row" : ""
                      }
                    >
                      <td>
                        <button
                          className="recording-link"
                          onClick={() => selectRecording(recording)}
                        >
                          <span className="file-icon">▷</span>
                          <span>
                            <strong>{recording.filename}</strong>
                            <small>
                              {new Date(
                                recording.created_at * 1000,
                              ).toLocaleString()}{" "}
                              · {size(recording.bytes)}
                            </small>
                          </span>
                        </button>
                      </td>
                      <td className="mono">
                        {duration(recording.duration_seconds)}
                      </td>
                      <td>
                        <span className={`status ${recording.status}`}>
                          {recording.status === "processing"
                            ? `Processing ${Math.floor(recording.progress)}%`
                            : recording.status}
                        </span>
                      </td>
                      <td>
                        <button
                          className="open-button"
                          aria-label={`Open ${recording.filename}`}
                          onClick={() => selectRecording(recording)}
                        >
                          ↗
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!filtered.length && (
              <div className="empty">
                <span>▤</span>
                <h3>
                  {search
                    ? "No matching recordings"
                    : "Your library starts here"}
                </h3>
                <p>
                  {search
                    ? "Try a different filename."
                    : "Upload a video to create your first set of recordings."}
                </p>
              </div>
            )}
            <div className="table-footer">
              <span>
                Showing {offset + (recordings.length ? 1 : 0)}–
                {offset + recordings.length}
              </span>
              <div>
                <button
                  className="text-button"
                  disabled={!offset}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  ← Previous
                </button>
                <button
                  className="text-button"
                  disabled={recordings.length < 50}
                  onClick={() => setOffset(offset + 50)}
                >
                  Next →
                </button>
              </div>
            </div>
          </section>
          <aside className="detail panel">
            <div className="panel-heading">
              <h2>Recording details</h2>
              <span className="muted">◫</span>
            </div>
            {!selectedId ? (
              <div className="detail-empty">
                <div className="detail-art">▶</div>
                <h3>Select a video to watch</h3>
                <p>
                  Click any video on the left to play it immediately or turn it into a live camera.
                </p>
              </div>
            ) : !detail ? (
              <div className="empty">Loading recording…</div>
            ) : (
              <div className="detail-content">
                <h3 className="detail-title">{detail.filename}</h3>
                <div className="detail-metadata">
                  <span>{duration(detail.duration_seconds)}</span>
                  <span>{size(detail.bytes)}</span>
                  <span className={`status ${detail.status}`}>
                    {detail.status}
                  </span>
                </div>
                {detail.status === "failed" && (
                  <div className="error">
                    <p>{detail.error}</p>
                    <button
                      className="secondary"
                      onClick={retry}
                      disabled={retrying}
                    >
                      {retrying ? "Retrying…" : "Retry processing"}
                    </button>
                  </div>
                )}
                {["queued", "processing", "uploading"].includes(
                  detail.status,
                ) && (
                  <div className="processing-card">
                    <span className="small-dot" />
                    <strong>
                      {detail.status === "queued"
                        ? "Waiting for recording worker"
                        : detail.status === "uploading"
                          ? "Receiving upload"
                          : "Creating your segments"}
                    </strong>
                    <progress value={detail.progress} max={100} />
                    <p>
                      You can leave this page after the upload finishes.
                      Processing runs independently.
                    </p>
                  </div>
                )}
                {segment && (
                  <div className="player">
                    <video
                      ref={detailVideo}
                      key={segment.id}
                      controls
                      preload="metadata"
                      src={segment.playback_url}
                      onLoadedMetadata={() => {
                        if (detailVideo.current) detailVideo.current.playbackRate = playbackRate;
                      }}
                      onEnded={() => {
                        if (!autoAdvance || !detail) return;
                        const currentIndex = detail.segments.findIndex((item) => item.id === segment.id);
                        if (currentIndex >= 0 && currentIndex + 1 < detail.segments.length) {
                          setSegment(detail.segments[currentIndex + 1]);
                          setPlayerError("");
                        }
                      }}
                      onError={() =>
                        setPlayerError(
                          "Playback unavailable. Refresh your session or try another segment.",
                        )
                      }
                    />
                    <div className="player-toolbar">
                      <span>
                        Segment {String(segment.number).padStart(2, "0")} ·{" "}
                        {duration(segment.start_seconds)}–
                        {duration(segment.end_seconds)}
                      </span>
                      <div className="player-controls">
                        <div className="player-speed" role="group" aria-label="Playback speed">
                          {([1, 1.5, 2] as const).map((rate) => (
                            <button
                              key={rate}
                              type="button"
                              className={playbackRate === rate ? "active" : ""}
                              onClick={() => setPlaybackRate(rate)}
                            >
                              {rate}x
                            </button>
                          ))}
                        </div>
                        <label className="loop-toggle">
                          <input
                            type="checkbox"
                            checked={autoAdvance}
                            onChange={(event) => setAutoAdvance(event.target.checked)}
                          />
                          Auto-next
                        </label>
                      </div>
                    </div>
                    {playerError && (
                      <p className="error" role="alert">
                        {playerError}
                      </p>
                    )}
                  </div>
                )}
                {detail.status === "ready" && (
                  <>
                    <button className="primary add-camera-button" onClick={() => { setVirtualVideoId(detail.id); setCameraName(detail.filename.replace(/\.[^.]+$/, "")); setCameraLocation(""); setCameraDialog(true); }}>＋ Add to Live View</button>
                    <div className="segment-heading">
                      SEGMENTS <span>{detail.segments.length} files</span>
                    </div>
                    <div className="segment-list">
                      {detail.segments.map((item) => (
                        <button
                          className={`segment ${segment?.id === item.id ? "active" : ""}`}
                          key={item.id}
                          onClick={() => {
                            setSegment(item);
                            setPlayerError("");
                          }}
                        >
                          <span className="segment-play">▷</span>
                          <span>
                            <strong>
                              Segment {String(item.number).padStart(2, "0")}
                            </strong>
                            <small>
                              {duration(item.start_seconds)} –{" "}
                              {duration(item.end_seconds)}
                            </small>
                          </span>
                          <span className="segment-size">
                            {size(item.bytes)}
                          </span>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}
          </aside>
        </div>
        <footer>
          <span>Intelligent VMS</span>
          <span>Recordings are stored independently of AI analytics.</span>
        </footer>
          </>
        )}
        {activePage === "users" && (
          <section className="admin-panel panel">
            <div className="panel-heading">
              <h2>System accounts <span className="count">{userAccounts.length}</span></h2>
              <input className="search" type="search" placeholder="Search users" aria-label="Search users" value={userSearch} onChange={(event) => setUserSearch(event.target.value)} />
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>USER</th><th>ROLE</th><th>STATUS</th><th>LAST SIGN-IN</th><th>ACTIONS</th></tr></thead>
                <tbody>
                  {filteredUsers.map((user) => (
                    <tr key={user.id}>
                      <td><strong>{user.full_name}</strong><small className="user-subline">{user.username} · {user.email}</small></td>
                      <td>{user.role_name}</td>
                      <td><span className={`status ${user.is_active ? "ready" : "failed"}`}>{user.is_active ? "Active" : "Disabled"}</span></td>
                      <td>{user.last_login_at ? new Date(user.last_login_at * 1000).toLocaleString() : "Never"}</td>
                      <td><div className="user-actions">
                        <button className="text-button" onClick={() => openUserDialog("edit", user)}>Edit</button>
                        <button className="text-button" onClick={() => openUserDialog("password", user)}>Reset password</button>
                        {user.id !== session.id && <button className="text-button" onClick={() => void toggleUserActive(user)}>{user.is_active ? "Deactivate" : "Activate"}</button>}
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!filteredUsers.length && <div className="empty"><h3>No users found</h3><p>Create an account or adjust your search.</p></div>}
            </div>
            <p className="admin-footnote">Passwords are Argon2id hashed. Deactivating an account immediately expires its active sessions.</p>
          </section>
        )}
        {activePage === "roles" && (
          <section className="role-grid">
            {accessRoles.map((role) => (
              <article className="panel role-card" key={role.id}>
                <div className="eyebrow">ROLE</div><h2>{role.display_name}</h2><p>{role.permissions.length} permissions</p>
                <ul>{role.permissions.map((permission) => <li key={permission}>{permission.replaceAll(".", " · ")}</li>)}</ul>
              </article>
            ))}
          </section>
        )}
        {activePage === "audit" && (
          <section className="admin-panel panel">
            <div className="panel-heading">
              <h2>Recent security events <span className="count">{filteredAudit.length}</span></h2>
              <div className="recordings-tools">
                <div className="pill-group" role="group" aria-label="Filter audit outcome">
                  {(["all", "success", "failure"] as const).map((outcome) => (
                    <button
                      key={outcome}
                      type="button"
                      className={`pill-btn ${auditFilter === outcome ? "active" : ""}`}
                      onClick={() => setAuditFilter(outcome)}
                    >
                      {outcome === "all" ? "All" : outcome === "success" ? "Success" : "Failed"}
                    </button>
                  ))}
                </div>
                <input
                  className="search"
                  type="search"
                  placeholder="Filter events or user…"
                  aria-label="Filter audit events"
                  value={auditSearch}
                  onChange={(event) => setAuditSearch(event.target.value)}
                />
              </div>
            </div>
            <div className="table-wrap"><table><thead><tr><th>TIME</th><th>EVENT</th><th>USER</th><th>OUTCOME</th><th>CLIENT</th></tr></thead>
              <tbody>{filteredAudit.map((event) => <tr key={event.id}><td>{new Date(event.created_at * 1000).toLocaleString()}</td><td>{event.action.replaceAll("_", " ")}</td><td>{event.actor_username || "System / unknown"}</td><td><span className={`outcome-pill ${event.outcome.toLowerCase()}`}>{event.outcome}</span></td><td className="mono">{event.remote_address || "—"}</td></tr>)}</tbody>
            </table>{!filteredAudit.length && <div className="empty"><h3>No matching audit events</h3><p>Successful and failed sign-ins matching your filter will appear here.</p></div>}</div>
          </section>
        )}
        </div>
        {userDialog && (
          <div className="dialog-backdrop" role="presentation" onClick={() => setUserDialog(null)}>
            <form className="camera-dialog user-dialog" onSubmit={(event) => void saveUser(event)} onClick={(event) => event.stopPropagation()}>
              <div className="dialog-header-row">
                <div className="eyebrow">ACCOUNT SECURITY</div>
                <button type="button" className="dialog-close" aria-label="Close dialog" onClick={() => setUserDialog(null)}>×</button>
              </div>
              <h2>{userDialog.mode === "create" ? "Create user" : userDialog.mode === "edit" ? "Edit user" : "Reset password"}</h2>
              {userDialog.mode !== "password" && <>
                <label htmlFor="user-full-name">Full name</label>
                <input id="user-full-name" value={userForm.full_name} onChange={(event) => setUserForm({ ...userForm, full_name: event.target.value })} required maxLength={120} />
                {userDialog.mode === "create" && <>
                  <label htmlFor="user-username">Username</label>
                  <input id="user-username" value={userForm.username} onChange={(event) => setUserForm({ ...userForm, username: event.target.value })} required minLength={3} maxLength={64} pattern="[A-Za-z0-9_.-]+" autoComplete="off" />
                </>}
                <label htmlFor="user-email">Email</label>
                <input id="user-email" type="email" value={userForm.email} onChange={(event) => setUserForm({ ...userForm, email: event.target.value })} required maxLength={254} />
                {userDialog.mode === "create" && <>
                  <label htmlFor="user-password">Temporary password (12+ characters)</label>
                  <input id="user-password" type="password" value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} required minLength={12} maxLength={256} autoComplete="new-password" />
                </>}
                <label htmlFor="user-role">Role</label>
                <select id="user-role" value={userForm.role_id} disabled={userDialog.mode === "edit" && userDialog.user?.id === session.id} onChange={(event) => setUserForm({ ...userForm, role_id: event.target.value })}>
                  {accessRoles.filter((role) => session.role === "super_administrator" || role.id !== "super_administrator").map((role) => <option key={role.id} value={role.id}>{role.display_name}</option>)}
                </select>
              </>}
              {userDialog.mode === "password" && <>
                <p>Set a new password for {userDialog.user?.username}. Their other sessions will be signed out.</p>
                <label htmlFor="reset-password">New password (12+ characters)</label>
                <input id="reset-password" type="password" value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} required minLength={12} maxLength={256} autoComplete="new-password" />
              </>}
              <div className="dialog-actions"><button type="button" className="secondary" onClick={() => setUserDialog(null)}>Cancel</button><button className="primary" disabled={userSaving}>{userSaving ? "Saving…" : "Save changes"}</button></div>
            </form>
          </div>
        )}
        {addCameraDialog && <div className="dialog-backdrop" role="presentation" onClick={() => setAddCameraDialog(false)}>
          <section className="camera-dialog add-camera-choice" role="dialog" aria-modal="true" aria-labelledby="add-camera-title" onClick={(event) => event.stopPropagation()}>
            <div className="dialog-header-row"><div className="eyebrow">ADD CAMERA</div><button type="button" className="dialog-close" aria-label="Close dialog" onClick={() => setAddCameraDialog(false)}>×</button></div>
            <h2 id="add-camera-title">Choose camera source</h2><p>Pick a live network camera or use one of your uploaded videos.</p>
            <button type="button" className="camera-source-choice" onClick={() => { setAddCameraDialog(false); setError(""); setCameraName(""); setCameraLocation(""); setRtspUrl(""); setRtspPreviewUrl(""); setRtspDialog(true); }}><Icon name="cameras" /><span><strong>Live RTSP / IP camera</strong><small>Paste the camera’s rtsp:// stream URL</small></span><b>→</b></button>
            {session.permissions.includes("recording.read") && (
              <button
                type="button"
                className="camera-source-choice"
                onClick={() => {
                  setAddCameraDialog(false);
                  if (readyRecordings.length > 0) {
                    const first = readyRecordings[0];
                    setVirtualVideoId(first.id);
                    setCameraName(first.filename.replace(/\.[^.]+$/, ""));
                    setCameraLocation("");
                    setCameraDialog(true);
                  } else {
                    setActivePage("recordings");
                    pushToast("Upload a video first to turn it into a camera.");
                  }
                }}
              >
                <Icon name="recordings" />
                <span>
                  <strong>Uploaded video{readyRecordings.length ? ` (${readyRecordings.length} ready)` : ""}</strong>
                  <small>{readyRecordings.length ? "Pick a ready video right here" : "Go to Video Library to upload a video first"}</small>
                </span>
                <b>→</b>
              </button>
            )}
          </section>
        </div>}
        {rtspDialog && <div className="dialog-backdrop" role="presentation" onClick={() => { setRtspDialog(false); setRtspUrl(""); setRtspPreviewUrl(""); }}>
          <form className="camera-dialog" onSubmit={(event) => { event.preventDefault(); void createRtspCamera(); }} onClick={(event) => event.stopPropagation()}>
            <div className="dialog-header-row">
              <div className="eyebrow">LIVE IP CAMERA</div>
              <button type="button" className="dialog-close" aria-label="Close dialog" onClick={() => { setRtspDialog(false); setRtspUrl(""); setRtspPreviewUrl(""); }}>×</button>
            </div>
            <h2>Add RTSP camera</h2>
            <p>Give your camera a name and paste its RTSP stream address.</p>
            {error && <div className="error" role="alert">{error}</div>}
            <label htmlFor="rtsp-name">Camera name</label><input id="rtsp-name" value={cameraName} onChange={(event) => setCameraName(event.target.value)} placeholder="e.g. Main Gate" required maxLength={120} autoFocus />
            <label htmlFor="rtsp-location">Location (optional)</label><input id="rtsp-location" value={cameraLocation} onChange={(event) => setCameraLocation(event.target.value)} placeholder="e.g. Ground Floor" maxLength={200} />
            <label htmlFor="rtsp-url">Main RTSP URL</label><input id="rtsp-url" type="password" value={rtspUrl} onChange={(event) => setRtspUrl(event.target.value)} placeholder="rtsp://user:password@camera-ip:554/stream" required maxLength={2000} autoComplete="off" />
            <label htmlFor="rtsp-preview-url">Low-bandwidth substream (optional)</label><input id="rtsp-preview-url" type="password" value={rtspPreviewUrl} onChange={(event) => setRtspPreviewUrl(event.target.value)} placeholder="rtsp://camera-ip:554/substream" maxLength={2000} autoComplete="off" />
            <div className="dialog-actions"><button type="button" className="secondary" onClick={() => { setRtspDialog(false); setRtspUrl(""); setRtspPreviewUrl(""); }}>Cancel</button><button className="primary" disabled={cameraSaving}>{cameraSaving ? "Adding…" : "Add camera"}</button></div>
          </form>
        </div>}
        {cameraDialog && (virtualVideoId || detail) && (
          <div className="dialog-backdrop" role="presentation" onClick={() => { setCameraDialog(false); setVirtualVideoId(""); }}>
            <form className="camera-dialog" onSubmit={(event) => { event.preventDefault(); void createVirtualCamera(); }} onClick={(event) => event.stopPropagation()}>
              <div className="dialog-header-row">
                <div className="eyebrow">VIRTUAL CAMERA</div>
                <button type="button" className="dialog-close" aria-label="Close dialog" onClick={() => { setCameraDialog(false); setVirtualVideoId(""); }}>×</button>
              </div>
              <h2>Camera details</h2>
              {readyRecordings.length > 0 ? (
                <>
                  <label htmlFor="virtual-video-select">Source video</label>
                  <select
                    id="virtual-video-select"
                    className="camera-filter-select"
                    value={virtualVideoId || detail?.id || ""}
                    onChange={(event) => {
                      const nextId = event.target.value;
                      setVirtualVideoId(nextId);
                      const picked = readyRecordings.find((r) => r.id === nextId);
                      if (picked && !cameraName.trim()) {
                        setCameraName(picked.filename.replace(/\.[^.]+$/, ""));
                      }
                    }}
                  >
                    {readyRecordings.map((item) => (
                      <option key={item.id} value={item.id}>{item.filename}</option>
                    ))}
                  </select>
                </>
              ) : (
                <p>Using video: <strong>{detail?.filename}</strong></p>
              )}
              <label htmlFor="camera-name">Camera name</label>
              <input id="camera-name" value={cameraName} onChange={(event) => setCameraName(event.target.value)} maxLength={120} required autoFocus />
              <label htmlFor="camera-location">Location (optional)</label>
              <input id="camera-location" value={cameraLocation} onChange={(event) => setCameraLocation(event.target.value)} maxLength={200} placeholder="e.g. Main entrance" />
              <div className="dialog-actions"><button type="button" className="secondary" onClick={() => { setCameraDialog(false); setVirtualVideoId(""); }}>Cancel</button><button className="primary" disabled={cameraSaving}>{cameraSaving ? "Adding…" : "Add camera"}</button></div>
            </form>
          </div>
        )}
        <CommandPalette
          open={commandOpen}
          onClose={() => setCommandOpen(false)}
          items={commandItems}
        />
        {toasts.length > 0 && (
          <div className="toast-stack" aria-live="polite">
            {toasts.map((toast) => (
              <div key={toast.id} className="toast-item" role="status">
                <span className="toast-dot" aria-hidden="true" />
                <span>{toast.text}</span>
                <button
                  type="button"
                  className="toast-close"
                  aria-label="Dismiss"
                  onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
