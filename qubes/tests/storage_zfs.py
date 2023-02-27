""" Tests for the ZFS storage driver """

# FIXME: copy tests from storage_reflink and storage_lvm when it makes sense.
# pylint: disable=protected-access
# pylint: disable=invalid-name

import asyncio
import dataclasses
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import qubes.storage as storage
import qubes.storage.zfs as zfs
import qubes.tests
import qubes.tests.storage as ts
import qubes.vm.appvm

from typing import Tuple, Dict, Any, List, Coroutine, Optional
from unittest.mock import patch

DUMP_POOL_AFTER_EACH_TEST = os.getenv("ZFS_DUMP_POOL_AFTER_EACH_TEST", "")
# DUMP_POOL_AFTER_EACH_TEST = True


def _VOLCFG(pool: str, **kwargs: Any) -> Dict[str, Any]:
    d = {
        "name": "root",
        "pool": pool,
        "rw": True,
        "size": 1024 * 1024,
    }
    for k, v in kwargs.items():
        d[k] = v
    return d


def ONEMEG_SAVE_ON_STOP(pool: str, **kwargs: Any) -> Dict[str, Any]:
    return _VOLCFG(pool, save_on_stop=True, **kwargs)


def ONEMEG_SNAP_ON_START(pool: str, **kwargs: Any) -> Dict[str, Any]:
    return _VOLCFG(pool, snap_on_start=True, **kwargs)


def call_no_output(cmd: List[str]) -> int:
    with open(os.devnull, "ab") as devnull:
        return subprocess.call(cmd, stdout=devnull, stderr=subprocess.STDOUT)


def call_output(cmd: List[str]) -> str:
    return subprocess.getoutput(shlex.join(cmd)).rstrip()


def skip_unless_zfs_available(test_item: Any) -> Any:
    """Decorator that skips ZFS tests if ZFS is missing."""
    avail = shutil.which("zfs") and shutil.which("zpool")
    msg = "Either the zfs command or the zpool command are not available."
    return unittest.skipUnless(avail, msg)(test_item)


class TestApp(qubes.Qubes):
    """A Mock App object"""

    def __init__(
        self, *args: Any, **kwargs: Any  # pylint: disable=unused-argument
    ) -> None:
        super().__init__(  # type: ignore
            "/tmp/qubes-zfs-test.xml",
            load=False,
            offline_mode=True,
            **kwargs,
        )
        self.load_initial_values()  # type: ignore


def setup_test_zfs_pool(pool_name: str) -> Tuple[str, str]:
    name = pool_name
    container = f"{name}/vms"
    want = 32 * 1024 * 1024 * 1024

    def freebytes(directory: str, without: str) -> int:
        free = os.statvfs(directory).f_blocks * os.statvfs(directory).f_bfree
        if os.path.isfile(without):
            # Compute the free space by adding the on-disk usage of the
            # file `without` to the free space.
            realsize = int(
                subprocess.run(
                    [
                        "du",
                        "--block-size=1",
                        without,
                    ],
                    capture_output=True,
                    check=True,
                    universal_newlines=True,
                ).stdout.split()[0]
            )
            free += realsize
        return free

    if os.path.ismount("/rw") and freebytes("/rw", f"/rw/{name}.img") > want:
        data_file = f"/rw/{name}.img"
    elif freebytes("/var/tmp", f"/var/tmp/{name}.img") > want:
        data_file = f"/var/tmp/{name}.img"
    else:
        assert 0, (
            "not enough disk space (32GiB) in /rw or "
            "/var/tmp to proceed with test ZFS pool creation"
        )
    with open(data_file, "wb") as f:
        f.seek(want - 1)
        f.write(b"\0")

    listres = call_no_output(["zpool", "list", pool_name])
    if listres == 0:
        cmd = ["sudo", "zpool", "destroy", "-f", pool_name]
        subprocess.check_call(cmd)
    cmd = ["sudo", "zpool", "create", "-f", pool_name, data_file]
    subprocess.check_call(cmd)
    return data_file, container


def teardown_test_zfs_pool(data_file: str, pool_name: str) -> None:
    cmd = ["sudo", "zpool", "destroy", pool_name]
    subprocess.check_call(cmd)
    os.unlink(data_file)


def dump_zfs_filesystems(text: str = "", dataset: str = "") -> None:
    print(text, file=sys.stderr)
    subprocess.call(
        f"zfs list -t all -r -o name,origin,used {dataset}>&2",
        shell=True,
    )


