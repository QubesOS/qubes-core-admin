.. program:: qvm-backup

:program:`qvm-backup` -- None
=============================

Synopsis
--------

:command:`qvm-backup` skel-manpage.py [-h] [--verbose] [--quiet] [--force-root] [--exclude EXCLUDE_LIST] [--dest-vm *APPVM*] [--encrypt] [--no-encrypt] [--passphrase-file PASS_FILE] [--enc-algo CRYPTO_ALGORITHM] [--hmac-algo HMAC_ALGORITHM] [--compress] [--compress-filter COMPRESS_FILTER] [--tmpdir *TMPDIR*] backup_location [vms [vms ...]]

Options
-------

.. option:: --help, -h

   show this help message and exit

.. option:: --verbose, -v

   increase verbosity

.. option:: --quiet, -q

   decrease verbosity

.. option:: --force-root

   force to run as root

.. option:: --exclude, -x

   Exclude the specified VM from the backup (may be repeated)

.. option:: --dest-vm, -d

   Specify the destination VM to which the backup will be sent (implies -e)

.. option:: --encrypt, -e

   Encrypt the backup

.. option:: --no-encrypt

   Skip encryption even if sending the backup to a VM

.. option:: --passphrase-file, -p

   Read passphrase from a file, or use '-' to read from stdin

.. option:: --enc-algo, -E

   Specify a non-default encryption algorithm. For a list of supported algorithms, execute 'openssl list-cipher-algorithms' (implies -e)

.. option:: --hmac-algo, -H

   Specify a non-default HMAC algorithm. For a list of supported algorithms, execute 'openssl list-message-digest-algorithms'

.. option:: --compress, -z

   Compress the backup

.. option:: --compress-filter, -Z

   Specify a non-default compression filter program (default: gzip)

.. option:: --tmpdir

   Specify a temporary directory (if you have at least 1GB free RAM in dom0, use of /tmp is advised) (default: /var/tmp)

Arguments
---------

The first positional parameter is the backup location (directory path, or
command to pipe backup to). After that you may specify the qubes you'd like to
backup. If not specified, all qubes with `include_in_backups` property set are
included.

Authors
-------

| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
| Wojtek Porczyk <woju at invisiblethingslab dot com>

.. vim: ts=3 sw=3 et tw=80
