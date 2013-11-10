# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


BGRA2YUV444P_kernel = """
#include <stdint.h>

__global__ void BGRA2YUV444P(uint8_t *srcImage,    int srcPitch,
                             uint8_t *yuvImage,    int dstPitch, int dstHeight,
                             int w,                int h)
{
    uint32_t gx, gy;
    gx = blockIdx.x * blockDim.x + threadIdx.x;
    gy = blockIdx.y * blockDim.y + threadIdx.y;

    if ((gx < w) & (gy < h)) {
        //one 32-bit RGB pixel at a time:
        uint8_t R;
        uint8_t G;
        uint8_t B;
        uint32_t si = (gy * srcPitch) + gx * 4;
        R = srcImage[si+2];
        G = srcImage[si+1];
        B = srcImage[si];

        uint32_t di;
        di = (gy * dstPitch) + gx;
        yuvImage[di] = __float2int_rn(0.257 * R + 0.504 * G + 0.098 * B + 16);
        di += dstPitch*dstHeight;
        yuvImage[di] = __float2int_rn(-0.148 * R - 0.291 * G + 0.439 * B + 128);
        di += dstPitch*dstHeight;
        yuvImage[di] = __float2int_rn(0.439 * R - 0.368 * G - 0.071 * B + 128);
    }
}
"""