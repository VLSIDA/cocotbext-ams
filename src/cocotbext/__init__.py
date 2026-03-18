# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, Matthew Guthaus
# See LICENSE for details.

# namespace package
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
