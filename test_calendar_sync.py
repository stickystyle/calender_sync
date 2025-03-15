# test_calendar_sync.py

import pytz
import requests
from datetime import datetime, date
from icalendar import Calendar, Event
from unittest.mock import MagicMock, patch

# Import functions from the calendar sync script
from calendar_sync import (
    get_config,
    fetch_source_calendar,
    get_source_events,
    get_source_event_uid,
    find_synced_event,
    event_details_changed,
    create_or_update_event,
    connect_to_dest_calendar,
    sync_calendars,
    get_dest_events,
generate_event_identifier
)


# Configuration Tests
@patch("calendar_sync.load_dotenv")
@patch("calendar_sync.parse_arguments")
@patch("calendar_sync.os.getenv")
def test_get_config(mock_getenv, mock_parse_args, mock_load_dotenv):
    """Test config loading from environment variables"""
    # Setup
    mock_args = MagicMock()
    mock_args.source_url = None
    mock_args.dest_url = None
    mock_args.dest_username = None
    mock_args.dest_password = None
    mock_args.dest_calendar = None
    mock_args.title = None
    mock_args.days = 30
    mock_args.verbose = False
    mock_args.timezone = None

    mock_parse_args.return_value = mock_args

    mock_getenv.side_effect = lambda key, default=None: {
        "SOURCE_CALENDAR_URL": "https://source.com/cal.ics",
        "DEST_CALDAV_URL": "https://caldav.icloud.com/",
        "DEST_CALDAV_USERNAME": "apple_id@icloud.com",
        "DEST_CALDAV_PASSWORD": "app_specific_password",
        "DEST_CALENDAR_NAME": "Work Calendar",
        "NORMALIZED_EVENT_TITLE": "Tucker Works",
        "TIMEZONE": "America/New_York",
    }.get(key, default)

    # Call function
    config = get_config()

    # Assertions
    assert config["source_url"] == "https://source.com/cal.ics"
    assert config["dest_url"] == "https://caldav.icloud.com/"
    assert config["dest_username"] == "apple_id@icloud.com"
    assert config["dest_password"] == "app_specific_password"
    assert config["normalized_title"] == "Tucker Works"
    assert config["timezone"] == pytz.timezone("America/New_York")


@patch("calendar_sync.load_dotenv")
@patch("calendar_sync.parse_arguments")
def test_get_config_cli_override(mock_parse_args, mock_load_dotenv):
    """Test command line arguments override env variables"""
    # Setup mock CLI arguments
    mock_args = MagicMock()
    mock_args.source_url = "https://cli-source.com/cal.ics"
    mock_args.dest_url = "https://cli-dest.com/"
    mock_args.dest_username = "cli-user"
    mock_args.dest_password = "cli-pass"
    mock_args.dest_calendar = "CLI Calendar"
    mock_args.title = "CLI Title"
    mock_args.days = 14
    mock_args.verbose = True
    mock_args.timezone = "Europe/London"

    mock_parse_args.return_value = mock_args

    # Call function
    config = get_config()

    # Assertions
    assert config["source_url"] == "https://cli-source.com/cal.ics"
    assert config["dest_url"] == "https://cli-dest.com/"
    assert config["normalized_title"] == "CLI Title"
    assert config["days_ahead"] == 14
    assert config["timezone"] == pytz.timezone("Europe/London")


# Source Calendar Tests
@patch("calendar_sync.requests.get")
def test_fetch_source_calendar_success(mock_get):
    """Test successful fetching of iCalendar file"""
    # Setup
    mock_response = MagicMock()
    mock_response.text = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test Corp//Calendar App//EN
