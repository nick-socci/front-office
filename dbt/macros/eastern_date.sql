{#
  The calendar date an instant falls on for fantasy purposes.

  ESPN's scoring day rolls over at midnight US/Eastern, not UTC. A snapshot taken at
  02:52 UTC belongs to the PREVIOUS Eastern day, and a West Coast game starting at 22:05
  Eastern still scores on its own day even though it is already tomorrow in UTC. Getting
  this wrong shifts every roster by a day -- subtly wrong rather than obviously broken.
#}

{% macro fo_eastern_date(timestamp_column) %}
    (({{ timestamp_column }} at time zone 'UTC') at time zone 'America/New_York')::date
{%- endmacro %}