class AsyncLoopHolderMixin(qubes.tests.QubesTestCase):
    def rc(self, future: Coroutine[Any, Any, Any]) -> Any:
        return self.loop.run_until_complete(future)  # type:ignore


class ZFSBase(AsyncLoopHolderMixin):
    pool_name = None
    container = None
    data_file = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.pool_name = "testpool"
        cls.data_file, cls.container = setup_test_zfs_pool(
            cls.pool_name,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        assert cls.data_file
        assert cls.pool_name
        teardown_test_zfs_pool(
            cls.data_file,
            cls.pool_name,
        )
        super().tearDownClass()

    def writable(self, volume_path: str) -> str:
        subprocess.check_call(["sudo", "chmod", "ugo+rw", volume_path])
        return volume_path

    def setUp(self) -> None:
        super().setUp()  # type:ignore
        pool_conf = {
            "driver": "zfs",
            "container": self.container,
            "name": "test-zfs",
        }
        self.app = TestApp()
        self.pool: zfs.ZFSPool = self.rc(
            self.app.add_pool(**pool_conf),  # type: ignore
        )
        self.app.default_pool = self.app.get_pool(
            pool_conf["name"],
        )  # type: ignore

    def tearDown(self) -> None:
        self.app.default_pool = "varlibqubes"
        self.rc(self.app.remove_pool(self.pool.name))  # type: ignore
        del self.pool
        self.app.close()  # type: ignore
        del self.app
        super().tearDown()
        # Dump if dumped.
        if DUMP_POOL_AFTER_EACH_TEST:
            self.dump()

    def dump(self, text: str = "") -> None:
        """Helper method to type less."""
        return dump_zfs_filesystems(text, self.pool.container)

    def assert_dataset_property_equals(
        self, dataset: str, propname: str, value: str
    ) -> None:
        cmd = ["zfs", "list", "-Hp", "-o", propname, dataset]
        actual = call_output(cmd)
        self.assertEqual(actual, value)

    def assert_dataset_property_not_equals(
        self, dataset: str, propname: str, value: str
    ) -> None:
        cmd = ["zfs", "list", "-Hp", "-o", propname, dataset]
        actual = call_output(cmd)
        self.assertNotEqual(actual, value)

    def assert_dataset_exists(self, dataset: str) -> None:
        assert (
            call_no_output(["zfs", "list", dataset]) == 0
        ), f"{dataset} does not exist"

    def assert_dataset_does_not_exist(self, dataset: str) -> None:
        try:
            self.assert_dataset_exists(dataset)
        except AssertionError:
            return
        assert 0, f"{dataset} exists when it should not"


class TC_01_ZFSPool_solidstate(AsyncLoopHolderMixin):
    def test_random_string(self):
        self.assertEqual(zfs.get_random_string(5, "a"), "aaaaa")

    def test_fail_unless_exists_async(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = os.path.join(tmpdir, "x")
            with self.assertRaises(storage.StoragePoolException):
                self.rc(zfs.fail_unless_exists_async(nonexistent))
            with open(nonexistent, "w", encoding="utf-8") as f:
                f.write("now it exists")
            self.rc(zfs.fail_unless_exists_async(nonexistent))

    def test_wait_for_device_async(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nonexistent = os.path.join(tmpdir, "x")

            async def waiter() -> None:
                await zfs.wait_for_device_async(nonexistent)

            async def creator() -> None:
                await asyncio.sleep(0.25)
                with open(nonexistent, "w", encoding="utf-8") as f:
                    f.write("now it exists")

            self.rc(asyncio.gather(waiter(), creator()))

    def test_dataset_in_root(self):
        self.assertTrue(zfs.dataset_in_root("a/b", "a"))
        self.assertTrue(zfs.dataset_in_root("a", "a"))
        self.assertFalse(zfs.dataset_in_root("a", "a/b"))

    def test_timestamp_to_revision(self):
        self.assertEqual(
            "dataset@" + zfs.timestamp_to_revision(123, "abc"),
            "dataset@qubes:abc:123.000000",
        )
        self.assertTrue(
            zfs.is_revision_dataset(
                zfs.VolumeSnapshot.make("dataset", "qubes:cause:123")
            )
        )
        self.assertFalse(
            zfs.is_revision_dataset(
                zfs.VolumeSnapshot.make("dataset", "qubes-cause-123")
            )
        )

    def test_is_clean_snapshot(self):
        snap = zfs.VolumeSnapshot.make("dataset", "qubes-clean-SnefS")
        assert snap.is_clean_snapshot()

    def test_dd(self):
        log = logging.getLogger(__name__)
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "in")
            dst = os.path.join(tmpdir, "out")
            with open(src, "w", encoding="utf-8") as f:
                f.write("now it exists")
            with open(dst, "w", encoding="utf-8") as f:
                f.write("former content")
            self.rc(zfs.duplicate_disk(src, dst, log))
            with open(dst, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "now it exists")
            falsesrc = os.path.join(tmpdir, "unrelated")
            with self.assertRaises(storage.StoragePoolException):
                self.rc(zfs.duplicate_disk(falsesrc, dst, log))


@skip_unless_zfs_available
class TC_10_ZFSPool(ZFSBase):

    vols_created_during_test: Optional[List[zfs.ZFSVolume]] = None

    def setUp(self) -> None:
        super().setUp()
        self.vols_created_during_test = []

    def tearDown(self) -> None:
        if self.vols_created_during_test:
            for v in self.vols_created_during_test:
                # Lazy cleanup here.
                self.rc(v.stop())
                self.rc(v.remove())
        super().tearDown()

    def get_vol(self, factory: Any, **kwargs: Any) -> zfs.ZFSVolume:
        volume = self.pool.init_volume(
            ts.TestVM(self),  # type:ignore
            factory(self.pool.name, **kwargs),
        )
        assert isinstance(self.vols_created_during_test, list)
        self.vols_created_during_test.insert(0, volume)
        return volume

    def test_000_harness(self) -> None:
        """No test.  If this passes the test harness worked."""

    def test_010_create_remove_saveonstop(self) -> None:
        """
        Test that a save_on_stop volume can be created and exists, then that
        it can be torn down and it vanished after teardown.
        """
        volume = self.get_vol(ONEMEG_SAVE_ON_STOP)
        self.rc(volume.create())
        self.assert_dataset_exists(volume.volume)
        self.assert_dataset_property_not_equals(
            volume.volume,
            "com.sun:auto-snapshot",
            "false",
        )
        self.rc(volume.remove())
        self.assert_dataset_does_not_exist(volume.volume)

    def write(self, path: str, text: str):
        with open(self.writable(path), "w+", encoding="utf-8") as v:
            v.write(text)

    def read(self, path: str, length: int) -> str:
        with open(self.writable(path), "r", encoding="utf-8") as v:
            return v.read(length)

    def test_011_saveonstop_persists_data(self) -> None:
        """
        Test that a save-on-stop volume saves data across `stop()`/`start()`.
        """
        volume = self.get_vol(ONEMEG_SAVE_ON_STOP)
        self.rc(volume.create())
        self.rc(volume.start())
        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)
        self.write(voldev, "test data")
        self.rc(volume.stop())
        self.rc(volume.start())
        r = self.read(voldev, 10)
        assert r.startswith("test data"), "volume did not persist data"

    def test_012_export_import(self) -> None:
        """
        Test that writing to an exported volume does not make data go into the
        volume, but that *importing* data to the volume does make the data go
        into the volume.
        """
        volume = self.get_vol(ONEMEG_SAVE_ON_STOP)
        self.rc(volume.create())

        # Export volume to device.
        exported = self.rc(volume.export())
        prefixlen = len(zfs.ZVOL_DIR) + 1
        exported_vol = exported[prefixlen:]
        self.assert_dataset_property_equals(
            exported_vol,
            "com.sun:auto-snapshot",
            "false",
        )
        # Write to the exported device.  This should NOT make it into the
        # volume data, as the exported device is independent of the volume.
        self.write(exported, "test data")
        # Unexport the volume.
        self.rc(volume.export_end(exported))

        # Export volume to device again.
        exported = self.rc(volume.export())
        # Read from the exported device, verifying the data did not
        # make it into the volume.
        data = self.read(exported, 20)
        assert not data.startswith("test data")
        # Unexport the volume.
        self.rc(volume.export_end(exported))

        # Import the following (zero-length) data into the volume.
        import_path = self.rc(volume.import_data(volume.size))

        self.write(import_path, "test data")
        self.rc(volume.import_data_end(True))
        self.assertFalse(
            os.path.exists(import_path),
            f"{import_path} was not removed",
        )

        # Export the volume again to check that the data was imported.
        exported = self.rc(volume.export())
        data = self.read(exported, 20)
        assert data.startswith("test data")
        # Unexport the volume.
        self.rc(volume.export_end(exported))

    def test_013_resize_saveonstop(self) -> None:
        """Test that a volume can be enlarged, but cannot be shrunk."""
        volume = self.get_vol(ONEMEG_SAVE_ON_STOP)
        self.rc(volume.create())

        # Enlarge!
        newsize = 2 * 1024 * 1024
        self.rc(volume.resize(newsize))
        self.assertEqual(
            volume.size,
            newsize,
            f"volume.size {volume.size} != newsize {newsize}",
        )

        # Fail at shrinking.
        self.assertRaises(
            storage.StoragePoolException,
            lambda: self.rc(volume.resize(1024 * 1024)),
        )

    def test_014_snaponstart_forgets_data(self) -> None:
        """
        Test that a snap-on-start volume drops data across `stop()`/`start()`.
        """
        # Create source volume, to clone the snap-on-start
        # volume from
        source = self.get_vol(ONEMEG_SAVE_ON_STOP, name="014")
        self.rc(source.create())
        # Create the snap-on-start volume.
        volume = self.get_vol(
            ONEMEG_SNAP_ON_START,
            source=source,
            name="rootclone",
        )
        self.rc(volume.create())
        self.rc(volume.start())
        self.assert_dataset_property_equals(
            volume.volume,
            "com.sun:auto-snapshot",
            "false",
        )
        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)

        self.write(voldev, "test data")
        self.rc(volume.stop())
        self.rc(volume.start())
        r = self.read(voldev, 10)
        assert not r.startswith("test data"), "volume persisted data"

    def test_015_saveonstop_usage(self) -> None:
        """
        Test disk space usage of a save-on-stop volume.
        """
        volume = self.get_vol(ONEMEG_SAVE_ON_STOP, name="015")
        self.rc(volume.create())
        self.rc(volume.start())
        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)
        self.write(voldev, "0123456789abcdef" * 1024 * int(1024 / 16))
        self.rc(volume.stop())
        # This should be close to what we want.
        assert volume.usage > 1024 * 1024 - 25 * 1024, volume.usage

    def test_016_resize_saveonstop(self) -> None:
        """Test that a volume does in fact enlarge after start."""
        volume = self.get_vol(ONEMEG_SAVE_ON_STOP, name="016")
        self.rc(volume.create())
        self.rc(volume.start())

        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)
        self.writable(voldev)

        def seekandwrite() -> None:
            with open(voldev, "w", encoding="utf-8") as v:
                v.seek(1536 * 1024)  # seek past one meg
                v.write("hells yeah")

        # This must fail
        self.assertRaises(OSError, seekandwrite)

        # Enlarge!
        self.rc(volume.resize(2 * 1024 * 1024))
        # This must not fail.
        seekandwrite()
        self.rc(volume.stop())

    def test_017_saveonstop_can_revert(self) -> None:
        """
        Test that a save-on-stop volume reverts successfully.
        """
        volume = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="017",
            revisions_to_keep=2,  # Otherwise our first snapshot bye bye.
        )
        # Make the volume.
        self.rc(volume.create())
        # Make a note of the latest clean snapshot (all zeros).
        snapshot_before_start, _ = volume.latest_revision
        # Start and write some data to it, then stop.
        self.rc(volume.start())
        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)
        self.write(voldev, "test data")
        self.rc(volume.stop())
        # Now revert.  Our volume should no longer contain what we
        # recently wrote to it.
        self.rc(volume.revert(snapshot_before_start))
        self.rc(volume.start())
        r = self.read(voldev, 10)
        assert not r.startswith("test data"), "volume did not revert"
        self.rc(volume.stop())

    def test_018_saveonstop_clone_correct_data_when_clean(self) -> None:
        """
        Test that the clone of a save-on-stop volume, performed right after
        stop (when it's clean), contains the data written to the volume
        during execution of the VM.
        """
        volume = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="018",
        )
        # Make the volume.
        self.rc(volume.create())
        # Start and write some data to it, then stop.
        self.rc(volume.start())
        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)
        self.write(voldev, "test 018")
        self.rc(volume.stop())

        # Let's clone volume2 from volume.
        volume2 = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="018-2",
            # No source, we later import it using Qubes codebase.
        )
        self.rc(volume2.create())
        self.rc(volume2.import_volume(volume))

        # Check that we imported the very latest data from the
        # (clean after stop) volume.
        # Test prompted by Debu's observations.
        voldev = os.path.join(zfs.ZVOL_DIR, volume2.volume)
        r = self.read(voldev, 10)
        assert r.startswith("test 018"), "volume did not commit correctly"
        self.rc(volume2.stop())

    def test_019_saveonstop_clone_correct_data_when_dirty(self) -> None:
        """
        Test that the clone of a save-on-stop volume, performed when the VM
        is running (and the volume is therefore dirty), contains the data
        written to the volume before start of the VM.
        """
        volume = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="019",
        )
        # Make the volume.
        self.rc(volume.create())
        # Start and write some data to it, then stop.
        self.rc(volume.start())
        voldev = os.path.join(zfs.ZVOL_DIR, volume.volume)
        self.write(voldev, "test 019")

        # Let's clone volume2 from volume.
        volume2 = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="019-2",
            # No source, we later import it using Qubes codebase.
        )
        self.rc(volume2.create())
        self.rc(volume2.import_volume(volume))

        # Check that we imported the very latest data from the
        # (clean after stop) volume.
        # Test prompted by Debu's observations.
        voldev = os.path.join(zfs.ZVOL_DIR, volume2.volume)
        r = self.read(voldev, 10)
        assert not r.startswith("test 019"), "volume did not commit correctly"
        self.rc(volume2.stop())
        self.rc(volume.stop())

    def test_020_saveonstop_clone_from_snaponstart(self) -> None:
        """
        Ensure a snap on start volume only sees the contents of its source
        once its source has been stopped (therefore is clean), the snap on
        start volume has been stopped, and then started again.

        This behavior is what you see when you turn off your TemplateVM,
        turn off your AppVM and restart the AppVM once again -- the *clean*
        contents of the root file system of the TemplateVM become visible
        to the AppVM, but *only after both* were shut off.
        """
        # Create source volume, to clone the snap-on-start
        # volume from
        source = self.get_vol(ONEMEG_SAVE_ON_STOP, name="020")
        self.rc(source.create())

        # Create target volume, the import from source volume.
        # This should never be the case.  Snap on start volumes
        # must instead be *sourced* from a save on stop volume.
        self.assertRaises(
            storage.StoragePoolException,
            lambda: self.get_vol(ONEMEG_SNAP_ON_START, name="020-2"),
        )

        # Create target volume by using the source mechanism.
        # This should work correctly.
        target = self.get_vol(
            ONEMEG_SNAP_ON_START,
            name="020-3",
            source=source,
        )
        self.rc(target.create())
        self.rc(target.start())
        self.assert_dataset_property_equals(
            target.volume,
            "com.sun:auto-snapshot",
            "false",
        )
        voldev = os.path.join(zfs.ZVOL_DIR, target.volume)
        with open(self.writable(voldev), "rb") as v:
            r = v.read(1)
        # Should be all zeroes, since it cloned from the empty
        # save on stop volume, recently created.
        self.assertEqual(r, b"\0")

        # Now let's write to the source volume, see how this goes.
        self.rc(source.start())
        voldev = os.path.join(zfs.ZVOL_DIR, source.volume)
        self.write(voldev, "test 020")

        # Should still be all zeroes, since the clone must have proceeded
        # from the clean snapshot of the now-dirty save on stop volume.
        voldev = os.path.join(zfs.ZVOL_DIR, target.volume)
        with open(self.writable(voldev), "rb") as dev:
            r = dev.read(1)
        self.assertEqual(r, b"\0")

        # Now let's stop the source, stop the target, and start the target
        # once again.
        self.rc(source.stop())
        self.rc(target.stop())
        self.rc(target.start())

        # Now, since both the target and the source were stopped, and
        # therefore are clean, upon new start of the target, it should
        # have the data written to the source before stop.
        voldev = os.path.join(zfs.ZVOL_DIR, target.volume)
        rstr = self.read(voldev, 8)
        self.assertEqual(rstr, "test 020")

    def test_021_saveonstop_clone_removed_lifo(self) -> None:
        """
        Ensure a save on stop volume and its save on stop clone can be created,
        then that the clone and the save on stop volume can be removed, in
        that order.

        This is the natural order in which we expect removals to happen,
        although another test case covers the opposite removal order.
        """
        # Create source volume.
        source = self.get_vol(ONEMEG_SAVE_ON_STOP, name="021")
        self.rc(source.create())
        self.rc(source.start())
        self.rc(source.stop())

        # Let's import clone from source, start then stop it.
        clone = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="021-import",
        )
        self.rc(clone.create())
        self.rc(clone.import_volume(source))
        self.rc(clone.start())
        self.rc(clone.stop())

        self.rc(clone.remove())
        self.rc(source.remove())

    def test_022_saveonstop_clone_removed_fifo(self) -> None:
        """
        Ensure a save on stop volume and its save on stop clone can be created,
        then that the save on stop volume can be removed *first* and the clone
        removed last.
        """
        # Create source volume.
        source = self.get_vol(ONEMEG_SAVE_ON_STOP, name="022")
        self.rc(source.create())
        self.rc(source.start())
        self.rc(source.stop())

        # Let's import clone from source, start then stop it.
        clone = self.get_vol(
            ONEMEG_SAVE_ON_STOP,
            name="022-import",
        )
        self.rc(clone.create())
        self.rc(clone.import_volume(source))
        self.rc(clone.start())
        self.rc(clone.stop())

        # Now we remove the source.  Obviously the source's snapshots must be
        # promoted by the code to the clone, so the source can then be deleted.
        self.rc(source.remove())
        self.rc(clone.remove())

    def test_023_forensics_feature(self) -> None:
        """
        Ensure a forensics-enable snap-on-start volume is conserved when
        the volume is stopped.
        """
        # Create source volume.
        source = self.get_vol(ONEMEG_SAVE_ON_STOP, name="023")
        self.rc(source.create())

        cloned = self.get_vol(
            ONEMEG_SNAP_ON_START,
            name="023-clone",
            source=source,
            snap_on_start_forensics=True,
        )
        self.rc(cloned.create())
        self.rc(cloned.start())
        self.rc(cloned.stop())

        # Now check the dataset exists.
        self.assert_dataset_exists(cloned.volume)

    def test_024_volume_names(self) -> None:
        v = self.get_vol(ONEMEG_SAVE_ON_STOP, name="024")
        join = os.path.join
        self.assertEqual(
            v.exported_volume_name(),
            join(v.pool.container, ".exported", v.vid.replace("/", "_")),
        )
        self.assertEqual(
            v.exported_volume_name("a"),
            join(v.pool.container, ".exported", v.vid.replace("/", "_"), "a"),
        )
        self.assertEqual(
            v.importing_volume_name,
            join(v.pool.container, ".importing", v.vid.replace("/", "_")),
        )

    def test_025_failed_import_volume_is_safe(self) -> None:
        """
        Test that a midway-interrupted failed volume import preserves the
        data on the destination volume when the import fails midway.
        """

        @dataclasses.dataclass
        class Voldata:
            vol: zfs.ZFSVolume
            data: str

        src = Voldata(
            self.get_vol(ONEMEG_SAVE_ON_STOP, name="025-source"),
            "source",
        )
        tgt = Voldata(
            self.get_vol(ONEMEG_SAVE_ON_STOP, name="025-target"),
            "target",
        )

        def init():
            for vol in [src, tgt]:
                # Make the volume.
                self.rc(vol.vol.create())
                # Start and write some data to it, then stop.
                self.rc(vol.vol.start())
                voldev = os.path.join(zfs.ZVOL_DIR, vol.vol.volume)
                self.write(voldev, vol.data)
                self.rc(vol.vol.stop())

        def deinit():
            for vol in [src, tgt]:
                self.rc(vol.vol.remove())

        # First init.
        init()
        self.rc(tgt.vol.import_volume(src.vol))

        # Check the successful, happy path first.
        self.rc(tgt.vol.start())
        voldev = os.path.join(zfs.ZVOL_DIR, tgt.vol.volume)
        r = self.read(voldev, 10)
        assert r.startswith(src.data), "volume did not commit correctly"
        self.rc(tgt.vol.stop())

        # Reinitialize.
        deinit()
        init()

        # Mock a failure
        with patch.object(
            tgt.vol.pool.accessor,
            "clone_snapshot_to_volume_async",
            side_effect=storage.StoragePoolException("mocked failure!"),
        ):
            with self.assertRaises(storage.StoragePoolException):
                # Fail clone!
                self.rc(tgt.vol.import_volume(src.vol))

        self.rc(tgt.vol.start())
        voldev = os.path.join(zfs.ZVOL_DIR, tgt.vol.volume)
        r = self.read(voldev, 10)
        assert r.startswith(tgt.data), "error handler did not keep target safe"
        self.rc(tgt.vol.stop())

        # Fin
        deinit()
