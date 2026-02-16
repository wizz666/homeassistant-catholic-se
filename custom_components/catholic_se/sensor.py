"""Sensor platform for Catholic SE integration using Liturgical Calendar API."""
from __future__ import annotations
import asyncio
import datetime
from datetime import date, timedelta
import logging
import aiohttp
import re

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# API Endpoint for General Roman Calendar (Sweden specific calendar not available in public API directly yet, fallback to general)
API_URL = "http://calapi.inadiutorium.cz/api/v0/en/calendars/default/{}/{}/{}"

# Katolska Kyrkan Sverige readings URL base
KATOLSKA_BASE_URL = "https://www.katolskakyrkan.se/forsamlingsliv/ordo-och-veckans-lasningar"

# Boston Catholic Journal Roman Martyrology (for saint descriptions)
BCJ_MARTYROLOGY_URL = "http://www.boston-catholic-journal.com/1959-roman-martrylogy-in-english/roman-martyrology-1959-{}-in-english.htm"

# English month names for BCJ URLs
ENGLISH_MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]

# Ordinal suffixes for day numbers
def ordinal(n: int) -> str:
    """Return ordinal string for a number (1st, 2nd, 3rd, etc.)."""
    if 11 <= n <= 13:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

# Swedish weekday names (Monday=0, Sunday=6)
SWEDISH_WEEKDAYS = ["mandag", "tisdag", "onsdag", "torsdag", "fredag", "lordag", "sondag"]
SWEDISH_WEEKDAYS_DISPLAY = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]

# Swedish month names
SWEDISH_MONTHS = [
    "januari", "februari", "mars", "april", "maj", "juni",
    "juli", "augusti", "september", "oktober", "november", "december"
]

# Swedish translations for common liturgical terms
TRANSLATIONS = {
    "white": "vit",
    "red": "röd",
    "violet": "lila",
    "green": "grön",
    "rose": "rosa",
    "gold": "guld",
    "ordinary": "under året",
    "advent": "advent",
    "christmas": "jul",
    "lent": "fastan",
    "easter": "påsk",
    "memorial": "minnesdag",
    "feast": "fest",
    "solemnity": "högtid",
    "commemoration": "minne",
    "feria": "vardag",
    "joyful": "glädjerika",
    "sorrowful": "smärtorika",
    "glorious": "glorfyllda",
    "luminous": "ljusets"
}

def build_katolska_url(target_date: date) -> str:
    """Build the katolskakyrkan.se URL for a specific date."""
    week_number = target_date.isocalendar()[1]
    weekday_idx = target_date.weekday()
    day = target_date.day
    month_idx = target_date.month - 1

    weekday_name = SWEDISH_WEEKDAYS[weekday_idx]
    month_name = SWEDISH_MONTHS[month_idx]

    # URL format: /vecka-{week}/{weekday}-den-{day}-{month}
    url = f"{KATOLSKA_BASE_URL}/vecka-{week_number}/{weekday_name}-den-{day}-{month_name}"
    return url


def clean_html(html_text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not html_text:
        return ""
    # Remove script and style elements
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    # Replace <br> and </p> with newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n\n', text, flags=re.IGNORECASE)
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    # Decode HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&auml;', 'ä')
    text = text.replace('&aring;', 'å')
    text = text.replace('&ouml;', 'ö')
    text = text.replace('&Auml;', 'Ä')
    text = text.replace('&Aring;', 'Å')
    text = text.replace('&Ouml;', 'Ö')
    return text.strip()


def parse_martyrology_for_day(html: str, day: int, month_name: str) -> str:
    """Parse the Boston Catholic Journal martyrology page for a specific day.

    Returns the full text for that day's saints.
    """
    # The structure is: <h2>February 13th</h2> followed by content until next <hr> or <h2>
    # Build pattern to find the day's heading
    day_ordinal = ordinal(day)
    month_capitalized = month_name.capitalize()

    # Pattern: find the h2 with the day, then capture until next h2 or hr
    # Example: <h2>February 13th</h2>
    pattern = rf'<h2>\s*{month_capitalized}\s+{day_ordinal}\s*</h2>(.*?)(?=<h2>|<hr|$)'
    match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)

    if match:
        content = match.group(1)
        # Clean the HTML
        text = clean_html(content)
        # Remove the "This Day, the Xth Day of Month" intro line
        text = re.sub(rf'This Day,?\s+the\s+\w+\s+Day\s+of\s+{month_capitalized}\s*', '', text, flags=re.IGNORECASE)
        return text.strip()

    return ""


