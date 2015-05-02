# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
import glib

from xpra.log import Logger
log = Logger("server", "gtk")
screenlog = Logger("server", "screen")

from xpra.gtk_common.quit import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable,
                           gtk_main_quit_on_fatal_exceptions_disable)
from xpra.server.server_base import ServerBase
from xpra.gtk_common.gtk_util import get_gtk_version_info, gtk_main
from xpra.util import updict


class GTKServerBase(ServerBase):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See X11ServerBase, XpraServer and XpraX11ShadowServer
    """

    def __init__(self):
        log("ServerBase.__init__()")
        self.idle_add = glib.idle_add
        self.timeout_add = glib.timeout_add
        self.source_remove = glib.source_remove
        ServerBase.__init__(self)

    def watch_keymap_changes(self):
        ### Set up keymap change notification:
        gtk.gdk.keymap_get_default().connect("keys-changed", self._keys_changed)

    def signal_quit(self, signum, frame):
        gtk_main_quit_on_fatal_exceptions_disable()
        ServerBase.signal_quit(self, signum, frame)

    def do_quit(self):
        log("do_quit: calling gtk_main_quit_really")
        gtk_main_quit_on_fatal_exceptions_disable()
        gtk_main_quit_really()
        log("do_quit: gtk_main_quit_really done")

    def do_run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        log("do_run() calling %s", gtk_main)
        gtk_main()
        log("do_run() end of gtk.main()")

    def add_listen_socket(self, socktype, sock):
        sock.listen(5)
        glib.io_add_watch(sock, glib.IO_IN, self._new_connection, sock)
        self.socket_types[sock] = socktype

    def make_hello(self, source):
        capabilities = ServerBase.make_hello(self, source)
        if source.wants_display:
            display = gtk.gdk.display_get_default()
            capabilities.update({
                "display"               : display.get_name(),
                "cursor.default_size"   : display.get_default_cursor_size(),
                "cursor.max_size"       : display.get_maximal_cursor_size()})
        if source.wants_versions:
            capabilities.update(get_gtk_version_info())
        return capabilities

    def get_ui_info(self, *args):
        info = ServerBase.get_ui_info(self, *args)
        info["server.display"] = gtk.gdk.display_get_default().get_name()
        info["server.root_window_size"] = self.get_root_window_size()
        return info

    def do_get_info(self, proto, *args):
        info = ServerBase.do_get_info(self, proto, *args)
        updict(info, "server", get_gtk_version_info())
        info.update({
                     "server.type"      : "Python/gtk-x11",
                     "features.randr"   : self.randr})
        return info

    def get_root_window_size(self):
        return gtk.gdk.get_default_root_window().get_size()

    def get_max_screen_size(self):
        max_w, max_h = gtk.gdk.get_default_root_window().get_size()
        return max_w, max_h

    def set_best_screen_size(self):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        return root_w, root_h

    def calculate_workarea(self, maxw, maxh):
        screenlog("calculate_workarea(%s, %s)", maxw, maxh)
        workarea = gtk.gdk.Rectangle(0, 0, maxw, maxh)
        for ss in self._server_sources.values():
            screen_sizes = ss.screen_sizes
            screenlog("calculate_workarea() screen_sizes(%s)=%s", ss, screen_sizes)
            if not screen_sizes:
                continue
            for display in screen_sizes:
                #avoid error with old/broken clients:
                if not display or type(display) not in (list, tuple):
                    continue
                #display: [':0.0', 2560, 1600, 677, 423, [['DFP2', 0, 0, 2560, 1600, 646, 406]], 0, 0, 2560, 1574]
                if len(display)>=10:
                    work_x, work_y, work_w, work_h = display[6:10]
                    display_workarea = gtk.gdk.Rectangle(work_x, work_y, work_w, work_h)
                    screenlog("calculate_workarea() found %s for display %s", display_workarea, display[0])
                    workarea = workarea.intersect(display_workarea)
        #sanity checks:
        if workarea.width==0 or workarea.height==0:
            screenlog.warn("failed to calculate a common workarea - using the full display area")
            workarea = gtk.gdk.Rectangle(0, 0, maxw, maxh)
        self.set_workarea(workarea)

    def set_workarea(self, workarea):
        pass

    def set_desktop_geometry(self, width, height):
        pass

    def set_dpi(self, xdpi, ydpi):
        pass


    def _move_pointer(self, wid, pos):
        x, y = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        pass

    def _process_button_action(self, proto, packet):
        pass


    def _process_map_window(self, proto, packet):
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet):
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet):
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet):
        log.info("_process_configure_window(%s, %s)", proto, packet)


    def send_clipboard_packet(self, *parts):
        #overriden so we can inject the nesting check:
        if self.clipboard_nesting_check(self._clipboard_client):
            ServerBase.send_clipboard_packet(self, *parts)

    def process_clipboard_packet(self, ss, packet):
        #overriden so we can inject the nesting check:
        def do_check():
            if self.clipboard_nesting_check(ss):
                ServerBase.process_clipboard_packet(self, ss, packet)
        #the nesting check calls gtk, so we must call it from the main thread:
        self.idle_add(do_check)

    def clipboard_nesting_check(self, ss):
        log("clipboard_nesting_check(%s)", ss)
        if self._clipboard_client is None or not self._clipboard_client.clipboard_enabled:
            return False
        if gtk.main_level()>=10:
            log.warn("loop nesting too deep: %s", gtk.main_level())
            log.warn("you may have a clipboard forwarding loop, disabling the clipboard")
            #turn off clipboard at our end:
            self.set_clipboard_enabled_status(ss, False)
            #if we can, tell the client to do the same:
            if ss.clipboard_set_enabled:
                ss.send_clipboard_enabled("probable clipboard loop detected")
            return  False
        return True
