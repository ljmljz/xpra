# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pygtk3 vs pygtk2 (sigh)
from wimpiggy.gobject_compat import import_gobject, import_gdk, is_gtk3
gobject = import_gobject()
gdk = import_gdk()

import cairo
import ctypes

from wimpiggy.log import Logger
log = Logger()

from xpra.scripts.main import ENCODINGS

PREFER_CAIRO = False        #just for testing the CairoBacking with gtk2

"""
An area we draw onto with cairo
This must be used with gtk3 since gtk3 no longer supports gdk pixmaps

/RANT: ideally we would want to use pycairo's create_for_data method:
#surf = cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, width, height)
but this is disabled in most cases, or does not accept our rowstride, so we cannot use it.
Instead we have to use PIL to convert via a PNG!
This is a complete waste of CPU! Please complain to pycairo.
"""
class CairoBacking(object):
    def __init__(self, w, h, old_backing, mmap_enabled, mmap):
        self.mmap_enabled = mmap_enabled
        self.mmap = mmap
        self._backing = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(self._backing)
        if old_backing is not None and old_backing._backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_surface(old_backing._backing, 0, 0)
            cr.paint()
            old_w = old_backing._backing.get_width()
            old_h = old_backing._backing.get_height()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
            old_backing._backing.finish()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def jpegimage(self, img_data, width, height):
        import Image
        try:
            from io import BytesIO          #@Reimport
            data = bytearray(img_data)
            buf = BytesIO(data)
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO(img_data)
        return Image.open(buf)
        #return Image.fromstring("RGB", (width, height), img_data, 'jpeg', 'RGB')

    def rgb24image(self, img_data, width, height, rowstride):
        import Image
        if rowstride>0:
            assert len(img_data) == rowstride * height
        else:
            assert len(img_data) == width * 3 * height
        return Image.fromstring("RGB", (width, height), img_data, 'raw', 'RGB', rowstride, 1)

    def paint_png(self, img_data, width, height):
        try:
            from io import BytesIO          #@Reimport
            import sys
            if sys.version>='3':
                data = bytearray(img_data.encode("latin1"))
            else:
                data = bytearray(img_data)
            buf = BytesIO(data)
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO(img_data)
        surf = cairo.ImageSurface.create_from_png(buf)
        gc = cairo.Context(self._backing)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()

    def paint_pil_image(self, pil_image, width, height):
        try:
            from io import BytesIO
            buf = BytesIO()
        except:
            from StringIO import StringIO   #@Reimport
            buf = StringIO()
        pil_image.save(buf, format="PNG")
        png_data = buf.getvalue()
        buf.close()
        self.cairo_paint_png(png_data, width, height)

    def paint_rgb24(self, img_data, width, height, rowstride):
        log.info("cairo_paint_rgb24(..,%s,%s,%s)" % (width, height, rowstride))
        gc = cairo.Context(self._backing)
        if rowstride==0:
            rowstride = width
        surf = cairo.ImageSurface.create_for_data(img_data, cairo.FORMAT_RGB24, width, height, rowstride)
        gc.set_source_surface(surf)
        gc.paint()
        surf.finish()

    def draw_region(self, x, y, width, height, coding, img_data, rowstride):
        log.debug("draw_region(%s,%s,%s,%s,%s,..,%s)", x, y, width, height, coding, rowstride)
        if coding == "mmap":
            """ see _mmap_send() in server.py for details """
            assert "rgb24" in ENCODINGS
            assert self.mmap_enabled
            data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
            if len(img_data)==1:
                #construct an array directly from the mmap zone:
                offset, length = img_data[0]
                arraytype = ctypes.c_char * length
                data = arraytype.from_buffer(self.mmap, offset)
                image = self.rgb24image(data, width, height, rowstride)
                data_start.value = offset+length
            else:
                #re-construct the buffer from discontiguous chunks:
                log("drawing from discontiguous area: %s", img_data)
                data = ""
                for offset, length in img_data:
                    self.mmap.seek(offset)
                    data += self.mmap.read(length)
                    data_start.value = offset+length
                image = self.rgb24image(data, width, height, rowstride)
            self.paint_pil_image(image, width, height)
        elif coding in ["rgb24", "jpeg"]:
            assert coding in ENCODINGS
            if coding=="rgb24":
                image = self.rgb24image(img_data, width, height, rowstride)
            else:   #if coding=="jpeg":
                image = self.jpegimage(img_data, width, height)
            self.paint_pil_image(image, width, height)
        elif coding == "png":
            assert coding in ENCODINGS
            self.paint_png(img_data, width, height)
        else:
            raise Exception("invalid picture encoding: %s" % coding)

    def cairo_draw(self, context, x, y):
        try:
            context.set_source_surface(self._backing, x, y)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)


