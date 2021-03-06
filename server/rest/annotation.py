#!/usr/bin/env python
# -*- coding: utf-8 -*-

##############################################################################
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
##############################################################################

import json
import ujson

import cherrypy
import traceback
from xml.etree.ElementTree import Element, SubElement, ElementTree
from xml.etree import ElementTree as etree

from girder import logger
from girder.api import access
from girder.api.describe import describeRoute, autoDescribeRoute, Description
from girder.api.rest import Resource, loadmodel, filtermodel, setResponseHeader
from girder.constants import AccessType, SortDir
from girder.exceptions import ValidationException, RestException, AccessException
from girder.models.item import Item
from girder.models.user import User
from girder.utility import JsonEncoder
from ..models.annotation import AnnotationSchema, Annotation
from ..models.annotationelement import Annotationelement
from __builtin__ import str
from bson.objectid import ObjectId


class AnnotationResource(Resource):

    def __init__(self):
        print('(#####):large_image/server/rest/annotation.py:__init__()')
        super(AnnotationResource, self).__init__()

        self.resourceName = 'annotation'
        self.route('GET', (), self.find)
        self.route('GET', ('schema',), self.getAnnotationSchema)
        self.route('GET', ('images',), self.findAnnotatedImages)
        self.route('GET', (':id',), self.getAnnotation)
        self.route('GET', (':id', 'history'), self.getAnnotationHistoryList)
        self.route('GET', (':id', 'history', ':version'), self.getAnnotationHistory)
        self.route('PUT', (':id', 'history', 'revert'), self.revertAnnotationHistory)
        self.route('POST', (), self.createAnnotation)
        self.route('POST', (':id', 'copy'), self.copyAnnotation)
        self.route('PUT', (':id',), self.updateAnnotation)
        self.route('DELETE', (':id',), self.deleteAnnotation)
        self.route('GET', (':id', 'access'), self.getAnnotationAccess)
        self.route('PUT', (':id', 'access'), self.updateAnnotationAccess)
        self.route('GET', ('item', ':id',), self.getItemAnnotations)
        self.route('POST', ('item', ':id',), self.createItemAnnotations)

    @describeRoute(
        Description('Search for annotations.')
        .responseClass('Annotation')
        .param('itemId', 'List all annotations in this item.', required=False)
        .param('userId', 'List all annotations created by this user.',
               required=False)
        .param('text', 'Pass this to perform a full text search for '
               'annotation names and descriptions.', required=False)
        .param('name', 'Pass to lookup an annotation by exact name match.',
               required=False)
        .pagingParams(defaultSort='lowerName')
        .errorResponse()
        .errorResponse('Read access was denied on the parent item.', 403)
    )
    @access.public
    @filtermodel(model='annotation', plugin='large_image')
    def find(self, params):
        print('(#####):large_image/server/rest/annotation.py:find()')
        limit, offset, sort = self.getPagingParameters(params, 'lowerName')
        query = {'_active': {'$ne': False}}
        if 'itemId' in params:
            item = Item().load(params.get('itemId'), force=True)
            Item().requireAccess(
                item, user=self.getCurrentUser(), level=AccessType.READ)
            query['itemId'] = item['_id']
        if 'userId' in params:
            user = User().load(
                params.get('userId'), user=self.getCurrentUser(),
                level=AccessType.READ)
            query['creatorId'] = user['_id']
        if params.get('text'):
            query['$text'] = {'$search': params['text']}
        if params.get('name'):
            query['annotation.name'] = params['name']
        fields = list(
            (
                'annotation.name', 'annotation.description', 'access', 'groups', '_version'
            ) + Annotation().baseFields)
        annotations = list(Annotation().filterResultsByPermission(
            cursor=Annotation().find(query, sort=sort, fields=fields),
            user=self.getCurrentUser(), level=AccessType.READ, limit=limit, offset=offset
        ))
        for annotation in annotations:
            Annotation().injectAnnotationGroupSet(annotation)
        return annotations

    @describeRoute(
        Description('Get the official Annotation schema')
        .notes('In addition to the schema, if IDs are specified on elements, '
               'all IDs must be unique.')
        .errorResponse()
    )
    @access.public
    def getAnnotationSchema(self, params):
        print('(#####):large_image/server/rest/annotation.py:getAnnotationSchema()')
        return AnnotationSchema.annotationSchema

    @describeRoute(
        Description('Get an annotation by id.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('left', 'The left column of the area to fetch.',
               required=False, dataType='float')
        .param('right', 'The right column (exclusive) of the area to fetch.',
               required=False, dataType='float')
        .param('top', 'The top row of the area to fetch.',
               required=False, dataType='float')
        .param('bottom', 'The bottom row (exclusive) of the area to fetch.',
               required=False, dataType='float')
        .param('low', 'The lowest z value of the area to fetch.',
               required=False, dataType='float')
        .param('high', 'The highest z value (exclusive) of the area to fetch.',
               required=False, dataType='float')
        .param('minimumSize', 'Only annotations larger than or equal to this '
               'size in pixels will be returned.  Size is determined by the '
               'length of the diagonal of the bounding box of an element.  '
               'This probably should be 1 at the maximum zoom, 2 at the next '
               'level down, 4 at the next, etc.', required=False,
               dataType='float')
        .param('maxDetails', 'Limit the number of annotations returned based '
               'on complexity.  The complexity of an annotation is how many '
               'points are used to defined it.  This is applied in addition '
               'to the limit.  Using maxDetails helps ensure results will be '
               'able to be rendered.', required=False, dataType='int')
        .pagingParams(defaultSort='_id', defaultLimit=None,
                      defaultSortDir=SortDir.ASCENDING)
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the annotation.', 403)
        .notes('Use "size" or "details" as possible sort keys.')
    )
    @access.cookie
    @access.public
    def getAnnotation(self, id, params):
        user = self.getCurrentUser()
        print('(#####):large_image/server/rest/annotation.py-getAnnotation():anno_results='+str(self._getAnnotation(user, id, params)))
        return self._getAnnotation(user, id, params)

    def _getAnnotation(self, user, id, params):
        """
        Get a generator function that will yield the json of an annotation.
        :param user: the user that needs read access on the annoation and its
            parent item.
        :param id: the annotation id.
        :param params: paging and region parameters for the annotation.
        :returns: a function that will return a generator.
        """
        annotation = Annotation().load(
            id, region=params, user=user, level=AccessType.READ, getElements=False)
        if annotation is None:
            raise RestException('Annotation not found', 404)
        # Ensure that we have read access to the parent item.  We could fail
        # faster when there are permissions issues if we didn't load the
        # annotation elements before checking the item access permissions.
        #  This had been done via the filtermodel decorator, but that doesn't
        # work with yielding the elements one at a time.
        annotation = Annotation().filter(annotation, self.getCurrentUser())

        annotation['annotation']['elements'] = []
        breakStr = b'"elements": ['
        base = json.dumps(annotation, sort_keys=True, allow_nan=False,
                          cls=JsonEncoder).encode('utf8').split(breakStr)
        print('(#####):large_image/server/rest/annotation.py-_getAnnotation():base='+str(base))

        def generateResult():
