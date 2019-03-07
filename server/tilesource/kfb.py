#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import math
import six

from six.moves import range

import openslide
import PIL

from ctypes import *

from .base import FileTileSource, TileSourceException
from ..cache_util import LruCacheMetaclass, methodcache

import sys

#--------------------------------------------------------------------------------
# for general compuation
import numpy as np
import skimage.io
from girder.models.file import File
from bson.objectid import ObjectId   

#--------------------------------------------------------------------------------
# For importing local modules
import sys
import stat 
import shutil
#------------------------------
# For open slide files
import os
import os.path
import traceback

sys.path.append("/opt/histomicstk/pvWeb/src/cython/r")
#sys.path.append("/home/ken/usr/work/pvWeb/src/cython/r/")
import pCythonInterface as mmHandler

try:
    import girder
    from girder import logger
    from .base import GirderTileSource
except ImportError:
    girder = None
    import logging as logger
    logger.getLogger().setLevel(logger.INFO)


def _nearPowerOfTwo(val1, val2, tolerance=0.02):
    """
    Check if two values are different by nearly a power of two.

    :param val1: the first value to check.
    :param val2: the second value to check.
    :param tolerance: the maximum difference in the log2 ratio's mantissa.
    :return: True if the valeus are nearly a power of two different from each
        other; false otherwise.
    """
    # If one or more of the values is zero or they have different signs, then
    # return False
    if val1 * val2 <= 0:
        return False
    log2ratio = math.log(float(val1) / float(val2)) / math.log(2)
    # Compare the mantissa of the ratio's log2 value.
    return abs(log2ratio - round(log2ratio)) < tolerance


@six.add_metaclass(LruCacheMetaclass)
class KFBFileTileSource(FileTileSource):
    """
    Provides tile access to KFB files.
    """
    cacheName = 'tilesource'
    name = 'kfbfile'
    exten = ''
    kfbFileName =''
    slideSizeX = 0 
    slideSizeY = 0
    scanScale = 0
    imageCapRes = 0
    imageBlockSiz = 0
    def __init__(self, path, **kwargs):
        """
        Initialize the tile class.

        :param path: the associated file path.
        """
        super(KFBFileTileSource, self).__init__(path, **kwargs)

        largeImagePath = self._getLargeImagePath()
        kfbFileName = largeImagePath
        logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:path=' + str(path))
        logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:largeImagePath=' + str(largeImagePath))

        try:
            fileName=str(self.largeImagePath.get("lowerName"))
            self.exten=fileName[-3:]
            logger.info('(#####)large_image/server/tilesource/kfb.py-__init__:exten =' + str(self.exten))
#             if self.exten != "kfb": # NOT kfb file
            largeImagePath="/home/ken/Documents/sample_images/TCGA-02-0010-01Z-00-DX4.07de2e55-a8fe-40ee-9e98-bcb78050b9f7.svs"
