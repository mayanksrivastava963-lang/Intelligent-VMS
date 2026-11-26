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
  id: string;
  video_id: string | null;
  name: string;
  location: string;
  source_type: "virtual" | "rtsp";
  status: "running" | "stopped";
  ai_enabled: boolean;
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

export function uploadVideo(
  file: File,
  progress: (percent: number) => void,
  finished: (recording: Recording | null, error: string | null) => void,
) {
  const request = new XMLHttpRequest();
  request.open("POST", "/api/videos");
  request.setRequestHeader("X-VMS-Request", "1");
  request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
  request.setRequestHeader("Content-Type", "application/octet-stream");
  request.upload.onprogress = (event) => {
    if (event.lengthComputable)
      progress(Math.round((100 * event.loaded) / event.total));
  };
  request.onload = () => {
    let body;
    try {
      body = JSON.parse(request.responseText);
    } catch {
      body = null;
    }
    if (request.status === 202 && body) finished(body, null);
    else {
      if (request.status === 401)
        window.dispatchEvent(new Event("session-expired"));
      finished(
        null,
        typeof body?.detail === "string"
          ? body.detail
          : `Upload failed (${request.status})`,
      );
    }
  };
  request.onerror = () =>
    finished(
      null,
      "Connection lost. Check the library before uploading again.",
    );
  request.onabort = () => finished(null, "Upload cancelled.");
  request.send(file);
  return request;
}
