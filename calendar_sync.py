#!/usr/bin/env python3
"""
Calendar Sync Script

Synchronizes events from a source calendar (HTTP iCalendar) to a destination calendar (CalDAV),
normalizing event titles in the process.
"""

import argparse
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, time, date

import caldav
import pytz
import requests
from dotenv import load_dotenv
from icalendar import Calendar, Event

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("calendar_sync")

# Load environment variables from .env file
load_dotenv()


def parse_arguments():
    """Parse command line arguments, overriding environment variables if provided."""
    parser = argparse.ArgumentParser(
        description="Synchronize events from source to destination calendar."
    )

    parser.add_argument(
        "--source-url", help="HTTPS URL for source calendar (iCalendar format)"
    )
    parser.add_argument("--dest-url", help="CalDAV URL for destination calendar")
    parser.add_argument("--dest-username", help="Username for destination calendar")
    parser.add_argument("--dest-password", help="Password for destination calendar")
    parser.add_argument(
        "--dest-calendar", help="Name of the destination calendar to use"
    )
    parser.add_argument("--title", help="Normalized title for synced events")
    parser.add_argument(
        "--days", type=int, default=30, help="Number of days to look ahead for events"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--timezone", help="Time zone for dates (e.g., America/New_York)"
    )

    return parser.parse_args()


def get_config():
    """Get configuration from environment variables and command line arguments."""
    args = parse_arguments()

    # Set logging level based on verbose flag
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    config = {
        "source_url": args.source_url or os.getenv("SOURCE_CALENDAR_URL"),
        "dest_url": args.dest_url or os.getenv("DEST_CALDAV_URL"),
        "dest_username": args.dest_username or os.getenv("DEST_CALDAV_USERNAME"),
        "dest_password": args.dest_password or os.getenv("DEST_CALDAV_PASSWORD"),
        "dest_calendar_name": args.dest_calendar or os.getenv("DEST_CALENDAR_NAME"),
        "normalized_title": args.title or os.getenv("NORMALIZED_EVENT_TITLE"),
        "days_ahead": args.days,
        "timezone": args.timezone or os.getenv("TIMEZONE", "UTC"),
    }

    # Validate required config
    if not config["source_url"]:
        logger.error("Source calendar URL is required")
        sys.exit(1)
    if not config["dest_url"]:
        logger.error("Destination CalDAV URL is required")
        sys.exit(1)
    if not config["dest_username"] or not config["dest_password"]:
        logger.error("Destination calendar credentials are required")
        sys.exit(1)

    # Validate timezone
    try:
        config["timezone"] = pytz.timezone(config["timezone"])
    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Unknown timezone: {config['timezone']}")
        logger.info("Using UTC timezone instead")
        config["timezone"] = pytz.UTC

    return config


def get_calendar_by_name(client, calendar_name=None):
    """Get a CalDAV calendar by name, or the default calendar if name is not provided."""
    try:
        principal = client.principal()
        calendars = principal.calendars()

        if not calendars:
            logger.error("No calendars found")
            return None

        if calendar_name:
            for calendar in calendars:
                if calendar.name == calendar_name:
                    logger.debug(f"Found calendar: {calendar_name}")
                    return calendar

            logger.warning(f"Calendar '{calendar_name}' not found, using default")

        # If no calendar name specified or not found, use the first calendar
        logger.debug(f"Using default calendar: {calendars[0].name}")
        return calendars[0]

    except Exception as e:
        logger.error(f"Error accessing calendars: {e}")
        return None


def connect_to_dest_calendar(url, username, password, calendar_name=None):
    """Connect to a CalDAV destination calendar."""
    try:
        client = caldav.DAVClient(url=url, username=username, password=password)
        return get_calendar_by_name(client, calendar_name)

    except Exception as e:
        logger.error(f"Error connecting to destination calendar: {e}")
        return None


def fetch_source_calendar(url):
    """Fetch iCalendar data from source URL."""
    try:
        logger.debug(f"Fetching source calendar from: {url}")
        response = requests.get(url)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses

        ical_data = response.text
        calendar = Calendar.from_ical(ical_data)

        logger.debug("Successfully fetched and parsed source calendar")
        return calendar

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching source calendar: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error parsing iCalendar data: {e}")
        return None


