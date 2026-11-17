:py:mod:`qubes.api` -- API
=================================

API sanitization is very important to maintain the AdminVM and everything it
controls, secure.

**Simple rules**:

* Handle exceptions gracefully. Unhandled exceptions have the traceback only in
  the AdminVM, not allowing clients to know what happened. More information
  about exceptions can be found at :py:class:`qubes.exc`.
* Failure to serve a request must raise exceptions that can be understood by the
  client. Each stage below allows a different class of exception to be shown.
  Be careful to not reveal more information than what the client is allowed to
  know at each stage.

**Stages**:

.# Sanitize data

   * Must never print, log or store untrusted data. Be careful when throwing an
     exception.
   * Qrexec sanitizes the argument, but if you will use the argument to
     something that you know has an even stricter syntax, it must be sanitized
     also.
   * The payload is received raw, in bytes. It must always be sanitized before
     being passed to functions that expect it to be already trusted.
   * When sanitizing data, if it may reveal information from the system, such as
     object existence, then, throw :py:class:`qubes.exc.PermissionDenied` to
     avoid leaking object existence or delay reveal till after
     `admin-permission`.

.# Fire permission event

   * Must only pass sanitized information.
   * The most commonly used is
     :py:meth:`qubes.api.AbstractQubesAPI.fire_event_for_permission`, which
     fires event `admin-permission` directly, used by
     :py:class:`qubes.api.admin.AdminExtension`. For more complex cases,
     involving global information such as fetching objects from different
     destinations, :py:meth:`qubes.api.AbstractQubesAPI.fire_event_for_filter`
     is more appropriate, as it fires `admin-permission` for each operation
     required.

.# Action

   * The client is fully authorized at this stage, it passed Qrexec policy
     evaluation and Qubesd `admin-permission`. The server may be aware that some
     resource could not be served before the `admin-permisison`, but it was not
     allowed to reveal at that stage, now it can reveal what and why it failed.
     A custom exception derived from :py:class:`qubes.exc.QubesException` can be
     used to allow the client to handle it gracefully.
   * Act.

.. code-block:: python

   @qubes.api.method(
        "dest.feat.Set",      # RPC name
        wants_arg=True,       # Argument must be provided
        wants_payload=None,   # Payload can be provided
        dest_adminvm=False,   # Target must not be AdminVM
        scope="global",       # Applies to the whole system
        read=True,            # Will read system information
        write=True,           # Will write information to the system
    )
    async def dest_feat_set(self, untrusted_payload):
        """
        Set destination feature

        name:  self.arg
        value: untrusted_payload
        """
        # Qrexec sanitizes self.arg, but our feature name can only be made of
        # letters. The client should have know to not make such a request in the
        # first case, therefore it throws qubes.exc.ProtocolError.
        allowed_chars = string.ascii_letters
        self.enforce(
            all(c in allowed_chars for c in self.arg),
            reason="Feature name must be in safe set: " + allowed_chars,
        )

        # Payload is in bytes and we receive it without being sanitized
        # previously. We only want to allow values to be in ASCII.
        try:
            untrusted_value = untrusted_payload.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise qubes.exc.ProtocolError("Value contains non-ASCII characters")
        # Delete untrusted payload prevent using it.
        del untrusted_payload

        # Second sanitization of the value
        if re.match(r"\A[\x20-\x7E]*\Z", untrusted_value) is None:
            raise qubes.exc.ProtocolError(
                f"{self.arg} value contains illegal characters"
            )
        # Delete untrusted value prevent using it.
        value = untrusted_value
        del untrusted_value

        # In this case, we just want to allow setting value to features that are
        # already set. We want to hide hide "absent" feature from "prohibited"
        # feature (see "admin-permission" below), therefore, it throws
        # qubes.exc.PermissionDenied.
        self.enforce_arg(
            wants=self.dest.features.keys(),
            short_reason="destination features",
        )

        # Event "admin-permission" is used to prohibit certain API calls from
        # qubesd when qrexec cannot possibly be that restrictive, as it doesn't
        # have full knowledge of the system nor the policy is expressive enough.
        # Only trusted data should be passed to this method.
        # Throws qubes.exc.PermissionDenied if call is prohibited.
        self.fire_event_for_permission(value=value)

        # The server is in a bad mood today. Let the user know we will not
        # serve them today.
        if True:
            raise qubes.exc.QubesException(
                "Not in a good mood today, feature '%r' doesn't look nice" %
                self.arg
            )

        # All validation has passed, we can return the requested data.
        self.dest.features[self.arg] = value
        self.app.save()

Inheritance diagram
-------------------

.. inheritance-diagram:: qubes.api

Module contents
---------------

.. autoclass:: qubes.api.admin
.. autoclass:: qubes.api.internal
.. autoclass:: qubes.api.misc

.. vim: ts=3 sw=3 et tw=80
