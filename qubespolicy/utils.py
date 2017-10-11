# -*- encoding: utf8 -*-
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2017 boring-stuff <boring-stuff@users.noreply.github.com>
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


def _sanitize_char(input_char, extra_allowed_characters):
    input_char_ord = ord(input_char)

    if (ord('a') <= input_char_ord <= ord('z')) \
       or (ord('A') <= input_char_ord <= ord('Z')) \
       or (ord('0') <= input_char_ord <= ord('9')) \
       or (input_char in ['$', '_', '-', '.']) \
       or (input_char in extra_allowed_characters):
        result = input_char
    else:
        result = '_'

    return result


# This function needs to be synchronized with qrexec-daemon.c's sanitize_name()
# from the qubes-core-admin-linux repository.
#
# See https://github.com/QubesOS/qubes-core-admin-linux/blob/
#  4f0878ccbf8a95f8264b54d2b6f4dc433ca0793a/qrexec/qrexec-daemon.c#L627-L646
#
def _sanitize_name(input_string, extra_allowed_characters, assert_sanitized):
    result = ''.join(_sanitize_char(character, extra_allowed_characters)
                    for character in input_string)

    if assert_sanitized:
        assert input_string == result, \
               'Input string was expected to be sanitized, but was not.'
    else:
        return result


def sanitize_domain_name(input_string, assert_sanitized=False):
    return _sanitize_name(input_string, {}, assert_sanitized)


def sanitize_service_name(input_string, assert_sanitized=False):
    return _sanitize_name(input_string, {'+'}, assert_sanitized)
