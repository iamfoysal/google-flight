#!/usr/bin/env python3
"""
Google Flights Scraper (Selenium Version)

Scrapes flight details from Google Flights based on search criteria.
Outputs results as structured JSON data.

Note: Web scraping may be against Google's Terms of Service.
Use responsibly and for personal/educational purposes only.
"""

import argparse
import json
import sys
import time
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager


class GoogleFlightsScraper:
    """Scraper for Google Flights search results using Selenium."""

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
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None

    def __enter__(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        
        # Anti-detection measures
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
        self.wait = WebDriverWait(self.driver, 15)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver.quit()

    def _dismiss_cookies(self):
        """Try to dismiss cookie consent dialog if present."""
        try:
            cookie_buttons = [
                "//button[contains(., 'Accept all')]",
                "//button[contains(., 'I agree')]",
                "//button[contains(., 'Agree')]",
                "//button[@aria-label='Accept all']",
                "//div[contains(@role, 'dialog')]//button[contains(., 'Accept')]",
            ]
            for xpath in cookie_buttons:
                try:
                    btn = self.driver.find_element(By.XPATH, xpath)
                    btn.click()
                    time.sleep(1)
                    break
                except NoSuchElementException:
                    continue
        except Exception:
            pass

    def _find_input_by_aria_label(self, aria_label: str, timeout: int = 10):
        """Find input by aria-label."""
        # Strategy 1: Exact match
        try:
            xpath = f"//input[@aria-label='{aria_label}']"
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except TimeoutException:
            pass
        
        # Strategy 2: Contains
        try:
            xpath = f"//input[contains(@aria-label, '{aria_label}')]"
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except TimeoutException:
            pass
        
        # Strategy 3: Find visible input that matches
        inputs = self.driver.find_elements(By.TAG_NAME, "input")
        for inp in inputs:
            if inp.is_displayed():
                label = inp.get_attribute("aria-label") or ""
                if aria_label.lower() in label.lower():
                    return inp
        
        raise TimeoutException(f"Could not find input with aria-label: {aria_label}")

    def _click_to_open_dialog(self, aria_label: str):
        """Click the original input to open the dialog. Uses JS click if intercepted."""
        try:
            el = self._find_input_by_aria_label(aria_label)
            # Try regular click first
            try:
                el.click()
            except ElementClickInterceptedException:
                # Dialog already open or overlay blocking - use JS click
                self.driver.execute_script("arguments[0].click();", el)
            time.sleep(0.5)
            return el
        except TimeoutException:
            # Last resort: click by coordinates on any element with matching text
            elements = self.driver.find_elements(By.XPATH, f"//*[contains(text(), '{aria_label.replace('?', '')}')]")
            for el in elements:
                if el.is_displayed():
                    self.driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.5)
                    return el
            raise

    def _get_dialog_input(self, original_aria_label: str, timeout: int = 5):
        """Get the input inside the opened dialog."""
        time.sleep(0.5)
        
        # Strategy 1: Use active element (most reliable since dialog input has autofocus)
        active = self.driver.switch_to.active_element
        if active.tag_name == "input":
            return active
        
        # Strategy 2: Find input with autofocus
        try:
            return self.driver.find_element(By.XPATH, "//input[@autofocus]")
        except NoSuchElementException:
            pass
        
        # Strategy 3: Find any visible input in a dialog/role=dialog
        try:
            inputs = self.driver.find_elements(By.XPATH, "//div[@role='dialog']//input | //div[@role='modal']//input")
            for inp in inputs:
                if inp.is_displayed():
                    return inp
        except Exception:
            pass
        
        # Strategy 4: Find by aria-label variations
        variations = [
            original_aria_label,
            original_aria_label + " ",
            original_aria_label.replace("?", ""),
            "Where else?",
            "Where to?",
            "Enter your origin",
            "Enter your destination",
        ]
        for var in variations:
            try:
                return self.driver.find_element(By.XPATH, f"//input[@aria-label='{var}' or contains(@aria-label, '{var}')]")
            except NoSuchElementException:
                continue
        
        # Strategy 5: Return active element anyway
        return active

    def _clear_and_type(self, element, value: str):
        """Clear input field and type new value, handling pre-filled values."""
        # Make sure element is interactable
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.2)
        
        # Click to focus
        try:
            element.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].focus();", element)
        time.sleep(0.3)
        
        # Select all text using JS
        self.driver.execute_script("arguments[0].select();", element)
        time.sleep(0.2)
        
        # Also send Ctrl+A to ensure selection
        element.send_keys(Keys.CONTROL + "a")
        time.sleep(0.2)
        
        # Delete selected text
        element.send_keys(Keys.DELETE)
        time.sleep(0.2)
        
        # Type new value
        element.send_keys(value)
        time.sleep(1.5)

    def _fill_airport(self, aria_label: str, value: str):
        """Fill an airport/city input field."""
        # Click the original input to open dialog
        self._click_to_open_dialog(aria_label)
        
        # Get the dialog's input (has autofocus)
        dialog_input = self._get_dialog_input(aria_label)
        
        # Clear and type in the dialog input
        self._clear_and_type(dialog_input, value)
        
        # Wait for dropdown suggestions to appear
        time.sleep(1.5)
        
        # Try to click the first suggestion in the dropdown
        suggestion_clicked = False
        suggestion_selectors = [
            "//ul[@role='listbox']/li[1]",
            "//div[@role='listbox']//li[1]",
            "//div[@role='option'][1]",
            "//ul//li[1]",
            f"//li[contains(., '{value}') or contains(., '{value.title()}')]",
        ]
        for xpath in suggestion_selectors:
            try:
                suggestions = self.driver.find_elements(By.XPATH, xpath)
                for sug in suggestions:
                    if sug.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", sug)
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].click();", sug)
                        time.sleep(0.5)
                        suggestion_clicked = True
                        break
                if suggestion_clicked:
                    break
            except Exception:
                continue
        
        # If no suggestion clicked, try arrow down + enter
        if not suggestion_clicked:
            active_input = self.driver.switch_to.active_element
            active_input.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.5)
            active_input.send_keys(Keys.ENTER)
            time.sleep(0.5)
        
        # Try to click Done button to confirm and close dialog
        try:
            done_btn = self.driver.find_element(By.XPATH, "//button[@aria-label='Done' or contains(., 'Done')]")
            if done_btn.is_displayed():
                self.driver.execute_script("arguments[0].click();", done_btn)
                time.sleep(0.5)
        except NoSuchElementException:
            # Press Escape as fallback to close dialog
            self._close_dialogs()

    def _close_dialogs(self):
        """Close any open dialogs/calendars by pressing Escape."""
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ESCAPE)
            time.sleep(0.3)
        except Exception:
            pass

    def _click_date_field(self, field_type: str = "departure"):
        """Click on the date field to open date picker."""
        # First close any open dialogs
        self._close_dialogs()
        
        labels = {
            "departure": ["Departure", "departure", "Depart", "depart"],
            "return": ["Return", "return"],
        }
        
        for label in labels.get(field_type, ["Departure"]):
            try:
                # Try to find by aria-label
                xpath = f"//input[@aria-label='{label}' or contains(@aria-label, '{label}')]"
                el = self.driver.find_element(By.XPATH, xpath)
                if el.is_displayed():
                    try:
                        el.click()
                    except ElementClickInterceptedException:
                        self.driver.execute_script("arguments[0].click();", el)
                    time.sleep(0.5)
                    return el
            except NoSuchElementException:
                continue
        
        # Fallback: find any visible input near date-related text
        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs:
                if inp.is_displayed():
                    aria = inp.get_attribute("aria-label") or ""
                    placeholder = inp.get_attribute("placeholder") or ""
                    if any(x.lower() in aria.lower() for x in labels.get(field_type, ["departure"])):
                        try:
                            inp.click()
                        except ElementClickInterceptedException:
                            self.driver.execute_script("arguments[0].click();", inp)
                        time.sleep(0.5)
                        return inp
                    if any(x.lower() in placeholder.lower() for x in labels.get(field_type, ["departure"])):
                        try:
                            inp.click()
                        except ElementClickInterceptedException:
                            self.driver.execute_script("arguments[0].click();", inp)
                        time.sleep(0.5)
                        return inp
        except Exception:
            pass
        
        return None

    def _select_date(self, date_str: str):
        """Select a date from the calendar picker."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day = date_obj.day
        month_year = date_obj.strftime("%B %Y")
        
        # Strategy 1: Click date by aria-label containing the full date
        aria_date_formats = [
            date_obj.strftime("%a, %b %-d, %Y"),
            date_obj.strftime("%a, %b %d, %Y"),
            date_obj.strftime("%A, %B %-d, %Y"),
            date_obj.strftime("%A, %B %d, %Y"),
        ]
        
        for aria_date in aria_date_formats:
            try:
                xpath = f"//div[contains(@aria-label, '{aria_date}')]"
                elements = self.driver.find_elements(By.XPATH, xpath)
                for el in elements:
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                        time.sleep(0.3)
                        el.click()
                        time.sleep(0.5)
                        self._close_datepicker()
                        return True
            except Exception:
                continue
        
        # Strategy 2: Find by role=gridcell and text content
        try:
            xpath = f"//div[@role='gridcell' and contains(., '{day}')]"
            elements = self.driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed():
                    # Check if it's in the right month
                    parent = el.find_element(By.XPATH, "..")
                    if month_year.lower() in (parent.text or "").lower() or month_year.lower() in (self.driver.find_element(By.XPATH, "//div[@role='dialog']").text or "").lower():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                        time.sleep(0.3)
                        el.click()
                        time.sleep(0.5)
                        self._close_datepicker()
                        return True
        except Exception:
            pass
        
        # Strategy 3: Click any visible element with the day number
        try:
            xpath = f"//div[contains(@class, 'WhWfE') and contains(., '{day}')]"
            elements = self.driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed():
                    el.click()
                    time.sleep(0.5)
                    self._close_datepicker()
                    return True
        except Exception:
            pass
        
        # Strategy 4: Type date directly and press enter
        try:
            active_input = self.driver.switch_to.active_element
            active_input.clear()
            active_input.send_keys(Keys.CONTROL + "a")
            active_input.send_keys(Keys.DELETE)
            active_input.send_keys(date_str)
            time.sleep(0.3)
            active_input.send_keys(Keys.ENTER)
            time.sleep(0.5)
            self._close_datepicker()
            return True
        except Exception:
            pass
        
        self._close_datepicker()
        return False

    def _close_datepicker(self):
        """Close datepicker by clicking Done button or clicking outside."""
        # Strategy 1: Click Done button
        try:
            done_selectors = [
                "//button[@aria-label='Done']",
                "//button[contains(., 'Done')]",
                "//span[contains(., 'Done')]/parent::button",
            ]
            for xpath in done_selectors:
                btns = self.driver.find_elements(By.XPATH, xpath)
                for btn in btns:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.5)
                        return
        except Exception:
            pass
        
        # Strategy 2: Click outside on body to close
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            # Click on a neutral area (top-left corner of body)
            self.driver.execute_script("arguments[0].click();", body)
            time.sleep(0.3)
        except Exception:
            pass
        
        # Strategy 3: Press Escape as fallback
        self._close_dialogs()

    def _set_trip_type_one_way(self):
        """Set trip type to one-way by clicking the trip type combobox."""
        try:
            # Find the combobox containing "Round trip"
            trip_combobox = self.driver.find_element(By.XPATH,
                "//div[@role='combobox' and contains(., 'Round trip')]"
            )
            self.driver.execute_script("arguments[0].click();", trip_combobox)
            time.sleep(0.5)
            
            # Select "One way" from dropdown
            one_way_option = self.driver.find_element(By.XPATH,
                "//div[@role='option' and contains(., 'One way')] | //li[contains(., 'One way')] | //div[contains(., 'One way')]"
            )
            self.driver.execute_script("arguments[0].click();", one_way_option)
            time.sleep(0.5)
            print("Trip type set to One way")
        except Exception as e:
            print(f"Could not set trip type: {e}")
            # Fallback: try to set via date picker dialog
            try:
                self._click_date_field("departure")
                time.sleep(0.5)
                trip_btn = self.driver.find_element(By.XPATH,
                    "//div[@role='combobox' and contains(., 'Round trip')]"
                )
                self.driver.execute_script("arguments[0].click();", trip_btn)
                time.sleep(0.5)
                one_way = self.driver.find_element(By.XPATH,
                    "//div[@role='option' and contains(., 'One way')]"
                )
                self.driver.execute_script("arguments[0].click();", one_way)
                time.sleep(0.5)
                self._close_datepicker()
            except Exception:
                pass

    def _set_date_by_typing(self, date_str: str, field_type: str = "departure"):
        """Set date by clicking the field and typing the date directly."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        
        # Click the date field to open picker
        date_input = self._click_date_field(field_type)
        if not date_input:
            print(f"Could not find {field_type} date field")
            return False
        
        time.sleep(0.8)
        
        # Try to type the date in a user-friendly format
        # Google Flights accepts various formats like "Aug 15" or "Thu, Aug 15"
        typed_formats = [
            date_obj.strftime("%b %d, %Y"),      # Aug 15, 2025
            date_obj.strftime("%a, %b %d"),       # Fri, Aug 15
            date_obj.strftime("%B %d, %Y"),       # August 15, 2025
            date_obj.strftime("%b %d"),           # Aug 15
            date_str,                              # 2025-08-15
        ]
        
        for date_text in typed_formats:
            try:
                # Get the active input (should be the date input in the dialog)
                active_input = self.driver.switch_to.active_element
                if active_input.tag_name != "input":
                    # Find the field input in the dialog
                    inputs = self.driver.find_elements(By.TAG_NAME, "input")
                    for inp in inputs:
                        aria = inp.get_attribute("aria-label") or ""
                        if field_type in aria.lower():
                            active_input = inp
                            break
                
                # Use JS to focus and set value directly for reliability
                self.driver.execute_script("arguments[0].focus();", active_input)
                time.sleep(0.2)
                self.driver.execute_script("arguments[0].select();", active_input)
                time.sleep(0.2)
                
                # Type the date
                active_input.send_keys(date_text)
                time.sleep(0.8)
                
                # Press Enter to confirm
                active_input.send_keys(Keys.ENTER)
                time.sleep(0.8)
                
                # Check if value was set
                current_value = active_input.get_attribute("value")
                if current_value and len(current_value) > 3:
                    print(f"Date set to: {current_value}")
                    self._close_datepicker()
                    return True
            except Exception as e:
                print(f"Date format '{date_text}' failed: {e}")
                continue
        
        # Fallback: try calendar clicking
        self._select_date(date_str)
        return True

    def _click_search_button(self):
        """Click the search button with multiple fallback strategies."""
        # Strategy 1: Find button with aria-label='Search'
        try:
            search_btn = self.driver.find_element(By.XPATH, "//button[@aria-label='Search']")
            if search_btn.is_displayed():
                self.driver.execute_script("arguments[0].click();", search_btn)
                print("Search clicked (aria-label)")
                return
        except NoSuchElementException:
            pass
        
        # Strategy 2: Find button containing "Search" text
        try:
            search_btn = self.driver.find_element(By.XPATH,
                "//button[contains(., 'Search')] | //div[@role='button' and contains(., 'Search')]"
            )
            if search_btn.is_displayed():
                self.driver.execute_script("arguments[0].click();", search_btn)
                print("Search clicked (text content)")
                return
        except NoSuchElementException:
            pass
        
        # Strategy 3: Press Enter on body
        try:
            body = self.driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ENTER)
            print("Search triggered with Enter key")
        except Exception:
            pass

    def _set_passengers_and_class(self, passengers: int, cabin_class: str):
        """Set passenger count and cabin class."""
        # Close any open dialogs first
        self._close_dialogs()
        
        # If defaults (1 passenger, economy), we might skip this entirely
        # But let's still try to open it for robustness
        dialog_opened = False
        
        # Click on passengers/class dropdown
        try:
            traveler_btn = self.driver.find_element(By.XPATH, 
                "//button[contains(., 'passenger') or contains(., 'Passenger') or contains(., 'traveler') or contains(., 'Traveler') or contains(@aria-label, 'passenger') or contains(@aria-label, 'Passenger')]"
            )
            self.driver.execute_script("arguments[0].click();", traveler_btn)
            time.sleep(0.5)
            dialog_opened = True
        except NoSuchElementException:
            try:
                btns = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in btns:
                    text = btn.text or ""
                    if any(x in text for x in ["1 passenger", "2 passengers", "Economy", "Business"]):
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.5)
                        dialog_opened = True
                        break
            except Exception:
                pass
        
        if not dialog_opened:
            return
        
        # Set passenger count if > 1
        if passengers > 1:
            try:
                adult_section = self.driver.find_element(By.XPATH, "//div[contains(., 'Adult') or contains(., 'adult')]")
                increment_btns = adult_section.find_elements(By.TAG_NAME, "button")
                for _ in range(passengers - 1):
                    for btn in increment_btns:
                        if "+" in btn.text or "increment" in (btn.get_attribute("aria-label") or "").lower():
                            self.driver.execute_script("arguments[0].click();", btn)
                            time.sleep(0.3)
                            break
            except Exception:
                pass
        
        # Set cabin class
        cabin_label = self.CABIN_CLASSES.get(cabin_class.lower(), "Economy")
        try:
            select = self.driver.find_element(By.TAG_NAME, "select")
            options = select.find_elements(By.TAG_NAME, "option")
            for opt in options:
                if cabin_label.lower() in (opt.text or "").lower():
                    self.driver.execute_script("arguments[0].click();", opt)
                    time.sleep(0.3)
                    break
        except NoSuchElementException:
            try:
                class_option = self.driver.find_element(By.XPATH, f"//div[contains(., '{cabin_label}')]")
                self.driver.execute_script("arguments[0].click();", class_option)
                time.sleep(0.3)
            except NoSuchElementException:
                pass
        
        # Click Done button
        try:
            done_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Done') or contains(@aria-label, 'Done')]")
            if done_btn.is_displayed() and done_btn.is_enabled():
                self.driver.execute_script("arguments[0].click();", done_btn)
                time.sleep(0.5)
        except Exception:
            # If Done button fails, just press Escape to close
            self._close_dialogs()

    def search(
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
        """
        if not self.driver:
            raise RuntimeError("Scraper not initialized. Use 'with' statement.")

        # Navigate to Google Flights
        self.driver.get(self.BASE_URL)
        time.sleep(3)
        
        # Dismiss cookie dialog if present
        self._dismiss_cookies()
        
        # Fill origin - use aria-label to find the field
        print(f"Setting origin to: {origin}")
        self._fill_airport("Where from?", origin)
        
        # Fill destination
        print(f"Setting destination to: {destination}")
        self._fill_airport("Where to?", destination)
        
        # Set trip type BEFORE opening date picker (can also be done in date dialog)
        if trip_type == "one_way":
            self._set_trip_type_one_way()
        
        # Click departure date field and select date by typing
        print(f"Setting departure date: {departure_date}")
        self._set_date_by_typing(departure_date, field_type="departure")
        time.sleep(0.5)
        
        # If round trip, handle return date
        if trip_type == "round_trip" and return_date:
            print(f"Setting return date: {return_date}")
            self._set_date_by_typing(return_date, field_type="return")
            time.sleep(0.5)
        
        # Set passengers and class
        self._set_passengers_and_class(passengers, cabin_class)
        
        # Click search button
        print("Clicking search...")
        self._click_search_button()
        
        # Wait for results to load
        print("Waiting for results to load...")
        time.sleep(12)
        
        # Debug: print current URL
        print(f"Current URL: {self.driver.current_url}")
        
        # Extract flight data
        flights = self._extract_flights()
        
        # If no flights found, try scrolling and waiting a bit more
        if not flights:
            print("No flights found initially, scrolling and retrying...")
            self.driver.execute_script("window.scrollTo(0, 500);")
            time.sleep(3)
            flights = self._extract_flights()
        
        return flights

    def _extract_flights(self) -> List[Dict[str, Any]]:
        """Extract flight details from the search results page."""
        flights = []
        
        # Wait for results to load
        print("Waiting for flight results to load...")
        time.sleep(5)
        
        # Scroll down to reveal flight sections
        self._scroll_to_load_flights()
        
        # Keep clicking "View more flights" until no more available
        self._load_all_flights()
        
        # Find all flight cards
        flight_cards = self._find_flight_cards()
        print(f"Found {len(flight_cards)} total flight cards")
        
        for idx, card in enumerate(flight_cards):
            try:
                # Scroll card into view
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                time.sleep(0.3)
                
                # Get basic info before expanding
                card_text = card.text[:200].replace('\n', ' | ')
                print(f"Processing card {idx+1}/{len(flight_cards)}: {card_text}")
                
                # Expand flight details by clicking down arrow
                expanded = self._expand_flight_card(card)
                time.sleep(0.5)
                
                # Parse the flight card (including expanded details)
                flight = self._parse_flight_card(card, expanded)
                
                if flight and flight.get("price"):
                    print(f"  -> Extracted: {flight.get('airline')} | {flight.get('departure', {}).get('time')} -> {flight.get('arrival', {}).get('time')} | {flight.get('price')} | {flight.get('stops')}")
                    flights.append(flight)
                
                # Collapse the card to avoid interference with next card
                if expanded:
                    self._collapse_flight_card(card)
                    time.sleep(0.2)
                    
            except Exception as e:
                print(f"  -> Error processing card {idx+1}: {e}")
                continue
        
        return flights

    def _scroll_to_load_flights(self):
        """Scroll down to load flight sections."""
        print("Scrolling to load flight sections...")
        
        # Scroll down in increments to load content
        for i in range(5):
            self.driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1)
        
        # Scroll back up a bit to ensure we can interact with elements
        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

    def _load_all_flights(self):
        """Click 'View more flights' buttons until no more are available."""
        max_clicks = 10
        clicks = 0
        
        while clicks < max_clicks:
            try:
                # Find 'View more flights' buttons
                view_more_selectors = [
                    "//button[contains(., 'View more flights')]",
                    "//div[contains(., 'View more flights') and @role='button']",
                    "//span[contains(., 'View more flights')]/parent::button",
                    "//button[contains(., 'More flights')]",
                    "//div[contains(@aria-label, 'View more flights')]",
                ]
                
                found_button = False
                for xpath in view_more_selectors:
                    buttons = self.driver.find_elements(By.XPATH, xpath)
                    for btn in buttons:
                        if btn.is_displayed():
                            # Scroll to button
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                            time.sleep(0.5)
                            self.driver.execute_script("arguments[0].click();", btn)
                            print("Clicked 'View more flights' button")
                            time.sleep(2)
                            found_button = True
                            break
                    if found_button:
                        break
                
                if not found_button:
                    break
                
                clicks += 1
                
            except Exception as e:
                print(f"No more 'View more flights' buttons: {e}")
                break
        
        if clicks > 0:
            print(f"Clicked 'View more flights' {clicks} time(s)")

    def _find_flight_cards(self) -> List[Any]:
        """Find all flight cards on the page."""
        cards = []
        
        # Strategy 1: Find cards within "Top departing flights" and "Other departing flights" sections
        section_selectors = [
            "//h2[contains(., 'Top departing flights')]/following-sibling::div//li",
            "//h2[contains(., 'Other departing flights')]/following-sibling::div//li",
            "//h2[contains(., 'Top departing flights')]/following-sibling::ul/li",
            "//h2[contains(., 'Other departing flights')]/following-sibling::ul/li",
            "//h3[contains(., 'Top departing flights')]/following-sibling::div//li",
            "//h3[contains(., 'Other departing flights')]/following-sibling::div//li",
            "//div[contains(., 'Top departing flights')]/following-sibling::div//li",
            "//div[contains(., 'Other departing flights')]/following-sibling::div//li",
        ]
        
        for xpath in section_selectors:
            try:
                found = self.driver.find_elements(By.XPATH, xpath)
                if found:
                    print(f"Found {len(found)} cards in section: {xpath}")
                    cards.extend(found)
            except Exception:
                continue
        
        # Strategy 2: If no section-based cards found, use generic selectors
        if not cards:
            generic_selectors = [
                "//li[@role='listitem']",
                "//div[@role='listitem']",
                "//div[contains(@class, 'pIav2d')]",
                "//div[contains(@class, 'JMc5Xc')]",
                "//div[contains(@class, 'yR1fYc')]",
                "//div[contains(@class, 'gQ6yfe')]",
                "//div[contains(@class, 'f9kS1')]",
                "//div[contains(@class, 'OgQvJf')]",
                "//div[contains(@class, 'V1iAHe')]",
                "//div[contains(@class, 'mz1N9c')]",
            ]
            
            for xpath in generic_selectors:
                try:
                    found = self.driver.find_elements(By.XPATH, xpath)
                    if found:
                        print(f"Found {len(found)} cards with selector: {xpath}")
                        cards = found
                        break
                except Exception:
                    continue
        
        # Strategy 3: Find by price elements (last resort)
        if not cards:
            print("Trying price-based card detection...")
            price_elements = self.driver.find_elements(By.XPATH, 
                "//*[contains(text(), '$') or contains(text(), '€') or contains(text(), '£')]"
            )
            seen = set()
            for pe in price_elements:
                try:
                    for level in range(3, 8):
                        ancestor = pe
                        for _ in range(level):
                            ancestor = ancestor.find_element(By.XPATH, "..")
                        aid = ancestor.id
                        if aid not in seen:
                            seen.add(aid)
                            cards.append(ancestor)
                            break
                except Exception:
                    continue
        
        # Remove duplicates based on element id
        unique_cards = []
        seen_ids = set()
        for card in cards:
            try:
                cid = card.id
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    unique_cards.append(card)
            except Exception:
                unique_cards.append(card)
        
        return unique_cards

    def _expand_flight_card(self, card) -> bool:
        """Click the down arrow to expand flight details. Returns True if expanded."""
        arrow_selectors = [
            ".//button[contains(@aria-label, 'Expand') or contains(@aria-label, 'expand')]",
            ".//button[contains(@aria-label, 'Details') or contains(@aria-label, 'details')]",
            ".//div[contains(@aria-label, 'Expand') or contains(@aria-label, 'expand')]",
            ".//span[contains(@aria-label, 'Expand') or contains(@aria-label, 'expand')]/parent::button",
            ".//button[.//span[contains(@class, 'arrow')] or .//div[contains(@class, 'arrow')]]",
            ".//div[contains(@role, 'button') and (.//span[contains(text(), '▼') or contains(text(), '▶') or contains(text(), '▼')])]",
            ".//button[.//*[name()='svg' or name()='path']]",
        ]
        
        for xpath in arrow_selectors:
            try:
                arrows = card.find_elements(By.XPATH, xpath)
                for arrow in arrows:
                    if arrow.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", arrow)
                        time.sleep(0.3)
                        self.driver.execute_script("arguments[0].click();", arrow)
                        time.sleep(0.8)
                        return True
            except Exception:
                continue
        
        return False

    def _collapse_flight_card(self, card):
        """Click the up arrow to collapse flight details."""
        try:
            collapse_selectors = [
                ".//button[contains(@aria-label, 'Collapse') or contains(@aria-label, 'collapse')]",
                ".//button[contains(@aria-label, 'Close') or contains(@aria-label, 'close')]",
                ".//div[contains(@aria-label, 'Collapse') or contains(@aria-label, 'collapse')]",
            ]
            for xpath in collapse_selectors:
                btns = card.find_elements(By.XPATH, xpath)
                for btn in btns:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(0.3)
                        return
        except Exception:
            pass

    def _parse_flight_card(self, card, expanded: bool = False) -> Dict[str, Any]:
        """Parse a single flight card element, including expanded details if available."""
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
            "booking_options": [],
            "details": {},
        }
        
        # Extract price
        price_patterns = [
            ".//span[contains(., '$') or contains(., '€') or contains(., '£')]",
            ".//div[contains(., '$') or contains(., '€') or contains(., '£')]",
            ".//*[contains(@aria-label, 'price') or contains(@aria-label, 'Price')]",
        ]
        for xpath in price_patterns:
            try:
                elements = card.find_elements(By.XPATH, xpath)
                for el in elements:
                    text = el.text
                    if text and any(c in text for c in ['$', '€', '£']):
                        flight["price"] = text.strip()
                        if "$" in text:
                            flight["currency"] = "USD"
                        elif "€" in text:
                            flight["currency"] = "EUR"
                        elif "£" in text:
                            flight["currency"] = "GBP"
                        break
                if flight["price"]:
                    break
            except Exception:
                continue
        
        # Extract airline
        airline_patterns = [
            ".//img[@alt]",
            ".//div[contains(@aria-label, 'airline') or contains(@aria-label, 'Airline')]",
            ".//span[contains(@aria-label, 'airline') or contains(@aria-label, 'Airline')]",
        ]
        for xpath in airline_patterns:
            try:
                el = card.find_element(By.XPATH, xpath)
                alt = el.get_attribute("alt")
                if alt:
                    flight["airline"] = alt.strip()
                    break
            except Exception:
                continue
        
        # Extract times
        time_elements = card.find_elements(By.XPATH, ".//span[contains(@aria-label, 'time') or contains(., ':')]")
        times = []
        for el in time_elements[:4]:
            text = el.text
            if text and re.match(r'\d{1,2}:\d{2}', text):
                times.append(text.strip())
        
        if len(times) >= 2:
            flight["departure"]["time"] = times[0]
            flight["arrival"]["time"] = times[1]
        
        # Extract duration
        duration_patterns = [
            ".//*[contains(., 'hr') or contains(., 'min')]",
            ".//*[contains(@aria-label, 'duration') or contains(@aria-label, 'Duration')]",
        ]
        for xpath in duration_patterns:
            try:
                elements = card.find_elements(By.XPATH, xpath)
                for el in elements:
                    text = el.text
                    if text and ("hr" in text or "min" in text):
                        if not re.match(r'^\d{1,2}:\d{2}$', text.strip()):
                            flight["duration"] = text.strip()
                            break
                if flight["duration"]:
                    break
            except Exception:
                continue
        
        # Extract stops
        stops_patterns = [
            ".//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'nonstop')]",
            ".//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'stop')]",
            ".//*[contains(@aria-label, 'stop') or contains(@aria-label, 'Stop')]",
        ]
        for xpath in stops_patterns:
            try:
                elements = card.find_elements(By.XPATH, xpath)
                for el in elements:
                    text = el.text
                    if text and ("stop" in text.lower() or "nonstop" in text.lower()):
                        flight["stops"] = text.strip()
                        break
                if flight["stops"]:
                    break
            except Exception:
                continue
        
        # Extract emissions
        try:
            emissions_el = card.find_element(By.XPATH, ".//*[contains(@aria-label, 'emissions') or contains(@aria-label, 'Emissions')]")
            flight["emissions"] = emissions_el.text
        except NoSuchElementException:
            pass
        
        # If expanded, extract additional details
        if expanded:
            flight["details"] = self._parse_expanded_details(card)
            flight["booking_options"] = self._parse_booking_options(card)
        
        return flight

    def _parse_expanded_details(self, card) -> Dict[str, Any]:
        """Parse expanded flight details section."""
        details = {
            "flight_segments": [],
            "aircraft": None,
            "amenities": [],
            "warnings": [],
            "additional_info": {},
        }
        
        # Extract flight segments (individual legs)
        segment_selectors = [
            ".//div[contains(@class, 'QMv22b')]",
            ".//div[contains(@class, 'yR1fYc')]",
            ".//div[contains(@class, 'gQ6yfe')]",
            ".//div[contains(@class, 'OgQvJf')]",
            ".//li",
        ]
        
        for xpath in segment_selectors:
            try:
                segments = card.find_elements(By.XPATH, xpath)
                for seg in segments:
                    text = seg.text
                    if text and any(keyword in text for keyword in ['Departure', 'Arrival', 'Layover', 'Terminal', 'Gate']):
                        details["flight_segments"].append(text.strip())
            except Exception:
                continue
        
        # Extract aircraft info
        try:
            aircraft_el = card.find_element(By.XPATH, ".//*[contains(., 'Aircraft') or contains(., 'aircraft')]")
            details["aircraft"] = aircraft_el.text
        except NoSuchElementException:
            pass
        
        # Extract amenities
        amenity_keywords = ['Wi-Fi', 'Entertainment', 'Power', 'Food', 'Seat', 'Legroom']
        for keyword in amenity_keywords:
            try:
                el = card.find_element(By.XPATH, f".//*[contains(., '{keyword}')]")
                details["amenities"].append(el.text.strip())
            except NoSuchElementException:
                pass
        
        # Extract warnings/notices
        try:
            warning_elements = card.find_elements(By.XPATH, ".//*[contains(@class, 'warning') or contains(@class, 'notice')]")
            for el in warning_elements:
                text = el.text.strip()
                if text:
                    details["warnings"].append(text)
        except Exception:
            pass
        
        return details

    def _parse_booking_options(self, card) -> List[Dict[str, Any]]:
        """Parse booking options from expanded flight card."""
        options = []
        
        booking_selectors = [
            ".//a[contains(@href, 'booking') or contains(@href, 'redirect')]",
            ".//button[contains(., 'Select') or contains(., 'Book')]",
            ".//div[contains(@role, 'button') and (contains(., 'Select') or contains(., 'Book'))]",
            ".//div[contains(@class, 'booking')]",
        ]
        
        for xpath in booking_selectors:
            try:
                elements = card.find_elements(By.XPATH, xpath)
                for el in elements:
                    if el.is_displayed():
                        option = {
                            "provider": None,
                            "price": None,
                            "url": None,
                        }
                        
                        text = el.text.strip()
                        if text:
                            option["provider"] = text
                        
                        href = el.get_attribute("href")
                        if href:
                            option["url"] = href
                        
                        # Try to find associated price
                        try:
                            parent = el.find_element(By.XPATH, "..")
                            price_els = parent.find_elements(By.XPATH, ".//*[contains(., '$') or contains(., '€') or contains(., '£')]")
                            for pel in price_els:
                                ptext = pel.text
                                if ptext and any(c in ptext for c in ['$', '€', '£']):
                                    option["price"] = ptext.strip()
                                    break
                        except Exception:
                            pass
                        
                        if option["provider"] or option["price"]:
                            options.append(option)
            except Exception:
                continue
        
        return options

    def to_json(self, flights: List[Dict[str, Any]], indent: int = 2) -> str:
        """Convert flights list to JSON string."""
        return json.dumps(flights, indent=indent, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape flight details from Google Flights (Selenium)",
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

    with GoogleFlightsScraper(headless=args.headless) as scraper:
        flights = scraper.search(
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
    main()
