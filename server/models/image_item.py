#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################################################################
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
#############################################################################

import json
import os
import pymongo
import six
import time
from six import BytesIO

from girder.constants import SortDir
from girder.exceptions import ValidationException
from girder.models.file import File
from girder.models.item import Item
from girder.models.setting import Setting
from girder.models.upload import Upload
from girder.plugins.worker import utils as workerUtils
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job
from girder import logger
from bson.objectid import ObjectId  
from large_image.server.tilesource.base import TileSource as base
    
from .base import TileGeneralException
from .. import constants
from ..tilesource import AvailableTileSources, TileSourceException

import sys
# sys.path.append("/home/ken/usr/work/pvWeb/src/cython/r/")
# import pCythonInterface as mmHandler
import numpy as np
import shutil
import stat
import traceback
import PIL 

class ImageItem(Item):
    logger.info('(#####)large_image/server/models/image_item.py:ImageItem')
    # We try these sources in this order.  The first entry is the fallback for
    # items that antedate there being multiple options.
    def initialize(self):
        logger.info('(#####)large_image/server/models/image_item.py:initialize')
        super(ImageItem, self).initialize()
        self.ensureIndices(['largeImage.fileId'])
        File().ensureIndices([([
            ('isLargeImageThumbnail', pymongo.ASCENDING),
            ('attachedToType', pymongo.ASCENDING),
            ('attachedToId', pymongo.ASCENDING),
        ], {})])

    def createImageItem(self, item, fileObj, user=None, token=None,
                        createJob=True, notify=False):
        logger.info('(#####)large_image/server/models/image_item.py:createImageItem:fileObj=' + str(fileObj))
        # Using setdefault ensures that 'largeImage' is in the item
        if 'fileId' in item.setdefault('largeImage', {}):
            # TODO: automatically delete the existing large file
            raise TileGeneralException('Item already has a largeImage set.')
        if fileObj['itemId'] != item['_id']:
            raise TileGeneralException('The provided file must be in the '
                                       'provided item.')
        if (item['largeImage'].get('expected') is True and
                'jobId' in item['largeImage']):
            raise TileGeneralException('Item is scheduled to generate a '
                                       'largeImage.')

        item['largeImage'].pop('expected', None)
        item['largeImage'].pop('sourceName', None)

        item['largeImage']['fileId'] = fileObj['_id']
        job = None

        fileName=str(item.get("lowerName"))
        exten=fileName[-3:]
        logger.info('(#####)large_image/server/models/image_item.py:createImageItem:exten=' + exten)
        logger.info('(#####)large_image/server/models/image_item.py:createImageItem:AvailableTileSources=' + str(AvailableTileSources))
        if exten != "kfb":
            for sourceName in AvailableTileSources:
                if getattr(AvailableTileSources[sourceName], 'girderSource',
                           False):
                    if AvailableTileSources[sourceName].canRead(item):
                        item['largeImage']['sourceName'] = sourceName
                        break
                logger.info('(#####)large_image/server/models/image_item.py:createImageItem:item 1=' + str(item))
            if 'sourceName' not in item['largeImage'] and not createJob:
                logger.info('(#####)large_image/server/models/image_item.py:createImageItem:TileGeneralException=' + str(TileGeneralException))
                raise TileGeneralException(
                    'A job must be used to generate a largeImage.')
            if 'sourceName' not in item['largeImage']:
                logger.info('(#####)large_image/server/models/image_item.py:del')
                # No source was successful
                del item['largeImage']['fileId']
                job = self._createLargeImageJob(item, fileObj, user, token)
                item['largeImage']['expected'] = True
                item['largeImage']['notify'] = notify
                item['largeImage']['originalId'] = fileObj['_id']
                item['largeImage']['jobId'] = job['_id']
        else: # kfb file
            item['largeImage']['sourceName'] = 'kfb'

        logger.info('(#####)large_image/server/models/image_item.py:createImageItem:item = ' + str(item))
        self.save(item)
        return job

    def _createLargeImageJob(self, item, fileObj, user, token):
        path = os.path.join(os.path.dirname(__file__), '..', 'create_tiff.py')
        with open(path, 'r') as f:
            script = f.read()

        title = 'TIFF conversion: %s' % fileObj['name']
        job = Job().createJob(
            title=title, type='large_image_tiff', handler='worker_handler',
            user=user)
        jobToken = Job().createJobToken(job)

        outputName = os.path.splitext(fileObj['name'])[0] + '.tiff'
        if outputName == fileObj['name']:
            outputName = (os.path.splitext(fileObj['name'])[0] + '.' +
                          time.strftime('%Y%m%d-%H%M%S') + '.tiff')

        task = {
            'mode': 'python',
            'script': script,
            'name': title,
            'inputs': [{
                'id': 'in_path',
                'target': 'filepath',
                'type': 'string',
                'format': 'text'
            }, {
                'id': 'out_filename',
                'type': 'string',
                'format': 'text'
            }, {
                'id': 'tile_size',
                'type': 'number',
                'format': 'number'
            }, {
                'id': 'quality',
                'type': 'number',
                'format': 'number'
            }],
            'outputs': [{
                'id': 'out_path',
                'target': 'filepath',
                'type': 'string',
                'format': 'text'
            }]
        }

        inputs = {
            'in_path': workerUtils.girderInputSpec(
                fileObj, resourceType='file', token=token),
            'quality': {
                'mode': 'inline',
                'type': 'number',
                'format': 'number',
                'data': 90
            },
            'tile_size': {
                'mode': 'inline',
                'type': 'number',
                'format': 'number',
                'data': 256
            },
            'out_filename': {
                'mode': 'inline',
                'type': 'string',
                'format': 'text',
                'data': outputName
            }
        }

        outputs = {
            'out_path': workerUtils.girderOutputSpec(
                parent=item, token=token, parentType='item')
        }

        # TODO: Give the job an owner
        job['kwargs'] = {
            'task': task,
            'inputs': inputs,
            'outputs': outputs,
            'jobInfo': workerUtils.jobInfoSpec(job, jobToken),
            'auto_convert': False,
            'validate': False
        }
        job['meta'] = {
            'creator': 'large_image',
            'itemId': str(item['_id']),
            'task': 'createImageItem',
        }

        job = Job().save(job)
        Job().scheduleJob(job)

        return job

    @classmethod
    def _loadTileSource(cls, item, **kwargs):
        if 'largeImage' not in item:
            logger.info('(#####)large_image/server/models/image_item.py:_loadTileSource:TileSourceException1')
            raise TileSourceException('No large image file in this item.')
        if item['largeImage'].get('expected'):
            logger.info('(#####)large_image/server/models/image_item.py:_loadTileSource:TileSourceException2')
            raise TileSourceException('The large image file for this item is '
                                      'still pending creation.')

        sourceName = item['largeImage']['sourceName']
        logger.info('(#####)large_image/server/models/image_item.py:_loadTileSource:item='+str(item))
        logger.info('(#####)large_image/server/models/image_item.py:_loadTileSource:kwargs='+str(kwargs))
        tileSource = AvailableTileSources[sourceName](item, **kwargs)
        logger.info('(#####)large_image/server/models/image_item.py:_loadTileSource:tileSource='+str(tileSource))
        return tileSource

    def getMetadata(self, item, **kwargs):
        tileSource = self._loadTileSource(item, **kwargs)
        return tileSource.getMetadata()

    def getTile(self, item, x, y, z, mayRedirect=False, **kwargs):
