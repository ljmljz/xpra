#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2010-2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys, os

from xpra.sound.sound_pipeline import SoundPipeline, gobject, glib, one_arg_signal
from xpra.sound.pulseaudio_util import has_pa
from xpra.sound.gstreamer_util import plugin_str, get_decoder_parser, get_queue_time, normv, MP3, CODECS, CODEC_ORDER, gst, QUEUE_LEAK, MS_TO_NS

from xpra.util import updict
from xpra.os_util import thread
from xpra.log import Logger
log = Logger("sound")


SINKS = ["autoaudiosink"]
DEFAULT_SINK = SINKS[0]
if has_pa():
    SINKS.append("pulsesink")
if sys.platform.startswith("darwin"):
    SINKS.append("osxaudiosink")
    DEFAULT_SINK = "osxaudiosink"
elif sys.platform.startswith("win"):
    SINKS.append("directsoundsink")
    DEFAULT_SINK = "directsoundsink"
if os.name=="posix":
    SINKS += ["alsasink", "osssink", "oss4sink", "jackaudiosink"]

#SINK_SHARED_DEFAULT_ATTRIBUTES = {"sync" : False,
#                                  "async" : True}
SINK_SHARED_DEFAULT_ATTRIBUTES = {"sync"    : False,
                                  "async"   : True,
                                  "qos"     : True
                                  }

SINK_DEFAULT_ATTRIBUTES = {
                           "pulsesink"  : {"client" : "Xpra"}
                           }

DEFAULT_SINK = os.environ.get("XPRA_SOUND_SINK", DEFAULT_SINK)
if DEFAULT_SINK not in SINKS:
    log.error("invalid default sound sink: '%s' is not in %s, using %s instead", DEFAULT_SINK, SINKS, SINKS[0])
    DEFAULT_SINK = SINKS[0]
QUEUE_SILENT = 0
QUEUE_TIME = get_queue_time(450)

GST_FORMAT_BUFFERS = 4

def sink_has_device_attribute(sink):
    return sink not in ("autoaudiosink", "jackaudiosink", "directsoundsink")


