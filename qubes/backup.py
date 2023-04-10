#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2013-2017  Marek Marczykowski-Górecki
#                                   <marmarek@invisiblethingslab.com>
# Copyright (C) 2013  Olivier Médoc <o_medoc@yahoo.fr>
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
#

import asyncio
import datetime
import fcntl
import functools
import grp
import itertools
import logging
import os
import pwd
import shutil
import stat
import string
import subprocess
import tempfile
import termios
import time

from .utils import size_to_human
import qubes
import qubes.storage
import qubes.storage.file
import qubes.vm.templatevm

QUEUE_ERROR = "ERROR"

QUEUE_FINISHED = "FINISHED"

HEADER_FILENAME = 'backup-header'
DEFAULT_CRYPTO_ALGORITHM = 'aes-256-cbc'
# 'scrypt' is not exactly HMAC algorithm, but a tool we use to
# integrity-protect the data
DEFAULT_HMAC_ALGORITHM = 'scrypt'
DEFAULT_COMPRESSION_FILTER = 'gzip'
CURRENT_BACKUP_FORMAT_VERSION = '4'
# Maximum size of error message get from process stderr (including VM process)
MAX_STDERR_BYTES = 1024
# header + qubes.xml max size
HEADER_QUBES_XML_MAX_SIZE = 1024 * 1024
# hmac file max size - regardless of backup format version!
HMAC_MAX_SIZE = 4096

BLKSIZE = 512


class BackupCanceledError(qubes.exc.QubesException):
    def __init__(self, msg, tmpdir=None):
        super().__init__(msg)
        self.tmpdir = tmpdir


class BackupHeader:
    '''Structure describing backup-header file included as the first file in
    backup archive
    '''
    # pylint: disable=too-few-public-methods
    header_keys = {
        'version': 'version',
        'encrypted': 'encrypted',
        'compressed': 'compressed',
        'compression-filter': 'compression_filter',
        'crypto-algorithm': 'crypto_algorithm',
        'hmac-algorithm': 'hmac_algorithm',
        'backup-id': 'backup_id'
    }
    bool_options = ['encrypted', 'compressed']
    int_options = ['version']

    def __init__(self,
            version=None,
            encrypted=None,
            compressed=None,
            compression_filter=None,
            hmac_algorithm=None,
            crypto_algorithm=None,
            backup_id=None):
        # repeat the list to help code completion...
        self.version = version
        self.encrypted = encrypted
        self.compressed = compressed
        # Options introduced in backup format 3+, which always have a header,
        # so no need for fallback in function parameter
        self.compression_filter = compression_filter
        self.hmac_algorithm = hmac_algorithm
        self.crypto_algorithm = crypto_algorithm
        self.backup_id = backup_id

    def save(self, filename):
        with open(filename, "w", encoding='ascii') as f_header:
            # make sure 'version' is the first key
            f_header.write('version={}\n'.format(self.version))
            for key, attr in self.header_keys.items():
                if key == 'version':
                    continue
                if getattr(self, attr) is None:
                    continue
                f_header.write("{!s}={!s}\n".format(key, getattr(self, attr)))


class SendWorker:
    # pylint: disable=too-few-public-methods
    def __init__(self, queue, base_dir, backup_stdout):
        super().__init__()
        self.queue = queue
        self.base_dir = base_dir
        self.backup_stdout = backup_stdout
        self.log = logging.getLogger('qubes.backup')

    async def run(self):
        self.log.debug("Started sending thread")

        while True:
            filename = await self.queue.get()
            if filename in (QUEUE_FINISHED, QUEUE_ERROR):
                break

            self.log.debug("Sending file {}".format(filename))
            # This tar used for sending data out need to be as simple, as
            # simple, as featureless as possible. It will not be
            # verified before untaring.
            tar_final_cmd = ["tar", "-cO", "--posix",
                             "-C", self.base_dir, filename]
            final_proc = await asyncio.create_subprocess_exec(
                *tar_final_cmd,
                stdout=self.backup_stdout)
            retcode = await final_proc.wait()
            if retcode >= 2:
                # handle only exit code 2 (tar fatal error) or
                # greater (call failed?)
                raise qubes.exc.QubesException(
                    "ERROR: Failed to write the backup, out of disk space? "
                    "Check console output or ~/.xsession-errors for details.")

            # Delete the file as we don't need it anymore
            self.log.debug("Removing file {}".format(filename))
            os.remove(os.path.join(self.base_dir, filename))

        self.log.debug("Finished sending thread")

