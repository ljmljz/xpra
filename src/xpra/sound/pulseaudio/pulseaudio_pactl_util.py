#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path

from xpra.sound.pulseaudio.pulseaudio_common_util import get_pulse_server_x11_property, get_pulse_id_x11_property
from xpra.scripts.exec_util import safe_exec
from xpra.util import nonl, print_nested_dict

from xpra.log import Logger
log = Logger("sound")


def which(name):
    if sys.platform.startswith("win"):
        return    ""
    cmd = ["which", name]
    try:
        returncode, out, _ = safe_exec(cmd, log_errors=False)
        log("safe_exec(%s)=%s", cmd, (returncode, out))
        if returncode!=0 or not out:
            return ""
        c = out.decode("utf8").replace("\n", "").replace("\r", "")
        if os.path.exists(c) and os.path.isfile(c):
            if os.name=="posix" and not os.access(c, os.X_OK):
                #odd, it's there but we can't run it!?
                return ""
            return c
        return ""
    except Exception as e:
        log.error("Error: failed to run '%s'", " ".join(cmd))
        log.error(" %s", e)
        log("which(%s) error", name, exc_info=True)
    return ""

pactl_bin = None
has_pulseaudio = None

def get_pactl_bin():
    global pactl_bin
    if pactl_bin is None:
        if sys.platform.startswith("win") or sys.platform.startswith("darwin"):
            pactl_bin = ""
        else:
            pactl_bin = which("pactl")
    return pactl_bin

def pactl_output(log_errors=True, *pactl_args):
    pactl_bin = get_pactl_bin()
    if not pactl_bin:
        return -1, None, None
    #ie: "pactl list"
    cmd = [pactl_bin] + list(pactl_args)
    #force "C" locale so that we can parse the output as expected
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    kwargs = {"env" : env}
    try:
        code, out, err = safe_exec(cmd, log_errors=log_errors, **kwargs)
        log("pactl_output%s returned %s", pactl_args, code)
        return  code, out, err
    except Exception as e:
        if log_errors:
            log.error("failed to execute %s: %s", cmd, e)
        else:
            log("failed to execute %s: %s", cmd, e)
        return  -1, None, None

def is_pa_installed():
    pactl_bin = get_pactl_bin()
    log("is_pa_installed() pactl_bin=%s", pactl_bin)
    return len(pactl_bin)>0

def has_pa():
    global has_pulseaudio
    if has_pulseaudio is None:
        has_pulseaudio = get_pulse_server_x11_property() or is_pa_installed()
    return has_pulseaudio


def set_source_mute(device, mute=False):
    code, out, err = pactl_output(True, "set-source-mute", device, str(int(mute)))
    log("set_source_mute: output=%s, err=%s", out, err)
    return code==0

def set_sink_mute(device, mute=False):
    code, out, err = pactl_output(True, "set-sink-mute", device, str(int(mute)))
    log("set_sink_mute: output=%s, err=%s", out, err)
    return code==0

def get_pactl_stat_line(prefix):
    if not has_pa():
        return ""
    code, out, err = pactl_output(False, "stat")
    if code!=0:
        log.warn("Warning: failed to query pulseaudio using 'pactl list'")
        if err:
            log.warn(" %s", nonl(err))
        return    ""
    stat = ""
    for line in out.splitlines():
        if line.startswith(prefix):
            stat = line[len(prefix):].strip()
            break
    log("get_pactl_stat_line(%s)=%s", prefix, stat)
    return stat

def get_default_sink():
    return get_pactl_stat_line("Default Sink:")

def get_pactl_server():
    return get_pactl_stat_line("Server String:")


def get_pulse_server(may_start_it=True):
    xp = get_pulse_server_x11_property()
    if xp or not may_start_it:
        return xp
    return get_pactl_server()

def get_pulse_id():
    return get_pulse_id_x11_property()


def get_pa_device_options(monitors=False, input_or_output=None, ignored_devices=["bell-window-system"], log_errors=True):
    """
    Finds the list of devices, monitors=False allows us to filter out monitors
    (which could create sound loops if we use them)
    set input_or_output=True to get inputs only
    set input_or_output=False to get outputs only
    set input_or_output=None to get both
    Same goes for monitors (False|True|None)
    Returns the a dict() with the PulseAudio name as key and a description as value
    """
    if sys.platform.startswith("win") or sys.platform.startswith("darwin"):
        return {}
    status, out, _ = pactl_output(False, "list")
    if status!=0 or not out:
        return  {}
    return do_get_pa_device_options(out, monitors, input_or_output, ignored_devices, log_errors)

def do_get_pa_device_options(pactl_list_output, monitors=False, input_or_output=None, ignored_devices=["bell-window-system"], log_errors=True):
    device_class = None
    device_description = None
    name = None
    devices = {}
    for line in pactl_list_output.splitlines():
        if not line.startswith(" ") and not line.startswith("\t"):        #clear vars when we encounter a new section
            if name and device_class:
                if name in ignored_devices:
                    continue
                #Verify against monitor flag if set:
                if monitors is not None:
                    is_monitor = device_class=='"monitor"'
                    if is_monitor!=monitors:
                        continue
                #Verify against input flag (if set):
                if input_or_output is not None:
                    is_input = name.lower().find("input")>=0
                    if is_input is True and input_or_output is False:
                        continue
                    is_output = name.lower().find("output")>=0
                    if is_output is True and input_or_output is True:
                        continue
                if not device_description:
                    device_description = name
                devices[name] = device_description
            name = None; device_class = None
        line = line.strip()
        if line.startswith("Name: "):
            name = line[len("Name: "):]
        if line.startswith("device.class = "):
            device_class = line[len("device-class = "):]
        if line.startswith("device.description = "):
            device_description = line[len("device.description = "):].strip('"')
    return devices


def get_info():
    i = 0
    dinfo = {}
    for monitors in (True, False):
        for io in (True, False):
            devices = get_pa_device_options(monitors, io, log_errors=False)
            for d,name in devices.items():
                dinfo[d] = name
                i += 1
    return {
            "device"        : dinfo,
            "devices"       : i,
            "pulseaudio"    : {
                               "wrapper"   : "pactl",
                               "found"     : has_pa(),
                               "id"        : get_pulse_id(),
                               "server"    : get_pulse_server(False),
                               }
            }


def main():
    from xpra.os_util import load_binary_file
    if "-v" in sys.argv:
        log.enable_debug()
        sys.argv.remove("-v")
    if len(sys.argv)>1:
        for filename in sys.argv[1:]:
            if not os.path.exists(filename):
                log.warn("file argument '%s' does not exist, ignoring", filename)
                continue
            data = load_binary_file(filename)
            devices = do_get_pa_device_options(data, True, False)
            log.info("%s devices found in '%s'", len(devices), filename)
            print_nested_dict(devices)
        return

    i = get_info()
    print_nested_dict(i)

if __name__ == "__main__":
    main()
