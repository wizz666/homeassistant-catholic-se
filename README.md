# Katolska Kyrkan Sverige - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-1.5.0-blue.svg)](https://github.com/wizz666/homeassistant-catholic-se)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support_this_project-F16061?logo=ko-fi&logoColor=white)](https://ko-fi.com/wizz666)

Custom Home Assistant integration providing Swedish Catholic liturgical data and daily Mass readings from [katolskakyrkan.se](https://www.katolskakyrkan.se/).

## Features

- **Liturgical Calendar** - Current season, liturgical colors, and celebrations
- **Swedish Mass Readings** - Daily readings scraped from Katolska Kyrkan Sverige
  - Första läsningen (First Reading)
  - Responsoriepsalm (Responsorial Psalm)
  - Andra läsningen (Second Reading - Sundays/Solemnities)
  - Evangelium (Gospel)
- **Saint of the Day** - From Roman Martyrology with descriptions
- **Rosary Mysteries** - Daily rotation based on tradition
- **Fasting & Abstinence** - Reminders for Fridays and Lent

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/wizz666/homeassistant-catholic-se` as **Integration**
4. Search for "Katolska Kyrkan Sverige" and install
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration**
7. Search for "Katolska Kyrkan Sverige"

### Manual Installation

1. Download the `custom_components/catholic_se` folder
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Add the integration via UI

## Sensors

### Liturgical Data

| Sensor | Entity ID | Description |
|--------|-----------|-------------|
| Liturgisk Kalender | `sensor.liturgisk_kalender` | Current liturgical season and celebration |
| Dagens Helgon | `sensor.dagens_helgon` | Saint of the day with description |
| Rosenkransmysterier | `sensor.dagens_rosenkransmysterier` | Today's rosary mysteries |
| Fasta & Abstinens | `sensor.fasta_abstinens` | Fasting/abstinence requirements |

### Swedish Readings

| Sensor | Entity ID | Key Attributes |
|--------|-----------|----------------|
| Första Läsningen | `sensor.forsta_lasningen` | `reference`, `text`, `text_preview` |
| Responsoriepsalm | `sensor.responsoriepsalm` | `reference`, `text`, `response` |
| Andra Läsningen | `sensor.andra_lasningen` | `reference`, `text`, `available` |
| Evangelium | `sensor.evangelium` | `reference`, `text`, `text_preview` |
| Läsningar Status | `sensor.lasningar_status` | `error`, `url`, `last_update` |

**Note:** Full text is stored in the `text` attribute (sensor state is limited to 255 characters). Use `text_preview` for card displays (truncated to 500 chars).

## Data Sources

1. **Liturgical Calendar** - [calapi.inadiutorium.cz](http://calapi.inadiutorium.cz/) for seasons, colors, celebrations
2. **Swedish Readings** - [katolskakyrkan.se](https://www.katolskakyrkan.se/forsamlingsliv/ordo-och-veckans-lasningar/) scraped daily
3. **Roman Martyrology** - [Boston Catholic Journal](https://www.romancatholicman.com/roman-martyrology/) for saint descriptions

## Lovelace Examples

### Full Readings Card

```yaml
type: markdown
title: Dagens Läsningar
content: |
  {% set status = states('sensor.lasningar_status') %}
  {% if status == 'OK' %}

  ### Första Läsningen
  **{{ state_attr('sensor.forsta_lasningen', 'reference') }}**
  {{ state_attr('sensor.forsta_lasningen', 'text_preview') }}

  ---

  ### Responsoriepsalm
  **{{ state_attr('sensor.responsoriepsalm', 'reference') }}**
  {% if state_attr('sensor.responsoriepsalm', 'response') %}
  *R: {{ state_attr('sensor.responsoriepsalm', 'response') }}*
  {% endif %}
  {{ state_attr('sensor.responsoriepsalm', 'text_preview') }}

  ---

  {% if state_attr('sensor.andra_lasningen', 'available') %}
  ### Andra Läsningen
  **{{ state_attr('sensor.andra_lasningen', 'reference') }}**
  {{ state_attr('sensor.andra_lasningen', 'text_preview') }}

  ---
  {% endif %}

  ### Evangelium
  **{{ state_attr('sensor.evangelium', 'reference') }}**
  {{ state_attr('sensor.evangelium', 'text_preview') }}

  {% else %}
  Kunde inte hämta läsningar: {{ state_attr('sensor.lasningar_status', 'error') }}
  {% endif %}
```

### Saint of the Day Card

```yaml
type: markdown
title: Dagens Helgon
content: |
  {% set saint = states('sensor.dagens_helgon') %}
  {% if saint != 'Inget helgon för denna dagen' %}
  ## {{ saint }}
  *{{ state_attr('sensor.dagens_helgon', 'type') }}*

  {{ state_attr('sensor.dagens_helgon', 'description_preview') }}

  {% set others = state_attr('sensor.dagens_helgon', 'other_saints') %}
  {% if others and others | length > 0 %}
  ---
  **Övriga helgon:** {{ others | join(', ') }}
  {% endif %}
  {% else %}
  *Ingen särskild helgondag idag.*
  {% endif %}
```

### Compact Entity Card

```yaml
type: entities
title: Katolska Läsningar
show_header_toggle: false
entities:
  - entity: sensor.liturgisk_kalender
    name: Liturgisk tid
  - entity: sensor.dagens_helgon
    name: Dagens helgon
  - type: divider
  - entity: sensor.forsta_lasningen
    name: Första läsningen
  - entity: sensor.responsoriepsalm
    name: Responsoriepsalm
  - entity: sensor.andra_lasningen
    name: Andra läsningen
  - entity: sensor.evangelium
    name: Evangelium
  - type: divider
  - entity: sensor.dagens_rosenkransmysterier
    name: Rosenkrans
  - entity: sensor.fasta_abstinens
    name: Fasta/Abstinens
```

## Technical Notes

- Readings are cached and fetched once per day
- Second reading (`sensor.andra_lasningen`) is only available on Sundays and Solemnities
- The integration handles both weekday and Sunday page formats from katolskakyrkan.se
- Supports both 1994 and 2022 lectionary versions (uses 2022 when available)
- Handles Lenten pages (uses "Lovsång" instead of "Halleluja")

## Changelog

### v1.5.0
- **Comprehensive Responsoriepsalm fix** for all page types
- Fixed psalm text missing on weekday pages (only reference showed before)
- Added support for Lenten pages: stops at "Lovsång" and "Vers före evangeliet"
- Handles feast days with multiple psalm headers (uses 2022 version)
- Works correctly for: weekdays, Sundays, Lent days, feast days on weekdays

### v1.4.1
- Enhanced support for major feasts on weekdays (Christmas, Easter, Epiphany, Ash Wednesday)
- All readings now handle 1994/2022 lectionary versions consistently
- Fixed "Andra läsningen" extraction when duplicates exist

### v1.4.0
- Fixed scraping for both weekdays AND Sundays
- Weekdays use `<strong>Läsning</strong>`, Sundays use `<strong>Första läsningen</strong>`
- Detects page format via "Ur Lektionarium" marker
- Added support for `<strong>Andra läsningen</strong>` on Sundays

### v1.3.0
- Enhanced **Dagens Helgon** sensor with Roman Martyrology
- Added full saint descriptions from Boston Catholic Journal
- Lists additional saints in `other_saints` attribute
- Added `description_preview` attribute for card displays

### v1.2.0
- Fixed scraping to match actual website structure
- Added week page lookup to handle URL typos on katolskakyrkan.se
- Extracts 2022 lectionary version when both 1994 and 2022 are present

### v1.1.0
- Added Swedish readings scraping from katolskakyrkan.se

### v1.0.0
- Initial release with liturgical calendar and static readings link

## Troubleshooting

### Readings not loading
1. Check `sensor.lasningar_status` for error messages
2. The website may not have published today's readings yet
3. Check Home Assistant logs: `grep "catholic_se" home-assistant.log`

### Psalm text missing
- Some feast days have complex page structures with multiple psalm headers
- The integration handles this by using the last (2022) version

## Support

If you find this integration useful, a coffee is always appreciated ☕

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/wizz666)

## License

MIT License

## Author

Created by [@wizz666](https://github.com/wizz666)
