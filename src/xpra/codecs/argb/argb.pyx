# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    ctypedef void** const_void_pp "const void**"
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1


import struct
try:
    import numpy
except:
    numpy = None
if numpy:
    def make_byte_buffer(len):
        return numpy.empty(len, dtype=numpy.byte)
    def byte_buffer_to_buffer(x):
        return x.tostring()
else:
    #test for availability of bytearray
    #in a way that does not cause Cython to fail to compile:
    import __builtin__
    _bytearray =  __builtin__.__dict__.get("bytearray")
    if _bytearray is not None:
        def make_byte_buffer(len):          #@DuplicatedSignature
            return _bytearray(len)
        def byte_buffer_to_buffer(x):       #@DuplicatedSignature
            return str(x)
    else:
        #python 2.4 and older do not have bytearray, use array:
        import array
        def make_byte_buffer(len):          #@DuplicatedSignature
            return array.array('B', '\0' * len)
        def byte_buffer_to_buffer(x):       #@DuplicatedSignature
            return x.tostring()


def argb_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef const unsigned char * cbuf = <unsigned char *> 0
    cdef Py_ssize_t cbuf_len = 0
    assert PyObject_AsReadBuffer(buf, <const_void_pp> &cbuf, &cbuf_len)==0
    return argbdata_to_rgba(cbuf, cbuf_len)

cdef argbdata_to_rgba(const unsigned char* data, int dlen):
    if dlen <= 0:
        return None
    assert dlen % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % dlen
    b = make_byte_buffer(dlen)
    #number of pixels:
    cdef int mi = dlen/4
    cdef int i = 0
    while i < dlen:
        b[i]    = data[i+1]             #R
        b[i+1]  = data[i+2]             #G
        b[i+2]  = data[i+3]             #B
        b[i+3]  = data[i]               #A
        i = i + 4
    return b

def argb_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef unsigned char * cbuf = <unsigned char *> 0     #@DuplicateSignature
    cdef Py_ssize_t cbuf_len = 0                        #@DuplicateSignature
    assert PyObject_AsReadBuffer(buf, <const_void_pp> &cbuf, &cbuf_len)==0
    return argbdata_to_rgb(cbuf, cbuf_len)

cdef argbdata_to_rgb(const unsigned char *data, int dlen):
    if dlen <= 0:
        return None
    assert dlen % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % dlen
    #number of pixels:
    cdef int mi = dlen/4                #@DuplicateSignature
    #3 bytes per pixel:
    buf = make_byte_buffer(mi*3)
    cdef int di = 0
    cdef int si = 0
    while si < dlen:
        buf[di]   = data[si+1]            #R
        buf[di+1] = data[si+2]            #G
        buf[di+2] = data[si+3]            #B
        di += 3
        si += 4
    return buf


def premultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0
    cdef Py_ssize_t cbuf_len = 0                #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert PyObject_AsWriteBuffer(buf, <void **>&cbuf, &cbuf_len)==0
    do_premultiply_argb_in_place(cbuf, cbuf_len)

cdef do_premultiply_argb_in_place(unsigned int *buf, Py_ssize_t argb_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b
    cdef unsigned int argb
    assert sizeof(int) == 4
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    cdef int i
    for 0 <= i < argb_len / 4:
        argb = buf[i]
        a = (argb >> 24) & 0xff
        r = (argb >> 16) & 0xff
        r = r * a / 255
        g = (argb >> 8) & 0xff
        g = g * a / 255
        b = (argb >> 0) & 0xff
        b = b * a / 255
        buf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)

def unpremultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0   #@DuplicateSignature
    cdef Py_ssize_t cbuf_len = 0                    #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert PyObject_AsWriteBuffer(buf, <void **>&cbuf, &cbuf_len)==0
    do_unpremultiply_argb_in_place(cbuf, cbuf_len)

cdef do_unpremultiply_argb_in_place(unsigned int * buf, Py_ssize_t buf_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b                    #@DuplicateSignature
    cdef unsigned int argb                          #@DuplicateSignature
    assert sizeof(int) == 4
    assert buf_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % buf_len
    cdef int i                                      #@DuplicateSignature
    for 0 <= i < buf_len / 4:
        argb = buf[i]
        a = (argb >> 24) & 0xff
        if a==0:
            buf[i] = 0
            continue
        r = (argb >> 16) & 0xff
        r = r * 255 / a
        g = (argb >> 8) & 0xff
        g = g * 255 / a
        b = (argb >> 0) & 0xff
        b = b * 255 / a
        buf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)

def unpremultiply_argb(buf):
    # b is a Python buffer object
    cdef unsigned int * argb = <unsigned int *> 0   #@DuplicateSignature
    cdef Py_ssize_t argb_len = 0                    #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert PyObject_AsReadBuffer(buf, <const void **>&argb, &argb_len)==0
    return do_unpremultiply_argb(argb, argb_len)


#precalculate indexes in native endianness:
tmp = str(struct.pack("=BBBB", 0, 1, 2, 3))
cdef int B = tmp.find('\0')
cdef int G = tmp.find('\1')
cdef int R = tmp.find('\2')
cdef int A = tmp.find('\3')

cdef do_unpremultiply_argb(unsigned int * argb_in, Py_ssize_t argb_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data
    cdef unsigned int a, r, g, b                    #@DuplicateSignature
    cdef unsigned int argb                          #@DuplicateSignature
    assert sizeof(int) == 4
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    argb_out = make_byte_buffer(argb_len)
    cdef int i                                      #@DuplicateSignature
    for 0 <= i < argb_len / 4:
        argb = argb_in[i]
        a = (argb >> 24) & 0xff
        r = (argb >> 16) & 0xff
        g = (argb >> 8) & 0xff
        b = (argb >> 0) & 0xff
        if a!=0:
            r = r * 255 / a
            g = g * 255 / a
            b = b * 255 / a
        else:
            r = 0
            g = 0
            b = 0
        #we could use struct pack to avoid endianness issues
        #but this is python 2.5 onwards only and is probably slower:
        #struct.pack_into("=BBBB", argb_out, i*4, b, g, r, a)
        argb_out[i*4+B] = b
        argb_out[i*4+G] = g
        argb_out[i*4+R] = r
        argb_out[i*4+A] = a
    return argb_out
