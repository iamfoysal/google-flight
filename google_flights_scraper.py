#!/usr/bin/env python3
"""
Google Flights Scraper

Scrapes flight details from Google Flights based on search criteria.
Outputs results as structured JSON data.

Note: Web scraping may be against Google's Terms of Service.
Use responsibly and for personal/educational purposes only.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import List, Dict, Optional, Any

try:
    from playwright.async_api import async_playwright, Page, Browser
except ImportError:
    print("Error: playwright is not installed. Run: pip install playwright && playwright install")
    sys.exit(1)


class GoogleFlightsScraper:
    """Scraper for Google Flights search results."""

    BASE_URL = "https://www.google.com/travel/flights"

    # Cabin class mapping
    CABIN_CLASSES = {
        "economy": "Economy",
        "premium_economy": "Premium economy",
        "business": "Business",
        "first": "First",
    }

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self.page = await context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if hasattr(self, "playwright"):
            await self.playwright.stop()

    async def _dismiss_cookies(self):
        """Try to dismiss cookie consent dialog if present."""
        try:
            # Common Google cookie consent button texts
            cookie_selectors = [
                'button:has-text("Accept all")',
                'button:has-text("I agree")',
                'button:has-text("Agree")',
                'button:has-text("Continue")',
                '[aria-label="Accept all"]',
            ]
            for selector in cookie_selectors:
                try:
                    await self.page.click(selector, timeout=3000)
                    await asyncio.sleep(0.5)
                    break
                except Exception:
                    continue
        except Exception:
            pass

    async def _fill_airport(self, placeholder_text: str, value: str):
        """Fill an airport/city input field."""
        # Try to find input by placeholder text
        input_selector = f'input[placeholder*="{placeholder_text}" i]'
        
        # Click to focus
        await self.page.click(input_selector, timeout=10000)
        await asyncio.sleep(0.3)
        
        # Clear and type
        await self.page.fill(input_selector, "", timeout=5000)
        await self.page.type(input_selector, value, delay=50)
        await asyncio.sleep(1.0)
        
        # Press Down and Enter to select first suggestion
        await self.page.press(input_selector, "ArrowDown")
        await asyncio.sleep(0.3)
        await self.page.press(input_selector, "Enter")
        await asyncio.sleep(0.5)

    async def _select_date(self, date_str: str, is_return: bool = False):
        """Select a date from the date picker."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%a, %b %d")  # e.g., "Mon, Jun 01"
        
        # Click the date input to open calendar
        if is_return:
            # For return date, we might need to click the return date field
            try:
                await self.page.click('input[placeholder*="Return" i]', timeout=5000)
            except Exception:
                await self.page.click('input[placeholder*="Departure" i]', timeout=5000)
        else:
            await self.page.click('input[placeholder*="Departure" i]', timeout=5000)
        
        await asyncio.sleep(0.8)
        
        # Try to find and click the specific date
        # Google uses aria-labels like "Mon, Jun 1, 2025"
        aria_date = date_obj.strftime("%a, %b %-d, %Y")
        date_selector = f'[aria-label="{aria_date}"]'
        
        try:
            await self.page.click(date_selector, timeout=5000)
        except Exception:
            # Fallback: try to click by role=gridcell with the date
            day = date_obj.day
            month_year = date_obj.strftime("%B %Y")
            # Try navigating to correct month if needed
            try:
                # Click the day number within the current calendar view
                await self.page.click(f'[role="gridcell"]:has-text("{day}")', timeout=5000)
            except Exception:
                pass
        
        await asyncio.sleep(0.5)

    async def _set_passengers_and_class(
        self,
        passengers: int,
        cabin_class: str,
    ):
        """Set passenger count and cabin class."""
        # Click on passengers/class dropdown
        try:
            await self.page.click('text=/\\d+ passenger/i', timeout=5000)
        except Exception:
            try:
                await self.page.click('[aria-label*="passenger" i]', timeout=5000)
            except Exception:
                pass
        
        await asyncio.sleep(0.5)
        
        # Set passenger count if > 1
        if passengers > 1:
            # Find the adult passenger increment button
            for _ in range(passengers - 1):
                try:
                    # Look for buttons near "Adult" text
                    await self.page.click('div:has-text("Adult") + div button:last-child', timeout=3000)
                    await asyncio.sleep(0.2)
                except Exception:
                    break
        
        # Set cabin class
        cabin_label = self.CABIN_CLASSES.get(cabin_class.lower(), "Economy")
        try:
            # Click on the cabin class dropdown/select
            await self.page.select_option('select', label=cabin_label)
        except Exception:
            try:
                await self.page.click(f'text="{cabin_label}"')
            except Exception:
                pass
        
        # Click Done button
        try:
            await self.page.click('button:has-text("Done")', timeout=3000)
        except Exception:
            pass
        
        await asyncio.sleep(0.3)

    async def search(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        passengers: int = 1,
        cabin_class: str = "economy",
        trip_type: str = "round_trip",
    ) -> List[Dict[str, Any]]:
        """
        Search for flights and return structured results.
        
        Args:
            origin: Origin airport code or city (e.g., "JFK" or "New York")
            destination: Destination airport code or city (e.g., "LHR" or "London")
            departure_date: Departure date in YYYY-MM-DD format
            return_date: Return date in YYYY-MM-DD format (optional for one-way)
            passengers: Number of passengers
            cabin_class: Cabin class (economy, premium_economy, business, first)
            trip_type: Trip type (one_way, round_trip)
        
        Returns:
            List of flight dictionaries
        """
        if not self.page:
            raise RuntimeError("Scraper not initialized. Use async with.")

        # Navigate to Google Flights
        await self.page.goto(self.BASE_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2.0)
        
        # Dismiss cookie dialog if present
        await self._dismiss_cookies()
        
        # Set trip type if one-way
        if trip_type == "one_way":
            try:
                await self.page.click('[aria-label*="Trip type" i], [role="combobox"]', timeout=3000)
                await asyncio.sleep(0.3)
                await self.page.click('text="One way"', timeout=3000)
                await asyncio.sleep(0.3)
            except Exception:
                pass
        
        # Fill origin
        await self._fill_airport("Where from?", origin)
        
        # Fill destination
        await self._fill_airport("Where to?", destination)
        
        # Select departure date
        await self._select_date(departure_date, is_return=False)
        
        # Select return date if round trip
        if trip_type == "round_trip" and return_date:
            await self._select_date(return_date, is_return=True)
        
        # Set passengers and cabin class
        await self._set_passengers_and_class(passengers, cabin_class)
        
        # Click search button
        try:
            await self.page.click('button[aria-label*="Search" i]', timeout=5000)
        except Exception:
            try:
                await self.page.click('text="Search"', timeout=5000)
            except Exception:
                # Fallback: press Enter
                await self.page.press('input[placeholder*="Where to?" i]', "Enter")
        
        # Wait for results to load
        await asyncio.sleep(5.0)
        
        # Wait for flight cards to appear
        try:
            await self.page.wait_for_selector('[role="listitem"]', timeout=30000)
        except Exception:
            pass
        
        await asyncio.sleep(2.0)
        
        # Extract flight data
        flights = await self._extract_flights()
        
        return flights

    async def _extract_flights(self) -> List[Dict[str, Any]]:
        """Extract flight details from the search results page."""
        flights = []
        
        # Google Flights uses various selectors; try multiple strategies
        # Strategy 1: Look for flight cards by role
        flight_cards = await self.page.query_selector_all('[role="listitem"]')
        
        if not flight_cards:
            # Strategy 2: Look for common container classes
            flight_cards = await self.page.query_selector_all('li, .pIav2d, [jsname]')
        
        for idx, card in enumerate(flight_cards[:15]):  # Limit to first 15 results
            try:
                flight = await self._parse_flight_card(card)
                if flight and flight.get("price"):
                    flights.append(flight)
            except Exception:
                continue
        
        return flights

    async def _parse_flight_card(self, card) -> Dict[str, Any]:
        """Parse a single flight card element."""
        flight = {
            "airline": None,
            "flight_number": None,
            "departure": {
                "time": None,
                "airport": None,
                "city": None,
            },
            "arrival": {
                "time": None,
                "airport": None,
                "city": None,
            },
            "duration": None,
            "stops": None,
            "price": None,
            "currency": None,
            "cabin_class": None,
            "emissions": None,
            "layovers": [],
        }
        
        # Extract price - try multiple selectors
        price_selectors = [
            '[aria-label*="price" i]',
            '[aria-label*="Price" i]',
            '.YMlIz.FpEdX',
            '.FpEdX',
            'span:has-text("$")',
            'span:has-text("€")',
            'span:has-text("£")',
        ]
        
        for selector in price_selectors:
            try:
                price_el = await card.query_selector(selector)
                if price_el:
                    price_text = await price_el.inner_text()
                    if price_text:
                        flight["price"] = price_text.strip()
                        # Detect currency
                        if "$" in price_text:
                            flight["currency"] = "USD"
                        elif "€" in price_text:
                            flight["currency"] = "EUR"
                        elif "£" in price_text:
                            flight["currency"] = "GBP"
                        break
            except Exception:
                continue
        
        # Extract airline
        airline_selectors = [
            'img[alt]',
            '[aria-label*="airline" i]',
            '[aria-label*="Airline" i]',
        ]
        for selector in airline_selectors:
            try:
                airline_el = await card.query_selector(selector)
                if airline_el:
                    airline_text = await airline_el.get_attribute("alt")
                    if airline_text:
                        flight["airline"] = airline_text.strip()
                        break
            except Exception:
                continue
        
        # Extract departure and arrival times
        time_els = await card.query_selector_all('span[aria-label*="time" i], [role="text"]')
        times = []
        for el in time_els[:4]:
            try:
                text = await el.inner_text()
                if text and any(c.isdigit() for c in text):
                    times.append(text.strip())
            except Exception:
                continue
        
        if len(times) >= 2:
            flight["departure"]["time"] = times[0]
            flight["arrival"]["time"] = times[1]
        
        # Extract duration
        duration_selectors = [
            '[aria-label*="duration" i]',
            '[aria-label*="Duration" i]',
            'span:has-text("hr")',
            'span:has-text("hr ")',
        ]
        for selector in duration_selectors:
            try:
                dur_el = await card.query_selector(selector)
                if dur_el:
                    dur_text = await dur_el.inner_text()
                    if dur_text and ("hr" in dur_text or "min" in dur_text):
                        flight["duration"] = dur_text.strip()
                        break
            except Exception:
                continue
        
        # Extract stops
        stops_selectors = [
            '[aria-label*="stop" i]',
            '[aria-label*="Stop" i]',
            'span:has-text("nonstop")',
            'span:has-text("Nonstop")',
            'span:has-text("stop")',
            'span:has-text("Stop")',
        ]
        for selector in stops_selectors:
            try:
                stops_el = await card.query_selector(selector)
                if stops_el:
                    stops_text = await stops_el.inner_text()
                    if stops_text:
                        flight["stops"] = stops_text.strip()
                        break
            except Exception:
                continue
        
        # Extract emissions info
        try:
            emissions_el = await card.query_selector('[aria-label*="emissions" i]')
            if emissions_el:
                flight["emissions"] = await emissions_el.inner_text()
        except Exception:
            pass
        
        return flight

    def to_json(self, flights: List[Dict[str, Any]], indent: int = 2) -> str:
        """Convert flights list to JSON string."""
        return json.dumps(flights, indent=indent, ensure_ascii=False)