def get_source_events(calendar, start_date, end_date, timezone):
    """Extract events from iCalendar data within the specified date range."""
    events = []

    if not calendar:
        return events

    # Ensure dates have timezone information for comparison
    if not start_date.tzinfo:
        start_date = timezone.localize(start_date)

    if not end_date.tzinfo:
        end_date = timezone.localize(end_date)

    for component in calendar.walk():
        if component.name == "VEVENT":
            # Get start and end times
            dtstart = component.get("dtstart").dt

            # Handle all-day events (date only, no time)
            if isinstance(dtstart, datetime):
                if dtstart.tzinfo is None:
                    dtstart = timezone.localize(dtstart)
                event_start = dtstart
            else:
                # All-day event, convert to datetime at midnight
                event_start = timezone.localize(
                    datetime.combine(dtstart, datetime.min.time())
                )

            # Check if event has DTEND, if not, use DTSTART
            if component.get("dtend"):
                dtend = component.get("dtend").dt
                if isinstance(dtend, datetime):
                    if dtend.tzinfo is None:
                        dtend = timezone.localize(dtend)
                    event_end = dtend
                else:
                    # All-day event, convert to datetime at midnight
                    event_end = timezone.localize(
                        datetime.combine(dtend, datetime.min.time())
                    )
            else:
                # If no end time, assume same as start time
                event_end = event_start

            # Check if event is within our date range
            if (
                (start_date <= event_start <= end_date)
                or (start_date <= event_end <= end_date)
                or (event_start <= start_date and event_end >= end_date)
            ):
                events.append(component)

    logger.debug(f"Found {len(events)} events in source calendar within date range")
    return events


def get_dest_events(dest_calendar, normalized_title):
    """Get all events from destination calendar with the normalized title."""
    try:
        # Get all events from the destination calendar
        all_events = dest_calendar.events()

        # Filter for events with our normalized title and our special property
        synced_events = []
        for event in all_events:
            event_ical = event.icalendar_instance
            event_component = event_ical.subcomponents[0]

            # Check if this is our synced event by title and custom property
            if (event_component.get('SUMMARY', '') == normalized_title and
                    'X-SYNC-SOURCE-IDENTIFIER' in event_component):
                synced_events.append(event)

        return synced_events

    except Exception as e:
        logger.error(f"Error getting destination events: {e}")
        return []


def find_synced_event(synced_events, source_event_identifier):
    """Find the synced event in the destination calendar matching the source identifier."""
    for event in synced_events:
        event_ical = event.icalendar_instance
        event_component = event_ical.subcomponents[0]

        if event_component.get('X-SYNC-SOURCE-IDENTIFIER', '') == source_event_identifier:
            return event

    return None


def get_source_event_uid(event):
    """Extract the UID from a source event."""
    try:
        return event["UID"]
    except (KeyError, IndexError, AttributeError):
        # If no UID found, generate one
        return str(uuid.uuid4())


def event_details_changed(source_event, synced_event):
    """Check if the event details have changed between source and synced event."""
    synced_ical = synced_event.icalendar_instance
    synced_component = synced_ical.subcomponents[0]

    # Compare start times
    try:
        source_start = source_event["DTSTART"].dt
        synced_start = synced_component["DTSTART"].dt

        # Handle datetime vs date comparison
        if isinstance(source_start, datetime) and isinstance(synced_start, datetime):
            # If one has timezone and the other doesn't, normalize for comparison
            if (source_start.tzinfo is None) != (synced_start.tzinfo is None):
                if source_start.tzinfo is None:
                    source_start = pytz.UTC.localize(source_start)
                if synced_start.tzinfo is None:
                    synced_start = pytz.UTC.localize(synced_start)

            if source_start != synced_start:
                return True
        elif type(source_start) is not type(synced_start):
            return True
        elif source_start != synced_start:
            return True
    except (KeyError, IndexError):
        return True

    # Compare end times
    try:
        # Source event might not have DTEND
        if "DTEND" in source_event and "DTEND" in synced_component:
            source_end = source_event["DTEND"].dt
            synced_end = synced_component["DTEND"].dt

            # Handle datetime vs date comparison
            if isinstance(source_end, datetime) and isinstance(synced_end, datetime):
                # If one has timezone and the other doesn't, normalize for comparison
                if (source_end.tzinfo is None) != (synced_end.tzinfo is None):
                    if source_end.tzinfo is None:
                        source_end = pytz.UTC.localize(source_end)
                    if synced_end.tzinfo is None:
                        synced_end = pytz.UTC.localize(synced_end)

                if source_end != synced_end:
                    return True
            elif type(source_end) is not type(synced_end):
                return True
            elif source_end != synced_end:
                return True
        elif "DTEND" in source_event or "DTEND" in synced_component:
            return True
    except (KeyError, IndexError):
        return True

    # Compare location, description, etc.
    for key in ["LOCATION", "DESCRIPTION"]:
        if (
            (key in source_event and key not in synced_component)
            or (key not in source_event and key in synced_component)
            or (
                key in source_event
                and key in synced_component
                and source_event[key] != synced_component[key]
            )
        ):
            return True

    return False


