export type Recording = {
  id: string;
  filename: string;
  status: "uploading" | "queued" | "processing" | "ready" | "failed";
  bytes: number;
  created_at: number;
  duration_seconds: number | null;
  segment_seconds: number;
  progress: number;
  error: string | null;
  camera_id?: string | null;
  protected?: boolean;
};

export type Segment = {
  id: string;
  number: number;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  bytes: number;
  playback_url: string;
};

export type RecordingDetail = Recording & { segments: Segment[] };
export type Camera = {
  ai_available?: boolean;
  id: string;
  video_id: string | null;
  name: string;
  location: string;
  source_type: "virtual" | "rtsp";
  has_substream?: boolean;
  status: "running" | "stopped";
  ai_enabled: boolean;
  recording_status?: string;
  connection_status?: "connecting" | "online" | "reconnecting" | "offline" | "stopped";
  filename: string;
  duration_seconds: number | null;
  segments: Segment[];
  playback_revision?: number;
};
export type Detection = {
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: [number, number, number, number];
};
export type DetectionResult = {
  width: number;
  height: number;
  detections: Detection[];
  processed_at: number;
  inference_ms: number;
};
export type CameraAlert = {
  id: string;
  camera_id: string;
  rule: string;
  message: string;
  occurred_at: number;
  acknowledged_at: number | null;
};
export type Session = {
  authenticated: boolean;
  id: string;
  username: string;
  full_name: string;
  role: string;
  role_name: string;
  permissions: string[];
  segment_seconds: number;
  max_upload_bytes: number;
  ai_sample_interval_ms: number;
  streaming_mode: "mediamtx" | "mjpeg";
};

export type UserAccount = {
  id: string;
  full_name: string;
  username: string;
  email: string;
  role_id: string;
  role_name: string;
  is_active: boolean;
  created_at: number;
  updated_at: number;
  last_login_at: number | null;
};

export type AccessRole = {
  id: string;
  display_name: string;
  permissions: string[];
};

export type AuditEvent = {
  id: string;
  actor_user_id: string | null;
  actor_username: string | null;
  action: string;
  target_user_id: string | null;
  outcome: string;
  remote_address: string | null;
  created_at: number;
};

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    credentials: "same-origin",
    headers: { "X-VMS-Request": "1", ...options.headers },
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login") {
      window.dispatchEvent(new Event("session-expired"));
    }
    const body = await response.json().catch(() => null);
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json() as Promise<T>;
}