async def launch_proc_with_pty(args, stdin=None, stdout=None,
                               stderr=None, echo=True):
    """Similar to pty.fork, but handle stdin/stdout according to parameters
    instead of connecting to the pty

    :return tuple (subprocess.Popen, pty_master)
    """

    def set_ctty(ctty_fd, master_fd):
        os.setsid()
        os.close(master_fd)
        fcntl.ioctl(ctty_fd, termios.TIOCSCTTY, 0)
        if not echo:
            termios_p = termios.tcgetattr(ctty_fd)
            # termios_p.c_lflags
            termios_p[3] &= ~termios.ECHO
            termios.tcsetattr(ctty_fd, termios.TCSANOW, termios_p)
    (pty_master, pty_slave) = os.openpty()
    p = await asyncio.create_subprocess_exec(*args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        preexec_fn=lambda: set_ctty(pty_slave, pty_master))
    os.close(pty_slave)
    # pylint: disable=consider-using-with
    return p, open(pty_master, 'wb+', buffering=0)


async def launch_scrypt(action, input_name, output_name, passphrase):
    '''
    Launch 'scrypt' process, pass passphrase to it and return
    subprocess.Popen object.

    :param action: 'enc' or 'dec'
    :param input_name: input path or '-' for stdin
    :param output_name: output path or '-' for stdout
    :param passphrase: passphrase
    :type passphrase: bytes
    :return: subprocess.Popen object
    '''
    command_line = ['scrypt', action, input_name, output_name]
    (p, pty) = await launch_proc_with_pty(command_line,
        stdin=subprocess.PIPE if input_name == '-' else None,
        stdout=subprocess.PIPE if output_name == '-' else None,
        stderr=subprocess.PIPE,
        echo=False)
    if action == 'enc':
        prompts = (b'Please enter passphrase: ', b'Please confirm passphrase: ')
    else:
        prompts = (b'Please enter passphrase: ',)
    for prompt in prompts:
        actual_prompt = await p.stderr.read(len(prompt))
        if actual_prompt != prompt:
            raise qubes.exc.QubesException(
                'Unexpected prompt from scrypt: {}'.format(actual_prompt))
        pty.write(passphrase + b'\n')
        pty.flush()
    # save it here, so garbage collector would not close it (which would kill
    #  the child)
    p.pty = pty
    return p


