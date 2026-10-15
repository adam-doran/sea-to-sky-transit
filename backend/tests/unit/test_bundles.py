"""Daily bundles, their verification, S3 upload (moto, never real AWS) and
local retention, on a copy of the recorded fixtures (one UTC day)."""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from transitlive.collector import bundles
from transitlive.collector.archive import Archive
from transitlive.collector.bundles import BundleError, S3Store, bundle_day, maintain, prune_day
from transitlive.collector.service import seconds_until_maintenance
from transitlive.config import REALTIME_FEEDS, ArchiveSettings, load_config

FIXTURES = Path(__file__).parents[1] / "fixtures" / "archive"
DAY = dt.date(2026, 10, 15)
SYSTEMS = ["squamish", "whistler", "pemberton"]


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    shutil.copytree(FIXTURES, tmp_path / "archive")
    return Archive(tmp_path / "archive")


def snapshot_files(archive: Archive, system: str, day: dt.date = DAY) -> list[Path]:
    return [p for feed in REALTIME_FEEDS for _, p in archive.day_files(system, feed, day)]


def every_snapshot(archive: Archive) -> list[tuple[str, str, int, str]]:
    return [
        (system, feed, ts, hashlib.sha256(data).hexdigest())
        for system in SYSTEMS
        for feed in REALTIME_FEEDS
        for ts, data in archive.snapshots(system, feed)
    ]


def bundles_only(archive: Archive, tmp_path: Path) -> Archive:
    """A second archive root holding just the bundles, as restored from S3 or a NAS."""
    root = tmp_path / "restored"
    shutil.copytree(archive.root / "bundles", root / "bundles")
    return Archive(root)


