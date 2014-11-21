.. program:: qvm-add-appvm

==========================================================================
:program:`qvm-add-appvm` -- Add an already installed appvm to the Qubes DB
==========================================================================

.. warning::
   Normally you would not need this command, and you would use qvm-create instead!

Synopsis
========
| qvm-add-appvm [options] <appvm-name> <vm-template-name>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --path=DIR_PATH, -p DIR_PATH

    Specify path to the template directory

.. option:: --conf=CONF_FILE, -c CONF_FILE

    Specify the Xen VM .conf file to use (relative to the template dir path)

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
