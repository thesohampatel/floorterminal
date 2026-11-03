"""Bounded conveyor geometry, independent of Tk and frame rate."""

import math
from itertools import pairwise


def belt_point(distance, straight, radius):
    """Position and outward normal on a clockwise capsule-shaped belt.

    Origin is the left roller centre. Top carry run goes right; bottom return
    goes left. The joins are continuous and no seam reverses at a roller.
    """
    straight, radius = max(1.0, straight), max(1.0, radius)
    arc = math.pi * radius
    distance %= 2 * (straight + arc)
    if distance < straight:
        return distance, -radius, 0.0, -1.0
    distance -= straight
    if distance < arc:
        angle = distance / radius - math.pi / 2
        nx, ny = math.cos(angle), math.sin(angle)
        return straight + radius * nx, radius * ny, nx, ny
    distance -= arc
    if distance < straight:
        return straight - distance, radius, 0.0, 1.0
    angle = (distance - straight) / radius + math.pi / 2
    nx, ny = math.cos(angle), math.sin(angle)
    return radius * nx, radius * ny, nx, ny


GROUP_COLORS = (
    ("#466CB4", "#F0F5FD"),
    ("#7B5BA7", "#F6F2FC"),
    ("#277C86", "#EDF8F8"),
    ("#9A713E", "#FBF6ED"),
)


def advance_motion(previous, now, running, circumference, travel, radius):
    """Independent bounded phases; resume without a jump or missed-frame burst."""
    last, belt, parcel, angle, was_running = previous or (
        now,
        0,
        travel / 2,
        0,
        running,
    )
    distance = min(0.1, max(0, now - last)) * 30 if running and was_running else 0
    return (
        now,
        (belt + distance) % circumference,
        (parcel + distance) % travel,
        (angle + distance / radius) % math.tau,
        running,
    )


def station_slots(zones, group_by_station, box, grouped):
    """Equal touch widths, with a larger physical break between groups."""
    left, top, right, bottom = box
    gaps = [
        20 if grouped and group_by_station[a]["id"] != group_by_station[b]["id"] else 8
        for a, b in pairwise(zones)
    ]
    width = (right - left - sum(gaps)) / max(1, len(zones))
    slots = []
    for index in range(len(zones)):
        slots.append((left, top, left + width, bottom))
        left += width + (gaps[index] if index < len(gaps) else 0)
    return slots