#             if False: # NOT kfb file
#                 self._openslide = openslide.OpenSlide(largeImagePath)
#                 
#                 kfbAvailableLevels = self._getAvailableLevels(largeImagePath)
#                 logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:kfbAvailableLevels=' + str(kfbAvailableLevels))
#                 if not len(kfbAvailableLevels):
#                     raise TileSourceException('OpenSlide image size is invalid.')
#                 self.sizeX = kfbAvailableLevels[0]['width']
#                 self.sizeY = kfbAvailableLevels[0]['height']
#                 logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:self.sizeX=' + str(self.sizeX))
#                 logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:self.sizeY=' + str(self.sizeY))
#                 if (self.sizeX != self._openslide.dimensions[0] or
#                         self.sizeY != self._openslide.dimensions[1]):
#                     msg = ('OpenSlide reports a dimension of %d x %d, but base layer '
#                            'has a dimension of %d x %d -- using base layer\'s '
#                            'dimensions.' % (
#                                self._openslide.dimensions[0],
#                                self._openslide.dimensions[1], self.sizeX, self.sizeY))
#                     logger.info(msg)
#         
# #                 self._getTileSize()
#                 self.tileWidth = 240
#                 self.tileHeight = 240
# 
# #                 self.levels = int(math.ceil(max(
# #                     math.log(float(self.sizeX) / self.tileWidth),
# #                     math.log(float(self.sizeY) / self.tileHeight)) / math.log(2))) + 1
#                 logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:self.levels=' + str(self.levels))
#                 if self.levels < 1:
#                     raise TileSourceException(
#                         'OpenSlide image must have at least one level.')
#                 self._kfblevels = []
#                 # Precompute which KFB level should be used for our tile levels.  KFB
#                 # level 0 is the maximum resolution.  The KFB levels are in descending
#                 # resolution and, we assume, are powers of two in scale.  For each of
#                 # our levels (where 0 is the minimum resolution), find the lowest
#                 # resolution KFB level that contains at least as many pixels.  If this
#                 # is not the same scale as we expect, note the scale factor so we can
#                 # load an appropriate area and scale it to the tile size later.
#                 maxSize = 16384  # This should probably be based on available memory
#                 for level in range(self.levels):
#                     levelW = max(1, self.sizeX / 2 ** (self.levels - 1 - level))
#                     levelH = max(1, self.sizeY / 2 ** (self.levels - 1 - level))
#                     # bestlevel and scale will be the picked kfb level and the scale
#                     # between that level and what we really wanted.  We expect scale to
#                     # always be a positive integer power of two.
#                     bestlevel = kfbAvailableLevels[0]['level']
#                     scale = 1
#                     for kfblevel in range(len(kfbAvailableLevels)):
#                         if (kfbAvailableLevels[kfblevel]['width'] < levelW - 1 or
#                                 kfbAvailableLevels[kfblevel]['height'] < levelH - 1):
#                             break
#                         bestlevel = kfbAvailableLevels[kfblevel]['level']
#                         scale = int(round(kfbAvailableLevels[kfblevel]['width'] / levelW))
#                     # If there are no tiles at a particular level, we have to read a
#                     # larger area of a higher resolution level.  If such an area would
#                     # be excessively large, we could have memroy issues, so raise an
#                     # error.
#                     if (self.tileWidth * scale > maxSize or
#                             self.tileHeight * scale > maxSize):
#                         msg = ('OpenSlide has no small-scale tiles (level %d is at %d '
#                                'scale)' % (level, scale))
#                         logger.info(msg)
#                         raise TileSourceException(msg)
#                     self._kfblevels.append({
#                         'kfblevel': bestlevel,
#                         'scale': scale
#                     })
#                 logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:self._kfblevels=' + str(self._kfblevels))
#             else: # kfb file
            logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:kfb')
            
            id = self.largeImagePath['largeImage']['fileId']                              
            file = File().findOne({'_id': ObjectId(id)})
            fileName=str(os.path.join("/opt/histomicstk/assetstore", file["path"]))
            kfbFileName_temp=str(os.path.join("/opt/histomicstk/assetstore", file["path"][0:5], "temp.kfb"))
            shutil.copyfile(fileName, kfbFileName_temp)
            os.chmod(kfbFileName_temp, stat.S_IRWXU |  stat.S_IRWXG |  stat.S_IRWXO)
            self.slideSizeX, self.slideSizeY, self.scanScale, spendTime, scanTime, self.imageCapRes, self.imageBlockSiz = mmHandler.getSlideInfo(kfbFileName_temp)
