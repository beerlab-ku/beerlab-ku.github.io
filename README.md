# BEER Lab website

Quarto website for the Biodiversity, Ecology and Evolution Research Lab, Kasetsart University.
It is hosted free on GitHub Pages. The publication list refreshes itself every Monday from ORCID and OpenAlex.

## What's where

| File | What it is |
|---|---|
| `index.qmd` | Home page (English + Thai) |
| `people.qmd` | Current members and alumni (instructions at the top of the file) |
| `research.qmd`, `teaching.qmd`, `join.qmd` | The other pages |
| `publications.qmd` | Publications page wrapper (the list itself is generated) |
| `data/pub_config.json` | ORCID iD, name to bold, options |
| `data/pub_overrides.json` | Hide, fix or add papers by hand |
| `data/publications.json` | Latest fetched list (updated by the bot; don't edit) |
| `_publications.md`, `_recent_publications.md` | Generated from the JSON (don't edit) |
| `scripts/fetch_publications.py` | The updater (Python standard library only) |
| `.github/workflows/publish.yml` | Weekly update + build + deploy |
| `styles.scss` | Colours and layout |
| `images/` | Logo, favicon, and `people/` for member photos |

## One-time setup (about 15 minutes)

1. **Create a GitHub organization** for the lab, e.g. `beerlab-ku` (github.com → your avatar → *Your organizations* → *New organization* → Free).
   A personal account also works; the site address will then be `yourname.github.io`.
2. **Create a public repository** in it named exactly **`beerlab-ku.github.io`** (the org name + `.github.io`).
3. **Upload this folder's contents** to the repo. The easiest way is [GitHub Desktop](https://desktop.github.com): *Add → Clone*, copy these files in, then *Commit* and *Push*.
   Make sure the hidden `.github` folder is included; on a Mac press ⌘⇧. in Finder to show it.
4. In the repo, go to **Settings → Pages → Build and deployment → Source: GitHub Actions**.
5. Go to the **Actions** tab → *Update publications and publish site* → **Run workflow**.
   After about 2 minutes the site is live at `https://beerlab-ku.github.io`, and the publication list has been replaced with the live ORCID/OpenAlex data.
6. If you picked a different name, update `site-url` in `_quarto.yml`.

## Keeping publications complete

The updater takes your ORCID record as the main list, adds anything OpenAlex links to your ORCID iD, and uses OpenAlex to fill in full author lists, open-access links and citation counts. To keep it complete without extra work:

- In ORCID, turn on automatic updates from **Crossref** (Account settings → Trusted parties / Permission notifications). New DOIs will then arrive in ORCID on their own.
- Link Scopus to ORCID once with the **Scopus → ORCID wizard** (Scopus author profile → "Connect to ORCID"). That imports your Scopus-indexed papers.
- For papers without a DOI (some Thai journals), add them in ORCID by hand, or put them under `"extra"` in `data/pub_overrides.json`:

```json
{
  "exclude": ["10.1234/wrong.paper", "Exact title of something to hide"],
  "fix": { "10.5678/some.doi": { "venue": "Thai Forest Bulletin (Botany)" } },
  "extra": [
    { "title": "Species richness of bryophytes at Khao Ngon Nak",
      "year": 2020, "venue": "KKU Science Journal",
      "authors": ["A. Senayai", "W. Lomlim", "S. Chantanaorrapint"] }
  ]
}
```

Optional: put an email in `contact_email` in `data/pub_config.json`. OpenAlex gives faster, more reliable service to requests that include one.

To refresh right away instead of waiting for Monday, go to *Actions → Run workflow*.

## Everyday edits

- **Quick text changes:** open the `.qmd` file on github.com, click the pencil, edit, and *Commit*. The site rebuilds itself in about 2 minutes.
- **New member:** copy a `::: {.person}` block in `people.qmd`. For a photo, add a square image to `images/people/` and replace the initials with `![](images/people/name.jpg)`.
- **Graduate:** move the person to the Alumni list.
- **Students can edit too:** add them to the GitHub organization with *Write* access.

## Previewing on your computer (optional)

Install [Quarto](https://quarto.org/docs/get-started/), then in this folder run:

```bash
python3 scripts/fetch_publications.py   # pull the latest publications (optional)
quarto preview
```

## Custom domain (optional)

If you get a domain (e.g. `beerlab.org`, or a `ku.ac.th` subdomain from the university), go to *Settings → Pages → Custom domain*, and ask your DNS admin to add a CNAME record pointing to `beerlab-ku.github.io`.
