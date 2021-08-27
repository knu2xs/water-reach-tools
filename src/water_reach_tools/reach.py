"""
author:     Joel McCune (joel.mccune+gis@gmail.com)
dob:        03 Dec 2014
purpose:    Provide the utilities to process and work with whitewater reach data.

Copyright 2014 Joel McCune
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
   http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from __future__ import annotations
from copy import deepcopy
import datetime
from html.parser import HTMLParser
import inspect
import json
import re
from typing import List, Tuple, Union
from uuid import uuid4

from arcgis.env import active_gis
from arcgis.gis import GIS
from arcgis.features import Feature, hydrology
from arcgis.geometry import Polygon
from html2text import html2text
import numpy as np
import requests
from scipy.interpolate import splprep, splev

from .epa_waters import WATERS
from .geometry_monkeypatch import *
from .feature_layers import ReachPointFeatureLayer, ReachLineFeatureLayer


# helper for cleaning up HTML strings
# From - https://stackoverflow.com/questions/753052/strip-html-from-strings-in-python
class _MLStripper(HTMLParser):
    def __init__(self):
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)


def _strip_tags(html):
    s = _MLStripper()
    s.feed(html)
    return s.get_data()


# smoothing function for geometry
def _smooth_geometry(geom, densify_max_segment_length=0.009, gis=None):

    if not isinstance(geom, Polygon) and not isinstance(geom, Polyline):
        raise Exception('Smoothing can only be performed on Esri Polygon or Polyline geometry types.')

    # get a GIS instance to have a geometry service to resolve to
    if gis is None and active_gis:
        gis = active_gis
    elif gis is None and active_gis is None:
        raise Exception('An active GIS or explicitly defined GIS is required to smooth geometry.')

    def _make_geometry_request(in_geom, url_extension, params):

        # create the url for making the
        url = f'{gis.properties.helperServices.geometry.url}/{url_extension}'

        # make a copy to not modify the original
        geom = deepcopy(in_geom)

        # get the key for the geometry coordinates
        geom_key = list(geom.keys())[0]

        params['geometries'] = {
            'geometryType': 'esriGeometryPolyline',
            'geometries': [
                {geom_key: geom[geom_key]}
            ]
        }

        # convert all dict or list params not at the top level of the dictionary to strings
        payload = {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}

        attempts = 0
        status = None

        while attempts < 5 and status != 200:

            try:

                # make the post request
                resp = requests.post(url, payload)

                # extract out the result from the request and patch into the original geometry object
                geom[geom_key] = resp.json()['geometries'][0][geom_key]

                status = resp.status_code

            except:

                attempts = attempts + 1

        # return the modified geometry object
        return geom

    def densify(in_geom):

        # construct the request parameter dictionary less the geometries
        params = {
            'f': 'json',
            'sr': {'wkid': 4326},
            'maxSegmentLength': densify_max_segment_length
        }

        # return the densified geometry object
        return _make_geometry_request(in_geom, 'densify', params)

    def simplify(in_geom):

        # construct the request parameter dictionary less the geometries
        params = {
            'f': 'json',
            'sr': {'wkid': 4326}
        }

        return _make_geometry_request(in_geom, 'simplify', params)

    def smooth_coord_lst(coord_lst):
        x_lst, y_lst = zip(*coord_lst)

        smoothing = 0.0005
        spline_order = 2
        knot_estimate = -1
        tck, fp, ier, msg = splprep([x_lst, y_lst], s=smoothing, k=spline_order, nest=knot_estimate, full_output=1)

        zoom = 5
        n_len = len(x_lst) * zoom
        x_ip, y_ip = splev(np.linspace(0, 1, n_len), tck[0])

        return [[x_ip[i], y_ip[i]] for i in range(0, len(x_ip))]

    # densify the geometry to help with too much deflection when smoothing
    new_geom = densify(geom)

    # get the dictionary key containing the geometry coordinate pairs
    geom_key = list(new_geom.keys())[0]

    # use the key to get all the coordinate pairs
    new_geom[geom_key] = [smooth_coord_lst(coords) for coords in new_geom[geom_key]]

    # simplify the geometry to remove unnecessary vertices
    new_geom = simplify(new_geom)

    # return smoothed geometry
    return new_geom


class ReachPoint(object):
    """
    Discrete object facilitating working with reach points.
    """

    def __init__(self, reach_id: str, geometry: Point, point_type: str, uid: str = None, subtype: str = None,
                 name: str = None, side_of_river: str = None, collection_method: str = None,
                 update_date: datetime = None, notes: str = None, description: str = None,
                 difficulty: str = None, **kwargs):

        self.nhdplus_measure = None
        self.nhdplus_reach_id = None

        self._side_of_river = None
        self._geom = None

        self.reach_id = str(reach_id)
        self.geometry = geometry
        self.point_type = point_type
        self.subtype = subtype
        self.name = name
        self.side_of_river = side_of_river  # left or right
        self.collection_method = collection_method
        self.update_date = update_date
        self.notes = notes
        self.description = description
        self.difficulty = difficulty

        if uid is None:
            self.uid = uuid4().hex
        else:
            self.uid = uid

    def __repr__(self):
        return f'{self.__class__.__name__ } ({self.reach_id} - {self.point_type} - {self.subtype})'

    @property
    def type_id(self):
        id_list = ['null' if val is None else val for val in [self.reach_id, self.point_type, self.subtype]]
        return '_'.join(id_list)

    @property
    def point(self) -> Point:
        """
        Point Geometry
        """
        return self.geometry

    @point.setter
    def point(self, geometry: Point):
        self.geometry = geometry

    @property
    def geometry(self) -> Point:
        """
        Geometry, a point.
        """
        return self._geom

    @geometry.setter
    def geometry(self, geometry: Point) -> None:
        """
        Set the geometry for the access.
        :param geometry: Point Geometry Object
        """
        if geometry.type != 'Point':
            raise Exception('geometry must be a valid ArcGIS Point Geometry object')
        else:
            self._geom = geometry

    @property
    def side_of_river(self) -> str:
        """
        Which side of the river the point is located on (if applicable).
        """
        return self._side_of_river

    @side_of_river.setter
    def side_of_river(self, side_of_river: str) -> None:
        if side_of_river is not None and side_of_river != 'left' and side_of_river != 'right':
            raise Exception('side of river must be either "left" or "right"')
        else:
            self._side_of_river = side_of_river

    def snap_to_nhdplus(self) -> bool:
        """
        Snap the access geometry to the nearest NHD Plus hydroline, and get the measure and NHD Plus Reach ID
            needed to perform traces against the EPA WATERS Upstream/Downstream service.
        :return: Boolean True when complete
        """
        # status flag
        waters_snap = False

        # if a geometry is populated
        if self.geometry:

            # snap the point using the waters service
            waters = WATERS()
            epa_point = waters.get_epa_snap_point(self.geometry.x, self.geometry.y)

            # if the EPA WATERSs' service was able to locate a point
            if epa_point:

                # set properties accordingly
                self.geometry = epa_point['geometry']
                self.nhdplus_measure = epa_point['measure']
                self.nhdplus_reach_id = epa_point['id']
                waters_snap = True

        return waters_snap

    @property
    def as_feature(self) -> Feature:
        """
        Get the access as an ArcGIS Python API Feature object.
        :return: ArcGIS Python API Feature object representing the access.
        """
        return Feature(
            geometry=self._geom,
            attributes={key: vars(self)[key] for key in vars(self).keys()
                        if key != '_geometry' and not key.startswith('_')}
        )

    @property
    def as_dictionary(self) -> dict:
        """
        Get the point as a dictionary of values making it easier to build DataFrames.
        :return: Dictionary of all properties, with a little modification for geometries.
        """
        dict_point = {key: vars(self)[key] for key in vars(self).keys() if not key.startswith('_')}
        dict_point['SHAPE'] = self.geometry
        return dict_point


class Reach(object):
    """
    Reach object
    """

    def __init__(self, reach_id):

        self._geometry = None
        self._reach_points = []
        self._gague_dhid = None

        self.abstract = ''
        self.agency = None
        self.description = ''
        self.difficulty = ''
        self.difficulty_minimum = ''
        self.difficulty_maximum = ''
        self.difficulty_outlier = ''
        self.error = None                   # boolean
        self.gauge_observation = None
        self.gauge_id = None
        self.gauge_metric = None
        self.gauge_r0 = None
        self.gauge_r1 = None
        self.gauge_r2 = None
        self.gauge_r3 = None
        self.gauge_r4 = None
        self.gauge_r5 = None
        self.gauge_r6 = None
        self.gauge_r7 = None
        self.gauge_r8 = None
        self.gauge_r9 = None
        self.gauge_units = None
        self.notes = ''
        self.reach_id = str(reach_id)
        self.reach_name = ''
        self.reach_name_alternate = ''
        self.river_name = ''
        self.river_name_alternate = ''
        self.tracing_method = None
        self.trace_source = None
        self.update_aw = None               # datetime
        self.update_arcgis = None           # datetime
        self.validated = None               # boolean
        self.validated_by = ''
        self._zoom_envelope = None          # Polygon Geometry

    def _download_raw_json_from_aw(self):
        url = 'https://www.americanwhitewater.org/content/River/detail/id/{}/.json'.format(self.reach_id)

        attempts = 0
        status_code = 0

        while attempts < 10 and status_code != 200:
            resp = requests.get(url)
            if resp.status_code == 200 and len(resp.content):
                return resp.json()
            elif resp.status_code == 200 and not len(resp.content):
                return False
            elif resp.status_code == 500:
                return False
            else:
                attempts = attempts + 1
        raise Exception('cannot download data for reach_id {}'.format(self['reach_id']))

    def _parse_difficulty_string(self, difficulty_combined:str) -> None:
        match = re.match(
            '^([I|IV|V|VI|5\.\d]{1,3}(?=-))?-?([I|IV|V|VI|5\.\d]{1,3}[+|-]?)\(?([I|IV|V|VI|5\.\d]{0,3}[+|-]?)',
            difficulty_combined
        )
        self.difficulty_minimum = self._get_if_length(match.group(1))
        self.difficulty_maximum = self._get_if_length(match.group(2))
        self.difficulty_outlier = self._get_if_length(match.group(3))

    @staticmethod
    def _get_if_length(match_string: str) -> Union[str, None]:
        if match_string and len(match_string):
            return match_string
        else:
            return None

    def _validate_aw_json(self, json_block: dict, key: str) -> str:

        # check to ensure a value exists
        if key not in json_block.keys():
            resp = None

        # ensure there is a value for the key
        elif json_block[key] is None:
            resp = None

        else:

            # clean up the text garbage...because there is a lot of it
            value = self._cleanup_string(json_block[key])

            # now, ensure something is still there...not kidding, this frequently is the case...it is all gone
            if not value:
                resp = None
            elif not len(value):
                resp = None

            else:
                # now check to ensure there is actually some text in the block, not just blank characters
                if not (re.match(r'^([ \r\n\t])+$', value) or not (value != 'N/A')):

                    # if everything is good, return a value
                    resp = value

                else:
                    resp = None

        return resp

    @staticmethod
    def _cleanup_string(input_string: str) -> str:

        # ensure something to work with
        if not input_string:
            return input_string

        # convert to markdown first, so any reasonable formatting is retained
        cleanup = html2text(input_string)

        # since people love to hit the space key multiple times in stupid places, get rid of multiple space, but leave
        # newlines in there since they actually do contribute to formatting
        cleanup = re.sub(r'\s{2,}', ' ', cleanup)

        # apparently some people think it is a good idea to hit return more than twice...account for this foolishness
        cleanup = re.sub(r'\n{3,}', '\n\n', cleanup)
        cleanup = re.sub('(.)\n(.)', '\g<1> \g<2>', cleanup)

        # get rid of any trailing newlines at end of entire text block
        cleanup = re.sub(r'\n+$', '', cleanup)

        # correct any leftover standalone links
        cleanup = cleanup.replace('<', '[').replace('>', ']')

        # get rid of any leading or trailing spaces
        cleanup = cleanup.strip()

        # finally call it good
        return cleanup

    def _parse_aw_json(self, raw_json: str) -> None:

        def remove_backslashes(input_str):
            if isinstance(input_str, str) and len(input_str):
                return input_str.replace('\\', '')
            else:
                return input_str

        # pluck out the stuff we are interested in
        self._reach_json = raw_json['CContainerViewJSON_view']['CRiverMainGadgetJSON_main']

        # pull a bunch of attributes through validation and save as properties
        reach_info = self._reach_json['info']
        self.river_name = self._validate_aw_json(reach_info, 'river')

        self.reach_name = remove_backslashes(self._validate_aw_json(reach_info, 'section'))
        self.reach_alternate_name = remove_backslashes(self._validate_aw_json(reach_info, 'altname'))

        self.huc = self._validate_aw_json(reach_info, 'huc')
        self.description = self._validate_aw_json(reach_info, 'description')
        self.abstract = self._validate_aw_json(reach_info, 'abstract')
        self.agency = self._validate_aw_json(reach_info, 'agency')
        length = self._validate_aw_json(reach_info, 'length')
        if length:
            self.length = float(length)

        # helper to extract gauge information
        def get_gauge_metric(gauge_info, metric):
            if metric in gauge_info.keys() and gauge_info[metric] is not None:
                return float(gauge_info[metric])

        # get the gauge information if there is a gauge
        if len(self._reach_json['gauges']):

            # save the first gauge to work work since typically there is only one
            self._gauge_info = self._reach_json['gauges'][0]

            # if there are multiple, bias toward cfs if available
            for gauge in self._reach_json['gauges']:

                if gauge['metric_unit'] == 'cfs':
                    self._gauge_info = gauge
                    break

            self.gauge_observation = get_gauge_metric(self._gauge_info, 'gauge_reading')
            self.gauge_id = self._gauge_info['gauge_id']
            self.gauge_units = self._gauge_info['metric_unit']
            self.gauge_metric = self._gauge_info['gauge_metric']

            # for all the gauge ranges correlating to the gauge we are working with, set the ranges
            for rng in self._reach_json['guagesummary']['ranges']:
                if rng['dhid'] == self._gauge_info['dhid']:
                    if rng['range_min'] and rng['gauge_min']:
                        setattr(self, f"gauge_{rng['range_min'].lower()}", float(rng['gauge_min']))
                    if rng['range_max'] and rng['gauge_max']:
                        setattr(self, f"gauge_{rng['range_max'].lower()}", float(rng['gauge_max']))

        # save the update datetime as a true datetime object
        if reach_info['edited']:
            self.update_aw = datetime.datetime.strptime(reach_info['edited'], '%Y-%m-%d %H:%M:%S')

        # process difficulty
        if len(reach_info['class']) and reach_info['class'].lower() != 'none':
            self.difficulty = self._validate_aw_json(reach_info, 'class')
            self._parse_difficulty_string(str(self.difficulty))

        # ensure putin coordinates are present, and if so, add the put-in point to the points list
        if reach_info['plon'] is not None and reach_info['plat'] is not None:
            self._reach_points.append(
                ReachPoint(
                    reach_id=self.reach_id,
                    geometry=Point({
                        'x': float(reach_info['plon']),
                        'y': float(reach_info['plat']),
                        'spatialReference': {'wkid': 4326}
                    }),
                    point_type='access',
                    subtype='putin'
                )
            )

        # ensure take-out coordinates are present, and if so, add take-out point to points list
        if reach_info['tlon'] is not None and reach_info['tlat'] is not None:
            self._reach_points.append(
                ReachPoint(
                    reach_id=self.reach_id,
                    point_type='access',
                    subtype='takeout',
                    geometry=Point({
                        'x': float(reach_info['tlon']),
                        'y': float(reach_info['tlat']),
                        'spatialReference': {'wkid': 4326}
                    })
                )
            )

        # if there is not an abstract, create one from the description
        if (not self.abstract or len(self.abstract) == 0) and (self.description and len(self.description) > 0):

            # remove all line returns, html tags, trim to 500 characters, and trim to last space to ensure full word
            self.abstract = self._cleanup_string(_strip_tags(reach_info['description']))
            self.abstract = self.abstract.replace('\\', '').replace('/n', '')[:500]
            self.abstract = self.abstract[:self.abstract.rfind(' ')]
            self.abstract = self.abstract + '...'

        # get the bounding box for the reach
        if reach_info['bbox'] and reach_info['bbox'] is not None:
            bbox = self._reach_json['info']['bbox']
            envlp_coords = [[bbox[0], bbox[1]], [bbox[0], bbox[3]], [bbox[2], bbox[3]], [bbox[2], bbox[1]],
                            [bbox[0], bbox[1]]]
            self._zoom_envelope = Geometry({"rings": [envlp_coords], "spatialReference": {"wkid": 4326}})

    @property
    def putin_x(self) -> float:
        return self.putin.geometry.x

    @property
    def putin_y(self) -> float:
        return self.putin.geometry.y

    @property
    def takeout_x(self) -> float:
        return self.takeout.geometry.x

    @property
    def takeout_y(self) -> float:
        return self.takeout.geometry.y

    @property
    def difficulty_filter(self) -> float:
        lookup_dict = {
            'I':    1.1,
            'I+':   1.2,
            'II-':  2.0,
            'II':   2.1,
            'II+':  2.2,
            'III-': 3.0,
            'III':  3.1,
            'III+': 3.2,
            'IV-':  4.0,
            'IV':   4.1,
            'IV+':  4.2,
            'V-':   5.0,
            'V':    5.1,
            'V+':   5.3
        }
        return lookup_dict[self.difficulty_maximum]

    @property
    def reach_points_as_features(self) -> List[Feature]:
        """
        Get all the reach points as a list of features.
        :return: List of ArcGIS Python API Feature objects.
        """
        return [pt.as_feature for pt in self._reach_points]

    @property
    def reach_points_as_dataframe(self) -> pd.DataFrame:
        """
        Get the reach points as an Esri Spatially Enabled Pandas DataFrame.
        :return:
        """
        df_pt = pd.DataFrame([pt.as_dictionary for pt in self._reach_points])
        df_pt.spatial.set_geometry('SHAPE')
        return df_pt

    @property
    def centroid(self) -> Point:
        """
        Get a point geometry centroid for the hydroline.

        :return: Point Geometry
            Centroid representing the reach location as a point.
        """
        # if the hydroline is defined, use the centroid of the hydroline
        if isinstance(self.geometry, Polyline):
            pt = Geometry({
                'x': np.mean([self.putin.geometry.x, self.takeout.geometry.x]),
                'y': np.mean([self.putin.geometry.y, self.takeout.geometry.y]),
                'spatialReference': self.putin.geometry.spatial_reference
            })

        # if both accesses are defined, use the mean of the accesses
        elif isinstance(self.putin, ReachPoint) and isinstance(self.takeout, ReachPoint):

            # create a point geometry using the average coordinates
            pt = Geometry({
                'x': np.mean([self.putin.geometry.x, self.takeout.geometry.x]),
                'y': np.mean([self.putin.geometry.y, self.takeout.geometry.y]),
                'spatialReference': self.putin.geometry.spatial_reference
            })

        # if only the putin is defined, use that
        elif isinstance(self.putin, ReachPoint):
            pt = self.putin.geometry

        # and if on the takeout is defined, likely the person digitizing was taking too many hits from the bong
        elif isinstance(self.takeout, ReachPoint):
            pt = self.takeout.geometry

        else:
            pt = None

        return pt

    @property
    def extent(self) -> Tuple[float]:
        """
        Provide the extent of the reach as (xmin, ymin, xmax, ymax)
        :return: Tuple (xmin, ymin, xmax, ymax)
        """
        ext = (
            min(self.putin.geometry.x, self.takeout.geometry.x),
            min(self.putin.geometry.y, self.takeout.geometry.y),
            max(self.putin.geometry.x, self.takeout.geometry.x),
            max(self.putin.geometry.y, self.takeout.geometry.y),
        )
        return ext

    @property
    def reach_search_string(self) -> str:
        if len(self.river_name) and len(self.reach_name):
            ret_str = f'{self.river_name} {self.reach_name}'
        elif len(self.river_name) and not len(self.reach_name):
            ret_str = self.river_name
        elif len(self.reach_name) and not len(self.river_name):
            ret_str = self.reach_name
        else:
            ret_str = ''
        return ret_str

    @property
    def has_point(self) -> bool:
        if self.putin is None and self.takeout is None:
            has_pt = False
        elif self.putin.geometry.type == 'Point' or self.putin.geometry == 'Point':
            has_pt = True
        else:
            has_pt = False

        return has_pt

    @property
    def gauge_min(self):
        gauge_min_lst = [self.gauge_r0, self.gauge_r1, self.gauge_r2, self.gauge_r3, self.gauge_r4, self.gauge_r5]
        gauge_min_lst = [val for val in gauge_min_lst if val is not None]

        g_min = min(gauge_min_lst) if len(gauge_min_lst) else None

        return g_min

    @property
    def gauge_max(self):
        gauge_max_lst = [self.gauge_r4, self.gauge_r5, self.gauge_r6, self.gauge_r7, self.gauge_r8, self.gauge_r9]
        gauge_max_lst = [val for val in gauge_max_lst if val is not None]

        g_max = max(gauge_max_lst) if len(gauge_max_lst) else None

        return g_max

    @property
    def gauge_runnable(self):
        has_all = self.gauge_min and self.gauge_max and self.gauge_observation
        is_between = self.gauge_min < self.gauge_observation < self.gauge_max

        runnable = has_all and is_between

        return runnable

    @property
    def gauge_stage(self):
        metric_keys = ['gauge_r0', 'gauge_r1', 'gauge_r2', 'gauge_r3', 'gauge_r4', 'gauge_r5', 'gauge_r6', 'gauge_r7',
                       'gauge_r8', 'gauge_r9']

        def get_metrics(metric_keys):
            metrics = [getattr(self, key) for key in metric_keys]
            metrics = list(set(val for val in metrics if val is not None))
            metrics.sort()
            return metrics

        metrics = get_metrics(metric_keys)
        if not len(metrics):
            return None

        low_metrics = get_metrics(metric_keys[:6])
        high_metrics = get_metrics(metric_keys[5:])

        if not self.gauge_observation:
            return 'no gauge reading'

        if self.gauge_observation < metrics[0]:
            return 'too low'
        if self.gauge_observation > metrics[-1]:
            return 'too high'

        if len(metrics) == 2 or (len(metrics) == 1 and len(high_metrics) > 0):
            return 'runnable'

        if len(metrics) == 3:
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'lower runnable'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'higher runnable'

        if len(metrics) == 4:
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'medium'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'high'

        if len(metrics) == 5 and len(low_metrics) > len(high_metrics):
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'very low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'medium low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'high'

        if len(metrics) == 5 and len(low_metrics) < len(high_metrics):
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'medium'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium high'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'very high'

        if len(metrics) == 6:
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'medium low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium high'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'high'

        if len(metrics) == 7 and len(low_metrics) > len(high_metrics):
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'very low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium low'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'medium high'
            if metrics[5] < self.gauge_observation < metrics[6]:
                return 'high'

        if len(metrics) == 7 and len(low_metrics) < len(high_metrics):
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'medium low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium high'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'high'
            if metrics[5] < self.gauge_observation < metrics[6]:
                return 'very high'

        if len(metrics) == 8:
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'very low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium low'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'medium high'
            if metrics[5] < self.gauge_observation < metrics[6]:
                return 'high'
            if metrics[6] < self.gauge_observation < metrics[7]:
                return 'very high'

        if len(metrics) == 9 and len(low_metrics) > len(high_metrics):
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'extremely low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'very low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'low'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium low'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'medium'
            if metrics[5] < self.gauge_observation < metrics[6]:
                return 'medium high'
            if metrics[6] < self.gauge_observation < metrics[7]:
                return 'high'
            if metrics[7] < self.gauge_observation < metrics[8]:
                return 'very high'

        if len(metrics) == 9 and len(low_metrics) > len(high_metrics):
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'very low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'medium low'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'medium high'
            if metrics[5] < self.gauge_observation < metrics[6]:
                return 'high'
            if metrics[6] < self.gauge_observation < metrics[7]:
                return 'very high'
            if metrics[7] < self.gauge_observation < metrics[8]:
                return 'extremely high'

        if len(metrics) == 10:
            if metrics[0] < self.gauge_observation < metrics[1]:
                return 'extremely low'
            if metrics[1] < self.gauge_observation < metrics[2]:
                return 'very low'
            if metrics[2] < self.gauge_observation < metrics[3]:
                return 'low'
            if metrics[3] < self.gauge_observation < metrics[4]:
                return 'medium low'
            if metrics[4] < self.gauge_observation < metrics[5]:
                return 'medium'
            if metrics[5] < self.gauge_observation < metrics[6]:
                return 'medium high'
            if metrics[6] < self.gauge_observation < metrics[7]:
                return 'high'
            if metrics[7] < self.gauge_observation < metrics[8]:
                return 'very high'
            if metrics[8] < self.gauge_observation < metrics[9]:
                return 'extremely high'

    @classmethod
    def from_aw(cls, reach_id: str) -> Reach:

        # create instance of reach
        reach = cls(reach_id)

        # download raw JSON from American Whitewater
        raw_json = reach._download_raw_json_from_aw()

        # if a reach does not exist at url, simply a blank response, return false
        if not raw_json:
            return False

        # parse data out of the AW JSON
        reach._parse_aw_json(raw_json)

        # return the result
        return reach

    @classmethod
    def from_arcgis(cls, reach_id, reach_point_layer: ReachPointFeatureLayer, reach_centroid_layer,
                    reach_line_layer: ReachLineFeatureLayer) -> cls:

        # create instance of reach
        reach = cls(reach_id)

        # get a data frame for the centroid, since this is used to store the most reach information
        df_centroid = reach_centroid_layer.query_by_reach_id(reach_id).sdf

        # populate all relevant properties of the reach using the downloaded reach centroid
        for column in df_centroid.columns:
            if hasattr(reach, column):
                setattr(reach, column, df_centroid.iloc[0][column])

        # if reach points provided...is optional
        if reach_point_layer:

            # get the reach points as a spatially enabled dataframe
            df_points = reach_point_layer.query_by_reach_id(reach_id).sdf

            # iterate rows to create reach points in the parent reach object
            for _, row in df_points.iterrows():

                # get a dictionary of values, and swap out geometry for SHAPE
                row_dict = row.to_dict()
                row_dict['geometry'] = row_dict['SHAPE']

                # get a list of ReachPoint input args
                reach_point_args = inspect.getfullargspec(ReachPoint).args

                # create a list of input arguments from the columns in the row
                input_args = []
                for arg in reach_point_args[1:]:
                    if arg in row_dict.keys():
                        input_args.append(row_dict[arg])
                    else:
                        input_args.append(None)

                # use the input args to create a new reach point
                reach_point = ReachPoint(*input_args)

                # add the reach point to the reach points list
                reach._reach_points.append(reach_point)

        # try to get the line geometry, and use this for the reach geometry
        fs_line = reach_line_layer.query_by_reach_id(reach_id)
        if len(fs_line.features) > 0:
            for this_feature in fs_line.features:
                if this_feature.geometry is not None:
                    reach._geometry = Geometry(this_feature.geometry)
                    break

        # return the reach object
        return reach

    def _get_access_list_by_type(self, access_type: str) -> List[ReachPoint]:

        # check to ensure the correct access type is being specified
        valid_typ = access_type == 'putin' or access_type == 'takeout' or access_type == 'intermediate'
        assert valid_typ, 'access type must be either "putin", "takeout" or "intermediate"'

        # return list of all accesses of specified type
        access_lst = [pt for pt in self._reach_points if pt.subtype == access_type and pt.point_type == 'access']

        return access_lst

    def _set_putin_takeout(self, access: ReachPoint, access_type: str) -> ReachPoint:
        """
        Set the putin or takeout using a ReachPoint object.
        :param access: ReachPoint - Required
            ReachPoint geometry delineating the location of the geometry to be modified.
        :param access_type: String - Required
            Either "putin" or "takeout".
        :return:
        """
        # enforce correct object type
        assert type(access) != ReachPoint, f'{access_type} access must be an instance of ReachPoint object type'

        # check to ensure the correct access type is being specified
        assert  access_type != 'putin' and access_type != 'takeout', 'access type must be either "putin" or "takeout"'

        # update the list to NOT include the point we are adding
        self._reach_points = [pt for pt in self._reach_points if pt.subtype != access_type]

        # ensure the new point being added is the right type
        access.point_type = 'access'
        access.subtype = access_type

        # add it to the reach point list
        self._reach_points.append(access)

    @property
    def putin(self) -> ReachPoint:
        access_df = self._get_access_list_by_type('putin')
        if len(access_df) > 0:
            pi = access_df[0]
        else:
            pi = None
        return pi

    @putin.setter
    def putin(self, access: ReachPoint) -> None:
        self._set_putin_takeout(access, 'putin')

    @property
    def takeout(self) -> ReachPoint:
        access_lst = self._get_access_list_by_type('takeout')
        if len(access_lst) > 0:
            to = access_lst[0]
        else:
            to = None
        return to

    @takeout.setter
    def takeout(self, access: ReachPoint) -> None:
        self._set_putin_takeout(access, 'takeout')

    @property
    def intermediate_access_list(self) -> List[ReachPoint]:
        access_df = self._get_access_list_by_type('intermediate')
        if len(access_df) > 0:
            return access_df
        else:
            return []

    def add_intermediate_access(self, access: ReachPoint) -> ReachPoint:
        access.set_type('intermediate')
        self.access_list.append(access)
        return access

    def get_hydroline(self, gis=None):
        """
        Update the putin and takeout coordinates, and trace the hydroline
        using the EPA's WATERS services.
        :param gis: Active GIS for performing hydrology analysis.
        :return:
        """
        # ensure a putin and takeout actually were found
        if self.putin is None or self.takeout is None:
            self.error = True
            self.notes = 'Reach does not appear to have both a put-in and take-out location defined.'
            trace_status = False

        # if there is something to work with, keep going
        else:

            # get the snapped and corrected reach locations for the put-in
            self.putin.snap_to_nhdplus()

            # if a put-in was not located using the WATERS service, flag
            if self.putin.nhdplus_measure is None or self.putin.nhdplus_reach_id is None:
                nhd_status = False

            # if the put-in was located using WATERS, flag as successful
            else:
                nhd_status = True

            # initialize trace_status to False first
            trace_status = False

            if nhd_status:

                # try to trace a few times using WATERS, but if it doesn't work, bingo to Esri Hydrology
                attempts = 0
                max_attempts = 5

                while attempts < max_attempts:

                    try:

                        # use the EPA navigate service to trace downstream
                        waters = WATERS()
                        trace_polyline = waters.get_downstream_navigation_polyline(self.putin.nhdplus_reach_id,
                                                                                   self.putin.nhdplus_measure)

                        # project the takeout geometry to the same spatial reference as the trace polyline
                        takeout_geom = self.takeout.geometry.match_spatial_reference(self.takeout.geometry)

                        # snap the takeout geometry to the hydroline
                        takeout_geom = takeout_geom.snap_to_line(trace_polyline)

                        # update the takeout to the snapped point
                        self.takeout.geometry = takeout_geom

                        # now dial in the coordinates using the EPA service - getting the rest of the attributes
                        self.takeout.snap_to_nhdplus()

                        # ensure a takeout was actually found
                        if self.takeout.nhdplus_measure is None or self.takeout.nhdplus_reach_id is None:
                            self.error = True
                            self.notes = 'Takeout could not be located using EPS\'s WATERS service'
                            trace_status = False

                        else:
                            self._geometry = trace_polyline.trim_at_point(self.takeout.geometry)
                            trace_status = True
                            self.tracing_method = 'EPA WATERS NHD Plus v2'
                            break

                    except:

                        # increment the attempt counter
                        attempts += 1

            # if the put-in has not yet been located using the WATERS service
            if not trace_status:

                # do a little voodoo to get a feature set containing just the put-in
                pts_df = self.reach_points_as_dataframe
                putin_fs = pts_df[
                    (pts_df['point_type'] == 'access')
                    & (pts_df['subtype'] == 'putin')
                ].spatial.to_featureset()

                # use the feature set to get a response from the watershed function using Esri's Hydrology service
                wtrshd_resp = hydrology.watershed(
                    input_points=putin_fs,
                    point_id_field='reach_id',
                    snap_distance=100,
                    snap_distance_units='Meters',
                    gis=gis
                )

                # update the putin if a point was found using the watershed function
                if len(wtrshd_resp._fields) and len(wtrshd_resp.snapped_points.features):
                    putin = self.putin
                    putin_geometry = wtrshd_resp.snapped_points.features[0].geometry
                    putin_geometry['spatialReference'] = wtrshd_resp.snapped_points.spatial_reference
                    putin.geometry = Geometry(putin_geometry)
                    self.set_putin(putin)

                # if a putin was not found, quit swimming in the ocean
                else:
                    self.error = True
                    self.notes = 'Put-in could not be located with neither WATERS nor Esri Hydrology services.'

                # trace using Esri Hydrology services
                attempts = 10
                fail_count = 0

                # set variable for tracking the trace response
                trace_resp = None

                # try to get a trace response
                while fail_count < attempts:
                    try:
                        trace_resp = hydrology.trace_downstream(putin_fs, point_id_field='reach_id', gis=gis)
                        break
                    except:
                        fail_count = fail_count + 1

                # if the trace was successful
                if trace_resp and not self.error:

                    # extract out the trace geometry
                    trace_geom = trace_resp.features[0].geometry
                    trace_geom['spatialReference'] = trace_resp.spatial_reference
                    trace_geom = Geometry(trace_geom)

                    # save the resolution for the smoothing later
                    trace_data_resolution = float(trace_resp.features[0].attributes['DataResolution'])

                    # snap the takeout to the traced line
                    takeout_geom = self.takeout.geometry.snap_to_line(trace_geom)
                    self.takeout.geometry = takeout_geom

                    # trim the reach line to the takeout
                    line_geom = trace_geom.trim_at_point(self.takeout.geometry)

                    # ensure there are more than two vertices for smoothing
                    if line_geom.coordinates().size > 6:

                        # smooth the geometry since the hydrology tracing can appear a little jagged
                        self._geometry = _smooth_geometry(line_geom,
                                                          densify_max_segment_length=trace_data_resolution * 2,
                                                          gis=gis)

                    else:
                        self._geometry = line_geom

                    trace_status = True
                    self.tracing_method = "ArcGIS Online Hydrology Services"

            # if neither of those worked, flag the error
            if not trace_status:
                self.error = True
                self.notes = "The reach could not be trace with neither the EPA's WATERS service nor the Esri " \
                             "Hydrology services."

        return trace_status

    @property
    def geometry(self) -> Polyline:
        """
        Return the reach polyline geometry.
        :return: Polyline Geometry
        """
        return self._geometry

    @property
    def hydroline(self) -> Polyline:
        """
        Return the reach hydroline geometry.
        :return: Polyline Geometry object delineating the hydroline.
        """
        return self._geometry

    def _get_feature_attributes(self) -> dict:
        """helper function for exporting features"""
        srs = pd.Series(dir(self))
        srs = srs[
            (~srs.str.startswith('_'))
            & (~srs.str.contains('as_'))
            & (srs != 'putin')
            & (srs != 'takeout')
            & (srs != 'intermediate_accesses')
            & (srs != 'geometry')
            & (srs != 'has_a_point')
            & (srs != 'centroid')
            ]
        srs = srs[srs.apply(lambda p: not hasattr(getattr(self, p), '__call__'))]
        return {key: getattr(self, key) for key in srs}

    @property
    def as_feature(self) -> Feature:
        """
        Get the reach as an ArcGIS Python API Feature object.
        :return: ArcGIS Python API Feature object representing the reach.
        """
        if self.geometry:
            feat = Feature(geometry=self.geometry, attributes=self._get_feature_attributes())
        else:
            feat = Feature(attributes=self._get_feature_attributes())
        return feat

    @property
    def as_centroid_feature(self) -> Feature:
        """
        Get a feature with the centroid geometry.
        :return: Feature with point geometry for the reach centroid.
        """
        return Feature(geometry=self.centroid, attributes=self._get_feature_attributes())

    @property
    def as_zoom_envelope_feature(self) -> Feature:
        """
        Get a polygon geometry object with a generally accurate zoom envelope.
        :return: Polygon feature complete with attributes.
        """
        if self._zoom_envelope:
            feat = Feature(geometry=self._zoom_envelope, attributes=self._get_feature_attributes())
        else:
            feat = Feature(attributes=self._get_feature_attributes())
        return feat

    def publish(self, reach_line_layer, reach_centroid_layer, reach_point_layer):
        """
        Publish the reach to three feature layers; the reach line layer, the reach centroid layer,
        and the reach points layer.
        :param gis: GIS object providing the credentials.
        :param reach_line_layer: ReachLayer with line geometry to publish to.
        :param reach_centroid_layer: ReachLayer with point geometry for the centroid to publish to.
        :param reach_point_layer: ReachPointLayer
        :return: Boolean True if successful and False if not
        """
        if not self.putin and not self.takeout:
            return False

        # add the reach line if it was successfully traced
        if not self.error:
            resp_line = reach_line_layer.add_reach(self)
            add_line = len(resp_line['addResults'])

        # regardless, add the centroid and points
        resp_centroid = reach_centroid_layer.add_reach(self)
        add_centroid = len(resp_centroid['addResults'])

        resp_point = reach_point_layer.add_reach(self)
        add_point = len(resp_point['addResults'])

        # check results for adds and return correct response
        if not self.error and add_line and add_centroid and add_point:
            return True
        elif add_centroid and add_point:
            return True
        else:
            return False

    def publish_updates(self, reach_line_layer, reach_centroid_layer, reach_point_layer):
        """
        Based on the current status of the reach, push updates to the online Feature Services.
        :param reach_line_layer: ReachLayer with line geometry to publish to.
        :param reach_centroid_layer: ReachLayer with point geometry for the centroid to publish to.
        :param reach_point_layer: ReachPointLayer
        :return: Boolean True if successful and False if not
        """
        if not self.putin and not self.takeout:
            return False

        resp_line = reach_line_layer.update_reach(self)
        update_line = len(resp_line['updateResults'])

        resp_centroid = reach_centroid_layer.update_reach(self)
        update_centroid = len(resp_centroid['updateResults'])

        resp_putin = reach_point_layer.update_putin(self.putin)
        update_putin = len(resp_putin['updateResults'])

        resp_takeout = reach_point_layer.update_takeout(self.takeout)
        update_takeout = len(resp_takeout['updateResults'])

        # check results for adds and return correct response
        if update_line and update_centroid and update_putin and update_takeout:
            return True
        elif update_centroid and update_putin and update_takeout:
            return True
        else:
            return False

    def publish_attribute_updates_only(self, reach_line_layer, reach_centroid_layer):
        """
        Based on the current status of the reach, push updates to the online Feature Services only for attributes.
        :param reach_line_layer: ReachLayer with line geometry to publish to.
        :param reach_centroid_layer: ReachLayer with point geometry for the centroid to publish to.
        :return: Boolean True if successful and False if not
        """
        resp_line = reach_line_layer.update_reach(self)
        if resp_line:
            update_line = len(resp_line['updateResults'])
        else:
            update_line = False

        resp_centroid = reach_centroid_layer.update_reach(self)
        if resp_centroid:
            update_centroid = len(resp_centroid['updateResults'])
        else:
            update_centroid = False

        # check results for adds and return correct response
        if update_line and update_centroid:
            return True
        elif update_centroid:
            return True
        else:
            return False

    def webmap(self, gis=None):
        """
        Display reach and accesses on web map widget.
        :param gis: ArcGIS Python API GIS object instance.
        :return: map widget
        """
        if gis is None and active_gis is not None:
            gis = active_gis
        elif gis is None:
            gis = GIS()

        webmap = gis.map()
        webmap.basemap = 'topo-vector'
        webmap.extent = {
            'xmin': self.extent[0],
            'ymin': self.extent[1],
            'xmax': self.extent[2],
            'ymax': self.extent[3],
            'spatialReference': {'wkid': 4326}
        }
        if self.geometry:
            webmap.draw(
                shape=self.geometry,
                symbol={
                    "type": "esriSLS",
                    "style": "esriSLSSolid",
                    "color": [0, 0, 255, 255],
                    "width": 1.5
                }
            )
        if self.putin.geometry:
            webmap.draw(
                shape=self.putin.geometry,
                symbol={
                    "xoffset": 12,
                    "yoffset": 12,
                    "type": "esriPMS",
                    "url": "http://static.arcgis.com/images/Symbols/Basic/GreenFlag.png",
                    "contentType": "image/png",
                    "width": 24,
                    "height": 24
                }
            )
        if self.takeout.geometry:
            webmap.draw(
                shape=self.takeout.geometry,
                symbol={
                    "xoffset": 12,
                    "yoffset": 12,
                    "type": "esriPMS",
                    "url": "http://static.arcgis.com/images/Symbols/Basic/RedFlag.png",
                    "contentType": "image/png",
                    "width": 24,
                    "height": 24
                }
            )
        if self.as_centroid_feature.geometry:
            webmap.draw(
                shape=self.as_centroid_feature.geometry,
                symbol={
                    "type": "esriPMS",
                    "url": "http://static.arcgis.com/images/Symbols/Basic/CircleX.png",
                    "contentType": "image/png",
                    "width": 24,
                    "height": 24
                }
            )

        return webmap
