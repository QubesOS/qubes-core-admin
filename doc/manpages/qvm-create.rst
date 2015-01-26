.. program:: qvm-create

=========================================
:program:`qvm-create` -- Creates a new VM
=========================================

Synopsis
========
:command:`qvm-create` [*options*] <*vm-name*>

Options
=======

.. option:: --help, -h

    Show this help message and exit

.. option:: --template=TEMPLATE, -t TEMPLATE

    Specify the TemplateVM to use

.. option:: --label=LABEL, -l LABEL

    Specify the label to use for the new VM (e.g. red, yellow, green, ...)

.. option:: --proxy, -p

    Create ProxyVM

.. option:: --net, -n

    Create NetVM

.. option:: --hvm, -H

    Create HVM (standalone, unless :option:`--template` option used)

.. option:: --hvm-template

    Create HVM template

.. option:: --root-move-from=ROOT_MOVE, -R ROOT_MOVE

    Use provided root.img instead of default/empty one
    (file will be *moved*)

.. option:: --root-copy-from=ROOT_COPY, -r ROOT_COPY

    Use provided root.img instead of default/empty one
    (file will be *copied*)

.. option:: --standalone, -s

    Create standalone VM --- independent of template

.. option:: --mem=MEM, -m MEM

    Initial memory size (in MB)

.. option:: --vcpus=VCPUS, -c VCPUS

    VCPUs count

.. option:: --internal, -i

    Create VM for internal use only (hidden in qubes-manager, no appmenus)

.. option:: --force-root

    Force to run, even with root privileges

.. option:: --quiet, -q

    Be quiet

Authors
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
