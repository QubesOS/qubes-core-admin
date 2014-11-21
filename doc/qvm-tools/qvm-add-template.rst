.. program:: qvm-add-template

=================================================================================
:program:`qvm-add-template` -- Adds an already installed template to the Qubes DB
=================================================================================

Synopsis
========
| qvm-add-template [options] <vm-template-name>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --path=DIR_PATH, -p DIR_PATH

    Specify path to the template directory

.. option:: --conf=CONF_FILE, -c CONF_FILE

    Specify the Xen VM .conf file to use(relative to the template dir path)

.. option:: --rpm

    Template files have been installed by RPM

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
