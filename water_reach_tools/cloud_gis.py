import os

from arcgis.gis import GIS
from arcgis.features import FeatureLayer, Item
from dotenv import load_dotenv, find_dotenv

# get the dotenv files from any parent directories
load_dotenv(find_dotenv())


class ReachGIS(GIS):

    def __init__(self, url=None, username=None, password=None, key_file=None, cert_file=None, verify_cert=True, set_active=True, client_id=None, profile=None, **kwargs):

        # if not explicitly specified, try to get the necessary information from a dotenv
        if not url:
            url = os.getenv('GIS_URL')

        if not username and not password:
            username = os.getenv('GIS_USERNAME')
            password = os.getenv('GIS_PASSWORD')

        super().__init__(url=url, username=username, password=password, key_file=key_file, cert_file=cert_file, verify_cert=verify_cert, set_active=set_active, client_id=client_id, profile=profile, **kwargs)

        # attempt to load the respective relevant feature layers from the dotenv file
        centroid_id = os.getenv('REACH_CENTROID_ID')
        self.centroid_feature_layer = self._get_feature_layer_by_object_id(centroid_id) if centroid_id else None

        line_id = os.getenv('REACH_LINE_ID')
        self.line_feature_layer = self._get_feature_layer_by_object_id(line_id) if line_id else None

        points_id = os.getenv('REACH_POINTS_ID')
        self.points_feature_layer = self._get_feature_layer_by_object_id(points_id) if points_id else None

    def _get_feature_layer_by_object_id(self, object_id):
        return self.content.get(object_id).layers[0]
