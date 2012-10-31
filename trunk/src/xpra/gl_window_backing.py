# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#only works with gtk2:
from gtk import gdk
assert gdk
import gtk.gdkgl, gtk.gtkgl         #@UnresolvedImport
assert gtk.gdkgl is not None and gtk.gtkgl is not None
import gobject

from wimpiggy.log import Logger
log = Logger()

from xpra.codec_constants import YUV420P, YUV422P, YUV444P
from xpra.gl_colorspace_conversions import GL_COLORSPACE_CONVERSIONS
from xpra.window_backing import PixmapBacking
from OpenGL.GL import GL_PROJECTION, GL_MODELVIEW, GL_VERTEX_ARRAY, \
    GL_TEXTURE_COORD_ARRAY, GL_FRAGMENT_PROGRAM_ARB, \
    GL_PROGRAM_ERROR_STRING_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, \
    GL_TEXTURE_RECTANGLE_ARB, GL_UNPACK_ROW_LENGTH, \
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_NEAREST, \
    GL_UNSIGNED_BYTE, GL_LUMINANCE, GL_LINEAR, \
    GL_TEXTURE0, GL_TEXTURE1, GL_TEXTURE2, GL_QUADS, \
    glActiveTexture, glTexSubImage2D, \
    glGetString, glViewport, glMatrixMode, glLoadIdentity, glOrtho, \
    glEnableClientState, glGenTextures, glDisable, \
    glBindTexture, glPixelStorei, glEnable, glBegin, \
    glTexParameteri, \
    glTexImage2D, \
    glMultiTexCoord2i, \
    glVertex2i, glEnd
from OpenGL.GL.ARB.vertex_program import glGenProgramsARB, glBindProgramARB, glProgramStringARB

