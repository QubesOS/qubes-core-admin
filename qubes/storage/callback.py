#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2020  David Hobach <david@hobach.de>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

# pylint: disable=line-too-long

import logging
import subprocess
import json
import asyncio
import threading
from shlex import quote
from qubes.utils import coro_maybe

import qubes.storage

class UnhandledSignalException(qubes.storage.StoragePoolException):
    def __init__(self, pool, signal):
        super().__init__('The pool %s failed to handle the signal %s, likely because it was run from synchronous code.' % (pool.name, signal))

class CallbackPool(qubes.storage.Pool):
    ''' Proxy storage pool driver adding callback functionality to other pool drivers.

    This way, users can extend storage pool drivers with custom functionality using the programming language of their choice.

    All configuration for this pool driver must be done in `/etc/qubes_callback.json`. Each configuration ID `conf_id` can be used
    to create a callback pool with e.g. `qvm-pool -o conf_id=your_conf_id -a pool_name callback`.
    Check `/usr/share/doc/qubes/qubes_callback.json.example` for an overview of the available options.

    Example applications of this driver:
        - custom pool mounts
        - encryption
        - debugging
        - run synchronous pool drivers asynchronously

    A word of caution:
    This implementation runs all methods that `qubes.storage.Pool` allows to be asynchronous asynchronously. So if a backend pool driver does
    not support a particular method to be run asynchronously, there may be issues. In short, it is always preferable to use the original backend
    driver over this one unless the functionality of this driver is required for a particular use case.


    **Integration tests**:
    (all of these tests assume the `qubes_callback.json.example` configuration)

    Tests that should **fail**:
    ```
    qvm-pool -a test callback
    qvm-pool -o conf_id=non-existing -a test callback
    qvm-pool -o conf_id=conf_id -a test callback
    qvm-pool -o conf_id=testing-fail-missing-all -a test callback
    qvm-pool -o conf_id=testing-fail-missing-bdriver-args -a test callback
    ```

    Tests that should **work**:
    ```
    qvm-pool -o conf_id=testing-succ-file-01 -a test callback
    qvm-pool
    ls /mnt/test01
    qvm-pool -r test && sudo rm -rf /mnt/test01

    echo '#!/bin/bash'$'\n''i=1 ; for arg in "$@" ; do echo "$i: $arg" >> /tmp/callback.log ; (( i++)) ; done ; exit 0' > /usr/bin/testCbLogArgs && chmod +x /usr/bin/testCbLogArgs
    rm -f /tmp/callback.log
    qvm-pool -o conf_id=testing-succ-file-02 -a test callback
    qvm-pool
    ls /mnt/test02
    less /tmp/callback.log (post_ctor & pre_setup should be there and in that order)
    qvm-create -l red -P test test-vm
    cat /tmp/callback.log (2x pre_volume_create should be added)
    qvm-start test-vm
    qvm-volume | grep test-vm
    grep test-vm /var/lib/qubes/qubes.xml
    ls /mnt/test02/appvms/
    cat /tmp/callback.log (2x pre_volume_start & 2x post_volume_start should be added)
    qvm-shutdown test-vm
    cat /tmp/callback.log (2x post_volume_stop should be added)
    #reboot
    cat /tmp/callback.log (only (!) post_ctor should be there)
    qvm-start test-vm
    cat /tmp/callback.log (pre_sinit & 2x pre_volume_start & 2x post_volume_start should be added)
    qvm-shutdown --wait test-vm && qvm-remove test-vm
    qvm-pool -r test && sudo rm -rf /mnt/test02
    less /tmp/callback.log (2x post_volume_stop, 2x post_volume_remove, post_destroy should be added)

    qvm-pool -o conf_id=testing-succ-file-02 -a test callback
    qvm-create -l red -P test test-dvm
    qvm-prefs test-dvm template_for_dispvms True
    qvm-run --dispvm test-dvm xterm
    grep -E 'test-dvm|disp' /var/lib/qubes/qubes.xml
    qvm-volume | grep -E 'test-dvm|disp' (unexpected by most users: Qubes OS places only the private volume on the pool, cf. #5933)
    ls /mnt/test02/appvms/
    cat /tmp/callback.log
    #close the disposable VM
    qvm-remove test-dvm
    qvm-pool -r test

    qvm-pool -o conf_id=testing-succ-file-03 -a test callback
    qvm-pool
    ls /mnt/test03
    less /tmp/callback.log (post_ctor & pre_setup should be there, no more arguments)
    qvm-pool -r test && sudo rm -rf /mnt/test03
    less /tmp/callback.log (nothing should have been added)

    #luks pool test:
    #(make sure /mnt/test.key & /mnt/test.luks don't exist)
    qvm-pool -o conf_id=testing-succ-file-luks -a tluks callback
    ls /mnt/
    qvm-pool
    sudo cryptsetup status test-luks
    sudo mount | grep test_luks
    ls /mnt/test_luks/
    qvm-create -l red -P tluks test-luks (journalctl -b0 should show two pre_volume_create callbacks)
    ls /mnt/test_luks/appvms/test-luks/
    qvm-volume | grep test-luks
    qvm-start test-luks
    #reboot
    grep luks /var/lib/qubes/qubes.xml
    sudo cryptsetup status test-luks (should be inactive due to late pre_sinit!)
    qvm-start test-luks
    sudo mount | grep test_luks
    qvm-shutdown --wait test-luks
    qvm-remove test-luks
    qvm-pool -r tluks
    sudo cryptsetup status test-luks
    ls -l /mnt/

    #ephemeral luks pool test (key in RAM / lost on reboot):
    qvm-pool -o conf_id=testing-succ-file-luks-eph -a teph callback (executes setup() twice due to signal_back)
    ls /mnt/
    ls /mnt/ram
    md5sum /mnt/ram/teph.key (1)
    sudo mount|grep -E 'ram|test'
    sudo cryptsetup status test-eph
    qvm-create -l red -P teph test-eph (should execute two pre_volume_create callbacks)
    qvm-volume | grep test-eph
    ls /mnt/test_eph/appvms (should have private.img and volatile.img)
    ls /var/lib/qubes/appvms/test-eph (should only have the icon)
    qvm-start test-eph
    #reboot
    ls /mnt/ram (should be empty)
    ls /mnt/
    sudo mount|grep -E 'ram|test' (should be empty)
    qvm-ls | grep eph (should still have test-eph)
    grep eph /var/lib/qubes/qubes.xml (should still have test-eph)
    qvm-remove test-eph (should create a new encrypted pool backend)
    sudo cryptsetup status test-eph
    grep eph /var/lib/qubes/qubes.xml (only the pool should be left)
    ls /mnt/test_eph/ (should have the appvms directory etc.)
    qvm-create -l red -P teph test-eph2
    ls /mnt/test_eph/appvms/
    ls /mnt/ram
    qvm-start test-eph2
    md5sum /mnt/ram/teph.key ((2), different than in (1))
    qvm-shutdown --wait test-eph2
    systemctl restart qubesd
    qvm-start test-eph2 (trigger storage re-init)
    md5sum /mnt/ram/teph.key (same as in (2))
    qvm-shutdown --wait test-eph2
    sudo umount /mnt/test_eph
    qvm-create -l red -P teph test-eph-fail (must fail with error in journalctl)
    ls /mnt/test_eph/ (should be empty)
    systemctl restart qubesd
    qvm-remove test-eph2
    qvm-create -l red -P teph test-eph3
    md5sum /mnt/ram/teph.key (same as in (2))
    sudo mount|grep -E 'ram|test'
    ls /mnt/test_eph/appvms/test-eph3
    qvm-remove test-eph3
    qvm-ls | grep test-eph
    qvm-pool -r teph
    grep eph /var/lib/qubes/qubes.xml (nothing should be left)
    qvm-pool
    ls /mnt/
    ls /mnt/ram/ (should be empty)
    ```
    '''

    driver = 'callback'
    config_path = '/etc/qubes_callback.json'

    def __init__(self, *, name, conf_id):
        '''Constructor.
        :param conf_id: Identifier as found inside the user-controlled configuration at `/etc/qubes_callback.json`.
                       Non-ASCII, non-alphanumeric characters may be disallowed.
                       **Security Note**: Depending on your RPC policy (admin.pool.Add) this constructor and its parameters
                       may be called from an untrusted VM (not by default though). In those cases it may be security-relevant
                       not to pick easily guessable `conf_id` values for your configuration as untrusted VMs may otherwise
                       execute callbacks meant for other pools.
        :raise StoragePoolException: For user configuration issues.
        '''
        #NOTE: attribute names **must** start with `_cb_` unless they are meant to be stored as self._cb_impl attributes
        self._cb_ctor_done = False #: Boolean to indicate whether or not `__init__` successfully ran through.
        self._cb_log = logging.getLogger('qubes.storage.callback') #: Logger instance.
        if not isinstance(conf_id, str):
            raise qubes.storage.StoragePoolException('conf_id is no String. VM attack?!')
        self._cb_conf_id = conf_id #: Configuration ID as passed to `__init__()`.

        with open(CallbackPool.config_path) as json_file:
            conf_all = json.load(json_file)
        if not isinstance(conf_all, dict):
            raise qubes.storage.StoragePoolException('The file %s is supposed to define a dict.' % CallbackPool.config_path)

        try:
            self._cb_conf = conf_all[self._cb_conf_id] #: Dictionary holding all configuration for the given _cb_conf_id.
        except KeyError:
            #we cannot throw KeyErrors as we'll otherwise generate incorrect error messages @qubes.app._get_pool()
            raise qubes.storage.StoragePoolException('The specified conf_id %s could not be found inside %s.' % (self._cb_conf_id, CallbackPool.config_path))

        try:
            bdriver = self._cb_conf['bdriver']
        except KeyError:
            raise qubes.storage.StoragePoolException('Missing bdriver for the conf_id %s inside %s.' % (self._cb_conf_id, CallbackPool.config_path))

        self._cb_cmd_arg = json.dumps(self._cb_conf, sort_keys=True, indent=2) #: Full configuration as string in the format required by _callback().

        try:
            cls = qubes.utils.get_entry_point_one(qubes.storage.STORAGE_ENTRY_POINT, bdriver)
        except KeyError:
            raise qubes.storage.StoragePoolException('The driver %s was not found on your system.' % bdriver)

        if not issubclass(cls, qubes.storage.Pool):
            raise qubes.storage.StoragePoolException('The class %s must be a subclass of qubes.storage.Pool.' % cls)

        self._cb_requires_init = self._check_init() #: Boolean indicating whether late storage initialization yet has to be done or not.
        self._cb_init_lock = threading.Lock() #: Lock ensuring that late storage initialization is only run exactly once. Currently a `threading.Lock()` to make it accessible from synchronous code as well.
        bdriver_args = self._cb_conf.get('bdriver_args', {})
        self._cb_impl = cls(name=name, **bdriver_args) #: Instance of the backend pool driver.

        super().__init__(name=name, revisions_to_keep=int(bdriver_args.get('revisions_to_keep', 1)))
        self._cb_ctor_done = True
        self._callback_nocoro('post_ctor')

    def _check_init(self):
        ''' Whether or not this object requires late storage initialization via callback. '''
        cmd = self._cb_conf.get('pre_sinit')
        if not cmd:
            cmd = self._cb_conf.get('cmd')
        return bool(cmd and cmd != '-')

    @asyncio.coroutine
    def _init(self, callback=True):
        ''' Late storage initialization on first use for e.g. decryption on first usage request.
        :param callback: Whether to trigger the `pre_sinit` callback or not.
        '''
        with self._cb_init_lock:
            if self._cb_requires_init:
                if callback:
                    yield from self._callback('pre_sinit')
                self._cb_requires_init = False

    def _init_nocoro(self, callback=True):
        ''' `_init()` in synchronous code. '''
        with self._cb_init_lock:
            if self._cb_requires_init:
                if callback:
                    self._callback_nocoro('pre_sinit')
                self._cb_requires_init = False

    @asyncio.coroutine
    def _assert_initialized(self, **kwargs):
        if self._cb_requires_init:
            yield from self._init(**kwargs)

    def _callback_nocoro(self, cb, cb_args=None, handle_signals=True):
        '''Run a callback (variant that can be used outside of coroutines / from synchronous code).
        :param cb: Callback identifier string.
        :param cb_args: Optional list of arguments to pass to the command as last arguments.
                        Only passed on for the generic command specified as `cmd`, not for `on_xyz` callbacks.
        :param handle_signals: Attempt to handle signals locally in synchronous code.
                        May throw an exception, if a callback signal cannot be handled locally.
        :return: String with potentially unhandled signals, if `handle_signals` is `False`. Nothing otherwise.
        '''
        if self._cb_ctor_done:
            cmd = self._cb_conf.get(cb)
            args = [] #on_xyz callbacks should never receive arguments
            if not cmd:
                if cb_args is None:
                    cb_args = []
                cmd = self._cb_conf.get('cmd')
                args = [self.name, self._cb_conf['bdriver'], cb, self._cb_cmd_arg, *cb_args]
            if cmd and cmd != '-':
                args = ' '.join(quote(str(a)) for a in args)
                cmd = ' '.join(filter(None, [cmd, args]))
                self._cb_log.info('callback driver executing (%s, %s %s): %s', self._cb_conf_id, cb, cb_args, cmd)
                res = subprocess.run(['/bin/bash', '-c', cmd], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                #stdout & stderr are reported if the exit code check fails
                self._cb_log.debug('callback driver stdout (%s, %s %s): %s', self._cb_conf_id, cb, cb_args, res.stdout)
                self._cb_log.debug('callback driver stderr (%s, %s %s): %s', self._cb_conf_id, cb, cb_args, res.stderr)
                if self._cb_conf.get('signal_back', False) is True:
                    if handle_signals:
                        self._process_signals_nocoro(res.stdout)
                    else:
                        return res.stdout
        return None

    @asyncio.coroutine
    def _callback(self, cb, cb_args=None):
        '''Run a callback.
        :param cb: Callback identifier string.
        :param cb_args: Optional list of arguments to pass to the command as last arguments.
                        Only passed on for the generic command specified as `cmd`, not for `on_xyz` callbacks.
        '''
        ret = self._callback_nocoro(cb, cb_args=cb_args, handle_signals=False)
        if ret:
            yield from self._process_signals(ret)

    @asyncio.coroutine
    def _process_signals(self, out):
        '''Process any signals found inside a string.
        :param out: String to check for signals. Each signal must be on a dedicated line.
                    They are executed in the order they are found. Callbacks are not triggered.
        '''
        for line in out.splitlines():
            if line == 'SIGNAL_setup':
                self._cb_log.info('callback driver processing SIGNAL_setup for %s', self._cb_conf_id)
                #NOTE: calling our own methods may lead to a deadlock / qubesd freeze due to `self._assert_initialized()` / `self._cb_init_lock`
                yield from coro_maybe(self._cb_impl.setup())

    def _process_signals_nocoro(self, out):
        '''Variant of `process_signals` to be used with synchronous code.
        :param out: String to check for signals. Each signal must be on a dedicated line.
                    They are executed in the order they are found. Callbacks are not triggered.
        :raise UnhandledSignalException: If signals cannot be handled here / in synchronous code.
        '''
        for line in out.splitlines():
            if line == 'SIGNAL_setup':
                raise UnhandledSignalException(self, line)

    @property
    def config(self):
        return {
            'name': self.name,
            'driver': CallbackPool.driver,
            'conf_id': self._cb_conf_id,
        }

    @asyncio.coroutine
    def destroy(self):
        yield from self._assert_initialized()
        ret = yield from coro_maybe(self._cb_impl.destroy())
        yield from self._callback('post_destroy')
        return ret

    def init_volume(self, vm, volume_config):
        ret = CallbackVolume(self, self._cb_impl.init_volume(vm, volume_config))
        volume_config['pool'] = self
        return ret

    @asyncio.coroutine
    def setup(self):
        yield from self._assert_initialized(callback=False) #setup is assumed to include storage initialization
        yield from self._callback('pre_setup')
        return (yield from coro_maybe(self._cb_impl.setup()))

    @property
    def volumes(self):
        for vol in self._cb_impl.volumes:
            yield CallbackVolume(self, vol)

    def list_volumes(self):
        for vol in self._cb_impl.list_volumes():
            yield CallbackVolume(self, vol)

    def get_volume(self, vid):
        return CallbackVolume(self, self._cb_impl.get_volume(vid))

    def included_in(self, app):
        if self._cb_requires_init:
            return None
        return self._cb_impl.included_in(app)

    @property
    def size(self):
        if self._cb_requires_init:
            return None
        return self._cb_impl.size

    @property
    def usage(self):
        if self._cb_requires_init:
            return None
        return self._cb_impl.usage

    #remaining method & attribute delegation ("delegation pattern")
    #Convention: The methods of this object have priority over the delegated object's methods. All attributes are
    #           passed to the delegated object unless their name starts with '_cb_'.
    def __getattr__(self, name):
        #NOTE: This method is only called when an attribute cannot be resolved locally (not part of the instance,
        #       not part of the class tree). It is also called for methods that cannot be resolved.
        return getattr(self._cb_impl, name)

    def __setattr__(self, name, value):
        #NOTE: This method is called on every attribute assignment.
        if name.startswith('_cb_'):
            super().__setattr__(name, value)
        else:
            setattr(self._cb_impl, name, value)

    def __delattr__(self, name):
        if name.startswith('_cb_'):
            super().__delattr__(name)
        else:
            delattr(self._cb_impl, name)

class CallbackVolume(qubes.storage.Volume):
    ''' Proxy volume adding callback functionality to other volumes.

        Required to support the `pre_sinit` and other callbacks.
    '''

    def __init__(self, pool, impl):
        '''Constructor.
        :param pool: `CallbackPool` of this volume
        :param impl: `qubes.storage.Volume` object to wrap
        '''
        # pylint: disable=super-init-not-called
        #NOTE: we must *not* call super().__init__() as it would prevent attribute delegation
        assert isinstance(impl, qubes.storage.Volume), 'impl must be a qubes.storage.Volume instance. Found a %s instance.' % impl.__class__
        assert isinstance(pool, CallbackPool), 'pool must use a qubes.storage.CallbackPool instance. Found a %s instance.' % pool.__class__
        impl.pool = pool #enforce the CallbackPool instance as the parent pool of the volume
        self._cb_pool = pool #: CallbackPool instance the Volume belongs to.
        self._cb_impl = impl #: Backend volume implementation instance.

    @asyncio.coroutine
    def _assert_initialized(self, **kwargs):
        yield from self._cb_pool._assert_initialized(**kwargs) # pylint: disable=protected-access

    @asyncio.coroutine
    def _callback(self, cb, cb_args=None, **kwargs):
        if cb_args is None:
            cb_args = []
        vol_args = [self.name, self.vid, self.source, *cb_args]
        yield from self._cb_pool._callback(cb, cb_args=vol_args, **kwargs) # pylint: disable=protected-access

    @asyncio.coroutine
    def create(self):
        yield from self._assert_initialized()
        yield from self._callback('pre_volume_create')
        return (yield from coro_maybe(self._cb_impl.create()))

    @asyncio.coroutine
    def remove(self):
        yield from self._assert_initialized()
        ret = yield from coro_maybe(self._cb_impl.remove())
        yield from self._callback('post_volume_remove')
        return ret

    @asyncio.coroutine
    def resize(self, size):
        yield from self._assert_initialized()
        yield from self._callback('pre_volume_resize', cb_args=[size])
        return (yield from coro_maybe(self._cb_impl.resize(size)))

    @asyncio.coroutine
    def start(self):
        yield from self._assert_initialized()
        yield from self._callback('pre_volume_start')
        ret = yield from coro_maybe(self._cb_impl.start())
        yield from self._callback('post_volume_start')
        return ret

    @asyncio.coroutine
    def stop(self):
        yield from self._assert_initialized()
        ret = yield from coro_maybe(self._cb_impl.stop())
        yield from self._callback('post_volume_stop')
        return ret

    @asyncio.coroutine
    def import_data(self, size):
        yield from self._assert_initialized()
        yield from self._callback('pre_volume_import_data', cb_args=[size])
        return (yield from coro_maybe(self._cb_impl.import_data(size)))

    @asyncio.coroutine
    def import_data_end(self, success):
        yield from self._assert_initialized()
        ret = yield from coro_maybe(self._cb_impl.import_data_end(success))
        yield from self._callback('post_volume_import_data_end', cb_args=[success])
        return ret

    @asyncio.coroutine
    def import_volume(self, src_volume):
        yield from self._assert_initialized()
        yield from self._callback('pre_volume_import', cb_args=[src_volume.vid])
        return (yield from coro_maybe(self._cb_impl.import_volume(src_volume)))

    def is_dirty(self):
        # pylint: disable=protected-access
        if self._cb_pool._cb_requires_init:
            return False
        return self._cb_impl.is_dirty()

    def is_outdated(self):
        # pylint: disable=protected-access
        if self._cb_pool._cb_requires_init:
            return False
        return self._cb_impl.is_outdated()

    @property
    def revisions(self):
        return self._cb_impl.revisions

    @property
    def size(self):
        return self._cb_impl.size

    @size.setter
    def size(self, size):
        self._cb_impl.size = size

    @property
    def config(self):
        return self._cb_impl.config

    def block_device(self):
        # pylint: disable=protected-access
        if self._cb_pool._cb_requires_init:
            # usually Volume.start() is called beforehand
            # --> we should be initialized in 99% of cases
            return None
        return self._cb_impl.block_device()

    def export(self):
        # pylint: disable=protected-access
        #TODO: once this becomes a coroutine in the Volume class, avoid the below blocking & potentially exception-throwing code; maybe also add a callback
        if self._cb_pool._cb_requires_init:
            self._cb_pool._init_nocoro()
        return self._cb_impl.export()

    @asyncio.coroutine
    def verify(self):
        yield from self._assert_initialized()
        return (yield from coro_maybe(self._cb_impl.verify()))

    @asyncio.coroutine
    def revert(self, revision=None):
        yield from self._assert_initialized()
        return (yield from coro_maybe(self._cb_impl.revert(revision=revision)))

    #remaining method & attribute delegation
    def __getattr__(self, name):
        return getattr(self._cb_impl, name)

    def __setattr__(self, name, value):
        if name.startswith('_cb_'):
            super().__setattr__(name, value)
        else:
            setattr(self._cb_impl, name, value)

    def __delattr__(self, name):
        if name.startswith('_cb_'):
            super().__delattr__(name)
        else:
            delattr(self._cb_impl, name)
