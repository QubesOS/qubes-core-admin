#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2013-2015  Marek Marczykowski-Górecki
#                                   <marmarek@invisiblethingslab.com>
# Copyright (C) 2013  Olivier Médoc <o_medoc@yahoo.fr>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>
#
#
from __future__ import unicode_literals
import itertools
import logging
import functools
import termios

from qubes.utils import size_to_human
import stat
import os
import fcntl
import subprocess
import re
import shutil
import tempfile
import time
import grp
import pwd
import datetime
from multiprocessing import Queue, Process
import qubes
import qubes.core2migration
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

_re_alphanum = re.compile(r'^[A-Za-z0-9-]*$')


class BackupCanceledError(qubes.exc.QubesException):
    def __init__(self, msg, tmpdir=None):
        super(BackupCanceledError, self).__init__(msg)
        self.tmpdir = tmpdir


class BackupHeader(object):
    '''Structure describing backup-header file included as the first file in
    backup archive
    '''
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
            header_data=None,
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

        if header_data is not None:
            self.load(header_data)

    def load(self, untrusted_header_text):
        """Parse backup header file.

        :param untrusted_header_text: header content
        :type untrusted_header_text: basestring

        .. warning::
            This function may be exposed to not yet verified header,
            so is security critical.
        """
        try:
            untrusted_header_text = untrusted_header_text.decode('ascii')
        except UnicodeDecodeError:
            raise qubes.exc.QubesException(
                "Non-ASCII characters in backup header")
        for untrusted_line in untrusted_header_text.splitlines():
            if untrusted_line.count('=') != 1:
                raise qubes.exc.QubesException("Invalid backup header")
            key, value = untrusted_line.strip().split('=', 1)
            if not _re_alphanum.match(key):
                raise qubes.exc.QubesException("Invalid backup header (key)")
            if key not in self.header_keys.keys():
                # Ignoring unknown option
                continue
            if not _re_alphanum.match(value):
                raise qubes.exc.QubesException("Invalid backup header (value)")
            if getattr(self, self.header_keys[key]) is not None:
                raise qubes.exc.QubesException(
                    "Duplicated header line: {}".format(key))
            if key in self.bool_options:
                value = value.lower() in ["1", "true", "yes"]
            elif key in self.int_options:
                value = int(value)
            setattr(self, self.header_keys[key], value)

        self.validate()

    def validate(self):
        if self.version == 1:
            # header not really present
            pass
        elif self.version in [2, 3, 4]:
            expected_attrs = ['version', 'encrypted', 'compressed',
                'hmac_algorithm']
            if self.encrypted:
                expected_attrs += ['crypto_algorithm']
            if self.version >= 3 and self.compressed:
                expected_attrs += ['compression_filter']
            if self.version >= 4:
                expected_attrs += ['backup_id']
            for key in expected_attrs:
                if getattr(self, key) is None:
                    raise qubes.exc.QubesException(
                        "Backup header lack '{}' info".format(key))
        else:
            raise qubes.exc.QubesException(
                "Unsupported backup version {}".format(self.version))

    def save(self, filename):
        with open(filename, "w") as f_header:
            # make sure 'version' is the first key
            f_header.write('version={}\n'.format(self.version))
            for key, attr in self.header_keys.items():
                if key == 'version':
                    continue
                if getattr(self, attr) is None:
                    continue
                f_header.write("{!s}={!s}\n".format(key, getattr(self, attr)))


