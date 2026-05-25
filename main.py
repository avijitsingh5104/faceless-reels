"""
Faceless Reels Auto-Generator
Niche: Astronomical facts and stories
Pipeline: Claude API → Edge TTS → Pexels → FFmpeg → YouTube
"""

import os
import re
import json
import time
import random
import asyncio
import requests
import subprocess
from pathlib import Path
from datetime import datetime

import google.generativeai as genai
import edge_tts
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# ─── CONFIG ───────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_API_KEY    = os.environ["PEXELS_API_KEY"]
YOUTUBE_TOKEN     = os.environ["YOUTUBE_TOKEN"]         # OAuth2 JSON token string

NICHE             = "Astronomical facts and stories"
REEL_DURATION     = 45          # seconds
VOICE             = "en-US-GuyNeural"   # calm & deep male (Edge TTS)
MUSIC_VOLUME      = 0.12        # lo-fi chill kept quiet under voice
OUTPUT_DIR        = Path("output")
ASSETS_DIR        = Path("assets")
TOPICS_FILE       = Path("topics.txt")

OUTPUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

# ─── STEP 1 — PICK TODAY'S TOPIC ─────────────────────────────────────────────

def get_todays_topic() -> str:
    lines = [l.strip() for l in TOPICS_FILE.read_text().splitlines() if l.strip()]
    if not lines:
        raise ValueError("topics.txt is empty — add topics first.")
    # rotate based on day-of-year so each day is different
    idx = datetime.now().timetuple().tm_yday % len(lines)
    topic = lines[idx]
    print(f"[1/6] Today's topic: {topic}")
    return topic

# ─── STEP 2 — GENERATE SCRIPT ────────────────────────────────────────────────

