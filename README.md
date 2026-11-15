# Google Flights Scraper

A Python tool to scrape flight search results from [Google Flights](https://www.google.com/travel/flights) using browser automation (Selenium + Chrome).

There are two versions available:
- `google_flights_scraper_selenium.py` — **Recommended** (Selenium + ChromeDriver)
- `google_flights_scraper.py` — Alternative (Playwright)

## Features

- Search flights by origin, destination, dates, passengers, and cabin class
- Supports one-way and round-trip searches
- Outputs structured JSON data with flight details
- Extracts price, airline, duration, stops, departure/arrival times, and more
- Anti-detection measures to avoid bot blocking

## Installation

1. Clone or navigate to the project directory:
```bash
cd google-flight
```

2. Create and activate a virtual environment (optional but recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

> **Note:** Chrome must be installed on your system. The script will auto-download the correct ChromeDriver.

## Usage

### Recommended (Selenium)

```bash
python google_flights_scraper_selenium.py --from "New York" --to "London" --depart 2025-06-15 --return 2025-06-25
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--from`, `-f` | Yes | - | Origin airport code or city name |
| `--to`, `-t` | Yes | - | Destination airport code or city name |
| `--depart`, `-d` | Yes | - | Departure date (YYYY-MM-DD) |
| `--return`, `-r` | For round trips | - | Return date (YYYY-MM-DD) |
| `--passengers`, `-p` | No | 1 | Number of passengers |
| `--class`, `-c` | No | economy | Cabin class: `economy`, `premium_economy`, `business`, `first` |
| `--type` | No | round_trip | Trip type: `one_way`, `round_trip` |
| `--no-headless` | No | False | Show browser UI for debugging |
| `--output`, `-o` | No | stdout | Save JSON output to a file |
| `--max-results` | No | 15 | Maximum number of results to return |

### Examples

**One-way business class flight:**
```bash
python google_flights_scraper_selenium.py \
  --from JFK \
  --to LHR \
  --depart 2025-07-01 \
  --passengers 2 \
  --class business \
  --type one_way
```

**Round-trip economy to Tokyo:**
```bash
python google_flights_scraper_selenium.py \
  --from "Los Angeles" \
  --to "Tokyo" \
  --depart 2025-08-10 \
  --return 2025-08-24 \
  --passengers 1 \
  --class economy
```

**Save results to file:**
```bash
python google_flights_scraper_selenium.py \
  --from "Dhaka" \
  --to "Dubai" \
  --depart 2025-09-15 \
  --return 2025-09-25 \
  -o results.json
```

## Output Format

The script returns a JSON object containing:

```json
{
  "search_parameters": {
    "origin": "New York",
    "destination": "London",
    "departure_date": "2025-06-15",
    "return_date": "2025-06-25",
    "passengers": 1,
    "cabin_class": "economy",
    "trip_type": "round_trip"
  },
  "total_results": 10,
  "flights": [
    {
      "airline": "British Airways",
      "departure": {
        "time": "10:30 PM",
        "airport": null,
        "city": null
      },
      "arrival": {
        "time": "10:50 AM",
        "airport": null,
        "city": null
      },
      "duration": "7 hr 20 min",
      "stops": "Nonstop",
      "price": "$450",
      "currency": "USD",
      "emissions": null,
      "layovers": []
    }
  ]
}
```

## Important Notes

- **Terms of Service**: Web scraping may violate Google's Terms of Service. Use responsibly and for personal/educational purposes only.
- **DOM Changes**: Google frequently updates their website layout. If the scraper stops working, the CSS selectors may need to be updated.
- **Rate Limiting**: Avoid making too many requests in a short period to prevent being blocked.
- **Headless Mode**: If you encounter issues, run with `--no-headless` to see what the browser is doing.

## License

This project is for educational purposes.
