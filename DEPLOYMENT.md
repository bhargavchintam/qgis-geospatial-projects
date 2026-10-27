# Publishing checklist

Everything below is free. Total time about 20 minutes.

## 1. Push the repo

```bash
cd qgis-geospatial-projects
git add -A
git status            # sanity check: no *.tif, no results/ folders
git commit -m "Six runnable geospatial projects with demos, Streamlit apps, QGIS assets and CI"
git push origin main
```

The CI workflow (`.github/workflows/ci.yml`) starts on push. It installs each project, runs its tests, runs `demo.py` on a small grid, compiles the QGIS scripts and checks the .qml files. The badge at the top of the root README goes green when it finishes (about 5 to 8 minutes for all six jobs).

## 2. Turn on GitHub Pages (portfolio site + interactive maps)

Status: done. Pages now serves the `main` branch from the root folder. The steps are kept here for reference.

1. Open the repo on GitHub > Settings > Pages.
2. Under "Build and deployment" choose Source: **Deploy from a branch**.
3. Branch: **main**, folder: **/ (root)**. Save.
4. After a minute the site is live at https://bhargavchintam.github.io/qgis-geospatial-projects/

That single setting publishes:

- the landing page `index.html`
- every project's map at `https://bhargavchintam.github.io/qgis-geospatial-projects/<project>/docs/map.html`
- every figure at `.../<project>/docs/figures/00_hero.png`

These URLs are already used in the READMEs and in `index.html`, so nothing else needs editing.

## 3. Deploy the Streamlit apps (live demo links)

Streamlit Community Cloud is free for public repos.

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **New app** (or "Create app" > "Deploy a public app from GitHub").
3. Repository: `bhargavchintam/qgis-geospatial-projects`, branch: `main`.
4. Main file path: `urban-heat-island-analysis/app.py`.
5. App URL (subdomain): type `urban-heat-island-analysis` so the link becomes `https://urban-heat-island-analysis.streamlit.app`.
6. Advanced settings > Python version 3.11. Deploy.
7. Repeat for the other five, changing only the main file path and the subdomain:

| Main file path | Subdomain |
|---|---|
| `urban-heat-island-analysis/app.py` | `urban-heat-island-analysis` |
| `flood-risk-assessment/app.py` | `flood-risk-assessment` |
| `crop-health-ndvi-monitoring/app.py` | `crop-health-ndvi-monitoring` |
| `healthcare-access-analysis/app.py` | `healthcare-access-analysis` |
| `forest-change-detection/app.py` | `forest-change-detection` |
| `solar-site-suitability/app.py` | `solar-site-suitability` |

Streamlit Cloud reads the `requirements.txt` in the same folder as the app file (each project has one), and falls back to the root `requirements.txt`. No secrets or API keys are needed.

If a subdomain is already taken, pick another (for example `bhargav-flood-risk`). Note that `urban-heat-island-analysis` and `flood-risk-assessment` are already used by other people's apps, so those two need new names.

The READMEs and `index.html` do not link to any hosted app yet. After an app is live, add its link in three places: the project README "Try it" section (it says "there is no hosted version yet" today), the "Dashboard code" button on that project's card in `index.html`, and the root README if you want it there.

Free-tier apps sleep after inactivity and wake up in about 30 seconds on the first visit. That is fine for a portfolio; mention it in interviews if someone clicks a cold link.

## 4. GitHub profile README

Status: done. The profile README lives in its own repo, [bhargavchintam/bhargavchintam](https://github.com/bhargavchintam/bhargavchintam), and shows on https://github.com/bhargavchintam automatically. Edit it there, not in this repo.

## 5. What to put on a resume or application form

- Portfolio: https://bhargavchintam.github.io/qgis-geospatial-projects/
- Code: https://github.com/bhargavchintam/qgis-geospatial-projects
- One live app link, for example the flood risk or healthcare access app, since those two are the most interactive.

One-line description that fits most forms:

> Six end-to-end QGIS + Python geospatial projects (urban heat, flood risk, crop health, healthcare access, forest change, solar siting) with interactive maps, Streamlit dashboards, QGIS Processing scripts, 158 automated tests and CI.

## 6. Keeping it honest in interviews

All demo numbers come from synthetic scenes that are built to look and behave like the real data (correct CRS, realistic value ranges, physically consistent layers). Say that up front. The value you are showing is the pipeline, the method choices, the validation and the packaging. Each README has a "Use it with real data" section that names the public datasets, and `config.yaml` is where the paths change. A good follow-up project is to run one pipeline on a real scene and add that result as a second results table.

## 7. Optional upgrades later

- Run one project on real data (Landsat scene for Phoenix is the easiest: three bands from USGS EarthExplorer) and commit a `docs/figures/real_*.png` set.
- Package the six Processing scripts as a single QGIS plugin with a provider, and publish it to the QGIS plugin repository.
- Add a Dockerfile at the root so reviewers can run everything without installing GDAL.
