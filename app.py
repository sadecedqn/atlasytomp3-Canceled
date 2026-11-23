import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

def get_ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return shutil.which("ffmpeg") or "ffmpeg"

FFMPEG_PATH = get_ffmpeg_path()
YTDLP_PATH = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
if not os.path.exists(YTDLP_PATH):
    YTDLP_PATH = shutil.which("yt-dlp") or "yt-dlp"
NODE_PATH = shutil.which("node") or shutil.which("nodejs") or ""
SECRET_COOKIE_PATH = "/etc/secrets/cookies.txt"

TR_MAP = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")

app = Flask(__name__)

def get_cookie_info():
    if os.path.exists(SECRET_COOKIE_PATH) and os.path.getsize(SECRET_COOKIE_PATH) > 0:
        with open(SECRET_COOKIE_PATH, "rb") as f:
            return f.read(), "secret_file"
    b64_val = os.environ.get("YT_COOKIES_B64", "").strip()
    if b64_val:
        try:
            return base64.b64decode(b64_val), "b64"
        except Exception:
            pass
    raw_val = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if raw_val:
        return raw_val.replace("\\n", "\n").encode("utf-8"), "env"
    return None, "none"

def write_temp_cookie(temp_dir):
    cookie_bytes, _ = get_cookie_info()
    if not cookie_bytes:
        return None
    cookie_path = os.path.join(temp_dir, "cookies.txt")
    with open(cookie_path, "wb") as f:
        f.write(cookie_bytes)
    return cookie_path

def build_base_args(cookie_path=None):
    args = ["--no-warnings", "--no-playlist"]
    if NODE_PATH:
        args += ["--js-runtimes", f"node:{NODE_PATH}"]
    if cookie_path:
        args += ["--cookies", cookie_path]
    return args

def clean_display_name(title):
    cleaned = "".join(c for c in title if c.isalnum() or c in " _-()[]").strip()
    return cleaned or "audio"

def to_ascii_filename(title):
    transliterated = title.translate(TR_MAP)
    ascii_only = "".join(c for c in transliterated if c.isascii() and (c.isalnum() or c in " _-()[]")).strip()
    return ascii_only or "audio"

def format_error_message(stderr_text):
    lines = [line.strip() for line in (stderr_text or "").splitlines() if line.strip()]
    error_lines = [line for line in lines if "ERROR:" in line]
    if error_lines:
        return error_lines[-1][:350]
    if lines:
        return lines[-1][:350]
    return "İndirme sırasında bilinmeyen bir hata oluştu."

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/version")
def version():
    r = subprocess.run([YTDLP_PATH, "--version"], capture_output=True, text=True)
    cookie_bytes, cookie_source = get_cookie_info()
    return jsonify({
        "yt_dlp": r.stdout.strip(),
        "node": NODE_PATH,
        "ffmpeg": FFMPEG_PATH,
        "cookie": cookie_bytes is not None,
        "cookie_source": cookie_source,
    })

@app.route("/info", methods=["POST"])
def info():
    url = request.form.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL gerekli"}), 400
    temp_dir = tempfile.mkdtemp()
    try:
        cookie_path = write_temp_cookie(temp_dir)
        cmd = [YTDLP_PATH] + build_base_args(cookie_path) + ["-J", url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            return jsonify({"error": format_error_message(r.stderr)}), 400
        data = json.loads(r.stdout)
        return jsonify({
            "title": data.get("title", ""),
            "duration": data.get("duration", 0),
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Video bilgisi alınırken zaman aşımı oluştu."}), 504
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.route("/download", methods=["POST"])
def download():
    url = request.form.get("url", "").strip()
    quality = request.form.get("quality", "192").strip()
    if quality not in {"128", "192", "256", "320"}:
        quality = "192"
    if not url:
        return "Lütfen geçerli bir link girin.", 400

    temp_dir = tempfile.mkdtemp()
    try:
        cookie_path = write_temp_cookie(temp_dir)
        source_template = os.path.join(temp_dir, "source.%(ext)s")
        yt_cmd = [
            YTDLP_PATH,
            "-f", "bestaudio/best",
            "--write-info-json",
            "--concurrent-fragments", "4",
            "-o", source_template,
        ] + build_base_args(cookie_path) + [url]

        yt_result = subprocess.run(yt_cmd, capture_output=True, text=True, timeout=180)
        if yt_result.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return format_error_message(yt_result.stderr), 400

        source_path = None
        info_path = None
        for fname in os.listdir(temp_dir):
            full_path = os.path.join(temp_dir, fname)
            if fname.endswith(".info.json"):
                info_path = full_path
            elif fname.startswith("source.") and not fname.endswith(".part"):
                source_path = full_path

        if not source_path:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return "Ses akışı indirilemedi.", 500

        track_title = "audio"
        artist = ""
        year = ""
        if info_path and os.path.exists(info_path):
            with open(info_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            track_title = meta.get("title") or "audio"
            artist = meta.get("uploader") or meta.get("channel") or ""
            upload_date = str(meta.get("upload_date") or "")
            year = upload_date[:4] if len(upload_date) >= 4 else ""

        output_path = os.path.join(temp_dir, "output.mp3")
        ff_cmd = [
            FFMPEG_PATH,
            "-y",
            "-i", source_path,
            "-vn",
            "-ar", "44100",
            "-ac", "2",
            "-b:a", f"{quality}k",
            "-metadata", f"title={track_title}",
            "-metadata", f"artist={artist}",
            "-metadata", f"date={year}",
            "-id3v2_version", "3",
            output_path,
        ]

        ff_result = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=180)
        if ff_result.returncode != 0 or not os.path.exists(output_path):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return "MP3 dönüşümü başarısız oldu.", 500

        utf8_name = clean_display_name(track_title)
        ascii_name = to_ascii_filename(utf8_name)
        encoded_utf8 = quote(f"{utf8_name}.mp3")

        def stream_file():
            try:
                with open(output_path, "rb") as audio_file:
                    while True:
                        chunk = audio_file.read(65536)
                        if not chunk:
                            break
                        yield chunk
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        return Response(
            stream_with_context(stream_file()),
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_name}.mp3"; filename*=UTF-8\'\'{encoded_utf8}',
                "X-Accel-Buffering": "no",
            },
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return "İşlem zaman aşımına uğradı. Daha kısa bir video deneyin.", 504
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return f"Sunucu hatası: {str(exc)}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)