"""Main water reach tools module."""
from uuid import uuid4

from arcgis.features import Feature, FeatureLayer

from .epa_waters import WATERS


class ReachPoint(object):
    """
    Discrete object facilitating working with reach points.
    """

    def __init__(self, reach_id, geometry, point_type, uid=None, subtype=None, name=None, side_of_river=None,
                 collection_method=None, update_date=None, notes=None, description=None, difficulty=None, **kwargs):

        self.reach_id = str(reach_id)
        self.point_type = point_type
        self.subtype = subtype
        self.name = name
        self.nhdplus_measure = None
        self.nhdplus_reach_id = None
        self.collection_method = collection_method
        self.update_date = update_date
        self.notes = notes
        self.description = description
        self.difficulty = difficulty
        self._geometry = None

        self.set_geometry(geometry)
        self.set_side_of_river(side_of_river)  # left or right

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
    def geometry(self):
        """
        Geometry for the access, a point.
        :return: Point Geometry object
            Point where access is located.
        """
        return self._geometry

    def set_geometry(self, geometry):
        """
        Set the geometry for the access.
        :param geometry: Point Geometry Object
        :return: Boolean True if successful
        """
        if geometry.type != 'Point':
            raise Exception('access geometry must be a valid ArcGIS Point Geometry object')
        else:
            self._geometry = geometry
            return True

    def set_side_of_river(self, side_of_river):
        """
        Set the side of the river the access is located on.
        :param side_of_river:
        :return:
        """
        if side_of_river is not None and side_of_river != 'left' and side_of_river != 'right':
            raise Exception('side of river must be either "left" or "right"')
        else:
            self.side_of_river = side_of_river

    def snap_to_nhdplus(self):
        """
        Snap the access geometry to the nearest NHD Plus hydroline, and get the measure and NHD Plus Reach ID
            needed to perform traces against the EPA WATERS Upstream/Downstream service.
        :return: Boolean True when complete
        """
        if self.geometry:
            waters = WATERS()
            epa_point = waters.get_epa_snap_point(self.geometry.x, self.geometry.y)

            # if the EPA WATERSs' service was able to locate a point
            if epa_point:

                # set properties accordingly
                self.set_geometry(epa_point['geometry'])
                self.nhdplus_measure = epa_point['measure']
                self.nhdplus_reach_id = epa_point['id']
                return True

            # if a point was not located, return false
            else:
                return False

    @property
    def as_feature(self):
        """
        Get the access as an ArcGIS Python API Feature object.
        :return: ArcGIS Python API Feature object representing the access.
        """
        return Feature(
            geometry=self._geometry,
            attributes={key: vars(self)[key] for key in vars(self).keys()
                        if key != '_geometry' and not key.startswith('_')}
        )

    @property
    def as_dictionary(self):
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


class _ReachIdFeatureLayer(FeatureLayer):

    @classmethod
    def from_item_id(cls, gis, item_id):
        url = Item(gis, item_id).layers[0].url
        return cls(url, gis)

    @classmethod
    def from_url(cls, gis, url):
        return cls(url, gis)

    def query_by_reach_id(self, reach_id, spatial_reference={'wkid': 4326}):
        return self.query(f"reach_id = '{reach_id}'", out_sr=spatial_reference)

    def flush(self):
        """
        Delete all data!
        :return: Response
        """
        # get a list of all OID's
        oid_list = self.query(return_ids_only=True)['objectIds']

        # if there are features
        if len(oid_list):
            # convert the list to a comma separated string
            oid_deletes = ','.join([str(v) for v in oid_list])

            # delete all the features using the OID string
            return self.edit_features(deletes=oid_deletes)


