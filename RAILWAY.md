# Railway: see your deployed app

GitHub repo: https://github.com/anushkamathur14-cloud/ReceiptAutomation-

The app does **not** appear on GitHub Pages. It runs only on Railway after you expose it.

## Step 1 — Confirm deploy succeeded

1. Open [Railway Dashboard](https://railway.app/dashboard).
2. Open project **ReceiptAutomation-**.
3. Click your service.
4. Open the **Deployments** tab.
5. Latest deploy should be **Active** / green (commit: `Fix Railway deploy with Dockerfile and web API`).

If it says **Failed**, click **View logs** and fix that first.

## Step 2 — Generate a public URL (required)

Your service was **Unexposed** — there is no public link until you create one.

1. In the same service, go to **Settings**.
2. Scroll to **Networking** (or **Public Networking**).
3. Click **Generate Domain** (or **+ Domain**).
4. Copy the URL Railway gives you, e.g.  
   `https://receiptautomation-production-xxxx.up.railway.app`

That URL is your deployed app.

## Step 3 — Open the app

In your browser, visit:

| What | URL |
|------|-----|
| Home page | `https://YOUR-DOMAIN/` |
| Health check | `https://YOUR-DOMAIN/health` |
| Demo run | `https://YOUR-DOMAIN/api/sample-run` |
| Upload UI | `https://YOUR-DOMAIN/docs` |

You should see a green **“Deployed and running”** banner on `/`.

## Step 4 — Redeploy if needed

If you do not see the latest version:

1. **Deployments** → **Redeploy** on the latest commit, or
2. Push any small change to `main` on GitHub (Railway auto-deploys).

## Common mistakes

- Opening the **GitHub repo** instead of the **Railway domain** — the live app is not on GitHub.
- Skipping **Generate Domain** — Railway runs the app but gives no public link.
- Using an old failed deployment URL — use the domain from the **Active** deployment.

## Still stuck?

Send a screenshot of:

1. Deployments tab (status)
2. Settings → Networking (domain section)
3. Build/deploy logs if status is Failed
