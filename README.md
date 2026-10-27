# Daily Tech & Security Brief

Every night at **00:00 IST**, a GitHub Actions workflow:

1. Fetches **BleepingComputer** (security news, with full article text), **Techmeme** (global tech headlines) and the **CISA KEV** catalog.
2. Keeps only items not seen in earlier runs and published in the last ~36 hours.
3. Tags security stories whose CVEs are in KEV as **actively exploited** (and 🦠 if KEV marks them as used by ransomware), and finds newly added KEV entries.
4. Asks an LLM for a detailed Telegram brief and a ~600–900 character lockscreen paragraph. It tries **Gemini** first, then falls back to **GitHub Models** and **Groq** (both free) if Gemini is down.
5. Sends the brief to you on **Telegram**.
6. Writes `summary.json` to a **secret gist**. Your Scriptable script and Shortcut read it to build the lockscreen wallpaper.

Run state (`state.json`: seen links and known KEV IDs) also lives in the gist. It is written only after Telegram delivery succeeds, so a failed night is retried the next night.

```
brief.py               entrypoint
brief/                 modules (sources, kev, gemini, telegram, state, cli, ...)
prompts/brief.txt      the Gemini instructions; edit freely
tests/                 pytest suite with offline fixtures
.github/workflows/     scheduled workflow
```

---

## Setup checklist

### 1. Gemini API key
1. Go to <https://aistudio.google.com/apikey> and sign in.
2. Click **Create API key** and copy it. This is `GEMINI_API_KEY`.
3. Optional: `GEMINI_MODEL` (default `gemini-2.5-flash`). In October 2026 testing, the newer `gemini-3.7-flash`, `gemini-3.8-flash` and `gemini-flash-latest` were overloaded (hanging, or returning 503 "high demand"), so 2.5 is the default. If the model returns 404 or "not supported", the script automatically picks the newest stable `flash` model and logs which one it used.
4. Each Gemini attempt has a hard 90-second limit (see step 1b for the overall time limits). A hung request can't stall the job until GitHub kills it at 10 minutes.

### 1b. Fallback LLMs (free, recommended)
Gemini's newer models were often overloaded in testing, so the brief has two fallbacks, tried in this order:

1. **Gemini** (`GEMINI_API_KEY`), which gets the full input including article text.
2. **GitHub Models**. Nothing to set up: in Actions it uses the built-in `GITHUB_TOKEN` (the workflow requests `models: read`). The default model is `openai/gpt-4.1`; to change it, set a `GITHUB_MODELS_MODEL` secret using a model ID from <https://github.com/marketplace?type=models>.
3. **Groq**. Create a free key at <https://console.groq.com/keys> and add it as the `GROQ_API_KEY` secret. The default model is `openai/gpt-oss-120b`; change it with a `GROQ_MODEL` secret.

The fallbacks have small free-tier request limits, so they get a **compact** input: shorter article excerpts and fewer fields. Any provider that isn't configured is skipped. The brief's last line ("Written by …") and the `generated_by` field in `summary.json` show which provider wrote it.

Time limits: Gemini gets at most 2.5 minutes, then GitHub Models and Groq get 1.5 minutes each. The whole job stays inside its 10-minute limit even if every provider hangs.

### 2. Telegram bot and chat ID
1. In Telegram, open **@BotFather**, send `/newbot`, and follow the prompts.
2. Copy the token BotFather gives you (`123456:ABC-...`). This is `TELEGRAM_TOKEN`.
3. Open a chat with your new bot and send it any message, for example `hi`. The bot can't message you until you've done this.
4. In a browser, open `https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates`.
5. Find `"chat":{"id":123456789,...}` in the response. That number is `TELEGRAM_CHAT_ID`. (If `result` is empty, send the bot another message and reload.)

### 3. Secret gist
1. Go to <https://gist.github.com>.
2. Add a file named `state.json` with the content `{}`.
3. Click **Add file**, name it `summary.json`, and set its content to:
   ```json
   {"status": "ok", "lockscreen": "Waiting for the first brief.", "date_ist": "", "generated_at": "", "new_kev_count": 0, "exploited_in_news_count": 0}
   ```
4. Click **Create secret gist**.
5. The gist ID is the last part of the URL: `https://gist.github.com/<user>/<GIST_ID>`. This is `GIST_ID`.

### 4. GitHub token with only gist access
Use either type:
- **Classic token** (simplest): <https://github.com/settings/tokens> → *Generate new token (classic)*. Tick **only** `gist`, set an expiry, and generate.
- **Fine-grained token**: <https://github.com/settings/personal-access-tokens> → *Generate new token*. Under *Account permissions*, set **Gists → Read and write**. Leave everything else at *No access*.

Copy the token. This is `GIST_TOKEN`. Set a calendar reminder to rotate it before it expires.

### 5. Repository secrets
In this repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | from step 1 |
| `GEMINI_MODEL` | optional; defaults to `gemini-2.5-flash` |
| `GROQ_API_KEY` | optional but recommended; from step 1b |
| `GITHUB_MODELS_MODEL`, `GROQ_MODEL` | optional model overrides |
| `TELEGRAM_TOKEN` | from step 2 |
| `TELEGRAM_CHAT_ID` | from step 2 |
| `GIST_TOKEN` | from step 4 |
| `GIST_ID` | from step 3 |

### 6. Dry run, then a real run
1. Go to **Actions → Daily tech & security brief → Run workflow**, tick **Dry run**, and run it.
2. Open the run logs. You should see each step, then the Telegram text and `summary.json` printed. A dry run sends nothing and writes nothing.
3. Run it again with **Dry run** unticked. You should get the brief on Telegram, and the gist's `state.json` and `summary.json` should update.
4. From then on, it runs automatically every night.

### 7. Lockscreen wallpaper: `summary.json` contract
Your Scriptable script should fetch the raw gist file, with a cache-busting query parameter so you don't get a stale CDN copy:

```
https://gist.githubusercontent.com/<user>/<GIST_ID>/raw/summary.json?t=<unix-time>
```

(Leave the commit hash out of the raw URL so it always serves the latest version.)

```json
{
  "generated_at": "2026-10-27T00:01:12+05:30",
  "date_ist": "27 Oct",
  "lockscreen": "One dense ~600–900 char paragraph covering exploited vulns, new KEV entries, big incidents and top tech stories...",
  "new_kev_count": 2,
  "exploited_in_news_count": 3,
  "status": "ok"
}
```

- `status` is `"ok"` or `"error"`. On error there is also an `"error"` field, and `lockscreen` contains a short "⚠️ Brief failed: ..." sentence.
- On a quiet night, `lockscreen` says nothing new arrived.
- Treat the data as stale if `generated_at` is more than ~36 hours old.
- `lockscreen` is plain text, at most ~1000 characters, with no line breaks or links. Its only emoji is ⚠️.

### 8. Notes
- **Cron runs in UTC.** `30 18 * * *` is 18:30 UTC, which is 00:00 IST.
- **Scheduled runs can start 10–30 minutes late**, especially around the top of the hour. GitHub also disables scheduled workflows after 60 days with no repository activity; re-enable them from the Actions tab if that happens.
- **Keep this repo private.**
- **A secret gist is unlisted, not private.** Anyone with the URL can read it. It only ever holds news links, KEV IDs and the summary, so **never put secrets in it.**
- A run fails (red ❌ in Actions) and sends you a short Telegram alert if all sources fail, or if every LLM provider (Gemini, GitHub Models, Groq) fails. If only one source fails, the brief still goes out with a note at the bottom.

### 9. Editing the Gemini prompt
Edit [`prompts/brief.txt`](prompts/brief.txt) and commit. The input JSON is appended automatically after the prompt, and `{{DATE_IST}}` is replaced with today's date.

Keep these two things unchanged, because the code depends on them:
- The model must return a JSON object with the keys `"telegram"` and `"lockscreen"`.
- The `telegram` text may use only `<b>`, `<i>`, `<code>` and `<a href>` tags. Telegram rejects other tags; when that happens the script resends that part as plain text.

---

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # fill in at least GEMINI_API_KEY

.venv/bin/pytest            # offline tests
.venv/bin/python brief.py --dry-run --local-state ./state.local.json
.venv/bin/python brief.py --dry-run --local-state ./state.local.json --no-fulltext   # faster
```

| Flag | Effect |
|---|---|
| `--dry-run` | Does everything except send Telegram and write state/summary; prints the Telegram text and `summary.json`. |
| `--no-fulltext` | Skips fetching full BleepingComputer articles and uses the RSS teaser. |
| `--local-state PATH` | Uses a local state file instead of the gist (summary goes to `PATH.summary.json` on real runs). |

A dry run doesn't save state, so running it repeatedly always behaves like a first run. To test the "seen items" behaviour locally, do a non-dry run with `--local-state`. This sends to Telegram, so it needs the Telegram variables set.
