from datetime import UTC, date, datetime, time

# First day of the reserved period. Only the owner can authorize changing it.
RESERVED_DAY = date(2024, 1, 1)
RESERVED_START = RESERVED_DAY.isoformat()
# The first instant of the reserved day: the one boundary every reader cuts at.
RESERVED_INSTANT = datetime.combine(RESERVED_DAY, time.min, tzinfo=UTC)