class Backup:
    '''Backup operation manager. Usage:

    >>> app = qubes.Qubes()
    >>> # optional - you can use 'None' to use default list (based on
    >>> #  vm.include_in_backups property)
    >>> vms = [app.domains[name] for name in ['my-vm1', 'my-vm2', 'my-vm3']]
    >>> exclude_vms = []
    >>> options = {
    >>>     'compressed': True,
    >>>     'passphrase': 'This is very weak backup passphrase',
    >>>     'target_vm': app.domains['sys-usb'],
    >>>     'target_dir': '/media/disk',
    >>> }
    >>> backup_op = Backup(app, vms, exclude_vms, **options)
    >>> print(backup_op.get_backup_summary())
    >>> asyncio.get_event_loop().run_until_complete(backup_op.backup_do())

    See attributes of this object for all available options.

    '''
    # pylint: disable=too-many-instance-attributes
    class FileToBackup:
        # pylint: disable=too-few-public-methods
        def __init__(self, file_path_or_func, subdir=None, name=None, size=None,
                     cleanup_func=None):
            """Store a single file to backup

            :param file_path_or_func: path to the file or a function
                returning one; in case of function, it can be a coroutine;
                if a function is given, *name*, *subdir* and *size* needs to be
                given too
            :param subdir: directory in a backup archive to place file in
            :param name: name of the file in the backup archive
            :param size: size
            :param cleanup_func: function to call after processing the file;
                the function will get the file path as an argument
            """
            if callable(file_path_or_func):
                assert subdir is not None \
                       and name is not None \
                       and size is not None

            if size is None:
                size = qubes.storage.file.get_disk_usage(file_path_or_func)

            if subdir is None:
                abs_file_path = os.path.abspath(file_path_or_func)
                abs_base_dir = os.path.abspath(
                    qubes.config.system_path["qubes_base_dir"]) + '/'
                abs_file_dir = os.path.dirname(abs_file_path) + '/'
                (nothing, directory, subdir) = \
                    abs_file_dir.partition(abs_base_dir)
                assert nothing == ""
                assert directory == abs_base_dir
            else:
                if subdir and not subdir.endswith('/'):
                    subdir += '/'

            if name is None:
                name = os.path.basename(file_path_or_func)

            #: real path to the file (or callable to get one)
            self.path = file_path_or_func
            #: size of the file
            self.size = size
            #: directory in backup archive where file should be placed
            self.subdir = subdir
            #: use this name in the archive (aka rename)
            self.name = name
            #: function to call after processing the file
            self.cleanup_func = cleanup_func

    class VMToBackup:
        # pylint: disable=too-few-public-methods
        def __init__(self, vm, files, subdir):
            self.vm = vm
            self.files = files
            self.subdir = subdir

        @property
        def size(self):
            return functools.reduce(lambda x, y: x + y.size, self.files, 0)

    def __init__(self, app, vms_list=None, exclude_list=None, **kwargs):
        """
        If vms = None, use default list based on vm.include_in_backups property;
        exclude_list is always applied
        """
        super().__init__()

        #: progress of the backup - bytes handled of the current VM
        self.chunk_size = 100 * 1024 * 1024
        self._current_vm_bytes = 0
        #: progress of the backup - bytes handled of finished VMs
        self._done_vms_bytes = 0
        #: total backup size (set by :py:meth:`get_files_to_backup`)
        self.total_backup_bytes = 0
        #: application object
        self.app = app
        #: directory for temporary files - set after creating the directory
        self.tmpdir = None

        # Backup settings - defaults
        #: should the backup be compressed?
        self.compressed = True
        #: what passphrase should be used to intergrity protect (and encrypt)
        #: the backup; required
        self.passphrase = None
        #: custom compression filter; a program which process stdin to stdout
        self.compression_filter = DEFAULT_COMPRESSION_FILTER
        #: VM to which backup should be sent (if any)
        self.target_vm = None
        #: directory to save backup in (either in dom0 or target VM,
        #: depending on :py:attr:`target_vm`
        self.target_dir = None
        #: callback for progress reporting. Will be called with one argument
        #: - progress in percents
        self.progress_callback = None
        self.last_progress_time = time.time()
        #: backup ID, needs to be unique (for a given user),
        #: not necessary unpredictable; automatically generated
        self.backup_id = datetime.datetime.now().strftime(
            '%Y%m%dT%H%M%S-' + str(os.getpid()))

        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise AttributeError(key)

        self.log = logging.getLogger('qubes.backup')

        if exclude_list is None:
            exclude_list = []

        if vms_list is None:
            vms_list = [vm for vm in app.domains if vm.include_in_backups]

        # Apply exclude list
        self.vms_for_backup = [vm for vm in vms_list
            if vm.name not in exclude_list]

        self._files_to_backup = self.get_files_to_backup()

    def __del__(self):
        if self.tmpdir and os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def get_files_to_backup(self):
        files_to_backup = {}
        for vm in self.vms_for_backup:
            if vm.qid == 0:
                # handle dom0 later
                continue

            subdir = 'vm%d/' % vm.qid

            vm_files = []
            for name, volume in vm.volumes.items():
                if not volume.save_on_stop:
                    continue
                vm_files.append(self.FileToBackup(
                    volume.export,
                    subdir,
                    name + '.img',
                    volume.usage,
                    cleanup_func=volume.export_end))

            vm_files.extend(self.FileToBackup(i, subdir)
                for i in vm.fire_event('backup-get-files'))

            firewall_conf = os.path.join(vm.dir_path, vm.firewall_conf)
            if os.path.exists(firewall_conf):
                vm_files.append(self.FileToBackup(firewall_conf, subdir))

            if not vm_files:
                # subdir/ is needed in the tar file, otherwise restore
                # of a (Disp)VM without any backed up files is going
                # to fail. Adding a zero-sized file here happens to be
                # more straightforward than adding an empty directory.
                empty = self.FileToBackup("/var/run/qubes/empty", subdir)
                assert empty.size == 0
                vm_files.append(empty)

            files_to_backup[vm.qid] = self.VMToBackup(vm, vm_files, subdir)

        # Dom0 user home
        if 0 in [vm.qid for vm in self.vms_for_backup]:
            local_user = grp.getgrnam('qubes').gr_mem[0]
            home_dir = pwd.getpwnam(local_user).pw_dir
            # Home dir should have only user-owned files, so fix it now
            # to prevent permissions problems - some root-owned files can
            # left after 'sudo bash' and similar commands
            subprocess.check_call(['sudo', 'chown', '-R', local_user, home_dir])

            home_to_backup = [
                self.FileToBackup(home_dir, 'dom0-home/')]
            vm_files = home_to_backup

            files_to_backup[0] = self.VMToBackup(self.app.domains[0],
                vm_files,
                os.path.join('dom0-home', os.path.basename(home_dir)))

        self.total_backup_bytes = functools.reduce(
            lambda x, y: x + y.size, files_to_backup.values(), 0)
        return files_to_backup


    def get_backup_summary(self):
        summary = ""

        fields_to_display = [
            {"name": "VM", "width": 16},
            {"name": "type", "width": 12},
            {"name": "size", "width": 12}
        ]

        # Display the header
        for field in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(field["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"
        for field in fields_to_display:
            fmt = "{{0:>{0}}} |".format(field["width"] + 1)
            summary += fmt.format(field["name"])
        summary += "\n"
        for field in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(field["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"

        files_to_backup = self._files_to_backup

        for qid, vm_info in files_to_backup.items():
            summary_line = ""
            fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
            summary_line += fmt.format(vm_info.vm.name)

            fmt = "{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
            if qid == 0:
                summary_line += fmt.format("User home")
            elif isinstance(vm_info.vm, qubes.vm.templatevm.TemplateVM):
                summary_line += fmt.format("Template VM")
            else:
                summary_line += fmt.format("VM" + (" + Sys" if
                    vm_info.vm.updateable else ""))

            vm_size = vm_info.size

            fmt = "{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
            summary_line += fmt.format(size_to_human(vm_size))

            if qid != 0 and vm_info.vm.is_running():
                summary_line += " <-- The VM is running, backup will contain " \
                                "its state from before its start!"

            summary += summary_line + "\n"

        for field in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(field["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"

        fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        summary += fmt.format("Total size:")
        fmt = "{{0:>{0}}} |".format(
            fields_to_display[1]["width"] + 1 + 2 + fields_to_display[2][
                "width"] + 1)
        summary += fmt.format(size_to_human(self.total_backup_bytes))
        summary += "\n"

        for field in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(field["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"

        vms_not_for_backup = [vm.name for vm in self.app.domains
                              if vm not in self.vms_for_backup]
        summary += "VMs not selected for backup:\n - " + "\n - ".join(
            sorted(vms_not_for_backup)) + "\n"

        return summary

    async def _prepare_backup_header(self):
        header_file_path = os.path.join(self.tmpdir, HEADER_FILENAME)
        backup_header = BackupHeader(
            version=CURRENT_BACKUP_FORMAT_VERSION,
            hmac_algorithm=DEFAULT_HMAC_ALGORITHM,
            encrypted=True,
            compressed=self.compressed,
            compression_filter=self.compression_filter,
            backup_id=self.backup_id,
        )
        backup_header.save(header_file_path)
        # Start encrypt, scrypt will also handle integrity
        # protection
        scrypt_passphrase = '{filename}!'.format(
            filename=HEADER_FILENAME).encode() + self.passphrase
        scrypt = await launch_scrypt(
            'enc', header_file_path, header_file_path + '.hmac',
            scrypt_passphrase)

        retcode = await scrypt.wait()
        if retcode:
            raise qubes.exc.QubesException(
                "Failed to compute hmac of header file: "
                + (await scrypt.stderr.read()).decode())
        return HEADER_FILENAME, HEADER_FILENAME + ".hmac"

    def _send_progress_update(self):
        if not self.total_backup_bytes:
            return
        if callable(self.progress_callback):
            if time.time() - self.last_progress_time >= 1: # avoid flooding
                progress = (
                    100 * (self._done_vms_bytes + self._current_vm_bytes) /
                    self.total_backup_bytes)
                self.last_progress_time = time.time()
                # pylint: disable=not-callable
                self.progress_callback(progress)

    def _add_vm_progress(self, bytes_done):
        self._current_vm_bytes += bytes_done
        self._send_progress_update()

    async def _split_and_send(self, input_stream, file_basename,
            output_queue):
        '''Split *input_stream* into parts of max *chunk_size* bytes and send
        to *output_queue*.

        :param input_stream: stream (asyncio reader stream) of data to split
        :param file_basename: basename (i.e. without part number and '.enc')
        of output files
        :param output_queue: asyncio.Queue instance to put produced files to
        - queue will get only filenames of written chunks
        '''
        # Wait for compressor (tar) process to finish or for any
        # error of other subprocesses
        i = 0
        run_error = "size_limit"
        scrypt = None
        while run_error == "size_limit":
            # Prepare a first chunk
            chunkfile = file_basename + ".%03d.enc" % i
            i += 1

            # Start encrypt, scrypt will also handle integrity
            # protection
            scrypt_passphrase = \
                '{backup_id}!{filename}!'.format(
                    backup_id=self.backup_id,
                    filename=os.path.relpath(chunkfile[:-4],
                        self.tmpdir)).encode() + self.passphrase
            try:
                scrypt = await launch_scrypt(
                    "enc", "-", chunkfile, scrypt_passphrase)

                run_error = await handle_streams(
                    input_stream,
                    scrypt.stdin,
                    self.chunk_size,
                    self._add_vm_progress
                )

                self.log.debug(
                    "handle_streams returned: {}".format(run_error))
            except:
                scrypt.terminate()
                raise

            scrypt.stdin.close()
            await scrypt.wait()
            self.log.debug("scrypt return code: {}".format(
                scrypt.returncode))

            # Send the chunk to the backup target
            await output_queue.put(
                os.path.relpath(chunkfile, self.tmpdir))

    async def _wrap_and_send_files(self, files_to_backup, output_queue):
        for vm_info in files_to_backup:
            for file_info in vm_info.files:

                self.log.debug("Backing up {}".format(file_info))

                backup_tempfile = os.path.join(
                    self.tmpdir, file_info.subdir,
                    file_info.name)
                self.log.debug("Using temporary location: {}".format(
                    backup_tempfile))

                # Ensure the temporary directory exists
                if not os.path.isdir(os.path.dirname(backup_tempfile)):
                    os.makedirs(os.path.dirname(backup_tempfile))

                # The first tar cmd can use any complex feature as we want.
                # Files will be verified before untaring this.
                # Prefix the path in archive with filename["subdir"] to have it
                # verified during untar
                path = file_info.path
                if callable(path):
                    path = await qubes.utils.coro_maybe(path())
                tar_cmdline = (["tar", "-Pc", '--sparse',
                                '-C', os.path.dirname(path)] +
                               (['--dereference'] if
                               file_info.subdir != "dom0-home/" else []) +
                               ['--xform=s:^%s:%s\\0:' % (
                                   os.path.basename(path),
                                   file_info.subdir),
                                   os.path.basename(path)
                               ])
                file_stat = os.stat(path)
                if stat.S_ISBLK(file_stat.st_mode) or \
                        file_info.name != os.path.basename(path):
                    # tar doesn't handle content of block device, use our
                    # writer
                    # also use our tar writer when renaming file
                    assert not stat.S_ISDIR(file_stat.st_mode), \
                        "Renaming directories not supported"
                    tar_cmdline = ['python3', '-m', 'qubes.tarwriter',
                        '--override-name=%s' % (
                            os.path.join(file_info.subdir, os.path.basename(
                                file_info.name))),
                        path]
                if self.compressed:
                    tar_cmdline.insert(-2,
                        "--use-compress-program=%s" % self.compression_filter)

                self.log.debug(" ".join(tar_cmdline))

                # Pipe: tar-sparse | scrypt | tar | backup_target
                # TODO: log handle stderr
                tar_sparse = await asyncio.create_subprocess_exec(
                    *tar_cmdline, stdout=subprocess.PIPE)

                try:
                    await self._split_and_send(
                        tar_sparse.stdout,
                        backup_tempfile,
                        output_queue)
                except:
                    try:
                        tar_sparse.terminate()
                    except ProcessLookupError:
                        pass
                    raise
                finally:
                    if file_info.cleanup_func is not None:
                        await qubes.utils.coro_maybe(
                            file_info.cleanup_func(path))

                await tar_sparse.wait()
                if tar_sparse.returncode:
                    raise qubes.exc.QubesException(
                        'Failed to archive {} file'.format(file_info.path))


            # This VM done, update progress
            self._done_vms_bytes += vm_info.size
            self._current_vm_bytes = 0
            self._send_progress_update()

        await output_queue.put(QUEUE_FINISHED)

    @staticmethod
    async def _monitor_process(proc, error_message):
        try:
            await proc.wait()
        except:
            proc.terminate()
            raise

        if proc.returncode:
            if proc.stderr is not None:
                proc_stderr = await proc.stderr.read()
                proc_stderr = proc_stderr.decode('ascii', errors='ignore')
                proc_stderr = ''.join(
                    c for c in proc_stderr if c in string.printable and
                                              c not in '\r\n%{}')
                error_message += ': ' + proc_stderr
            raise qubes.exc.QubesException(error_message)

    @staticmethod
    async def _cancel_on_error(future, previous_task):
        '''If further element of chain fail, cancel previous one to
        avoid deadlock.
        When earlier element of chain fail, it will be handled by
        :py:meth:`backup_do`.

        The chain is:
        :py:meth:`_wrap_and_send_files` -> :py:class:`SendWorker` -> vmproc
        '''
        try:
            await future
        except:  # pylint: disable=bare-except
            previous_task.cancel()

    async def backup_do(self):
        # pylint: disable=too-many-statements
        if self.passphrase is None:
            raise qubes.exc.QubesException("No passphrase set")
        if not isinstance(self.passphrase, bytes):
            self.passphrase = self.passphrase.encode('utf-8')
        qubes_xml = self.app.store
        self.tmpdir = tempfile.mkdtemp()
        shutil.copy(qubes_xml, os.path.join(self.tmpdir, 'qubes.xml'))
        qubes_xml = os.path.join(self.tmpdir, 'qubes.xml')
        backup_app = qubes.Qubes(qubes_xml, offline_mode=True)
        backup_app.events_enabled = False

        files_to_backup = self._files_to_backup
        # make sure backup_content isn't set initially
        for vm in backup_app.domains:
            vm.events_enabled = False
            vm.features['backup-content'] = False

        for qid, vm_info in files_to_backup.items():
            # VM is included in the backup
            backup_app.domains[qid].features['backup-content'] = True
            backup_app.domains[qid].features['backup-path'] = vm_info.subdir
            backup_app.domains[qid].features['backup-size'] = vm_info.size
        backup_app.save()
        del backup_app

        vmproc = None
        if self.target_vm is not None:
            # Prepare the backup target (Qubes service call)
            # If APPVM, STDOUT is a PIPE
            read_fd, write_fd = os.pipe()
            vmproc = await self.target_vm.run_service('qubes.Backup',
                stdin=read_fd,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL)
            os.close(read_fd)
            os.write(write_fd, (self.target_dir.
                replace("\r", "").replace("\n", "") + "\n").encode())
            backup_stdout = write_fd
        else:
            # Prepare the backup target (local file)
            if os.path.isdir(self.target_dir):
                backup_target = self.target_dir + "/qubes-{0}". \
                    format(time.strftime("%Y-%m-%dT%H%M%S"))
            else:
                backup_target = self.target_dir

                # Create the target directory
                if not os.path.exists(os.path.dirname(self.target_dir)):
                    raise qubes.exc.QubesException(
                        "ERROR: the backup directory for {0} does not exists".
                        format(self.target_dir))

            # If not APPVM, STDOUT is a local file
            backup_stdout = open(backup_target, 'wb')

        # Tar with tape length does not deals well with stdout
        # (close stdout between two tapes)
        # For this reason, we will use named pipes instead
        self.log.debug("Working in {}".format(self.tmpdir))

        self.log.debug("Will backup: {}".format(files_to_backup))

        header_files = await self._prepare_backup_header()

        # Setup worker to send encrypted data chunks to the backup_target
        to_send = asyncio.Queue(10)
        send_proc = SendWorker(to_send, self.tmpdir, backup_stdout)
        send_task = asyncio.ensure_future(send_proc.run())

        vmproc_task = None
        if vmproc is not None:
            vmproc_task = asyncio.ensure_future(
                self._monitor_process(vmproc,
                    'Writing backup to VM {} failed'.format(
                        self.target_vm.name)))
            asyncio.ensure_future(self._cancel_on_error(
                vmproc_task, send_task))

        for file_name in header_files:
            await to_send.put(file_name)

        qubes_xml_info = self.VMToBackup(
            None,
            [self.FileToBackup(qubes_xml, '')],
            ''
        )
        inner_archive_task = asyncio.ensure_future(
            self._wrap_and_send_files(
                itertools.chain([qubes_xml_info], files_to_backup.values()),
                to_send
            ))
        asyncio.ensure_future(
            self._cancel_on_error(send_task, inner_archive_task))

        try:
            try:
                await inner_archive_task
            except:
                await to_send.put(QUEUE_ERROR)
                # in fact we may be handling CancelledError, induced by
                # exception in send_task or vmproc_task (and propagated by
                # self._cancel_on_error call above); in such a case this
                # await will raise exception, covering CancelledError -
                # this is intended behaviour
                if vmproc_task:
                    await vmproc_task
                await send_task
                raise

            await send_task

        finally:
            if isinstance(backup_stdout, int):
                os.close(backup_stdout)
            else:
                backup_stdout.close()
            try:
                if vmproc_task:
                    await vmproc_task
            finally:
                shutil.rmtree(self.tmpdir)

        # Save date of last backup, only when backup succeeded
        for qid, vm_info in files_to_backup.items():
            if vm_info.vm:
                vm_info.vm.backup_timestamp = \
                    int(datetime.datetime.now().strftime('%s'))

        self.app.save()


async def handle_streams(stream_in, stream_out, size_limit=None,
        progress_callback=None):
    '''
    Copy stream_in to all streams_out and monitor all mentioned processes.
    If any of them terminate with non-zero code, interrupt the process. Copy
    at most `size_limit` data (if given).

    :param stream_in: StreamReader object to read data from
    :param stream_out: StreamWriter object to write data to
    :param size_limit: int maximum data amount to process
    :param progress_callback: callable function to report progress, will be
        given copied data size (it should accumulate internally)
    :return: "size_limit" or None (no error)
    '''
    buffer_size = 409600
    bytes_copied = 0
    while True:
        if size_limit:
            to_copy = min(buffer_size, size_limit - bytes_copied)
            if to_copy <= 0:
                return "size_limit"
        else:
            to_copy = buffer_size
        buf = await stream_in.read(to_copy)
        if not buf:
            # done
            break

        if callable(progress_callback):
            progress_callback(len(buf))
        stream_out.write(buf)
        bytes_copied += len(buf)
    return None

# vim:sw=4:et:
