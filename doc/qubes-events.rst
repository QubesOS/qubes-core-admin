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
standard events will be fired on it. When firing an event, caller may specify
some optional keyword arguments. Those are dependent on the particular event in
question -- they are passed as-is to handlers.

Event handlers are fired in reverse method resolution order, that is, first for
parent class and then for it's child. For each class, first are called handlers
defined in it's source, then handlers from extensions and last the callers added
manually.

The :py:meth:`qubes.events.Emitter.fire_event` method have keyword argument
`pre_event`, which fires events in reverse order. It is suitable for events
fired before some action is performed. You may at your own responsibility raise
exceptions from such events to try to prevent such action.

Events handlers may yield values. Those values are aggregated and returned
to the caller as a list of those values. See below for details.

Handling events
---------------

There are several ways to handle events. In all cases you supply a callable
(most likely function or method) that will be called when someone fires the
event. The first argument passed to the callable will be the object instance on
which the event was fired and the second one is the event name. The rest are
passed from :py:meth:`qubes.events.Emitter.fire_event` as described previously.
One callable can handle more than one event.

The easiest way to hook an event is to use
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
   o.events_enabled = True
   o.fire_event('event1')

Note that your handler will be called for all instances of this class.

.. TODO: extensions
.. TODO: add/remove_handler
.. TODO: wildcards (property-set:*)


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

   app = qubes.Qubes()
   app.add_handler('property-set:default_netvm')

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

   app = qubes.Qubes()
   app.add_handler('property-set:default_netvm')

There is no possible way of collision other than intentionally passing this very
object (not even passing similar featureless ``object()``), because ``is``
python syntax checks object's :py:meth:`id`\ entity, which will be different for
each :py:class:`object` instance.


Returning values from events
----------------------------

Some events may be called to collect values from the handlers. For example the
event ``is-fully-usable`` allows plugins to report a domain as not fully usable.
Such handlers, instead of returning :py:obj:`None` (which is the default when
the function does not include ``return`` statement), should return an iterable
or itself be a generator. Those values are aggregated from all handlers and
returned to the caller as list. The order of this list is undefined.

.. code-block:: python

   import qubes.events

   class MyClass(qubes.events.Emitter):
       @qubes.events.handler('event1')
       def event1_handler1(self, event):
           # do not return anything, equivalent to "return" and "return None"
           pass

       @qubes.events.handler('event1')
       def event1_handler2(self, event):
           yield 'aqq'
           yield 'zxc'

       @qubes.events.handler('event1')
       def event1_handler3(self, event):
           return ('123', '456')

   o = MyClass()
   o.events_enabled = True

   # returns ['aqq', 'zxc', '123', '456'], possibly not in order
   effect = o.fire_event('event1')


Asynchronous event handling
---------------------------

Event handlers can be defined as coroutine. This way they can execute long
running actions without blocking the whole qubesd process. To define
asynchronous event handler, annotate a coroutine (a function defined with
`async def`, or decorated with :py:func:`asyncio.coroutine`) with
:py:func:`qubes.events.handler` decorator. By definition, order of
such handlers is undefined.

Asynchronous events can be fired using
:py:meth:`qubes.events.Emitter.fire_event_async` method. It will handle both
synchronous and asynchronous handlers. It's an error to register asynchronous
handler (a coroutine) for synchronous event (the one fired with
:py:meth:`qubes.events.Emitter.fire_event`) - it will result in
:py:exc:`RuntimeError` exception.

.. code-block:: python

   import asyncio
   import qubes.events

   class MyClass(qubes.events.Emitter):
       @qubes.events.handler('event1', 'event2')
       @asyncio.coroutine
       def event_handler(self, event):
           if event == 'event1':
               print('Got event 1, starting long running action')
               yield from asyncio.sleep(10)
               print('Done')

   o = MyClass()
   o.events_enabled = True
   loop = asyncio.get_event_loop()
   loop.run_until_complete(o.fire_event_async('event1'))

Asynchronous event handlers can also return value - but only a collection, not
yield individual values (because of python limitation):

.. code-block:: python

   import asyncio
   import qubes.events

   class MyClass(qubes.events.Emitter):
       @qubes.events.handler('event1')
       @asyncio.coroutine
       def event_handler(self, event):
            print('Got event, starting long running action')
            yield from asyncio.sleep(10)
            return ('result1', 'result2')

       @qubes.events.handler('event1')
       @asyncio.coroutine
       def another_handler(self, event):
            print('Got event, starting long running action')
            yield from asyncio.sleep(10)
            return ('result3', 'result4')

       @qubes.events.handler('event1')
       def synchronous_handler(self, event):
            yield 'sync result'

   o = MyClass()
   o.events_enabled = True
   loop = asyncio.get_event_loop()
   # returns ['sync result', 'result1', 'result2', 'result3', 'result4'],
   # possibly not in order
   effects = loop.run_until_complete(o.fire_event_async('event1'))


Module contents
---------------

.. automodule:: qubes.events
   :members:
   :show-inheritance:

.. vim: ts=3 sw=3 et
