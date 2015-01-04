#!/usr/bin/env python

import gtk.gdk

def main():
	window = gtk.Window(gtk.WINDOW_TOPLEVEL)
	window.set_size_request(200, 80)
	window.connect("delete_event", gtk.mainquit)
	vbox = gtk.VBox(False, 0)

	def add_buttons(t1, cb1, t2, cb2):
		hbox = gtk.HBox(True, 10)
		b1 = gtk.Button(t1)
		def vcb1(*args):
			cb1()
		b1.connect('clicked', vcb1)
		hbox.pack_start(b1, expand=True, fill=False, padding=5)
		b2 = gtk.Button(t2)
		def vcb2(*args):
			cb2()
		b2.connect('clicked', vcb2)
		hbox.pack_start(b2, expand=True, fill=False, padding=5)
		vbox.pack_start(hbox, expand=False, fill=False, padding=2)

	add_buttons("maximize", window.maximize, "unmaximize", window.unmaximize)
	add_buttons("fullscreen", window.fullscreen, "unfullscreen", window.unfullscreen)

	def window_state(widget, event):
		STATES = {
				gtk.gdk.WINDOW_STATE_WITHDRAWN	: "withdrawn",
				gtk.gdk.WINDOW_STATE_ICONIFIED	: "iconified",
				gtk.gdk.WINDOW_STATE_MAXIMIZED	: "maximized",
				gtk.gdk.WINDOW_STATE_STICKY		: "sticky",
				gtk.gdk.WINDOW_STATE_FULLSCREEN	: "fullscreen",
				gtk.gdk.WINDOW_STATE_ABOVE		: "above",
				gtk.gdk.WINDOW_STATE_BELOW		: "below",
				}
		print("window_state(%s, %s)" % (widget, event))
		print("flags: %s" % [STATES[x] for x in STATES.keys() if x & event.new_window_state])
	window.connect("window-state-event", window_state)

	window.add(vbox)
	window.show_all()
	gtk.main()
	return 0


if __name__ == "__main__":
	main()