class ReachPointFeatureLayer(_ReachIdFeatureLayer):

    def add_reach(self, reach):
        """
        Push new reach points to the reach point feature service in bulk.
        :param reach: Reach - Required
            Reach object being pushed to feature service.
        :return: Dictionary response from edit features method.
        """
        # check for correct object type
        if type(reach) != Reach:
            raise Exception('Reach to add must be a Reach object instance.')

        return self.edit_features(adds=reach.reach_points_as_features)

    def _add_reach_point(self, reach_point):
        # add a new reach point to ArcGIS Online
        resp = self.update(adds=[reach_point.as_feature])

        # TODO: handle the response
        return None

    def update_putin_or_takeout(self, access):
        access_resp = self.query(
            f"reach_id = '{access.reach_id}' AND point_type = 'access' AND subtype = '{access.subtype}'",
            return_ids_only=True)['objectIds']
        if len(access_resp):
            oid_access = access_resp[0]
            access_feature = access.as_feature
            access_feature.attributes['OBJECTID'] = oid_access
            return self.edit_features(updates=[access_feature])
        else:
            return self.edit_features(adds=[access.as_feature])

    def update_putin(self, access):
        if not access.subtype == 'putin':
            raise Exception('A put-in access point must be provided to update the put-in.')
        return self.update_putin_or_takeout(access)

    def update_takeout(self, access):
        if not access.subtype == 'takeout':
            raise Exception('A take-out access point must be provided to update the take-out.')
        return self.update_putin_or_takeout(access)

    def _create_reach_point_from_series(self, reach_point):

        # create an access object instance with the required parameters
        access = ReachPoint(reach_point['reach_id'], reach_point['_geometry'], reach_point['type'])

        # for the remainder of the fields from the service, populate if matching key in access object
        for key in [val for val in reach_point.keys() if val not in ['reach_id', '_geometry', 'type']]:
            if key in access.keys():
                access[key] = reach_point[key]

        return access

    def get_putin(self, reach_id):

        # get a pandas series from the feature service representing the putin access
        sdf = self.get_putin_sdf(reach_id)
        putin_series = sdf.iloc[0]
        return self._create_reach_point_from_series(putin_series)

    def get_takeout(self, reach_id):

        # get a pandas series from the feature service representing the putin access
        sdf = self.get_takeout_sdf(reach_id)
        takeout_series = sdf.iloc[0]
        return self._create_reach_point_from_series(takeout_series)


class ReachFeatureLayer(_ReachIdFeatureLayer):

    def query_by_river_name(self, river_name_search):
        field_name = 'name_river'
        where_list = ["{} LIKE '%{}%'".format(field_name, name_part) for name_part in river_name_search.split()]
        where_clause = ' AND '.join(where_list)
        return self.query(where_clause).df

    def query_by_section_name(self, section_name_search):
        field_name = 'name_section'
        where_list = ["{} LIKE '%{}%'".format(field_name, name_part) for name_part in section_name_search.split()]
        where_clause = ' AND '.join(where_list)
        return self.query(where_clause).df

    def add_reach(self, reach):
        """
        Push reach to feature service.
        :param reach: Reach - Required
            Reach object being pushed to feature service.
        :return: Dictionary response from edit features method.
        """

        # check for correct object type
        if type(reach) != Reach:
            raise Exception('Reach to add must be a Reach object instance.')

        # check the geometry type of the target feature service - point or line
        if self.properties.geometryType == 'esriGeometryPoint':
            point_feature = reach.as_centroid_feature
            resp = self.edit_features(adds=[point_feature])

        elif self.properties.geometryType == 'esriGeometryPolyline':
            line_feature = reach.as_feature
            resp = self.edit_features(adds=[line_feature])

        else:
            raise Exception('The feature service geometry type must be either point or polyline.')

        return resp

    def update_reach(self, reach):

        # get oid of records matching reach_id
        oid_lst = self.query(f"reach_id = '{reach.reach_id}'", return_ids_only=True)['objectIds']

        # if a feature already exists - hopefully the case, get the oid, add it to the feature, and push it
        if len(oid_lst) > 0:

            # check the geometry type of the target feature service - point or line
            if self.properties.geometryType == 'esriGeometryPoint':
                update_feat = reach.as_centroid_feature

            elif self.properties.geometryType == 'esriGeometryPolyline':
                update_feat = reach.as_feature

            update_feat.attributes['OBJECTID'] = oid_lst[0]
            resp = self.edit_features(updates=[update_feat])

        # if the feature does not exist, add it
        else:
            resp = self.add_reach(reach)

        return resp

    def update_reach_attributes_only(self, reach):

        # get oid of records matching reach_id
        oid_lst = self.query(f"reach_id = '{reach.reach_id}'", return_ids_only=True)['objectIds']

        # if a feature already exists - hopefully the case, get the oid, add it to the feature, and push it
        if len(oid_lst) > 0:

            # check the geometry type of the target feature service - point or line
            if self.properties.geometryType == 'esriGeometryPoint':
                update_feat = reach.as_centroid_feature

            elif self.properties.geometryType == 'esriGeometryPolyline':
                update_feat = reach.as_feature

            # remove any of the geographic properties from the feature
            for attr in ['putin_x', 'putin_y', 'takeout_x', 'takeout_y', 'extent', 'centroid']:
                del (update_feat.attributes[attr])
            update_feat = Feature(attributes=update_feat.attributes)  # gets rid of geometry

            update_feat.attributes['OBJECTID'] = oid_lst[0]

            # push the update
            resp = self.edit_features(updates=[update_feat])

            return resp

        else:

            return False
