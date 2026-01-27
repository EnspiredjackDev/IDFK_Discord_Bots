"""XP level calculation utilities."""

def xp_to_next(level: int) -> int:
    """Calculate XP needed to reach the next level."""
    return 5 * level * level + 50 * level + 100

def total_xp_for_level(L: int) -> int:
    """Calculate total XP needed to reach level L from 0."""
    # XP needed to reach level L from 0:
    # 5L(2L^2 + 27L + 91)/6
    return (5 * L * (2 * L * L + 27 * L + 91)) // 6

def level_from_total_xp(xp: int) -> int:
    """Calculate level from total XP using binary search."""
    lo, hi = 0, 5000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if total_xp_for_level(mid) <= xp:
            lo = mid
        else:
            hi = mid - 1
    return lo
