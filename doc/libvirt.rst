Custom libvirt config
=====================

Starting from Qubes OS R4.0, libvirt domain config is generated using jinja
templates. Those templates can be overridden by the user in a couple of ways.
A basic knowledge of jinja template language and libvirt xml spec is needed.

.. seealso::

   https://libvirt.org/formatdomain.html
      Format of the domain XML in libvirt.

   http://jinja.pocoo.org/docs/dev/templates/
      Template format documentation.

File paths
----------

In order of increasing precedence: the main template, from which the config is
generated is :file:`/usr/share/qubes/templates/libvirt/xen.xml`).
The distributor may put a file at
:file:`/usr/share/qubes/templates/libvirt/xen-dist.xml`) to override this file.
User may put a file at either
:file:`/etc/qubes/templates/libvirt/xen-user.xml` or
:file:`/etc/qubes/templates/libvirt/xen/by-name/<name>.xml`, where ``<name>`` is
full name of the domain. Wildcards are not supported but symlinks are.

Jinja has a concept of template names, which basically is the path below some
load point, which in Qubes' case is :file:`/etc/qubes/templates` and
:file:`/usr/share/qubes/templates`. Thus names of those templates are
respectively ``'libvirt/xen.xml'``, ``'libvirt/xen-dist.xml'``,
``'libvirt/xen-user.xml'`` and ``'libvirt/xen/by-name/<name>.xml'``.
This will be important later.

.. note::

   Those who know jinja python API will know that the abovementioned locations
   aren't the only possibilities. Yes, it's a lie, but a justified one.

What to put in the template
---------------------------

In principle the user may put anything in the template and there is no attempt
to constrain the user from doing stupid things. One obvious thing is to copy the
original config file and make changes.

.. code-block:: jinja

   <domain type="xen">
       <name>{{ vm.name }}</name>
       ...

The better way is to inherit from the original template and override any number
of blocks. This is the point when we need the name of the original template.

.. code-block:: jinja

   {% extends 'libvirt/xen.xml' %}
   {% block devices %}
       {{ super() }}
       <serial type='pty'>
           <target port='0'/>
       </serial>
   {% endblock %}

``{% extends %}`` specifies which template we inherit from. Then you may put any
block by putting new content inside ``{% block %}{% endblock %}``.
``{{ super() }}`` is substituted with original content of the block as specified
in the parent template. Untouched blocks remain as they were.

The example above adds serial device.

Template API
------------

.. warning::

   This API is provisional and subject to change at the minor releases until
   further notice. No backwards compatibility is promised.

Globals
```````
vm
   the domain object (instance of subclass of
   :py:class:`qubes.vm.qubesvm.QubesVM`)

Filters
```````

No custom filters at the moment.

Blocks in the default template
``````````````````````````````
basic
   Contains ``<name>``, ``<uuid>``, ``<memory>``, ``<currentMemory>`` and
   ``<vcpu>`` nodes.

cpu
   ``<cpu>`` node.

os
   Contents of ``<os>`` node.

features
   Contents of ``<features>`` node.

clock
   Contains the ``<clock>`` node.

on
   Contains ``<on_*>`` nodes.

devices
   Contents of ``<devices>`` node.


.. vim: ts=3 sts=3 sw=3 et