#             print('(#####):generateResult():headers='+ str(cherrypy.response.headers))
#             print('(#####):generateResult():stream='+ str(cherrypy.response.stream))
#             print('(#####):generateResult():status='+ str(cherrypy.response.status))
#             print('(#####):generateResult():cookie='+ str(cherrypy.response.cookie))

#             print('(#####):generateResult():headers.elements='+ str(cherrypy.request.headers.elements))
#             print('(#####):generateResult():headers='+ str(cherrypy.request.headers))
#             print('(#####):generateResult():cookie='+ str(cherrypy.request.cookie))

            info = {}
            idx = 0
            yield base[0]
            yield breakStr
            for element in Annotationelement().yieldElements(annotation, params, info):
                # The json conversion is fastest if we use defaults as much as
                # possible.  The only value in an annotation element that needs
                # special handling is the id, so cast that ourselves and then
                # use a json encoder in the most compact form.
                element['id'] = str(element['id'])
                # Use ujson; it is much faster.  The standard json library
                # could be used in its most default mode instead like so:
                #   result = json.dumps(element, separators=(',', ':'))
                result = ujson.dumps(element)
                result = (b',' if idx else b'') + result.encode('utf8')
                yield result
                idx += 1
            yield base[1].rstrip().rstrip(b'}')
            yield b', "_elementQuery": '
            yield json.dumps(
                info, sort_keys=True, allow_nan=False, cls=JsonEncoder).encode('utf8')
            yield b'}'

        def generateResultAno(id, params):
            traceback.print_stack()
            print('(#####):generateResultAno():headers='+ str(cherrypy.response.headers))
