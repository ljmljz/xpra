#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os

#default implementation uses pycups
from xpra.log import Logger
log = Logger("printing")

MIMETYPES = [
             "application/pdf",
             "application/postscript",
            ]
#make it easier to test different mimetypes:
PREFERRED_MIMETYPE = os.environ.get("XPRA_PRINTING_PREFERRED_MIMETYPE")
if os.environ.get("XPRA_PRINTER_RAW", "0")=="1":
    MIMETYPES.append("raw")
if PREFERRED_MIMETYPE:
    if PREFERRED_MIMETYPE in MIMETYPES:
        MIMETYPES.remove(PREFERRED_MIMETYPE)
        MIMETYPES.insert(0, PREFERRED_MIMETYPE)
    else:
        log.warn("Warning: ignoring invalid preferred printing mimetype: %s", PREFERRED_MIMETYPE)
        log.warn(" allowed mimetypes: %s", MIMETYPES)


def err(*args):
    log.error(*args)

def get_printers():
    return {}

def get_printer_attributes(name):
    return []

def get_default_printer():
    return None

def print_files(printer, filenames, title, options):
    raise Exception("no print implementation available")

def printing_finished(printpid):
    return True

def init_printing(printers_modified_callback=None):
    pass

def cleanup_printing():
    pass

#default implementation uses pycups:
from xpra.platform import platform_import
try:
    from xpra.platform.pycups_printing import get_printers, print_files, printing_finished, init_printing, cleanup_printing
    assert get_printers and print_files and printing_finished and init_printing, cleanup_printing
except Exception as e:
    #ignore the error on win32:
    if not sys.platform.startswith("win"):
        err("Error: printing disabled:")
        err(" %s", e)

platform_import(globals(), "printing", False,
                "init_printing",
                "cleanup_printing",
                "get_printers",
                "get_default_printer",
                "print_files",
                "printing_finished",
                "MIMETYPES")


def main():
    if "-v" in sys.argv or "--verbose" in sys.argv:
        from xpra.log import add_debug_category, enable_debug_for
        add_debug_category("printing")
        enable_debug_for("printing")
        try:
            sys.argv.remove("-v")
        except:
            pass
        try:
            sys.argv.remove("--verbose")
        except:
            pass

    from xpra.util import nonl, pver
    def dump_printers(d):
        for k in sorted(d.keys()):
            v = d[k]
            print("* %s" % k)
            try:
                for pk,pv in v.items():
                    print("        %s : %s" % (pk.ljust(32), nonl(pver(pv))))
            except:
                print("        %s : %s" % (k.ljust(32), nonl(pver(v))))
            attr = get_printer_attributes(k)
            if attr:
                print(" attributes:")
                for a in attr:
                    print("        %s" % a)
    from xpra.platform import init, clean
    from xpra.log import enable_color
    from xpra.util import csv
    try:
        init("Printing", "Printing")
        enable_color()
        if len(sys.argv)<=1:
            dump_printers(get_printers())
            return 0
        printers = get_printers()
        if len(printers)==0:
            print("Cannot print: no printers found")
            return 1
        if len(sys.argv)==2:
            filename = sys.argv[1]
            if not os.path.exists(filename):
                print("Cannot print file '%s': file does not exist" % filename)
                return 1
            printer = get_default_printer()
            if not printer:
                printer = printers.keys()[0]
                if len(printers)>1:
                    print("More than one printer found: %s", csv(printer.keys()))
            print("Using printer '%s'" % printer)
            filenames = [filename]
        if len(sys.argv)>2:
            printer = sys.argv[1]
            if printer not in printers:
                print("Invalid printer '%s'" % printer)
                return 1
            filenames = sys.argv[2:]
            for filename in filenames:
                if not os.path.exists(filename):
                    print("File '%s' does not exist" % filename)
                    return 1
        print("Printing: %s" % csv(filenames))
        print_files(printer, filenames, "Print Command", {})
        return 0
    finally:
        clean()


if __name__ == "__main__":
    sys.exit(main())
