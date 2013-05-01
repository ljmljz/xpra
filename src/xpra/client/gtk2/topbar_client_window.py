# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
import gobject
from xpra.client.gtk2.client_window import ClientWindow

from xpra.log import Logger
log = Logger()


"""
A window which has a top bar above the window contents,
where we can place widgets.
"""
class TopBarClientWindow(ClientWindow):

    def init_window(self, metadata):
        self.info("init_window(%s)", metadata)
        ClientWindow.init_window(self, metadata)
        self._has_custom_decorations = False
        if not self._override_redirect:
            self._has_custom_decorations = True
            vbox = gtk.VBox()
            hbox = gtk.HBox()
            self.add_top_bar_widgets(hbox)
            vbox.pack_start(hbox, False, False, 2)
            self.add(vbox)
            vbox.show_all()
            w, h = vbox.size_request()
            self.debug("vbox size: %sx%s", w, h)
            self._offset = 0, h, 0, 0

    def add_top_bar_widgets(self, hbox):
        label = gtk.Label("hello")
        hbox.add(label)

    def do_expose_event(self, event):
        gtk.Window.do_expose_event(self, event)
        ClientWindow.do_expose_event(self, event)

    def paint_offset(self, event, context):
        #we use gtk.Window.do_expose_event to paint our widgets
        pass

gobject.type_register(TopBarClientWindow)