#             kfbAvailableLevels = [{'width': round(slideSizeX/(scanScale/40)),   'height': round(slideSizeY/(scanScale/40)),   'level': 0}, # scale=40x 
#                                   {'width': round(slideSizeX/(scanScale/20)),   'height': round(slideSizeY/(scanScale/20)),   'level': 1}, # scale=20x
#                                   {'width': round(slideSizeX/(scanScale/10)),   'height': round(slideSizeY/(scanScale/10)),   'level': 2}, # scale=10x
#                                   {'width': round(slideSizeX/(scanScale/5)),    'height': round(slideSizeY/(scanScale/5)),    'level': 3}, # scale=5x
#                                   {'width': round(slideSizeX/(scanScale/2.5)),  'height': round(slideSizeY/(scanScale/2.5)),  'level': 4}, # scale=3x
#                                   {'width': round(slideSizeX/(scanScale/(0.6))),'height': round(slideSizeY/(scanScale/(0.6))),'level': 5}] # scale=1x
#             kfbAvailableLevels = self._getAvailableLevels(kfbFileName_temp)            
            kfbAvailableLevels = svsAvailableLevels=[{'width': self.slideSizeX,   'height': self.slideSizeY, 'level': 0}]
            logger.info('(#####)large_image/server/tilesource/kfb.py:__init__(kfb):kfbAvailableLevels=' + str(kfbAvailableLevels))
            if not len(kfbAvailableLevels):
                raise TileSourceException('OpenSlide image size is invalid.')
            self.sizeX = kfbAvailableLevels[0]['width']
            self.sizeY = kfbAvailableLevels[0]['height']

            self.tileWidth = self.imageBlockSiz
            self.tileHeight = self.imageBlockSiz

            self.levels = int(math.ceil(max(
                math.log(float(self.sizeX) / self.tileWidth),
                math.log(float(self.sizeY) / self.tileHeight)) / math.log(2))) + 1
            logger.info('(#####)large_image/server/tilesource/kfb.py:__init__(kfb):self.levels=' + str(self.levels))