def parse_katolska_readings(html: str) -> dict:
    """Parse readings from katolskakyrkan.se page.

    The website structure uses simple <p> tags with <strong> headers:
    - <strong>Läsning</strong> followed by reference
    - <strong>Responsoriepsalm</strong> followed by reference
    - <strong>Halleluja</strong>
    - <strong>Evangelium</strong> followed by reference

    Note: Page may contain both 1994 and 2022 lectionary versions.
    We extract the 2022 version when available (appears second).
    """
    readings = {
        "first_reading": {"reference": "", "text": ""},
        "responsorial_psalm": {"reference": "", "text": "", "response": ""},
        "second_reading": {"reference": "", "text": ""},
        "gospel": {"reference": "", "text": ""},
        "title": "",
    }

    # Try to extract the title/date header
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
    if title_match:
        readings["title"] = clean_html(title_match.group(1))

    # Extract just the main content area
    main_match = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL | re.IGNORECASE)
    if main_match:
        html = main_match.group(1)

    # The website uses different labels depending on the day:
    # - Weekdays: "<strong>Läsning</strong>" (often with 1994 + 2022 versions)
    # - Sundays/Solemnities: "<strong>Första läsningen</strong>"
    # - Major feasts on weekdays: may use either format, possibly with 1994/2022 versions
    # We check for both patterns and prefer 2022 version when duplicates exist

    # Check if this is a page with 1994/2022 lectionary versions
    has_lectionary_versions = "Ur Lektionarium" in html

    # Pattern 1: "Första läsningen" (Sundays/Solemnities/Major Feasts)
    first_reading_pattern = r'<p>\s*<strong>Första läsningen</strong>\s*([^<]+)</p>(.*?)(?=<p>\s*<strong>(?:Responsoriepsalm|Halleluja|Evangelium|Andra läsningen|Första läsningen)</strong>|<p>\s*<em>Ur Lektionarium|$)'
    first_reading_matches = list(re.finditer(first_reading_pattern, html, re.DOTALL | re.IGNORECASE))

    # Pattern 2: "Läsning" (Weekdays)
    reading_pattern = r'<p>\s*<strong>Läsning</strong>\s*([^<]+)</p>(.*?)(?=<p>\s*<strong>(?:Responsoriepsalm|Halleluja|Evangelium|Läsning)</strong>|<p>\s*<em>Ur Lektionarium|$)'
    reading_matches = list(re.finditer(reading_pattern, html, re.DOTALL | re.IGNORECASE))

    # Use "Första läsningen" if found, otherwise use "Läsning"
    if first_reading_matches:
        # May have 1994 + 2022 versions on weekday feasts
        if has_lectionary_versions and len(first_reading_matches) > 1:
            match = first_reading_matches[-1]  # Use 2022 version
        else:
            match = first_reading_matches[0]
        reference = clean_html(match.group(1)).strip()
        text = clean_html(match.group(2)).strip()
        readings["first_reading"]["reference"] = reference
        readings["first_reading"]["text"] = text
    elif reading_matches:
        # Weekday format - may have 1994 + 2022 versions
        if has_lectionary_versions and len(reading_matches) > 1:
            match = reading_matches[-1]  # Use 2022 version
        else:
            match = reading_matches[0]
        reference = clean_html(match.group(1)).strip()
        text = clean_html(match.group(2)).strip()
        readings["first_reading"]["reference"] = reference
        readings["first_reading"]["text"] = text

    # Responsorial Psalm
    # Find all psalm headers - on some pages (feast days) there are separate 1992/2022 versions
    psalm_header_pattern = r'<p>\s*<strong>Responsoriepsalm</strong>\s*([^<]+)</p>'
    psalm_header_matches = list(re.finditer(psalm_header_pattern, html, re.IGNORECASE))

    if psalm_header_matches:
        # If page has lectionary versions and multiple psalm headers, use the last one (2022)
        if has_lectionary_versions and len(psalm_header_matches) > 1:
            psalm_header_match = psalm_header_matches[-1]
        else:
            psalm_header_match = psalm_header_matches[0]

        reference = clean_html(psalm_header_match.group(1)).strip()
        readings["responsorial_psalm"]["reference"] = reference

        # Find where the psalm header is in the HTML
        psalm_start = psalm_header_match.end()

        # Find where the psalm section ends
        # During Lent: "Lovsång" or "Vers före evangeliet" instead of "Halleluja"
        # Also stop at next section header (Läsning, Evangelium, etc.)
        psalm_end_pattern = r'<p>\s*<strong>(?:Halleluja|Lovsång|Vers före evangeliet|Evangelium|Läsning)</strong>'
        psalm_end_match = re.search(psalm_end_pattern, html[psalm_start:], re.IGNORECASE)
        if psalm_end_match:
            psalm_section = html[psalm_start:psalm_start + psalm_end_match.start()]
        else:
            psalm_section = html[psalm_start:]

        # For the selected psalm, check if content is within a lectionary section
        # (This handles cases where psalm text appears after a 2022 marker within the section)
        if "Ur Lektionarium" in psalm_section and "2022" in psalm_section:
            marker_2022 = re.search(r'<p>\s*<em>Ur Lektionarium[^<]*2022[^<]*</em>\s*</p>', psalm_section, re.IGNORECASE)
            if marker_2022:
                content = psalm_section[marker_2022.end():]
            else:
                content = psalm_section
        else:
            content = psalm_section

        # Look for the response line (R. ...) - first one in the content
        resp_match = re.search(r'<p>\s*R\.\s*(.+?)</p>', content, re.IGNORECASE)
        if resp_match:
            readings["responsorial_psalm"]["response"] = clean_html(resp_match.group(1)).strip()

        readings["responsorial_psalm"]["text"] = clean_html(content).strip()

    # Second Reading (Sundays/Solemnities/Major Feasts) - "Andra läsningen"
    # May have 1994 + 2022 versions on weekday feasts
    second_pattern = r'<p>\s*<strong>(?:Andra\s+läsningen|2:a\s+läsningen)</strong>\s*([^<]+)</p>(.*?)(?=<p>\s*<strong>(?:Halleluja|Evangelium|Andra\s+läsningen|2:a\s+läsningen)</strong>|<p>\s*<em>Ur Lektionarium|$)'
    second_matches = list(re.finditer(second_pattern, html, re.DOTALL | re.IGNORECASE))

    if second_matches:
        # Use same logic as other readings: last match if lectionary versions exist
        if has_lectionary_versions and len(second_matches) > 1:
            match = second_matches[-1]
        else:
            match = second_matches[0]
        reference = clean_html(match.group(1)).strip()
        text = clean_html(match.group(2)).strip()
        readings["second_reading"]["reference"] = reference
        readings["second_reading"]["text"] = text

    # Gospel - "Evangelium"
    # On weekdays: two versions (1994 + 2022) - we want the last one (2022)
    # On Sundays: may have full + short version - we want the first one (full)
    # Strategy: check if page has "Ur Lektionarium" (weekday format) to decide
    gospel_pattern = r'<p>\s*<strong>Evangelium</strong>\s*([^<]+)</p>(.*?)(?=<p>eller|<p>\s*<strong>Evangelium</strong>|<div|<footer|<aside|$)'
    gospel_matches = list(re.finditer(gospel_pattern, html, re.DOTALL | re.IGNORECASE))

    if gospel_matches:
        # Check if this is a weekday page with 1994/2022 versions
        has_lectionary_versions = "Ur Lektionarium" in html

        if has_lectionary_versions and len(gospel_matches) > 1:
            # Weekday: use the last match (2022 version)
            match = gospel_matches[-1]
        else:
            # Sunday or single version: use the first match (full version)
            match = gospel_matches[0]

        reference = clean_html(match.group(1)).strip()
        text = clean_html(match.group(2)).strip()
        readings["gospel"]["reference"] = reference
        readings["gospel"]["text"] = text

    return readings


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    session = async_get_clientsession(hass)
    coordinator = LiturgyCoordinator(hass, session)
    readings_coordinator = ReadingsCoordinator(hass, session)
    martyrology_coordinator = MartyrologyCoordinator(hass, session)

    # Fetch initial data
    await coordinator.async_refresh()
    await readings_coordinator.async_refresh()
    await martyrology_coordinator.async_refresh()

    async_add_entities([
        LiturgicalDaySensor(coordinator),
        SaintOfTheDaySensor(coordinator, martyrology_coordinator),
        SwedishFirstReadingSensor(readings_coordinator),
        SwedishPsalmSensor(readings_coordinator),
        SwedishSecondReadingSensor(readings_coordinator),
        SwedishGospelSensor(readings_coordinator),
        ReadingsStatusSensor(readings_coordinator),
        RosaryMysteriesSensor(coordinator),
        CatholicAbstinenceSensor(coordinator)
    ], update_before_add=True)