def create_or_update_event(dest_calendar, source_event, normalized_title, existing_event=None):
    """Create a new event or update an existing event in the destination calendar."""
    try:
        # Generate a stable identifier for the source event
        source_identifier = generate_event_identifier(source_event)

        # Create a new calendar with a single event
        new_cal = Calendar()
        new_event = Event()

        # Copy over the essential properties
        for key in ['DTSTART', 'DTEND', 'LOCATION', 'DESCRIPTION']:
            if key in source_event:
                new_event[key] = source_event[key]

        # Set normalized title
        new_event['SUMMARY'] = normalized_title

        # Set UID - either keep existing or generate new
        if existing_event:
            existing_ical = existing_event.icalendar_instance
            existing_component = existing_ical.subcomponents[0]
            existing_uid = existing_component['UID']
            new_event['UID'] = existing_uid
        else:
            new_event['UID'] = str(uuid.uuid4())

        # Add our stable identifier property
        new_event['X-SYNC-SOURCE-IDENTIFIER'] = source_identifier

        # Add event to calendar
        new_cal.add_component(new_event)

        # Save to destination calendar
        if existing_event:
            existing_event.data = new_cal.to_ical()
            existing_event.save()
            logger.info(f"Updated existing event: {normalized_title} (Source Identifier: {source_identifier})")
        else:
            dest_calendar.save_event(new_cal.to_ical())
            logger.info(f"Created new event: {normalized_title} (Source Identifier: {source_identifier})")

        return True

    except Exception as e:
        logger.error(f"Error creating/updating event: {e}")
        return False


def sync_calendars(config):
    """Synchronize events from source to destination calendar."""
    # Connect to destination calendar (CalDAV)
    dest_calendar = connect_to_dest_calendar(
        config['dest_url'],
        config['dest_username'],
        config['dest_password'],
        config['dest_calendar_name']
    )

    if not dest_calendar:
        logger.error("Failed to connect to destination calendar")
        return False

    # Fetch source calendar (iCalendar over HTTPS)
    source_calendar = fetch_source_calendar(config['source_url'])

    if not source_calendar:
        logger.error("Failed to fetch source calendar")
        return False

    # Define date range for events
    now = datetime.now(config['timezone'])
    end_date = now + timedelta(days=config['days_ahead'])

    # Get events from source calendar within date range
    source_events = get_source_events(source_calendar, now, end_date, config['timezone'])
    logger.info(f"Found {len(source_events)} events in source calendar within date range")

    # Get all existing synced events from destination calendar
    dest_events = get_dest_events(dest_calendar, config['normalized_title'])
    logger.info(f"Found {len(dest_events)} existing synced events in destination calendar")

    # Keep track of processed source event identifiers
    processed_source_identifiers = set()

    # Process each source event
    for source_event in source_events:
        # Generate a stable identifier for the source event
        source_identifier = generate_event_identifier(source_event)

        # Add to our set of processed identifiers
        processed_source_identifiers.add(source_identifier)

        # Find matching event in destination calendar
        synced_event = find_synced_event(dest_events, source_identifier)

        if synced_event:
            # Check if event details have changed
            if event_details_changed(source_event, synced_event):
                create_or_update_event(dest_calendar, source_event,
                                       config['normalized_title'], synced_event)
            else:
                logger.debug(f"No changes needed for event with identifier: {source_identifier}")
        else:
            # Create new event
            create_or_update_event(dest_calendar, source_event, config['normalized_title'])

    # Remove destination events that no longer exist in source (except past events)
    removed_count = 0
    preserved_count = 0

    for dest_event in dest_events:
        event_ical = dest_event.icalendar_instance
        event_component = event_ical.subcomponents[0]
        source_identifier = event_component.get('X-SYNC-SOURCE-IDENTIFIER', '')

        if source_identifier and source_identifier not in processed_source_identifiers:
            # Check if this event is in the past
            if is_event_in_past(dest_event, now):
                # This is a past event, preserve it
                preserved_count += 1
                logger.debug(f"Preserved past event in destination calendar (Identifier: {source_identifier})")
            else:
                # This is a future/current event that no longer exists in source, delete it
                try:
                    dest_event.delete()
                    removed_count += 1
                    logger.info(f"Deleted event from destination calendar (Identifier: {source_identifier})")
                except Exception as e:
                    logger.error(f"Error deleting event with identifier {source_identifier}: {e}")

    if removed_count > 0:
        logger.info(f"Removed {removed_count} future events that no longer exist in source")

    if preserved_count > 0:
        logger.info(f"Preserved {preserved_count} past events for historical record")

    return True

