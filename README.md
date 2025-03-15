# Calendar Sync Tool

A Python script that synchronizes calendar events from a source calendar to a destination calendar, normalizing event titles in the process.

## Background

This tool was created to solve a specific problem: keeping track of a work schedule that's shared via a frequently-updating calendar system.

I had already created a similar script, so this version became an experiment for an old-school python developer using AI tools.
I used the Claude Sonnet 3.7 thinking model via [OpenRouter.ai](openrouter.ai) and a self-hosted [OpenWebUI](https://github.com/open-webui/open-webui) to generate all the code and commit messages via chat. 
The solutions developed by Claude were very similar to what I originally wrote, but there were some Claude definitely had some good ideas that I missed in my original script. Total cost of this experiment was $0.09 (!!)

**The Problem:**
- Work scheduling software updates its calendar by deleting and recreating all events every hour
- Subscribing directly to this calendar results in constant notifications for "updated events"
- These notifications occur even when no actual schedule changes have happened
- This creates "notification fatigue" and makes it easy to miss real changes

**The Solution:**
- Create an intermediary calendar that only updates when actual changes occur
- Synchronize events from the source calendar to a personal destination calendar
- Normalize event titles (e.g., to "Tucker Works") for cleaner display
- Only modify events when actual schedule details change
- Delete events that no longer exist in the source calendar

This way, your phone only notifies you when a real change happens to the work schedule.

## Features

- One-way synchronization from a source calendar to a destination calendar
- Works with:
  - Source: HTTP-shared iCalendar (.ics) feeds
  - Destination: CalDAV calendars (including iCloud)
- Normalizes event titles to a configurable string (default: "Tucker Works")
- Preserves event details: dates, times, locations, descriptions
- Detects and updates events only when actual changes occur
- Cleans up events that no longer exist in the source calendar
- Configurable via .env file or command-line arguments
- Detailed logging

## Installation

### Requirements
- Python 3.11+
- UV package manager

### Steps

1. Clone this repository
```bash
git clone https://github.com/yourusername/calendar-sync.git
cd calendar-sync
```

2. Install dependencies using UV
```bash
uv sync
```

## Configuration

You can configure the tool through a `.env` file or command-line arguments.

### Environment Variables (.env file)

Create a `.env` file in the project directory with the following variables:

```
# Source calendar (iCalendar URL)
SOURCE_CALENDAR_URL=https://example.com/shared/calendar.ics

# Destination calendar (requires authentication)
DEST_CALDAV_URL=https://caldav.icloud.com/
DEST_CALDAV_USERNAME=your_apple_id@example.com
DEST_CALDAV_PASSWORD=your_app_specific_password
DEST_CALENDAR_NAME=Work Calendar

# Configuration
NORMALIZED_EVENT_TITLE=Tucker Works
TIMEZONE=America/New_York
```

### Command-Line Arguments

All environment variables can be overridden with command-line arguments:

```
--source-url URL         HTTPS URL for source calendar (iCalendar format)
--dest-url URL           CalDAV URL for destination calendar
--dest-username USER     Username for destination calendar
--dest-password PASS     Password for destination calendar
--dest-calendar NAME     Name of the destination calendar to use
--title TITLE            Normalized title for synced events
--days DAYS              Number of days to look ahead for events (default: 30)
--verbose, -v            Enable verbose logging
--timezone TZ            Time zone for dates (e.g., America/New_York)
```

## Usage

### Basic Usage

```bash
python calendar_sync.py
```

### Examples

Synchronize with verbose logging:
```bash
python calendar_sync.py --verbose
```

Use a custom event title:
```bash
python calendar_sync.py --title "Work Shift"
```

Sync events for the next 90 days:
```bash
python calendar_sync.py --days 90
```

## How It Works

1. The script fetches the source calendar via HTTPS
2. It connects to the destination calendar via CalDAV
3. For each event in the source calendar:
   - It checks if a corresponding event exists in the destination calendar
   - If it doesn't exist, it creates a new event
   - If it exists but has changed, it updates the event
   - If it exists and hasn't changed, it leaves it alone
4. It removes events from the destination calendar that no longer exist in the source

Events in the destination calendar are linked to their source events using a custom property, allowing the script to track which events correspond to each other across synchronizations.

## Testing

The project includes a comprehensive test suite built with pytest:

```bash
# Install testing dependencies
uv pip install pytest pytest-cov

# Run tests
python -m pytest

# Run tests with coverage report
python -m pytest --cov=calendar_sync
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome, but this was more of a one-off experiment than a full-fledged project. If you have suggestions or improvements, feel free to fork the repository and submit a pull request.