class LiturgyCoordinator:
    """Manages fetching data from the API."""
    def __init__(self, hass, session):
        self.hass = hass
        self.session = session
        self.data = None
        self.last_update = None

    async def async_refresh(self):
        """Fetch data for today."""
        today = date.today()
        # Avoid fetching if we already have today's data (simple cache)
        if self.data and self.last_update == today:
            return

        year = today.year
        month = today.month
        day = today.day
        
        url = API_URL.format(year, month, day)
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    self.data = await response.json()
                    self.last_update = today
                    _LOGGER.debug("Fetched liturgy data: %s", self.data)
                else:
                    _LOGGER.error("Error fetching liturgy data: %s", response.status)
        except Exception as e:
            _LOGGER.error("Exception fetching liturgy data: %s", e)

    def get_season(self):
        if not self.data: return "Okänd"
        season = self.data.get("season", "ordinary")
        return TRANSLATIONS.get(season, season).capitalize()

    def get_color(self):
        if not self.data: return "grön"
        # API returns list of celebrations, usually first one dictates color
        celebrations = self.data.get("celebrations", [])
        if celebrations:
            color = celebrations[0].get("colour", "green")
            return TRANSLATIONS.get(color, color)
        season = self.data.get("season", "ordinary")
        # Fallback based on season defaults
        if season == "lent" or season == "advent": return "lila"
        if season == "easter" or season == "christmas": return "vit"
        return "grön"

    def get_primary_celebration(self):
        if not self.data: return None
        celebrations = self.data.get("celebrations", [])
        if not celebrations: return None

        # Determine highest ranking celebration
        # API usually sorts by rank, so taking the first one is often correct
        primary = celebrations[0]

        # Translate rank
        rank = primary.get("rank", "")
        rank_translated = TRANSLATIONS.get(rank, rank)

        return {
            "name": primary.get("title", ""),
            "rank": rank_translated,
            "raw_rank": rank, # Keep English for logic
            "color": TRANSLATIONS.get(primary.get("colour", ""), "grön")
        }

    def get_all_celebrations(self):
        """Get all celebrations for the day, not just the primary one."""
        if not self.data:
            return []
        celebrations = self.data.get("celebrations", [])
        result = []
        for c in celebrations:
            rank = c.get("rank", "")
            result.append({
                "name": c.get("title", ""),
                "rank": TRANSLATIONS.get(rank, rank),
                "raw_rank": rank,
                "color": TRANSLATIONS.get(c.get("colour", ""), "grön")
            })
        return result


