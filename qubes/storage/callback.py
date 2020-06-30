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

import logging
import subprocess
import importlib
import json
from shlex import quote

import qubes.storage

class CallbackPool(qubes.storage.Pool):
    ''' Proxy storage pool driver adding callback functionality to other pool drivers.

    This way, users can extend storage pool drivers with custom functionality using the programming language of their choice.

    All configuration for this pool driver must be done in `/etc/qubes_callback.json`. Each configuration ID `conf_id` can be used
    to create a callback pool with e.g. `qvm-pool -o conf_id=your_conf_id -a pool_name callback`.
    Check the `qubes_callback.json.example` for an overview of the available options.

    Example applications of this driver:
        - custom pool mounts
        - encryption
        - debugging


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
    
    echo '#!/bin/bash'$'\n''i=0 ; for arg in "$@" ; do echo "$i: $arg" >> /tmp/callback.log ; (( i++)) ; done ; exit 0' > /usr/bin/testCbLogArgs && chmod +x /usr/bin/testCbLogArgs
    rm -f /tmp/callback.log
    qvm-pool -o conf_id=testing-succ-file-02 -a test callback
    qvm-pool
    ls /mnt/test02
    less /tmp/callback.log (on_ctor & on_setup should be there and in that order)
    qvm-create -l red -P test test-vm
    cat /tmp/callback.log (2x on_volume_create should be added)
    qvm-start test-vm
    qvm-volume | grep test-vm
    grep test-vm /var/lib/qubes/qubes.xml
    ls /mnt/test02/appvms/
    cat /tmp/callback.log (2x on_volume_start should be added)
    qvm-shutdown test-vm
    cat /tmp/callback.log (2x on_volume_stop should be added)
    #reboot
    cat /tmp/callback.log (only (!) on_ctor should be there)
    qvm-start test-vm
    cat /tmp/callback.log (on_sinit & 2x on_volume_start should be added)
    qvm-shutdown --wait test-vm && qvm-remove test-vm
    qvm-pool -r test && sudo rm -rf /mnt/test02
    less /tmp/callback.log (2x on_volume_stop, 2x on_volume_remove, on_destroy should be added)
    
    qvm-pool -o conf_id=testing-succ-file-03 -a test callback
    qvm-pool
    ls /mnt/test03
    less /tmp/callback.log (on_ctor & on_setup should be there, no more arguments)
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
    qvm-create -l red -P tluks test-luks (journalctl -b0 should show two on_volume_create callbacks)
    ls /mnt/test_luks/appvms/test-luks/
    qvm-volume | grep test-luks
    qvm-start test-luks
    #reboot
    grep luks /var/lib/qubes/qubes.xml
    sudo cryptsetup status test-luks (should be inactive due to late on_sinit!)
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
    qvm-create -l red -P teph test-eph (should execute two on_volume_create callbacks)
    qvm-volume | grep test-eph
    ls /mnt/test_eph/appvms
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
    qvm-shutdown test-eph2
    sudo umount /mnt/test_eph
    qvm-create -l red -P teph test-eph-fail (must fail with error in journalctl)
    ls /mnt/test_eph/ (should be empty)
    systemctl restart qubesd
    qvm-remove test-eph2
    qvm-create -l red -P teph test-eph3
    md5sum /mnt/ram/teph.key (same as in (2))
    sudo mount|grep -E 'ram|test'
    ls /mnt/test_eph/appvms/test_eph3
    qvm-remove test-eph3
    qvm-ls | grep test-eph
    qvm-pool -r teph
    grep eph /var/lib/qubes/qubes.xml (nothing should be left)
    qvm-pool
    ls /mnt/
    ls /mnt/ram/ (should be empty)
    ```
    '''  # pylint: disable=protected-access

    driver = 'callback'
    config_path='/etc/qubes_callback.json'

    def __init__(self, *, name, conf_id):
        '''Constructor.
        :param conf_id: Identifier as found inside the user-controlled configuration at `/etc/qubes_callback.json`.
                       Non-ASCII, non-alphanumeric characters may be disallowed.
                       **Security Note**: Depending on your RPC policy (admin.pool.Add) this constructor and its parameters
                       may be called from an untrusted VM (not by default though). In those cases it may be security-relevant
                       not to pick easily guessable `conf_id` values for your configuration as untrusted VMs may otherwise
                       execute callbacks meant for other pools.
        '''
        self._cb_ctor_done = False
        assert isinstance(conf_id, str), 'conf_id is no String. VM attack?!'
        self._cb_conf_id = conf_id

        with open(CallbackPool.config_path) as json_file:
            conf_all = json.load(json_file)
        assert isinstance(conf_all, dict), 'The file %s is supposed to define a dict.' % CallbackPool.config_path

        try:
            self._cb_conf = conf_all[self._cb_conf_id]
        except KeyError:
            #we cannot throw KeyErrors as we'll otherwise generate incorrect error messages @qubes.app._get_pool()
            raise NameError('The specified conf_id %s could not be found inside %s.' % (self._cb_conf_id, CallbackPool.config_path))

        try:
            bdriver = self._cb_conf['bdriver']
        except KeyError:
            raise NameError('Missing bdriver for the conf_id %s inside %s.' % (self._cb_conf_id, CallbackPool.config_path))

        self._cb_cmd_arg = json.dumps(self._cb_conf, sort_keys=True, indent=2)

        try:
            cls = qubes.utils.get_entry_point_one(qubes.storage.STORAGE_ENTRY_POINT, bdriver)
        except KeyError:
            raise NameError('The driver %s was not found on your system.' % bdriver)
        assert issubclass(cls, qubes.storage.Pool), 'The class %s must be a subclass of qubes.storage.Pool.' % cls

        self._cb_requires_init = self._check_init()
        bdriver_args = self._cb_conf.get('bdriver_args', {})
        self._cb_impl = cls(name=name, **bdriver_args)

        super().__init__(name=name, revisions_to_keep=int(bdriver_args.get('revisions_to_keep', 1)))
        self._cb_ctor_done = True
        self._callback('on_ctor')

    def _check_init(self):
        ''' Whether or not this object requires late storage initialization via callback. '''
        cmd = self._cb_conf.get('on_sinit')
        if not cmd:
            cmd = self._cb_conf.get('cmd')
        return bool(cmd and cmd != '-')

    def _init(self, callback=True):
        #late initialization on first use for e.g. decryption on first usage request
        #maybe TODO: if this function is meant to be run in parallel (are Pool operations asynchronous?), a function lock is required!
        if callback:
            self._callback('on_sinit')
        self._cb_requires_init = False

    def _assertInitialized(self, **kwargs):
        if self._cb_requires_init:
            self._init(**kwargs)

    def _callback(self, cb, cb_args=[], log=logging.getLogger('qubes.storage.callback')):
        '''Run a callback.
        :param cb: Callback identifier string.
        :param cb_args: Optional arguments to pass to the command as last arguments.
                        Only passed on for the generic command specified as `cmd`, not for `on_xyz` callbacks.
        '''
        if self._cb_ctor_done:
            cmd = self._cb_conf.get(cb)
            args = [] #on_xyz callbacks should never receive arguments
            if not cmd:
                cmd = self._cb_conf.get('cmd')
                args = [ self.name, self._cb_conf['bdriver'], cb, self._cb_cmd_arg, *cb_args ]
            if cmd and cmd != '-':
                args = filter(None, args)
                args = ' '.join(quote(str(a)) for a in args)
                cmd = ' '.join(filter(None, [cmd, args]))
                log.info('callback driver executing (%s, %s %s): %s' % (self._cb_conf_id, cb, cb_args, cmd))
                res = subprocess.run(['/bin/bash', '-c', cmd], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                #stdout & stderr are reported if the exit code check fails
                log.debug('callback driver stdout (%s, %s %s): %s' % (self._cb_conf_id, cb, cb_args, res.stdout))
                log.debug('callback driver stderr (%s, %s %s): %s' % (self._cb_conf_id, cb, cb_args, res.stderr))
                if self._cb_conf.get('signal_back', False) is True:
                    self._process_signals(res.stdout, log)

    def _process_signals(self, out, log=logging.getLogger('qubes.storage.callback')):
        '''Process any signals found inside a string.
        :param out: String to check for signals. Each signal must be on a dedicated line.
                    They are executed in the order they are found. Callbacks are not triggered.
        '''
        for line in out.splitlines():
            if line == 'SIGNAL_setup':
                log.info('callback driver processing SIGNAL_setup for %s' % self._cb_conf_id)
                self.setup(callback=False)

    def __del__(self):
        s = super()
        if hasattr(s, '__del__'):
            s.__del__()

    @property
    def config(self):
        return {
            'name': self.name,
            'driver': CallbackPool.driver,
            'conf_id': self._cb_conf_id,
        }

    def destroy(self):
        self._assertInitialized()
        ret = self._cb_impl.destroy()
        self._callback('on_destroy')
        return ret

    def init_volume(self, vm, volume_config):
        return CallbackVolume(self, self._cb_impl.init_volume(vm, volume_config))

    def setup(self, callback=True):
        if callback:
            self._callback('on_setup')
        self._assertInitialized(callback=False) #setup is assumed to include initialization
        return self._cb_impl.setup()

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
        else:
            return self._cb_impl.included_in(app)

    @property
    def size(self):
        if self._cb_requires_init:
            return None
        else:
            return self._cb_impl.size

    @property
    def usage(self):
        if self._cb_requires_init:
            return None
        else:
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

class CallbackVolume:
    ''' Proxy volume adding callback functionality to other volumes.

        Required to support the `on_sinit` callback for late storage initialization.

        **Important for Developers**: Even though instances of this class behave exactly as `qubes.storage.Volume` instances,
                                    they are no such instances (e.g. `assert isinstance(obj, qubes.storage.Volume)` will fail).
    '''

    def __init__(self, pool, impl):
        '''Constructor.
        :param pool: `CallbackPool` of this volume
        :param impl: `qubes.storage.Volume` object to wrap
        '''
        assert isinstance(impl, qubes.storage.Volume), 'impl must be a qubes.storage.Volume instance. Found a %s instance.' % impl.__class__
        assert isinstance(pool, CallbackPool), 'pool must use a qubes.storage.CallbackPool instance. Found a %s instance.' % pool.__class__
        self._cb_pool = pool
        self._cb_impl = impl

    def _assertInitialized(self, **kwargs):
        return self._cb_pool._assertInitialized(**kwargs)

    def _callback(self, cb, cb_args=[], **kwargs):
        vol_args = [ *cb_args, self.name, self.vid ]
        return self._cb_pool._callback(cb, cb_args=vol_args, **kwargs)

    def create(self):
        self._assertInitialized()
        self._callback('on_volume_create')
        return self._cb_impl.create()

    def remove(self):
        self._assertInitialized()
        ret = self._cb_impl.remove()
        self._callback('on_volume_remove')
        return ret

    def resize(self, size):
        self._assertInitialized()
        self._callback('on_volume_resize', cb_args=[size])
        return self._cb_impl.resize(size)

    def start(self):
        self._assertInitialized()
        self._callback('on_volume_start')
        return self._cb_impl.start()

    def stop(self):
        self._assertInitialized()
        ret = self._cb_impl.stop()
        self._callback('on_volume_stop')
        return ret

    def import_data(self):
        self._assertInitialized()
        self._callback('on_volume_import_data')
        return self._cb_impl.import_data()

    def import_data_end(self, success):
        self._assertInitialized()
        ret = self._cb_impl.import_data_end(success)
        self._callback('on_volume_import_data_end', cb_args=[success])
        return ret

    def import_volume(self, src_volume):
        self._assertInitialized()
        self._callback('on_volume_import', cb_args=[src_volume.vid])
        return self._cb_impl.import_volume(src_volume)

    def is_dirty(self):
        if self._cb_pool._cb_requires_init:
            return False
        else:
            return self._cb_impl.is_dirty()

    def is_outdated(self):
        if self._cb_pool._cb_requires_init:
            return False
        else:
            return self._cb_impl.is_outdated()

    #remaining method & attribute delegation
    def __getattr__(self, name):
        if name in [ 'block_device', 'verify', 'revert', 'export' ]:
            self._assertInitialized()
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