def generate_event_identifier(event):
    """Generate a stable identifier for an event based on its properties.

    This creates a hash of the event's core properties (date, time, summary)
    that should remain consistent even if the event is deleted and recreated.
    """
    try:
        # Extract key properties
        dtstart = event.get('dtstart').dt

        # Handle all-day events vs. time-specific events
        if isinstance(dtstart, datetime):
            date_str = dtstart.strftime('%Y%m%d%H%M')
        else:
            date_str = dtstart.strftime('%Y%m%d')

        # Get duration or end time
        if event.get('dtend'):
            dtend = event.get('dtend').dt
            if isinstance(dtend, datetime):
                end_str = dtend.strftime('%Y%m%d%H%M')
            else:
                end_str = dtend.strftime('%Y%m%d')
        else:
            end_str = date_str

        # Get original summary (before normalization)
        summary = event.get('summary', '')

        # Get location if available
        location = event.get('location', '')

        # Combine properties to create a stable identifier
        # Include enough properties to make it unique, but not so many that minor changes break matching
        id_string = f"{date_str}_{end_str}_{summary}_{location}"

        # Create a hash of this string
        import hashlib
        return hashlib.md5(id_string.encode('utf-8')).hexdigest()

    except Exception as e:
        logger.error(f"Error generating event identifier: {e}")
        # Fall back to UID if available, or generate a random one
        try:
            return event.get('uid', str(uuid.uuid4()))
        except:
            return str(uuid.uuid4())


def is_event_in_past(event, current_time):
    """
    Determine if an event is in the past (has ended before current_time).

    Args:
        event: CalDAV event to check
        current_time: datetime object representing the current time (with timezone)

    Returns:
        bool: True if the event has ended and is in the past, False otherwise
    """
    try:
        event_ical = event.icalendar_instance
        event_component = event_ical.subcomponents[0]

        # Get end time of the event
        if 'DTEND' in event_component:
            dtend = event_component['DTEND'].dt
        elif 'DTSTART' in event_component:
            # If no end time, use start time (assuming it's a point-in-time event)
            dtend = event_component['DTSTART'].dt
        else:
            # If no time information, assume it's not in the past
            return False

        # If it's a date (all-day event) rather than datetime
        if isinstance(dtend, date) and not isinstance(dtend, datetime):
            # Convert to datetime at the end of day
            dtend = datetime.combine(dtend, time(23, 59, 59))

            # Add timezone if current_time has one
            if current_time.tzinfo:
                dtend = current_time.tzinfo.localize(dtend)

        # Compare end time with current time
        return dtend < current_time

    except Exception as e:
        logger.error(f"Error checking if event is in past: {e}")
        # If we can't determine, assume it's not in the past to be safe
        return False

def main():
    """Main function to run the calendar sync."""
    logger.info("Starting calendar synchronization...")
    config = get_config()
    success = sync_calendars(config)

    if success:
        logger.info("Calendar synchronization completed successfully")
    else:
        logger.error("Calendar synchronization failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
