#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("osx", "events")


exit_cb = None
def quit_handler(*args):
    global exit_cb
    if exit_cb:
        exit_cb()
    else:
        from xpra.gtk_common.quit import gtk_main_quit_really
        gtk_main_quit_really()
    return True

def set_exit_cb(ecb):
    global exit_cb
    exit_cb = ecb


macapp = None
def get_OSXApplication():
    global macapp
    if macapp is None:
        try:
            import gtkosx_application        #@UnresolvedImport
            macapp = gtkosx_application.Application()
            macapp.connect("NSApplicationBlockTermination", quit_handler)
        except:
            pass
    return macapp

try:
    from Carbon import Snd      #@UnresolvedImport
except:
    Snd = None


def do_init():
    osxapp = get_OSXApplication()
    log("do_init() osxapp=%s", osxapp)
    if not osxapp:
        return  #not much else we can do here
    from xpra.platform.paths import get_icon
    icon = get_icon("xpra.png")
    log("do_init() icon=%s", icon)
    if icon:
        osxapp.set_dock_icon_pixbuf(icon)
    from xpra.platform.darwin.osx_menu import getOSXMenuHelper
    mh = getOSXMenuHelper(None)
    log("do_init() menu helper=%s", mh)
    osxapp.set_dock_menu(mh.build_dock_menu())
    osxapp.set_menu_bar(mh.rebuild())


def do_ready():
    osxapp = get_OSXApplication()
    osxapp.ready()


def get_native_tray_menu_helper_classes():
    from xpra.platform.darwin.osx_menu import getOSXMenuHelper
    return [getOSXMenuHelper]

def get_native_tray_classes():
    from xpra.platform.darwin.osx_tray import OSXTray
    return [OSXTray]

def system_bell(*args):
    if Snd is None:
        return False
    Snd.SysBeep(1)
    return True

#if there is an easier way of doing this, I couldn't find it:
try:
    import ctypes
    Carbon_ctypes = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
except:
    Carbon_ctypes = None

def get_double_click_time():
    try:
        #what are ticks? just an Apple retarded way of measuring elapsed time.
        #They must have considered gigaparsecs divided by teapot too, which is just as useful.
        #(but still call it "Time" you see)
        MS_PER_TICK = 1000/60
        return int(Carbon_ctypes.GetDblTime() * MS_PER_TICK)
    except:
        return -1


def get_window_frame_sizes():
    #use a hard-coded window position and size:
    return get_window_frame_size(20, 20, 100, 100)

