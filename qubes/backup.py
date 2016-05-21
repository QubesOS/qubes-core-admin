#!/usr/bin/python
# -*- coding: utf-8 -*-
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
from qubes.utils import size_to_human
import sys
import os
import fcntl
import subprocess
import re
import shutil
import tempfile
import time
import grp
import pwd
import errno
import datetime
from multiprocessing import Queue, Process
import qubes
import qubes.core2migration
import qubes.storage
import qubes.storage.file

QUEUE_ERROR = "ERROR"

QUEUE_FINISHED = "FINISHED"

HEADER_FILENAME = 'backup-header'
DEFAULT_CRYPTO_ALGORITHM = 'aes-256-cbc'
DEFAULT_HMAC_ALGORITHM = 'SHA512'
DEFAULT_COMPRESSION_FILTER = 'gzip'
CURRENT_BACKUP_FORMAT_VERSION = '4'
# Maximum size of error message get from process stderr (including VM process)
MAX_STDERR_BYTES = 1024
# header + qubes.xml max size
HEADER_QUBES_XML_MAX_SIZE = 1024 * 1024

BLKSIZE = 512

_re_alphanum = re.compile(r'^[A-Za-z0-9-]*$')

class BackupCanceledError(qubes.exc.QubesException):
    def __init__(self, msg, tmpdir=None):
        super(BackupCanceledError, self).__init__(msg)
        self.tmpdir = tmpdir


class BackupHeader(object):
    header_keys = {
        'version': 'version',
        'encrypted': 'encrypted',
        'compressed': 'compressed',
        'compression-filter': 'compression_filter',
        'crypto-algorithm': 'crypto_algorithm',
        'hmac-algorithm': 'hmac_algorithm',
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
            crypto_algorithm=None):
        # repeat the list to help code completion...
        self.version = version
        self.encrypted = encrypted
        self.compressed = compressed
        # Options introduced in backup format 3+, which always have a header,
        # so no need for fallback in function parameter
        self.compression_filter = compression_filter
        self.hmac_algorithm = hmac_algorithm
        self.crypto_algorithm = crypto_algorithm

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
            for key in expected_attrs:
                if getattr(self, key) is None:
                    raise qubes.exc.QubesException(
                        "Backup header lack '{}' info".format(key))
        else:
            raise qubes.exc.QubesException(
                "Unsupported backup version {}".format(self.version))

    def save(self, filename):
        with open(filename, "w") as f:
            # make sure 'version' is the first key
            f.write('version={}\n'.format(self.version))
            for key, attr in self.header_keys.iteritems():
                if key == 'version':
                    continue
                if getattr(self, attr) is None:
                    continue
                f.write("{!s}={!s}\n".format(key, getattr(self, attr)))


class SendWorker(Process):
    def __init__(self, queue, base_dir, backup_stdout):
        super(SendWorker, self).__init__()
        self.queue = queue
        self.base_dir = base_dir
        self.backup_stdout = backup_stdout
        self.log = logging.getLogger('qubes.backup')

    def run(self):
        self.log.debug("Started sending thread")

        self.log.debug("Moving to temporary dir".format(self.base_dir))
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


