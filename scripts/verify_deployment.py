"""Read-only deployed checks. Credentials stay in memory and never enter output."""
import http.cookiejar
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "storage/deployment-validation"


def main():
    config = dotenv_values(DEST / "validation.env")
    base = "https://localhost:" + config["VMS_HTTPS_PORT"]
    context = ssl.create_default_context(cafile=str(DEST / "tls/fullchain.pem"))
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                       urllib.request.HTTPCookieProcessor(jar))
    def get(path, payload=None, headers=None):
        req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                     headers={"Content-Type": "application/json", "X-VMS-Request": "1", **(headers or {})})
        return opener.open(req, timeout=15)
    result = {}
    with get("/") as response:
        result["frontend"] = response.status == 200 and b"<html" in response.read()
    with get("/recordings") as response:
        result["spa_refresh"] = response.status == 200 and b"<html" in response.read()
    with get("/api/auth/login", {"username": config["VMS_OPERATOR_USERNAME"], "password": config["VMS_OPERATOR_PASSWORD"]}) as response:
        result["login"] = response.status == 200
    result["secure_cookie"] = bool(list(jar)) and all(cookie.secure for cookie in jar)
    with get("/api/videos?limit=100") as response:
        videos = json.load(response)
    result["retained_recordings"] = len(videos)
    result["range_playback"] = []
    for video in videos[:10]:
        with get("/api/videos/" + video["id"]) as response:
            details = json.load(response)
        for segment in details.get("segments", [])[:1]:
            path = "/api/segments/" + segment["id"] + "/content"
            with get(path, headers={"Range": "bytes=0-1023"}) as response:
                result["range_playback"].append(response.status == 206 and len(response.read()) == 1024)
            try:
                urllib.request.urlopen(base + path, context=context, timeout=5)
                result["unauthenticated_playback_denied"] = False
            except urllib.error.HTTPError as error:
                result["unauthenticated_playback_denied"] = error.code == 401
    original = dotenv_values(ROOT / ".env")
    env = os.environ.copy()
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT"):
        env[key] = original.get(key, "5432" if key.endswith("PORT") else "")
    code = "import os,psycopg; c=psycopg.connect(host='host.docker.internal',port=os.environ['POSTGRES_PORT'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'],dbname=os.environ['POSTGRES_DB'],connect_timeout=5,options='-c default_transaction_read_only=on'); assert c.execute('SELECT 1').fetchone()==(1,); c.close()"
    command = ["docker", "run", "--rm", "--memory", "128m"]
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT"):
        command += ["-e", key]
    probe = subprocess.run(command + ["intelligent-vms-api:0.1.0", "python", "-c", code],
                           env=env, capture_output=True, timeout=30)
    result["existing_host_postgresql_from_container_readonly"] = probe.returncode == 0
    # Never echo database exception text, which could include connection details.
    (DEST / "deployed-checks.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
