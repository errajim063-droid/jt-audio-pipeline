# JT Radio Pipeline

Daily audio news bulletin for a French-speaking journalist. Fetches RSS feeds, generates a 4-segment radio script via Claude, converts it to MP3, and emails everything at 18 h.

## Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- A Gmail account with [2-Factor Authentication](https://myaccount.google.com/security) enabled
- A [Gmail App Password](https://myaccount.google.com/apppasswords) (not your regular password)

---

## Installation

```bash
cd ~/jt_audio

# 1 — Install dependencies
pip install feedparser requests beautifulsoup4 anthropic gtts pydub python-dotenv

# 2 — Create your .env file
cp .env.example .env
# Then edit .env with your real keys
```

> **pydub** is optional but recommended — it enables chunked TTS for long scripts.
> Without it, very long scripts may be silently truncated by gTTS.
> Install ffmpeg too if you use pydub: https://ffmpeg.org/download.html

---

## Configuration

Edit `~/jt_audio/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
GMAIL_USER=your.email@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

---

## Running manually

```bash
python ~/jt_audio/main.py
```

Output files land in `~/jt_audio/`:
- `jt_YYYY-MM-DD.mp3` — the audio bulletin
- `script_YYYY-MM-DD.txt` — the full text script

---

## Scheduling

### Linux / WSL (cron)

Run at 17:15 every day (pipeline takes ~30–40 min; email arrives by 18:00):

```bash
crontab -e
```

Add this line:

```
15 17 * * * /usr/bin/python3 ~/jt_audio/main.py >> ~/jt_audio/log.txt 2>&1
```

Verify the Python path first: `which python3`

### Windows (Task Scheduler)

1. Open **Task Scheduler** → *Create Basic Task*
2. Name: `JT Radio Pipeline`
3. Trigger: **Daily** at **17:15**
4. Action: **Start a program**
   - Program: `C:\Users\vPro\AppData\Local\Programs\Python\Python311\python.exe`
   - Arguments: `C:\Users\vPro\jt_audio\main.py`
   - Start in: `C:\Users\vPro\jt_audio`
5. Finish → check *Run with highest privileges*

Or use the PowerShell one-liner below (run as Administrator once):

```powershell
$action = New-ScheduledTaskAction `
  -Execute "python.exe" `
  -Argument "C:\Users\vPro\jt_audio\main.py" `
  -WorkingDirectory "C:\Users\vPro\jt_audio"

$trigger = New-ScheduledTaskTrigger -Daily -At "17:15"

Register-ScheduledTask `
  -TaskName "JT Radio Pipeline" `
  -Action $action `
  -Trigger $trigger `
  -RunLevel Highest `
  -Force
```

---

## Architecture

```
main.py          Orchestrator — runs steps 1–4, handles fallback email
fetcher.py       RSS fetch + keyword filtering → 4 article buckets
processor.py     Claude API → structured French radio script (~4 500 words)
audio.py         gTTS → jt_YYYY-MM-DD.mp3  +  script_YYYY-MM-DD.txt
mailer.py        Gmail SMTP → email with MP3 attachment + article digest
```

### The 4 segments

| # | Title | Sources | Filter |
|---|-------|---------|--------|
| 1 | IA & Tech Maroc | Moroccan general press | Tech/AI keywords |
| 2 | IA & Tech International | TechCrunch, Wired, MIT Tech Review, etc. | Tech/AI keywords |
| 3 | Casablanca & région | Moroccan press | Location keywords |
| 4 | Grandes lignes nationales | MAP + Moroccan general | No tech filter |

### Fallback logic

| Failure point | Action |
|---------------|--------|
| 0 articles fetched | Fallback email (article list only, no audio) |
| Claude API error | Fallback email |
| gTTS error | Email with article list, no MP3 |
| Email error | Logged to stdout/log.txt |

---

## Logs

Each run logs to stdout. When scheduled, redirect to a file:

```
15 17 * * * /usr/bin/python3 ~/jt_audio/main.py >> ~/jt_audio/log.txt 2>&1
```

---

## Troubleshooting

**`535 Authentication failed` from Gmail**
→ Make sure you used an *App Password*, not your regular Gmail password.
→ 2FA must be active on the sending account.

**gTTS `ConnectionError`**
→ Requires internet access to Google's TTS servers. Check your connection.

**Feed returns 0 articles**
→ Check the feed URL directly in a browser. Some feeds rotate or block bots.
→ The pipeline will continue with the other feeds and log a warning.

**Script too short**
→ Add more RSS sources to the relevant list in `fetcher.py`.
→ Increase `max_tokens` in `processor.py` (current: 8192).
