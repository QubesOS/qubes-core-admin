:py:mod:`qubes.events` -- Qubes events
======================================

Some objects in qubes (most notably domains) emit events. You may hook them and
execute your code when particular event is fired. Events in qubes are added
class-wide -- it is not possible to add event handler to one instance only, you
have to add handler for whole class.


Firing events
-------------

Events are fired by calling :py:meth:`qubes.events.Emitter.fire_event`. The
first argument is event name (a string). You can fire any event you wish, the
names are not checked in any way, however each class' documentation tells what
standard events will be fired on it. The rest of arguments are dependent on the
particular event in question -- they are passed as-is to handlers.

Event handlers are fired in reverse method resolution order, that is, first for
parent class and then for it's child. For each class, first are called handlers
defined in it's source, then handlers from extensions and last the callers added
manually.

There is second method, :py:meth:`qubes.events.Emitter.fire_event_pre`, which
fires events in reverse order. It is suitable for events fired before some
action is performed. You may at your own responsibility raise exceptions from
such events to try to prevent such action.

Event handlers may return a value. Those values are aggregated and returned
to the caller as a list of those values. The order of this list is undefined.
:py:obj:`None` values are omitted.

Handling events
---------------

There are several ways to handle events. In all cases you supply a callable
(most likely function or method) that will be called when someone fires the
event. The first argument passed to the callable will be the object instance on
which the event was fired and the second one is the event name. The rest are
passed from :py:meth:`qubes.events.Emitter.fire_event` as described previously.
One callable can handle more than one event.

The easiest way to hook an event is to invoke
:py:meth:`qubes.events.Emitter.add_handler` classmethod.

.. code-block:: python

   import qubes.events

   class MyClass(qubes.events.Emitter):
       pass

   def event_handler(subject, event):
       if event == 'event1':
           print('Got event 1')
       elif event == 'event2':
           print('Got event 2')

   MyClass.add_handler('event1', event_handler)
   MyClass.add_handler('event2', event_handler)

   o = MyClass()
   o.fire_event('event1')

If you wish to define handler in the class definition, the best way is to use
:py:func:`qubes.events.handler` decorator.

.. code-block:: python

   import qubes.events

   class MyClass(qubes.events.Emitter):
       @qubes.events.handler('event1', 'event2')
       def event_handler(self, event):
           if event == 'event1':
               print('Got event 1')
           elif event == 'event2':
               print('Got event 2')

   o = MyClass()
   o.fire_event('event1')

.. TODO: extensions


Handling events with variable signature
---------------------------------------

Some events are specified with variable signature (i.e. they may have different
number of arguments on each call to handlers). You can write handlers just like
every other python function with variable signature.

.. code-block:: python

   import qubes

   def on_property_change(subject, event, name, newvalue, oldvalue=None):
       if oldvalue is None:
           print('Property {} initialised to {!r}'.format(name, newvalue))
       else:
           print('Property {} changed {!r} -> {!r}'.format(name, oldvalue, newvalue))

   qubes.Qubes.add_handler('property-set:default_netvm')

If you expect :py:obj:`None` to be a reasonable value of the property, you have
a problem. One way to solve it is to invent your very own, magic
:py:class:`object` instance.

.. code-block:: python

   import qubes

   MAGIC_NO_VALUE = object()
   def on_property_change(subject, event, name, newvalue, oldvalue=MAGIC_NO_VALUE):
       if oldvalue is MAGIC_NO_VALUE:
           print('Property {} initialised to {!r}'.format(name, newvalue))
       else:
           print('Property {} changed {!r} -> {!r}'.format(name, oldvalue, newvalue))

   qubes.Qubes.add_handler('property-set:default_netvm')

There is no possible way of collision other than intentionally passing this very
object (not even passing similar featureless ``object()``), because ``is``
python syntax checks object's :py:meth:`id`\ entity, which will be different for
each :py:class:`object` instance.


Module contents
---------------

.. automodule:: qubes.events
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et