#         traceback.print_stack()
        logger.info('(#####)large_image/server/models/image_item.py:getTile():x, y, z='+str(x)+', '+str(y)+', '+str(z))
        tileSource = self._loadTileSource(item, **kwargs)
        tileMimeType = tileSource.getTileMimeType()
        self.levels =10
        fileName=str(item.get("lowerName"))
        exten=fileName[-3:]
        logger.info('(#####)large_image/server/models/image_item.py:getTile():exten=' + exten)
#         if exten != "kfb":
        tileData = tileSource.getTile(x, y, z, mayRedirect=mayRedirect)
#         else:
#             scale = 2 ** (self.levels - 1 - z)
#             offsetx = x * 240 * scale
#             offsety = y * 240 * scale
#             svslevel={'svslevel': 0, 'scale':1}
#             tile = PIL.Image.new("RGB", (240 * svslevel['scale'], 240 * svslevel['scale']), 'green')
#     
#             topLeftX = offsetx
#             topLeftY = offsety
#             level = svslevel['svslevel']
#             szX = 240 * svslevel['scale']
#             szY = 240 * svslevel['scale']
#             
#             l2sHash = dict((('0', 40), ('1',10), ('2',2.5),('3',0.6)))
#             iii = np.zeros([szY, szX, 3], dtype=np.uint8)
# 
#             logger.info('(#####)large_image/server/tilesource/image_item.py-getTile:level='+str(level))
#             logger.info('(#####)large_image/server/tilesource/image_item.py-getTile:l2sHash='+str(l2sHash))
#             scale = l2sHash[str(level)]
#             scale = 40            
#             id = item['largeImage']['fileId']
#             logger.info('(#####)large_image/server/tilesource/image_item.py-getTile:id='+str(id))
#             file = File().findOne({'_id': ObjectId(id)})
# 
#             fileName=str(os.path.join("/opt/histomicstk/assetstore", file["path"]))
#             fileName_temp=str(os.path.join("/opt/histomicstk/assetstore", file["path"][0:5], "temp.kfb"))
#             logger.info('(#####)large_image/server/tilesource/svs-getTile:fileName='+(fileName_temp))
#             mmHandler.extractKFSlideRegionToUcharArray(fileName_temp, topLeftX, topLeftY, scale, szX, szY, iii)        
# 
#             tile = PIL.Image.fromarray(iii.astype('uint8'), 'RGB')
#             tileData = self._outputTile(tile, 'PIL', x, y, z, False, **kwargs)
        logger.info('(#####)large_image/server/models/image_item.py:getTile():tileMimeType='+str(tileMimeType))
        logger.info('(#####)large_image/server/models/image_item.py:getTile():tileData='+str(tileData)[:10])
        return tileData, tileMimeType

    def _outputTile(self, tile, tileEncoding, x, y, z, pilImageAllowed=False, **kwargs):
        """
        Convert a tile from a PIL image or image in memory to the desired
        encoding.

        :param tile: the tile to convert.
        :param tileEncoding: the current tile encoding.
        :param x: tile x value.  Used for cropping or edge adjustment.
        :param y: tile y value.  Used for cropping or edge adjustment.
        :param z: tile z (level) value.  Used for cropping or edge adjustment.
        :param pilImageAllowed: True if a PIL image may be returned.
        :returns: either a PIL image or a memory object with an image file.
        """

        isEdge = False
        self.edge = False
        if self.edge:
            sizeX = int(self.sizeX * 2 ** (z - (self.levels - 1)))
            sizeY = int(self.sizeY * 2 ** (z - (self.levels - 1)))
            maxX = (x + 1) * self.tileWidth
            maxY = (y + 1) * self.tileHeight
            isEdge = maxX > sizeX or maxY > sizeY
        if tileEncoding != 'PIL':
            if tileEncoding == self.encoding and not isEdge:
                return tile
            tile = PIL.Image.open(BytesIO(tile))
        if isEdge:
            contentWidth = min(self.tileWidth,
                               sizeX - (maxX - self.tileWidth))
            contentHeight = min(self.tileHeight,
                                sizeY - (maxY - self.tileHeight))
            if self.edge in (True, 'crop'):
                tile = tile.crop((0, 0, contentWidth, contentHeight))
            else:
                color = PIL.ImageColor.getcolor(self.edge, tile.mode)
                if contentWidth < self.tileWidth:
                    PIL.ImageDraw.Draw(tile).rectangle(
                        [(contentWidth, 0), (self.tileWidth, contentHeight)],
                        fill=color, outline=None)
                if contentHeight < self.tileHeight:
                    PIL.ImageDraw.Draw(tile).rectangle(
                        [(0, contentHeight), (self.tileWidth, self.tileHeight)],
                        fill=color, outline=None)
        if pilImageAllowed:
            logger.info('(#####)large_image/server/models/image_item.py:getTile():tile='+str(tile))
            return tile
        TileOutputPILFormat={'JFIF': 'JPEG'}
        encoding='JPEG'
        encoding = TileOutputPILFormat.get(encoding, encoding)
        if encoding == 'JPEG' and tile.mode not in ('L', 'RGB'):
            tile = tile.convert('RGB')
        # If we can't redirect, but the tile is read from a file in the desired
        # output format, just read the file
        if hasattr(tile, 'fp') and self._pilFormatMatches(tile):
            tile.fp.seek(0)
            logger.info('(#####)large_image/server/models/image_item.py:getTile():tile.fp.read()='+str(tile.fp.read()))
            return tile.fp.read()
        output = BytesIO()
        jpegQuality = 95
        jpegSubsampling = 0
        tiffCompression = 'raw'
        tile.save(
            output, encoding, quality=jpegQuality,
            subsampling=jpegSubsampling, compression=tiffCompression)