#             print('(#####):generateResultAno():stream='+ str(cherrypy.response.stream))
#             print('(#####):generateResultAno():status='+ str(cherrypy.response.status))
#             print('(#####):generateResulAnot():cookie='+ str(cherrypy.response.cookie))

#             print('(#####):generateResultAno():headers.elements='+ str(cherrypy.request.headers.elements))
#             print('(#####):generateResultAno():headers='+ str(cherrypy.request.headers))
#             print('(#####):generateResultAno():cookie='+ str(cherrypy.request.cookie))
#             yield '<?xml version="1.0" encoding="gb2312"?>'
            root = Element('Slide')
            annotations = SubElement(root, 'Annotations')
            regions = SubElement(annotations, 'Regions')
            info = {}
            for element in Annotationelement().yieldElements(annotation, params, info):
                print('(#####):generateResultAno():headers.elements='+ str(cherrypy.request.headers.elements))
                height=element.get("height")
                width=element.get("width")
                fillColor=element.get("fillColor")
                lineColor=element.get("lineColor")
                lineWidth=element.get("lineWidth")
                center=element.get("center")
                type_pv=element.get("type")

                region = SubElement(regions, 'Region')
                region.set('Detail', "")
                region.set('FontItalic', 'False')
                region.set('FontBold', 'False')
                region.set('MsVisble', 'True')
                region.set('Hidden', 'Visible')
                region.set('Zoom', '0.5')
                region.set('Visible', "Visible")
                region.set('Color', '4282056448')

                if type_pv=="rectangle":
                    region.set('Guid', 'Rectangle')
                    region.set('Name', 'JuXing')
                    region.set('FontSize', '12')
                    region.set('Size', str(lineWidth))
                    region.set('FigureType', 'Rectangle')
                    region.set('PinType', 'images/pin_1.png')

                    vertices = SubElement(region, 'Vertices')
                    vertice = SubElement(vertices, 'Vertice')
                    vertice.set('X', str((center[0]-(width/2))/40))
                    vertice.set('Y', str((center[1]-(height/2))/40))
                    vertice = SubElement(vertices, 'Vertice')
                    vertice.set('X', str((center[0]+(width/2))/40))
                    vertice.set('Y', str((center[1]+(height/2))/40))

                elif type_pv=="polyline":
                    region.set('Guid', 'Polygon')
                    region.set('Name', 'QuXian')
                    region.set('FontSize', '12')
                    region.set('Size', str(lineWidth))
                    region.set('FigureType', 'Polygon')
                    region.set('PinType', 'images/pin_1.png')
                    vertices = SubElement(region, 'Vertices')
                    points=element.get("points")
                    for point in points:
                        vertice = SubElement(vertices, 'Vertice')
                        vertice.set('X', str(point[0]/40))
                        vertice.set('Y', str(point[1]/40))
                else : # type=="line"
                    region.set('Guid', 'Remark')
                    region.set('Name', 'BiaoZhu')
                    region.set('FontSize', '12')
                    region.set('Size', str(lineWidth))
                    region.set('FigureType', 'Remark')
                    region.set('PinType', 'images/pin_4.png')

                    vertices = SubElement(region, 'Vertices')
                    vertice = SubElement(vertices, 'Vertice')
                    vertice.set('X', str(center[0]/40))
                    vertice.set('Y', str(center[1]/40))

