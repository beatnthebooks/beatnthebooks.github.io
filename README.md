# Edge Board

NFL betting analytics: an Elo model compared with the betting market, a tested
wind-under signal for totals, season tracking and team ratings. Analysis only;
it never places bets.

The website (`site/`) has four pages: **This week**, **Season**, **Teams** and **Method**.
`weekly.py` rebuilds its numbers (`site/data.js`) from the latest nflverse data and
Open-Meteo wind forecasts. Python 3.9+, standard library only.

```bash
py weekly.py --fetch     # download fresh data and rebuild the site
```

Then open `site/index.html` in a browser.

## Put it on the web (GitHub Pages, free, updates itself)

The workflow in `.github/workflows/update-site.yml` rebuilds and republishes the
site six times a day in GitHub's cloud, so your computer doesn't need to be on.

1. Sign in at github.com (or create an account) and click **New repository**.
   Name it `edge-board`. Free accounts need it to be **Public** for Pages.
2. On the new repo page, click **uploading an existing file**, drag in everything
   from this folder (including the `.github` folder), and click **Commit changes**.
   If `.github` doesn't upload, use **Add file → Create new file**, type the name
   `.github/workflows/update-site.yml`, and paste that file's contents.
3. Go to **Settings → Pages** and set **Source** to **GitHub Actions**.
4. Go to **Settings → Actions → General → Workflow permissions** and choose
   **Read and write permissions**, then **Save**.
5. Go to the **Actions** tab, open **Update site**, and click **Run workflow**.

After about a minute the site is live at `https://<your-username>.github.io/edge-board/`.

## Best prices across sportsbooks (optional)

1. Get a free key at https://the-odds-api.com (Starter plan, 500 credits a month).
2. On your PC, save it as a user environment variable named `ODDS_API_KEY`, then restart the Claude app.
   On GitHub, add it under **Settings → Secrets and variables → Actions → New repository secret**
   with the same name.
3. By default the site prices your bets on **Kalshi and Polymarket** (fees included) against the
   fair price from the sportsbooks. To change where you bet, set `ODDS_BOOKS`, e.g.
   `kalshi,polymarket,draftkings` (on GitHub: the **Variables** tab on the same page).
4. Run `py odds.py` to see a line-shopping table. Each fetch costs 3 credits and is cached for 6 hours.
   Use the key in one place only (your PC or GitHub), or the two will share the monthly credits.

## Files

| File | What it does |
|---|---|
| `weekly.py` | Builds the website's data: every game, Elo vs market, wind signals, results, ratings |
| `site/` | The website: static pages + `assets/`, plus the generated `data.js` |
| `alerts.py` | Phone alerts for new wind unders and price gaps (ntfy app; channel name in `ntfy_topic.txt`) |
| `odds.py` | Best price per bet across sportsbooks (The Odds API; needs a free key) |
| `rift_real.py` | Walk-forward Elo model and the real backtest (2016–2025 at closing lines) |
| `edge_lab.py` | Tests 37 signals against the market's own price, out of sample |
| `injuries.py` | Tests injury-report signals (snap share out) against the closing line; none passed |
| `history.py` | Opening vs closing lines (aussportsbetting.com sheet, personal use only) |
| `wind_check.py` | Re-tests the wind signal with archived forecasts |
| `update_board.py` | Refreshes the older one-page local board in `web/edge-board.html` |
| `rift_edge.py`, `rift_model.py`, `rift_backtest.py` | Odds math, model classes, simulation harness |
| `data/games.csv` | nflverse game data since 1999 |
| `data/wind_log.json` | The wind forecast used for each 2026 game (frozen at kickoff) |
| `results/` | Backtest outputs and the tuned model settings |