class Backup(object):
    class FileToBackup(object):
        def __init__(self, file_path, subdir=None):
            sz = qubes.storage.file.get_disk_usage(file_path)

            if subdir is None:
                abs_file_path = os.path.abspath(file_path)
                abs_base_dir = os.path.abspath(
                    qubes.config.system_path["qubes_base_dir"]) + '/'
                abs_file_dir = os.path.dirname(abs_file_path) + '/'
                (nothing, directory, subdir) = abs_file_dir.partition(abs_base_dir)
                assert nothing == ""
                assert directory == abs_base_dir
            else:
                if len(subdir) > 0 and not subdir.endswith('/'):
                    subdir += '/'

            self.path = file_path
            self.size = sz
            self.subdir = subdir

    class VMToBackup(object):
        def __init__(self, vm, files, subdir):
            self.vm = vm
            self.files = files
            self.subdir = subdir

        @property
        def size(self):
            return reduce(lambda x, y: x + y.size, self.files, 0)

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
        #: should the backup be encrypted?
        self.encrypted = True
        #: should the backup be compressed?
        self.compressed = True
        #: what passphrase should be used to intergrity protect (and encrypt)
        #: the backup; required
        self.passphrase = None
        #: custom hmac algorithm
        self.hmac_algorithm = DEFAULT_HMAC_ALGORITHM
        #: custom encryption algorithm
        self.crypto_algorithm = DEFAULT_CRYPTO_ALGORITHM
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

        for key, value in kwargs.iteritems():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise AttributeError(key)

        #: whether backup was canceled
        self.canceled = False
        #: list of PIDs to kill on backup cancel
        self.processes_to_kill_on_cancel = []

        self.log = logging.getLogger('qubes.backup')

        # FIXME: drop this legacy feature?
        if isinstance(self.compressed, basestring):
            self.compression_filter = self.compressed
            self.compressed = True
        else:
            self.compression_filter = DEFAULT_COMPRESSION_FILTER

        if exclude_list is None:
            exclude_list = []

        if vms_list is None:
            vms_list = [vm for vm in app.domains if vm.include_in_backups]

        # Apply exclude list
        self.vms_for_backup = [vm for vm in vms_list
            if vm.name not in exclude_list]

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

            if self.encrypted:
                subdir = 'vm%d/' % vm.qid
            else:
                subdir = None

            vm_files = []
            if vm.private_img is not None:
                vm_files.append(self.FileToBackup(vm.private_img, subdir))

            vm_files.append(self.FileToBackup(vm.icon_path, subdir))
            vm_files.extend(self.FileToBackup(i, subdir)
                for i in vm.fire_event('backup-get-files'))

            # TODO: drop after merging firewall.xml into qubes.xml
            firewall_conf = os.path.join(vm.dir_path, vm.firewall_conf)
            if os.path.exists(firewall_conf):
                vm_files.append(self.FileToBackup(firewall_conf, subdir))

            if vm.updateable:
                vm_files.append(self.FileToBackup(vm.root_img, subdir))
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

        self.total_backup_bytes = reduce(
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
        for f in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"
        for f in fields_to_display:
            fmt = "{{0:>{0}}} |".format(f["width"] + 1)
            summary += fmt.format(f["name"])
        summary += "\n"
        for f in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"

        files_to_backup = self.get_files_to_backup()

        for qid, vm_info in files_to_backup.iteritems():
            s = ""
            fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
            s += fmt.format(vm_info['vm'].name)

            fmt = "{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
            if qid == 0:
                s += fmt.format("User home")
            elif vm_info['vm'].is_template():
                s += fmt.format("Template VM")
            else:
                s += fmt.format("VM" + (" + Sys" if vm_info['vm'].updateable
                    else ""))

            vm_size = vm_info['size']

            fmt = "{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
            s += fmt.format(size_to_human(vm_size))

            if qid != 0 and vm_info['vm'].is_running():
                s += " <-- The VM is running, please shut it down before proceeding " \
                     "with the backup!"

            summary += s + "\n"

        for f in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
            summary += fmt.format('-')
        summary += "\n"

        fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        summary += fmt.format("Total size:")
        fmt = "{{0:>{0}}} |".format(
            fields_to_display[1]["width"] + 1 + 2 + fields_to_display[2][
                "width"] + 1)
        summary += fmt.format(size_to_human(self.total_backup_bytes))
        summary += "\n"

        for f in fields_to_display:
            fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
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
            hmac_algorithm=self.hmac_algorithm,
            crypto_algorithm=self.crypto_algorithm,
            encrypted=self.encrypted,
            compressed=self.compressed,
            compression_filter=self.compression_filter,
        )
        backup_header.save(header_file_path)

        hmac = subprocess.Popen(
            ["openssl", "dgst", "-" + self.hmac_algorithm,
                "-hmac", self.passphrase],
            stdin=open(header_file_path, "r"),
            stdout=open(header_file_path + ".hmac", "w"))
        if hmac.wait() != 0:
            raise qubes.exc.QubesException(
                "Failed to compute hmac of header file")
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
            self.progress_callback(progress)

    def _add_vm_progress(self, bytes_done):
        self._current_vm_bytes += bytes_done
        self._send_progress_update()

    def backup_do(self):
        if self.passphrase is None:
            raise qubes.exc.QubesException("No passphrase set")
        qubes_xml = self.app.store
        self.tmpdir = tempfile.mkdtemp()
        shutil.copy(qubes_xml, os.path.join(self.tmpdir, 'qubes.xml'))
        qubes_xml = os.path.join(self.tmpdir, 'qubes.xml')
        backup_app = qubes.Qubes(qubes_xml)

        # FIXME: cache it earlier?
        files_to_backup = self.get_files_to_backup()
        # make sure backup_content isn't set initially
        for vm in backup_app.domains:
            vm.features['backup-content'] = False

        for qid, vm_info in files_to_backup.iteritems():
            if qid != 0 and vm_info.vm.is_running():
                raise qubes.exc.QubesVMNotHaltedError(vm_info.vm)
            # VM is included in the backup
            backup_app.domains[qid].features['backup-content'] = True
            backup_app.domains[qid].features['backup-path'] = vm_info.subdir
            backup_app.domains[qid].features['backup-size'] = vm_info.size
        backup_app.save()

        passphrase = self.passphrase.encode('utf-8')

        vmproc = None
        tar_sparse = None
        if self.target_vm is not None:
            # Prepare the backup target (Qubes service call)
            # If APPVM, STDOUT is a PIPE
            vmproc = self.target_vm.run_service('qubes.Backup',
                passio_popen=True, passio_stderr=True)
            vmproc.stdin.write(self.target_dir.
                               replace("\r", "").replace("\n", "") + "\n")
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

        for f in header_files:
            to_send.put(f)

        vm_files_to_backup = self.get_files_to_backup()
        qubes_xml_info = self.VMToBackup(
            None,
            [self.FileToBackup(qubes_xml, '')],
            ''
        )
        for vm_info in itertools.chain([qubes_xml_info],
                vm_files_to_backup.itervalues()):
            for file_info in vm_info.files:

                self.log.debug("Backing up {}".format(file_info))

                backup_tempfile = os.path.join(
                    self.tmpdir, file_info.subdir,
                    os.path.basename(file_info.path))
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
                               ['--xform', 's:^%s:%s\\0:' % (
                                   os.path.basename(file_info.path),
                                   file_info.subdir),
                                os.path.basename(file_info.path)
                                ])
                if self.compressed:
                    tar_cmdline.insert(-1,
                        "--use-compress-program=%s" % self.compression_filter)

                self.log.debug(" ".join(tar_cmdline))

                # Tips: Popen(bufsize=0)
                # Pipe: tar-sparse | encryptor [| hmac] | tar | backup_target
                # Pipe: tar-sparse [| hmac] | tar | backup_target
                # TODO: log handle stderr
                tar_sparse = subprocess.Popen(
                    tar_cmdline, stdin=subprocess.PIPE)
                self.processes_to_kill_on_cancel.append(tar_sparse)

                # Wait for compressor (tar) process to finish or for any
                # error of other subprocesses
                i = 0
                run_error = "paused"
                encryptor = None
                if self.encrypted:
                    # Start encrypt
                    # If no cipher is provided,
                    # the data is forwarded unencrypted !!!
                    encryptor = subprocess.Popen([
                        "openssl", "enc",
                        "-e", "-" + self.crypto_algorithm,
                        "-pass", "pass:" + passphrase],
                        stdin=open(backup_pipe, 'rb'),
                        stdout=subprocess.PIPE)
                    pipe = encryptor.stdout
                else:
                    pipe = open(backup_pipe, 'rb')
                while run_error == "paused":

                    # Start HMAC
                    hmac = subprocess.Popen([
                        "openssl", "dgst", "-" + self.hmac_algorithm,
                        "-hmac", passphrase],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE)

                    # Prepare a first chunk
                    chunkfile = backup_tempfile + "." + "%03d" % i
                    i += 1
                    chunkfile_p = open(chunkfile, 'wb')

                    common_args = {
                        'backup_target': chunkfile_p,
                        'hmac': hmac,
                        'vmproc': vmproc,
                        'addproc': tar_sparse,
                        'progress_callback': self._add_vm_progress,
                        'size_limit': self.chunk_size,
                    }
                    run_error = wait_backup_feedback(
                        in_stream=pipe, streamproc=encryptor,
                        **common_args)
                    chunkfile_p.close()

                    self.log.debug(
                        "Wait_backup_feedback returned: {}".format(run_error))

                    if self.canceled:
                        try:
                            tar_sparse.terminate()
                        except OSError:
                            pass
                        try:
                            hmac.terminate()
                        except OSError:
                            pass
                        tar_sparse.wait()
                        hmac.wait()
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

                    # Send the chunk to the backup target
                    self._queue_put_with_check(
                        send_proc, vmproc, to_send,
                        os.path.relpath(chunkfile, self.tmpdir))

                    # Close HMAC
                    hmac.stdin.close()
                    hmac.wait()
                    self.log.debug("HMAC proc return code: {}".format(
                        hmac.poll()))

                    # Write HMAC data next to the chunk file
                    hmac_data = hmac.stdout.read()
                    self.log.debug(
                        "Writing hmac to {}.hmac".format(chunkfile))
                    with open(chunkfile + ".hmac", 'w') as hmac_file:
                        hmac_file.write(hmac_data)

                    # Send the HMAC to the backup target
                    self._queue_put_with_check(
                        send_proc, vmproc, to_send,
                        os.path.relpath(chunkfile, self.tmpdir) + ".hmac")

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




def wait_backup_feedback(progress_callback, in_stream, streamproc,
                         backup_target, hmac=None, vmproc=None,
                         addproc=None,
                         size_limit=None):
    '''
    Wait for backup chunk to finish
    - Monitor all the processes (streamproc, hmac, vmproc, addproc) for errors
    - Copy stdout of streamproc to backup_target and hmac stdin if available
    - Compute progress based on total_backup_sz and send progress to
      progress_callback function
    - Returns if
    -     one of the monitored processes error out (streamproc, hmac, vmproc,
          addproc), along with the processe that failed
    -     all of the monitored processes except vmproc finished successfully
          (vmproc termination is controlled by the python script)
    -     streamproc does not delivers any data anymore (return with the error
          "")
    -     size_limit is provided and is about to be exceeded
    '''

    buffer_size = 409600
    run_error = None
    run_count = 1
    bytes_copied = 0
    log = logging.getLogger('qubes.backup')

    while run_count > 0 and run_error is None:
        if size_limit and bytes_copied + buffer_size > size_limit:
            return "size_limit"

        buf = in_stream.read(buffer_size)
        if callable(progress_callback):
            progress_callback(len(buf))
        bytes_copied += len(buf)

        run_count = 0
        if hmac:
            retcode = hmac.poll()
            if retcode is not None:
                if retcode != 0:
                    run_error = "hmac"
            else:
                run_count += 1

        if addproc:
            retcode = addproc.poll()
            if retcode is not None:
                if retcode != 0:
                    run_error = "addproc"
            else:
                run_count += 1

        if vmproc:
            retcode = vmproc.poll()
            if retcode is not None:
                if retcode != 0:
                    run_error = "VM"
                    log.debug(vmproc.stdout.read())
            else:
                # VM should run until the end
                pass

        if streamproc:
            retcode = streamproc.poll()
            if retcode is not None:
                if retcode != 0:
                    run_error = "streamproc"
                    break
                elif retcode == 0 and len(buf) <= 0:
                    return ""
            run_count += 1

        else:
            if len(buf) <= 0:
                return ""

        try:
            backup_target.write(buf)
        except IOError as e:
            if e.errno == errno.EPIPE:
                run_error = "target"
            else:
                raise

        if hmac:
            hmac.stdin.write(buf)

    return run_error


