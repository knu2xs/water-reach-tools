from __future__ import annotations
import os
from typing import Union

from arcgis.gis import GIS, Item
from arcgis.features import FeatureLayer, Feature
from arcgis.geometry import SpatialReference


class _ReachIdFeatureLayer(FeatureLayer):

    @classmethod
    def from_item_id(cls, gis: GIS, item_id: str) -> _ReachIdFeatureLayer:
        url = Item(gis, item_id).layers[0].url
        return cls(url, gis)

    @classmethod
    def from_url(cls, gis: GIS, url: str) -> _ReachIdFeatureLayer:
        return cls(url, gis)

    def query_by_reach_id(self, reach_id: str, spatial_reference: Union[int, dict, SpatialReference] = {'wkid': 4326}):
        return self.query(f"reach_id = '{reach_id}'", out_sr=spatial_reference)

    def flush(self) -> dict:
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

    def update(self, reach):

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

    def update_attributes_only(self, reach):

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
            for attr in ['extent']:
                del (update_feat.attributes[attr])
            update_feat = Feature(attributes=update_feat.attributes)  # gets rid of geometry

            update_feat.attributes['OBJECTID'] = oid_lst[0]

            # push the update
            resp = self.edit_features(updates=[update_feat])

            return resp

        else:

            return False

    def update_stage(self, reach):

        # get oid of records matching reach_id
        oid_lst = self.query(f"reach_id = '{reach.reach_id}'", return_ids_only=True)['objectIds']

        # if a feature already exists - hopefully the case, get the oid, add it to the feature, and push it
        if len(oid_lst) > 0:

            # check the geometry type of the target feature service - point or line
            if self.properties.geometryType == 'esriGeometryPoint':
                update_feat = reach.as_centroid_feature

            elif self.properties.geometryType == 'esriGeometryPolyline':
                update_feat = reach.as_feature

            # remove properties not needed, which is most of them
            update_keys = ['gauge_runnable', 'gauge_stage', 'gauge_observation']
            attrs = {k: update_feat.attributes[k] for k in update_feat.attributes.keys() if k in update_keys}

            # create new feature without geometry and only needed attributes
            update_feat = Feature(attributes=attrs)

            # tack on the object id retrieved initally
            update_feat.attributes['OBJECTID'] = oid_lst[0]

            # push the update
            resp = self.edit_features(updates=[update_feat])

            return resp

        else:

            return False


class ReachPointFeatureLayer(_ReachIdFeatureLayer):

    def add_reach(self, reach):
        """
        Push new reach points to the reach point feature service in bulk.
        :param reach: Reach - Required
            Reach object being pushed to feature service.
        :return: Dictionary response from edit features method.
        """
        from .reach import Reach

        # check for correct object type
        if type(reach) != Reach:
            raise Exception('Reach to add must be a Reach object instance.')

        # TODO: Ensure reach does not already exist
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
        from .reach import ReachPoint

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


class ReachLineFeatureLayer(_ReachIdFeatureLayer):

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
        from .reach import Reach

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


def update_stage(reach_id, line_lyr_id=os.getenv('REACH_LINE_ID'), centroid_lyr_id=os.getenv('REACH_CENTROID_ID')):
    """
    Update the reach stage by the id.
    :param reach_id: Reach ID uniquely identifying the reach
    :return: Boolean success or failure.
    """
    from .reach import Reach
    reach = Reach.get_from_aw(reach_id)
    for lyr_id in [line_lyr_id, centroid_lyr_id]:
        lyr = ReachFeatureLayer.from_item_id(lyr_id)
        lyr.update_reach_attributes_only(reach)