# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
MAX_NONVIDEO_PIXELS = 512
MAX_NONVIDEO_OR_INITIAL_PIXELS = 1024*64
try:
    MAX_NONVIDEO_PIXELS = int(os.environ.get("XPRA_MAX_NONVIDEO_PIXELS", 2048))
except:
    pass
try:
    MAX_NONVIDEO_OR_INITIAL_PIXELS = int(os.environ.get("XPRA_MAX_NONVIDEO_OR_INITIAL_PIXELS", 1024*64))
except:
    pass

AUTO_REFRESH_ENCODING = os.environ.get("XPRA_AUTO_REFRESH_ENCODING", "")
AUTO_REFRESH_THRESHOLD = int(os.environ.get("XPRA_AUTO_REFRESH_THRESHOLD", 90))
AUTO_REFRESH_QUALITY = int(os.environ.get("XPRA_AUTO_REFRESH_QUALITY", 95))
AUTO_REFRESH_SPEED = int(os.environ.get("XPRA_AUTO_REFRESH_SPEED", 0))

#how many historical records to keep
#for the various statistics we collect:
#(cannot be lower than DamageBatchConfig.MAX_EVENTS)
NRECS = 100

import gtk.gdk
import gobject
import time
from threading import Lock

from xpra.log import Logger
log = Logger()

XPRA_DAMAGE_DEBUG = os.environ.get("XPRA_DAMAGE_DEBUG", "0")!="0"
if XPRA_DAMAGE_DEBUG:
    debug = log.debug
    info = log.info
    rgblog = log.debug
else:
    def noop(*args, **kwargs):
        pass
    debug = noop
    info = noop
    rgblog = None

from xpra.deque import maxdeque
from xpra.net.protocol import zlib_compress, Compressed
from xpra.server.window_stats import WindowPerformanceStatistics
from xpra.simple_stats import add_list_stats
from xpra.server.stats.maths import calculate_time_weighted_average
from xpra.server.batch_delay_calculator import calculate_batch_delay, update_video_encoder
try:
    from xpra.codecs.xor import xor_str        #@UnresolvedImport
except:
    xor_str = None
from xpra.os_util import StringIOClass

#old gtk versions lack gtk.gdk.Region().get_rectangles()
#so for those we just keep them in a list..
#(which isn't as good since we don't merge rectangles
#or discard subsets, but better than carrying ugly crufty code
#just for those outdated pygtk versions..)
tmp_region = gtk.gdk.Region()
if hasattr(tmp_region, "get_rectangles") and os.environ.get("XPRA_FAKE_OLD_PYGTK", "0")=="0":
    def new_region():
        return gtk.gdk.Region()
    def add_rectangle(region, rectangle):
        region.union_with_rect(rectangle)
    def get_rectangles(region):
        return region.get_rectangles()
else:
    log.warn("using get_rectangles workaround for old pygtk versions")
    def new_region():
        return list()
    def add_rectangle(region, rectangle):
        if rectangle not in region:
            region.append(rectangle)
    def get_rectangles(region):
        return region
del tmp_region


class DamageBatchConfig(object):
    """
    Encapsulate all the damage batching configuration into one object.
    """
    ALWAYS = False
    MAX_EVENTS = min(50, NRECS)         #maximum number of damage events
    MAX_PIXELS = 1024*1024*MAX_EVENTS   #small screen at MAX_EVENTS frames
    TIME_UNIT = 1                       #per second
    MIN_DELAY = 5                       #lower than 5 milliseconds does not make sense, just don't batch
    START_DELAY = 50
    MAX_DELAY = 15000
    RECALCULATE_DELAY = 0.04            #re-compute delay 25 times per second at most
                                        #(this theoretical limit is never achieved since calculations take time + scheduling also does)


    def __init__(self):
        self.always = self.ALWAYS
        self.max_events = self.MAX_EVENTS
        self.max_pixels = self.MAX_PIXELS
        self.time_unit = self.TIME_UNIT
        self.min_delay = self.MIN_DELAY
        self.max_delay = self.MAX_DELAY
        self.delay = self.START_DELAY
        self.last_delays = maxdeque(64)                 #the delays we have tried to use (milliseconds)
        self.last_actual_delays = maxdeque(64)          #the delays we actually used (milliseconds)
        self.last_updated = 0
        self.wid = 0

    def clone(self):
        c = DamageBatchConfig()
        for x in ["always", "max_events", "max_pixels", "time_unit",
                  "min_delay", "max_delay", "delay"]:
            setattr(c, x, getattr(self, x))
        return c

    def __str__(self):
        return  "DamageBatchConfig(wid=%s, always=%s, min=%s, max=%s, current=%s, max events=%s, max pixels=%s, time unit=%s)" % \
                (self.wid, self.always, self.min_delay, self.max_delay, self.delay, self.max_events, self.max_pixels, self.time_unit)