BEGIN:VEVENT
UID:12345
SUMMARY:Test Event
DTSTART:20230601T090000Z
DTEND:20230601T100000Z
END:VEVENT
END:VCALENDAR"""
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    # Call function
    result = fetch_source_calendar("https://example.com/calendar.ics")

    # Assertions
    assert result is not None
    assert isinstance(result, Calendar)
    assert len(list(result.walk("VEVENT"))) == 1


@patch("calendar_sync.requests.get")
def test_fetch_source_calendar_http_error(mock_get):
    """Test handling of HTTP errors when fetching calendar"""
    # Setup mock to raise an exception
    mock_get.side_effect = requests.exceptions.RequestException("Test error")

    # Call function
    result = fetch_source_calendar("https://example.com/calendar.ics")

    # Assertions
    assert result is None


def test_get_source_events_date_filtering():
    """Test filtering of events based on date range"""
    # Setup
    cal = Calendar()

    # Event 1: Within date range
    event1 = Event()
    event1.add("summary", "Event 1")
    event1.add("dtstart", datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    event1.add("dtend", datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    event1.add("uid", "12345")
    cal.add_component(event1)

    # Event 2: Outside date range
    event2 = Event()
    event2.add("summary", "Event 2")
    event2.add("dtstart", datetime(2023, 7, 1, 10, 0, 0, tzinfo=pytz.UTC))
    event2.add("dtend", datetime(2023, 7, 1, 11, 0, 0, tzinfo=pytz.UTC))
    event2.add("uid", "67890")
    cal.add_component(event2)

    # Event 3: All-day event within range
    event3 = Event()
    event3.add("summary", "Event 3")
    event3.add("dtstart", date(2023, 6, 5))
    event3.add("dtend", date(2023, 6, 6))
    event3.add("uid", "24680")
    cal.add_component(event3)

    # Call function
    start_date = datetime(2023, 5, 30, tzinfo=pytz.UTC)
    end_date = datetime(2023, 6, 15, tzinfo=pytz.UTC)
    events = get_source_events(cal, start_date, end_date, pytz.UTC)

    # Assertions
    assert len(events) == 2
    event_uids = [event["UID"] for event in events]
    assert "12345" in event_uids
    assert "24680" in event_uids
    assert "67890" not in event_uids


def test_get_source_event_uid():
    """Test extracting UID from a source event"""
    # Setup
    event = Event()
    event.add("uid", "test-uid-123")

    # Call function
    uid = get_source_event_uid(event)

    # Assertions
    assert uid == "test-uid-123"


@patch("calendar_sync.uuid.uuid4")
def test_get_source_event_uid_missing(mock_uuid4):
    """Test generating a UID when source event has none"""
    # Setup
    mock_uuid4.return_value = "generated-uuid"
    event = Event()
    # No UID added

    # Call function
    uid = get_source_event_uid(event)

    # Assertions
    assert uid == "generated-uuid"


# Destination Calendar Tests
@patch("calendar_sync.caldav.DAVClient")
def test_connect_to_dest_calendar_success(mock_client):
    """Test successful connection to destination calendar"""
    # Setup
    mock_principal = MagicMock()
    mock_calendar = MagicMock()
    mock_calendar.name = "Test Calendar"

    mock_principal.calendars.return_value = [mock_calendar]
    mock_client.return_value.principal.return_value = mock_principal

    # Call function
    result = connect_to_dest_calendar(
        "https://example.com", "username", "password", "Test Calendar"
    )

    # Assertions
    assert result == mock_calendar
    mock_client.assert_called_with(
        url="https://example.com", username="username", password="password"
    )


@patch("calendar_sync.caldav.DAVClient")
def test_connect_to_dest_calendar_error(mock_client):
    """Test handling of errors when connecting to destination calendar"""
    # Setup
    mock_client.side_effect = Exception("Connection error")

    # Call function
    result = connect_to_dest_calendar(
        "https://example.com", "username", "password", "Test Calendar"
    )

    # Assertions
    assert result is None


# Event Comparison Tests
def test_find_synced_event_found():
    """Test finding matching synced event by source identifier"""
    # Setup
    event1 = MagicMock()
    event1_component = MagicMock()
    event1_component.get.side_effect = lambda key, default=None: 'source-id-1' if key == 'X-SYNC-SOURCE-IDENTIFIER' else default
    event1.icalendar_instance.subcomponents = [event1_component]

    event2 = MagicMock()
    event2_component = MagicMock()
    event2_component.get.side_effect = lambda key, default=None: 'source-id-2' if key == 'X-SYNC-SOURCE-IDENTIFIER' else default
    event2.icalendar_instance.subcomponents = [event2_component]

    synced_events = [event1, event2]

    # Call function
    result = find_synced_event(synced_events, 'source-id-2')

    # Assertions
    assert result == event2


def test_event_details_changed_time_changed():
    """Test detecting changed event time"""
    # Setup
    # Source event
    source_event = Event()
    source_event.add("dtstart", datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    source_event.add("dtend", datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    source_event.add("location", "Room 123")

    # Synced event (different end time)
    synced_event = MagicMock()
    synced_component = MagicMock()
    synced_component.__getitem__.side_effect = lambda key: {
        "DTSTART": MagicMock(dt=datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC)),
        "DTEND": MagicMock(
            dt=datetime(2023, 6, 1, 12, 0, 0, tzinfo=pytz.UTC)
        ),  # Changed time
        "LOCATION": "Room 123",
    }[key]
    synced_component.__contains__.side_effect = lambda key: key in [
        "DTSTART",
        "DTEND",
        "LOCATION",
    ]
    synced_event.icalendar_instance.subcomponents = [synced_component]

    # Call function
    result = event_details_changed(source_event, synced_event)

    # Assertions
    assert result is True


def test_event_details_changed_location_changed():
    """Test detecting changed event location"""
    # Setup
    # Source event
    source_event = Event()
    source_event.add("dtstart", datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    source_event.add("dtend", datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    source_event.add("location", "Room 123")

    # Synced event (different location)
    synced_event = MagicMock()
    synced_component = MagicMock()
    synced_component.__getitem__.side_effect = lambda key: {
        "DTSTART": MagicMock(dt=datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC)),
        "DTEND": MagicMock(dt=datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC)),
        "LOCATION": "Room 456",  # Changed location
    }[key]
    synced_component.__contains__.side_effect = lambda key: key in [
        "DTSTART",
        "DTEND",
        "LOCATION",
    ]
    synced_event.icalendar_instance.subcomponents = [synced_component]

    # Call function
    result = event_details_changed(source_event, synced_event)

    # Assertions
    assert result is True


# Event Creation/Update Tests
@patch('calendar_sync.generate_event_identifier')
@patch('calendar_sync.uuid.uuid4')
def test_create_new_event(mock_uuid, mock_generate_id):
    """Test creating a new event in destination calendar"""
    # Setup
    mock_uuid.return_value = 'new-uid-123'
    mock_generate_id.return_value = 'generated-identifier-123'
    dest_calendar = MagicMock()

    source_event = Event()
    source_event.add('dtstart', datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    source_event.add('dtend', datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    source_event.add('location', 'Room 123')
    source_event.add('uid', 'source-uid-123')

    # Call function
    result = create_or_update_event(dest_calendar, source_event, 'Tucker Works')

    # Assertions
    assert result is True
    dest_calendar.save_event.assert_called_once()

    # Extract calendar from saved data
    call_args = dest_calendar.save_event.call_args[0][0]
    cal = Calendar.from_ical(call_args)
    event = list(cal.walk('VEVENT'))[0]

    # Verify event properties
    assert event['SUMMARY'] == 'Tucker Works'
    assert event['UID'] == 'new-uid-123'
    assert event['X-SYNC-SOURCE-IDENTIFIER'] == 'generated-identifier-123'
    assert event['DTSTART'].dt == datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC)
    assert event['DTEND'].dt == datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC)
    assert event['LOCATION'] == 'Room 123'


def test_update_existing_event():
    """Test updating an existing event in destination calendar"""
    # Setup
    dest_calendar = MagicMock()

    source_event = Event()
    source_event.add("dtstart", datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    source_event.add("dtend", datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    source_event.add("location", "Room 123")
    source_event.add("uid", "source-uid-123")

    existing_event = MagicMock()
    existing_event_component = MagicMock()
    existing_event_component.__getitem__.side_effect = lambda key: (
        "existing-uid-123" if key == "UID" else None
    )
    existing_event.icalendar_instance.subcomponents = [existing_event_component]

    # Call function
    result = create_or_update_event(
        dest_calendar, source_event, "Tucker Works", existing_event
    )

    # Assertions
    assert result is True
    existing_event.save.assert_called_once()


# Full Sync Process Test
@patch("calendar_sync.connect_to_dest_calendar")
@patch("calendar_sync.fetch_source_calendar")
@patch("calendar_sync.get_source_events")
@patch("calendar_sync.get_dest_events")
@patch("calendar_sync.find_synced_event")
@patch("calendar_sync.event_details_changed")
@patch("calendar_sync.create_or_update_event")
def test_sync_calendars_success(
    mock_create_update,
    mock_details_changed,
    mock_find_synced,
    mock_get_dest,
    mock_get_source,
    mock_fetch,
    mock_connect,
):
    """Test full synchronization process with multiple events"""
    # Setup
    mock_dest_calendar = MagicMock()
    mock_connect.return_value = mock_dest_calendar

    mock_source_calendar = MagicMock()
    mock_fetch.return_value = mock_source_calendar

    # Create two source events
    mock_source_event1 = MagicMock()
    mock_source_event1["UID"] = "src-uid-1"
    mock_source_event2 = MagicMock()
    mock_source_event2["UID"] = "src-uid-2"
    mock_get_source.return_value = [mock_source_event1, mock_source_event2]

    # One existing destination event
    mock_dest_event = MagicMock()
    mock_get_dest.return_value = [mock_dest_event]

    # First event: found match, needs update
    # Second event: no match, create new
    mock_find_synced.side_effect = [mock_dest_event, None]
    mock_details_changed.return_value = True
    mock_create_update.return_value = True

    config = {
        "dest_url": "https://caldav.icloud.com/",
        "dest_username": "user",
        "dest_password": "pass",
        "dest_calendar_name": "Work Calendar",
        "source_url": "https://source.com/cal.ics",
        "normalized_title": "Tucker Works",
        "days_ahead": 30,
        "timezone": pytz.UTC,
    }

    # Call function
    result = sync_calendars(config)

    # Assertions
    assert result is True
    mock_connect.assert_called_once()
    mock_fetch.assert_called_once()
    assert mock_get_source.call_count == 1
    assert mock_get_dest.call_count == 1
    assert mock_find_synced.call_count == 2
    assert mock_details_changed.call_count == 1
    assert mock_create_update.call_count == 2


@patch("calendar_sync.connect_to_dest_calendar")
def test_sync_calendars_dest_connection_failure(mock_connect):
    """Test handling connection failure to destination calendar"""
    # Setup
    mock_connect.return_value = None

    config = {
        "dest_url": "https://caldav.icloud.com/",
        "dest_username": "user",
        "dest_password": "pass",
        "dest_calendar_name": "Work Calendar",
        "source_url": "https://source.com/cal.ics",
        "normalized_title": "Tucker Works",
        "days_ahead": 30,
        "timezone": pytz.UTC,
    }

    # Call function
    result = sync_calendars(config)

    # Assertions
    assert result is False
    mock_connect.assert_called_once()


@patch('calendar_sync.connect_to_dest_calendar')
@patch('calendar_sync.fetch_source_calendar')
@patch('calendar_sync.get_source_events')
@patch('calendar_sync.get_dest_events')
@patch('calendar_sync.generate_event_identifier')  # Mock this to return fixed values
def test_sync_calendars_removes_orphaned_events(mock_generate_id, mock_get_dest,
                                                mock_get_source, mock_fetch, mock_connect):
    """Test that events are removed from destination if they no longer exist in source"""
    # Setup
    mock_dest_calendar = MagicMock()
    mock_connect.return_value = mock_dest_calendar

    mock_source_calendar = MagicMock()
    mock_fetch.return_value = mock_source_calendar

    # Create one source event and set the identifier generator to return a fixed value
    mock_source_event = MagicMock()
    mock_get_source.return_value = [mock_source_event]
    # Make generate_event_identifier return 'src-id-1' for our source event
    mock_generate_id.return_value = 'src-id-1'

    # Create two destination events - one matching source, one orphaned
    mock_dest_event1 = MagicMock()
    mock_dest_event1_component = MagicMock()
    mock_dest_event1_component.get.side_effect = lambda key, default=None: 'src-id-1' if key == 'X-SYNC-SOURCE-IDENTIFIER' else default
    mock_dest_event1.icalendar_instance.subcomponents = [mock_dest_event1_component]

    mock_dest_event2 = MagicMock()
    mock_dest_event2_component = MagicMock()
    mock_dest_event2_component.get.side_effect = lambda key, default=None: 'src-id-2' if key == 'X-SYNC-SOURCE-IDENTIFIER' else default
    mock_dest_event2.icalendar_instance.subcomponents = [mock_dest_event2_component]

    mock_get_dest.return_value = [mock_dest_event1, mock_dest_event2]

    # Also need to mock the other functions called during event processing
    with patch('calendar_sync.find_synced_event', return_value=None) as mock_find_synced:
        with patch('calendar_sync.create_or_update_event', return_value=True) as mock_create_update:
            config = {
                'dest_url': 'https://caldav.icloud.com/',
                'dest_username': 'user',
                'dest_password': 'pass',
                'dest_calendar_name': 'Work Calendar',
                'source_url': 'https://source.com/cal.ics',
                'normalized_title': 'Tucker Works',
                'days_ahead': 30,
                'timezone': pytz.UTC
            }

            # Call function
            result = sync_calendars(config)

            # Assertions
            assert result is True

            # Create or update should be called for the source event
            mock_create_update.assert_called_once()

            # The second destination event should be deleted as it has no matching source event
            mock_dest_event2.delete.assert_called_once()

            # The first destination event should NOT be deleted
            mock_dest_event1.delete.assert_not_called()


@patch("calendar_sync.connect_to_dest_calendar")
@patch("calendar_sync.fetch_source_calendar")
@patch("calendar_sync.get_source_events")
@patch("calendar_sync.get_dest_events")
def test_sync_calendars_handles_delete_errors(
        mock_get_dest, mock_get_source, mock_fetch, mock_connect
):
    """Test that errors during event deletion are handled gracefully"""
    # Setup
    mock_dest_calendar = MagicMock()
    mock_connect.return_value = mock_dest_calendar

    mock_source_calendar = MagicMock()
    mock_fetch.return_value = mock_source_calendar

    # No source events
    mock_get_source.return_value = []

    # One destination event that should be deleted
    mock_dest_event = MagicMock()
    mock_dest_event_component = MagicMock()

    # Use X-SYNC-SOURCE-IDENTIFIER instead of X-SYNC-SOURCE-UID
    mock_dest_event_component.get.side_effect = (
        lambda key, default=None: "orphaned-id"
        if key == "X-SYNC-SOURCE-IDENTIFIER"
        else default
    )

    # Also need to implement __contains__ for 'in' operator checks
    mock_dest_event_component.__contains__.side_effect = lambda key: key in ['SUMMARY', 'X-SYNC-SOURCE-IDENTIFIER']

    mock_dest_event.icalendar_instance.subcomponents = [mock_dest_event_component]

    # Make the delete method raise an exception
    mock_dest_event.delete.side_effect = Exception("Delete failed")

    mock_get_dest.return_value = [mock_dest_event]

    config = {
        "dest_url": "https://caldav.icloud.com/",
        "dest_username": "user",
        "dest_password": "pass",
        "dest_calendar_name": "Work Calendar",
        "source_url": "https://source.com/cal.ics",
        "normalized_title": "Tucker Works",
        "days_ahead": 30,
        "timezone": pytz.UTC,
    }

    # Call function
    result = sync_calendars(config)

    # Assertions
    assert result is True  # Should still return True despite the delete error
    mock_dest_event.delete.assert_called_once()  # Delete was attempted


def test_get_dest_events():
    """Test filtering events in the destination calendar by title and custom property"""
    # Setup
    mock_dest_calendar = MagicMock()

    # Event 1: Matching title and has X-SYNC-SOURCE-IDENTIFIER (should be included)
    mock_event1 = MagicMock()
    mock_event1_component = MagicMock()
    mock_event1_component.get.side_effect = lambda key, default=None: {
        'SUMMARY': 'Tucker Works',
        'X-SYNC-SOURCE-IDENTIFIER': 'source-id-1'
    }.get(key, default)
    # Add __contains__ method to handle 'in' operator
    mock_event1_component.__contains__.side_effect = lambda key: key in ['SUMMARY', 'X-SYNC-SOURCE-IDENTIFIER']
    mock_event1.icalendar_instance.subcomponents = [mock_event1_component]

    # Event 2: Matching title but no X-SYNC-SOURCE-IDENTIFIER (should be excluded)
    mock_event2 = MagicMock()
    mock_event2_component = MagicMock()
    mock_event2_component.get.side_effect = lambda key, default=None: {
        'SUMMARY': 'Tucker Works'
    }.get(key, default)
    # Add __contains__ method that returns False for X-SYNC-SOURCE-IDENTIFIER
    mock_event2_component.__contains__.side_effect = lambda key: key in ['SUMMARY']
    mock_event2.icalendar_instance.subcomponents = [mock_event2_component]

    # Event 3: Has X-SYNC-SOURCE-IDENTIFIER but different title (should be excluded)
    mock_event3 = MagicMock()
    mock_event3_component = MagicMock()
    mock_event3_component.get.side_effect = lambda key, default=None: {
        'SUMMARY': 'Different Title',
        'X-SYNC-SOURCE-IDENTIFIER': 'source-id-3'
    }.get(key, default)
    mock_event3_component.__contains__.side_effect = lambda key: key in ['SUMMARY', 'X-SYNC-SOURCE-IDENTIFIER']
    mock_event3.icalendar_instance.subcomponents = [mock_event3_component]

    # Event 4: Another matching event (should be included)
    mock_event4 = MagicMock()
    mock_event4_component = MagicMock()
    mock_event4_component.get.side_effect = lambda key, default=None: {
        'SUMMARY': 'Tucker Works',
        'X-SYNC-SOURCE-IDENTIFIER': 'source-id-4'
    }.get(key, default)
    mock_event4_component.__contains__.side_effect = lambda key: key in ['SUMMARY', 'X-SYNC-SOURCE-IDENTIFIER']
    mock_event4.icalendar_instance.subcomponents = [mock_event4_component]

    # Set up calendar to return all events
    mock_dest_calendar.events.return_value = [mock_event1, mock_event2, mock_event3, mock_event4]

    # Call function
    result = get_dest_events(mock_dest_calendar, 'Tucker Works')

    # Assertions
    assert len(result) == 2
    assert mock_event1 in result
    assert mock_event2 not in result
    assert mock_event3 not in result
    assert mock_event4 in result

    # Verify the calendar's events method was called
    mock_dest_calendar.events.assert_called_once()


def test_generate_event_identifier():
    """Test generating stable identifiers for events"""
    from datetime import datetime, date
    from icalendar import Event
    import pytz

    # Create a time-specific event
    event1 = Event()
    event1.add('summary', 'Team Meeting')
    event1.add('dtstart', datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    event1.add('dtend', datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    event1.add('location', 'Conference Room A')

    # Create an identical event - should generate same ID
    event2 = Event()
    event2.add('summary', 'Team Meeting')
    event2.add('dtstart', datetime(2023, 6, 1, 10, 0, 0, tzinfo=pytz.UTC))
    event2.add('dtend', datetime(2023, 6, 1, 11, 0, 0, tzinfo=pytz.UTC))
    event2.add('location', 'Conference Room A')

    # Create an event with different time - should generate different ID
    event3 = Event()
    event3.add('summary', 'Team Meeting')
    event3.add('dtstart', datetime(2023, 6, 1, 14, 0, 0, tzinfo=pytz.UTC))  # Different time
    event3.add('dtend', datetime(2023, 6, 1, 15, 0, 0, tzinfo=pytz.UTC))
    event3.add('location', 'Conference Room A')

    # Create an all-day event
    event4 = Event()
    event4.add('summary', 'Company Holiday')
    event4.add('dtstart', date(2023, 7, 4))
    event4.add('dtend', date(2023, 7, 5))

    # Generate identifiers
    id1 = generate_event_identifier(event1)
    id2 = generate_event_identifier(event2)
    id3 = generate_event_identifier(event3)
    id4 = generate_event_identifier(event4)

    # Assertions
    assert id1 == id2, "Identical events should have the same identifier"
    assert id1 != id3, "Events with different times should have different identifiers"
    assert id1 != id4, "All-day and time-specific events should have different identifiers"

    # Test error handling by passing an incomplete event
    incomplete_event = Event()
    # No dtstart added
    incomplete_id = generate_event_identifier(incomplete_event)
    assert incomplete_id, "Should return a fallback ID for incomplete events"


def test_identifier_stability_across_uids():
    """Test that identifiers remain stable even when UIDs change"""
    from datetime import datetime
    from icalendar import Event
    import pytz

    # Create an event with one UID
    event1 = Event()
    event1.add('summary', 'Weekly Status Update')
    event1.add('dtstart', datetime(2023, 6, 7, 9, 0, 0, tzinfo=pytz.UTC))
    event1.add('dtend', datetime(2023, 6, 7, 10, 0, 0, tzinfo=pytz.UTC))
    event1.add('location', 'Meeting Room 1')
    event1.add('uid', 'original-uid-123')

    # Create identical event but with different UID
    event2 = Event()
    event2.add('summary', 'Weekly Status Update')
    event2.add('dtstart', datetime(2023, 6, 7, 9, 0, 0, tzinfo=pytz.UTC))
    event2.add('dtend', datetime(2023, 6, 7, 10, 0, 0, tzinfo=pytz.UTC))
    event2.add('location', 'Meeting Room 1')
    event2.add('uid', 'new-uid-456')  # Different UID

    # Generate identifiers
    id1 = generate_event_identifier(event1)
    id2 = generate_event_identifier(event2)

    # Assertion
    assert id1 == id2, "Events with identical properties but different UIDs should have the same identifier"