async def main():
    parser = argparse.ArgumentParser(
        description="Scrape flight details from Google Flights",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --from "New York" --to "London" --depart 2025-06-15 --return 2025-06-25
  %(prog)s --from JFK --to LHR --depart 2025-07-01 --passengers 2 --class business --type one_way
  %(prog)s --from "Los Angeles" --to "Tokyo" --depart 2025-08-10 --return 2025-08-24 --passengers 1 --class economy
        """,
    )
    
    parser.add_argument(
        "--from", "-f",
        dest="origin",
        required=True,
        help="Origin airport code or city name (e.g., JFK, 'New York')",
    )
    parser.add_argument(
        "--to", "-t",
        dest="destination",
        required=True,
        help="Destination airport code or city name (e.g., LHR, 'London')",
    )
    parser.add_argument(
        "--depart", "-d",
        dest="departure_date",
        required=True,
        help="Departure date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--return", "-r",
        dest="return_date",
        default=None,
        help="Return date in YYYY-MM-DD format (required for round trips)",
    )
    parser.add_argument(
        "--passengers", "-p",
        type=int,
        default=1,
        help="Number of passengers (default: 1)",
    )
    parser.add_argument(
        "--class", "-c",
        dest="cabin_class",
        default="economy",
        choices=["economy", "premium_economy", "business", "first"],
        help="Cabin class (default: economy)",
    )
    parser.add_argument(
        "--type",
        dest="trip_type",
        default="round_trip",
        choices=["one_way", "round_trip"],
        help="Trip type (default: round_trip)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run browser with visible UI for debugging",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path (default: print to stdout)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=15,
        help="Maximum number of results to return (default: 15)",
    )

    args = parser.parse_args()

    # Validate dates
    try:
        datetime.strptime(args.departure_date, "%Y-%m-%d")
        if args.return_date:
            datetime.strptime(args.return_date, "%Y-%m-%d")
    except ValueError:
        print("Error: Dates must be in YYYY-MM-DD format")
        sys.exit(1)

    # Validate return date for round trips
    if args.trip_type == "round_trip" and not args.return_date:
        print("Error: --return date is required for round trips")
        sys.exit(1)

    print(f"Searching flights from {args.origin} to {args.destination}...")
    print(f"Departure: {args.departure_date}")
    if args.return_date:
        print(f"Return: {args.return_date}")
    print(f"Passengers: {args.passengers}, Class: {args.cabin_class}, Type: {args.trip_type}")
    print("-" * 50)

    async with GoogleFlightsScraper(headless=args.headless) as scraper:
        flights = await scraper.search(
            origin=args.origin,
            destination=args.destination,
            departure_date=args.departure_date,
            return_date=args.return_date,
            passengers=args.passengers,
            cabin_class=args.cabin_class,
            trip_type=args.trip_type,
        )

    # Limit results
    flights = flights[:args.max_results]

    # Prepare output
    output = {
        "search_parameters": {
            "origin": args.origin,
            "destination": args.destination,
            "departure_date": args.departure_date,
            "return_date": args.return_date,
            "passengers": args.passengers,
            "cabin_class": args.cabin_class,
            "trip_type": args.trip_type,
        },
        "total_results": len(flights),
        "flights": flights,
    }

    json_output = json.dumps(output, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json_output)
        print(f"\nResults saved to {args.output}")
    else:
        print("\n" + json_output)


if __name__ == "__main__":
    asyncio.run(main())