def generate_script(topic: str) -> str:
    print("[2/6] Generating script with Gemini...")
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""You are a scriptwriter for short viral faceless reels about {NICHE}...
Write a {REEL_DURATION}-second voiceover script about: "{topic}"
Rules:
- Start with a SHOCKING hook sentence (no "Did you know")
- Short punchy sentences. Pause beats with "..."
- Build tension then deliver the mind-blowing fact
- End with one reflective closing line
- Plain text only, ~110 words
Return ONLY the script text."""
    response = model.generate_content(prompt)
    script = response.text.strip()
    print(f"    Script ({len(script.split())} words): {script[:80]}...")
    return script

# ─── STEP 3 — GENERATE VOICEOVER ─────────────────────────────────────────────

async def generate_voiceover_async(script: str, out_path: Path):
    communicate = edge_tts.Communicate(script, VOICE, rate="-5%", volume="+10%")
    await communicate.save(str(out_path))

def generate_voiceover(script: str) -> Path:
    print("[3/6] Generating voiceover with Edge TTS...")
    out = OUTPUT_DIR / "voiceover.mp3"
    asyncio.run(generate_voiceover_async(script, out))
    print(f"    Saved: {out}")
    return out

# ─── STEP 4 — FETCH STOCK FOOTAGE ────────────────────────────────────────────

SPACE_QUERIES = [
    "space galaxy stars", "nebula cosmos", "milky way night sky",
    "planet earth from space", "stars universe", "astronomy telescope",
    "solar system", "black hole space", "aurora borealis"
]

def fetch_pexels_videos(n_clips: int = 5) -> list[Path]:
    print("[4/6] Fetching stock footage from Pexels...")
    headers = {"Authorization": PEXELS_API_KEY}
    clips = []
    queries = random.sample(SPACE_QUERIES, min(n_clips, len(SPACE_QUERIES)))

    for i, query in enumerate(queries):
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        videos = r.json().get("videos", [])
        if not videos:
            continue

        # pick a video, prefer portrait (9:16)
        video = random.choice(videos)
        # get smallest HD file to save bandwidth
        files = sorted(video["video_files"], key=lambda x: x.get("width", 0))
        vfile = next((f for f in files if f.get("width", 0) >= 720), files[-1])
        video_url = vfile["link"]

        clip_path = ASSETS_DIR / f"clip_{i}.mp4"
        with requests.get(video_url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(clip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
        clips.append(clip_path)
        print(f"    Downloaded clip {i+1}: {query}")
        time.sleep(0.3)

    return clips

# ─── STEP 5 — ASSEMBLE VIDEO WITH FFMPEG ─────────────────────────────────────

def get_audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())

def download_lofi_music() -> Path:
    """Download a royalty-free lo-fi track from Free Music Archive."""
    music_path = ASSETS_DIR / "lofi.mp3"
    if music_path.exists():
        return music_path
    # Royalty-free lo-fi from archive.org
    url = "https://archive.org/download/lofi_20231231/lofi_chill.mp3"
    try:
        r = requests.get(url, timeout=30, stream=True)
        r.raise_for_status()
        with open(music_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return music_path
    except Exception:
        # fallback: generate silent audio so pipeline doesn't break
        subprocess.run([
            "ffmpeg", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "120", "-q:a", "9", "-acodec", "libmp3lame", str(music_path), "-y"
        ], check=True, capture_output=True)
        return music_path

def wrap_text(text: str, max_chars: int = 38) -> str:
    """Wrap script into subtitle-style lines."""
    words = text.split()
    lines, current = [], []
    for word in words:
        if sum(len(w) for w in current) + len(current) + len(word) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines

def build_video(clips: list[Path], voiceover: Path, script: str, topic: str) -> Path:
    print("[5/6] Assembling video with FFmpeg...")
    audio_dur = get_audio_duration(voiceover)
    clip_dur  = audio_dur / max(len(clips), 1)

    # 1. Scale & crop each clip to 1080x1920 (9:16 portrait), trim to clip_dur
    scaled = []
    for i, clip in enumerate(clips):
        out = ASSETS_DIR / f"scaled_{i}.mp4"
        subprocess.run([
            "ffmpeg", "-i", str(clip), "-t", str(clip_dur),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,"
                   "crop=1080:1920,setsar=1",
            "-c:v", "libx264", "-preset", "fast", "-an", str(out), "-y"
        ], check=True, capture_output=True)
        scaled.append(out)

    # 2. Concatenate clips
    concat_list = ASSETS_DIR / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in scaled))
    concat_out = ASSETS_DIR / "concat.mp4"
    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", str(concat_out), "-y"
    ], check=True, capture_output=True)

    # 3. Get/create lo-fi music
    music = download_lofi_music()

    # 4. Build subtitle drawtext filter (word-by-word fade)
    lines = wrap_text(script)
    words_per_sec = len(script.split()) / audio_dur
    drawtext_filters = []
    word_idx = 0
    for line in lines:
        word_count = len(line.split())
        t_start = word_idx / words_per_sec
        t_end   = (word_idx + word_count) / words_per_sec
        escaped = line.replace("'", "\\'").replace(":", "\\:")
        drawtext_filters.append(
            f"drawtext=text='{escaped}'"
            f":fontcolor=white:fontsize=52:font='Arial Bold'"
            f":x=(w-text_w)/2:y=h*0.75-text_h/2"
            f":shadowcolor=black:shadowx=3:shadowy=3"
            f":enable='between(t,{t_start:.2f},{t_end:.2f})'"
        )
        word_idx += word_count

    vf = ",".join(drawtext_filters)

    # 5. Final mix: video + captions + voice + music
    final_out = OUTPUT_DIR / "final_reel.mp4"
    subprocess.run([
        "ffmpeg",
        "-i", str(concat_out),
        "-i", str(voiceover),
        "-i", str(music),
        "-filter_complex",
        f"[0:v]{vf}[v];"
        f"[1:a]volume=1.0[voice];"
        f"[2:a]volume={MUSIC_VOLUME},aloop=loop=-1:size=44100*120[bg];"
        f"[voice][bg]amix=inputs=2:duration=first[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(audio_dur),
        "-movflags", "+faststart",
        str(final_out), "-y"
    ], check=True)
    print(f"    Final video: {final_out}")
    return final_out

# ─── STEP 6 — UPLOAD TO YOUTUBE ──────────────────────────────────────────────

def upload_to_youtube(video_path: Path, topic: str, script: str):
    print("[6/6] Uploading to YouTube Shorts...")
    creds_data = json.loads(YOUTUBE_TOKEN)
    creds = Credentials(
        token=creds_data["token"],
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
    )
    youtube = build("youtube", "v3", credentials=creds)

    # first 2 sentences as description
    sentences = re.split(r'(?<=[.!?])\s+', script)
    description = " ".join(sentences[:2]) + "\n\n#Shorts #Space #AstronomyFacts #SpaceFacts #Universe"

    body = {
        "snippet": {
            "title": topic[:95] + (" #Shorts" if len(topic) < 88 else ""),
            "description": description,
            "tags": ["shorts", "space", "astronomy", "universe", "facts", "science"],
            "categoryId": "28",   # Science & Technology
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        }
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    Uploading... {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"    ✓ Uploaded! https://youtube.com/shorts/{video_id}")
    return video_id

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Faceless Reels — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    topic     = get_todays_topic()
    script    = generate_script(topic)
    voiceover = generate_voiceover(script)
    clips     = fetch_pexels_videos(n_clips=5)
    video     = build_video(clips, voiceover, script, topic)
    video_id  = upload_to_youtube(video, topic, script)

    print(f"\n✓ Done! Reel posted for: {topic}")
    print(f"  Watch: https://youtube.com/shorts/{video_id}\n")

if __name__ == "__main__":
    main()
