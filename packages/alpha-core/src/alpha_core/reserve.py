from datetime import date

# First day of the reserved period. Only the owner can authorize changing it.
RESERVED_DAY = date(2024, 1, 1)
RESERVED_START = RESERVED_DAY.isoformat()
