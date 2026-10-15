from __future__ import annotations

from tests.builders import at, simple_line, stu, trip_update, vehicle
from transitlive.domain.schedule_check import schedule_check, vehicle_block
from transitlive.domain.waiting import waiting_info


def timetable():
    fb = simple_line()
    # Block B1 drives T1 then T2; block B2 drives T3
    fb.trip("T1", "R1", [("A", "10:00:00"), ("B", "10:02:00"), ("D", "10:20:00")], block="B1", shape="SH1")
    fb.trip("T2", "R1", [("A", "10:30:00"), ("B", "10:32:00"), ("D", "10:50:00")], block="B1", shape="SH1")
    fb.trip("T3", "R1", [("A", "10:10:00"), ("B", "10:12:00"), ("D", "10:40:00")], block="B2", shape="SH1")
    return fb.build()


class TestWaiting:
    def test_parked_before_its_trip_starts(self) -> None:
        tt = timetable()
        w = waiting_info(tt, {}, vehicle(trip="T2", speed=0, seq=1), at(2026, 10, 14, 10, 25))
        assert w is not None and w.departs == at(2026, 10, 14, 10, 30) and w.stop_id == "A"

    def test_moving_bus_is_not_waiting(self) -> None:
        tt = timetable()
        assert waiting_info(tt, {}, vehicle(trip="T2", speed=8, seq=1), at(2026, 10, 14, 10, 25)) is None

    def test_late_bus_still_at_first_stop_is_waiting(self) -> None:
        tt = timetable()
        w = waiting_info(tt, {}, vehicle(trip="T2", speed=0, seq=1), at(2026, 10, 14, 10, 33))
        assert w is not None and w.departs == at(2026, 10, 14, 10, 30)  # overdue

    def test_stopped_mid_trip_is_not_waiting(self) -> None:
        tt = timetable()
        assert waiting_info(tt, {}, vehicle(trip="T1", speed=0, seq=3), at(2026, 10, 14, 10, 10)) is None

    def test_prediction_overrides_schedule(self) -> None:
        tt = timetable()
        tus = {"T2": trip_update("T2", stu("A", at(2026, 10, 14, 10, 34)))}
        w = waiting_info(tt, tus, vehicle(trip="T2", speed=0, seq=1), at(2026, 10, 14, 10, 25))
        assert w is not None and w.predicted == at(2026, 10, 14, 10, 34) and w.departs == w.predicted

    def test_start_time_from_the_feed_is_used(self) -> None:
        tt = timetable()
        v = vehicle(trip="T2", speed=0, seq=1, start_date="20261014", start_time="10:31:00")
        w = waiting_info(tt, {}, v, at(2026, 10, 14, 10, 25))
        assert w is not None and w.scheduled == at(2026, 10, 14, 10, 31)


class TestScheduleCheck:
    def test_trip_with_no_bus_is_untracked_after_grace(self) -> None:
        tt = timetable()
        check = schedule_check(tt, [vehicle(trip="T1")], {}, at(2026, 10, 14, 10, 15))
        r = check.routes["R1"]
        assert r.active == 2 and r.tracked == 1
        assert [t.trip_id for t in r.untracked] == ["T3"] and check.untracked_trips == {"T3"}

    def test_grace_period_before_flagging(self) -> None:
        tt = timetable()
        check = schedule_check(tt, [vehicle(trip="T1")], {}, at(2026, 10, 14, 10, 11))
        assert check.routes["R1"].untracked == []

    def test_bus_already_on_next_trip_of_block_counts_as_tracked(self) -> None:
        # T1 is scheduled until 10:20, but its bus finished early and logged into T2
        tt = timetable()
        check = schedule_check(tt, [vehicle(trip="T2"), vehicle("V2", trip="T3")], {}, at(2026, 10, 14, 10, 18))
        assert check.routes["R1"].untracked == []

    def test_cancelled_trip(self) -> None:
        tt = timetable()
        check = schedule_check(
            tt, [vehicle(trip="T1")], {"T3": trip_update("T3", cancelled=True)}, at(2026, 10, 14, 10, 15)
        )
        r = check.routes["R1"]
        assert [t.trip_id for t in r.cancelled] == ["T3"] and r.untracked == []

    def test_extra_trip_not_in_timetable(self) -> None:
        tt = timetable()
        extra = vehicle("V9", trip="2516528:14637469:B1")
        check = schedule_check(tt, [vehicle(trip="T1"), extra], {}, at(2026, 10, 14, 10, 5))
        assert check.unscheduled == (extra,) and check.unknown_trip_ratio == 0.5

    def test_block_parsed_from_trip_id_for_extra_trips(self) -> None:
        tt = timetable()
        assert vehicle_block(tt, vehicle(trip="2516528:14637469:14647750")) == "14647750"
        assert vehicle_block(tt, vehicle(trip="T3")) == "B2"
        assert vehicle_block(tt, vehicle(trip="odd-format")) is None

    def test_next_departure_names_its_first_stop(self) -> None:
        tt = timetable()
        check = schedule_check(tt, [], {}, at(2026, 10, 14, 10, 5))
        nxt = check.routes["R1"].next
        assert nxt is not None and nxt.trip_id == "T3" and nxt.stop_id == "A"
        assert nxt.time == at(2026, 10, 14, 10, 10)

    def test_waiting_bus_stays_next_departure_after_its_time_passes(self) -> None:
        # The bug the prototype had: at 10:31 the 10:30 bus is still parked,
        # so it must stay the next departure instead of skipping ahead.
        tt = timetable()
        parked = vehicle(trip="T2", speed=0, seq=1)
        check = schedule_check(tt, [parked], {}, at(2026, 10, 14, 10, 31))
        nxt = check.routes["R1"].next
        assert nxt is not None and nxt.trip_id == "T2" and nxt.time == at(2026, 10, 14, 10, 30)

    def test_predicted_departure_used_for_next(self) -> None:
        tt = timetable()
        tus = {"T3": trip_update("T3", stu("A", at(2026, 10, 14, 10, 13)))}
        nxt = schedule_check(tt, [], tus, at(2026, 10, 14, 10, 5)).routes["R1"].next
        assert nxt is not None and nxt.time == at(2026, 10, 14, 10, 13) and nxt.scheduled == at(2026, 10, 14, 10, 10)

    def test_no_service_today(self) -> None:
        tt = timetable()
        check = schedule_check(tt, [], {}, at(2026, 10, 20, 10, 0))
        assert check.routes["R1"].active == 0 and check.routes["R1"].next is None