class SendWorker(Process):
    def __init__(self, queue, base_dir, backup_stdout):
        super(SendWorker, self).__init__()
        self.queue = queue
        self.base_dir = base_dir
        self.backup_stdout = backup_stdout
        self.log = logging.getLogger('qubes.backup')

    def run(self):
        self.log.debug("Started sending thread")

        self.log.debug("Moving to temporary dir %s", self.base_dir)
        os.chdir(self.base_dir)

        for filename in iter(self.queue.get, None):
            if filename in (QUEUE_FINISHED, QUEUE_ERROR):
                break

            self.log.debug("Sending file {}".format(filename))
            # This tar used for sending data out need to be as simple, as
            # simple, as featureless as possible. It will not be
            # verified before untaring.
            tar_final_cmd = ["tar", "-cO", "--posix",
                             "-C", self.base_dir, filename]
            final_proc = subprocess.Popen(tar_final_cmd,
                                          stdin=subprocess.PIPE,
                                          stdout=self.backup_stdout)
            if final_proc.wait() >= 2:
                if self.queue.full():
                    # if queue is already full, remove some entry to wake up
                    # main thread, so it will be able to notice error
                    self.queue.get()
                # handle only exit code 2 (tar fatal error) or
                # greater (call failed?)
                raise qubes.exc.QubesException(
                    "ERROR: Failed to write the backup, out of disk space? "
                    "Check console output or ~/.xsession-errors for details.")

            # Delete the file as we don't need it anymore
            self.log.debug("Removing file {}".format(filename))
            os.remove(filename)

        self.log.debug("Finished sending thread")


def launch_proc_with_pty(args, stdin=None, stdout=None, stderr=None, echo=True):
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
    p = subprocess.Popen(args, stdin=stdin, stdout=stdout, stderr=stderr,
        preexec_fn=lambda: set_ctty(pty_slave, pty_master))
    os.close(pty_slave)
    return p, os.fdopen(pty_master, 'wb+', buffering=0)


def launch_scrypt(action, input_name, output_name, passphrase):
    '''
    Launch 'scrypt' process, pass passphrase to it and return
    subprocess.Popen object.

    :param action: 'enc' or 'dec'
    :param input_name: input path or '-' for stdin
    :param output_name: output path or '-' for stdout
    :param passphrase: passphrase
    :return: subprocess.Popen object
    '''
    command_line = ['scrypt', action, input_name, output_name]
    (p, pty) = launch_proc_with_pty(command_line,
        stdin=subprocess.PIPE if input_name == '-' else None,
        stdout=subprocess.PIPE if output_name == '-' else None,
        stderr=subprocess.PIPE,
        echo=False)
    if action == 'enc':
        prompts = (b'Please enter passphrase: ', b'Please confirm passphrase: ')
    else:
        prompts = (b'Please enter passphrase: ',)
    for prompt in prompts:
        actual_prompt = p.stderr.read(len(prompt))
        if actual_prompt != prompt:
            raise qubes.exc.QubesException(
                'Unexpected prompt from scrypt: {}'.format(actual_prompt))
        pty.write(passphrase.encode('utf-8') + b'\n')
        pty.flush()
    # save it here, so garbage collector would not close it (which would kill
    #  the child)
    p.pty = pty
    return p