class SoundSink(SoundPipeline):

    __gsignals__ = SoundPipeline.__generic_signals__.copy()
    __gsignals__.update({
        "underrun"  : one_arg_signal,
        "overrun"   : one_arg_signal,
        "eos"       : one_arg_signal,
        })

    def __init__(self, sink_type=None, sink_options={}, codecs=CODECS, codec_options={}, volume=1.0):
        if not sink_type:
            sink_type = DEFAULT_SINK
        assert sink_type in SINKS, "invalid sink: %s" % sink_type
        matching = [x for x in CODEC_ORDER if (x in codecs and x in CODECS)]
        log("SoundSink(..) found matching codecs %s", matching)
        assert len(matching)>0, "no matching codecs between arguments %s and supported list %s" % (codecs, CODECS)
        codec = matching[0]
        decoder, parser = get_decoder_parser(codec)
        SoundPipeline.__init__(self, codec)
        self.sink_type = sink_type
        decoder_str = plugin_str(decoder, codec_options)
        pipeline_els = []
        pipeline_els.append("appsrc"+
                            " name=src"+
                            " emit-signals=0"+
                            " block=0"+
                            " is-live=0"+
                            " stream-type=stream"+
                            " format=%s" % GST_FORMAT_BUFFERS)
        pipeline_els.append(parser)
        pipeline_els.append(decoder_str)
        pipeline_els.append("audioconvert")
        pipeline_els.append("audioresample")
        pipeline_els.append("volume name=volume volume=%s" % volume)
        queue_el = ["queue",
                    "name=queue",
                    "min-threshold-time=0",
                    "max-size-buffers=0",
                    "max-size-bytes=0",
                    "max-size-time=%s" % QUEUE_TIME,
                    "leaky=%s" % QUEUE_LEAK]
        if QUEUE_SILENT:
            queue_el.append("silent=%s" % QUEUE_SILENT)
        pipeline_els.append(" ".join(queue_el))
        sink_attributes = SINK_SHARED_DEFAULT_ATTRIBUTES.copy()
        sink_attributes.update(SINK_DEFAULT_ATTRIBUTES.get(sink_type, {}))
        sink_attributes.update(sink_options)
        sink_str = plugin_str(sink_type, sink_attributes)
        pipeline_els.append(sink_str)
        self.setup_pipeline_and_bus(pipeline_els)
        self.volume = self.pipeline.get_by_name("volume")
        self.src    = self.pipeline.get_by_name("src")
        self.queue  = self.pipeline.get_by_name("queue")
        self.overruns = 0
        self.queue_state = "starting"
        if QUEUE_SILENT==0:
            self.queue.connect("overrun", self.queue_overrun)
            self.queue.connect("underrun", self.queue_underrun)
            self.queue.connect("running", self.queue_running)
            self.queue.connect("pushing", self.queue_pushing)

    def __repr__(self):
        return "SoundSink('%s' - %s)" % (self.pipeline_str, self.state)

    def cleanup(self):
        SoundPipeline.cleanup(self)
        self.sink_type = ""
        self.src = None


    def queue_pushing(self, *args):
        ltime = self.queue.get_property("current-level-time")/MS_TO_NS
        log("queue pushing: level=%i", ltime)
        self.check_levels("pushing")
        return 0

    def queue_running(self, *args):
        ltime = self.queue.get_property("current-level-time")/MS_TO_NS
        log("queue running: level=%s", ltime)
        self.check_levels("running")
        return 0

    def check_levels(self, new_state):
        if self.queue_state=="underrun":
            #lift min time restrictions:
            self.queue.set_property("min-threshold-time", 0)
        elif self.queue_state == "overrun":
            clt = self.queue.get_property("current-level-time")
            qpct = min(QUEUE_TIME, clt)*100//QUEUE_TIME
            log("resetting max-size-time back to %ims (level=%ims, %i%%)", QUEUE_TIME//MS_TO_NS, clt//MS_TO_NS, qpct)
            self.queue.set_property("max-size-time", QUEUE_TIME)
        self.queue_state = new_state
        self.emit_info()


    def queue_underrun(self, *args):
        if self.queue_state=="underrun" or self.queue_state=="starting":
            return
        ltime = self.queue.get_property("current-level-time")/MS_TO_NS
        log("queue underrun: level=%i, previous state=%s", ltime, self.queue_state)
        self.queue_state = "underrun"
        MIN_QUEUE = QUEUE_TIME//2
        mts = self.queue.get_property("min-threshold-time")
        if mts==MIN_QUEUE:
            return 0
        #set min time restrictions to fill up queue:
        log("increasing the min-threshold-time to %ims", MIN_QUEUE//MS_TO_NS)
        self.queue.set_property("min-threshold-time", MIN_QUEUE)
        def restore():
            if self.queue.get_property("min-threshold-time")==0:
                log("min-threshold-time already restored!")
                return False
            ltime = self.queue.get_property("current-level-time")//MS_TO_NS
            if ltime==0:
                log("not restored! (still underrun: %ims)", ltime)
                return True
            log("resetting the min-threshold-time back to %ims", 0)
            self.queue.set_property("min-threshold-time", 0)
            self.queue_state = "running"
            return False
        glib.timeout_add(1000, restore)
        return 0

    def queue_overrun(self, *args):
        if self.queue_state=="overrun":
            return
        ltime = self.queue.get_property("current-level-time")//MS_TO_NS
        log("queue overrun: level=%i, previous state=%s", ltime, self.queue_state)
        self.queue_state = "overrun"
        REDUCED_QT = QUEUE_TIME//2
        #empty the queue by reducing its max size:
        log("queue overrun: halving the max-size-time to %ims", REDUCED_QT//MS_TO_NS)
        self.queue.set_property("max-size-time", REDUCED_QT)
        self.overruns += 1
        self.emit("overrun", ltime)
        def restore():
            if self.queue.get_property("max-size-time")==QUEUE_TIME:
                log("max-size-time already restored!")
                return False
            ltime = self.queue.get_property("current-level-time")//MS_TO_NS
            if ltime>=REDUCED_QT:
                log("max-size-time not restored! (still overrun: %ims)", ltime)
                return True
            log("raising the max-size-time back to %ims", QUEUE_TIME//MS_TO_NS)
            self.queue.set_property("max-size-time", QUEUE_TIME)
            self.queue_state = "running"
            return False
        glib.timeout_add(1000, restore)
        return 0

    def eos(self):
        log("eos()")
        if self.src:
            self.src.emit('end-of-stream')
        self.cleanup()
        return 0

    def get_info(self):
        info = SoundPipeline.get_info(self)
        if QUEUE_TIME>0:
            clt = self.queue.get_property("current-level-time")
            qmax = self.queue.get_property("max-size-time")
            qmin = self.queue.get_property("min-threshold-time")
            updict(info, "queue", {
                "min"           : qmin//MS_TO_NS,
                "max"           : qmax//MS_TO_NS,
                "cur"           : clt//MS_TO_NS,
                "pct"           : min(QUEUE_TIME, clt)*100//qmax,
                "overruns"      : self.overruns,
                "state"         : self.queue_state})
        return info

    def add_data(self, data, metadata=None):
        if not self.src:
            log("add_data(..) dropped")
            return
        if self.queue_state=="overrun":
            log("add_data(..) queue in overrun state, data dropped")
            return
        #having a timestamp causes problems with the queue and overruns:
        if "timestamp" in metadata:
            del metadata["timestamp"]
        log("add_data(%s bytes, %s) queue_state=%s", len(data), metadata, self.queue_state)
        buf = gst.new_buffer(data)
        if metadata:
            ts = metadata.get("timestamp")
            if ts is not None:
                buf.timestamp = normv(ts)
            d = metadata.get("duration")
            if d is not None:
                buf.duration = normv(d)
        if self.push_buffer(buf):
            self.buffer_count += 1
            self.byte_count += len(data)
            ltime = self.queue.get_property("current-level-time")//MS_TO_NS
            log("pushed %s bytes, new buffer level: %sms, queue state=%s", len(data), ltime, self.queue_state)
        self.emit_info()

    def push_buffer(self, buf):
        #buf.size = size
        #buf.timestamp = timestamp
        #buf.duration = duration
        #buf.offset = offset
        #buf.offset_end = offset_end
        #buf.set_caps(gst.caps_from_string(caps))
        r = self.src.emit("push-buffer", buf)
        if r!=gst.FLOW_OK:
            log.error("push-buffer error: %s", r)
            self.emit('error', "push-buffer error: %s" % r)
            return False
        return True

gobject.type_register(SoundSink)


def main():
    from xpra.platform import init, clean
    init("Sound-Record")
    try:
        args = sys.argv
        log.enable_debug()
        import os.path
        if len(args) not in (2, 3):
            print("usage: %s [-v|--verbose] filename [codec]" % sys.argv[0])
            return 1
        filename = args[1]
        if not os.path.exists(filename):
            print("file %s does not exist" % filename)
            return 2
        if len(args)==3:
            codec = args[2]
            if codec not in CODECS:
                print("invalid codec: %s" % codec)
                return 2
        else:
            codec = None
            parts = filename.split(".")
            if len(parts)>1:
                extension = parts[-1]
                if extension.lower() in CODECS:
                    codec = extension.lower()
                    print("guessed codec %s from file extension %s" % (codec, extension))
            if codec is None:
                print("assuming this is an mp3 file...")
                codec = MP3

        log.enable_debug()
        with open(filename, "rb") as f:
            data = f.read()
        print("loaded %s bytes from %s" % (len(data), filename))
        #force no leak since we push all the data at once
        global QUEUE_LEAK, GST_QUEUE_NO_LEAK, QUEUE_SILENT
        QUEUE_LEAK = GST_QUEUE_NO_LEAK
        QUEUE_SILENT = 1
        ss = SoundSink(codec=codec)
        ss.add_data(data)
        def eos(*args):
            print("eos")
            glib.idle_add(glib_mainloop.quit)
        ss.connect("eos", eos)
        ss.start()

        glib_mainloop = glib.MainLoop()

        import signal
        def deadly_signal(*args):
            glib.idle_add(glib_mainloop.quit)
        signal.signal(signal.SIGINT, deadly_signal)
        signal.signal(signal.SIGTERM, deadly_signal)

        def check_for_end(*args):
            qtime = ss.queue.get_property("current-level-time")//MS_TO_NS
            if qtime<=0:
                log.info("underrun (end of stream)")
                thread.start_new_thread(ss.stop, ())
                glib.timeout_add(500, glib_mainloop.quit)
                return False
            return True
        glib.timeout_add(1000, check_for_end)

        glib_mainloop.run()
        return 0
    finally:
        clean()


if __name__ == "__main__":
    sys.exit(main())
