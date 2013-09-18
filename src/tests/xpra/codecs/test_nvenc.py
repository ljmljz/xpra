#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from tests.xpra.codecs.test_encoder import test_encoder
from xpra.codecs.nvenc import encoder, get_cuda_devices #@UnresolvedImport

TEST_DIMENSIONS = ((32, 32), (1920, 1080), (512, 512))

def test_encode():
    print("test_nvenc()")
    test_encoder(encoder)

def test_parallel_encode():
    cuda_devices = get_cuda_devices()
    print("test_parallel_encode() will test one encoder on each of %s sequentially" % cuda_devices)
    for device_id, info in cuda_devices.items():
        options = {"cuda_device" : device_id}
        print("testing on %s" % info)
        test_encoder(encoder, options)


def main():
    import logging
    import sys
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    test_encode()


if __name__ == "__main__":
    main()
