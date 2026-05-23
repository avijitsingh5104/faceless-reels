# Faceless Reels — Auto Generator

Auto-generates and posts one YouTube Short every day about **Astronomical facts and stories**.

**Pipeline:** Claude API → Edge TTS → Pexels → FFmpeg → YouTube Shorts

---

## Setup (one-time)

### 1. Clone & install locally (optional, for testing)

```bash
git clone https://github.com/YOUR_USERNAME/faceless-reels
cd faceless-reels
pip install -r requirements.txt
sudo apt install ffmpeg   # or: brew install ffmpeg on Mac
```

### 2. Get your API keys

| Key | Where to get it | Free? |
|-----|----------------|-------|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com | $5 free credit |
| `PEXELS_API_KEY` | https://www.pexels.com/api | Free unlimited |
| `YOUTUBE_TOKEN` | See YouTube OAuth below | Free |

### 3. YouTube OAuth token

Run this once on your local machine to get the token:

```python
# get_youtube_token.py
from google_auth_oauthlib.flow import InstalledAppFlow
import json

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secrets.json",   # download from Google Cloud Console
    scopes=["https://www.googleapis.com/auth/youtube.upload"]
)
creds = flow.run_local_server(port=0)
token_data = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
}
print(json.dumps(token_data))
```

Steps:
1. Go to https://console.cloud.google.com
2. Create a project → Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials → Download `client_secrets.json`
4. Run the script above → copy the JSON output

### 4. Add secrets to GitHub

Go to your repo → **Settings → Secrets → Actions → New secret**:

- `ANTHROPIC_API_KEY` — your Anthropic key
- `PEXELS_API_KEY` — your Pexels key  
- `YOUTUBE_TOKEN` — the full JSON string from step 3

### 5. Push to GitHub

```bash
git add .
git commit -m "initial setup"
git push origin main
```

The workflow runs automatically at **9:00 AM IST every day**.
You can also trigger it manually from the **Actions** tab.

---

## Adding more topics

Edit `topics.txt` — one topic per line. The script rotates through them by day of year.

## Testing locally

```bash
export ANTHROPIC_API_KEY=sk-...
export PEXELS_API_KEY=...
export YOUTUBE_TOKEN='{"token":...}'
python main.py
```

## File structure

```
faceless-reels/
├── main.py                        # full pipeline
├── topics.txt                     # your topic queue
├── requirements.txt               
├── README.md                      
├── .github/
│   └── workflows/
│       └── daily.yml              # runs at 9 AM IST daily
├── output/                        # generated videos (gitignored)
└── assets/                        # temp clips (gitignored)
```

Add this to `.gitignore`:
```
output/
assets/
*.mp3
*.mp4
client_secrets.json
```
