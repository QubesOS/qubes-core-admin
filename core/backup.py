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
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#
from __future__ import unicode_literals

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

from qubes import QubesException, QubesVmCollection, qubes_base_dir
from qubes import QubesVmClasses
from qubes import system_path, vm_files
from backupparser import SafeQubesVmCollection
from qubesutils import size_to_human, print_stdout, print_stderr, \
    get_disk_usage
from multiprocessing import Queue, Process

BACKUP_DEBUG = False

HEADER_FILENAME = 'backup-header'
DEFAULT_CRYPTO_ALGORITHM = 'aes-256-cbc'
DEFAULT_HMAC_ALGORITHM = 'SHA512'
DEFAULT_COMPRESSION_FILTER = 'gzip'
CURRENT_BACKUP_FORMAT_VERSION = '3'
# Maximum size of error message get from process stderr (including VM process)
MAX_STDERR_BYTES = 1024
# header + qubes.xml max size
HEADER_QUBES_XML_MAX_SIZE = 1024 * 1024

# global state for backup_cancel()
running_backup_operation = None


class BackupOperationInfo:
    def __init__(self):
        self.canceled = False
        self.processes_to_kill_on_cancel = []
        self.tmpdir_to_remove = None


class BackupCanceledError(QubesException):
    def __init__(self, msg, tmpdir=None):
        super(BackupCanceledError, self).__init__(msg)
        self.tmpdir = tmpdir


class BackupHeader:
    version = 'version'
    encrypted = 'encrypted'
    compressed = 'compressed'
    compression_filter = 'compression-filter'
    crypto_algorithm = 'crypto-algorithm'
    hmac_algorithm = 'hmac-algorithm'
    bool_options = ['encrypted', 'compressed']
    int_options = ['version']


def file_to_backup(file_path, subdir=None):
    sz = get_disk_usage(file_path)

    if subdir is None:
        abs_file_path = os.path.abspath(file_path)
        abs_base_dir = os.path.abspath(system_path["qubes_base_dir"]) + '/'
        abs_file_dir = os.path.dirname(abs_file_path) + '/'
        (nothing, directory, subdir) = abs_file_dir.partition(abs_base_dir)
        assert nothing == ""
        assert directory == abs_base_dir
    else:
        if len(subdir) > 0 and not subdir.endswith('/'):
            subdir += '/'
    return [{"path": file_path, "size": sz, "subdir": subdir}]


def backup_cancel():
    """
    Cancel currently running backup/restore operation

    @return: True if any operation was signaled
    """
    if running_backup_operation is None:
        return False

    running_backup_operation.canceled = True
    for proc in running_backup_operation.processes_to_kill_on_cancel:
        try:
            proc.terminate()
        except:
            pass
    return True