#         logger.info('(#####)large_image/server/models/image_item.py:getTile():output.getvalue()='+str(output.getvalue()))
        return output.getvalue()

    def _pilFormatMatches(self, image, match=True, **kwargs):
        """
        Determine if the specified PIL image matches the format of the tile
        source with the specified arguments.

        :param image: the PIL image to check.
        :param match: if 'any', all image encodings are considered matching,
            if 'encoding', then a matching encoding matches regardless of
            quality options, otherwise, only match if the encoding and quality
            options match.
        :param **kwargs: additional parameters to use in determining format.
        """
        logger.info('(#####)large_image/server/tilesource/base.py:_pilFormatMatches')

        TileOutputPILFormat = {
            'JFIF': 'JPEG'
        }
        encoding = TileOutputPILFormat.get(self.encoding, self.encoding)
        if match == 'any' and encoding in ('PNG', 'JPEG'):
            return True
        if image.format != encoding:
            return False
        if encoding == 'PNG':
            return True
        if encoding == 'JPEG':
            if match == 'encoding':
                return True
            originalQuality = None
            try:
                if image.format == 'JPEG' and hasattr(image, 'quantization'):
                    if image.quantization[0][58] <= 100:
                        originalQuality = int(100 - image.quantization[0][58] / 2)
                    else:
                        originalQuality = int(5000.0 / 2.5 / image.quantization[0][15])
            except Exception:
                return False
            return abs(originalQuality - self.jpegQuality) <= 1
        # We fail for the TIFF file format; it is general enough that ensuring
        # compatibility could be an issue.
        return False

    def delete(self, item):
        deleted = False
        if 'largeImage' in item:
            job = None
            if 'jobId' in item['largeImage']:
                try:
                    job = Job().load(item['largeImage']['jobId'], force=True, exc=True)
                except ValidationException:
                    # The job has been deleted, but we still need to clean up
                    # the rest of the tile information
                    pass
            if (item['largeImage'].get('expected') and job and
                    job.get('status') in (
                    JobStatus.QUEUED, JobStatus.RUNNING)):
                # cannot cleanly remove the large image, since a conversion
                # job is currently in progress
                # TODO: cancel the job
                # TODO: return a failure error code
                return False

            # If this file was created by the worker job, delete it
            if 'jobId' in item['largeImage']:
                if job:
                    # TODO: does this eliminate all traces of the job?
                    # TODO: do we want to remove the original job?
                    Job().remove(job)
                del item['largeImage']['jobId']

            if 'originalId' in item['largeImage']:
                # The large image file should not be the original file
                assert item['largeImage']['originalId'] != \
                    item['largeImage'].get('fileId')

                if 'fileId' in item['largeImage']:
                    file = File().load(id=item['largeImage']['fileId'], force=True)
                    if file:
                        File().remove(file)
                del item['largeImage']['originalId']

            del item['largeImage']

            item = self.save(item)
            deleted = True
        self.removeThumbnailFiles(item)
        return deleted

    def getThumbnail(self, item, width=None, height=None, **kwargs):
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:item='+str(item))
        """
        Using a tile source, get a basic thumbnail.  Aspect ratio is
        preserved.  If neither width nor height is given, a default value is
        used.  If both are given, the thumbnail will be no larger than either
        size.

        :param item: the item with the tile source.
        :param width: maximum width in pixels.
        :param height: maximum height in pixels.
        :param **kwargs: optional arguments.  Some options are encoding,
            jpegQuality, jpegSubsampling, tiffCompression, fill.  This is also
            passed to the tile source.
        :returns: thumbData, thumbMime: the image data and the mime type OR
            a generator which will yield a file.
        """
        # check if a thumbnail file exists with a particular key
        keydict = dict(kwargs, width=width, height=height)
        if 'fill' in keydict and (keydict['fill']).lower() == 'none':
            del keydict['fill']
        keydict = {k: v for k, v in six.viewitems(keydict) if v is not None}
        key = json.dumps(keydict, sort_keys=True, separators=(',', ':'))
        existing = File().findOne({
            'attachedToType': 'item',
            'attachedToId': item['_id'],
            'isLargeImageThumbnail': True,
            'thumbnailKey': key
        })
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:existing='+str(existing))
        if existing:
            if kwargs.get('contentDisposition') != 'attachment':
                contentDisposition = 'inline'
            else:
                contentDisposition = kwargs['contentDisposition']
            return File().download(existing, contentDisposition=contentDisposition)
        tileSource = self._loadTileSource(item, **kwargs)
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:tileSource = ' + str(tileSource))
        thumbData, thumbMime = tileSource.getThumbnail(
            width, height, **kwargs)
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:thumbData = ' + str(thumbData)[:10])
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:thumbMime = ' + str(thumbMime))

        # The logic on which files to save could be more sophisticated.
        maxThumbnailFiles = int(Setting().get(
            constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES))
        saveFile = maxThumbnailFiles > 0
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:maxThumbnailFiles = ' + str(maxThumbnailFiles))
        logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:saveFile = ' + str(saveFile))
        if saveFile:
            # Make sure we don't exceed the desired number of thumbnails
            self.removeThumbnailFiles(item, maxThumbnailFiles - 1)
            # Save the thumbnail as a file
            thumbfile = Upload().uploadFromFile(
                six.BytesIO(thumbData), size=len(thumbData),
                name='_largeImageThumbnail', parentType='item', parent=item,
                user=None, mimeType=thumbMime, attachParent=True)
            logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:thumbfile = ' + str(thumbfile))
            thumbfile.update({
                'isLargeImageThumbnail': True,
                'thumbnailKey': key,
            })
            # Ideally, we would check that the file is still wanted before we
            # save it.  This is probably imposible without true transactions in
            # Mongo.
            File().save(thumbfile)
            logger.info('(#####)large_image/server/models/image_item.py:getThumbnail:save = ')
        # Return the data
        return thumbData, thumbMime

    def removeThumbnailFiles(self, item, keep=0, sort=None, **kwargs):
        """
        Remove all large image thumbnails from an item.

        :param item: the item that owns the thumbnails.
        :param keep: keep this many entries.
        :param sort: the sort method used.  The first (keep) records in this
            sort order are kept.
        :param **kwargs: additional parameters to determine which files to
            remove.
        :returns: a tuple of (the number of files before removal, the number of
            files removed).
        """
        if not sort:
            sort = [('_id', SortDir.DESCENDING)]
        query = {
            'attachedToType': 'item',
            'attachedToId': item['_id'],
            'isLargeImageThumbnail': True,
        }
        query.update(kwargs)
        present = 0
        removed = 0
        for file in File().find(query, sort=sort):
            present += 1
            if keep > 0:
                keep -= 1
                continue
            File().remove(file)
            removed += 1
        return (present, removed)

    def getRegion(self, item, **kwargs):
        """
        Using a tile source, get an arbitrary region of the image, optionally
        scaling the results.  Aspect ratio is preserved.

        :param item: the item with the tile source.
        :param **kwargs: optional arguments.  Some options are left, top,
            right, bottom, regionWidth, regionHeight, units, width, height,
            encoding, jpegQuality, jpegSubsampling, and tiffCompression.  This
            is also passed to the tile source.
        :returns: regionData, regionMime: the image data and the mime type.
        """
        tileSource = self._loadTileSource(item, **kwargs)
        regionData, regionMime = tileSource.getRegion(**kwargs)
        return regionData, regionMime

    def getPixel(self, item, **kwargs):
        """
        Using a tile source, get a single pixel from the image.

        :param item: the item with the tile source.
        :param **kwargs: optional arguments.  Some options are left, top.
        :returns: a dictionary of the color channel values, possibly with
            additional information
        """
        tileSource = self._loadTileSource(item, **kwargs)
        return tileSource.getPixel(**kwargs)

    def tileSource(self, item, **kwargs):
        """
        Get a tile source for an item.

        :param item: the item with the tile source.
        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
        return self._loadTileSource(item, **kwargs)

    def getAssociatedImagesList(self, item, **kwargs):
        """
        Return a list of associated images.

        :param item: the item with the tile source.
        :return: a list of keys of associated images.
        """
        tileSource = self._loadTileSource(item, **kwargs)
        return tileSource.getAssociatedImagesList()

    def getAssociatedImage(self, item, imageKey, *args, **kwargs):
        """
        Return an associated image.

        :param item: the item with the tile source.
        :param imageKey: the key of the associated image to retreive.
        :param **kwargs: optional arguments.  Some options are width, height,
            encoding, jpegQuality, jpegSubsampling, and tiffCompression.
        :returns: imageData, imageMime: the image data and the mime type, or
            None if the associated image doesn't exist.
        """
        tileSource = self._loadTileSource(item, **kwargs)
        return tileSource.getAssociatedImage(imageKey, *args, **kwargs)
