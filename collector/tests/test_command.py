import datetime as dt
import io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from collector.backup import PREFIX, backup
from collector.models import CollectRun


def call(*args):
    out = io.StringIO()
    call_command('collect_lun', *args, stdout=out, stderr=io.StringIO())
    return out.getvalue()


def finished_run(status):
    return CollectRun(started_at=timezone.now(), finished_at=timezone.now(), status=status, rows_upserted=0)


class CollectCommandTests(TestCase):
    def test_if_stale_skips_after_a_recent_success(self):
        CollectRun.objects.create(started_at=timezone.now() - dt.timedelta(days=2), status=CollectRun.Status.OK)
        with mock.patch('collector.management.commands.collect_lun.collect') as collect:
            self.assertIn('skipped', call('--if-stale'))
        collect.assert_not_called()

    def test_if_stale_runs_when_old(self):
        CollectRun.objects.create(started_at=timezone.now() - dt.timedelta(days=9), status=CollectRun.Status.OK)
        with mock.patch('collector.management.commands.collect_lun.collect',
                        return_value=finished_run(CollectRun.Status.OK)) as collect:
            call('--if-stale')
        collect.assert_called_once()

    def test_city_filter(self):
        with mock.patch('collector.management.commands.collect_lun.collect',
                        return_value=finished_run(CollectRun.Status.OK)) as collect:
            call('--city', 'kyiv', '--city', 'lviv')
        self.assertEqual(sorted(c.slug for c in collect.call_args.args[0]), ['kyiv', 'lviv'])

    def test_unknown_city(self):
        with self.assertRaises(CommandError):
            call('--city', 'atlantis')

    def test_failed_run_is_an_error_and_skips_backup(self):
        with mock.patch('collector.management.commands.collect_lun.collect',
                        return_value=finished_run(CollectRun.Status.FAILED)), \
                mock.patch('collector.management.commands.collect_lun.backup_from_settings') as backup_mock:
            with self.assertRaises(CommandError):
                call('--backup')
        backup_mock.assert_not_called()

    def test_skips_when_another_collection_holds_the_lock(self):
        with mock.patch('collector.management.commands.collect_lun.try_lock', return_value=False), \
                mock.patch('collector.management.commands.collect_lun.collect') as collect:
            self.assertIn('Another collection', call())
        collect.assert_not_called()

    @override_settings(BACKUP={'DIR': '', 'KEEP': 8})
    def test_backup_off_without_dir(self):
        with mock.patch('collector.management.commands.collect_lun.collect',
                        return_value=finished_run(CollectRun.Status.OK)):
            self.assertIn('BACKUP_DIR not set', call('--backup'))


class BackupTests(TestCase):
    def test_keeps_the_newest_dumps(self):
        with TemporaryDirectory() as tmp, mock.patch('collector.backup.subprocess.run') as run:
            for name in ('20250101-000000', '20250102-000000', '20250103-000000'):
                (Path(tmp) / f'{PREFIX}{name}.dump').write_bytes(b'x')
            run.side_effect = lambda args, **kw: Path(args[3].removeprefix('--file=')).write_bytes(b'new')
            target = backup(tmp, keep=2)
            left = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(len(left), 2)
        self.assertIn(target.name, left)
        self.assertIn(f'{PREFIX}20250103-000000.dump', left)