class Backup(object):
    '''Backup operation manager. Usage:

    >>> app = qubes.Qubes()
    >>> # optional - you can use 'None' to use default list (based on
    >>> #  vm.include_in_backups property)
    >>> vms = [app.domains[name] for name in ['my-vm1', 'my-vm2', 'my-vm3']]
    >>> exclude_vms = []
    >>> options = {
    >>>     'encrypted': True,
    >>>     'compressed': True,
    >>>     'passphrase': 'This is very weak backup passphrase',
    >>>     'target_vm': app.domains['sys-usb'],
    >>>     'target_dir': '/media/disk',
    >>> }
    >>> backup_op = Backup(app, vms, exclude_vms, **options)
    >>> print(backup_op.get_backup_summary())
    >>> backup_op.backup_do()

    See attributes of this object for all available options.

    '''
    # pylint: disable=too-many-instance-attributes
    class FileToBackup(object):
        # pylint: disable=too-few-public-methods
        def __init__(self, file_path, subdir=None, name=None):
            file_size = qubes.storage.file.get_disk_usage(file_path)

            if subdir is None:
                abs_file_path = os.path.abspath(file_path)
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

            #: real path to the file
            self.path = file_path
            #: size of the file
            self.size = file_size
            #: directory in backup archive where file should be placed
            self.subdir = subdir
            #: use this name in the archive (aka rename)
            self.name = os.path.basename(file_path)
            if name is not None:
                self.name = name

    class VMToBackup(object):
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
        If vms = None, include all (sensible) VMs;
        exclude_list is always applied
        """
        super(Backup, self).__init__()

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
        #: backup ID, needs to be unique (for a given user),
        #: not necessary unpredictable; automatically generated
        self.backup_id = datetime.datetime.now().strftime(
            '%Y%m%dT%H%M%S-' + str(os.getpid()))

        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise AttributeError(key)

        #: whether backup was canceled
        self.canceled = False
        #: list of PIDs to kill on backup cancel
        self.processes_to_kill_on_cancel = []

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

    def cancel(self):
        """Cancel running backup operation. Can be called from another thread.
        """
        self.canceled = True
        for proc in self.processes_to_kill_on_cancel:
            try:
                proc.terminate()
            except OSError:
                pass


    def get_files_to_backup(self):
        files_to_backup = {}
        for vm in self.vms_for_backup:
            if vm.qid == 0:
                # handle dom0 later
                continue

            subdir = 'vm%d/' % vm.qid

            vm_files = []
            if vm.volumes['private'] is not None:
                path_to_private_img = vm.storage.export('private')
                vm_files.append(self.FileToBackup(path_to_private_img, subdir,
                        'private.img'))

            vm_files.append(self.FileToBackup(vm.icon_path, subdir))
            vm_files.extend(self.FileToBackup(i, subdir)
                for i in vm.fire_event('backup-get-files'))

            # TODO: drop after merging firewall.xml into qubes.xml
            firewall_conf = os.path.join(vm.dir_path, vm.firewall_conf)
            if os.path.exists(firewall_conf):
                vm_files.append(self.FileToBackup(firewall_conf, subdir))

            if vm.updateable:
                path_to_root_img = vm.storage.export('root')
                vm_files.append(self.FileToBackup(path_to_root_img, subdir,
                    'root.img'))
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
            summary_line += fmt.format(vm_info['vm'].name)

            fmt = "{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
            if qid == 0:
                summary_line += fmt.format("User home")
            elif isinstance(vm_info['vm'], qubes.vm.templatevm.TemplateVM):
                summary_line += fmt.format("Template VM")
            else:
                summary_line += fmt.format("VM" + (" + Sys" if
                    vm_info['vm'].updateable else ""))

            vm_size = vm_info['size']

            fmt = "{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
            summary_line += fmt.format(size_to_human(vm_size))

            if qid != 0 and vm_info['vm'].is_running():
                summary_line += " <-- The VM is running, please shut down it " \
                     "before proceeding with the backup!"

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
            sorted(vms_not_for_backup))

        return summary

    def prepare_backup_header(self):
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
        scrypt_passphrase = u'{filename}!{passphrase}'.format(
            filename=HEADER_FILENAME, passphrase=self.passphrase)
        scrypt = launch_scrypt(
            'enc', header_file_path, header_file_path + '.hmac',
            scrypt_passphrase)

        if scrypt.wait() != 0:
            raise qubes.exc.QubesException(
                "Failed to compute hmac of header file: "
                + scrypt.stderr.read())
        return HEADER_FILENAME, HEADER_FILENAME + ".hmac"


    @staticmethod
    def _queue_put_with_check(proc, vmproc, queue, element):
        if queue.full():
            if not proc.is_alive():
                if vmproc:
                    message = ("Failed to write the backup, VM output:\n" +
                               vmproc.stderr.read())
                else:
                    message = "Failed to write the backup. Out of disk space?"
                raise qubes.exc.QubesException(message)
        queue.put(element)

    def _send_progress_update(self):
        if callable(self.progress_callback):
            progress = (
                100 * (self._done_vms_bytes + self._current_vm_bytes) /
                self.total_backup_bytes)
            # pylint: disable=not-callable
            self.progress_callback(progress)

    def _add_vm_progress(self, bytes_done):
        self._current_vm_bytes += bytes_done
        self._send_progress_update()

    def backup_do(self):
        # pylint: disable=too-many-statements
        if self.passphrase is None:
            raise qubes.exc.QubesException("No passphrase set")
        qubes_xml = self.app.store
        self.tmpdir = tempfile.mkdtemp()
        shutil.copy(qubes_xml, os.path.join(self.tmpdir, 'qubes.xml'))
        qubes_xml = os.path.join(self.tmpdir, 'qubes.xml')
        backup_app = qubes.Qubes(qubes_xml)

        files_to_backup = self._files_to_backup
        # make sure backup_content isn't set initially
        for vm in backup_app.domains:
            vm.features['backup-content'] = False

        for qid, vm_info in files_to_backup.items():
            if qid != 0 and vm_info.vm.is_running():
                raise qubes.exc.QubesVMNotHaltedError(vm_info.vm)
            # VM is included in the backup
            backup_app.domains[qid].features['backup-content'] = True
            backup_app.domains[qid].features['backup-path'] = vm_info.subdir
            backup_app.domains[qid].features['backup-size'] = vm_info.size
        backup_app.save()

        vmproc = None
        tar_sparse = None
        if self.target_vm is not None:
            # Prepare the backup target (Qubes service call)
            # If APPVM, STDOUT is a PIPE
            vmproc = self.target_vm.run_service('qubes.Backup',
                passio_popen=True, passio_stderr=True)
            vmproc.stdin.write((self.target_dir.
                replace("\r", "").replace("\n", "") + "\n").encode())
            vmproc.stdin.flush()
            backup_stdout = vmproc.stdin
            self.processes_to_kill_on_cancel.append(vmproc)
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

        backup_pipe = os.path.join(self.tmpdir, "backup_pipe")
        self.log.debug("Creating pipe in: {}".format(backup_pipe))
        os.mkfifo(backup_pipe)

        self.log.debug("Will backup: {}".format(files_to_backup))

        header_files = self.prepare_backup_header()

        # Setup worker to send encrypted data chunks to the backup_target
        to_send = Queue(10)
        send_proc = SendWorker(to_send, self.tmpdir, backup_stdout)
        send_proc.start()

        for file_name in header_files:
            to_send.put(file_name)

        qubes_xml_info = self.VMToBackup(
            None,
            [self.FileToBackup(qubes_xml, '')],
            ''
        )
        for vm_info in itertools.chain([qubes_xml_info],
                files_to_backup.values()):
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
                tar_cmdline = (["tar", "-Pc", '--sparse',
                               "-f", backup_pipe,
                               '-C', os.path.dirname(file_info.path)] +
                               (['--dereference'] if
                                file_info.subdir != "dom0-home/" else []) +
                               ['--xform=s:^%s:%s\\0:' % (
                                   os.path.basename(file_info.path),
                                   file_info.subdir),
                                os.path.basename(file_info.path)
                                ])
                file_stat = os.stat(file_info.path)
                if stat.S_ISBLK(file_stat.st_mode) or \
                        file_info.name != os.path.basename(file_info.path):
                    # tar doesn't handle content of block device, use our
                    # writer
                    # also use our tar writer when renaming file
                    assert not stat.S_ISDIR(file_stat.st_mode),\
                        "Renaming directories not supported"
                    tar_cmdline = ['python3', '-m', 'qubes.tarwriter',
                        '--override-name=%s' % (
                            os.path.join(file_info.subdir, os.path.basename(
                                file_info.name))),
                        file_info.path,
                        backup_pipe]
                if self.compressed:
                    tar_cmdline.insert(-2,
                        "--use-compress-program=%s" % self.compression_filter)

                self.log.debug(" ".join(tar_cmdline))

                # Pipe: tar-sparse | scrypt | tar | backup_target
                # TODO: log handle stderr
                tar_sparse = subprocess.Popen(
                    tar_cmdline)
                self.processes_to_kill_on_cancel.append(tar_sparse)

                # Wait for compressor (tar) process to finish or for any
                # error of other subprocesses
                i = 0
                pipe = open(backup_pipe, 'rb')
                run_error = "paused"
                while run_error == "paused":
                    # Prepare a first chunk
                    chunkfile = backup_tempfile + ".%03d.enc" % i
                    i += 1

                    # Start encrypt, scrypt will also handle integrity
                    # protection
                    scrypt_passphrase = \
                        u'{backup_id}!{filename}!{passphrase}'.format(
                            backup_id=self.backup_id,
                            filename=os.path.relpath(chunkfile[:-4],
                                self.tmpdir),
                            passphrase=self.passphrase)
                    scrypt = launch_scrypt(
                        "enc", "-", chunkfile, scrypt_passphrase)

                    run_error = handle_streams(
                        pipe,
                        {'backup_target': scrypt.stdin},
                        {'vmproc': vmproc,
                         'addproc': tar_sparse,
                         'scrypt': scrypt,
                        },
                        self.chunk_size,
                        self._add_vm_progress
                    )

                    self.log.debug(
                        "Wait_backup_feedback returned: {}".format(run_error))

                    if self.canceled:
                        try:
                            tar_sparse.terminate()
                        except OSError:
                            pass
                        tar_sparse.wait()
                        to_send.put(QUEUE_ERROR)
                        send_proc.join()
                        shutil.rmtree(self.tmpdir)
                        raise BackupCanceledError("Backup canceled")
                    if run_error and run_error != "size_limit":
                        send_proc.terminate()
                        if run_error == "VM" and vmproc:
                            raise qubes.exc.QubesException(
                                "Failed to write the backup, VM output:\n" +
                                vmproc.stderr.read(MAX_STDERR_BYTES))
                        else:
                            raise qubes.exc.QubesException(
                                "Failed to perform backup: error in " +
                                run_error)

                    scrypt.stdin.close()
                    scrypt.wait()
                    self.log.debug("scrypt return code: {}".format(
                        scrypt.poll()))

                    # Send the chunk to the backup target
                    self._queue_put_with_check(
                        send_proc, vmproc, to_send,
                        os.path.relpath(chunkfile, self.tmpdir))

                    if tar_sparse.poll() is None or run_error == "size_limit":
                        run_error = "paused"
                    else:
                        self.processes_to_kill_on_cancel.remove(tar_sparse)
                        self.log.debug(
                            "Finished tar sparse with exit code {}".format(
                                tar_sparse.poll()))
                pipe.close()

            # This VM done, update progress
            self._done_vms_bytes += vm_info.size
            self._current_vm_bytes = 0
            self._send_progress_update()
            # Save date of last backup
            if vm_info.vm:
                vm_info.vm.backup_timestamp = datetime.datetime.now()

        self._queue_put_with_check(send_proc, vmproc, to_send, QUEUE_FINISHED)
        send_proc.join()
        shutil.rmtree(self.tmpdir)

        if self.canceled:
            raise BackupCanceledError("Backup canceled")

        if send_proc.exitcode != 0:
            raise qubes.exc.QubesException(
                "Failed to send backup: error in the sending process")

        if vmproc:
            self.log.debug("VMProc1 proc return code: {}".format(vmproc.poll()))
            if tar_sparse is not None:
                self.log.debug("Sparse1 proc return code: {}".format(
                    tar_sparse.poll()))
            vmproc.stdin.close()

        self.app.save()


def handle_streams(stream_in, streams_out, processes, size_limit=None,
        progress_callback=None):
    '''
    Copy stream_in to all streams_out and monitor all mentioned processes.
    If any of them terminate with non-zero code, interrupt the process. Copy
    at most `size_limit` data (if given).

    :param stream_in: file-like object to read data from
    :param streams_out: dict of file-like objects to write data to
    :param processes: dict of subprocess.Popen objects to monitor
    :param size_limit: int maximum data amount to process
    :param progress_callback: callable function to report progress, will be
        given copied data size (it should accumulate internally)
    :return: failed process name, failed stream name, "size_limit" or None (
        no error)
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
        buf = stream_in.read(to_copy)
        if not buf:
            # done
            return None

        if callable(progress_callback):
            progress_callback(len(buf))
        for name, stream in streams_out.items():
            if stream is None:
                continue
            try:
                stream.write(buf)
            except IOError:
                return name
        bytes_copied += len(buf)

        for name, proc in processes.items():
            if proc is None:
                continue
            if proc.poll():
                return name


def get_supported_hmac_algo(hmac_algorithm=None):
    # Start with provided default
    if hmac_algorithm:
        yield hmac_algorithm
    if hmac_algorithm != 'scrypt':
        yield 'scrypt'
    proc = subprocess.Popen(['openssl', 'list-message-digest-algorithms'],
                            stdout=subprocess.PIPE)
    for algo in proc.stdout.readlines():
        algo = algo.decode('ascii')
        if '=>' in algo:
            continue
        yield algo.strip()
    proc.wait()

# vim:sw=4:et:
