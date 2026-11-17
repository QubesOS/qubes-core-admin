:py:mod:`qubes.exc` -- Exceptions
=================================

As most of the modern programming languages, Python has exceptions, which can be
thrown (``raise``\ d) when something goes bad. What exactly means "bad" depends
on several circumstances.

One of those circumstances is who exactly is to blame: programmer or user? Some
errors are commited by programmer and will most probably result it program
failure. But most errors are caused by the user, notably by specifying invalid
commands or data input. Those errors *should not* result in failure, but fault
and be handled gracefuly. One more time, what "gracefuly" means depends on
specific program and its interface (for example GUI programs should most likely
display some admonition, but will not crash).

In Qubes we have special exception class, :py:class:`qubes.exc.QubesException`,
which is dedicated to handling user-caused problems. Programmer errors should
not result in raising QubesException, but it should instead result in one of the
standard Python exception. QubesExceptions should have a nice message that can
be shown to the user. On the other hand, some children classes of QubesException
also inherit from children of :py:class:`StandardException` to allow uniform
``except`` clauses.

Often the error relates to some domain, because we expect it to be in certain
state, but it is not. For example to start a machine, it should be halted. For
that we have the children of the :py:class:`qubes.exc.QubesVMError` class. They
all take the domain in question as their first argument and an (optional)
message as the second. If not specified, there is stock message which is
generally informative enough.


On writing error messages
-------------------------

As a general rule, error messages should be short but precise. They should not
blame user for error, but the user should know, what had been done wrong and
what to do next.

If possible, write the message that is stating the fact, for example "Domain is
not running" instead of "You forgot to start the domain" (you fool!). Avoid
commanding user, like "Start the domain first" (user is not a function you can
call for effect). Instead consider writing in negative form, implying expected
state: "Domain is not running" instead of "Domain is paused" (yeah, what's wrong
with that?).

Also avoid implying the personhood of the computer, including addressing user in
second person. For example, write "Sending message failed" instead of "I failed
to send the message".


Inheritance diagram
-------------------

.. inheritance-diagram:: qubes.exc

Module contents
---------------

.. automodule:: qubes.exc
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et tw=80
