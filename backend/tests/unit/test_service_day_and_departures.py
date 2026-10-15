from __future__ import annotations

from tests.builders import FeedBuilder, at, simple_line, stu, trip_update
from transitlive.domain.departures import all_departures, stop_departures
from transitlive.domain.service_day import gtfs_time, local_date, service_day_start


class TestServiceDay:
    def test_normal_day_starts_at_local_midnight(self) -> None:
        assert service_day_start("20261014", "America/Vancouver") == at(2026, 10, 14)

    def test_fall_back_day_counts_from_noon_minus_12h(self) -> None:
        # 1 Nov 2026: clocks go back at 02:00. 08:00 must still mean 08:00 local,
        # which a midnight-based calculation would get wrong by an hour.
        assert gtfs_time("20261101", "08:00:00", "America/Vancouver") == at(2026, 11, 1, 8)

    def test_spring_forward_day(self) -> None:
        assert gtfs_time("20270314", "08:00:00", "America/Vancouver") == at(2027, 3, 14, 8)

    def test_times_past_midnight(self) -> None:
        assert gtfs_time("20261014", "25:10:00", "America/Vancouver") == at(2026, 10, 15, 1, 10)

    def test_local_date(self) -> None:
        assert local_date(at(2026, 10, 14, 23, 59), "America/Vancouver") == "20261014"
        assert local_date(at(2026, 10, 15, 0, 1), "America/Vancouver", -1) == "20261014"


class TestDepartures:
    def timetable(self):
        fb = simple_line()
        fb.trip("T1", "R1", [("A", "10:00:00"), ("B", "10:02:00"), ("C", "10:04:00"), ("D", "10:06:00")])
        fb.trip("T2", "R1", [("A", "10:30:00"), ("B", "10:32:00"), ("C", "10:34:00"), ("D", "10:36:00")])
        return fb.build()

    def test_scheduled_departures_in_order(self) -> None:
        tt = self.timetable()
        deps = stop_departures(tt, {}, "B", at(2026, 10, 14, 9, 50))
        assert [(d.trip_id, d.time, d.live) for d in deps] == [
            ("T1", at(2026, 10, 14, 10, 2), False),
            ("T2", at(2026, 10, 14, 10, 32), False),
        ]

    def test_last_stop_of_a_trip_is_not_a_departure(self) -> None:
        tt = self.timetable()
        assert stop_departures(tt, {}, "D", at(2026, 10, 14, 9, 50)) == []

    def test_live_prediction_replaces_the_timetable(self) -> None:
        tt = self.timetable()
        tus = {"T1": trip_update("T1", stu("B", at(2026, 10, 14, 10, 5), delay=180))}
        deps = stop_departures(tt, tus, "B", at(2026, 10, 14, 9, 50))
        assert deps[0].live and deps[0].time == at(2026, 10, 14, 10, 5) and deps[0].delay == 180
        assert [d.trip_id for d in deps] == ["T1", "T2"]

    def test_trip_with_prediction_that_has_passed_the_stop_is_dropped(self) -> None:
        tt = self.timetable()
        # T1's update only lists later stops: it has already left B
        tus = {"T1": trip_update("T1", stu("C", at(2026, 10, 14, 10, 4)))}
        assert [d.trip_id for d in stop_departures(tt, tus, "B", at(2026, 10, 14, 9, 50))] == ["T2"]

    def test_skipped_stop_is_dropped(self) -> None:
        tt = self.timetable()
        tus = {"T1": trip_update("T1", stu("B", at(2026, 10, 14, 10, 2), relationship="SKIPPED"))}
        assert [d.trip_id for d in stop_departures(tt, tus, "B", at(2026, 10, 14, 9, 50))] == ["T2"]

    def test_cancelled_trip_is_shown_as_cancelled(self) -> None:
        tt = self.timetable()
        deps = stop_departures(tt, {"T1": trip_update("T1", cancelled=True)}, "B", at(2026, 10, 14, 9, 50))
        assert deps[0].trip_id == "T1" and deps[0].cancelled and not deps[0].live

    def test_untracked_trips_are_flagged(self) -> None:
        tt = self.timetable()
        deps = stop_departures(tt, {}, "B", at(2026, 10, 14, 9, 50), untracked_trips=frozenset({"T2"}))
        assert [d.untracked for d in deps] == [False, True]

    def test_departures_outside_window_are_excluded(self) -> None:
        tt = self.timetable()
        assert [d.trip_id for d in stop_departures(tt, {}, "B", at(2026, 10, 14, 9, 50), window=20 * 60)] == ["T1"]

    def test_yesterdays_trip_running_past_midnight(self) -> None:
        fb = FeedBuilder(service_dates=("20261014",)).route("R1", "1").stop("A", 49.7).stop("B", 49.701)
        fb.trip("NIGHT", "R1", [("A", "25:10:00"), ("B", "25:20:00")])
        tt = fb.build()
        deps = stop_departures(tt, {}, "A", at(2026, 10, 15, 0, 50))
        assert [(d.trip_id, d.time) for d in deps] == [("NIGHT", at(2026, 10, 15, 1, 10))]

    def test_all_departures_matches_per_stop(self) -> None:
        tt = self.timetable()
        tus = {"T1": trip_update("T1", stu("B", at(2026, 10, 14, 10, 5)), stu("C", at(2026, 10, 14, 10, 7)))}
        now = at(2026, 10, 14, 9, 50)
        everything = all_departures(tt, tus, now)
        for stop_id in tt.stops:
            assert everything[stop_id] == stop_departures(tt, tus, stop_id, now)