class PixmapBacking(object):

    def __init__(self, w, h, old_backing, mmap_enabled, mmap):
        self.mmap_enabled = mmap_enabled
        self.mmap = mmap
        self._backing = gdk.Pixmap(gdk.get_default_root_window(), w, h)
        cr = self._backing.cairo_create()
        if old_backing is not None and old_backing._backing is not None:
            # Really we should respect bit-gravity here but... meh.
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_pixmap(old_backing._backing, 0, 0)
            cr.paint()
            old_w, old_h = old_backing._backing.get_size()
            cr.move_to(old_w, 0)
            cr.line_to(w, 0)
            cr.line_to(w, h)
            cr.line_to(0, h)
            cr.line_to(0, old_h)
            cr.line_to(old_w, old_h)
            cr.close_path()
        else:
            cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()

    def draw_region(self, x, y, width, height, coding, img_data, rowstride):
        gc = self._backing.new_gc()
        if coding == "mmap":
            """ see _mmap_send() in server.py for details """
            assert self.mmap_enabled
            data_start = ctypes.c_uint.from_buffer(self.mmap, 0)
            if len(img_data)==1:
                #construct an array directly from the mmap zone:
                offset, length = img_data[0]
                arraytype = ctypes.c_char * length
                data = arraytype.from_buffer(self.mmap, offset)
                self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, data, rowstride)
                data_start.value = offset+length
            else:
                #re-construct the buffer from discontiguous chunks:
                log("drawing from discontiguous area: %s", img_data)
                data = ""
                for offset, length in img_data:
                    self.mmap.seek(offset)
                    data += self.mmap.read(length)
                    data_start.value = offset+length
                self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, data, rowstride)
        elif coding == "rgb24":
            assert coding in ENCODINGS
            if rowstride>0:
                assert len(img_data) == rowstride * height
            else:
                assert len(img_data) == width * 3 * height
            self._backing.draw_rgb_image(gc, x, y, width, height, gdk.RGB_DITHER_NONE, img_data, rowstride)
        else:
            assert coding in ENCODINGS
            loader = gdk.PixbufLoader(coding)
            loader.write(img_data, len(img_data))
            loader.close()
            pixbuf = loader.get_pixbuf()
            if not pixbuf:
                log.error("failed %s pixbuf=%s data len=%s" % (coding, pixbuf, len(img_data)))
            else:
                self._backing.draw_pixbuf(gc, pixbuf, 0, 0, x, y, width, height)

    def cairo_draw(self, context, x, y):
        try:
            context.set_source_pixmap(self._backing, 0, 0)
            context.set_operator(cairo.OPERATOR_SOURCE)
            context.paint()
            return False
        except:
            log.error("cairo_draw(%s)", context, exc_info=True)


def new_backing(w, h, old_backing, mmap_enabled, mmap):
    if is_gtk3() or PREFER_CAIRO:
        return  CairoBacking(w, h, old_backing, mmap_enabled, mmap)
    return PixmapBacking(w, h, old_backing, mmap_enabled, mmap)
