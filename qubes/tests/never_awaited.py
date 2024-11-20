#
# The Qubes OS Project, https://www.qubes-os.org/
#
# Copyright (C) 2021 Rusty Bird <rustybird@net-c.com>
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

import functools
import gc
import warnings


# For unittest.TestResult._is_relevant_tb_level()
__unittest = True


def detect(handle=True, gc_before=False, gc_after=False):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            detected = []
            showwarning_orig = warnings.showwarning

            def showwarning(
                message, category, filename, lineno, file=None, line=None
            ):
                if issubclass(category, RuntimeWarning) and str.endswith(
                    str(message), " was never awaited"
                ):
                    detected.append(
                        warnings.WarningMessage(
                            message, category, filename, lineno, file, line
                        )
                    )
                else:
                    showwarning_orig(
                        message, category, filename, lineno, file, line
                    )

            if gc_before:
                gc.collect()
            warnings.showwarning = showwarning

            try:
                func(*args, **kwargs)
            finally:
                if gc_after:
                    gc.collect()
                warnings.showwarning = showwarning_orig
                if detected and handle:
                    raise RuntimeError("\n" + ";\n".join(map(str, detected)))

        return wrapper

    return decorator


ignore = functools.partial(detect, False, gc_before=True, gc_after=True)
