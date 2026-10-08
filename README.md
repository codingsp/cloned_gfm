<div align="left">
  <h1>GoFundMe Donors Export (CLONED)</h1>
  <p><em>A fast, reliable Python script to scrape GoFundMe campaigns and export donor data.</em></p>
</div>

## What is GoFundMe Donors Export?

This is a Python script that pulls all donor data, campaign metadata, and text updates from any GoFundMe campaign and saves them into clean JSON and CSV files.

I built this (with AI) to just work. It hooks directly into GoFundMe's internal GraphQL API, meaning it's fast and handles pagination automatically. It also respects rate limits so you don't get blocked. If you need to stop the script halfway through, just hit `Ctrl+C` and it will safely save whatever it managed to download up to that point.

If you run the script again on the same campaign later, it's smart enough to only fetch the new donations instead of starting over from scratch.

It grabs practically everything available:

- **Campaign data**: Title, story description, current amount raised, target goal, creation dates, the organizer's details, and all campaign updates.
- **Donor data**: Exact timestamps, donation amounts, currencies, donor names, and whether the donation was made anonymously or offline.

## How to Install

1. Clone this repository:

   ```bash
   git clone https://github.com/plumkewe/gofundme-donors-export.git
   cd gofundme-donors-export
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## How to Run

Pass the full campaign URL or just the campaign slug to the script:

```bash
python3 gofundme_scraper.py https://www.gofundme.com/f/campaign-name
```

Or if you just want to use the slug:

```bash
python3 gofundme_scraper.py campaign-name
```

## Parameters

You can tweak how the script exports data using a few flags:

```bash
usage: gofundme_scraper.py [-h] [--format {json,csv,both}] [--no-raw] [--output OUTPUT] url

positional arguments:
  url                   GoFundMe campaign URL or campaign slug (e.g. https://www.gofundme.com/f/campaign-slug)

optional arguments:
  -h, --help            show this help message and exit
  --format {json,csv,both}
                        Export format (json, csv, both) - default: both
  --no-raw              Skip exporting the raw, unformatted GraphQL JSON response (raw.json)
  --output OUTPUT, -o OUTPUT
                        Custom output directory (default: exported/<campaign-slug>/)
```

## Examples

**Default extraction (exports parsed JSON, CSV, and the raw GraphQL JSON):**

```bash
python3 gofundme_scraper.py https://www.gofundme.com/f/campaign-name
```

**Export only the CSV file and skip the raw JSON payload:**

```bash
python3 gofundme_scraper.py https://www.gofundme.com/f/campaign-name --format csv --no-raw
```

**Export to a custom directory instead of the default `exported/` folder:**

```bash
python3 gofundme_scraper.py https://www.gofundme.com/f/campaign-name -o ./my_custom_folder
```