class TestBundling:
    def test_a_bundle_holds_every_file_of_the_day(self, archive: Archive) -> None:
        files = snapshot_files(archive, "squamish")
        result = bundle_day(archive, "squamish", DAY)
        assert result is not None and result.created
        assert result.path == archive.root / "bundles" / "squamish" / "2026-10-15.tar.zst"
        assert result.members == len(files) + 1  # and the day's timetable zip
        hashes = bundles.bundle_hashes(result.path)
        for path in files:
            name = f"{path.parts[-3]}/{path.name.removesuffix('.zst')}"
            assert hashes[name] == hashlib.sha256(Archive.read(path)).hexdigest()
        assert not list(result.path.parent.glob("*.tmp"))

    def test_consecutive_snapshots_compress_well(self, archive: Archive) -> None:
        result = bundle_day(archive, "whistler", DAY)
        assert result is not None
        raw = sum(len(Archive.read(p)) for p in snapshot_files(archive, "whistler"))
        timetable = next(archive.iter_static("whistler")).stat().st_size  # already compressed
        assert result.size - timetable < raw / 8

    def test_replaying_bundles_alone_gives_the_same_snapshots(self, archive: Archive, tmp_path: Path) -> None:
        before = every_snapshot(archive)
        for system in SYSTEMS:
            bundle_day(archive, system, DAY)
        assert every_snapshot(archive) == before  # files and bundles together: no duplicates
        restored = bundles_only(archive, tmp_path)
        assert every_snapshot(restored) == before
        name, load = restored.latest_static("squamish") or ("", bytes)
        assert name == next(archive.iter_static("squamish")).name
        assert load() == next(archive.iter_static("squamish")).read_bytes()
        assert restored.load(f"squamish/static/{name}") == load()
        with pytest.raises(FileNotFoundError):
            restored.load("squamish/static/2026-10-16_0000000000000000.zip")

    def test_running_again_changes_nothing(self, archive: Archive) -> None:
        first = bundle_day(archive, "pemberton", DAY)
        assert first is not None
        mtime = first.path.stat().st_mtime_ns
        again = bundle_day(archive, "pemberton", DAY)
        assert again is not None and not again.created and again.members == first.members
        assert first.path.stat().st_mtime_ns == mtime

    def test_late_files_are_added_and_bundled_members_kept(self, archive: Archive) -> None:
        first = bundle_day(archive, "pemberton", DAY)
        assert first is not None
        alerts = [p for _, p in archive.day_files("pemberton", "alerts", DAY)]
        for path in alerts[:3]:
            path.unlink()  # as if deleted by retention
        archive.write_realtime("pemberton", "alerts", int(alerts[-1].name.split(".")[0]) + 1, Archive.read(alerts[-1]))
        second = bundle_day(archive, "pemberton", DAY)
        assert second is not None and second.created and second.members == first.members + 1
        assert len(list(archive.snapshots("pemberton", "alerts"))) == len(alerts) + 1
        for path in snapshot_files(archive, "pemberton"):
            path.unlink()
        assert len(list(archive.snapshots("pemberton", "alerts"))) == len(alerts) + 1  # all from the bundle

    def test_a_bundle_that_fails_verification_is_not_kept(
        self, archive: Archive, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(path: Path, expected: dict[str, str]) -> None:
            raise BundleError("corrupt")

        monkeypatch.setattr(bundles, "verify", broken)
        with pytest.raises(BundleError):
            bundle_day(archive, "squamish", DAY)
        assert not archive.bundle_path("squamish", DAY).exists()
        assert not list((archive.root / "bundles" / "squamish").iterdir())

    def test_verify_checks_count_and_contents(self, archive: Archive) -> None:
        result = bundle_day(archive, "pemberton", DAY)
        assert result is not None
        hashes = bundles.bundle_hashes(result.path)
        bundles.verify(result.path, hashes)
        with pytest.raises(BundleError, match="members, expected"):
            bundles.verify(result.path, dict(list(hashes.items())[1:]))
        name = next(iter(hashes))
        with pytest.raises(BundleError, match="don't match"):
            bundles.verify(result.path, {**hashes, name: "0" * 64})

    def test_nothing_archived(self, archive: Archive) -> None:
        assert bundle_day(archive, "squamish", DAY - dt.timedelta(days=1)) is None

    def test_default_day_is_yesterday_in_utc(self) -> None:
        # 2026-10-15 03:47 UTC is still the 14th in Squamish; bundles use UTC
        assert bundles.previous_utc_day(1_792_036_020) == dt.date(2026, 10, 14)

    def test_cli_bundles_a_day(self, archive: Archive, monkeypatch: pytest.MonkeyPatch) -> None:
        from transitlive.cli import main

        monkeypatch.delenv("TRANSITLIVE_S3_BUCKET", raising=False)
        main(["bundle", "--archive", str(archive.root), "--date", "2026-10-15"])
        assert archive.has_bundles(SYSTEMS, DAY)
        assert not archive.has_bundles(SYSTEMS, DAY + dt.timedelta(days=1))


class TestLocalRetention:
    def settings(self, keep: int = 3) -> ArchiveSettings:
        return ArchiveSettings(keep_snapshot_days=keep)

    def test_files_go_only_once_bundled_and_old_enough(self, archive: Archive) -> None:
        summary = maintain(archive, SYSTEMS, self.settings(), DAY + dt.timedelta(days=3), None)
        assert len(summary.bundled) == 3 and summary.deleted_files == 0
        assert snapshot_files(archive, "squamish")

        before = every_snapshot(archive)
        summary = maintain(archive, SYSTEMS, self.settings(), DAY + dt.timedelta(days=4), None)
        assert summary.bundled == [] and summary.errors == 0
        assert summary.deleted_files == 122
        for system in SYSTEMS:
            assert snapshot_files(archive, system) == []
            assert not (archive.root / system / "vehicleupdates" / DAY.isoformat()).exists()
            assert list(archive.iter_static(system))  # timetables stay
        assert every_snapshot(archive) == before  # still readable, from the bundles
        # Nothing left to do on later nights
        again = maintain(archive, SYSTEMS, self.settings(), DAY + dt.timedelta(days=5), None)
        assert (again.bundled, again.deleted_files) == ([], 0)

    def test_today_is_never_bundled(self, archive: Archive) -> None:
        summary = maintain(archive, SYSTEMS, self.settings(), DAY, None)
        assert summary.bundled == [] and not archive.bundle_path("squamish", DAY).exists()

    def test_a_day_without_a_bundle_is_kept(self, archive: Archive) -> None:
        assert prune_day(archive, "squamish", DAY, None) == 0
        assert snapshot_files(archive, "squamish")

    def test_files_missing_from_the_bundle_are_kept(self, archive: Archive) -> None:
        bundle_day(archive, "squamish", DAY)
        ts, _ = archive.day_files("squamish", "alerts", DAY)[-1]
        archive.write_realtime("squamish", "alerts", ts + 1, b"arrived after bundling")
        assert prune_day(archive, "squamish", DAY, None) == 0
        assert len(snapshot_files(archive, "squamish")) == 43

    def test_a_corrupt_bundle_keeps_its_files(self, archive: Archive) -> None:
        bundle_day(archive, "squamish", DAY)
        archive.bundle_path("squamish", DAY).write_bytes(b"not zstd")
        summary = maintain(archive, ["squamish"], self.settings(), DAY + dt.timedelta(days=10), None)
        assert summary.errors == 1 and len(snapshot_files(archive, "squamish")) == 42


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Store]:
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(var, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        client = boto3.client("s3", region_name="ca-central-1")
        client.create_bucket(Bucket="layover", CreateBucketConfiguration={"LocationConstraint": "ca-central-1"})
        yield S3Store("layover", "bundles", client=client)


class TestS3:
    def test_uploads_once(self, archive: Archive, s3: S3Store) -> None:
        result = bundle_day(archive, "squamish", DAY)
        assert result is not None
        assert s3.key("squamish", DAY) == "bundles/squamish/2026-10-15.tar.zst"
        assert not s3.has(result.path, "squamish", DAY)
        assert s3.upload(result.path, "squamish", DAY)
        assert s3.has(result.path, "squamish", DAY)
        assert not s3.upload(result.path, "squamish", DAY)  # same size and checksum: skipped
        head = s3.client.head_object(Bucket="layover", Key=s3.key("squamish", DAY))
        assert head["Metadata"]["sha256"] == bundles.file_sha256(result.path)
        body = s3.client.get_object(Bucket="layover", Key=s3.key("squamish", DAY))["Body"].read()
        assert body == result.path.read_bytes()

    def test_a_changed_bundle_is_uploaded_again(self, archive: Archive, s3: S3Store) -> None:
        result = bundle_day(archive, "pemberton", DAY)
        assert result is not None
        s3.upload(result.path, "pemberton", DAY)
        ts, latest = archive.day_files("pemberton", "alerts", DAY)[-1]
        archive.write_realtime("pemberton", "alerts", ts + 1, Archive.read(latest))
        bundle_day(archive, "pemberton", DAY)
        assert not s3.has(result.path, "pemberton", DAY)
        assert s3.upload(result.path, "pemberton", DAY)

    def test_files_stay_until_the_bundle_is_in_s3(self, archive: Archive, s3: S3Store) -> None:
        bundle_day(archive, "squamish", DAY)
        assert prune_day(archive, "squamish", DAY, s3) == 0
        settings = ArchiveSettings(keep_snapshot_days=3)
        summary = maintain(archive, SYSTEMS, settings, DAY + dt.timedelta(days=4), s3)
        assert summary.uploaded == 3 and summary.deleted_files == 122
        keys = [o["Key"] for o in s3.client.list_objects_v2(Bucket="layover")["Contents"]]
        assert sorted(keys) == [f"bundles/{s}/2026-10-15.tar.zst" for s in sorted(SYSTEMS)]

    def test_prefix_and_settings(self) -> None:
        assert S3Store.from_settings(ArchiveSettings()) is None
        store = S3Store("b", "", client=object())
        assert store.key("whistler", DAY) == "whistler/2026-10-15.tar.zst"
        assert S3Store("b", "x/", client=object()).key("whistler", DAY) == "x/whistler/2026-10-15.tar.zst"


class TestConfig:
    def write(self, tmp_path: Path, extra: str) -> Path:
        base = (Path(__file__).parents[3] / "config" / "systems.toml").read_text()
        path = tmp_path / "systems.toml"
        path.write_text(base.replace("[archive]", f"[archive]\n{extra}"))
        return path

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TRANSITLIVE_S3_BUCKET", raising=False)
        config = load_config()
        assert config.archive == ArchiveSettings(keep_snapshot_days=3, database_days=90)
        assert config.collector.prediction_threshold_seconds == 30

    def test_s3_from_the_file_or_the_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TRANSITLIVE_S3_BUCKET", raising=False)
        path = self.write(tmp_path, 's3_bucket = "from-file"\ns3_prefix = "p/"\ns3_region = "ca-central-1"')
        assert load_config(path).archive.s3_bucket == "from-file"
        monkeypatch.setenv("TRANSITLIVE_S3_BUCKET", "from-env")
        archive = load_config(path).archive
        assert (archive.s3_bucket, archive.s3_prefix, archive.s3_region) == ("from-env", "p/", "ca-central-1")

    def test_unsafe_values_are_refused(self) -> None:
        with pytest.raises(ValueError, match="keep_snapshot_days"):
            ArchiveSettings(keep_snapshot_days=0)
        with pytest.raises(ValueError, match="database_days"):
            ArchiveSettings(database_days=20)
        assert ArchiveSettings(database_days=0).database_days == 0


def test_maintenance_runs_shortly_after_midnight_utc() -> None:
    midnight = dt.datetime(2026, 10, 15, tzinfo=dt.UTC).timestamp()
    assert seconds_until_maintenance(midnight) == 10 * 60
    assert seconds_until_maintenance(midnight + 10 * 60) == 6 * 3600
    assert seconds_until_maintenance(midnight - 60) == 11 * 60
    assert seconds_until_maintenance(midnight + 7 * 3600) == 5 * 3600 + 10 * 60  # 07:00 -> 12:10