#                 vertices = SubElement(region, 'Vertices')
#                 for point in points:
#                     vertice = SubElement(vertices, 'Vertice')
#                     vertice.set('X', str(point[0]))
#                     vertice.set('Y', str(point[1]))
                #tree = ElementTree(root)
            head='<?xml version="1.0" encoding="utf-8"?>'
            print('(#####):generateResult():id='+ str(id))
            annotation_1 = Annotation().findOne({'_id': ObjectId(id)})
            print('(#####):generateResult():item='+ str(annotation_1))
            print('(#####):generateResult():itemId='+ str(annotation_1["itemId"]))
            item=Item().findOne({'_id': annotation_1["itemId"]})
            print('(#####):generateResult():name='+ str(item["name"]))
            name = item["name"]
            cherrypy.response.headers.update({'Content-Type': 'application/html',
                                              'Content-Disposition': 'attachment; filename=' + name +'.Ano'})
            xml_resut=(head + etree.tostring(root).encode('utf-8'))
            print('(#####):generateResult():xml_resut='+ xml_resut)
            return xml_resut

        setResponseHeader('Content-Type', 'application/json')

        accept = cherrypy.request.headers.elements('Accept')
        if accept:
            print('(#####):generateResult():Accept 1='+ str(accept))
            return generateResult
        else:
            print('(#####):generateResult():Accept 2='+ str(accept))
            return generateResultAno(id, params)

    @describeRoute(
        Description('Create an annotation.')
        .responseClass('Annotation')
        .param('itemId', 'The ID of the associated item.')
        .param('body', 'A JSON object containing the annotation.',
               paramType='body')
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the item.', 403)
        .errorResponse('Invalid JSON passed in request body.')
        .errorResponse('Validation Error: JSON doesn\'t follow schema.')
    )
    @access.user
    @loadmodel(map={'itemId': 'item'}, model='item', level=AccessType.WRITE)
    @filtermodel(model='annotation', plugin='large_image')
    def createAnnotation(self, item, params):
        print('(#####):large_image/server/rest/annotation.py:createAnnotation()')
        try:
            return Annotation().createAnnotation(
                item, self.getCurrentUser(), self.getBodyJson())
        except ValidationException as exc:
            logger.exception('Failed to validate annotation')
            raise RestException(
                'Validation Error: JSON doesn\'t follow schema (%r).' % (
                    exc.args, ))

    @describeRoute(
        Description('Copy an annotation from one item to an other.')
        .param('id', 'The ID of the annotation.', paramType='path',
               required=True)
        .param('itemId', 'The ID of the destination item.',
               required=True)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the item.', 403)
    )
    @access.user
    @loadmodel(model='annotation', plugin='large_image', level=AccessType.READ)
    @filtermodel(model='annotation', plugin='large_image')
    def copyAnnotation(self, annotation, params):
        print('(#####):large_image/server/rest/annotation.py:copyAnnotation()')
        itemId = params['itemId']
        user = self.getCurrentUser()
        Item().load(annotation.get('itemId'),
                    user=user,
                    level=AccessType.READ)
        item = Item().load(itemId, user=user, level=AccessType.WRITE)
        return Annotation().createAnnotation(
            item, user, annotation['annotation'])

    @describeRoute(
        Description('Update an annotation or move it to a different item.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('itemId', 'Pass this to move the annotation to a new item.',
               required=False)
        .param('body', 'A JSON object containing the annotation.  If the '
               '"annotation":"elements" property is not set, the elements '
               'will not be modified.',
               paramType='body', required=False)
        .errorResponse('Write access was denied for the item.', 403)
        .errorResponse('Invalid JSON passed in request body.')
        .errorResponse('Validation Error: JSON doesn\'t follow schema.')
    )
    @access.user
    @loadmodel(model='annotation', plugin='large_image', level=AccessType.WRITE)
    @filtermodel(model='annotation', plugin='large_image')
    def updateAnnotation(self, annotation, params):
        print('(#####):large_image/server/rest/annotation.py:updateAnnotation()')
        user = self.getCurrentUser()
        item = Item().load(annotation.get('itemId'), force=True)
        if item is not None:
            Item().requireAccess(
                item, user=user, level=AccessType.WRITE)
        # If we have a content length, then we have replacement JSON.  If
        # elements are not included, don't replace them
        returnElements = True
        if cherrypy.request.body.length:
            oldElements = annotation.get('annotation', {}).get('elements')
            annotation['annotation'] = self.getBodyJson()
            if 'elements' not in annotation['annotation'] and oldElements:
                annotation['annotation']['elements'] = oldElements
                returnElements = False
        if params.get('itemId'):
            newitem = Item().load(params['itemId'], force=True)
            Item().requireAccess(
                newitem, user=user, level=AccessType.WRITE)
            annotation['itemId'] = newitem['_id']
        try:
            annotation = Annotation().updateAnnotation(annotation, updateUser=user)
        except ValidationException as exc:
            logger.exception('Failed to validate annotation')
            raise RestException(
                'Validation Error: JSON doesn\'t follow schema (%r).' % (
                    exc.args, ))
        if not returnElements:
            del annotation['annotation']['elements']
        return annotation

    @describeRoute(
        Description('Delete an annotation.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the annotation.', 403)
    )
    @access.user
    # Load with a limit of 1 so that we don't bother getting most annotations
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.WRITE)
    def deleteAnnotation(self, annotation, params):
        print('(#####):large_image/server/rest/annotation.py:deleteAnnotation()')
        # Ensure that we have write access to the parent item
        item = Item().load(annotation.get('itemId'), force=True)
        if item is not None:
            Item().requireAccess(
                item, user=self.getCurrentUser(), level=AccessType.WRITE)
        Annotation().remove(annotation)

    @describeRoute(
        Description('Search for annotated images.')
        .notes(
            'By default, this endpoint will return a list of recently annotated images.  '
            'This list can be further filtered by passing the creatorId and/or imageName '
            'parameters.  The creatorId parameter will limit results to annotations '
            'created by the given user.  The imageName parameter will only include '
            'images whose name (or a token in the name) begins with the given string.')
        .param('creatorId', 'Limit to annotations created by this user', required=False)
        .param('imageName', 'Filter results by image name (case-insensitive)', required=False)
        .pagingParams(defaultSort='updated', defaultSortDir=-1)
        .errorResponse()
    )
    @access.public
    def findAnnotatedImages(self, params):
        print('(#####):large_image/server/rest/annotation.py:findAnnotatedImages()')
        limit, offset, sort = self.getPagingParameters(
            params, 'updated', SortDir.DESCENDING)
        user = self.getCurrentUser()

        creator = None
        if 'creatorId' in params:
            creator = User().load(params.get('creatorId'), force=True)

        return Annotation().findAnnotatedImages(
            creator=creator, imageNameFilter=params.get('imageName'),
            user=user, level=AccessType.READ,
            offset=offset, limit=limit, sort=sort)

    @describeRoute(
        Description('Get the access control list for an annotation.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the annotation.', 403)
    )
    @access.user
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.ADMIN)
    def getAnnotationAccess(self, annotation, params):
        print('(#####):large_image/server/rest/annotation.py:getAnnotationAccess()')
        return Annotation().getFullAccessList(annotation)

    @describeRoute(
        Description('Update the access control list for an annotation.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('access', 'The JSON-encoded access control list.')
        .param('public', 'Whether the annotation should be publicly visible.',
               dataType='boolean', required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the annotation.', 403)
    )
    @access.user
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.ADMIN)
    @filtermodel(model=Annotation, addFields={'access'})
    def updateAnnotationAccess(self, annotation, params):
        print('(#####):large_image/server/rest/annotation.py:updateAnnotationAccess()')
        access = json.loads(params['access'])
        public = self.boolParam('public', params, False)
        annotation = Annotation().setPublic(annotation, public)
        annotation = Annotation().setAccessList(
            annotation, access, save=False, user=self.getCurrentUser())
        Annotation().update({'_id': annotation['_id']}, {'$set': {
            key: annotation[key] for key in ('access', 'public', 'publicFlags')
            if key in annotation
        }})
        return annotation

    @autoDescribeRoute(
        Description('Get a list of an annotation\'s history.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .pagingParams(defaultSort='_version', defaultLimit=0,
                      defaultSortDir=SortDir.DESCENDING)
        .errorResponse('Read access was denied for the annotation.', 403)
    )
    @access.cookie
    @access.public
    def getAnnotationHistoryList(self, id, limit, offset, sort):
        print('(#####):large_image/server/rest/annotation.py:getAnnotationHistoryList()')
        return list(Annotation().versionList(id, self.getCurrentUser(), limit, offset, sort))

    @autoDescribeRoute(
        Description('Get a specific version of an annotation\'s history.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('version', 'The version of the annotation.', paramType='path',
               dataType='integer')
        .errorResponse('Annotation history version not found.')
        .errorResponse('Read access was denied for the annotation.', 403)
    )
    @access.cookie
    @access.public
    def getAnnotationHistory(self, id, version):
        print('(#####):large_image/server/rest/annotation.py:getAnnotationHistory()')
        result = Annotation().getVersion(id, version, self.getCurrentUser())
        if result is None:
            raise RestException('Annotation history version not found.')
        return result

    @autoDescribeRoute(
        Description('Revert an annotation to a specific version.')
        .notes('This can be used to undelete an annotation by reverting to '
               'the most recent version.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('version', 'The version of the annotation.  If not specified, '
               'if the annotation was deleted this undeletes it.  If it was '
               'not deleted, this reverts to the previous version.',
               required=False, dataType='integer')
        .errorResponse('Annotation history version not found.')
        .errorResponse('Read access was denied for the annotation.', 403)
    )
    @access.public
    def revertAnnotationHistory(self, id, version):
        print('(#####):large_image/server/rest/annotation.py:revertAnnotationHistory()')
        annotation = Annotation().revertVersion(id, version, self.getCurrentUser())
        if not annotation:
            raise RestException('Annotation history version not found.')
        # Don't return the elements -- it can be too verbose
        del annotation['annotation']['elements']
        return annotation

    @autoDescribeRoute(
        Description('Get all annotations for an item.')
        .notes('This returns a list of annotation model records.')
        .modelParam('id', model=Item, level=AccessType.READ)
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403)
    )
    @access.public
    def getItemAnnotations(self, item):
        print('(#####):large_image/server/rest/annotation.py:getItemAnnotations():item='+str(item))
        user = self.getCurrentUser()
        query = {'_active': {'$ne': False}, 'itemId': item['_id']}
        print('(#####):large_image/server/rest/annotation.py:getItemAnnotations():itemId='+str(query['itemId']))

        def generateResult():
            yield b'['
            first = True
            for annotation in Annotation().find(query, limit=0, sort=[('_id', 1)]):
                if not first:
                    yield b',\n'
                try:
                    annotationGenerator = self._getAnnotation(user, annotation['_id'], {})()
                except AccessException:
                    continue
                for chunk in annotationGenerator:
                    yield chunk
                first = False
            yield b']'

        setResponseHeader('Content-Type', 'application/json')
        return generateResult

    @autoDescribeRoute(
        Description('Create multiple annotations on an item.')
        .modelParam('id', model=Item, level=AccessType.WRITE)
        .jsonParam('annotations', 'A JSON list of annotation model records or '
                   'annotations.  If these are complete models, the value of '
                   'the "annotation" key is used and the other information is '
                   'ignored (such as original creator ID).', paramType='body',
                   requireArray=True)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the item.', 403)
        .errorResponse('Invalid JSON passed in request body.')
        .errorResponse('Validation Error: JSON doesn\'t follow schema.')
    )
    @access.user
    def createItemAnnotations(self, item, annotations):
        print('(#####):large_image/server/rest/annotation.py:createItemAnnotations()')
        user = self.getCurrentUser()
        if not isinstance(annotations, list):
            annotations = [annotations]
        for entry in annotations:
            if not isinstance(entry, dict):
                raise RestException('Entries in the annotation list must be JSON objects.')
            annotation = entry.get('annotation', entry)
            try:
                Annotation().createAnnotation(item, user, annotation)
            except ValidationException as exc:
                logger.exception('Failed to validate annotation')
                raise RestException(
                    'Validation Error: JSON doesn\'t follow schema (%r).' % (
                        exc.args, ))
        return len(annotations)