class ReadingsCoordinator:
    """Manages fetching Swedish readings from katolskakyrkan.se."""

    def __init__(self, hass, session):
        self.hass = hass
        self.session = session
        self.data = None
        self.last_update = None
        self.error = None
        self.url = None

    async def _find_day_url_from_week_page(self, target_date: date) -> str | None:
        """Fetch week page and extract the actual day URL from navigation.

        This handles the website's inconsistent URL spelling (e.g., 'feburari' vs 'februari').
        """
        week_number = target_date.isocalendar()[1]
        week_url = f"{KATOLSKA_BASE_URL}/vecka-{week_number}"

        try:
            async with self.session.get(week_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    _LOGGER.debug("Week page not found: %s", week_url)
                    return None

                html = await response.text()

                # Find the day link in the navigation
                # Links look like: /forsamlingsliv/ordo-och-veckans-lasningar/vecka-7/fredag-den-13-feburari
                weekday_name = SWEDISH_WEEKDAYS[target_date.weekday()]
                day = target_date.day

                # Pattern to find the day URL - look for weekday-den-{day} pattern
                # This handles both correct and misspelled month names
                pattern = rf'href="([^"]*/{weekday_name}-den-{day}-[^"]+)"'
                match = re.search(pattern, html, re.IGNORECASE)

                if match:
                    day_path = match.group(1)
                    # Make it a full URL if it's a relative path
                    if day_path.startswith('/'):
                        return f"https://www.katolskakyrkan.se{day_path}"
                    return day_path

                _LOGGER.debug("Day URL not found in week page for %s %s", weekday_name, day)
                return None

        except Exception as e:
            _LOGGER.debug("Error fetching week page: %s", e)
            return None

    async def async_refresh(self):
        """Fetch readings for today from katolskakyrkan.se."""
        today = date.today()
        # Avoid fetching if we already have today's data
        if self.data and self.last_update == today:
            return

        # First, try to find the actual URL from the week navigation page
        # This handles typos in URLs on the website
        self.url = await self._find_day_url_from_week_page(today)

        # Fallback to the calculated URL if we couldn't find it
        if not self.url:
            self.url = build_katolska_url(today)

        _LOGGER.debug("Fetching Swedish readings from: %s", self.url)

        try:
            async with self.session.get(self.url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    self.data = parse_katolska_readings(html)
                    self.data["url"] = self.url
                    self.data["date"] = today.isoformat()
                    self.last_update = today
                    self.error = None
                    _LOGGER.debug("Parsed Swedish readings: %s", self.data.get("title", ""))
                elif response.status == 404:
                    # Page not found - might be a date with different URL format
                    self.error = f"Sidan hittades inte (404) - läsningar kanske inte är publicerade än"
                    _LOGGER.warning("Swedish readings page not found: %s", self.url)
                else:
                    self.error = f"HTTP {response.status}"
                    _LOGGER.error("Error fetching Swedish readings: %s", response.status)
        except asyncio.TimeoutError:
            self.error = "Timeout vid hämtning"
            _LOGGER.error("Timeout fetching Swedish readings from %s", self.url)
        except Exception as e:
            self.error = str(e)
            _LOGGER.error("Exception fetching Swedish readings: %s", e)

    def get_first_reading(self):
        if not self.data:
            return {"reference": "", "text": ""}
        return self.data.get("first_reading", {"reference": "", "text": ""})

    def get_psalm(self):
        if not self.data:
            return {"reference": "", "text": "", "response": ""}
        return self.data.get("responsorial_psalm", {"reference": "", "text": "", "response": ""})

    def get_second_reading(self):
        if not self.data:
            return {"reference": "", "text": ""}
        return self.data.get("second_reading", {"reference": "", "text": ""})

    def get_gospel(self):
        if not self.data:
            return {"reference": "", "text": ""}
        return self.data.get("gospel", {"reference": "", "text": ""})


class MartyrologyCoordinator:
    """Manages fetching saint descriptions from Boston Catholic Journal."""

    def __init__(self, hass, session):
        self.hass = hass
        self.session = session
        self.data = None  # Will store {month: html_content}
        self.last_update = None
        self.text = ""
        self.error = None

    async def async_refresh(self):
        """Fetch martyrology for today's date."""
        today = date.today()
        # Avoid fetching if we already have today's data
        if self.text and self.last_update == today:
            return

        month_idx = today.month - 1
        month_name = ENGLISH_MONTHS[month_idx]
        url = BCJ_MARTYROLOGY_URL.format(month_name)

        _LOGGER.debug("Fetching martyrology from: %s", url)

        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    self.text = parse_martyrology_for_day(html, today.day, month_name)
                    self.last_update = today
                    self.error = None
                    _LOGGER.debug("Parsed martyrology text length: %d", len(self.text))
                else:
                    self.error = f"HTTP {response.status}"
                    _LOGGER.error("Error fetching martyrology: %s", response.status)
        except asyncio.TimeoutError:
            self.error = "Timeout"
            _LOGGER.error("Timeout fetching martyrology from %s", url)
        except Exception as e:
            self.error = str(e)
            _LOGGER.error("Exception fetching martyrology: %s", e)

    def get_description(self) -> str:
        """Get the martyrology text for today."""
        return self.text or ""


class LiturgicalDaySensor(SensorEntity):
    """Sensor for the current liturgical day / season."""
    
    _attr_name = "Liturgisk Kalender"
    _attr_unique_id = "catholic_se_liturgy"
    _attr_icon = "mdi:church"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        await self.coordinator.async_refresh()
        
        self._attr_native_value = self.coordinator.get_season()
        
        color = self.coordinator.get_color()
        celebration = self.coordinator.get_primary_celebration()
        
        self._attr_extra_state_attributes = {
            "liturgical_color": color,
            "season": self.coordinator.get_season(),
            "primary_celebration": celebration["name"] if celebration else None,
            "rank": celebration["rank"] if celebration else None
        }

class SaintOfTheDaySensor(SensorEntity):
    """Sensor for the Saint of the Day with description from Roman Martyrology."""

    _attr_name = "Dagens Helgon"
    _attr_unique_id = "catholic_se_saint"
    _attr_icon = "mdi:account-star"

    def __init__(self, coordinator, martyrology_coordinator):
        self.coordinator = coordinator
        self.martyrology = martyrology_coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
        await self.martyrology.async_refresh()

        all_celebrations = self.coordinator.get_all_celebrations()

        # Filter out feria (ordinary weekday) entries - these are not saint days
        saints = [c for c in all_celebrations if "feria" not in c.get("raw_rank", "feria").lower()]

        if not saints:
            # No saints today
            self._attr_native_value = "Inget helgon för denna dagen"
            self._attr_extra_state_attributes = {
                "type": "Vardag (Feria)",
                "color": self.coordinator.get_color(),
                "description": "",
                "other_saints": [],
                "martyrology_text": self.martyrology.get_description(),
            }
        else:
            # We have at least one saint
            primary = saints[0]
            other_saints = [s["name"] for s in saints[1:]] if len(saints) > 1 else []

            self._attr_native_value = primary["name"]
            self._attr_extra_state_attributes = {
                "type": primary["rank"],
                "color": primary["color"],
                "description": self.martyrology.get_description(),
                "description_preview": truncate_text(self.martyrology.get_description(), 500),
                "other_saints": other_saints,
                "total_saints": len(saints),
            }

class RosaryMysteriesSensor(SensorEntity):
    """Sensor for Today's Rosary Mysteries."""
    
    _attr_name = "Dagens Rosenkransmysterier"
    _attr_unique_id = "catholic_se_rosary"
    _attr_icon = "mdi:rosary"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        # No API call needed strictly, but good to ensure date consistency
        weekday = date.today().weekday() # Mon=0, Sun=6
        
        # Standard weekly rotation
        # Mon (0): Joyful
        # Tue (1): Sorrowful
        # Wed (2): Glorious
        # Thu (3): Luminous
        # Fri (4): Sorrowful
        # Sat (5): Joyful
        # Sun (6): Glorious (usually)
        
        mysteries = {
            0: "glädjerika",
            1: "smärtorika",
            2: "glorfyllda",
            3: "ljusets",
            4: "smärtorika",
            5: "glädjerika",
            6: "glorfyllda"
        }
        
        # Liturgical adjustments for Sundays could be added here (e.g. Advent/Lent)
        # For now, sticking to the standard weekly cycle commonly used
        
        self._attr_native_value = mysteries[weekday].capitalize()
        self._attr_extra_state_attributes = {
            "rotation": "Standard Weekly"
        }

class CatholicAbstinenceSensor(SensorEntity):
    """Sensor for Fasting and Abstinence."""
    
    _attr_name = "Fasta & Abstinens"
    _attr_unique_id = "catholic_se_abstinence"
    _attr_icon = "mdi:food-off"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
        today = date.today()
        weekday = today.weekday() # Fri=4
        
        season = "ordinary"
        if self.coordinator.data:
            season = self.coordinator.data.get("season", "ordinary")
            
        celebration = self.coordinator.get_primary_celebration()
        title = celebration["name"].lower() if celebration else ""
        
        is_lent = season == "lent"
        is_friday = weekday == 4
        is_ash_wednesday = "ash wednesday" in title
        is_good_friday = "good friday" in title
        
        state = "Ingen"
        desc = "Ingen särskild botgöring idag."
        
        if is_ash_wednesday or is_good_friday:
            state = "Fasta & Abstinens"
            desc = "Idag gäller både fasta (begränsat matintag) och abstinens (inget kött)."
        elif is_lent and is_friday:
            state = "Abstinens"
            desc = "Idag avstår vi från kött (Långfredagsbot)."
        elif is_friday:
            state = "Fredagsbot"
            desc = "Fredag är en botdag. Avstå från kött eller gör en annan god gärning."
            
        self._attr_native_value = state
        self._attr_extra_state_attributes = {
            "beskrivning": desc,
            "is_friday": is_friday,
            "is_lent": is_lent
        }

def truncate_text(text: str, max_length: int = 255) -> str:
    """Truncate text to fit in sensor state (max 255 chars)."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."


class SwedishFirstReadingSensor(SensorEntity):
    """Sensor for the First Reading in Swedish."""

    _attr_name = "Första Läsningen"
    _attr_unique_id = "catholic_se_first_reading"
    _attr_icon = "mdi:book-open-variant"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
        reading = self.coordinator.get_first_reading()

        reference = reading.get("reference", "")
        text = reading.get("text", "")

        self._attr_native_value = truncate_text(reference or "Första läsningen")
        self._attr_extra_state_attributes = {
            "reference": reference,
            "text": text,
            "text_preview": truncate_text(text, 500),
            "source_url": self.coordinator.url,
        }


class SwedishPsalmSensor(SensorEntity):
    """Sensor for the Responsorial Psalm in Swedish."""

    _attr_name = "Responsoriepsalm"
    _attr_unique_id = "catholic_se_psalm"
    _attr_icon = "mdi:music-note"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
        reading = self.coordinator.get_psalm()

        reference = reading.get("reference", "")
        text = reading.get("text", "")
        response = reading.get("response", "")

        self._attr_native_value = truncate_text(reference or "Responsoriepsalm")
        self._attr_extra_state_attributes = {
            "reference": reference,
            "text": text,
            "text_preview": truncate_text(text, 500),
            "response": response,
            "source_url": self.coordinator.url,
        }


class SwedishSecondReadingSensor(SensorEntity):
    """Sensor for the Second Reading in Swedish (Sundays/Solemnities)."""

    _attr_name = "Andra Läsningen"
    _attr_unique_id = "catholic_se_second_reading"
    _attr_icon = "mdi:book-open-variant"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
        reading = self.coordinator.get_second_reading()

        reference = reading.get("reference", "")
        text = reading.get("text", "")
        has_reading = bool(text)

        self._attr_native_value = truncate_text(
            reference if has_reading else "Ingen andra läsning idag"
        )
        self._attr_extra_state_attributes = {
            "reference": reference,
            "text": text,
            "text_preview": truncate_text(text, 500) if has_reading else "",
            "available": has_reading,
            "source_url": self.coordinator.url,
        }


class SwedishGospelSensor(SensorEntity):
    """Sensor for the Gospel in Swedish."""

    _attr_name = "Evangelium"
    _attr_unique_id = "catholic_se_gospel"
    _attr_icon = "mdi:book-cross"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()
        reading = self.coordinator.get_gospel()

        reference = reading.get("reference", "")
        text = reading.get("text", "")

        self._attr_native_value = truncate_text(reference or "Evangelium")
        self._attr_extra_state_attributes = {
            "reference": reference,
            "text": text,
            "text_preview": truncate_text(text, 500),
            "source_url": self.coordinator.url,
        }


class ReadingsStatusSensor(SensorEntity):
    """Sensor showing the status of Swedish readings fetch."""

    _attr_name = "Läsningar Status"
    _attr_unique_id = "catholic_se_readings_status"
    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self) -> None:
        await self.coordinator.async_refresh()

        if self.coordinator.error:
            self._attr_native_value = "Fel"
            self._attr_icon = "mdi:alert-circle"
        elif self.coordinator.data:
            self._attr_native_value = "OK"
            self._attr_icon = "mdi:check-circle"
        else:
            self._attr_native_value = "Väntar"
            self._attr_icon = "mdi:clock-outline"

        self._attr_extra_state_attributes = {
            "last_update": self.coordinator.last_update.isoformat() if self.coordinator.last_update else None,
            "url": self.coordinator.url,
            "error": self.coordinator.error,
            "title": self.coordinator.data.get("title", "") if self.coordinator.data else "",
        }