class ExtractWorker2(Process):
    def __init__(self, queue, base_dir, passphrase, encrypted,
                 progress_callback, vmproc=None,
                 compressed=False, crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM,
                 verify_only=False):
        super(ExtractWorker2, self).__init__()
        self.queue = queue
        self.base_dir = base_dir
        self.passphrase = passphrase
        self.encrypted = encrypted
        self.compressed = compressed
        self.crypto_algorithm = crypto_algorithm
        self.verify_only = verify_only
        self.blocks_backedup = 0
        self.tar2_process = None
        self.tar2_current_file = None
        self.decompressor_process = None
        self.decryptor_process = None

        self.progress_callback = progress_callback

        self.vmproc = vmproc

        self.restore_pipe = os.path.join(self.base_dir, "restore_pipe")

        self.log = logging.getLogger('qubes.backup.extract')
        self.log.debug("Creating pipe in: {}".format(self.restore_pipe))
        os.mkfifo(self.restore_pipe)

        self.stderr_encoding = sys.stderr.encoding or 'utf-8'

    def collect_tar_output(self):
        if not self.tar2_process.stderr:
            return

        if self.tar2_process.poll() is None:
            try:
                new_lines = self.tar2_process.stderr \
                    .read(MAX_STDERR_BYTES).splitlines()
            except IOError as e:
                if e.errno == errno.EAGAIN:
                    return
                else:
                    raise
        else:
            new_lines = self.tar2_process.stderr.readlines()

        new_lines = map(lambda x: x.decode(self.stderr_encoding), new_lines)

        msg_re = re.compile(r".*#[0-9].*restore_pipe")
        debug_msg = filter(msg_re.match, new_lines)
        self.log.debug('tar2_stderr: {}'.format('\n'.join(debug_msg)))
        new_lines = filter(lambda x: not msg_re.match(x), new_lines)

        self.tar2_stderr += new_lines

    def run(self):
        try:
            self.__run__()
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            # Cleanup children
            for process in [self.decompressor_process,
                            self.decryptor_process,
                            self.tar2_process]:
                if process:
                    # FIXME: kill()?
                    try:
                        process.terminate()
                    except OSError:
                        pass
                    process.wait()
            self.log.error("ERROR: " + unicode(e))
            raise e, None, exc_traceback

    def __run__(self):
        self.log.debug("Started sending thread")
        self.log.debug("Moving to dir " + self.base_dir)
        os.chdir(self.base_dir)

        filename = None

        for filename in iter(self.queue.get, None):
            if filename in (QUEUE_FINISHED, QUEUE_ERROR):
                break

            self.log.debug("Extracting file " + filename)

            if filename.endswith('.000'):
                # next file
                if self.tar2_process is not None:
                    if self.tar2_process.wait() != 0:
                        self.collect_tar_output()
                        self.log.error(
                            "ERROR: unable to extract files for {0}, tar "
                            "output:\n  {1}".
                            format(self.tar2_current_file,
                                   "\n  ".join(self.tar2_stderr)))
                    else:
                        # Finished extracting the tar file
                        self.tar2_process = None
                        self.tar2_current_file = None

                tar2_cmdline = ['tar',
                                '-%sMkvf' % ("t" if self.verify_only else "x"),
                                self.restore_pipe,
                                os.path.relpath(filename.rstrip('.000'))]
                self.log.debug("Running command " + unicode(tar2_cmdline))
                self.tar2_process = subprocess.Popen(tar2_cmdline,
                                                     stdin=subprocess.PIPE,
                                                     stderr=subprocess.PIPE)
                fcntl.fcntl(self.tar2_process.stderr.fileno(), fcntl.F_SETFL,
                            fcntl.fcntl(self.tar2_process.stderr.fileno(),
                                        fcntl.F_GETFL) | os.O_NONBLOCK)
                self.tar2_stderr = []
            elif not self.tar2_process:
                # Extracting of the current archive failed, skip to the next
                # archive
                # TODO: some debug option to preserve it?
                os.remove(filename)
                continue
            else:
                self.collect_tar_output()
                self.log.debug("Releasing next chunck")
                self.tar2_process.stdin.write("\n")
                self.tar2_process.stdin.flush()
            self.tar2_current_file = filename

            pipe = open(self.restore_pipe, 'wb')
            common_args = {
                'backup_target': pipe,
                'hmac': None,
                'vmproc': self.vmproc,
                'addproc': self.tar2_process
            }
            if self.encrypted:
                # Start decrypt
                self.decryptor_process = subprocess.Popen(
                    ["openssl", "enc",
                     "-d",
                     "-" + self.crypto_algorithm,
                     "-pass",
                     "pass:" + self.passphrase] +
                    (["-z"] if self.compressed else []),
                    stdin=open(filename, 'rb'),
                    stdout=subprocess.PIPE)

                run_error = wait_backup_feedback(
                    progress_callback=self.progress_callback,
                    in_stream=self.decryptor_process.stdout,
                    streamproc=self.decryptor_process,
                    **common_args)
            elif self.compressed:
                self.decompressor_process = subprocess.Popen(
                    ["gzip", "-d"],
                    stdin=open(filename, 'rb'),
                    stdout=subprocess.PIPE)

                run_error = wait_backup_feedback(
                    progress_callback=self.progress_callback,
                    in_stream=self.decompressor_process.stdout,
                    streamproc=self.decompressor_process,
                    **common_args)
            else:
                run_error = wait_backup_feedback(
                    progress_callback=self.progress_callback,
                    in_stream=open(filename, "rb"), streamproc=None,
                    **common_args)

            try:
                pipe.close()
            except IOError as e:
                if e.errno == errno.EPIPE:
                    self.log.debug(
                        "Got EPIPE while closing pipe to "
                        "the inner tar process")
                    # ignore the error
                else:
                    raise
            if len(run_error):
                if run_error == "target":
                    self.collect_tar_output()
                    details = "\n".join(self.tar2_stderr)
                else:
                    details = "%s failed" % run_error
                self.tar2_process.terminate()
                self.tar2_process.wait()
                self.tar2_process = None
                self.log.error("Error while processing '{}': {}".format(
                    self.tar2_current_file, details))

            # Delete the file as we don't need it anymore
            self.log.debug("Removing file " + filename)
            os.remove(filename)

        os.unlink(self.restore_pipe)

        if self.tar2_process is not None:
            if filename == QUEUE_ERROR:
                self.tar2_process.terminate()
                self.tar2_process.wait()
            elif self.tar2_process.wait() != 0:
                self.collect_tar_output()
                raise qubes.exc.QubesException(
                    "unable to extract files for {0}.{1} Tar command "
                    "output: %s".
                    format(self.tar2_current_file,
                           (" Perhaps the backup is encrypted?"
                            if not self.encrypted else "",
                            "\n".join(self.tar2_stderr))))
            else:
                # Finished extracting the tar file
                self.tar2_process = None

        self.log.debug("Finished extracting thread")


