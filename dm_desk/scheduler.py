"""Wall-clock runner for all desks on one clock (America/Chicago).

every 4h (00/04/08/12/16/20): research scan (+ engine scan inside it when --advisor engine), execution manage
weekday 06:45: research game plan   weekday 08:25: execution fire window   weekday 16:00: research EOD
Holidays keep the 4h loop; the three weekday slots are marked HOLIDAY by the desks themselves."""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config as C
from .desk import Desk
from .execution import FIRE_WINDOW

TZ = ZoneInfo(C.TZ)


def next_events(now: datetime) -> list[tuple[datetime, str]]:
    ev: list[tuple[datetime, str]] = []
    base = now.replace(minute=0, second=0, microsecond=0)
    h = (now.hour // C.SCAN_INTERVAL_HOURS + 1) * C.SCAN_INTERVAL_HOURS
    ev.append((base.replace(hour=0) + timedelta(hours=h), "scan"))
    for (hh, mm), name in ((C.GAMEPLAN_TIME, "gameplan"), (FIRE_WINDOW, "fire"), (C.EOD_TIME, "eod")):
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        ev.append((t, name))
    return sorted(ev)


def run(desk: Desk, execution=None, once: bool = False) -> None:
    while True:
        now = datetime.now(TZ)
        when, what = next_events(now)[0]
        wait = (when - now).total_seconds()
        if wait > 0:
            time.sleep(wait)
        if what == "scan":
            desk.scan()
            if execution is not None:
                execution.manage()
        elif what == "gameplan":
            desk.gameplan()
        elif what == "fire":
            if execution is not None:
                execution.fire()
        else:
            desk.eod()
        if once:
            return
