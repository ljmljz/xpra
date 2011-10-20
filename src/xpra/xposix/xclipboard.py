# This file is part of Parti.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import struct
import gtk

from wimpiggy.lowlevel import (get_xatom, gdk_atom_objects_from_gdk_atom_array) #@UnresolvedImport
from wimpiggy.log import Logger
log = Logger()

from xpra.platform.clipboard_base import ClipboardProtocolHelperBase

class ClipboardProtocolHelper(ClipboardProtocolHelperBase):
    """ This clipboard helper adds the ability to parse raw X11 atoms
        to and from a form suitable for transport over the wire.
    """

    def __init__(self, send_packet_cb):
        ClipboardProtocolHelperBase.__init__(self, send_packet_cb, ["CLIPBOARD", "PRIMARY", "SECONDARY"])

    def _do_munge_raw_selection_to_wire(self, type, format, data):
        if format == 32:
            if type in ("ATOM", "ATOM_PAIR"):
                # Convert to strings and send that. Bizarrely, the atoms are
                # not actual X atoms, but an array of GdkAtom's reinterpreted
                # as a byte buffer.
                atoms = gdk_atom_objects_from_gdk_atom_array(data)
                return ("atoms", [str(atom) for atom in atoms])
            else:
                sizeof_long = struct.calcsize("@L")
                format = "@" + "L" * (len(data) // sizeof_long)
                ints = struct.unpack(format, data)
                return ("integers", ints)
        return ClipboardProtocolHelperBase._do_munge_raw_selection_to_wire(self, type, format, data)

    def _munge_wire_selection_to_raw(self, encoding, type, format, data):
        if encoding == "atoms":
            d = gtk.gdk.display_get_default()
            ints = [get_xatom(d, a) for a in data]
            return struct.pack("@" + "L" * len(ints), *ints)
        return ClipboardProtocolHelperBase._munge_wire_selection_to_raw(self, encoding, type, format, data)
