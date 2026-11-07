# Rotativa

A personal daily press briefing in Spanish, emailed at 08:00 UK time (a weekly edition on Sundays).

- `sources.json`: the researched newspapers, agencies and broadcasters (region, leaning, paywall, verified feeds).
- `collector/collect.py`: run by GitHub Actions (`.github/workflows/collect.yml`) at 05:10, 06:10 and 07:10 UTC. It downloads every feed plus market prices and publishes `latest.json` to the `data` branch.
- `briefing/`: used by the Claude cloud routine.
  - `INSTRUCTIONS.md`: what the routine does.
  - `digest.py`: turns the selected sources into a compact text digest.
  - `render.py`: turns the written briefing into the HTML email and the archive record.
- `page/index.html`: the Rotativa page (newspaper picker plus archive), published as a claude.ai artifact. Your picks are stored in its `config/settings` document and each briefing in `briefings/<date>-<edition>`.

Run a collection by hand: `gh workflow run collect.yml`.