class WindowSource(object):
    """
    We create a Window Source for each window we send pixels for.

    The UI thread calls 'damage' and we eventually
    call ServerSource.queue_damage to queue the damage compression,

    """

    def __init__(self, queue_damage, queue_packet, statistics,
                    wid, batch_config, auto_refresh_delay,
                    encoding, encodings, core_encodings, encoding_options,
                    default_encoding_options,
                    mmap, mmap_size):
        self.queue_damage = queue_damage                #callback to add damage data which is ready to compress to the damage processing queue
        self.queue_packet = queue_packet                #callback to add a network packet to the outgoing queue
        self.wid = wid
        self.global_statistics = statistics             #shared/global statistics from ServerSource
        self.statistics = WindowPerformanceStatistics()
        self.encoding = encoding                        #the current encoding
        self.encodings = encodings                      #all the encodings supported by the client
        self.core_encodings = core_encodings            #the core encodings
        self.encoding_options = encoding_options        #extra options which may be specific to the encoder (ie: x264)
        self.default_encoding_options = default_encoding_options    #default encoding options, like "quality", "min-quality", etc
                                                        #may change at runtime (ie: see ServerSource.set_quality)
        self.encoding_client_options = encoding_options.get("client_options", False)
                                                        #does the client support encoding options?
        self.supports_rgb24zlib = encoding_options.get("rgb24zlib", False)
                                                        #supports rgb24 compression outside network layer (unwrapped)
        self.uses_swscale = encoding_options.get("uses_swscale", True)
                                                        #client uses uses_swscale (has extra limits on sizes)
                                                        #unused since we still use swscale on the server...
        from xpra.server.server_base import SERVER_CORE_ENCODINGS
        self.SERVER_CORE_ENCODINGS = SERVER_CORE_ENCODINGS
        self.supports_delta = []
        if xor_str is not None:
            self.supports_delta = [x for x in encoding_options.get("supports_delta", []) if x in ("png", "rgb24")]
        self.last_pixmap_data = None
        self.batch_config = batch_config
        #auto-refresh:
        self.auto_refresh_delay = auto_refresh_delay
        self.refresh_timer = None
        self.timeout_timer = None
        self.expire_timer = None

        self.window_dimensions = 0, 0

        # mmap:
        self._mmap = mmap
        self._mmap_size = mmap_size

        # video codecs:
        self._video_encoder = None
        self._video_encoder_lock = Lock()               #to ensure we serialize access to the encoder and its internals
        self._video_encoder_quality = maxdeque(NRECS)   #keep track of the target encoding_quality: (event time, encoding speed)
        self._video_encoder_speed = maxdeque(NRECS)     #keep track of the target encoding_speed: (event time, encoding speed)
        # for managing/cancelling damage requests:
        self._damage_delayed = None                     #may store a delayed region when batching in progress
        self._damage_delayed_expired = False            #when this is True, the region should have expired
                                                        #but it is now waiting for the backlog to clear
        self._sequence = 1                              #increase with every region we process or delay
        self._last_sequence_queued = 0                  #the latest sequence we queued for sending (after encoding it)
        self._damage_cancelled = 0                      #stores the highest _sequence cancelled
        self._damage_packet_sequence = 1                #increase with every damage packet created

    def cleanup(self):
        self.cancel_damage()
        self.video_encoder_cleanup()
        self._damage_cancelled = float("inf")
        debug("encoding_totals for wid=%s with primary encoding=%s : %s", self.wid, self.encoding, self.statistics.encoding_totals)

    def video_encoder_cleanup(self):
        """ Video encoders (x264 and vpx) require us to run
            cleanup code to free the memory they use.
        """
        try:
            self._video_encoder_lock.acquire()
            if self._video_encoder:
                self.do_video_encoder_cleanup()
        finally:
            self._video_encoder_lock.release()

    def do_video_encoder_cleanup(self):
        self._video_encoder.clean()
        self._video_encoder = None
        self._video_encoder_speed = maxdeque(NRECS)
        self._video_encoder_quality = maxdeque(NRECS)

    def set_new_encoding(self, encoding):
        """ Changes the encoder for the given 'window_ids',
            or for all windows if 'window_ids' is None.
        """
        if self.encoding==encoding:
            return
        self.video_encoder_cleanup()
        self.last_pixmap_data = None
        self.encoding = encoding
        self.statistics.reset()

    def cancel_damage(self):
        """
        Use this method to cancel all currently pending and ongoing
        damage requests for a window.
        Damage methods will check this value via 'is_cancelled(sequence)'.
        """
        debug("cancel_damage() wid=%s, dropping delayed region %s and all sequences up to %s", self.wid, self._damage_delayed, self._sequence)
        #for those in flight, being processed in separate threads, drop by sequence:
        self._damage_cancelled = self._sequence
        self.cancel_expire_timer()
        self.cancel_refresh_timer()
        self.cancel_timeout_timer()
        #if a region was delayed, we can just drop it now:
        self._damage_delayed = None
        self._damage_delayed_expired = False
        self.last_pixmap_data = None
        if self._last_sequence_queued<self._sequence:
            #we must clean the video encoder to ensure
            #we will resend a key frame because it looks like we will
            #drop a frame which is being processed
            self.video_encoder_cleanup()

    def cancel_expire_timer(self):
        if self.expire_timer:
            gobject.source_remove(self.expire_timer)
            self.expire_timer = None

    def cancel_refresh_timer(self):
        if self.refresh_timer:
            gobject.source_remove(self.refresh_timer)
            self.refresh_timer = None

    def cancel_timeout_timer(self):
        if self.timeout_timer:
            gobject.source_remove(self.timeout_timer)
            self.timeout_timer = None


    def is_cancelled(self, sequence):
        """ See cancel_damage(wid) """
        return sequence>=0 and self._damage_cancelled>=sequence

    def add_stats(self, info, metadata, suffix=""):
        """
            Add window specific stats
        """
        prefix = "window[%s]." % self.wid
        #no suffix for metadata (as it is the same for all clients):
        info[prefix+"dimensions"] = self.window_dimensions
        if metadata:
            for k,v in metadata.items():
                if k=="icon" or v is None:
                    continue
                if k=="size-constraints":
                    #unroll nested props:
                    for sk,sv in v.items():
                        info[prefix+sk] = sv
                    continue
                info[prefix+k] = v
        info[prefix+"encoding"+suffix] = self.encoding
        self.statistics.add_stats(info, prefix, suffix)
        #batch stats:
        if len(self.batch_config.last_actual_delays)>0:
            batch_delays = [x for _,x in list(self.batch_config.last_delays)]
            add_list_stats(info, prefix+"batch_delay"+suffix, batch_delays, show_percentile=[9])
        try:
            quality_list, speed_list = None, None
            self._video_encoder_lock.acquire()
            if self._video_encoder is not None:
                quality_list = [x for _, x in list(self._video_encoder_quality)]
                speed_list = [x for _, x in list(self._video_encoder_speed)]
        finally:
            self._video_encoder_lock.release()
        if quality_list and speed_list:
            add_list_stats(info, prefix+self._video_encoder.get_type()+".quality"+suffix, quality_list, show_percentile=[9])
            add_list_stats(info, prefix+self._video_encoder.get_type()+".speed"+suffix, speed_list, show_percentile=[9])


    def calculate_batch_delay(self):
        calculate_batch_delay(self.window_dimensions, self.wid, self.batch_config, self.global_statistics, self.statistics)

    def update_video_encoder(self):
        if self._video_encoder and not self._video_encoder.is_closed():
            update_video_encoder(self.wid, self.window_dimensions, self.batch_config, self.global_statistics, self.statistics,
                              self._video_encoder, self._video_encoder_lock, self._video_encoder_speed, self._video_encoder_quality,
                              fixed_quality=self.default_encoding_options.get("quality", -1),
                              min_quality=self.default_encoding_options.get("min-quality", -1),
                              fixed_speed=self.default_encoding_options.get("speed", -1),
                              min_speed=self.default_encoding_options.get("min-speed", -1))


    def damage(self, window, x, y, w, h, options={}):
        """ decide what to do with the damage area:
            * send it now (if not congested)
            * add it to an existing delayed region
            * create a new delayed region if we find the client needs it
            Also takes care of updating the batch-delay in case of congestion.
            The options dict is currently used for carrying the
            "quality" and "override_options" values, and potentially others.
            When damage requests are delayed and bundled together,
            specify an option of "override_options"=True to
            force the current options to override the old ones,
            otherwise they are only merged.
        """
        if w==0 or h==0:
            #we may fire damage ourselves,
            #in which case the dimensions may be zero (if so configured by the client)
            return
        now = time.time()
        self.statistics.last_damage_event_time = now
        ww, wh = window.get_dimensions()
        self.window_dimensions = ww, wh

        if self._damage_delayed:
            #use existing delayed region:
            region = self._damage_delayed[2]
            add_rectangle(region, gtk.gdk.Rectangle(x, y, w, h))
            #merge/override options
            if options is not None:
                override = options.get("override_options", False)
                existing_options = self._damage_delayed[4]
                for k,v in options.items():
                    if override or k not in existing_options:
                        existing_options[k] = v
            debug("damage(%s, %s, %s, %s, %s) wid=%s, using existing delayed %s region created %.1fms ago",
                x, y, w, h, options, self.wid, self._damage_delayed[3], now-self._damage_delayed[0])
            return
        elif self.batch_config.delay < self.batch_config.min_delay:
            #work out if we have too many damage requests
            #or too many pixels in those requests
            #for the last time_unit, and if so we force batching on
            event_min_time = now-self.batch_config.time_unit
            all_pixels = [pixels for _,event_time,pixels in self.global_statistics.damage_last_events if event_time>event_min_time]
            eratio = float(len(all_pixels)) / self.batch_config.max_events
            pratio = float(sum(all_pixels)) / self.batch_config.max_pixels
            if eratio>1.0 or pratio>1.0:
                self.batch_config.delay = self.batch_config.min_delay * max(eratio, pratio)

        delay = options.get("delay", self.batch_config.delay)
        delay = max(delay, options.get("min_delay", 0))
        delay = min(delay, options.get("max_delay", self.batch_config.max_delay))
        packets_backlog = self.statistics.get_packets_backlog()
        if packets_backlog==0 and not self.batch_config.always and delay<self.batch_config.min_delay:
            #send without batching:
            debug("damage(%s, %s, %s, %s, %s) wid=%s, sending now with sequence %s", x, y, w, h, options, self.wid, self._sequence)
            actual_encoding = self.get_best_encoding(False, window, w*h, ww, wh, self.encoding)
            if actual_encoding in ("x264", "vpx") or window.is_tray():
                x, y = 0, 0
                w, h = ww, wh
            self.batch_config.last_delays.append((now, delay))
            self.batch_config.last_actual_delays.append((now, delay))
            gobject.idle_add(self.process_damage_region, now, window, x, y, w, h, actual_encoding, options)
            return

        #create a new delayed region:
        region = new_region()
        add_rectangle(region, gtk.gdk.Rectangle(x, y, w, h))
        self._damage_delayed_expired = False
        self._damage_delayed = now, window, region, self.encoding, options or {}
        debug("damage(%s, %s, %s, %s, %s) wid=%s, scheduling batching expiry for sequence %s in %.1f ms", x, y, w, h, options, self.wid, self._sequence, delay)
        self.batch_config.last_delays.append((now, delay))
        self.expire_timer = gobject.timeout_add(int(delay), self.expire_delayed_region)

    def expire_delayed_region(self):
        """ mark the region as expired so damage_packet_acked can send it later,
            and try to send it now.
        """
        self.expire_timer = None
        self._damage_delayed_expired = True
        self.may_send_delayed()
        if self._damage_delayed:
            #NOTE: this should never happen
            #the region has not been sent and it should now get sent
            #when we eventually receive the pending ACKs
            #but if somehow they go missing... try with a timer:
            delayed_region_time = self._damage_delayed[0]
            self.timeout_timer = gobject.timeout_add(self.batch_config.max_delay, self.delayed_region_timeout, delayed_region_time)

    def delayed_region_timeout(self, delayed_region_time):
        if self._damage_delayed:
            region_time = self._damage_delayed[0]
            if region_time==delayed_region_time:
                #same region!
                log.warn("delayed_region_timeout: sending now - something is wrong!")
                self.do_send_delayed_region()
        return False

    def may_send_delayed(self):
        """ send the delayed region for processing if there is no client backlog """
        if not self._damage_delayed:
            debug("window %s delayed region already sent", self.wid)
            return False
        damage_time = self._damage_delayed[0]
        packets_backlog = self.statistics.get_packets_backlog()
        now = time.time()
        actual_delay = 1000.0*(time.time()-damage_time)
        if packets_backlog>0:
            if actual_delay<self.batch_config.max_delay:
                debug("send_delayed for wid %s, delaying again because of backlog: %s packets, batch delay is %s, elapsed time is %.1f ms",
                        self.wid, packets_backlog, self.batch_config.delay, actual_delay)
                #this method will get fired again damage_packet_acked
                return False
            else:
                log.warn("send_delayed for wid %s, elapsed time %.1f is above limit of %.1f - sending now", self.wid, actual_delay, self.batch_config.max_delay)
        else:
            debug("send_delayed for wid %s, batch delay is %.1f, elapsed time is %.1f ms", self.wid, self.batch_config.delay, actual_delay)
        self.batch_config.last_actual_delays.append((now, actual_delay))
        self.do_send_delayed_region()
        return False

    def do_send_delayed_region(self):
        self.cancel_timeout_timer()
        delayed = self._damage_delayed
        self._damage_delayed = None
        self.send_delayed_regions(*delayed)
        return False

    def send_delayed_regions(self, damage_time, window, damage, coding, options):
        """ Called by 'send_delayed' when we expire a delayed region,
            There may be many rectangles within this delayed region,
            so figure out if we want to send them all or if we
            just send one full screen update instead.
        """
        regions = []
        ww,wh = window.get_dimensions()
        def send_full_screen_update():
            actual_encoding = self.get_best_encoding(True, window, ww*wh, ww, wh, coding)
            debug("send_delayed_regions: using full screen update %sx%s with %s", ww, wh, actual_encoding)
            self.process_damage_region(damage_time, window, 0, 0, ww, wh, actual_encoding, options)

        if window.is_tray():
            send_full_screen_update()
            return

        try:
            count_threshold = 60
            pixels_threshold = ww*wh*9/10
            packet_cost = 1024
            if self._mmap and self._mmap_size>0:
                #with mmap, we can move lots of data around easily
                #so favour large screen updates over many small packets
                pixels_threshold = ww*wh/2
                packet_cost = 4096
            pixel_count = 0
            for rect in get_rectangles(damage):
                pixel_count += rect.width*rect.height
                #favor full screen updates over many regions:
                if len(regions)>count_threshold or pixel_count+packet_cost*len(regions)>=pixels_threshold:
                    send_full_screen_update()
                    return
                regions.append((rect.x, rect.y, rect.width, rect.height))
            debug("send_delayed_regions: to regions: %s items, %s pixels", len(regions), pixel_count)
        except Exception, e:
            log.error("send_delayed_regions: error processing region %s: %s", damage, e, exc_info=True)
            return

        actual_encoding = self.get_best_encoding(True, window, pixel_count, ww, wh, coding)
        if actual_encoding in ("x264", "vpx"):
            #use full screen dimensions:
            self.process_damage_region(damage_time, window, 0, 0, ww, wh, actual_encoding, options)
            return

        #we're processing a number of regions with a non video encoding:
        for region in regions:
            x, y, w, h = region
            self.process_damage_region(damage_time, window, x, y, w, h, actual_encoding, options)

    def get_best_encoding(self, batching, window, pixel_count, ww, wh, current_encoding):
        return self.do_get_best_encoding(batching, window.has_alpha(), window.is_tray(), window.is_OR(), pixel_count, ww, wh, current_encoding)

    def do_get_best_encoding(self, batching, has_alpha, is_tray, is_OR, pixel_count, ww, wh, current_encoding):
        """
            decide whether we send a full screen update
            using the video encoder or if a small lossless region(s) is a better choice
        """
        def switch():
            coding = self.find_common_lossless_encoder(current_encoding, ww*wh)
            debug("temporarily switching to %s encoder for %s pixels", coding, pixel_count)
            return  coding
        if has_alpha and current_encoding not in ("png", "rgb32"):
            for x in ("png", "rgb32"):
                if x in self.SERVER_CORE_ENCODINGS and x in self.core_encodings:
                    return x
        if is_tray:
            #tray needs a lossless encoder
            return switch()
        if current_encoding not in ("x264", "vpx"):
            return current_encoding
        max_nvoip = MAX_NONVIDEO_OR_INITIAL_PIXELS
        max_nvp = MAX_NONVIDEO_PIXELS
        if not batching:
            max_nvoip *= 128
            max_nvp *= 128
        if self._sequence==1 and is_OR and pixel_count<max_nvoip:
            #first frame of a small-ish OR window, those are generally short lived
            #so delay using a video encoder until the next frame:
            return switch()
        if current_encoding=="x264":
            #x264 needs sizes divisible by 2:
            ww = ww & 0xFFFE
            wh = wh & 0xFFFE
        if ww<8 or wh<=2:
            #swscale limitation
            return switch()
        if pixel_count<ww*wh*0.01:
            #less than one percent of total area
            return switch()
        if pixel_count>max_nvp:
            #too many pixels, use current video encoder
            return current_encoding
        if pixel_count>0.5*ww*wh and batching:
            #small, but over 50% of the full window
            return current_encoding
        return switch()

    def find_common_lossless_encoder(self, fallback, pixel_count):
        if pixel_count<512:
            encs = "rgb24", "png"
        else:
            encs = "png", "rgb24"
        for e in encs:
            if e in self.SERVER_CORE_ENCODINGS and e in self.core_encodings:
                return e
        return fallback

    def process_damage_region(self, damage_time, window, x, y, w, h, coding, options):
        """
            Called by 'damage' or 'send_delayed_regions' to process a damage region.
            (here we may still generate more than one damage region processing
             to deal with video encoders and odd window sizes)
        """
        self.do_process_damage_region(damage_time, window, x, y, w, h, coding, options)
        if coding in ("vpx", "x264"):
            if w%2==1:
                lossless = self.find_common_lossless_encoder(coding, 1*h)
                self.do_process_damage_region(damage_time, window, x+w-1, y, 1, h, lossless, options)
            if h%2==1:
                lossless = self.find_common_lossless_encoder(coding, w*1)
                self.do_process_damage_region(damage_time, window, x, y+h-1, x+w, 1, lossless, options)

    def do_process_damage_region(self, damage_time, window, x, y, w, h, coding, options):
        """
            Actual damage region processing:
            we extract the rgb data from the pixmap and place it on the damage queue.
            This runs in the UI thread.
        """
        if w==0 or h==0:
            return
        if not window.is_managed():
            debug("the window %s is not composited!?", window)
            return
        # It's important to acknowledge changes *before* we extract them,
        # to avoid a race condition.
        window.acknowledge_changes()

        sequence = self._sequence + 1
        if self.is_cancelled(sequence):
            debug("get_window_pixmap: dropping damage request with sequence=%s", sequence)
            return
        rgb = window.get_rgb_rawdata(x, y, w, h)
        if rgb is None:
            debug("get_window_pixmap: no pixel data for window %s, wid=%s", window, self.wid)
            return
        if self.is_cancelled(sequence):
            return
        px, py, pw, ph, rgb_data, rgb_format, rowstride = rgb
        process_damage_time = time.time()
        data = (damage_time, process_damage_time, self.wid, px, py, pw, ph, coding, rgb_data, rgb_format, rowstride, sequence, options)
        self._sequence += 1
        debug("process_damage_regions: adding pixel data %s to queue, elapsed time: %.1f ms", data[:6], 1000*(time.time()-damage_time))
        def make_data_packet_cb(*args):
            #NOTE: this function is called from the damage data thread!
            packet = self.make_data_packet(*data)
            #NOTE: we have to send it (even if the window is cancelled by now..)
            #because the code may rely on the client having received this frame
            if packet:
                self.queue_damage_packet(packet, damage_time, process_damage_time)
                if self.encoding in ("png", "rgb24"):
                    #primary encoding is lossless, no need for auto-refresh
                    return
                #auto-refresh:
                if window.is_managed() and self.auto_refresh_delay>0 and not self.is_cancelled(sequence):
                    client_options = packet[10]     #info about this packet from the encoder
                    gobject.idle_add(self.schedule_auto_refresh, window, w, h, coding, options, client_options)
        self.queue_damage(make_data_packet_cb)

    def schedule_auto_refresh(self, window, w, h, coding, damage_options, client_options):
        """ Must be called from the UI thread: this makes it easier
            to prevent races, and we can call window.get_dimensions() safely
        """
        #NOTE: there is a small potential race here:
        #if the damage packet queue is congested, new damage requests could come in,
        #in between the time we schedule the new refresh timer and the time it fires,
        #and if not batching,
        #we would then do a full_quality_refresh when we should not...
        actual_quality = client_options.get("quality")
        if actual_quality is None:
            debug("schedule_auto_refresh: was a lossless %s packet, ignoring", coding)
            #lossless already: small region sent lossless or encoding is lossless
            #don't change anything: if we have a timer, keep it
            return
        if not window.is_managed():
            return
        ww, wh = window.get_dimensions()
        if actual_quality>=AUTO_REFRESH_THRESHOLD and w*h>=ww*wh:
            debug("schedule_auto_refresh: high quality (%s%%) full frame (%s pixels), cancelling refresh timer %s", actual_quality, w*h, self.refresh_timer)
            #got enough pixels at high quality, cancel timer:
            self.cancel_refresh_timer()
            return
        def full_quality_refresh():
            debug("full_quality_refresh() for %sx%s window", w, h)
            if self._damage_delayed:
                #there is already a new damage region pending
                return  False
            if not window.is_managed():
                #this window is no longer managed
                return  False
            self.refresh_timer = None
            new_options = damage_options.copy()
            if AUTO_REFRESH_ENCODING:
                new_options["encoding"] = AUTO_REFRESH_ENCODING
            #FIXME: with x264, the quality must be higher than the YUV444 threshold
            new_options["quality"] = AUTO_REFRESH_QUALITY
            new_options["speed"] = AUTO_REFRESH_SPEED
            debug("full_quality_refresh() with options=%s", new_options)
            self.damage(window, 0, 0, ww, wh, options=new_options)
            return False
            #self.process_damage_region(time.time(), window, 0, 0, ww, wh, coding, new_options)
        self.cancel_refresh_timer()
        if self._damage_delayed:
            debug("auto refresh: delayed region already exists")
            #there is already a new damage region pending, let it re-schedule when it gets sent
            return
        delay = int(max(50, self.auto_refresh_delay, self.batch_config.delay*4))
        debug("schedule_auto_refresh: low quality (%s%%) with %s pixels, (re)scheduling auto refresh timer with delay %s", actual_quality, w*h, delay)
        self.refresh_timer = gobject.timeout_add(delay, full_quality_refresh)

    def queue_damage_packet(self, packet, damage_time, process_damage_time):
        """
            Adds the given packet to the damage_packet_queue,
            (warning: this runs from the non-UI thread 'data_to_packet')
            we also record a number of statistics:
            - damage packet queue size
            - number of pixels in damage packet queue
            - damage latency (via a callback once the packet is actually sent)
        """
        #packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, rowstride, client_options]
        width = packet[4]
        height = packet[5]
        damage_packet_sequence = packet[8]
        actual_batch_delay = process_damage_time-damage_time
        def start_send(bytecount):
            now = time.time()
            self.statistics.damage_ack_pending[damage_packet_sequence] = [now, bytecount, 0, 0, width*height]
        def damage_packet_sent(bytecount):
            now = time.time()
            stats = self.statistics.damage_ack_pending.get(damage_packet_sequence)
            #if we timed it out, it may be gone already:
            if stats:
                stats[2] = now
                stats[3] = bytecount
                damage_out_latency = now-process_damage_time
                self.statistics.damage_out_latency.append((now, width*height, actual_batch_delay, damage_out_latency))
        now = time.time()
        damage_in_latency = now-process_damage_time
        self.statistics.damage_in_latency.append((now, width*height, actual_batch_delay, damage_in_latency))
        self.queue_packet(packet, self.wid, width*height, start_send, damage_packet_sent)

    def damage_packet_acked(self, damage_packet_sequence, width, height, decode_time):
        """
            The client is acknowledging a damage packet,
            we record the 'client decode time' (provided by the client itself)
            and the "client latency".
        """
        debug("packet decoding sequence %s for window %s %sx%s took %s µs", damage_packet_sequence, self.wid, width, height, decode_time)
        if decode_time>0:
            self.statistics.client_decode_time.append((time.time(), width*height, decode_time))
        pending = self.statistics.damage_ack_pending.get(damage_packet_sequence)
        if pending is None:
            debug("cannot find sent time for sequence %s", damage_packet_sequence)
            return
        del self.statistics.damage_ack_pending[damage_packet_sequence]
        if decode_time:
            start_send_at, start_bytes, end_send_at, end_bytes, pixels = pending
            bytecount = end_bytes-start_bytes
            self.global_statistics.record_latency(self.wid, decode_time, start_send_at, end_send_at, pixels, bytecount)
        else:
            #something failed client-side, so we can't rely on the delta being available
            self.last_pixmap_data = None
        if self._damage_delayed is not None and self._damage_delayed_expired:
            gobject.idle_add(self.may_send_delayed)

    def make_data_packet(self, damage_time, process_damage_time, wid, x, y, w, h, coding, rgbdata, rgb_format, rowstride, sequence, options):
        """
            Picture encoding - non-UI thread.
            Converts a damage item picked from the 'damage_data_queue'
            by the 'data_to_packet' thread and returns a packet
            ready for sending by the network layer.

            * 'mmap' will use 'mmap_send' - always if available, otherwise:
            * 'jpeg' and 'png' are handled by 'PIL_encode'.
            * 'webp' uses 'webp_encode'
            * 'x264' and 'vpx' use 'video_encode'
            * 'rgb24' uses 'rgb24_encode' and the 'Compressed' wrapper to tell the network layer it is already zlibbed
        """
        if self.is_cancelled(sequence):
            debug("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        assert w>0 and h>0, "invalid dimensions: %sx%s" % (w, h)
        assert rgbdata, "data is missing"
        debug("make_data_packet: damage data: %s", (wid, x, y, w, h, coding))
        start = time.time()
        if self._mmap and self._mmap_size>0 and len(rgbdata)>256 and rgb_format=="RGB":
            #try with mmap (will change coding to "mmap" if it succeeds)
            coding, data = self.mmap_send(coding, rgbdata)
        else:
            data = rgbdata
        #if client supports delta pre-compression for this encoding, use it if we can:
        delta = -1
        if coding in self.supports_delta and self.last_pixmap_data is not None:
            lw, lh, lcoding, lsequence, ldata = self.last_pixmap_data
            if lw==w and lh==h and lcoding==coding and len(ldata)==len(rgbdata):
                #xor with the last frame:
                delta = lsequence
                data = xor_str(rgbdata, ldata)

        if rgb_format.upper()!="RGB" and rgb_format.upper()!="RGBX":
            assert rgb_format.upper()=="RGBA", "invalid rgb format: %s" % rgb_format
            assert coding in ("rgb32", "png", ), "invalid encoding for %s: %s" % (rgb_format, coding)

        #by default, don't set rowstride (the container format will take care of providing it):
        outstride = 0
        if coding in ("jpeg", "png"):
            data, client_options = self.PIL_encode(w, h, coding, data, rgb_format, rowstride, options)
        elif coding=="x264":
            #x264 needs sizes divisible by 2:
            w = w & 0xFFFE
            h = h & 0xFFFE
            assert w>0 and h>0
            data, client_options = self.video_encode(wid, x, y, w, h, coding, data, rowstride, options)
        elif coding=="vpx":
            data, client_options = self.video_encode(wid, x, y, w, h, coding, data, rowstride, options)
        elif coding=="rgb24" or coding=="rgb32":
            data, client_options = self.rgb_encode(coding, data)
            outstride = rowstride
        elif coding=="webp":
            data, client_options = self.webp_encode(w, h, data, rowstride, options)
        elif coding=="mmap":
            client_options = {}  #actual sending is already handled via mmap_send above
            outstride = rowstride
        else:
            raise Exception("invalid encoding: %s" % coding)
        #check cancellation list again since the code above may take some time:
        #but always send mmap data so we can reclaim the space!
        if coding!="mmap" and self.is_cancelled(sequence):
            debug("make_data_packet: dropping data packet for window %s with sequence=%s", wid, sequence)
            return  None
        #tell client about delta/store for this pixmap:
        if delta>=0:
            client_options["delta"] = delta
        if coding in self.supports_delta:
            self.last_pixmap_data = w, h, coding, sequence, rgbdata
            client_options["store"] = sequence
        #actual network packet:
        packet = ["draw", wid, x, y, w, h, coding, data, self._damage_packet_sequence, outstride, client_options]
        end = time.time()
        #debug("%sms to compress %sx%s pixels using %s with ratio=%s%%, delta=%s",
        #         dec1(end*1000.0-start*1000.0), w, h, coding, dec1(100.0*len(data)/len(rgbdata)), delta)
        self._damage_packet_sequence += 1
        self.statistics.encoding_stats.append((coding, w*h, len(data), end-start))
        #record number of frames and pixels:
        totals = self.statistics.encoding_totals.setdefault(coding, [0, 0])
        totals[0] = totals[0] + 1
        totals[1] = totals[1] + w*h
        self._last_sequence_queued = sequence
        #debug("make_data_packet: returning packet=%s,[..],%s", packet[:7], packet[8:])
        return packet

    def webp_encode(self, w, h, data, rowstride, options):
        from xpra.codecs.webm.encode import EncodeRGB
        from xpra.codecs.webm.handlers import BitmapHandler
        image = BitmapHandler(data, BitmapHandler.RGB, w, h, rowstride)
        q = 80
        if options:
            q = options.get("quality", 80)
        q = min(99, max(1, q))
        return Compressed("webp", str(EncodeRGB(image, quality=q).data)), {"quality" : q}

    def rgb_encode(self, coding, data):
        #compress here and return a wrapper so network code knows it is already zlib compressed:
        zlib = zlib_compress(coding, data)
        if not self.encoding_client_options or not self.supports_rgb24zlib:
            return  zlib, {}
        #wrap it using "Compressed" so the network layer receiving it
        #won't decompress it (leave it to the client's draw thread)
        return Compressed(coding, zlib.data), {"zlib" : zlib.level}

    def PIL_encode(self, w, h, coding, data, rgb_format, rowstride, options):
        assert coding in self.SERVER_CORE_ENCODINGS
        import Image
        im = Image.fromstring(rgb_format, (w, h), data, "raw", rgb_format, rowstride)
        buf = StringIOClass()
        client_options = {}
        if coding=="jpeg":
            q = 80
            if options:
                q = options.get("quality", 80)
            q = min(99, max(1, q))
            debug("sending with jpeg quality %s", q)
            im.save(buf, "JPEG", quality=q)
            client_options["quality"] = q
        else:
            assert coding=="png"
            debug("sending as %s, mode=%s", coding, im.mode)
            #transparency = False
            #transparency=transparency
            im.save(buf, coding.upper())
        data = buf.getvalue()
        buf.close()
        return Compressed(coding, data), client_options

    def make_video_encoder(self, coding):
        assert coding in self.SERVER_CORE_ENCODINGS
        if coding=="x264":
            from xpra.codecs.x264.encoder import Encoder as x264Encoder   #@UnresolvedImport
            return x264Encoder()
        elif coding=="vpx":
            from xpra.codecs.vpx.encoder import Encoder as vpxEncoder     #@UnresolvedImport
            return vpxEncoder()
        else:
            raise Exception("invalid video encoder: %s" % coding)

    def video_encode(self, wid, x, y, w, h, coding, data, rowstride, options):
        """
            This method is used by make_data_packet to encode frames using x264 or vpx.
            Video encoders only deal with fixed dimensions,
            so we must clean and reinitialize the encoder if the window dimensions
            has changed.
            Since this runs in the non-UI thread 'data_to_packet', we must
            use the 'video_encoder_lock' to prevent races.
        """
        assert x==0 and y==0, "invalid position: %s,%s" % (x,y)
        #time_before = time.clock()
        try:
            self._video_encoder_lock.acquire()
            if self._video_encoder:
                if self._video_encoder.get_type()!=coding:
                    debug("video_encode: switching from %s to %s", self._video_encoder.get_type(), coding)
                    self.do_video_encoder_cleanup()
                elif self._video_encoder.get_width()!=w or self._video_encoder.get_height()!=h:
                    debug("%s: window dimensions have changed from %sx%s to %sx%s", coding, self._video_encoder.get_width(), self._video_encoder.get_height(), w, h)
                    old_pc = self._video_encoder.get_width() * self._video_encoder.get_height()
                    self._video_encoder.clean()
                    self._video_encoder.init_context(w, h, self.encoding_options)
                    #if we had an encoding speed set, restore it (also scaled):
                    if len(self._video_encoder_speed):
                        _, recent_speed = calculate_time_weighted_average(list(self._video_encoder_speed))
                        new_pc = w * h
                        new_speed = max(0, min(100, recent_speed*new_pc/old_pc))
                        self._video_encoder.set_encoding_speed(new_speed)
            if self._video_encoder is None:
                debug("%s: new encoder for wid=%s %sx%s", coding, wid, w, h)
                self._video_encoder = self.make_video_encoder(coding)
                self._video_encoder.init_context(w, h, self.encoding_options)
            data, client_options = self._video_encoder.compress_image(data, rowstride, options)
            if data is None:
                log.error("%s: ouch, compression failed", coding)
                return None, None
            debug("compress_image(..) %s wid=%s, result is %s bytes, client options=%s", coding, wid, len(data), client_options)
            return Compressed(coding, data), client_options
        finally:
            self._video_encoder_lock.release()

    def mmap_send(self, coding, data):
        from xpra.net.mmap_pipe import mmap_write
        start = time.time()
        mmap_data, mmap_free_size = mmap_write(self._mmap, self._mmap_size, data)
        self.global_statistics.mmap_free_size = mmap_free_size
        elapsed = time.time()-start+0.000000001 #make sure never zero!
        debug("%s MBytes/s - %s bytes written to mmap in %.1f ms", int(len(data)/elapsed/1024/1024), len(data), 1000*elapsed)
        if mmap_data is not None:
            self.global_statistics.mmap_bytes_sent += len(data)
            coding = "mmap"
            data = mmap_data
        return coding, data
