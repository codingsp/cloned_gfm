import requests
import json
import csv
import sys
import os
import re
import argparse
import statistics
import time
import html
from datetime import datetime

try:
    from tqdm import tqdm
    from tabulate import tabulate
except ImportError:
    print("Error: Missing required packages.")
    print("Please install them using: pip install -r requirements.txt")
    sys.exit(1)


def clean_html_text(text):
    """
    Normalizes HTML formatted text into clean, readable plain text
    by converting break tags to newlines, stripping tags, unescaping HTML entities,
    and cleaning whitespace.
    """
    if not text:
        return ""
    # Replace block & line break tags with newlines
    text = re.sub(r"<(?:br|/p|/div|/li|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize excessive newlines and spaces
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def get_campaign_slug(url_or_slug):
    """
    Extracts the campaign slug from a full GoFundMe URL,
    handling query parameters, hash fragments, or plain slug input.
    """
    cleaned = url_or_slug.strip()
    match = re.search(r'gofundme\.com/f/([^/?#]+)', cleaned)
    if match:
        return match.group(1)
    
    # If the user passed just the slug directly without URL structure
    if "/" not in cleaned and "?" not in cleaned and "#" not in cleaned and cleaned:
        return cleaned
    
    return None


def fetch_campaign_info_and_donations(slug, original_input, known_donation_ids=None):
    """
    Queries the GoFundMe GraphQL endpoint to fetch full campaign metadata,
    updates, organizer details, and all paginated donations.
    """
    if known_donation_ids is None:
        known_donation_ids = set()
        
    graphql_url = "https://graphql.gofundme.com/graphql"
    
    query = """
    query($slug: ID!, $after: String) {
      fundraiser(slug: $slug) {
        id
        title
        slug
        description
        status
        createdAt
        launchDate
        commentsEnabled
        commentCount
        socialShareCount
        photo {
          url
        }
        currentAmount {
          amount
          currencyCode
        }
        goalAmount {
          amount
          currencyCode
        }
        updates(last: 20) {
          edges {
            node {
              id
              text
              createdAt
            }
          }
        }
        donations(first: 50, after: $after) {
          totalCount
          edges {
            node {
              id
              amount {
                amount
                currencyCode
              }
              createdAt
              name
              isAnonymous
              isOffline
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """
    
    organizer_query = """
    query($fundId: ID!) {
      fundraiserByFundId(fundId: $fundId) {
        organizer {
          id
          firstName
          lastName
          profile {
            name
          }
        }
      }
    }
    """
    
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://www.gofundme.com",
        "Referer": f"https://www.gofundme.com/f/{slug}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    session = requests.Session()
    
    campaign_metadata = {}
    donations = []
    after = None
    
    print(f"Initializing extraction for: {slug}")
    
    pbar = tqdm(desc="Downloading donations", unit=" donations")
    max_retries = 5
    
    try:
        while True:
            success = False
            data = None
            
            for attempt in range(1, max_retries + 1):
                try:
                    res = session.post(
                        graphql_url,
                        json={"query": query, "variables": {"slug": slug, "after": after}},
                        headers=headers,
                        timeout=20
                    )
                    
                    if res.status_code == 200:
                        data = res.json()
                        if "errors" in data and not data.get("data"):
                            time.sleep(attempt * 1.5)
                            continue
                        success = True
                        break
                    elif res.status_code in [429, 500, 502, 503, 504]:
                        time.sleep(attempt * 2)
                    else:
                        res.raise_for_status()
                except (requests.exceptions.RequestException, Exception) as e:
                    if attempt == max_retries:
                        print(f"\nNetwork warning after {max_retries} attempts: {e}")
                    time.sleep(attempt * 1.5)
                    
            if not success or not data:
                print("\nUnable to retrieve next page after retries. Proceeding with collected data...")
                break
                
            fundraiser = (data.get("data") or {}).get("fundraiser")
            if not fundraiser:
                if not donations:
                    print("\nError: Campaign not found or invalid response from GoFundMe.")
                break
                
            # Extract campaign level metadata on first response
            if after is None:
                updates_raw = (fundraiser.get("updates") or {}).get("edges") or []
                updates_list = [u.get("node") for u in updates_raw if u.get("node")]
                
                campaign_metadata = {
                    "id": fundraiser.get("id"),
                    "slug": fundraiser.get("slug") or slug,
                    "title": fundraiser.get("title") or slug,
                    "description": fundraiser.get("description"),
                    "status": fundraiser.get("status"),
                    "createdAt": fundraiser.get("createdAt"),
                    "launchDate": fundraiser.get("launchDate"),
                    "hero_image_url": (fundraiser.get("photo") or {}).get("url"),
                    "current_amount": fundraiser.get("currentAmount"),
                    "goal_amount": fundraiser.get("goalAmount"),
                    "social_share_count": fundraiser.get("socialShareCount"),
                    "comment_count": fundraiser.get("commentCount"),
                    "comments_enabled": fundraiser.get("commentsEnabled"),
                    "updates": updates_list
                }
                
                # Fetch organizer profile if fundId is available
                fund_id = fundraiser.get("id")
                if fund_id:
                    try:
                        res_org = session.post(
                            graphql_url,
                            json={"query": organizer_query, "variables": {"fundId": str(fund_id)}},
                            headers=headers,
                            timeout=10
                        )
                        if res_org.status_code == 200:
                            org_data = (res_org.json().get("data") or {}).get("fundraiserByFundId") or {}
                            campaign_metadata["organizer"] = org_data.get("organizer")
                    except Exception:
                        campaign_metadata["organizer"] = None
                
            donations_data = fundraiser.get("donations") or {}
            
            # Initialize progress bar total if available
            if pbar.total is None:
                total_count = donations_data.get("totalCount")
                if total_count and isinstance(total_count, int):
                    pbar.total = total_count
                    
            edges = donations_data.get("edges") or []
            if not edges:
                break
                
            new_donations_in_page = 0
            for edge in edges:
                node = edge.get("node")
                if node:
                    d_id = node.get("id")
                    if d_id and d_id in known_donation_ids:
                        continue
                    donations.append(node)
                    new_donations_in_page += 1
                
            pbar.update(len(edges))
                
            page_info = donations_data.get("pageInfo") or {}
            
            if new_donations_in_page == 0 and known_donation_ids:
                print("\nReached already known donations. Stopping pagination.")
                break
                
            if not page_info.get("hasNextPage"):
                break
                
            after = page_info.get("endCursor")
            if not after:
                break

    except KeyboardInterrupt:
        print("\n\nExtraction interrupted by user. Exporting collected data so far...")
    finally:
        pbar.close()
        
    return campaign_metadata, donations


def export_data(campaign_metadata, slug, url, raw_donations, format_type, custom_output_dir=None, export_raw=False, existing_donations=None, existing_raw_donations=None):
    """
    Parses donation records, calculates statistical metrics,
    and writes complete metadata to JSON, CSV, and optional raw JSON.
    """
    if existing_donations is None:
        existing_donations = []
    if existing_raw_donations is None:
        existing_raw_donations = []

    if not raw_donations and not campaign_metadata and not existing_donations:
        print("\nNo data found to export.")
        return False

    processed_donations = []
    
    for d in raw_donations:
        raw_date = d.get("createdAt") or ""
        date_str = raw_date
        if raw_date:
            try:
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_str = raw_date
                
        is_anon = bool(d.get("isAnonymous", False))
        name = "Anonymous" if is_anon else (d.get("name") or "Anonymous")
            
        amount_info = d.get("amount") or {}
        try:
            amount = float(amount_info.get("amount") or 0.0)
        except (ValueError, TypeError):
            amount = 0.0
            
        currency = amount_info.get("currencyCode") or "USD"
        
        donation_id = d.get("id") or ""
        is_offline = bool(d.get("isOffline", False))
        
        donation_record = {
            "ID": donation_id,
            "Date": date_str,
            "Name": name,
            "Amount": amount,
            "Currency": currency,
            "IsAnonymous": is_anon,
            "IsOffline": is_offline
        }
        processed_donations.append(donation_record)

    # Merge new processed donations with existing ones
    seen_ids = set()
    merged_processed_donations = []
    
    for d in processed_donations + existing_donations:
        d_id = d.get("ID")
        
        if d_id:
            if d_id in seen_ids:
                continue
            seen_ids.add(d_id)
        merged_processed_donations.append(d)
        
    # Recalculate stats from merged
    amounts = [float(d["Amount"]) for d in merged_processed_donations]
    currencies = set(d["Currency"] for d in merged_processed_donations if d.get("Currency"))
    non_anonymous_count = sum(1 for d in merged_processed_donations if not d.get("IsAnonymous"))

    # Statistical calculations
    total_amount = sum(amounts)
    avg_amount = total_amount / len(amounts) if amounts else 0.0
    med_amount = statistics.median(amounts) if amounts else 0.0
    primary_currency = list(currencies)[0] if len(currencies) == 1 else "Mixed"
    
    stats = {
        "total_amount": round(total_amount, 2),
        "average_amount": round(avg_amount, 2),
        "median_amount": round(med_amount, 2),
        "currency": primary_currency,
        "total_donations": len(merged_processed_donations),
        "non_anonymous_donations": non_anonymous_count,
        "anonymous_donations": len(merged_processed_donations) - non_anonymous_count
    }
    
    # Clean and normalize metadata text for export.json
    cleaned_campaign = dict(campaign_metadata)
    if cleaned_campaign.get("description"):
        cleaned_campaign["description"] = clean_html_text(cleaned_campaign["description"])
    
    if cleaned_campaign.get("updates"):
        cleaned_updates = []
        for u in cleaned_campaign["updates"]:
            if isinstance(u, dict):
                u_copy = dict(u)
                if u_copy.get("text"):
                    u_copy["text"] = clean_html_text(u_copy["text"])
                cleaned_updates.append(u_copy)
            else:
                cleaned_updates.append(u)
        cleaned_campaign["updates"] = cleaned_updates

    json_structure = {
        "campaign": cleaned_campaign,
        "url": url,
        "scraping_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "statistics": stats,
        "donations": merged_processed_donations
    }

    # Merge raw donations
    merged_raw_donations = []
    seen_raw_ids = set()
    for d in raw_donations + existing_raw_donations:
        d_id = d.get("id")
        if d_id:
            if d_id in seen_raw_ids:
                continue
            seen_raw_ids.add(d_id)
        merged_raw_donations.append(d)

    # Raw full export payload
    raw_payload = {
        "campaign_metadata": campaign_metadata,
        "raw_donations": merged_raw_donations
    }

    # Determine destination directory
    output_dir = custom_output_dir or os.path.join("exported", slug)
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"\nSaving data to: {output_dir}/")
    
    # Save JSON
    if format_type in ["json", "both"]:
        json_filename = os.path.join(output_dir, "export.json")
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(json_structure, f, indent=4, ensure_ascii=False)
        print(f"[+] Created {json_filename}")

    # Save CSV
    if format_type in ["csv", "both"]:
        csv_filename = os.path.join(output_dir, "donations.csv")
        fieldnames = ["ID", "Date", "Name", "Amount", "Currency", "IsAnonymous", "IsOffline"]
        with open(csv_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(merged_processed_donations)
        print(f"[+] Created {csv_filename}")

    # Save Raw Data JSON if requested
    if export_raw:
        raw_filename = os.path.join(output_dir, "raw.json")
        with open(raw_filename, "w", encoding="utf-8") as f:
            json.dump(raw_payload, f, indent=4, ensure_ascii=False)
        print(f"[+] Created {raw_filename}")

    print("\nExport completed successfully!")
    
    # Render CLI Summary Table
    curr_str = f" {primary_currency}" if primary_currency != "Mixed" else ""
    campaign_title = campaign_metadata.get("title") or slug
    goal_dict = campaign_metadata.get("goal_amount") or {}
    goal_val = float(goal_dict.get("amount") or 0.0)
    goal_str = f"{goal_val:,.2f} {goal_dict.get('currencyCode', '')}" if goal_val > 0 else "N/A"
    
    organizer_dict = campaign_metadata.get("organizer") or {}
    org_profile = organizer_dict.get("profile") or {}
    org_name = org_profile.get("name") or f"{organizer_dict.get('firstName', '')} {organizer_dict.get('lastName', '')}".strip() or "N/A"
    
    table_data = [
        ["Title", campaign_title],
        ["Organizer", org_name],
        ["Status", campaign_metadata.get("status") or "ACTIVE"],
        ["Target Goal", goal_str],
        ["Total Raised", f"{stats['total_amount']:,.2f}{curr_str}"],
        ["Total Donations", f"{len(merged_processed_donations):,}"],
        ["Average Donation", f"{stats['average_amount']:,.2f}{curr_str}"],
        ["Median Donation", f"{stats['median_amount']:,.2f}{curr_str}"],
        ["Non-anonymous Donors", f"{stats['non_anonymous_donations']:,}"],
        ["Anonymous Donors", f"{stats['anonymous_donations']:,}"],
        ["Updates Count", len(campaign_metadata.get("updates") or [])]
    ]
    
    print("\n" + tabulate(table_data, headers=["Metric", "Value"], tablefmt="psql") + "\n")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Fast and robust GoFundMe complete metadata and donor data scraper (JSON & CSV)."
    )
    parser.add_argument(
        "url",
        help="GoFundMe campaign URL or campaign slug (e.g. https://www.gofundme.com/f/campaign-slug)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="both",
        help="Export format (json, csv, both) - default: both"
    )
    parser.add_argument(
        "--no-raw",
        action="store_false",
        dest="raw",
        help="Skip exporting full unformatted raw GraphQL JSON response (raw.json)"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Custom output directory (default: exported/<campaign-slug>/)"
    )
    
    args = parser.parse_args()
    
    slug = get_campaign_slug(args.url)
    if not slug:
        print("Error: Invalid GoFundMe URL or slug provided.")
        print("Expected format: https://www.gofundme.com/f/campaign-slug or plain campaign-slug")
        sys.exit(1)
        
    full_url = args.url if args.url.startswith("http") else f"https://www.gofundme.com/f/{slug}"
    output_dir = args.output or os.path.join("exported", slug)
    
    existing_donations = []
    existing_raw_donations = []
    known_donation_ids = set()
    
    export_json_path = os.path.join(output_dir, "export.json")
    if os.path.exists(export_json_path):
        try:
            with open(export_json_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                existing_donations = old_data.get("donations", [])
                for d in existing_donations:
                    if d.get("ID"):
                        known_donation_ids.add(d.get("ID"))
            print(f"Found existing export.json with {len(existing_donations)} donations.")
        except Exception as e:
            print(f"Warning: Could not read existing export.json: {e}")
            
    raw_json_path = os.path.join(output_dir, "raw.json")
    if os.path.exists(raw_json_path):
        try:
            with open(raw_json_path, "r", encoding="utf-8") as f:
                old_raw = json.load(f)
                existing_raw_donations = old_raw.get("raw_donations", [])
            print(f"Found existing raw.json with {len(existing_raw_donations)} raw donations.")
        except Exception as e:
            pass
            
    campaign_metadata, raw_donations = fetch_campaign_info_and_donations(slug, full_url, known_donation_ids)
    
    if len(raw_donations) > 0:
        print(f"Fetched {len(raw_donations)} new donations.")
    else:
        print("No new donations found. Updating campaign metadata.")
        
    success = export_data(
        campaign_metadata,
        slug,
        full_url,
        raw_donations,
        args.format,
        args.output,
        export_raw=args.raw,
        existing_donations=existing_donations,
        existing_raw_donations=existing_raw_donations
    )
    
    if not success and not raw_donations:
        sys.exit(1)


if __name__ == "__main__":
    main()
