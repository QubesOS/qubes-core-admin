#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2010-2015  Joanna Rutkowska <joanna@invisiblethingslab.com>
# Copyright (C) 2011-2015  Marek Marczykowski-Górecki
#                              <marmarek@invisiblethingslab.com>
# Copyright (C) 2014-2018  Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, see <https://www.gnu.org/licenses/>.
#

from . import vm as _vm

_NO_DEFAULT = object()

class Features(dict):
    '''Manager of the features.

    Features can have three distinct values: no value (not present in mapping,
    which is closest thing to :py:obj:`None`), empty string (which is
    interpreted as :py:obj:`False`) and non-empty string, which is
    :py:obj:`True`. Anything assigned to the mapping is coerced to strings,
    however if you assign instances of :py:class:`bool`, they are converted as
    described above. Be aware that assigning the number `0` (which is considered
    false in Python) will result in string `'0'`, which is considered true.

    This class inherits from dict, but has most of the methods that manipulate
    the item disarmed (they raise NotImplementedError). The ones that are left
    fire appropriate events on the qube that owns an instance of this class.
    '''

    #
    # Those are the methods that affect contents. Either disarm them or make
    # them report appropriate events. Good approach is to rewrite them carefully
    # using official documentation, but use only our (overloaded) methods.
    #
    def __init__(self, subject, other=None, **kwargs):
        super().__init__()
        self.subject = subject
        self.update(other, **kwargs)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.subject.fire_event('domain-feature-delete:' + key, feature=key)

    def __setitem__(self, key, value):
        if value is None or isinstance(value, bool):
            value = '1' if value else ''
        else:
            value = str(value)
        try:
            oldvalue = self[key]
            has_oldvalue = True
        except KeyError:
            has_oldvalue = False
        super().__setitem__(key, value)
        if has_oldvalue:
            self.subject.fire_event('domain-feature-set:' + key, feature=key,
                value=value, oldvalue=oldvalue)
        else:
            self.subject.fire_event('domain-feature-set:' + key, feature=key,
                value=value)

    def clear(self):
        for key in tuple(self):
            del self[key]

    def pop(self, _key, _default=None):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def popitem(self):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def setdefault(self, _key, _default=None):
        '''Not implemented
        :raises: NotImplementedError
        '''
        raise NotImplementedError()

    def update(self, other=None, **kwargs):
        if other is not None:
            if hasattr(other, 'keys'):
                for key in other:
                    self[key] = other[key]
            else:
                for key, value in other:
                    self[key] = value

        for key in kwargs:
            self[key] = kwargs[key]

    #
    # end of overriding
    #

    def _recursive_check(self, attr=None, *, feature, default,
            check_adminvm=False, check_app=False):
        '''Recursive search for a feature.

        Traverse domains along one attribute, like
        :py:attr:`qubes.vm.qubesvm.QubesVM.netvm` or
        :py:attr:`qubes.vm.appvm.AppVM.template`, starting with current domain
        (:py:attr:`subject`). Search stops when first `feature` is found. If
        a qube has no attribute, or if the attribute is :py:obj:`None`, the
        *default* is returned, or if not specified, :py:class:`KeyError` is
        raised.

        If `check_adminvm` is true, before returning default, also AdminVM is
        consulted (the recursion does not restart).

        If `check_app` is true, also the app feature is checked. This is not
        implemented, as app does not have features yet.
        '''
        if check_app:
            raise NotImplementedError('app does not have features yet')

        assert isinstance(self.subject, _vm.BaseVM), (
            'recursive checks do not work for {}'.format(
                type(self.subject).__name__))

        subject = self.subject
        while subject is not None:
            try:
                return subject.features[feature]
            except KeyError:
                if attr is None:
                    break
                subject = getattr(subject, attr, None)

        if check_adminvm:
            adminvm = self.subject.app.domains['dom0']
            if adminvm not in (None, self.subject):
                try:
                    return adminvm.features[feature]
                except KeyError:
                    pass

        # TODO check_app

        if default is not _NO_DEFAULT:
            return default

        raise KeyError(feature)

    def check_with_template(self, feature, default=_NO_DEFAULT):
        '''Check if the subject's template has the specified feature.'''
        return self._recursive_check('template',
            feature=feature, default=default)

    def check_with_netvm(self, feature, default=_NO_DEFAULT):
        '''Check if the subject's netvm has the specified feature.'''
        return self._recursive_check('netvm',
            feature=feature, default=default)

    def check_with_adminvm(self, feature, default=_NO_DEFAULT):
        '''Check if the AdminVM has the specified feature.'''
        return self._recursive_check(check_adminvm=True,
            feature=feature, default=default)

    def check_with_template_and_adminvm(self, feature, default=_NO_DEFAULT):
        '''Check if the template and AdminVM has the specified feature.'''
        return self._recursive_check('template', check_adminvm=True,
            feature=feature, default=default)