class ExtractWorker3(ExtractWorker2):
    def __init__(self, queue, base_dir, passphrase, encrypted,
                 progress_callback, vmproc=None,
                 compressed=False, crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM,
                 compression_filter=None, verify_only=False):
        super(ExtractWorker3, self).__init__(queue, base_dir, passphrase,
                                             encrypted,
                                             progress_callback, vmproc,
                                             compressed, crypto_algorithm,
                                             verify_only)
        self.compression_filter = compression_filter
        os.unlink(self.restore_pipe)

    def __run__(self):
        self.log.debug("Started sending thread")
        self.log.debug("Moving to dir " + self.base_dir)
        os.chdir(self.base_dir)

        filename = None

        input_pipe = None
        for filename in iter(self.queue.get, None):
            if filename in (QUEUE_FINISHED, QUEUE_ERROR):
                break

            self.log.debug("Extracting file " + filename)

            if filename.endswith('.000'):
                # next file
                if self.tar2_process is not None:
                    input_pipe.close()
                    if self.tar2_process.wait() != 0:
                        self.collect_tar_output()
                        self.log.error(
                            "ERROR: unable to extract files for {0}, tar "
                            "output:\n  {1}".
                            format(self.tar2_current_file,
                                   "\n  ".join(self.tar2_stderr)))
                    else:
                        # Finished extracting the tar file
                        self.tar2_process = None
                        self.tar2_current_file = None

                tar2_cmdline = ['tar',
                                '-%sk' % ("t" if self.verify_only else "x"),
                                os.path.relpath(filename.rstrip('.000'))]
                if self.compressed:
                    if self.compression_filter:
                        tar2_cmdline.insert(-1,
                                            "--use-compress-program=%s" %
                                            self.compression_filter)
                    else:
                        tar2_cmdline.insert(-1, "--use-compress-program=%s" %
                                            DEFAULT_COMPRESSION_FILTER)

                self.log.debug("Running command " + unicode(tar2_cmdline))
                if self.encrypted:
                    # Start decrypt
                    self.decryptor_process = subprocess.Popen(
                        ["openssl", "enc",
                         "-d",
                         "-" + self.crypto_algorithm,
                         "-pass",
                         "pass:" + self.passphrase],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE)

                    self.tar2_process = subprocess.Popen(
                        tar2_cmdline,
                        stdin=self.decryptor_process.stdout,
                        stderr=subprocess.PIPE)
                    input_pipe = self.decryptor_process.stdin
                else:
                    self.tar2_process = subprocess.Popen(
                        tar2_cmdline,
                        stdin=subprocess.PIPE,
                        stderr=subprocess.PIPE)
                    input_pipe = self.tar2_process.stdin

                fcntl.fcntl(self.tar2_process.stderr.fileno(), fcntl.F_SETFL,
                            fcntl.fcntl(self.tar2_process.stderr.fileno(),
                                        fcntl.F_GETFL) | os.O_NONBLOCK)
                self.tar2_stderr = []
            elif not self.tar2_process:
                # Extracting of the current archive failed, skip to the next
                # archive
                # TODO: some debug option to preserve it?
                os.remove(filename)
                continue
            else:
                self.log.debug("Releasing next chunck")
            self.tar2_current_file = filename

            common_args = {
                'backup_target': input_pipe,
                'hmac': None,
                'vmproc': self.vmproc,
                'addproc': self.tar2_process
            }

            run_error = wait_backup_feedback(
                progress_callback=self.progress_callback,
                in_stream=open(filename, "rb"), streamproc=None,
                **common_args)

            if len(run_error):
                if run_error == "target":
                    self.collect_tar_output()
                    details = "\n".join(self.tar2_stderr)
                else:
                    details = "%s failed" % run_error
                if self.decryptor_process:
                    self.decryptor_process.terminate()
                    self.decryptor_process.wait()
                    self.decryptor_process = None
                self.tar2_process.terminate()
                self.tar2_process.wait()
                self.tar2_process = None
                self.log.error("Error while processing '{}': {}".format(
                    self.tar2_current_file, details))

            # Delete the file as we don't need it anymore
            self.log.debug("Removing file " + filename)
            os.remove(filename)

        if self.tar2_process is not None:
            input_pipe.close()
            if filename == QUEUE_ERROR:
                if self.decryptor_process:
                    self.decryptor_process.terminate()
                    self.decryptor_process.wait()
                    self.decryptor_process = None
                self.tar2_process.terminate()
                self.tar2_process.wait()
            elif self.tar2_process.wait() != 0:
                self.collect_tar_output()
                raise qubes.exc.QubesException(
                    "unable to extract files for {0}.{1} Tar command "
                    "output: %s".
                    format(self.tar2_current_file,
                           (" Perhaps the backup is encrypted?"
                            if not self.encrypted else "",
                            "\n".join(self.tar2_stderr))))
            else:
                # Finished extracting the tar file
                self.tar2_process = None

        self.log.debug("Finished extracting thread")


def get_supported_hmac_algo(hmac_algorithm=None):
    # Start with provided default
    if hmac_algorithm:
        yield hmac_algorithm
    proc = subprocess.Popen(['openssl', 'list-message-digest-algorithms'],
                            stdout=subprocess.PIPE)
    for algo in proc.stdout.readlines():
        if '=>' in algo:
            continue
        yield algo.strip()
    proc.wait()


class BackupRestoreOptions(object):
    def __init__(self):
        #: use default NetVM if the one referenced in backup do not exists on
        #  the host
        self.use_default_netvm = True
        #: set NetVM to "none" if the one referenced in backup do not exists
        # on the host
        self.use_none_netvm = False
        #: set template to default if the one referenced in backup do not
        # exists on the host
        self.use_default_template = True
        #: restore dom0 home
        self.dom0_home = True
        #: dictionary how what templates should be used instead of those
        # referenced in backup
        self.replace_template = {}
        #: restore dom0 home even if username is different
        self.ignore_username_mismatch = False
        #: do not restore data, only verify backup integrity
        self.verify_only = False
        #: automatically rename VM during restore, when it would conflict
        # with existing one
        self.rename_conflicting = True
        #: list of VM names to exclude
        self.exclude = []