"""
This is the gtk2 + OpenGL version.
"""
class GLPixmapBacking(PixmapBacking):

    def __init__(self, wid, w, h, mmap_enabled, mmap):
        PixmapBacking.__init__(self, wid, w, h, mmap_enabled, mmap)
        display_mode = (gtk.gdkgl.MODE_RGB | gtk.gdkgl.MODE_SINGLE)
        self.glconfig = gtk.gdkgl.Config(mode=display_mode)
        self.glarea = gtk.gtkgl.DrawingArea(self.glconfig)
        self.glarea.set_size_request(w, h)
        self.glarea.show()
        self.textures = None # OpenGL texture IDs
        self.yuv_shader = None
        self.pixel_format = None
        self.size = 0, 0

    def init(self, w, h):
        #also init the pixmap as backup:
        self.size = w, h
        PixmapBacking.init(self, w, h)
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()

        self.yuv_shader = None

        # Re-create textures
        self.pixel_format = None

        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")

        log("GL Pixmap backing size: %d x %d", w, h)
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0.0, w, h, 0.0, -1.0, 1.0)
        glMatrixMode(GL_MODELVIEW)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glDisable(GL_FRAGMENT_PROGRAM_ARB)

        if self.textures is None:
            self.textures = glGenTextures(3)

        drawable.gl_end()

    def render(self):
        log("GL render")
        self.render_image()
        self.glarea.window.invalidate_rect(self.glarea.allocation, False)
        # Update window synchronously (fast).
        self.glarea.window.process_updates(False)

    def do_video_paint(self, coding, img_data, x, y, width, height, options, callbacks):
        log("do_video_paint: options=%s, decoder=%s", options, type(self._video_decoder))
        err, rowstrides, img_data = self._video_decoder.decompress_image_to_yuv(img_data, options)
        success = err==0 and img_data and len(img_data)==3
        if not success:
            log.error("do_video_paint: %s decompression error %s on %s bytes of picture data for %sx%s pixels, options=%s",
                      coding, err, len(img_data), width, height, options)
            self.fire_paint_callbacks(callbacks, False)
            return
        def do_paint():
            csc_pixel_format = options.get("csc_pixel_format", -1)
            pixel_format = self._video_decoder.get_pixel_format(csc_pixel_format)
            self.update_texture_yuv(img_data, x, y, width, height, rowstrides, pixel_format)
            self.render_image()
            self.fire_paint_callbacks(callbacks, True)
        gobject.idle_add(do_paint)

    def get_subsampling_divs(self, pixel_format):
        if pixel_format==YUV420P:
            return 1, 2, 2
        elif pixel_format==YUV422P:
            return 1, 2, 1
        elif pixel_format==YUV444P:
            return 1, 1, 1
        raise Exception("invalid pixel format: %s" % pixel_format)

    def update_texture_yuv(self, img_data, x, y, width, height, rowstrides, pixel_format):
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        window_width, window_height = self.size
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        assert self.textures is not None

        if self.pixel_format is None or self.pixel_format!=pixel_format:
            self.pixel_format = pixel_format
            divs = self.get_subsampling_divs(pixel_format)
            log("GL creating new YUV textures for pixel format %s using divs=%s", pixel_format, divs)
            # Create textures of the same size as the window's
            glEnable(GL_TEXTURE_RECTANGLE_ARB)

            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                div = divs[index]
                glActiveTexture(texture)
                glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
                glEnable(GL_TEXTURE_RECTANGLE_ARB)
                mag_filter = GL_NEAREST
                if div>1:
                    mag_filter = GL_LINEAR
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MAG_FILTER, mag_filter)
                glTexParameteri(GL_TEXTURE_RECTANGLE_ARB, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
                glTexImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, GL_LUMINANCE, window_width/div, window_height/div, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, 0)

            log("Assigning fragment program")
            glEnable(GL_FRAGMENT_PROGRAM_ARB)
            if not self.yuv_shader:
                self.yuv_shader = [ 1 ]
                glGenProgramsARB(1, self.yuv_shader)
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv_shader[0])
                prog = GL_COLORSPACE_CONVERSIONS
                glProgramStringARB(GL_FRAGMENT_PROGRAM_ARB, GL_PROGRAM_FORMAT_ASCII_ARB, len(prog), prog)
                log.error(glGetString(GL_PROGRAM_ERROR_STRING_ARB))
                glBindProgramARB(GL_FRAGMENT_PROGRAM_ARB, self.yuv_shader[0])

        # Clamp width and height to the actual texture size
        if x + width > window_width:
            width = window_width - x
        if y + height > window_height:
            height = window_height - y

        divs = self.get_subsampling_divs(pixel_format)
        for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
            div = divs[index]
            glActiveTexture(texture)
            glBindTexture(GL_TEXTURE_RECTANGLE_ARB, self.textures[index])
            glPixelStorei(GL_UNPACK_ROW_LENGTH, rowstrides[index])
            glTexSubImage2D(GL_TEXTURE_RECTANGLE_ARB, 0, x, y, width/div, height/div, GL_LUMINANCE, GL_UNSIGNED_BYTE, img_data[index])

        drawable.gl_end()

    def render_image(self):
        if self.pixel_format is None:
            #not ready to render yet
            return
        drawable = self.glarea.get_gl_drawable()
        context = self.glarea.get_gl_context()
        log("GL render_image() size=%s", self.size)
        w, h = self.size
        if not drawable.gl_begin(context):
            raise Exception("** Cannot create OpenGL rendering context!")
        glEnable(GL_FRAGMENT_PROGRAM_ARB)
        glBegin(GL_QUADS);
        divs = self.get_subsampling_divs(self.pixel_format)
        for x,y in ((0, 0), (0, h), (w, h), (w, 0)):
            for texture, index in ((GL_TEXTURE0, 0), (GL_TEXTURE1, 1), (GL_TEXTURE2, 2)):
                div = divs[index]
                glMultiTexCoord2i(texture, x/div, y/div)
            glVertex2i(x, y)
        glEnd()

        drawable.swap_buffers()
        drawable.gl_end()
