"""PredictionDeduper stores a prediction only when it moves meaningfully."""

from __future__ import annotations

from tests.builders import stu, trip_update
from transitlive.db.store import PredictionDeduper
from transitlive.domain.model import Snapshot

T0 = 1_792_000_000


def snap(ts: int, *tus: object) -> Snapshot:
    return Snapshot("tripupdates", ts, trip_updates=tuple(tus))  # type: ignore[arg-type]


def stored(deduper: PredictionDeduper, s: Snapshot) -> int:
    return len(deduper.changed_rows(43, s, {}))


def test_first_observation_is_always_stored() -> None:
    assert stored(PredictionDeduper(), snap(T0, trip_update("t1", stu("A", T0 + 600), stu("B", T0 + 900)))) == 2


def test_small_moves_are_skipped_until_they_add_up() -> None:
    d = PredictionDeduper(threshold_seconds=30)
    stored(d, snap(T0, trip_update("t1", stu("A", T0 + 600, delay=0))))
    assert stored(d, snap(T0 + 30, trip_update("t1", stu("A", T0 + 610, delay=10)))) == 0
    assert stored(d, snap(T0 + 60, trip_update("t1", stu("A", T0 + 625, delay=25)))) == 0
    # 30 s from the last *stored* prediction, though only 5 s from the last seen
    assert stored(d, snap(T0 + 90, trip_update("t1", stu("A", T0 + 630, delay=30)))) == 1
    assert stored(d, snap(T0 + 120, trip_update("t1", stu("A", T0 + 600, delay=0)))) == 1  # moving earlier counts too


def test_relationship_changes_are_always_stored() -> None:
    d = PredictionDeduper()
    stored(d, snap(T0, trip_update("t1", stu("A", T0 + 600))))
    assert stored(d, snap(T0 + 30, trip_update("t1", stu("A", T0 + 600, relationship="SKIPPED")))) == 1
    assert stored(d, snap(T0 + 60, trip_update("t1", stu("A", T0 + 600, relationship="SKIPPED"), cancelled=True))) == 1


def test_time_appearing_or_disappearing_is_stored() -> None:
    d = PredictionDeduper()
    stored(d, snap(T0, trip_update("t1", stu("A", None, delay=None))))
    assert stored(d, snap(T0 + 30, trip_update("t1", stu("A", T0 + 600)))) == 1
    assert stored(d, snap(T0 + 60, trip_update("t1", stu("A", None, delay=None)))) == 1


def test_trip_level_rows_and_forgotten_keys() -> None:
    d = PredictionDeduper()
    assert stored(d, snap(T0, trip_update("t1"))) == 1
    assert stored(d, snap(T0 + 30, trip_update("t1"))) == 0
    assert stored(d, snap(T0 + 60, trip_update("t1", cancelled=True))) == 1
    stored(d, snap(T0 + 90))  # trip gone from the feed: forgotten
    assert stored(d, snap(T0 + 120, trip_update("t1", cancelled=True))) == 1


def test_zero_threshold_stores_every_change() -> None:
    d = PredictionDeduper(threshold_seconds=0.5)
    stored(d, snap(T0, trip_update("t1", stu("A", T0 + 600))))
    assert stored(d, snap(T0 + 30, trip_update("t1", stu("A", T0 + 601, delay=1)))) == 1
