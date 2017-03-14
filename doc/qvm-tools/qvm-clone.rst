=========
qvm-clone
=========

NAME
====
qvm-clone - clones an existing VM by copying all its disk files

SYNOPSIS
========
| qvm-clone [options] <src-name> <new-name>

OPTIONS
=======
-h, --help
    Show this help message and exit
-q, --quiet
    Be quiet           
-p DIR_PATH, --path=DIR_PATH
    Specify path to the template directory
--force-root
    Force to run, even with root privileges
-P, --pool
    Specify in to which storage pool to clone

AUTHORS
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>