def get_window_frame_size(x, y, w, h):
    try:
        import Quartz                   #@UnresolvedImport
        cr = Quartz.NSMakeRect(x, y, w, h)
        mask = Quartz.NSTitledWindowMask | Quartz.NSClosableWindowMask | Quartz.NSMiniaturizableWindowMask | Quartz.NSResizableWindowMask
        wr = Quartz.NSWindow.pyobjc_classMethods.frameRectForContentRect_styleMask_(cr, mask)
        dx = int(wr[0][0] - cr[0][0])
        dy = int(wr[0][1] - cr[0][1])
        dw = int(wr[1][0] - cr[1][0])
        dh = int(wr[1][1] - cr[1][1])
        #note: we assume that the title bar is at the top
        #dx, dy and dw are usually 0
        #dh is usually 22 on my 10.5.x system
        return {
                "offset"    : (dx+dw//2, dy+dh),
                "frame"     : (dx+dw//2, dx+dw//2, dy+dh, dy),
                }
    except:
        log("failed to query frame size using Quartz, using hardcoded value", exc_info=True)
        return {            #left, right, top, bottom:
                "offset"    : (0, 22),
                "frame"     : (0, 0, 22, 0),
               }


#global menu handling:
window_menus = {}

def window_focused(window, event):
    global window_menus
    wid = window._id
    menu_data = window_menus.get(wid)
    log("window_focused(%s, %s) menu(%s)=%s", window, event, wid, menu_data)
    application_actions, window_menu = None, None
    if menu_data:
        menus, application_action_callback, window_action_callback = menu_data
        application_actions = menus.get("application-actions")
        window_actions = menus.get("window-actions")
        window_menu = menus.get("window-menu")
    from xpra.platform.darwin.osx_menu import getOSXMenuHelper
    mh = getOSXMenuHelper()
    mh.rebuild()
    mh.add_full_menu()
    if not menu_data or (not application_actions and not window_actions) or not window_menu:
        return
    #add the application menus after that:
    #ie: menu = {
    #         'enabled': True,
    #         'application-id':         'org.xpra.ExampleMenu',
    #         'application-actions':    {'quit': (True, '', ()), 'about': (True, '', ()), 'help': (True, '', ()), 'custom': (True, '', ()), 'activate-tab': (True, 's', ()), 'preferences': (True, '', ())},
    #         'window-actions':         {'edit-profile': (True, 's', ()), 'reset': (True, 'b', ()), 'about': (True, '', ()), 'help': (True, '', ()), 'fullscreen': (True, '', (0,)), 'detach-tab': (True, '', ()), 'save-contents': (True, '', ()), 'zoom': (True, 'i', ()), 'move-tab': (True, 'i', ()), 'new-terminal': (True, '(ss)', ()), 'switch-tab': (True, 'i', ()), 'new-profile': (True, '', ()), 'close': (True, 's', ()), 'show-menubar': (True, '', (1,)), 'select-all': (True, '', ()), 'copy': (True, '', ()), 'paste': (True, 's', ()), 'find': (True, 's', ()), 'preferences': (True, '', ())},
    #         'window-menu':            {0:
    #               {0: ({':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}),
    #                1: ({'action': 'win.new-terminal', 'target': ('default', 'default'), 'label': '_New Terminal'},),
    #                2: ({'action': 'app.preferences', 'label': '_Preferences'},),
    #                3: ({'action': 'app.help', 'label': '_Help'}, {'action': 'app.about', 'label': '_About'}, {'action': 'app.quit', 'label': '_Quit'}),
    #                }
    #             }
    #           }
    #go through all the groups (not sure how we would get more than one with gtk menus.. but still):
    def cb(menu_item):
        #find the action for this item:
        action = getattr(menu_item, "_action", "undefined")
        log("application menu cb %s, action=%s", menu_item, action)
        if action.startswith("app."):
            callback = application_action_callback
            actions = application_actions
            action = action[4:]
        elif action.startswith("win."):
            callback = window_action_callback
            actions = window_actions
            action = action[4:]
        else:
            log.warn("Warning: unknown action type '%s'", action)
            return
        action_def = actions.get(action)
        if action_def is None:
            log.warn("Warning: cannot find action '%s'", action)
            return
        enabled, state, pdata = action_def[:3]
        if not enabled:
            log("action %s: %s is not enabled", action, action_def)
            return
        if len(action_def)>=4:
            callback = action_def[3]        #use action supplied callback
        log("OSX application menu item %s, action=%s, action_def=%s, callback=%s", menu_item, action, action_def, callback)
        if callback:
            callback(menu_item, action, state, pdata)
    for group_id in sorted(window_menu.keys()):
        group = window_menu[group_id]
        title = window.get_title() or "Application"
        app_menu = mh.make_menu()
        for menuid in sorted(group.keys()):
            menu_entries = group[menuid]
            for d in menu_entries:
                action = d.get("action")
                if not action:
                    continue
                label = d.get("label") or action
                item = mh.menuitem(label, cb=cb)
                item._action = action
                item._target = d.get("target")
                app_menu.add(item)
                log("added %s to %s menu for %s", label, title, window)
        mh.add_to_menu_bar(title, app_menu)


def add_window_hooks(window):
    window.connect("focus-in-event", window_focused)

def remove_window_hooks(window):
    try:
        del window_menus[window._id]
    except:
        pass

def _set_osx_window_menu(add, wid, window, menus, application_action_callback=None, window_action_callback=None):
    global window_menus
    log("_set_osx_window_menu%s", (add, wid, window, menus, application_action_callback, window_action_callback))
    if (not menus) or (menus.get("enabled") is not True) or (add is False):
        try:
            del window_menus[wid]
        except:
            pass
    else:
        window_menus[wid] = (menus, application_action_callback, window_action_callback)


def get_menu_support_function():
    return _set_osx_window_menu


try:
    import Quartz.CoreGraphics as CG    #@UnresolvedImport
    ALPHA = {
             CG.kCGImageAlphaNone                  : "AlphaNone",
             CG.kCGImageAlphaPremultipliedLast     : "PremultipliedLast",
             CG.kCGImageAlphaPremultipliedFirst    : "PremultipliedFirst",
             CG.kCGImageAlphaLast                  : "Last",
             CG.kCGImageAlphaFirst                 : "First",
             CG.kCGImageAlphaNoneSkipLast          : "SkipLast",
             CG.kCGImageAlphaNoneSkipFirst         : "SkipFirst",
       }
except:
    CG = None


def get_CG_imagewrapper():
    from xpra.codecs.image_wrapper import ImageWrapper
    assert CG, "cannot capture without Quartz.CoreGraphics"
    #region = CG.CGRectMake(0, 0, 100, 100)
    region = CG.CGRectInfinite
    image = CG.CGWindowListCreateImage(region,
                CG.kCGWindowListOptionOnScreenOnly,
                CG.kCGNullWindowID,
                CG.kCGWindowImageDefault)
    width = CG.CGImageGetWidth(image)
    height = CG.CGImageGetHeight(image)
    bpc = CG.CGImageGetBitsPerComponent(image)
    bpp = CG.CGImageGetBitsPerPixel(image)
    rowstride = CG.CGImageGetBytesPerRow(image)
    alpha = CG.CGImageGetAlphaInfo(image)
    alpha_str = ALPHA.get(alpha, alpha)
    log("get_CG_imagewrapper(..) image size: %sx%s, bpc=%s, bpp=%s, rowstride=%s, alpha=%s", width, height, bpc, bpp, rowstride, alpha_str)
    prov = CG.CGImageGetDataProvider(image)
    argb = CG.CGDataProviderCopyData(prov)
    return ImageWrapper(0, 0, width, height, argb, "BGRX", 24, rowstride)

def take_screenshot():
    log("grabbing screenshot")
    from PIL import Image                       #@UnresolvedImport
    from xpra.os_util import StringIOClass
    image = get_CG_imagewrapper()
    w = image.get_width()
    h = image.get_height()
    img = Image.frombuffer("RGB", (w, h), image.get_pixels(), "raw", image.get_pixel_format(), image.get_rowstride())
    buf = StringIOClass()
    img.save(buf, "PNG")
    data = buf.getvalue()
    buf.close()
    return w, h, "png", image.get_rowstride(), data


try:
    import Foundation                           #@UnresolvedImport
    import AppKit                               #@UnresolvedImport
    import PyObjCTools.AppHelper as AppHelper   #@UnresolvedImport
    NSObject = Foundation.NSObject
    NSWorkspace = AppKit.NSWorkspace
except Exception as e:
    log.warn("failed to load critical modules for sleep notification support: %s", e)
    NSObject = object
    NSWorkspace = None

class NotificationHandler(NSObject):
    """Class that handles the sleep notifications."""

    def handleSleepNotification_(self, aNotification):
        log("handleSleepNotification(%s)", aNotification)
        self.sleep_callback()

    def handleWakeNotification_(self, aNotification):
        log("handleWakeNotification(%s)", aNotification)
        self.wake_callback()


class ClientExtras(object):
    def __init__(self, client, opts, blocking=False):
        swap_keys = opts and opts.swap_keys
        log("ClientExtras.__init__(%s, %s, %s) swap_keys=%s", client, opts, blocking, swap_keys)
        self.client = client
        self.blocking = blocking
        self.setup_event_loop()
        if opts and client:
            log("setting swap_keys=%s using %s", swap_keys, client.keyboard_helper)
            if client.keyboard_helper and client.keyboard_helper.keyboard:
                log("%s.swap_keys=%s", client.keyboard_helper.keyboard, swap_keys)
                client.keyboard_helper.keyboard.swap_keys = swap_keys

    def cleanup(self):
        self.client = None
        self.stop_event_loop()

    def stop_event_loop(self):
        if self.notificationCenter:
            self.notificationCenter = None
            if self.blocking:
                AppHelper.stopEventLoop()
        if self.handler:
            self.handler = None

    def setup_event_loop(self):
        if NSWorkspace is None:
            self.notificationCenter = None
            self.handler = None
            log.warn("event loop not started")
            return
        ws = NSWorkspace.sharedWorkspace()
        self.notificationCenter = ws.notificationCenter()
        self.handler = NotificationHandler.new()
        self.handler.sleep_callback = self.client.suspend
        self.handler.wake_callback = self.client.resume
        self.notificationCenter.addObserver_selector_name_object_(
                 self.handler, "handleSleepNotification:",
                 AppKit.NSWorkspaceWillSleepNotification, None)
        self.notificationCenter.addObserver_selector_name_object_(
                 self.handler, "handleWakeNotification:",
                 AppKit.NSWorkspaceDidWakeNotification, None)
        log("starting console event loop with notifcation center=%s and handler=%s", self.notificationCenter, self.handler)
        if self.blocking:
            #this is for running standalone
            AppHelper.runConsoleEventLoop(installInterrupt=self.blocking)
        #when not blocking, we rely on another part of the code
        #to run the event loop for us


def main():
    from xpra.platform import init, clean
    try:
        init("OSX Extras")
        ClientExtras(None, None, True)
    finally:
        clean()


if __name__ == "__main__":
    main()
