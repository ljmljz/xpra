# -*- coding: utf-8 -*-
"""
The original version of python-webm can be found here:
https://code.google.com/p/python-webm/
This modified version adds support for lossless compression.

Copyright (c) 2011, Daniele Esposti <expo@expobrain.net>
Copyright (c) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * The name of the contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import sys, os
from ctypes import cdll as loader


# Generic constants
__VERSION__ = "0.2.3"

PIXEL_SZ = 3
PIXEL_ALPHA_SZ = 4


# Per-OS setup
if sys.platform == "win32":
    _LIBRARY_NAMES = ["libwebp.dll"]

elif sys.platform == "darwin":
    _LIBRARY_NAMES = ["libwebp.dylib"]

elif os.name == "posix":
    _LIBRARY_NAMES = ["libwebp.so.5", "libwebp.so.4", "libwebp.so.2"]

else:
    raise ImportError(
        "Test non implemented under %s / %s" % (os.name, sys.platform))

# Load library
_LIBRARY = None
for name in _LIBRARY_NAMES:
    try:
        _LIBRARY = loader.LoadLibrary(name)
        break
    except:
        pass
if _LIBRARY is None:
    raise ImportError("Could not find webp library from %s" % str(_LIBRARY_NAMES))
