# This file is part of Xpra.
# Copyright (C) 2014, 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("printing")

import subprocess
import win32print       #@UnresolvedImport
import win32con         #@UnresolvedImport

#ensure we can find gsprint.exe in a subdirectory:
try:
    from xpra.platform.paths import get_app_dir
    import os.path
    gsprint_dir = os.path.join(get_app_dir(), "gsview")
    gsprint_exe = os.path.join(gsprint_dir, "gsprint.exe")
    assert os.path.exists(gsprint_dir), "cannot find gsview directory in '%s'" % gsprint_dir
except Exception as e:
    log.warn("failed to setup gsprint path!")
    gsprint_dir, gsprint_exe = None, None


#allows us to skip some printers we don't want to export
SKIPPED_PRINTERS = os.environ.get("XPRA_SKIPPED_PRINTERS", "Microsoft XPS Document Writer").split(",")


#emulate pycups job id
JOB_ID = 0
PROCESSES = {}

printers_modified_callback = None
def on_printers_modified(callback):
    global printers_modified_callback
    log("on_printers_modified(%s) printers_modified_callback=%s", callback, printers_modified_callback)
    printers_modified_callback = callback
    try:
        init_winspool_listener()
    except Exception:
        log.error("failed to register for print spooler changes", exc_info=True)

def init_winspool_listener():
    from xpra.platform.win32.win32_events import get_win32_event_listener
    el = get_win32_event_listener()
    el.add_event_callback(win32con.WM_DEVMODECHANGE, on_devmodechange)

def on_devmodechange(wParam, lParam):
    log("on_devmodechange(%s, %s)", wParam, lParam)
    if lParam>0:
        #from ctypes import c_wchar_p
        #name = c_wchar_p(lParam)
        #log("device changed: %s", name)
        global printers_modified_callback
        if printers_modified_callback:
            printers_modified_callback()


def get_printers():
    printers = {}
    if not gsprint_dir:
        #without gsprint, we can't handle printing!
        return printers
    #default_printer = win32print.GetDefaultPrinter()
    for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL, None, 1):
        flags, desc, name, comment = p
        if name in SKIPPED_PRINTERS:
            log("skipped printer: %s, %s, %s, %s", flags, desc, name, comment)
            continue
        log("found printer: %s, %s, %s, %s", flags, desc, name, comment)
        #strip duplicated and empty strings from the description:
        desc_els = []
        [desc_els.append(x) for x in desc.split(",") if (x and not desc_els.count(x))]
        printers[name] = {"printer-info"            : ",".join(desc_els)}
        if comment:
            printers["printer-make-and-model"] = comment
    log("win32.get_printers()=%s", printers)
    return printers

def print_files(printer, filenames, title, options):
    log("win32.print_files%s", (printer, filenames, title, options))
    assert gsprint_dir, "cannot print files without gsprint!"
    global JOB_ID, PROCESSES
    processes = []
    for filename in filenames:
        #command = ["C:\\Program Files\\Xpra\\gsview\\gsprint.exe"]
        command = [gsprint_exe]
        if printer:
            command += ["-printer", printer]
        command += [filename]
        log("print command: %s", command)
        process = subprocess.Popen(command, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=gsprint_dir)
        process.print_filename = filename
        #we just let it run, no need for reaping the process on win32
        processes.append(process)
    JOB_ID +=1
    PROCESSES[JOB_ID] = processes
    log("win32.print_files(..)=%s (%s)", JOB_ID, processes)
    return JOB_ID

def printing_finished(jobid):
    global PROCESSES
    processes = PROCESSES.get(jobid)
    if not processes:
        log.warn("win32.printing_finished(%s) job not found!", jobid)
        return True
    log("win32.printing_finished(%s) processes: %s", jobid, [x.print_filename for x in processes])
    pending = [proc.print_filename for proc in processes if proc.poll() is None]
    log("win32.printing_finished(%s) still pending: %s", jobid, pending)
    #return finished when all the processes have terminated
    return len(pending)==0
