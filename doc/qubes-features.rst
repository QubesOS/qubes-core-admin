:py:mod:`qubes.features` - Qubes VM features, services
======================================================

Features are generic mechanism for storing key-value pairs attached to a
VM. The primary use case for them is data storage for extensions (you can think
of them as more flexible properties, defined by extensions), but some are also
used in the qubes core itself. There is no definite list of supported features,
each extension can set their own and there is no requirement of registration,
but :program:`qvm-features` man page contains well known ones.
In addition, there is a mechanism for VM request setting a feature. This is
useful for extensions to discover if its VM part is present. 

Features can have three distinct values: no value (not present in mapping,
which is closest thing to :py:obj:`None`), empty string (which is
interpreted as :py:obj:`False`) and non-empty string, which is
:py:obj:`True`. Anything assigned to the mapping is coerced to strings,
however if you assign instances of :py:class:`bool`, they are converted as
described above. Be aware that assigning the number `0` (which is considered
false in Python) will result in string `'0'`, which is considered true.

:py:class:`qubes.features.Features` inherits from :py:class:`dict`, so provide
all the standard functions to get, list and set values.  Additionally provide
helper functions to check if given feature is set on the VM and default to the
value on the VM's template or netvm. This is useful for features which nature is
inherited from other VMs, like "is package X is installed" or "is VM behind
a VPN".

Example usage of features in extension:

.. code-block:: python

   import qubes.exc
   import qubes.ext

   class ExampleExtension(qubes.ext.Extension):
      @qubes.ext.handler('domain-pre-start')
      def on_domain_start(self, vm, event, **kwargs):
         if vm.features.get('do-not-start', False):
            raise qubes.exc.QubesVMError(vm,
               'Start prohibited because of do-not-start feature')

         if vm.features.check_with_template('something-installed', False):
            # do something

The above extension does two things:

 - prevent starting a qube with ``do-not-start`` feature set
 - do something when ``something-installed`` feature is set on the qube, or its
   template


qvm-features-request, qubes.PostInstall service
------------------------------------------------

When some package in the VM want to request feature to be set (aka advertise
support for it), it should place a shell script in ``/etc/qubes/post-install.d``.
This script should call :program:`qvm-features-request` with ``FEATURE=VALUE``
pair(s) as arguments to request those features. It is recommended to use very
simple values here (for example ``1``). The script should be named in form
``XX-package-name.sh`` where ``XX`` is two-digits number below 90 and
``package-name`` is unique name specific to this package (preferably actual
package name). The script needs executable bit set.

``qubes.PostInstall`` service will call all those scripts after any package
installation and also after initial template installation.
This way package have a chance to report to dom0 if any feature is
added/removed.

The features flow to dom0 according to the diagram below. Important part is that
qubes core :py:class:`qubes.ext.Extension` is responsible for handling such
request in ``features-request`` event handler. If no extension handles given
feature request, it will be ignored. The extension should carefuly validate
requested features (ignoring those not recognized - may be for another
extension) and only then set appropriate value on VM object
(:py:attr:`qubes.vm.BaseVM.features`). It is recommended to make the
verification code as bulletproof  as possible (for example allow only specific
simple values, instead of complex structures), because feature requests come
from untrusted sources. The features actually set on the VM in some cases may
not be necessary those requested. Similar for values.

.. graphviz::

   digraph {

      "qubes.PostInstall";
      "/etc/qubes/post-install.d/ scripts";
      "qvm-features-request";
      "qubes.FeaturesRequest";
      "qubes core extensions";
      "VM features";

      "qubes.PostInstall" -> "/etc/qubes/post-install.d/ scripts";
      "/etc/qubes/post-install.d/ scripts" -> "qvm-features-request" 
         [xlabel="each script calls"];
      "qvm-features-request" -> "qubes.FeaturesRequest" 
         [xlabel="last script call the service to dom0"];
      "qubes.FeaturesRequest" -> "qubes core extensions" 
         [xlabel="features-request event"];
      "qubes core extensions" -> "VM features" 
         [xlabel="verification"];

   }

Example ``/etc/qubes/post-install.d/20-example.sh`` file:

.. code-block:: shell

   #!/bin/sh

   qvm-features-request example-feature=1

Example extension handling the above:

.. code-block:: python

   import qubes.ext

   class ExampleExtension(qubes.ext.Extension):
      # the last argument must be named untrusted_features
      @qubes.ext.handler('features-request')
      def on_features_request(self, vm, event, untrusted_features):
         # don't allow TemplateBasedVMs to request the feature - should be
         # requested by the template instead
         if hasattr(vm, 'template'):
            return

         untrusted_value = untrusted_features.get('example-feature', None)
         # check if feature is advertised and verify its value
         if untrusted_value != '1':
            return
         value = untrusted_value

         # and finally set the value
         vm.features['example-feature'] = value

Services
---------

`Qubes services <https://www.qubes-os.org/doc/qubes-service/>`_ are implemented
as features with ``service.`` prefix. The
:py:class:`qubes.ext.services.ServicesExtension` enumerate all the features
in form of ``service.<service-name>`` prefix and write them to QubesDB as
``/qubes-service/<service-name>`` and value either ``0`` or ``1``.
VM startup scripts list those entries for for each with value of ``1``, create
``/var/run/qubes-service/<service-name>`` file. Then, it can be conveniently
used by other scripts to check whether dom0 wishes service to be enabled or
disabled.

VM package can advertise what services are supported. For that, it needs to
request ``supported-service.<service-name>`` feature with value ``1`` according
to description above. The :py:class:`qubes.ext.services.ServicesExtension` will
handle such request and set this feature on VM object. ``supported-service.``
features that stop being advertised with ``qvm-features-request`` call are
removed. This way, it's enough to remove the file from
``/etc/qubes/post-install.d`` (for example by uninstalling package providing
the service) to tell dom0 the service is no longer supported. Services
advertised by TemplateBasedVMs are currently ignored (related
``supported-service.`` features are not set), but retrieving them may be added
in the future. Applications checking for specific service support should use
``vm.features.check_with_template('supported-service.<service-name>', False)``
call on desired VM object. When enumerating all supported services, application
should consider both the vm and its template (if any).

Various tools will use this information to discover if given service is
supported. The API does not enforce service being first advertised before being
enabled (means: there can be service which is enabled, but without matching
``supported-service.`` feature). The list of well known services is in
:program:`qvm-service` man page.

Example ``/etc/qubes/post-install.d/20-my-service.sh``:

.. code-block:: shell

   #!/bin/sh

   qvm-features-request supported-service.my-service=1

Services and features can be then inspected from dom0 using
:program:`qvm-features` tool, for example:

.. code-block:: shell

   $ qvm-features my-qube
   supported-service.my-service  1

Module contents
---------------

.. automodule:: qubes.features
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et