def backup_prepare(vms_list=None, exclude_list=None,
                   print_callback=print_stdout, hide_vm_names=True):
    """
    If vms = None, include all (sensible) VMs;
    exclude_list is always applied
    """
    files_to_backup = file_to_backup(system_path["qubes_store_filename"])

    if exclude_list is None:
        exclude_list = []

    qvm_collection = QubesVmCollection()
    qvm_collection.lock_db_for_writing()
    qvm_collection.load()

    if vms_list is None:
        all_vms = [vm for vm in qvm_collection.values()]
        selected_vms = [vm for vm in all_vms if vm.include_in_backups]
        appvms_to_backup = [vm for vm in selected_vms if
                            vm.is_appvm() and not vm.internal]
        netvms_to_backup = [vm for vm in selected_vms if
                            vm.is_netvm() and not vm.qid == 0]
        template_vms_worth_backingup = [vm for vm in selected_vms if (
            vm.is_template() and vm.include_in_backups)]
        dom0 = [qvm_collection[0]]

        vms_list = appvms_to_backup + netvms_to_backup + \
            template_vms_worth_backingup + dom0

    vms_for_backup = vms_list
    # Apply exclude list
    if exclude_list:
        vms_for_backup = [vm for vm in vms_list if vm.name not in exclude_list]

    there_are_running_vms = False

    fields_to_display = [
        {"name": "VM", "width": 16},
        {"name": "type", "width": 12},
        {"name": "size", "width": 12}
    ]

    # Display the header
    s = ""
    for f in fields_to_display:
        fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt = "{{0:>{0}}} |".format(f["width"] + 1)
        s += fmt.format(f["name"])
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    files_to_backup_index = 0
    for vm in sorted(vms_for_backup, key=lambda vm: vm.name):
        if vm.is_template():
            # handle templates later
            continue
        if vm.qid == 0:
            # handle dom0 later
            continue

        if hide_vm_names:
            subdir = 'vm%d/' % vm.qid
        else:
            subdir = None

        if vm.private_img is not None:
            files_to_backup += file_to_backup(vm.private_img, subdir)

        if vm.is_appvm():
            files_to_backup += file_to_backup(vm.icon_path, subdir)
        if vm.updateable:
            if os.path.exists(vm.dir_path + "/apps.templates"):
                # template
                files_to_backup += file_to_backup(
                    vm.dir_path + "/apps.templates", subdir)
            else:
                # standaloneVM
                files_to_backup += file_to_backup(vm.dir_path + "/apps", subdir)

            if os.path.exists(vm.dir_path + "/kernels"):
                files_to_backup += file_to_backup(vm.dir_path + "/kernels",
                                                  subdir)
        if os.path.exists(vm.firewall_conf):
            files_to_backup += file_to_backup(vm.firewall_conf, subdir)
        if 'appmenus_whitelist' in vm_files and \
                os.path.exists(os.path.join(vm.dir_path,
                                            vm_files['appmenus_whitelist'])):
            files_to_backup += file_to_backup(
                os.path.join(vm.dir_path, vm_files['appmenus_whitelist']),
                subdir)

        if vm.updateable:
            files_to_backup += file_to_backup(vm.root_img, subdir)

        s = ""
        fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format(vm.name)

        fmt = "{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        if vm.is_netvm():
            s += fmt.format("NetVM" + (" + Sys" if vm.updateable else ""))
        else:
            s += fmt.format("AppVM" + (" + Sys" if vm.updateable else ""))

        vm_size = reduce(lambda x, y: x + y["size"],
                         files_to_backup[files_to_backup_index:],
                         0)
        files_to_backup_index = len(files_to_backup)

        fmt = "{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
        s += fmt.format(size_to_human(vm_size))

        if vm.is_running():
            s += " <-- The VM is running, please shut it down before proceeding " \
                 "with the backup!"
            there_are_running_vms = True

        print_callback(s)

    for vm in vms_for_backup:
        if not vm.is_template():
            # already handled
            continue
        if vm.qid == 0:
            # handle dom0 later
            continue
        vm_sz = vm.get_disk_utilization()
        if hide_vm_names:
            template_subdir = 'vm%d/' % vm.qid
        else:
            template_subdir = os.path.relpath(
                vm.dir_path,
                system_path["qubes_base_dir"]) + '/'
        template_to_backup = [{"path": vm.dir_path + '/.',
                               "size": vm_sz,
                               "subdir": template_subdir}]
        files_to_backup += template_to_backup

        s = ""
        fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format(vm.name)

        fmt = "{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        s += fmt.format("Template VM")

        fmt = "{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
        s += fmt.format(size_to_human(vm_sz))

        if vm.is_running():
            s += " <-- The VM is running, please shut it down before proceeding " \
                 "with the backup!"
            there_are_running_vms = True

        print_callback(s)

    # Initialize backup flag on all VMs
    vms_for_backup_qid = [vm.qid for vm in vms_for_backup]
    for vm in qvm_collection.values():
        vm.backup_content = False
        if vm.qid == 0:
            # handle dom0 later
            continue

        if vm.qid in vms_for_backup_qid:
            vm.backup_content = True
            vm.backup_size = vm.get_disk_utilization()
            if hide_vm_names:
                vm.backup_path = 'vm%d' % vm.qid
            else:
                vm.backup_path = os.path.relpath(vm.dir_path,
                                                 system_path["qubes_base_dir"])

    # Dom0 user home
    if 0 in vms_for_backup_qid:
        local_user = grp.getgrnam('qubes').gr_mem[0]
        home_dir = pwd.getpwnam(local_user).pw_dir
        # Home dir should have only user-owned files, so fix it now to prevent
        # permissions problems - some root-owned files can left after
        # 'sudo bash' and similar commands
        subprocess.check_call(['sudo', 'chown', '-R', local_user, home_dir])

        home_sz = get_disk_usage(home_dir)
        home_to_backup = [
            {"path": home_dir, "size": home_sz, "subdir": 'dom0-home/'}]
        files_to_backup += home_to_backup

        vm = qvm_collection[0]
        vm.backup_content = True
        vm.backup_size = home_sz
        vm.backup_path = os.path.join('dom0-home', os.path.basename(home_dir))

        s = ""
        fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
        s += fmt.format('Dom0')

        fmt = "{{0:>{0}}} |".format(fields_to_display[1]["width"] + 1)
        s += fmt.format("User home")

        fmt = "{{0:>{0}}} |".format(fields_to_display[2]["width"] + 1)
        s += fmt.format(size_to_human(home_sz))

        print_callback(s)

    qvm_collection.save()
    # FIXME: should be after backup completed
    qvm_collection.unlock_db()

    total_backup_sz = 0
    for f in files_to_backup:
        total_backup_sz += f["size"]

    s = ""
    for f in fields_to_display:
        fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    s = ""
    fmt = "{{0:>{0}}} |".format(fields_to_display[0]["width"] + 1)
    s += fmt.format("Total size:")
    fmt = "{{0:>{0}}} |".format(
        fields_to_display[1]["width"] + 1 + 2 + fields_to_display[2][
            "width"] + 1)
    s += fmt.format(size_to_human(total_backup_sz))
    print_callback(s)

    s = ""
    for f in fields_to_display:
        fmt = "{{0:-^{0}}}-+".format(f["width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    vms_not_for_backup = [vm.name for vm in qvm_collection.values()
                          if not vm.backup_content]
    print_callback("VMs not selected for backup:\n%s" % "\n".join(sorted(
        vms_not_for_backup)))

    if there_are_running_vms:
        raise QubesException("Please shutdown all VMs before proceeding.")

    for fileinfo in files_to_backup:
        assert len(fileinfo["subdir"]) == 0 or fileinfo["subdir"][-1] == '/', \
            "'subdir' must ends with a '/': %s" % unicode(fileinfo)

    return files_to_backup


class SendWorker(Process):
    def __init__(self, queue, base_dir, backup_stdout):
        super(SendWorker, self).__init__()
        self.queue = queue
        self.base_dir = base_dir
        self.backup_stdout = backup_stdout

    def run(self):
        if BACKUP_DEBUG:
            print "Started sending thread"

        if BACKUP_DEBUG:
            print "Moving to temporary dir", self.base_dir
        os.chdir(self.base_dir)

        for filename in iter(self.queue.get, None):
            if filename == "FINISHED" or filename == "ERROR":
                break

            if BACKUP_DEBUG:
                print "Sending file", filename
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
                raise QubesException(
                    "ERROR: Failed to write the backup, out of disk space? "
                    "Check console output or ~/.xsession-errors for details.")

            # Delete the file as we don't need it anymore
            if BACKUP_DEBUG:
                print "Removing file", filename
            os.remove(filename)

        if BACKUP_DEBUG:
            print "Finished sending thread"


def prepare_backup_header(target_directory, passphrase, compressed=False,
                          encrypted=False,
                          hmac_algorithm=DEFAULT_HMAC_ALGORITHM,
                          crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM,
                          compression_filter=None):
    header_file_path = os.path.join(target_directory, HEADER_FILENAME)
    with open(header_file_path, "w") as f:
        f.write(str("%s=%s\n" % (BackupHeader.version,
                                 CURRENT_BACKUP_FORMAT_VERSION)))
        f.write(str("%s=%s\n" % (BackupHeader.hmac_algorithm, hmac_algorithm)))
        f.write(str("%s=%s\n" % (BackupHeader.crypto_algorithm,
                                 crypto_algorithm)))
        f.write(str("%s=%s\n" % (BackupHeader.encrypted, str(encrypted))))
        f.write(str("%s=%s\n" % (BackupHeader.compressed, str(compressed))))
        if compressed:
            f.write(str("%s=%s\n" % (BackupHeader.compression_filter,
                                     str(compression_filter))))

    hmac = subprocess.Popen(["openssl", "dgst",
                             "-" + hmac_algorithm, "-hmac", passphrase],
                            stdin=open(header_file_path, "r"),
                            stdout=open(header_file_path + ".hmac", "w"))
    if hmac.wait() != 0:
        raise QubesException("Failed to compute hmac of header file")
    return HEADER_FILENAME, HEADER_FILENAME + ".hmac"


def backup_do(base_backup_dir, files_to_backup, passphrase,
              progress_callback=None, encrypted=False, appvm=None,
              compressed=False, hmac_algorithm=DEFAULT_HMAC_ALGORITHM,
              crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM,
              tmpdir=None):
    global running_backup_operation

    def queue_put_with_check(proc, vmproc, queue, element):
        if queue.full():
            if not proc.is_alive():
                if vmproc:
                    message = ("Failed to write the backup, VM output:\n" +
                               vmproc.stderr.read())
                else:
                    message = "Failed to write the backup. Out of disk space?"
                raise QubesException(message)
        queue.put(element)

    total_backup_sz = 0
    passphrase = passphrase.encode('utf-8')
    for f in files_to_backup:
        total_backup_sz += f["size"]

    if isinstance(compressed, str):
        compression_filter = compressed
    else:
        compression_filter = DEFAULT_COMPRESSION_FILTER

    running_backup_operation = BackupOperationInfo()
    vmproc = None
    tar_sparse = None
    if appvm is not None:
        # Prepare the backup target (Qubes service call)
        backup_target = "QUBESRPC qubes.Backup dom0"

        # If APPVM, STDOUT is a PIPE
        vmproc = appvm.run(command=backup_target, passio_popen=True,
                           passio_stderr=True)
        vmproc.stdin.write((base_backup_dir.
                            replace("\r", "").replace("\n", "") + "\n").
                                encode('utf-8'))
        backup_stdout = vmproc.stdin
        running_backup_operation.processes_to_kill_on_cancel.append(vmproc)
    else:
        # Prepare the backup target (local file)
        if os.path.isdir(base_backup_dir):
            backup_target = base_backup_dir + "/qubes-{0}". \
                format(time.strftime("%Y-%m-%dT%H%M%S"))
        else:
            backup_target = base_backup_dir

            # Create the target directory
            if not os.path.exists(os.path.dirname(base_backup_dir)):
                raise QubesException(
                    "ERROR: the backup directory for {0} does not exists".
                    format(base_backup_dir))

        # If not APPVM, STDOUT is a local file
        backup_stdout = open(backup_target, 'wb')

    global blocks_backedup
    blocks_backedup = 0
    if callable(progress_callback):
        progress = blocks_backedup * 11 / total_backup_sz
        progress_callback(progress)

    backup_tmpdir = tempfile.mkdtemp(prefix="backup_", dir=tmpdir)
    running_backup_operation.tmpdir_to_remove = backup_tmpdir

    # Tar with tape length does not deals well with stdout (close stdout between
    # two tapes)
    # For this reason, we will use named pipes instead
    if BACKUP_DEBUG:
        print "Working in", backup_tmpdir

    backup_pipe = os.path.join(backup_tmpdir, "backup_pipe")
    if BACKUP_DEBUG:
        print "Creating pipe in:", backup_pipe
    os.mkfifo(backup_pipe)

    if BACKUP_DEBUG:
        print "Will backup:", files_to_backup

    header_files = prepare_backup_header(backup_tmpdir, passphrase,
                                         compressed=bool(compressed),
                                         encrypted=encrypted,
                                         hmac_algorithm=hmac_algorithm,
                                         crypto_algorithm=crypto_algorithm,
                                         compression_filter=compression_filter)

    # Setup worker to send encrypted data chunks to the backup_target
    def compute_progress(new_size, total_backup_size):
        global blocks_backedup
        blocks_backedup += new_size
        if callable(progress_callback):
            this_progress = blocks_backedup / float(total_backup_size)
            progress_callback(int(round(this_progress * 100, 2)))

    to_send = Queue(10)
    send_proc = SendWorker(to_send, backup_tmpdir, backup_stdout)
    send_proc.start()

    for f in header_files:
        to_send.put(f)

    for filename in files_to_backup:
        if BACKUP_DEBUG:
            print "Backing up", filename

        backup_tempfile = os.path.join(backup_tmpdir,
                                       filename["subdir"],
                                       os.path.basename(filename["path"]))
        if BACKUP_DEBUG:
            print "Using temporary location:", backup_tempfile

        # Ensure the temporary directory exists
        if not os.path.isdir(os.path.dirname(backup_tempfile)):
            os.makedirs(os.path.dirname(backup_tempfile))

        # The first tar cmd can use any complex feature as we want. Files will
        # be verified before untaring this.
        # Prefix the path in archive with filename["subdir"] to have it
        # verified during untar
        tar_cmdline = (["tar", "-Pc", '--sparse',
                       "-f", backup_pipe,
                       '-C', os.path.dirname(filename["path"])] +
                       (['--dereference'] if filename["subdir"] != "dom0-home/"
                       else []) +
                       ['--xform', 's:^%s:%s\\0:' % (
                           os.path.basename(filename["path"]),
                           filename["subdir"]),
                       os.path.basename(filename["path"])
                       ])
        if compressed:
            tar_cmdline.insert(-1,
                               "--use-compress-program=%s" % compression_filter)

        if BACKUP_DEBUG:
            print " ".join(tar_cmdline)

        # Tips: Popen(bufsize=0)
        # Pipe: tar-sparse | encryptor [| hmac] | tar | backup_target
        # Pipe: tar-sparse [| hmac] | tar | backup_target
        tar_sparse = subprocess.Popen(tar_cmdline, stdin=subprocess.PIPE,
                                      stderr=(open(os.devnull, 'w')
                                              if not BACKUP_DEBUG
                                              else None))
        running_backup_operation.processes_to_kill_on_cancel.append(tar_sparse)

        # Wait for compressor (tar) process to finish or for any error of other
        # subprocesses
        i = 0
        run_error = "paused"
        encryptor = None
        if encrypted:
            # Start encrypt
            # If no cipher is provided, the data is forwarded unencrypted !!!
            encryptor = subprocess.Popen(["openssl", "enc",
                                          "-e", "-" + crypto_algorithm,
                                          "-pass", "pass:" + passphrase],
                                         stdin=open(backup_pipe, 'rb'),
                                         stdout=subprocess.PIPE)
            pipe = encryptor.stdout
        else:
            pipe = open(backup_pipe, 'rb')
        while run_error == "paused":

            # Start HMAC
            hmac = subprocess.Popen(["openssl", "dgst",
                                     "-" + hmac_algorithm, "-hmac", passphrase],
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE)

            # Prepare a first chunk
            chunkfile = backup_tempfile + "." + "%03d" % i
            i += 1
            chunkfile_p = open(chunkfile, 'wb')

            common_args = {
                'backup_target': chunkfile_p,
                'total_backup_sz': total_backup_sz,
                'hmac': hmac,
                'vmproc': vmproc,
                'addproc': tar_sparse,
                'progress_callback': compute_progress,
                'size_limit': 100 * 1024 * 1024,
            }
            run_error = wait_backup_feedback(
                in_stream=pipe, streamproc=encryptor,
                **common_args)
            chunkfile_p.close()

            if BACKUP_DEBUG:
                print "Wait_backup_feedback returned:", run_error

            if running_backup_operation.canceled:
                try:
                    tar_sparse.terminate()
                except:
                    pass
                try:
                    hmac.terminate()
                except:
                    pass
                tar_sparse.wait()
                hmac.wait()
                to_send.put("ERROR")
                send_proc.join()
                shutil.rmtree(backup_tmpdir)
                running_backup_operation = None
                raise BackupCanceledError("Backup canceled")
            if run_error and run_error != "size_limit":
                send_proc.terminate()
                if run_error == "VM" and vmproc:
                    raise QubesException(
                        "Failed to write the backup, VM output:\n" +
                        vmproc.stderr.read(MAX_STDERR_BYTES))
                else:
                    raise QubesException("Failed to perform backup: error in " +
                                         run_error)

            # Send the chunk to the backup target
            queue_put_with_check(
                send_proc, vmproc, to_send,
                os.path.relpath(chunkfile, backup_tmpdir))

            # Close HMAC
            hmac.stdin.close()
            hmac.wait()
            if BACKUP_DEBUG:
                print "HMAC proc return code:", hmac.poll()

            # Write HMAC data next to the chunk file
            hmac_data = hmac.stdout.read()
            if BACKUP_DEBUG:
                print "Writing hmac to", chunkfile + ".hmac"
            hmac_file = open(chunkfile + ".hmac", 'w')
            hmac_file.write(hmac_data)
            hmac_file.flush()
            hmac_file.close()

            # Send the HMAC to the backup target
            queue_put_with_check(
                send_proc, vmproc, to_send,
                os.path.relpath(chunkfile, backup_tmpdir) + ".hmac")

            if tar_sparse.poll() is None or run_error == "size_limit":
                run_error = "paused"
            else:
                running_backup_operation.processes_to_kill_on_cancel.remove(
                    tar_sparse)
                if BACKUP_DEBUG:
                    print "Finished tar sparse with exit code", tar_sparse \
                        .poll()
        pipe.close()

    queue_put_with_check(send_proc, vmproc, to_send, "FINISHED")
    send_proc.join()
    shutil.rmtree(backup_tmpdir)

    if running_backup_operation.canceled:
        running_backup_operation = None
        raise BackupCanceledError("Backup canceled")

    running_backup_operation = None

    if send_proc.exitcode != 0:
        raise QubesException(
            "Failed to send backup: error in the sending process")

    if vmproc:
        if BACKUP_DEBUG:
            print "VMProc1 proc return code:", vmproc.poll()
            if tar_sparse is not None:
                print "Sparse1 proc return code:", tar_sparse.poll()
        vmproc.stdin.close()

    # Save date of last backup
    qvm_collection = QubesVmCollection()
    qvm_collection.lock_db_for_writing()
    qvm_collection.load()

    for vm in qvm_collection.values():
        if vm.backup_content:
            vm.backup_timestamp = datetime.datetime.now()

    qvm_collection.save()
    qvm_collection.unlock_db()


'''
' Wait for backup chunk to finish
' - Monitor all the processes (streamproc, hmac, vmproc, addproc) for errors
' - Copy stdout of streamproc to backup_target and hmac stdin if available
' - Compute progress based on total_backup_sz and send progress to
'   progress_callback function
' - Returns if
' -     one of the monitored processes error out (streamproc, hmac, vmproc,
'       addproc), along with the processe that failed
' -     all of the monitored processes except vmproc finished successfully
'       (vmproc termination is controlled by the python script)
' -     streamproc does not delivers any data anymore (return with the error
'       "")
' -     size_limit is provided and is about to be exceeded
'''


def wait_backup_feedback(progress_callback, in_stream, streamproc,
                         backup_target, total_backup_sz, hmac=None, vmproc=None,
                         addproc=None,
                         size_limit=None):
    buffer_size = 409600

    run_error = None
    run_count = 1
    bytes_copied = 0
    while run_count > 0 and run_error is None:

        if size_limit and bytes_copied + buffer_size > size_limit:
            return "size_limit"
        buf = in_stream.read(buffer_size)
        progress_callback(len(buf), total_backup_sz)
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
                    if BACKUP_DEBUG:
                        print vmproc.stdout.read()
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


def verify_hmac(filename, hmacfile, passphrase, algorithm):
    if BACKUP_DEBUG:
        print "Verifying file " + filename

    if hmacfile != filename + ".hmac":
        raise QubesException(
            "ERROR: expected hmac for {}, but got {}".
            format(filename, hmacfile))

    hmac_proc = subprocess.Popen(["openssl", "dgst", "-" + algorithm,
                                  "-hmac", passphrase],
                                 stdin=open(filename, 'rb'),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    hmac_stdout, hmac_stderr = hmac_proc.communicate()

    if len(hmac_stderr) > 0:
        raise QubesException(
            "ERROR: verify file {0}: {1}".format(filename, hmac_stderr))
    else:
        if BACKUP_DEBUG:
            print "Loading hmac for file " + filename
        hmac = load_hmac(open(hmacfile, 'r').read())

        if len(hmac) > 0 and load_hmac(hmac_stdout) == hmac:
            os.unlink(hmacfile)
            if BACKUP_DEBUG:
                print "File verification OK -> Sending file " + filename
            return True
        else:
            raise QubesException(
                "ERROR: invalid hmac for file {0}: {1}. "
                "Is the passphrase correct?".
                format(filename, load_hmac(hmac_stdout)))
    # Not reachable
    return False


class ExtractWorker2(Process):
    def __init__(self, queue, base_dir, passphrase, encrypted, total_size,
                 print_callback, error_callback, progress_callback, vmproc=None,
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
        self.total_size = total_size
        self.blocks_backedup = 0
        self.tar2_process = None
        self.tar2_current_file = None
        self.decompressor_process = None
        self.decryptor_process = None

        self.print_callback = print_callback
        self.error_callback = error_callback
        self.progress_callback = progress_callback

        self.vmproc = vmproc

        self.restore_pipe = os.path.join(self.base_dir, "restore_pipe")
        if BACKUP_DEBUG:
            print "Creating pipe in:", self.restore_pipe
        os.mkfifo(self.restore_pipe)

        self.stderr_encoding = sys.stderr.encoding or 'utf-8'

    def compute_progress(self, new_size, _):
        if self.progress_callback:
            self.blocks_backedup += new_size
            progress = self.blocks_backedup / float(self.total_size)
            progress = int(round(progress * 100, 2))
            self.progress_callback(progress)

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

        if not BACKUP_DEBUG:
            msg_re = re.compile(r".*#[0-9].*restore_pipe")
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
            self.error_callback("ERROR: " + unicode(e))
            raise e, None, exc_traceback

    def __run__(self):
        if BACKUP_DEBUG and callable(self.print_callback):
            self.print_callback("Started sending thread")
            self.print_callback("Moving to dir " + self.base_dir)
        os.chdir(self.base_dir)

        filename = None

        for filename in iter(self.queue.get, None):
            if filename == "FINISHED" or filename == "ERROR":
                break

            if BACKUP_DEBUG and callable(self.print_callback):
                self.print_callback("Extracting file " + filename)

            if filename.endswith('.000'):
                # next file
                if self.tar2_process is not None:
                    if self.tar2_process.wait() != 0:
                        self.collect_tar_output()
                        self.error_callback(
                            "ERROR: unable to extract files for {0}, tar "
                            "output:\n  {1}".
                            format(self.tar2_current_file,
                                   "\n  ".join(self.tar2_stderr)))
                    else:
                        # Finished extracting the tar file
                        self.tar2_process = None
                        self.tar2_current_file = None

                tar2_cmdline = ['tar',
                                '-%sMk%sf' % ("t" if self.verify_only else "x",
                                              "v" if BACKUP_DEBUG else ""),
                                self.restore_pipe,
                                os.path.relpath(filename.rstrip('.000'))]
                if BACKUP_DEBUG and callable(self.print_callback):
                    self.print_callback("Running command " +
                                        unicode(tar2_cmdline))
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
                if not BACKUP_DEBUG:
                    os.remove(filename)
                continue
            else:
                self.collect_tar_output()
                if BACKUP_DEBUG and callable(self.print_callback):
                    self.print_callback("Releasing next chunck")
                self.tar2_process.stdin.write("\n")
                self.tar2_process.stdin.flush()
            self.tar2_current_file = filename

            pipe = open(self.restore_pipe, 'wb')
            common_args = {
                'backup_target': pipe,
                'total_backup_sz': self.total_size,
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
                    progress_callback=self.compute_progress,
                    in_stream=self.decryptor_process.stdout,
                    streamproc=self.decryptor_process,
                    **common_args)
            elif self.compressed:
                self.decompressor_process = subprocess.Popen(
                    ["gzip", "-d"],
                    stdin=open(filename, 'rb'),
                    stdout=subprocess.PIPE)

                run_error = wait_backup_feedback(
                    progress_callback=self.compute_progress,
                    in_stream=self.decompressor_process.stdout,
                    streamproc=self.decompressor_process,
                    **common_args)
            else:
                run_error = wait_backup_feedback(
                    progress_callback=self.compute_progress,
                    in_stream=open(filename, "rb"), streamproc=None,
                    **common_args)

            try:
                pipe.close()
            except IOError as e:
                if e.errno == errno.EPIPE:
                    if BACKUP_DEBUG:
                        self.error_callback(
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
                self.error_callback("Error while processing '%s': %s " %
                                    (self.tar2_current_file, details))

            # Delete the file as we don't need it anymore
            if BACKUP_DEBUG and callable(self.print_callback):
                self.print_callback("Removing file " + filename)
            os.remove(filename)

        os.unlink(self.restore_pipe)

        if self.tar2_process is not None:
            if filename == "ERROR":
                self.tar2_process.terminate()
                self.tar2_process.wait()
            elif self.tar2_process.wait() != 0:
                self.collect_tar_output()
                raise QubesException(
                    "unable to extract files for {0}.{1} Tar command "
                    "output: %s".
                    format(self.tar2_current_file,
                           (" Perhaps the backup is encrypted?"
                            if not self.encrypted else "",
                            "\n".join(self.tar2_stderr))))
            else:
                # Finished extracting the tar file
                self.tar2_process = None

        if BACKUP_DEBUG and callable(self.print_callback):
            self.print_callback("Finished extracting thread")


class ExtractWorker3(ExtractWorker2):
    def __init__(self, queue, base_dir, passphrase, encrypted, total_size,
                 print_callback, error_callback, progress_callback, vmproc=None,
                 compressed=False, crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM,
                 compression_filter=None, verify_only=False):
        super(ExtractWorker3, self).__init__(queue, base_dir, passphrase,
                                             encrypted, total_size,
                                             print_callback, error_callback,
                                             progress_callback, vmproc,
                                             compressed, crypto_algorithm,
                                             verify_only)
        self.compression_filter = compression_filter
        os.unlink(self.restore_pipe)

    def __run__(self):
        if BACKUP_DEBUG and callable(self.print_callback):
            self.print_callback("Started sending thread")
            self.print_callback("Moving to dir " + self.base_dir)
        os.chdir(self.base_dir)

        filename = None

        input_pipe = None
        for filename in iter(self.queue.get, None):
            if filename == "FINISHED" or filename == "ERROR":
                break

            if BACKUP_DEBUG and callable(self.print_callback):
                self.print_callback("Extracting file " + filename)

            if filename.endswith('.000'):
                # next file
                if self.tar2_process is not None:
                    input_pipe.close()
                    if self.tar2_process.wait() != 0:
                        self.collect_tar_output()
                        self.error_callback(
                            "ERROR: unable to extract files for {0}, tar "
                            "output:\n  {1}".
                            format(self.tar2_current_file,
                                   "\n  ".join(self.tar2_stderr)))
                    else:
                        # Finished extracting the tar file
                        self.tar2_process = None
                        self.tar2_current_file = None

                tar2_cmdline = ['tar',
                                '-%sk%s' % ("t" if self.verify_only else "x",
                                            "v" if BACKUP_DEBUG else ""),
                                os.path.relpath(filename.rstrip('.000'))]
                if self.compressed:
                    if self.compression_filter:
                        tar2_cmdline.insert(-1,
                                            "--use-compress-program=%s" %
                                            self.compression_filter)
                    else:
                        tar2_cmdline.insert(-1, "--use-compress-program=%s" %
                                            DEFAULT_COMPRESSION_FILTER)

                if BACKUP_DEBUG and callable(self.print_callback):
                    self.print_callback("Running command " +
                                        unicode(tar2_cmdline))
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
                if not BACKUP_DEBUG:
                    os.remove(filename)
                continue
            else:
                if BACKUP_DEBUG and callable(self.print_callback):
                    self.print_callback("Releasing next chunck")
            self.tar2_current_file = filename

            common_args = {
                'backup_target': input_pipe,
                'total_backup_sz': self.total_size,
                'hmac': None,
                'vmproc': self.vmproc,
                'addproc': self.tar2_process
            }

            run_error = wait_backup_feedback(
                progress_callback=self.compute_progress,
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
                self.error_callback("Error while processing '%s': %s " %
                                    (self.tar2_current_file, details))

            # Delete the file as we don't need it anymore
            if BACKUP_DEBUG and callable(self.print_callback):
                self.print_callback("Removing file " + filename)
            os.remove(filename)

        if self.tar2_process is not None:
            input_pipe.close()
            if filename == "ERROR":
                if self.decryptor_process:
                    self.decryptor_process.terminate()
                    self.decryptor_process.wait()
                    self.decryptor_process = None
                self.tar2_process.terminate()
                self.tar2_process.wait()
            elif self.tar2_process.wait() != 0:
                self.collect_tar_output()
                raise QubesException(
                    "unable to extract files for {0}.{1} Tar command "
                    "output: %s".
                    format(self.tar2_current_file,
                           (" Perhaps the backup is encrypted?"
                            if not self.encrypted else "",
                            "\n".join(self.tar2_stderr))))
            else:
                # Finished extracting the tar file
                self.tar2_process = None

        if BACKUP_DEBUG and callable(self.print_callback):
            self.print_callback("Finished extracting thread")


def get_supported_hmac_algo(hmac_algorithm):
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


def parse_backup_header(filename):
    header_data = {}
    with open(filename, 'r') as f:
        for line in f.readlines():
            if line.count('=') != 1:
                raise QubesException("Invalid backup header (line %s)" % line)
            (key, value) = line.strip().split('=')
            if not any([key == getattr(BackupHeader, attr) for attr in dir(
                    BackupHeader)]):
                # Ignoring unknown option
                continue
            if key in BackupHeader.bool_options:
                value = value.lower() in ["1", "true", "yes"]
            elif key in BackupHeader.int_options:
                value = int(value)
            header_data[key] = value
    return header_data


def restore_vm_dirs(backup_source, restore_tmpdir, passphrase, vms_dirs, vms,
                    vms_size, print_callback=None, error_callback=None,
                    progress_callback=None, encrypted=False, appvm=None,
                    compressed=False, hmac_algorithm=DEFAULT_HMAC_ALGORITHM,
                    crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM,
                    verify_only=False,
                    format_version=CURRENT_BACKUP_FORMAT_VERSION,
                    compression_filter=None):
    global running_backup_operation

    if callable(print_callback):
        if BACKUP_DEBUG:
            print_callback("Working in temporary dir:" + restore_tmpdir)
        print_callback(
            "Extracting data: " + size_to_human(vms_size) + " to restore")

    passphrase = passphrase.encode('utf-8')
    header_data = None
    vmproc = None
    if appvm is not None:
        # Prepare the backup target (Qubes service call)
        backup_target = "QUBESRPC qubes.Restore dom0"

        # If APPVM, STDOUT is a PIPE
        vmproc = appvm.run(command=backup_target, passio_popen=True,
                           passio_stderr=True)
        vmproc.stdin.write((
            backup_source.replace("\r", "").replace("\n", "") + "\n").encode('utf-8'))

        # Send to tar2qfile the VMs that should be extracted
        vmproc.stdin.write(" ".join(vms_dirs) + "\n")
        if running_backup_operation:
            running_backup_operation.processes_to_kill_on_cancel.append(vmproc)

        backup_stdin = vmproc.stdout
        tar1_command = ['/usr/libexec/qubes/qfile-dom0-unpacker',
                        str(os.getuid()), restore_tmpdir, '-v']
    else:
        backup_stdin = open(backup_source, 'rb')

        tar1_command = ['tar',
                        '-ixvf', backup_source,
                        '-C', restore_tmpdir] + vms_dirs

    tar1_env = os.environ.copy()
    # TODO: add some safety margin?
    tar1_env['UPDATES_MAX_BYTES'] = str(vms_size)
    # Restoring only header
    if vms_dirs and vms_dirs[0] == HEADER_FILENAME:
        # backup-header, backup-header.hmac, qubes-xml.000, qubes-xml.000.hmac
        tar1_env['UPDATES_MAX_FILES'] = '4'
    else:
        # Currently each VM consists of at most 7 archives (count
        # file_to_backup calls in backup_prepare()), but add some safety
        # margin for further extensions. Each archive is divided into 100MB
        # chunks. Additionally each file have own hmac file. So assume upper
        # limit as 2*(10*COUNT_OF_VMS+TOTAL_SIZE/100MB)
        tar1_env['UPDATES_MAX_FILES'] = str(2 * (10 * len(vms_dirs) +
                                                 int(vms_size /
                                                     (100 * 1024 * 1024))))
    if BACKUP_DEBUG and callable(print_callback):
        print_callback("Run command" + unicode(tar1_command))
    command = subprocess.Popen(
        tar1_command,
        stdin=backup_stdin,
        stdout=vmproc.stdin if vmproc else subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=tar1_env)
    if running_backup_operation:
        running_backup_operation.processes_to_kill_on_cancel.append(command)

    # qfile-dom0-unpacker output filelist on stderr (and have stdout connected
    # to the VM), while tar output filelist on stdout
    if appvm:
        filelist_pipe = command.stderr
        # let qfile-dom0-unpacker hold the only open FD to the write end of
        # pipe, otherwise qrexec-client will not receive EOF when
        # qfile-dom0-unpacker terminates
        vmproc.stdin.close()
    else:
        filelist_pipe = command.stdout

    expect_tar_error = False

    to_extract = Queue()
    nextfile = None

    # If want to analyze backup header, do it now
    if vms_dirs and vms_dirs[0] == HEADER_FILENAME:
        filename = filelist_pipe.readline().strip()
        hmacfile = filelist_pipe.readline().strip()
        if not appvm:
            nextfile = filelist_pipe.readline().strip()

        if BACKUP_DEBUG and callable(print_callback):
            print_callback("Got backup header and hmac: %s, %s" % (filename,
                                                                   hmacfile))

        if not filename or filename == "EOF" or \
                not hmacfile or hmacfile == "EOF":
            if appvm:
                vmproc.wait()
                proc_error_msg = vmproc.stderr.read(MAX_STDERR_BYTES)
            else:
                command.wait()
                proc_error_msg = command.stderr.read(MAX_STDERR_BYTES)
            raise QubesException("Premature end of archive while receiving "
                                 "backup header. Process output:\n" +
                                 proc_error_msg)
        filename = os.path.join(restore_tmpdir, filename)
        hmacfile = os.path.join(restore_tmpdir, hmacfile)
        file_ok = False
        for hmac_algo in get_supported_hmac_algo(hmac_algorithm):
            try:
                if verify_hmac(filename, hmacfile, passphrase, hmac_algo):
                    file_ok = True
                    hmac_algorithm = hmac_algo
                    break
            except QubesException:
                # Ignore exception here, try the next algo
                pass
        if not file_ok:
            raise QubesException("Corrupted backup header (hmac verification "
                                 "failed). Is the password correct?")
        if os.path.basename(filename) == HEADER_FILENAME:
            header_data = parse_backup_header(filename)
            if BackupHeader.version in header_data:
                format_version = header_data[BackupHeader.version]
            if BackupHeader.crypto_algorithm in header_data:
                crypto_algorithm = header_data[BackupHeader.crypto_algorithm]
            if BackupHeader.hmac_algorithm in header_data:
                hmac_algorithm = header_data[BackupHeader.hmac_algorithm]
            if BackupHeader.compressed in header_data:
                compressed = header_data[BackupHeader.compressed]
            if BackupHeader.encrypted in header_data:
                encrypted = header_data[BackupHeader.encrypted]
            if BackupHeader.compression_filter in header_data:
                compression_filter = header_data[
                    BackupHeader.compression_filter]
            os.unlink(filename)
        else:
            # if no header found, create one with guessed HMAC algo
            header_data = {BackupHeader.hmac_algorithm: hmac_algorithm}
            # If this isn't backup header, pass it to ExtractWorker
            to_extract.put(filename)
            # when tar do not find expected file in archive, it exit with
            # code 2. This will happen because we've requested backup-header
            # file, but the archive do not contain it. Ignore this particular
            # error.
            if not appvm:
                expect_tar_error = True

    # Setup worker to extract encrypted data chunks to the restore dirs
    # Create the process here to pass it options extracted from backup header
    extractor_params = {
        'queue': to_extract,
        'base_dir': restore_tmpdir,
        'passphrase': passphrase,
        'encrypted': encrypted,
        'compressed': compressed,
        'crypto_algorithm': crypto_algorithm,
        'verify_only': verify_only,
        'total_size': vms_size,
        'print_callback': print_callback,
        'error_callback': error_callback,
        'progress_callback': progress_callback,
    }
    if format_version == 2:
        extract_proc = ExtractWorker2(**extractor_params)
    elif format_version == 3:
        extractor_params['compression_filter'] = compression_filter
        extract_proc = ExtractWorker3(**extractor_params)
    else:
        raise NotImplemented(
            "Backup format version %d not supported" % format_version)
    extract_proc.start()

    try:
        filename = None
        while True:
            if running_backup_operation and running_backup_operation.canceled:
                break
            if not extract_proc.is_alive():
                command.terminate()
                command.wait()
                expect_tar_error = True
                if vmproc:
                    vmproc.terminate()
                    vmproc.wait()
                    vmproc = None
                break
            if nextfile is not None:
                filename = nextfile
            else:
                filename = filelist_pipe.readline().strip()

            if BACKUP_DEBUG and callable(print_callback):
                print_callback("Getting new file:" + filename)

            if not filename or filename == "EOF":
                break

            hmacfile = filelist_pipe.readline().strip()

            if running_backup_operation and running_backup_operation.canceled:
                break
            # if reading archive directly with tar, wait for next filename -
            # tar prints filename before processing it, so wait for
            # the next one to be sure that whole file was extracted
            if not appvm:
                nextfile = filelist_pipe.readline().strip()

            if BACKUP_DEBUG and callable(print_callback):
                print_callback("Getting hmac:" + hmacfile)
            if not hmacfile or hmacfile == "EOF":
                # Premature end of archive, either of tar1_command or
                # vmproc exited with error
                break

            if not any(map(lambda x: filename.startswith(x), vms_dirs)):
                if BACKUP_DEBUG and callable(print_callback):
                    print_callback("Ignoring VM not selected for restore")
                os.unlink(os.path.join(restore_tmpdir, filename))
                os.unlink(os.path.join(restore_tmpdir, hmacfile))
                continue

            if verify_hmac(os.path.join(restore_tmpdir, filename),
                           os.path.join(restore_tmpdir, hmacfile),
                           passphrase, hmac_algorithm):
                to_extract.put(os.path.join(restore_tmpdir, filename))

        if running_backup_operation and running_backup_operation.canceled:
            raise BackupCanceledError("Restore canceled",
                                      tmpdir=restore_tmpdir)

        if command.wait() != 0 and not expect_tar_error:
            raise QubesException(
                "unable to read the qubes backup file {0} ({1}). "
                "Is it really a backup?".format(backup_source, command.wait()))
        if vmproc:
            if vmproc.wait() != 0:
                raise QubesException(
                    "unable to read the qubes backup {0} "
                    "because of a VM error: {1}".format(
                        backup_source, vmproc.stderr.read(MAX_STDERR_BYTES)))

        if filename and filename != "EOF":
            raise QubesException(
                "Premature end of archive, the last file was %s" % filename)
    except:
        to_extract.put("ERROR")
        extract_proc.join()
        raise
    else:
        to_extract.put("FINISHED")

    if BACKUP_DEBUG and callable(print_callback):
        print_callback("Waiting for the extraction process to finish...")
    extract_proc.join()
    if BACKUP_DEBUG and callable(print_callback):
        print_callback("Extraction process finished with code:" +
                       str(extract_proc.exitcode))
    if extract_proc.exitcode != 0:
        raise QubesException(
            "unable to extract the qubes backup. "
            "Check extracting process errors.")

    return header_data


def backup_restore_set_defaults(options):
    if 'use-default-netvm' not in options:
        options['use-default-netvm'] = False
    if 'use-none-netvm' not in options:
        options['use-none-netvm'] = False
    if 'use-default-template' not in options:
        options['use-default-template'] = False
    if 'dom0-home' not in options:
        options['dom0-home'] = True
    if 'replace-template' not in options:
        options['replace-template'] = []
    if 'ignore-username-mismatch' not in options:
        options['ignore-username-mismatch'] = False
    if 'verify-only' not in options:
        options['verify-only'] = False
    if 'rename-conflicting' not in options:
        options['rename-conflicting'] = False
    if 'paranoid-mode' not in options:
        options['paranoid-mode'] = False

    return options


def load_hmac(hmac):
    hmac = hmac.strip().split("=")
    if len(hmac) > 1:
        hmac = hmac[1].strip()
    else:
        raise QubesException("ERROR: invalid hmac file content")

    return hmac


def backup_detect_format_version(backup_location):
    if os.path.exists(os.path.join(backup_location, 'qubes.xml')):
        return 1
    else:
        # this could mean also 3, but not distinguishable until backup header
        # is read
        return 2


def backup_restore_header(source, passphrase,
                          print_callback=print_stdout,
                          error_callback=print_stderr,
                          encrypted=False, appvm=None, compressed=False,
                          format_version=None,
                          hmac_algorithm=DEFAULT_HMAC_ALGORITHM,
                          crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM):
    global running_backup_operation
    running_backup_operation = None

    restore_tmpdir = tempfile.mkdtemp(prefix="/var/tmp/restore_")

    if format_version is None:
        format_version = backup_detect_format_version(source)

    if format_version == 1:
        return restore_tmpdir, os.path.join(source, 'qubes.xml'), None

    # tar2qfile matches only beginnings, while tar full path
    if appvm:
        extract_filter = [HEADER_FILENAME, 'qubes.xml.000']
    else:
        extract_filter = [HEADER_FILENAME, HEADER_FILENAME + '.hmac',
                          'qubes.xml.000', 'qubes.xml.000.hmac']

    header_data = restore_vm_dirs(source,
                                  restore_tmpdir,
                                  passphrase=passphrase,
                                  vms_dirs=extract_filter,
                                  vms=None,
                                  vms_size=HEADER_QUBES_XML_MAX_SIZE,
                                  format_version=format_version,
                                  hmac_algorithm=hmac_algorithm,
                                  crypto_algorithm=crypto_algorithm,
                                  print_callback=print_callback,
                                  error_callback=error_callback,
                                  progress_callback=None,
                                  encrypted=encrypted,
                                  compressed=compressed,
                                  appvm=appvm)

    return (restore_tmpdir, os.path.join(restore_tmpdir, "qubes.xml"),
            header_data)

def generate_new_name_for_conflicting_vm(orig_name, host_collection,
                                         restore_info):
    number = 1
    if len(orig_name) > 29:
        orig_name = orig_name[0:29]
    new_name = orig_name
    while (new_name in restore_info.keys() or
           new_name in map(lambda x: x.get('rename_to', None),
                           restore_info.values()) or
           host_collection.get_vm_by_name(new_name)):
        new_name = str('{}{}'.format(orig_name, number))
        number += 1
        if number == 100:
            # give up
            return None
    return new_name

def restore_info_verify(restore_info, host_collection):
    options = restore_info['$OPTIONS$']
    for vm in restore_info.keys():
        if vm in ['$OPTIONS$', 'dom0']:
            continue

        vm_info = restore_info[vm]

        vm_info.pop('excluded', None)
        if 'exclude' in options.keys():
            if vm in options['exclude']:
                vm_info['excluded'] = True

        vm_info.pop('already-exists', None)
        if not options['verify-only'] and \
                host_collection.get_vm_by_name(vm) is not None:
            if options['rename-conflicting']:
                new_name = generate_new_name_for_conflicting_vm(
                    vm, host_collection, restore_info
                )
                if new_name is not None:
                    vm_info['rename-to'] = new_name
                else:
                    vm_info['already-exists'] = True
            else:
                vm_info['already-exists'] = True

        # check template
        vm_info.pop('missing-template', None)
        if vm_info['template']:
            template_name = vm_info['template']
            host_template = host_collection.get_vm_by_name(template_name)
            if not host_template or not host_template.is_template():
                # Maybe the (custom) template is in the backup?
                if not (template_name in restore_info.keys() and
                        restore_info[template_name]['vm'].is_template()):
                    if options['use-default-template']:
                        if 'orig-template' not in vm_info.keys():
                            vm_info['orig-template'] = template_name
                        vm_info['template'] = host_collection \
                            .get_default_template().name
                    else:
                        vm_info['missing-template'] = True

        # check netvm
        vm_info.pop('missing-netvm', None)
        if vm_info['vm'].uses_default_netvm:
            default_netvm = host_collection.get_default_netvm()
            vm_info['netvm'] = default_netvm.name if \
                default_netvm else None
        elif vm_info['netvm']:
            netvm_name = vm_info['netvm']

            netvm_on_host = host_collection.get_vm_by_name(netvm_name)

            # No netvm on the host?
            if not ((netvm_on_host is not None) and netvm_on_host.is_netvm()):

                # Maybe the (custom) netvm is in the backup?
                if not (netvm_name in restore_info.keys() and
                        restore_info[netvm_name]['vm'].is_netvm()):
                    if options['use-default-netvm']:
                        default_netvm = host_collection.get_default_netvm()
                        vm_info['netvm'] = default_netvm.name if \
                            default_netvm else None
                        vm_info['vm'].uses_default_netvm = True
                    elif options['use-none-netvm']:
                        vm_info['netvm'] = None
                    else:
                        vm_info['missing-netvm'] = True

        # check dispvm-netvm
        vm_info.pop('missing-dispvm_netvm', None)
        if not vm_info['vm'].uses_default_dispvm_netvm and \
                vm_info['dispvm_netvm']:
            dispvm_netvm_name = vm_info['dispvm_netvm']

            dispvm_netvm_on_host = host_collection.get_vm_by_name(dispvm_netvm_name)

            # No dispvm_netvm on the host?
            if not ((dispvm_netvm_on_host is not None) and dispvm_netvm_on_host.is_netvm()):

                # Maybe the (custom) dispvm_netvm is in the backup?
                if not (dispvm_netvm_name in restore_info.keys() and
                        restore_info[dispvm_netvm_name]['vm'].is_netvm()):
                    if options['use-default-netvm']:
                        vm_info['dispvm_netvm'] = vm_info['netvm']
                        vm_info['vm'].uses_default_dispvm_netvm = True
                    elif options['use-none-netvm']:
                        vm_info['dispvm_netvm'] = None
                    else:
                        vm_info['missing-dispvm_netvm'] = True

        vm_info['good-to-go'] = not any([(prop in vm_info.keys()) for
                                         prop in ['missing-netvm',
                                                  'missing-dispvm_netvm',
                                                  'missing-template',
                                                  'already-exists',
                                                  'excluded']])

    # update references to renamed VMs:
    for vm in restore_info.keys():
        if vm in ['$OPTIONS$', 'dom0']:
            continue
        vm_info = restore_info[vm]
        template_name = vm_info['template']
        if (template_name in restore_info and
                restore_info[template_name]['good-to-go'] and
                'rename-to' in restore_info[template_name]):
            vm_info['template'] = restore_info[template_name]['rename-to']
        netvm_name = vm_info['netvm']
        if (netvm_name in restore_info and
                restore_info[netvm_name]['good-to-go'] and
                'rename-to' in restore_info[netvm_name]):
            vm_info['netvm'] = restore_info[netvm_name]['rename-to']

    return restore_info


def backup_restore_prepare(backup_location, passphrase, options=None,
                           host_collection=None, encrypted=False, appvm=None,
                           compressed=False, print_callback=print_stdout,
                           error_callback=print_stderr,
                           format_version=None,
                           hmac_algorithm=DEFAULT_HMAC_ALGORITHM,
                           crypto_algorithm=DEFAULT_CRYPTO_ALGORITHM):
    if options is None:
        options = {}
    # Defaults
    backup_restore_set_defaults(options)
    # Options introduced in backup format 3+, which always have a header,
    # so no need for fallback in function parameter
    compression_filter = DEFAULT_COMPRESSION_FILTER

    # Private functions begin
    def is_vm_included_in_backup_v1(backup_dir, check_vm):
        if check_vm.qid == 0:
            return os.path.exists(os.path.join(backup_dir, 'dom0-home'))

        # DisposableVM
        if check_vm.dir_path is None:
            return False

        backup_vm_dir_path = check_vm.dir_path.replace(
            system_path["qubes_base_dir"], backup_dir)

        if os.path.exists(backup_vm_dir_path):
            return True
        else:
            return False

    def is_vm_included_in_backup_v2(_, check_vm):
        if check_vm.backup_content:
            return True
        else:
            return False

    def find_template_name(template, replaces):
        rx_replace = re.compile("(.*):(.*)")
        for r in replaces:
            m = rx_replace.match(r)
            if m.group(1) == template:
                return m.group(2)

        return template

    # Private functions end

    # Format versions:
    # 1 - Qubes R1, Qubes R2 beta1, beta2
    #  2 - Qubes R2 beta3+

    if format_version is None:
        format_version = backup_detect_format_version(backup_location)

    if format_version == 1:
        is_vm_included_in_backup = is_vm_included_in_backup_v1
    elif format_version in [2, 3]:
        is_vm_included_in_backup = is_vm_included_in_backup_v2
        if not appvm:
            if not os.path.isfile(backup_location):
                raise QubesException("Invalid backup location (not a file or "
                                     "directory with qubes.xml)"
                                     ": %s" % unicode(backup_location))
    else:
        raise QubesException(
            "Unknown backup format version: %s" % str(format_version))

    (restore_tmpdir, qubes_xml, header_data) = backup_restore_header(
        backup_location,
        passphrase,
        encrypted=encrypted,
        appvm=appvm,
        compressed=compressed,
        hmac_algorithm=hmac_algorithm,
        crypto_algorithm=crypto_algorithm,
        print_callback=print_callback,
        error_callback=error_callback,
        format_version=format_version)

    if not callable(print_callback):
        print_callback = lambda x: None

    if header_data:
        if BackupHeader.version in header_data:
            format_version = header_data[BackupHeader.version]
        if BackupHeader.crypto_algorithm in header_data:
            crypto_algorithm = header_data[BackupHeader.crypto_algorithm]
        if BackupHeader.hmac_algorithm in header_data:
            hmac_algorithm = header_data[BackupHeader.hmac_algorithm]
        if BackupHeader.compressed in header_data:
            compressed = header_data[BackupHeader.compressed]
        if BackupHeader.encrypted in header_data:
            encrypted = header_data[BackupHeader.encrypted]
        if BackupHeader.compression_filter in header_data:
            compression_filter = header_data[BackupHeader.compression_filter]

    if options['paranoid-mode']:
        if format_version != 3:
            raise QubesException(
                'paranoid-mode: Rejecting old backup format')
        if compressed:
            raise QubesException(
                'paranoid-mode: Compressed backups rejected')
        if crypto_algorithm != DEFAULT_CRYPTO_ALGORITHM:
            raise QubesException(
                'paranoid-mode: Only {} encryption allowed'.format(
                    DEFAULT_CRYPTO_ALGORITHM))
        if options['dom0-home']:
            print_callback('paranoid-mode: not restoring dom0 home')
            options['dom0-home'] = False

    if BACKUP_DEBUG:
        print "Loading file", qubes_xml
    if options['paranoid-mode']:
        backup_collection = SafeQubesVmCollection(store_filename=qubes_xml)
        backup_collection.lock_db_for_reading()
        backup_collection.load()
    else:
        backup_collection = QubesVmCollection(store_filename=qubes_xml)
        backup_collection.lock_db_for_reading()
        backup_collection.load()

    if host_collection is None:
        host_collection = QubesVmCollection()
        host_collection.lock_db_for_reading()
        host_collection.load()
        host_collection.unlock_db()

    backup_vms_list = [vm for vm in backup_collection.values()]
    vms_to_restore = {}

    # ... and the actual data
    for vm in backup_vms_list:
        if vm.qid == 0:
            # Handle dom0 as special case later
            continue
        if is_vm_included_in_backup(backup_location, vm):
            if BACKUP_DEBUG:
                print vm.name, "is included in backup"

            vms_to_restore[vm.name] = {}
            vms_to_restore[vm.name]['vm'] = vm

            if vm.template is None:
                vms_to_restore[vm.name]['template'] = None
            else:
                templatevm_name = find_template_name(vm.template.name, options[
                    'replace-template'])
                vms_to_restore[vm.name]['template'] = templatevm_name

            if vm.netvm is None:
                vms_to_restore[vm.name]['netvm'] = None
            else:
                netvm_name = vm.netvm.name
                vms_to_restore[vm.name]['netvm'] = netvm_name
                # Set to None to not confuse QubesVm object from backup
                # collection with host collection (further in clone_attrs). Set
                # directly _netvm to suppress setter action, especially
                # modifying firewall
                vm._netvm = None

            if vm.dispvm_netvm is None:
                vms_to_restore[vm.name]['dispvm_netvm'] = None
            else:
                netvm_name = vm.dispvm_netvm.name
                vms_to_restore[vm.name]['dispvm_netvm'] = netvm_name
                vm.dispvm_netvm = None

    # Store restore parameters
    options['location'] = backup_location
    options['restore_tmpdir'] = restore_tmpdir
    options['passphrase'] = passphrase
    options['encrypted'] = encrypted
    options['compressed'] = compressed
    options['compression_filter'] = compression_filter
    options['hmac_algorithm'] = hmac_algorithm
    options['crypto_algorithm'] = crypto_algorithm
    options['appvm'] = appvm
    options['format_version'] = format_version
    vms_to_restore['$OPTIONS$'] = options

    vms_to_restore = restore_info_verify(vms_to_restore, host_collection)

    # ...and dom0 home
    if options['dom0-home'] and \
            is_vm_included_in_backup(backup_location, backup_collection[0]):
        vm = backup_collection[0]
        vms_to_restore['dom0'] = {}
        if format_version == 1:
            vms_to_restore['dom0']['subdir'] = \
                os.listdir(os.path.join(backup_location, 'dom0-home'))[0]
            vms_to_restore['dom0']['size'] = 0  # unknown
        else:
            vms_to_restore['dom0']['subdir'] = vm.backup_path
            vms_to_restore['dom0']['size'] = vm.backup_size
        local_user = grp.getgrnam('qubes').gr_mem[0]

        dom0_home = vms_to_restore['dom0']['subdir']

        vms_to_restore['dom0']['username'] = os.path.basename(dom0_home)
        if vms_to_restore['dom0']['username'] != local_user:
            vms_to_restore['dom0']['username-mismatch'] = True
            if options['ignore-username-mismatch']:
                vms_to_restore['dom0']['ignore-username-mismatch'] = True
            else:
                vms_to_restore['dom0']['good-to-go'] = False

        if 'good-to-go' not in vms_to_restore['dom0']:
            vms_to_restore['dom0']['good-to-go'] = True

    # Not needed - all the data stored in vms_to_restore
    if format_version >= 2:
        os.unlink(qubes_xml)
    return vms_to_restore


def backup_restore_print_summary(restore_info, print_callback=print_stdout):
    fields = {
        "qid": {"func": "vm.qid"},

        "name": {"func": "('[' if vm.is_template() else '')\
                 + ('{' if vm.is_netvm() else '')\
                 + vm.name \
                 + (']' if vm.is_template() else '')\
                 + ('}' if vm.is_netvm() else '')"},

        "type": {"func": "'Tpl' if vm.is_template() else \
                 'HVM' if vm.type == 'HVM' else \
                 vm.type.replace('VM','')"},

        "updbl": {"func": "'Yes' if vm.updateable else ''"},

        "template": {"func": "'n/a' if vm.is_template() or vm.template is None else\
                     vm_info['template']"},

        "netvm": {"func": "'n/a' if vm.is_netvm() and not vm.is_proxyvm() else\
                  ('*' if vm.uses_default_netvm else '') +\
                    vm_info['netvm'] if vm_info['netvm'] is not None else '-'"},

        "label": {"func": "vm.label.name"},
    }

    fields_to_display = ["name", "type", "template", "updbl", "netvm", "label"]

    # First calculate the maximum width of each field we want to display
    total_width = 0
    for f in fields_to_display:
        fields[f]["max_width"] = len(f)
        for vm_info in restore_info.values():
            if 'vm' in vm_info.keys():
                # noinspection PyUnusedLocal
                vm = vm_info['vm']
                l = len(unicode(eval(fields[f]["func"])))
                if l > fields[f]["max_width"]:
                    fields[f]["max_width"] = l
        total_width += fields[f]["max_width"]

    print_callback("")
    print_callback("The following VMs are included in the backup:")
    print_callback("")

    # Display the header
    s = ""
    for f in fields_to_display:
        fmt = "{{0:-^{0}}}-+".format(fields[f]["max_width"] + 1)
        s += fmt.format('-')
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt = "{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
        s += fmt.format(f)
    print_callback(s)
    s = ""
    for f in fields_to_display:
        fmt = "{{0:-^{0}}}-+".format(fields[f]["max_width"] + 1)
        s += fmt.format('-')
    print_callback(s)

    for vm_info in restore_info.values():
        # Skip non-VM here
        if 'vm' not in vm_info:
            continue
        # noinspection PyUnusedLocal
        vm = vm_info['vm']
        s = ""
        for f in fields_to_display:
            fmt = "{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
            s += fmt.format(eval(fields[f]["func"]))

        if 'excluded' in vm_info and vm_info['excluded']:
            s += " <-- Excluded from restore"
        elif 'already-exists' in vm_info:
            s += " <-- A VM with the same name already exists on the host!"
        elif 'missing-template' in vm_info:
            s += " <-- No matching template on the host or in the backup found!"
        elif 'missing-netvm' in vm_info:
            s += " <-- No matching netvm on the host or in the backup found!"
        else:
            if 'orig-template' in vm_info:
                s += " <-- Original template was '%s'" % (vm_info['orig-template'])
            if 'rename-to' in vm_info:
                s += " <-- Will be renamed to '%s'" % vm_info['rename-to']

        print_callback(s)

    if 'dom0' in restore_info.keys():
        s = ""
        for f in fields_to_display:
            fmt = "{{0:>{0}}} |".format(fields[f]["max_width"] + 1)
            if f == "name":
                s += fmt.format("Dom0")
            elif f == "type":
                s += fmt.format("Home")
            else:
                s += fmt.format("")
        if 'username-mismatch' in restore_info['dom0']:
            s += " <-- username in backup and dom0 mismatch"
        if 'ignore-username-mismatch' in restore_info['dom0']:
            s += " (ignored)"

        print_callback(s)


def backup_restore_do(restore_info,
                      host_collection=None, print_callback=print_stdout,
                      error_callback=print_stderr, progress_callback=None,
                      ):
    global running_backup_operation

    # Private functions begin
    def restore_vm_dir_v1(backup_dir, src_dir, dst_dir):

        backup_src_dir = src_dir.replace(system_path["qubes_base_dir"],
                                         backup_dir)

        # We prefer to use Linux's cp, because it nicely handles sparse files
        cp_retcode = subprocess.call(["cp", "-rp", "--reflink=auto", backup_src_dir, dst_dir])
        if cp_retcode != 0:
            raise QubesException(
                "*** Error while copying file {0} to {1}".format(backup_src_dir,
                                                                 dst_dir))

    # Private functions end

    options = restore_info['$OPTIONS$']
    backup_location = options['location']
    restore_tmpdir = options['restore_tmpdir']
    passphrase = options['passphrase']
    encrypted = options['encrypted']
    compressed = options['compressed']
    compression_filter = options['compression_filter']
    hmac_algorithm = options['hmac_algorithm']
    crypto_algorithm = options['crypto_algorithm']
    verify_only = options['verify-only']
    appvm = options['appvm']
    format_version = options['format_version']

    if not callable(print_callback):
        print_callback = lambda x: None

    if format_version is None:
        format_version = backup_detect_format_version(backup_location)

    lock_obtained = False
    if host_collection is None:
        host_collection = QubesVmCollection()
        host_collection.lock_db_for_writing()
        host_collection.load()
        lock_obtained = True

    # Perform VM restoration in backup order
    vms_dirs = []
    vms_size = 0
    vms = {}
    for vm_info in restore_info.values():
        if 'vm' not in vm_info:
            continue
        if not vm_info['good-to-go']:
            continue
        vm = vm_info['vm']
        if format_version >= 2:
            vms_size += vm.backup_size
            vms_dirs.append(vm.backup_path)
        vms[vm.name] = vm

    running_backup_operation = BackupOperationInfo()

    if format_version >= 2:
        if 'dom0' in restore_info.keys() and restore_info['dom0']['good-to-go']:
            vms_dirs.append(os.path.dirname(restore_info['dom0']['subdir']))
            vms_size += restore_info['dom0']['size']

        try:
            restore_vm_dirs(backup_location,
                            restore_tmpdir,
                            passphrase=passphrase,
                            vms_dirs=vms_dirs,
                            vms=vms,
                            vms_size=vms_size,
                            format_version=format_version,
                            hmac_algorithm=hmac_algorithm,
                            crypto_algorithm=crypto_algorithm,
                            verify_only=verify_only,
                            print_callback=print_callback,
                            error_callback=error_callback,
                            progress_callback=progress_callback,
                            encrypted=encrypted,
                            compressed=compressed,
                            compression_filter=compression_filter,
                            appvm=appvm)
        except QubesException:
            if verify_only:
                raise
            else:
                if callable(print_callback):
                    print_callback(
                        "Some errors occurred during data extraction, "
                        "continuing anyway to restore at least some "
                        "VMs")
    else:
        if verify_only:
            if callable(print_callback):
                print_callback("WARNING: Backup verification not supported for "
                               "this backup format.")

    if verify_only:
        shutil.rmtree(restore_tmpdir)
        return

    # Add VM in right order
    for (vm_class_name, vm_class) in sorted(QubesVmClasses.items(),
                                            key=lambda _x: _x[1].load_order):
        if running_backup_operation.canceled:
            break
        for vm in vms.values():
            if running_backup_operation.canceled:
                # only break the loop to save qubes.xml with already restored
                # VMs
                break
            if not vm.__class__ == vm_class:
                continue
            if callable(print_callback):
                print_callback("-> Restoring {type} {0}...".
                               format(vm.name, type=vm_class_name))
            retcode = subprocess.call(
                ["mkdir", "-p", os.path.dirname(vm.dir_path)])
            if retcode != 0:
                error_callback("*** Cannot create directory: {0}?!".format(
                    vm.dir_path))
                error_callback("Skipping...")
                continue

            template = None
            if vm.template is not None:
                template_name = restore_info[vm.name]['template']
                template = host_collection.get_vm_by_name(template_name)

            new_vm = None
            vm_name = vm.name
            if 'rename-to' in restore_info[vm.name]:
                vm_name = restore_info[vm.name]['rename-to']

            try:
                new_vm = host_collection.add_new_vm(vm_class_name, name=vm_name,
                                                    template=template,
                                                    installed_by_rpm=False)
                if os.path.exists(new_vm.dir_path):
                    move_to_path = tempfile.mkdtemp('', os.path.basename(
                        new_vm.dir_path), os.path.dirname(new_vm.dir_path))
                    try:
                        os.rename(new_vm.dir_path, move_to_path)
                        error_callback(
                            "*** Directory {} already exists! It has "
                            "been moved to {}".format(new_vm.dir_path,
                                                      move_to_path))
                    except OSError:
                        error_callback(
                            "*** Directory {} already exists and "
                            "cannot be moved!".format(new_vm.dir_path))
                        error_callback("Skipping...")
                        continue

                if format_version == 1:
                    restore_vm_dir_v1(backup_location,
                                      vm.dir_path,
                                      os.path.dirname(new_vm.dir_path))
                elif format_version >= 2:
                    if options['paranoid-mode']:
                        # cleanup/exclude things; do it this late to be sure
                        # that no tricks on tar archive level would
                        # (re-)create those files/directories
                        for filedir in ['apps', 'apps.templates',
                                'apps.tempicons', 'apps.icons', 'firewall.xml']:
                            path = os.path.join(restore_tmpdir,
                                vm.backup_path, filedir)
                            if os.path.exists(path):
                                print_callback('paranoid-mode: VM {}: skipping '
                                               '{}'.format(vm.name, filedir))
                                shutil.rmtree(path)

                    shutil.move(os.path.join(restore_tmpdir, vm.backup_path),
                                new_vm.dir_path)

                new_vm.verify_files()
            except Exception as err:
                error_callback("ERROR: {0}".format(err))
                error_callback("*** Skipping VM: {0}".format(vm.name))
                if new_vm:
                    host_collection.pop(new_vm.qid)
                continue

            # FIXME: cannot check for 'kernel' property, because it is always
            # defined - accessing it touches non-existent '_kernel'
            if not isinstance(vm, QubesVmClasses['QubesHVm']):
                # TODO: add a setting for this?
                if vm.kernel and vm.kernel not in \
                        os.listdir(system_path['qubes_kernels_base_dir']):
                    if callable(print_callback):
                        print_callback("WARNING: Kernel %s not installed, "
                                       "using default one" % vm.kernel)
                    vm.uses_default_kernel = True
                    vm.kernel = host_collection.get_default_kernel()
            try:
                new_vm.clone_attrs(vm)
            except Exception as err:
                error_callback("ERROR: {0}".format(err))
                error_callback("*** Some VM property will not be restored")

            try:
                for service, value in vm.services.items():
                    new_vm.services[service] = value
            except Exception as err:
                error_callback("ERROR: {0}".format(err))
                error_callback("*** Some VM property will not be restored")

            try:
                new_vm.appmenus_create(verbose=callable(print_callback))
            except Exception as err:
                error_callback("ERROR during appmenu restore: {0}".format(err))
                error_callback(
                    "*** VM '{0}' will not have appmenus".format(vm.name))

    # Set network dependencies - only non-default netvm setting
    for vm in vms.values():
        vm_name = vm.name
        if 'rename-to' in restore_info[vm.name]:
            vm_name = restore_info[vm.name]['rename-to']
        host_vm = host_collection.get_vm_by_name(vm_name)

        if host_vm is None:
            # Failed/skipped VM
            continue

        if not vm.uses_default_netvm:
            if restore_info[vm.name]['netvm'] is not None:
                host_vm.netvm = host_collection.get_vm_by_name(
                    restore_info[vm.name]['netvm'])
            else:
                host_vm.netvm = None

        if not vm.uses_default_dispvm_netvm:
            if restore_info[vm.name]['dispvm_netvm'] is not None:
                host_vm.dispvm_netvm = host_collection.get_vm_by_name(
                    restore_info[vm.name]['dispvm_netvm'])
            else:
                host_vm.dispvm_netvm = None

    host_collection.save()
    if lock_obtained:
        host_collection.unlock_db()

    if running_backup_operation.canceled:
        if format_version >= 2:
            raise BackupCanceledError("Restore canceled",
                                      tmpdir=restore_tmpdir)
        else:
            raise BackupCanceledError("Restore canceled")

    # ... and dom0 home as last step
    if 'dom0' in restore_info.keys() and restore_info['dom0']['good-to-go']:
        backup_path = restore_info['dom0']['subdir']
        local_user = grp.getgrnam('qubes').gr_mem[0]
        home_dir = pwd.getpwnam(local_user).pw_dir
        if format_version == 1:
            backup_dom0_home_dir = os.path.join(backup_location, backup_path)
        else:
            backup_dom0_home_dir = os.path.join(restore_tmpdir, backup_path)
        restore_home_backupdir = "home-pre-restore-{0}".format(
            time.strftime("%Y-%m-%d-%H%M%S"))

        if callable(print_callback):
            print_callback(
                "-> Restoring home of user '{0}'...".format(local_user))
            print_callback(
                "--> Existing files/dirs backed up in '{0}' dir".format(
                    restore_home_backupdir))
        os.mkdir(home_dir + '/' + restore_home_backupdir)
        for f in os.listdir(backup_dom0_home_dir):
            home_file = home_dir + '/' + f
            if os.path.exists(home_file):
                os.rename(home_file,
                          home_dir + '/' + restore_home_backupdir + '/' + f)
            if format_version == 1:
                subprocess.call(
                    ["cp", "-nrp", "--reflink=auto", backup_dom0_home_dir + '/' + f, home_file])
            elif format_version >= 2:
                shutil.move(backup_dom0_home_dir + '/' + f, home_file)
        retcode = subprocess.call(['sudo', 'chown', '-R', local_user, home_dir])
        if retcode != 0:
            error_callback("*** Error while setting home directory owner")

    if callable(print_callback):
        print_callback("-> Done. Please install updates for all the restored "
                       "templates.")

    shutil.rmtree(restore_tmpdir)

# vim:sw=4:et:
