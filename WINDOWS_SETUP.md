# Posting Dashboard — Windows setup (Command Prompt)

Everything below is typed once, in order. Copy each line exactly.

## Step 1 — Check Python

Open **Command Prompt** (Win+R, type `cmd`, Enter) and run:

```
python --version
```

You need **Python 3.10 or newer**. If it's missing or old, install it from the Microsoft Store (search "Python 3.12") or python.org — tick **"Add python.exe to PATH"** during install.

## Step 2 — Unzip the folder

Unzip the file I sent you (it contains the `phase2` folder) somewhere easy, e.g.:

```
C:\Users\Work\Desktop\dashboard\
```

You should see `run.bat`, `requirements.txt`, and the `app`, `adapters`, `static` folders inside `phase2`.

## Step 3 — Launch

In Command Prompt, go into the folder and run the launcher:

```
cd C:\Users\Work\Desktop\dashboard\phase2
run.bat
```

The first launch takes a minute or two (creates the virtual environment, installs packages, generates the token-encryption key). After that, keep the window open — that's your dashboard server running.

## Step 4 — Open it

In your browser go to:

```
http://127.0.0.1:8077
```

That's the dashboard. Five pages: Home, Upload, Compose, Approve, Audit.

## How it works (the short version)

1. **Accounts** — on the home page, add one account per brand per platform (brand + platform + your @handle).
2. **Upload** — drop in a video file. It stays on YOUR laptop, in the `media` folder.
3. **Compose** — pick the video, pick which brand accounts post it, write the title/caption. The compliance engine checks it (blocks broker links on Faceless Wicks, gambling-operator links on The Odds Board, unlabeled concept art on Heist).
4. **Approve** — nothing posts without your approval. Tap approve, optionally set a scheduled time.
5. **Publish** — approved + due posts go out automatically. Every action lands in the **Audit** log.

## Connect YouTube (real posting)

YouTube is the first platform wired for real publishing. Two parts: **one** Google-side setup (done once), then **per-brand-channel** connect in the dashboard.

### Part A — Get client_secret.json (once, ~10 minutes)

Do this in your browser, signed in as yourself:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a **new project**, name it `V.R World Media`.
2. **APIs & Services → Library** → search **YouTube Data API v3** → **Enable**.
3. **APIs & Services → OAuth consent screen** → **External** → fill in app name (`V.R World Media`), your email, developer email → **Save**. (Leave it in *Testing* for now — tokens last ~7 days; we'll flip it to Production later.)
4. **Credentials → Create Credentials → OAuth client ID** → application type **Desktop app** → name it `dashboard` → **Create**.
5. **Download JSON** (the ⬇ button on the new client). Rename the downloaded file to exactly **`client_secret.json`**.
6. Copy `client_secret.json` into the **phase2 folder** (the same folder as `run.bat`). Then **restart the dashboard** (Ctrl+C in its window, run `run.bat` again).

The dashboard's home page has a **YouTube** section — if it says "client_secret.json is missing", the file isn't in the right folder yet. (Never email this file or post it anywhere — it's a secret.)

### Part B — Connect each brand channel (in the dashboard)

1. On the home page, **add one YouTube account per brand** (Connected accounts → Add account → platform **YouTube**, brand, display name like `@Heisthq365official`).
2. In the **YouTube** section, click **Connect YouTube** next to a brand.
3. Your browser opens **Google's sign-in** — sign in with the **Google account that owns that brand's channel** (e.g. `hqheist375@gmail.com` for Heist), click through the "unverified app" warning (Advanced → Go to …), and **Approve**.
4. Google sends you back to a dashboard page saying **"YouTube connected"** with the channel id. Done — repeat for the other two brands.

After this, approved + due posts on a YouTube account **upload for real**. They go up as **private** by default — you flip them to public/unlisted in YouTube Studio. Quota: uploads have their own 100/day allowance (1 unit per upload); the project's standard 10,000 units/day quota is separate — the dashboard shows uploads today against the 100/day allowance. Move the OAuth consent screen to Production later to stop the 7-day token expiry.

To revoke: YouTube section → **Disconnect**, and remove the app at `myaccount.google.com/permissions`.

## Mock mode vs real posting

Right now the adapters run in **real mode but without tokens** — publishing will fail until platform API keys are connected (that's the next step, and it's your keys, so we do it together in your browser).

To see the full pipeline work end-to-end before wiring keys, run one test launch in **mock mode** (publishes are simulated, zero network calls):

```
cd C:\Users\Work\Desktop\dashboard\phase2
set VRWM_MOCK_ADAPTERS=1
run.bat
```

Close that window, run `run.bat` normally to go back to real mode.

## Notes

- Your token-encryption key lives in `.vrwm_key` next to `run.bat` — don't share it, don't delete it (stored platform tokens stop decrypting without it).
- The database lives in `data\hub.db` — your posts, accounts, and audit trail. Back it up if you ever move the folder.
- The window must stay open while you use the dashboard. When you close it (Ctrl+C), the server stops; run `run.bat` to start it again.