#                 if (self.sizeX != self._openslide.dimensions[0] or
#                         self.sizeY != self._openslide.dimensions[1]):
#                     msg = ('OpenSlide reports a dimension of %d x %d, but base layer '
#                            'has a dimension of %d x %d -- using base layer\'s '
#                            'dimensions.' % (
#                                self._openslide.dimensions[0],
#                                self._openslide.dimensions[1], self.sizeX, self.sizeY))
#                     logger.info(msg)        
            if self.levels < 1:
                raise TileSourceException(
                    'OpenSlide image must have at least one level.')
            self._kfblevels = []
            # Precompute which KFB level should be used for our tile levels.  KFB
            # level 0 is the maximum resolution.  The KFB levels are in descending
            # resolution and, we assume, are powers of two in scale.  For each of
            # our levels (where 0 is the minimum resolution), find the lowest
            # resolution KFB level that contains at least as many pixels.  If this
            # is not the same scale as we expect, note the scale factor so we can
            # load an appropriate area and scale it to the tile size later.
            maxSize = 16384*100  # This should probably be based on available memory
            for level in range(self.levels):
                levelW = max(1, self.sizeX / 2 ** (self.levels - 1 - level))
                levelH = max(1, self.sizeY / 2 ** (self.levels - 1 - level))
                # bestlevel and scale will be the picked kfb level and the scale
                # between that level and what we really wanted.  We expect scale to
                # always be a positive integer power of two.
                bestlevel = kfbAvailableLevels[0]['level']
                scale = 1
                for kfblevel in range(len(kfbAvailableLevels)):
                    if (kfbAvailableLevels[kfblevel]['width'] < levelW - 1 or
                            kfbAvailableLevels[kfblevel]['height'] < levelH - 1):
                        break
                    bestlevel = kfbAvailableLevels[kfblevel]['level']
                    scale = int(round(kfbAvailableLevels[kfblevel]['width'] / levelW))
                # If there are no tiles at a particular level, we have to read a
                # larger area of a higher resolution level.  If such an area would
                # be excessively large, we could have memroy issues, so raise an
                # error.
                    if (self.tileWidth * scale > maxSize or
                            self.tileHeight * scale > maxSize):
                        msg = ('SDK has no small-scale tiles (level %d is at %d '
                               'scale)' % (level, scale))
                        logger.info(msg)
                        raise TileSourceException(msg)
                self._kfblevels.append({
                    'kfblevel': bestlevel,
                    'scale': 1
                })
            logger.info('(#####)large_image/server/tilesource/kfb.py:__init__:self._kfblevels=' + str(self._kfblevels))
        except openslide.lowlevel.OpenSlideUnsupportedFormatError:
            raise TileSourceException('File cannot be opened via OpenSlide.')

    def _getTileSize(self):
        """
        Get the tile size.  The tile size isn't in the official openslide
        interface documentation, but every example has the tile size in the
        properties.  If the tile size has an excessive aspect ratio or isn't
        set, fall back to a default of 256 x 256.  The read_region function
        abstracts reading the tiles, so this may be less efficient, but will
        still work.
        """
        # Try to read it, but fall back to 256 if it isn't set.
        width = height = 256
        try:
            width = int(self._openslide.properties[
                'openslide.level[0].tile-width'])
        except (ValueError, KeyError):
            pass
        try:
            height = int(self._openslide.properties[
                'openslide.level[0].tile-height'])
        except (ValueError, KeyError):
            pass
        # If the tile size is too small (<4) or wrong (<=0), use a default value
        if width < 4:
            width = 256
        if height < 4:
            height = 256
        # If the tile has an excessive aspect ratio, use default values
        if max(width, height) / min(width, height) >= 4:
            width = height = 256
        # Don't let tiles be bigger than the whole image.
        self.tileWidth = min(width, self.sizeX)
        self.tileHeight = min(height, self.sizeY)
        logger.info('(#####)large_image/server/tilesource/kfb.py:_getTileSize:self.tileWidth=' + str(self.tileWidth))
        logger.info('(#####)large_image/server/tilesource/kfb.py:_getTileSize:self.tileHeight=' + str(self.tileHeight))

    def _getAvailableLevels(self, path):
        """
        Some KFB files (notably some NDPI variants) have levels that cannot be
        read.  Get a list of levels, check that each is at least potentially
        readable, and return a list of these sorted highest-resolution first.

        :param path: the path of the KFB file.  After a failure, the file is
            reopened to reset the error state.
        :returns: levels.  A list of valid levels, each of which is a
            dictionary of level (the internal 0-based level number), width, and
            height.
        """
        levels = []
        kfbLevelDimensions = self._openslide.level_dimensions
        logger.info('(#####)large_image/server/tilesource/kfb.py:_getAvailableLevels:kfbLevelDimensions=' + str(kfbLevelDimensions))
        for kfblevel in range(len(kfbLevelDimensions)):
            try:
                self._openslide.read_region((0, 0), kfblevel, (1, 1))
                level = {
                    'level': kfblevel,
                    'width': kfbLevelDimensions[kfblevel][0],
                    'height': kfbLevelDimensions[kfblevel][1],
                }
                if level['width'] > 0 and level['height'] > 0:
                    # add to the list so that we can sort by resolution
                    levels.append((level['width'] * level['height'], level))
            except openslide.lowlevel.OpenSlideError:
                self._openslide = openslide.OpenSlide(path)
        # sort highest resolution first.
        levels = [entry[-1] for entry in sorted(levels, reverse=True)]
        # Discard levels that are not a power-of-two compared to the highest
        # resolution level.
        logger.info('(#####)large_image/server/tilesource/kfb.py:_getAvailableLevels:levels=' + str(levels))
        levels = [entry for entry in levels if
                  _nearPowerOfTwo(levels[0]['width'], entry['width']) and
                  _nearPowerOfTwo(levels[0]['height'], entry['height'])]
        return levels

    def getNativeMagnification(self):
        """
        Get the magnification at a particular level.

        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
#         traceback.print_stack()
#         if self.exten != "kfb":
#             logger.info('(#####)large_image/server/tilesource/kfb.py:getNativeMagnification:No-KFB' )
#             try:
#                 mag = self._openslide.properties[
#                     openslide.PROPERTY_NAME_OBJECTIVE_POWER]
#                 mag = float(mag) if mag else None
#             except (KeyError, ValueError):
#                 mag = None
#             try:
#                 mm_x = float(self._openslide.properties[
#                     openslide.PROPERTY_NAME_MPP_X]) * 0.001
#                 mm_y = float(self._openslide.properties[
#                     openslide.PROPERTY_NAME_MPP_Y]) * 0.001
#             except Exception:
#                 mm_x = mm_y = None
#             # Estimate the magnification if we don't have a direct value
#             if mag is None and mm_x is not None:
#                 mag = 0.01 / mm_x
#         else: # kfb file
        logger.info('(#####)large_image/server/tilesource/kfb.py:getNativeMagnification:kfb' )
        mag=self.scanScale
        mm_x=self.imageCapRes * 0.001
        mm_y=self.imageCapRes * 0.001
            
        logger.info('(#####)large_image/server/tilesource/kfb.py:getNativeMagnification:mag=' + str(mag))
        logger.info('(#####)large_image/server/tilesource/kfb.py:getNativeMagnification:mm_x=' + str(mm_x))
        logger.info('(#####)large_image/server/tilesource/kfb.py:getNativeMagnification:mm_y=' + str(mm_y))
        return {
            'magnification': mag,
            'mm_x': mm_x,
            'mm_y': mm_y,
        }
         

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, **kwargs):
#         traceback.print_stack()
#         logger.info('(#####)large_image/server/tilesource/kfb.py:getTile:(x, y, z)=' + str(x) + "," + str(y) + "," + str(z))
#         fileName=str(self.largeImagePath.get("lowerName"))
#         self.exten=fileName[-3:]
        if z < 0:
            raise TileSourceException('z layer does not exist')
        try:
            kfblevel = self._kfblevels[z]
#             logger.info('(#####)large_image/server/tilesource/kfb.py:getTile():kfblevel=' + str(kfblevel))
        except IndexError:
            raise TileSourceException('z layer does not exist')
        # When we read a region from the KFB, we have to ask for it in the
        # KFB level 0 coordinate system.  Our x and y is in tile space at the
        # specifed z level, so the offset in KFB level 0 coordinates has to be
        # scaled by the tile size and by the z level.

#         scale = 2 ** (self.levels - 1 - z)
        scale = 2 ** (self.levels - 1 - z)
        scale =1;
        offsetx = x * self.tileWidth * scale
        if not (0 <= offsetx < self.sizeX):
            raise TileSourceException('x is outside layer')
        offsety = y * self.tileHeight * scale
        if not (0 <= offsety < self.sizeY):
            raise TileSourceException('y is outside layer')
        # We ask to read an area that will cover the tile at the z level.  The
        # scale we computed in the __init__ process for this kfb level tells
        # how much larger a region we need to read.
#         offsetx = 0;
#         offsety = 0;
        try:
            tile = PIL.Image.new("RGB", (self.tileWidth * kfblevel['scale'], self.tileHeight * kfblevel['scale']), 'blue')
    
            id = self.largeImagePath['largeImage']['fileId']                              
            file = File().findOne({'_id': ObjectId(id)})
            kfbFileName_temp=str(os.path.join("/opt/histomicstk/assetstore", file["path"][0:5], "temp.kfb"))
            logger.info('(#####)large_image/server/tilesource/kfb-getTile:kfbFileName_temp='+(kfbFileName_temp))
            self.slideSizeX, self.slideSizeY, self.scanScale, spendTime, scanTime, self.imageCapRes, self.imageBlockSiz = mmHandler.getSlideInfo(kfbFileName_temp)
            logger.info('(#####)KFB getSlideInfo =' + str(self.slideSizeX) + ", " + str(self.slideSizeY) + ", " + str(self.scanScale) + " "+ str(self.imageCapRes) + ', ' + str(self.imageBlockSiz))

            level2scaleHash = dict((('0', 0.078125),('1', 0.15625),('2', 0.3125),('3', 0.625),('4', 1.25),('5', 2.5),('6', 5), ('7',10), ('8',20),('9',40)))
            kfbScale = level2scaleHash[str(z)]

            offsetx = x * self.tileWidth * scale
            if not (0 <= offsetx < int(self.slideSizeX/(self.scanScale/kfbScale))):
                raise TileSourceException('x is outside layer')
            offsety = y * self.tileHeight * scale
            if not (0 <= offsety < int(self.slideSizeY/(self.scanScale/kfbScale))):
                raise TileSourceException('y is outside layer')
#             level = kfblevel['kfblevel']
#             szX = self.tileWidth * kfblevel['scale']
#             szY = self.tileHeight * kfblevel['scale']
#             szX = int(slideSizeX/(scanScale/kfbScale))
#             szY = int(slideSizeY/(scanScale/kfbScale))
            szX = self.tileWidth
            szY = self.tileWidth

            iii = np.zeros([szY, szX, 3], dtype=np.uint8)
#             logger.info('(#####)large_image/server/tilesource/kfb.py-getTile:level='+str(level))

            logger.info('(#####)KFB (x, y, z) offsetx, offsety, kfbScale, szX, szY, kfblevel = (' + str(x) + "," + str(y) + "," + str(z) + ")"+ str(offsetx) + ', ' + str(offsety) + ", " + str(kfbScale) + ", " + str(szX) + ", " + str(szY) + str(kfblevel))
            mmHandler.extractKFSlideRegionToUcharArray(kfbFileName_temp, offsetx, offsety, kfbScale, szX, szY, iii)        

            tile = PIL.Image.fromarray(iii.astype('uint8'), 'RGB')
            logger.info('(#####)KFB (x, y, z), iii, tile.getpixel result= (' + str(x) + "," + str(y) + "," + str(z) + ") "+ str(iii[0, 0, 0]) + ', ' + str(tile.getpixel((0, 0))))
#             logger.info(iii[0, 0, 0])
#             logger.info(tile.getpixel((0, 0)))

        except openslide.lowlevel.OpenSlideError as exc:
            raise TileSourceException(
                'Failed to get OpenSlide region (%r).' % exc)
        # Always scale to the kfb level 0 tile size.
        if kfblevel['scale'] != 1:
            tile = tile.resize((self.tileWidth, self.tileHeight),
                               PIL.Image.LANCZOS)
        logger.info('(#####)large_image/server/tilesource/kfb.py:getTile:tile=' + str(tile))
        return self._outputTile(tile, 'PIL', x, y, z, pilImageAllowed, **kwargs)

    def getPreferredLevel(self, level):
        """
        Given a desired level (0 is minimum resolution, self.levels - 1 is max
        resolution), return the level that contains actual data that is no
        lower resolution.

        :param level: desired level
        :returns level: a level with actual data that is no lower resolution.
        """
        level = max(0, min(level, self.levels - 1))
        scale = self._kfblevels[level]['scale']
        while scale > 1:
            level += 1
            scale /= 2
        logger.info('(#####)large_image/server/tilesource/kfb.py:getPreferredLevel=' + str(level))
        return level

    def getAssociatedImagesList(self):
        logger.info('(#####)large_image/server/tilesource/kfb.py:getAssociatedImagesList')
        """
        Get a list of all associated images.

        :return: the list of image keys.
        """
        try:
            return sorted(self._openslide.associated_images)
        except openslide.lowlevel.OpenSlideError:
            return []

    def _getAssociatedImage(self, imageKey):
        logger.info('(#####)large_image/server/tilesource/kfb.py:_getAssociatedImage')
        """
        Get an associated image in PIL format.

        :param imageKey: the key of the associated image.
        :return: the image in PIL format or None.
        """
        try:
            if imageKey in self._openslide.associated_images:
                return self._openslide.associated_images[imageKey]
        except openslide.lowlevel.OpenSlideError:
            pass
        return None


if girder:

    class KFBGirderTileSource(KFBFileTileSource, GirderTileSource):
        """
        Provides tile access to Girder items with an KFB file.
        """
        logger.info('(#####)large_image/server/tilesource/kfb.py:KFBGirderTileSource')
        cacheName = 'tilesource'
        name = 'kfb'