class BackupRestore(object):
    """Usage:
    >>> restore_op = BackupRestore(...)
    >>> # adjust restore_op.options here
    >>> restore_info = restore_op.get_restore_info()
    >>> # manipulate restore_info to select VMs to restore here
    >>> restore_op.restore_do(restore_info)
    """

    class VMToRestore(object):
        #: VM excluded from restore by user
        EXCLUDED = object()
        #: VM with such name already exists on the host
        ALREADY_EXISTS = object()
        #: NetVM used by the VM does not exists on the host
        MISSING_NETVM = object()
        #: TemplateVM used by the VM does not exists on the host
        MISSING_TEMPLATE = object()

        def __init__(self, vm):
            self.vm = vm
            if 'backup-path' in vm.features:
                self.subdir = vm.features['backup-path']
            else:
                self.subdir = None
            if 'backup-size' in vm.features and vm.features['backup-size']:
                self.size = int(vm.features['backup-size'])
            else:
                self.size = 0
            self.problems = set()
            if hasattr(vm, 'template') and vm.template:
                self.template = vm.template.name
            else:
                self.template = None
            if vm.netvm:
                self.netvm = vm.netvm.name
            else:
                self.netvm = None
            self.name = vm.name
            self.orig_template = None

        @property
        def good_to_go(self):
            return len(self.problems) == 0

    class Dom0ToRestore(VMToRestore):
        #: backup was performed on system with different dom0 username
        USERNAME_MISMATCH = object()

        def __init__(self, vm, subdir=None):
            super(BackupRestore.Dom0ToRestore, self).__init__(vm)
            if subdir:
                self.subdir = subdir
            self.username = os.path.basename(subdir)

    def __init__(self, app, backup_location, backup_vm, passphrase):
        super(BackupRestore, self).__init__()

        #: qubes.Qubes instance
        self.app = app

        #: options how the backup should be restored
        self.options = BackupRestoreOptions()

        #: VM from which backup should be retrieved
        self.backup_vm = backup_vm
        if backup_vm and backup_vm.qid == 0:
            self.backup_vm = None

        #: backup path, inside VM pointed by :py:attr:`backup_vm`
        self.backup_location = backup_location

        #: passphrase protecting backup integrity and optionally decryption
        self.passphrase = passphrase

        #: temporary directory used to extract the data before moving to the
        # final location; should be on the same filesystem as /var/lib/qubes
        self.tmpdir = tempfile.mkdtemp(prefix="restore", dir="/var/tmp")

        #: list of processes (Popen objects) to kill on cancel
        self.processes_to_kill_on_cancel = []

        #: is the backup operation canceled
        self.canceled = False

        #: report restore progress, called with one argument - percents of
        # data restored
        # FIXME: convert to float [0,1]
        self.progress_callback = None

        self.log = logging.getLogger('qubes.backup')

        #: basic information about the backup
        self.header_data = self._retrieve_backup_header()

        #: VMs included in the backup
        self.backup_app = self._process_qubes_xml()

    def cancel(self):
        """Cancel running backup operation. Can be called from another thread.
        """
        self.canceled = True
        for proc in self.processes_to_kill_on_cancel:
            try:
                proc.terminate()
            except OSError:
                pass

    def _start_retrieval_process(self, filelist, limit_count, limit_bytes):
        """Retrieve backup stream and extract it to :py:attr:`tmpdir`

        :param filelist: list of files to extract; listing directory name
        will extract the whole directory; use empty list to extract the whole
        archive
        :param limit_count: maximum number of files to extract
        :param limit_bytes: maximum size of extracted data
        :return: a touple of (Popen object of started process, file-like
        object for reading extracted files list, file-like object for reading
        errors)
        """

        vmproc = None
        if self.backup_vm is not None:
            # If APPVM, STDOUT is a PIPE
            vmproc = self.backup_vm.run_service('qubes.Restore',
                passio_popen=True, passio_stderr=True)
            vmproc.stdin.write(
                self.backup_location.replace("\r", "").replace("\n", "") + "\n")

            # Send to tar2qfile the VMs that should be extracted
            vmproc.stdin.write(" ".join(filelist) + "\n")
            self.processes_to_kill_on_cancel.append(vmproc)

            backup_stdin = vmproc.stdout
            tar1_command = ['/usr/libexec/qubes/qfile-dom0-unpacker',
                            str(os.getuid()), self.tmpdir, '-v']
        else:
            backup_stdin = open(self.backup_location, 'rb')

            tar1_command = ['tar',
                            '-ixv',
                            '-C', self.tmpdir] + filelist

        tar1_env = os.environ.copy()
        tar1_env['UPDATES_MAX_BYTES'] = str(limit_bytes)
        tar1_env['UPDATES_MAX_FILES'] = str(limit_count)
        self.log.debug("Run command" + unicode(tar1_command))
        command = subprocess.Popen(
            tar1_command,
            stdin=backup_stdin,
            stdout=vmproc.stdin if vmproc else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=tar1_env)
        self.processes_to_kill_on_cancel.append(command)

        # qfile-dom0-unpacker output filelist on stderr
        # and have stdout connected to the VM), while tar output filelist
        # on stdout
        if self.backup_vm:
            filelist_pipe = command.stderr
            # let qfile-dom0-unpacker hold the only open FD to the write end of
            # pipe, otherwise qrexec-client will not receive EOF when
            # qfile-dom0-unpacker terminates
            vmproc.stdin.close()
        else:
            filelist_pipe = command.stdout

        if self.backup_vm:
            error_pipe = vmproc.stderr
        else:
            error_pipe = command.stderr
        return command, filelist_pipe, error_pipe

    def _verify_hmac(self, filename, hmacfile, algorithm=None):
        def load_hmac(hmac_text):
            hmac_text = hmac_text.strip().split("=")
            if len(hmac_text) > 1:
                hmac_text = hmac_text[1].strip()
            else:
                raise qubes.exc.QubesException(
                    "ERROR: invalid hmac file content")

            return hmac_text
        if algorithm is None:
            algorithm = self.header_data.hmac_algorithm
        passphrase = self.passphrase.encode('utf-8')
        self.log.debug("Verifying file {}".format(filename))

        if hmacfile != filename + ".hmac":
            raise qubes.exc.QubesException(
                "ERROR: expected hmac for {}, but got {}".
                format(filename, hmacfile))

        hmac_proc = subprocess.Popen(
            ["openssl", "dgst", "-" + algorithm, "-hmac", passphrase],
            stdin=open(os.path.join(self.tmpdir, filename), 'rb'),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        hmac_stdout, hmac_stderr = hmac_proc.communicate()

        if len(hmac_stderr) > 0:
            raise qubes.exc.QubesException(
                "ERROR: verify file {0}: {1}".format(filename, hmac_stderr))
        else:
            self.log.debug("Loading hmac for file {}".format(filename))
            hmac = load_hmac(open(os.path.join(self.tmpdir, hmacfile),
                'r').read())

            if len(hmac) > 0 and load_hmac(hmac_stdout) == hmac:
                os.unlink(os.path.join(self.tmpdir, hmacfile))
                self.log.debug(
                    "File verification OK -> Sending file {}".format(filename))
                return True
            else:
                raise qubes.exc.QubesException(
                    "ERROR: invalid hmac for file {0}: {1}. "
                    "Is the passphrase correct?".
                    format(filename, load_hmac(hmac_stdout)))

    def _retrieve_backup_header(self):
        """Retrieve backup header and qubes.xml. Only backup header is
        analyzed, qubes.xml is left as-is
        (not even verified/decrypted/uncompressed)

        :return header_data
        :rtype :py:class:`BackupHeader`
        """

        if not self.backup_vm and os.path.exists(
                os.path.join(self.backup_location, 'qubes.xml')):
            # backup format version 1 doesn't have header
            header_data = BackupHeader()
            header_data.version = 1
            return header_data

        (retrieve_proc, filelist_pipe, error_pipe) = \
            self._start_retrieval_process(
                ['backup-header', 'backup-header.hmac',
                'qubes.xml.000', 'qubes.xml.000.hmac'], 4, 1024 * 1024)

        expect_tar_error = False

        filename = filelist_pipe.readline().strip()
        hmacfile = filelist_pipe.readline().strip()
        # tar output filename before actually extracting it, so wait for the
        # next one before trying to access it
        if not self.backup_vm:
            filelist_pipe.readline().strip()

        self.log.debug("Got backup header and hmac: {}, {}".format(
            filename, hmacfile))

        if not filename or filename == "EOF" or \
                not hmacfile or hmacfile == "EOF":
            retrieve_proc.wait()
            proc_error_msg = error_pipe.read(MAX_STDERR_BYTES)
            raise qubes.exc.QubesException(
                "Premature end of archive while receiving "
                "backup header. Process output:\n" + proc_error_msg)
        file_ok = False
        hmac_algorithm = DEFAULT_HMAC_ALGORITHM
        for hmac_algo in get_supported_hmac_algo(hmac_algorithm):
            try:
                if self._verify_hmac(filename, hmacfile, hmac_algo):
                    file_ok = True
                    hmac_algorithm = hmac_algo
                    break
            except qubes.exc.QubesException:
                # Ignore exception here, try the next algo
                pass
        if not file_ok:
            raise qubes.exc.QubesException(
                "Corrupted backup header (hmac verification "
                "failed). Is the password correct?")
        if os.path.basename(filename) == HEADER_FILENAME:
            filename = os.path.join(self.tmpdir, filename)
            header_data = BackupHeader(open(filename, 'r').read())
            os.unlink(filename)
        else:
            # if no header found, create one with guessed HMAC algo
            header_data = BackupHeader(
                version=2,
                hmac_algorithm=hmac_algorithm,
                # place explicitly this value, because it is what format_version
                # 2 have
                crypto_algorithm='aes-256-cbc',
                # TODO: set encrypted to something...
            )
            # when tar do not find expected file in archive, it exit with
            # code 2. This will happen because we've requested backup-header
            # file, but the archive do not contain it. Ignore this particular
            # error.
            if not self.backup_vm:
                expect_tar_error = True

        if retrieve_proc.wait() != 0 and not expect_tar_error:
            raise qubes.exc.QubesException(
                "unable to read the qubes backup file {0} ({1}): {2}".format(
                    self.backup_location,
                    retrieve_proc.wait(),
                    error_pipe.read(MAX_STDERR_BYTES)
                ))
        if retrieve_proc in self.processes_to_kill_on_cancel:
            self.processes_to_kill_on_cancel.remove(retrieve_proc)
        # wait for other processes (if any)
        for proc in self.processes_to_kill_on_cancel:
            if proc.wait() != 0:
                raise qubes.exc.QubesException(
                    "Backup header retrieval failed (exit code {})".format(
                        proc.wait())
                )
        return header_data

    def _start_inner_extraction_worker(self, queue):
        """Start a worker process, extracting inner layer of bacup archive,
        extract them to :py:attr:`tmpdir`.
        End the data by pushing QUEUE_FINISHED or QUEUE_ERROR to the queue.

        :param queue :py:class:`Queue` object to handle files from
        """

        # Setup worker to extract encrypted data chunks to the restore dirs
        # Create the process here to pass it options extracted from
        # backup header
        extractor_params = {
            'queue': queue,
            'base_dir': self.tmpdir,
            'passphrase': self.passphrase,
            'encrypted': self.header_data.encrypted,
            'compressed': self.header_data.compressed,
            'crypto_algorithm': self.header_data.crypto_algorithm,
            'verify_only': self.options.verify_only,
            'progress_callback': self.progress_callback,
        }
        format_version = self.header_data.version
        if format_version == 2:
            extract_proc = ExtractWorker2(**extractor_params)
        elif format_version in [3, 4]:
            extractor_params['compression_filter'] = \
                self.header_data.compression_filter
            extract_proc = ExtractWorker3(**extractor_params)
        else:
            raise NotImplementedError(
                "Backup format version %d not supported" % format_version)
        extract_proc.start()
        return extract_proc

    def _process_qubes_xml(self):
        """Verify, unpack and load qubes.xml. Possibly convert its format if
        necessary. It expect that :py:attr:`header_data` is already populated,
        and :py:meth:`retrieve_backup_header` was called.
        """
        if self.header_data.version == 1:
            backup_app = qubes.core2migration.Core2Qubes(
                os.path.join(self.backup_location, 'qubes.xml'))
            return backup_app
        else:
            self._verify_hmac("qubes.xml.000", "qubes.xml.000.hmac")
            queue = Queue()
            queue.put("qubes.xml.000")
            queue.put(QUEUE_FINISHED)

        extract_proc = self._start_inner_extraction_worker(queue)
        extract_proc.join()
        if extract_proc.exitcode != 0:
            raise qubes.exc.QubesException(
                "unable to extract the qubes backup. "
                "Check extracting process errors.")

        if self.header_data.version in [2, 3]:
            backup_app = qubes.core2migration.Core2Qubes(
                os.path.join(self.tmpdir, 'qubes.xml'))
        else:
            backup_app = qubes.Qubes(os.path.join(self.tmpdir, 'qubes.xml'))
        # Not needed anymore - all the data stored in backup_app
        os.unlink(os.path.join(self.tmpdir, 'qubes.xml'))
        return backup_app

    def _restore_vm_dirs(self, vms_dirs, vms_size):
        # Currently each VM consists of at most 7 archives (count
        # file_to_backup calls in backup_prepare()), but add some safety
        # margin for further extensions. Each archive is divided into 100MB
        # chunks. Additionally each file have own hmac file. So assume upper
        # limit as 2*(10*COUNT_OF_VMS+TOTAL_SIZE/100MB)
        limit_count = str(2 * (10 * len(vms_dirs) +
                               int(vms_size / (100 * 1024 * 1024))))

        self.log.debug("Working in temporary dir:" + self.tmpdir)
        self.log.info(
            "Extracting data: " + size_to_human(vms_size) + " to restore")

        # retrieve backup from the backup stream (either VM, or dom0 file)
        # TODO: add some safety margin in vms_size?
        (retrieve_proc, filelist_pipe, error_pipe) = \
            self._start_retrieval_process(vms_dirs, limit_count, vms_size)

        to_extract = Queue()

        # extract data retrieved by retrieve_proc
        extract_proc = self._start_inner_extraction_worker(to_extract)

        try:
            filename = None
            nextfile = None
            while True:
                if self.canceled:
                    break
                if not extract_proc.is_alive():
                    retrieve_proc.terminate()
                    retrieve_proc.wait()
                    if retrieve_proc in self.processes_to_kill_on_cancel:
                        self.processes_to_kill_on_cancel.remove(retrieve_proc)
                    # wait for other processes (if any)
                    for proc in self.processes_to_kill_on_cancel:
                        proc.wait()
                    break
                if nextfile is not None:
                    filename = nextfile
                else:
                    filename = filelist_pipe.readline().strip()

                self.log.debug("Getting new file:" + filename)

                if not filename or filename == "EOF":
                    break

                hmacfile = filelist_pipe.readline().strip()

                if self.canceled:
                    break
                # if reading archive directly with tar, wait for next filename -
                # tar prints filename before processing it, so wait for
                # the next one to be sure that whole file was extracted
                if not self.backup_vm:
                    nextfile = filelist_pipe.readline().strip()

                self.log.debug("Getting hmac:" + hmacfile)
                if not hmacfile or hmacfile == "EOF":
                    # Premature end of archive, either of tar1_command or
                    # vmproc exited with error
                    break

                if not any(map(lambda x: filename.startswith(x), vms_dirs)):
                    self.log.debug("Ignoring VM not selected for restore")
                    os.unlink(os.path.join(self.tmpdir, filename))
                    os.unlink(os.path.join(self.tmpdir, hmacfile))
                    continue

                if self._verify_hmac(filename, hmacfile):
                    to_extract.put(os.path.join(self.tmpdir, filename))

            if self.canceled:
                raise BackupCanceledError("Restore canceled",
                                          tmpdir=self.tmpdir)

            if retrieve_proc.wait() != 0:
                raise qubes.exc.QubesException(
                    "unable to read the qubes backup file {0} ({1}): {2}"
                    .format(self.backup_location, error_pipe.read(
                        MAX_STDERR_BYTES)))
            # wait for other processes (if any)
            for proc in self.processes_to_kill_on_cancel:
                # FIXME check 'vmproc' exit code?
                proc.wait()

            if filename and filename != "EOF":
                raise qubes.exc.QubesException(
                    "Premature end of archive, the last file was %s" % filename)
        except:
            to_extract.put(QUEUE_ERROR)
            extract_proc.join()
            raise
        else:
            to_extract.put(QUEUE_FINISHED)

        self.log.debug("Waiting for the extraction process to finish...")
        extract_proc.join()
        self.log.debug("Extraction process finished with code: {}".format(
            extract_proc.exitcode))
        if extract_proc.exitcode != 0:
            raise qubes.exc.QubesException(
                "unable to extract the qubes backup. "
                "Check extracting process errors.")

    def generate_new_name_for_conflicting_vm(self, orig_name, restore_info):
        number = 1
        if len(orig_name) > 29:
            orig_name = orig_name[0:29]
        new_name = orig_name
        while (new_name in restore_info.keys() or
               new_name in map(lambda x: x.name,
                               restore_info.values()) or
               new_name in self.app.domains):
            new_name = str('{}{}'.format(orig_name, number))
            number += 1
            if number == 100:
                # give up
                return None
        return new_name

    def restore_info_verify(self, restore_info):
        for vm in restore_info.keys():
            if vm in ['dom0']:
                continue

            vm_info = restore_info[vm]
            assert isinstance(vm_info, self.VMToRestore)

            vm_info.problems.clear()
            if vm in self.options.exclude:
                vm_info.problems.add(self.VMToRestore.EXCLUDED)

            if not self.options.verify_only and \
                    vm in self.app.domains:
                if self.options.rename_conflicting:
                    new_name = self.generate_new_name_for_conflicting_vm(
                        vm, restore_info
                    )
                    if new_name is not None:
                        vm_info.name = new_name
                    else:
                        vm_info.problems.add(self.VMToRestore.ALREADY_EXISTS)
                else:
                    vm_info.problems.add(self.VMToRestore.ALREADY_EXISTS)

            # check template
            if vm_info.template:
                template_name = vm_info.template
                try:
                    host_template = self.app.domains[template_name]
                except KeyError:
                    host_template = None
                if not host_template or not host_template.is_template():
                    # Maybe the (custom) template is in the backup?
                    if not (template_name in restore_info.keys() and
                            restore_info[template_name].good_to_go and
                            restore_info[template_name].vm.is_template()):
                        if self.options.use_default_template and \
                                self.app.default_template:
                            if vm_info.orig_template is None:
                                vm_info.orig_template = template_name
                            vm_info.template = self.app.default_template.name
                        else:
                            vm_info.problems.add(
                                self.VMToRestore.MISSING_TEMPLATE)

            # check netvm
            if not vm_info.vm.property_is_default('netvm') and vm_info.netvm:
                netvm_name = vm_info.netvm

                try:
                    netvm_on_host = self.app.domains[netvm_name]
                except KeyError:
                    netvm_on_host = None
                # No netvm on the host?
                if not ((netvm_on_host is not None)
                        and netvm_on_host.provides_network):

                    # Maybe the (custom) netvm is in the backup?
                    if not (netvm_name in restore_info.keys() and
                            restore_info[netvm_name].good_to_go and
                            restore_info[netvm_name].vm.provides_network):
                        if self.options.use_default_netvm:
                            vm_info.vm.netvm = qubes.property.DEFAULT
                        elif self.options.use_none_netvm:
                            vm_info.netvm = None
                        else:
                            vm_info.problems.add(self.VMToRestore.MISSING_NETVM)

        return restore_info

    def _is_vm_included_in_backup_v1(self, check_vm):
        if check_vm.qid == 0:
            return os.path.exists(
                os.path.join(self.backup_location, 'dom0-home'))

        # DisposableVM
        if check_vm.dir_path is None:
            return False

        backup_vm_dir_path = check_vm.dir_path.replace(
            qubes.config.system_path["qubes_base_dir"], self.backup_location)

        if os.path.exists(backup_vm_dir_path):
            return True
        else:
            return False

    @staticmethod
    def _is_vm_included_in_backup_v2(check_vm):
        if 'backup-content' in check_vm.features:
            return check_vm.features['backup-content']
        else:
            return False

    def _find_template_name(self, template):
        if template in self.options.replace_template:
            return self.options.replace_template[template]
        return template

    def _is_vm_included_in_backup(self, vm):
        if self.header_data.version == 1:
            return self._is_vm_included_in_backup_v1(vm)
        elif self.header_data.version in [2, 3, 4]:
            return self._is_vm_included_in_backup_v2(vm)
        else:
            raise qubes.exc.QubesException(
                "Unknown backup format version: {}".format(
                    self.header_data.version))

    def get_restore_info(self):
        # Format versions:
        # 1 - Qubes R1, Qubes R2 beta1, beta2
        #  2 - Qubes R2 beta3+

        vms_to_restore = {}

        for vm in self.backup_app.domains:
            if vm.qid == 0:
                # Handle dom0 as special case later
                continue
            if self._is_vm_included_in_backup(vm):
                self.log.debug("{} is included in backup".format(vm.name))

                vms_to_restore[vm.name] = self.VMToRestore(vm)

                if hasattr(vm, 'template'):
                    templatevm_name = self._find_template_name(
                        vm.template.name)
                    vms_to_restore[vm.name].template = templatevm_name

                # Set to None to not confuse QubesVm object from backup
                # collection with host collection (further in clone_attrs).
                vm.netvm = None

        vms_to_restore = self.restore_info_verify(vms_to_restore)

        # ...and dom0 home
        if self.options.dom0_home and \
                self._is_vm_included_in_backup(self.backup_app.domains[0]):
            vm = self.backup_app.domains[0]
            if self.header_data.version == 1:
                subdir = os.listdir(os.path.join(self.backup_location,
                    'dom0-home'))[0]
            else:
                subdir = None
            vms_to_restore['dom0'] = self.Dom0ToRestore(vm, subdir)
            local_user = grp.getgrnam('qubes').gr_mem[0]

            if vms_to_restore['dom0'].username != local_user:
                if not self.options.ignore_username_mismatch:
                    vms_to_restore['dom0'].problems.add(
                        self.Dom0ToRestore.USERNAME_MISMATCH)

        return vms_to_restore

    @staticmethod
    def get_restore_summary(restore_info):
        fields = {
            "qid": {"func": "vm.qid"},

            "name": {"func": "('[' if vm.is_template() else '')\
                     + ('{' if vm.is_netvm() else '')\
                     + vm.name \
                     + (']' if vm.is_template() else '')\
                     + ('}' if vm.is_netvm() else '')"},

            "type": {"func": "'Tpl' if vm.is_template() else \
                     'App' if isinstance(vm, qubes.vm.appvm.AppVM) else \
                     vm.__class__.__name__.replace('VM','')"},

            "updbl": {"func": "'Yes' if vm.updateable else ''"},

            "template": {"func": "'n/a' if not hasattr(vm, 'template') is None "
                                 "else vm_info.template"},

            "netvm": {"func": "'n/a' if vm.is_netvm() and not vm.is_proxyvm() else\
                      ('*' if vm.property_is_default('netvm') else '') +\
                        vm_info.netvm if vm_info.netvm is not None "
                              "else '-'"},

            "label": {"func": "vm.label.name"},
        }

        fields_to_display = ["name", "type", "template", "updbl",
            "netvm", "label"]

        # First calculate the maximum width of each field we want to display
        total_width = 0
        for f in fields_to_display:
            fields[f]["max_width"] = len(f)
            for vm_info in restore_info.values():
                if vm_info.vm:
                    # noinspection PyUnusedLocal
                    vm = vm_info.vm
                    l = len(unicode(eval(fields[f]["func"])))
                    if l > fields[f]["max_width"]:
                        fields[f]["max_width"] = l
            total_width += fields[f]["max_width"]

        summary = ""
        summary += "The following VMs are included in the backup:\n"
        summary += "\n"

        # Display the header
        for f in fields_to_display:
            # noinspection PyTypeChecker
            fmt = "{{0:-^{0}}}-+".format(fields[f]["max_width"] + 1)
            summary += fmt.format('-')
        summary += "\n"
        for f in fields_to_display:
            # noinspection PyTypeChecker
            fmt = "{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
            summary += fmt.format(f)
        summary += "\n"
        for f in fields_to_display:
            # noinspection PyTypeChecker
            fmt = "{{0:-^{0}}}-+".format(fields[f]["max_width"] + 1)
            summary += fmt.format('-')
        summary += "\n"

        for vm_info in restore_info.values():
            assert isinstance(vm_info, BackupRestore.VMToRestore)
            # Skip non-VM here
            if not vm_info.vm:
                continue
            # noinspection PyUnusedLocal
            vm = vm_info.vm
            s = ""
            for f in fields_to_display:
                # noinspection PyTypeChecker
                fmt = "{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
                s += fmt.format(eval(fields[f]["func"]))

            if BackupRestore.VMToRestore.EXCLUDED in vm_info.problems:
                s += " <-- Excluded from restore"
            elif BackupRestore.VMToRestore.ALREADY_EXISTS in vm_info.problems:
                s += " <-- A VM with the same name already exists on the host!"
            elif BackupRestore.VMToRestore.MISSING_TEMPLATE in \
                    vm_info.problems:
                s += " <-- No matching template on the host " \
                     "or in the backup found!"
            elif BackupRestore.VMToRestore.MISSING_NETVM in \
                    vm_info.problems:
                s += " <-- No matching netvm on the host " \
                     "or in the backup found!"
            else:
                if vm_info.orig_template:
                    s += " <-- Original template was '{}'".format(
                        vm_info.orig_template)
                if vm_info.name != vm_info.vm.name:
                    s += " <-- Will be renamed to '{}'".format(
                        vm_info.name)

            summary += s + "\n"

        if 'dom0' in restore_info.keys():
            s = ""
            for f in fields_to_display:
                # noinspection PyTypeChecker
                fmt = "{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
                if f == "name":
                    s += fmt.format("Dom0")
                elif f == "type":
                    s += fmt.format("Home")
                else:
                    s += fmt.format("")
            if BackupRestore.Dom0ToRestore.USERNAME_MISMATCH in \
                    restore_info['dom0'].problems:
                s += " <-- username in backup and dom0 mismatch"

            summary += s + "\n"

        return summary

    def _restore_vm_dir_v1(self, src_dir, dst_dir):

        backup_src_dir = src_dir.replace(
            qubes.config.system_path["qubes_base_dir"], self.backup_location)

        # We prefer to use Linux's cp, because it nicely handles sparse files
        cp_retcode = subprocess.call(
            ["cp", "-rp", "--reflink=auto", backup_src_dir, dst_dir])
        if cp_retcode != 0:
            raise qubes.exc.QubesException(
                "*** Error while copying file {0} to {1}".format(backup_src_dir,
                                                                 dst_dir))

    def restore_do(self, restore_info):
        # FIXME handle locking

        # Perform VM restoration in backup order
        vms_dirs = []
        vms_size = 0
        vms = {}
        for vm_info in restore_info.values():
            assert isinstance(vm_info, self.VMToRestore)
            if not vm_info.vm:
                continue
            if not vm_info.good_to_go:
                continue
            vm = vm_info.vm
            if self.header_data.version >= 2:
                if vm.features['backup-size']:
                    vms_size += int(vm.features['backup-size'])
                vms_dirs.append(vm.features['backup-path'])
            vms[vm.name] = vm

        if self.header_data.version >= 2:
            if 'dom0' in restore_info.keys() and \
                    restore_info['dom0'].good_to_go:
                vms_dirs.append(os.path.dirname(restore_info['dom0'].subdir))
                vms_size += restore_info['dom0'].size

            try:
                self._restore_vm_dirs(vms_dirs=vms_dirs, vms_size=vms_size)
            except qubes.exc.QubesException:
                if self.options.verify_only:
                    raise
                else:
                    self.log.warning(
                        "Some errors occurred during data extraction, "
                        "continuing anyway to restore at least some "
                        "VMs")
        else:
            if self.options.verify_only:
                self.log.warning(
                    "Backup verification not supported for this backup format.")

        if self.options.verify_only:
            shutil.rmtree(self.tmpdir)
            return

        # First load templates, then other VMs
        for vm in sorted(vms.values(), key=lambda x: x.is_template(),
                reverse=True):
            if self.canceled:
                # only break the loop to save qubes.xml
                # with already restored VMs
                break
            self.log.info("-> Restoring {0}...".format(vm.name))
            retcode = subprocess.call(
                ["mkdir", "-p", os.path.dirname(vm.dir_path)])
            if retcode != 0:
                self.log.error("*** Cannot create directory: {0}?!".format(
                    vm.dir_path))
                self.log.warning("Skipping VM {}...".format(vm.name))
                continue

            kwargs = {}
            if hasattr(vm, 'template'):
                template = restore_info[vm.name].template
                # handle potentially renamed template
                if template in restore_info \
                        and restore_info[template].good_to_go:
                    template = restore_info[template].name
                kwargs['template'] = template

            new_vm = None
            vm_name = restore_info[vm.name].name

            try:
                # first only minimal set, later clone_properties
                # will be called
                new_vm = self.app.add_new_vm(
                    vm.__class__,
                    name=vm_name,
                    label=vm.label,
                    installed_by_rpm=False,
                    **kwargs)
                if os.path.exists(new_vm.dir_path):
                    move_to_path = tempfile.mkdtemp('', os.path.basename(
                        new_vm.dir_path), os.path.dirname(new_vm.dir_path))
                    try:
                        os.rename(new_vm.dir_path, move_to_path)
                        self.log.warning(
                            "*** Directory {} already exists! It has "
                            "been moved to {}".format(new_vm.dir_path,
                                                      move_to_path))
                    except OSError:
                        self.log.error(
                            "*** Directory {} already exists and "
                            "cannot be moved!".format(new_vm.dir_path))
                        self.log.warning("Skipping VM {}...".format(
                            vm.name))
                        continue

                if self.header_data.version == 1:
                    self._restore_vm_dir_v1(vm.dir_path,
                        os.path.dirname(new_vm.dir_path))
                else:
                    shutil.move(os.path.join(self.tmpdir,
                        vm.features['backup-path']),
                        new_vm.dir_path)

                new_vm.verify_files()
            except Exception as err:
                self.log.error("ERROR: {0}".format(err))
                self.log.warning("*** Skipping VM: {0}".format(vm.name))
                if new_vm:
                    del self.app.domains[new_vm.qid]
                continue

            if hasattr(vm, 'kernel'):
                # TODO: add a setting for this?
                if not vm.property_is_default('kernel') and vm.kernel and \
                        vm.kernel not in \
                        os.listdir(os.path.join(qubes.config.qubes_base_dir,
                            qubes.config.system_path[
                            'qubes_kernels_base_dir'])):
                    self.log.warning("Kernel %s not installed, "
                    "using default one" % vm.kernel)
                    vm.kernel = qubes.property.DEFAULT
            # remove no longer needed backup metadata
            if 'backup-content' in vm.features:
                del vm.features['backup-content']
                del vm.features['backup-size']
                del vm.features['backup-path']
            try:
                # exclude VM references - handled manually according to
                # restore options
                proplist = [prop for prop in new_vm.property_list()
                    if prop.clone and prop.__name__ not in
                          ['template', 'netvm', 'dispvm_netvm']]
                new_vm.clone_properties(vm, proplist=proplist)
            except Exception as err:
                self.log.error("ERROR: {0}".format(err))
                self.log.warning("*** Some VM property will not be "
                                 "restored")

            try:
                new_vm.fire_event('domain-restore')
            except Exception as err:
                self.log.error("ERROR during appmenu restore: "
                   "{0}".format(err))
                self.log.warning(
                    "*** VM '{0}' will not have appmenus".format(vm.name))

        # Set network dependencies - only non-default netvm setting
        for vm in vms.values():
            vm_info = restore_info[vm.name]
            vm_name = vm_info.name
            try:
                host_vm = self.app.domains[vm_name]
            except KeyError:
                # Failed/skipped VM
                continue

            if not vm.property_is_default('netvm'):
                if vm_info.netvm in restore_info:
                    host_vm.netvm = restore_info[vm_info.netvm].name
                else:
                    host_vm.netvm = vm_info.netvm

        self.app.save()

        if self.canceled:
            if self.header_data.version >= 2:
                raise BackupCanceledError("Restore canceled",
                                          tmpdir=self.tmpdir)
            else:
                raise BackupCanceledError("Restore canceled")

        # ... and dom0 home as last step
        if 'dom0' in restore_info.keys() and restore_info['dom0'].good_to_go:
            backup_path = restore_info['dom0'].subdir
            local_user = grp.getgrnam('qubes').gr_mem[0]
            home_dir = pwd.getpwnam(local_user).pw_dir
            if self.header_data.version == 1:
                backup_dom0_home_dir = os.path.join(self.backup_location,
                    backup_path)
            else:
                backup_dom0_home_dir = os.path.join(self.tmpdir, backup_path)
            restore_home_backupdir = "home-pre-restore-{0}".format(
                time.strftime("%Y-%m-%d-%H%M%S"))

            self.log.info(
                "Restoring home of user '{0}'...".format(local_user))
            self.log.info(
                "Existing files/dirs backed up in '{0}' dir".format(
                    restore_home_backupdir))
            os.mkdir(home_dir + '/' + restore_home_backupdir)
            for f in os.listdir(backup_dom0_home_dir):
                home_file = home_dir + '/' + f
                if os.path.exists(home_file):
                    os.rename(home_file,
                              home_dir + '/' + restore_home_backupdir + '/' + f)
                if self.header_data.version == 1:
                    subprocess.call(
                        ["cp", "-nrp", "--reflink=auto",
                            backup_dom0_home_dir + '/' + f, home_file])
                elif self.header_data.version >= 2:
                    shutil.move(backup_dom0_home_dir + '/' + f, home_file)
            retcode = subprocess.call(['sudo', 'chown', '-R',
                local_user, home_dir])
            if retcode != 0:
                self.log.error("*** Error while setting home directory owner")

        shutil.rmtree(self.tmpdir)

# vim:sw=4:et:
