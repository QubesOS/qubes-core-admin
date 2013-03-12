=================
qubes-dom0-update
=================

NAME
====
qubes-dom0-update - update software in dom0

:Date:   2012-04-13

SYNOPSIS
========
| qubes-dom0-update [--clean] [--check-only] [--gui] [<pkg list>]

OPTIONS
=======
--clean
    Clean yum cache before doing anything
--check-only
    Only check for updates (no install)
--gui
    Use gpk-update-viewer for update selection

<pkg list>
    Download (and install if run by root) new packages in dom0 instead of updating

AUTHORS
=======
| Joanna Rutkowska <joanna at invisiblethingslab dot com>
| Rafal Wojtczuk <rafal at invisiblethingslab dot com>
| Marek Marczykowski <marmarek at invisiblethingslab dot com>
