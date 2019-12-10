from arcgis.geometry import Geometry, Polyline
import requests
import shapely


class WATERS(object):

    @staticmethod
    def _get_point_indexing(x, y, search_distance=5, return_geometry=False):
        """
        Get the raw response JSON for snapping points to hydrolines from the WATERS Point Indexing Service
            (https://www.epa.gov/waterdata/point-indexing-service)
        :param x: X coordinate (longitude) in decimal degrees (WGS84)
        :param y: Y coordinate (latitude) in decimal degrees (WGS84)
        :param search_distance: Distance radius to search for a hydroline to snap to in kilometers (default 5km)
        :param return_geometry: Whether or not to return the geometry of the matching hydroline (default False)
        :return: Raw response JSON as a dictionary
        """
        url = "https://ofmpub.epa.gov/waters10/PointIndexing.Service"

        query_string = {
            "pGeometry": "POINT({} {})".format(x, y),
            "pGeometryMod": "WKT,SRSNAME=urn:ogc:def:crs:OGC::CRS84",
            "pPointIndexingMethod": "DISTANCE",
            "pPointIndexingMaxDist": search_distance,
            "pOutputPathFlag": True,
            "pReturnFlowlineGeomFlag": return_geometry,
            "optOutCS": "SRSNAME=urn:ogc:def:crs:OGC::CRS84",
            "optOutPrettyPrint": 0,
            "f": "json"
        }

        response = requests.get(
            url=url,
            params=query_string
        )

        return response.json()

    def get_epa_snap_point(self, x, y):
        """
        Get the snapped point defined both with a geometry, and as an ID and measure needed for tracing.
        :param x: X coordinate (longitude) in decimal degrees (WGS84)
        :param y: Y coordinate (latitude) in decimal degrees (WGS84)
        :return: Dictionary with three keys; geometry, measure, and id. Geometry is an ArcGIS Python API Point Geometry
        object. Measure and ID are values required as input parameters when using tracing WATER services.
        """
        # hit the EPA's Point Indexing service to true up the point
        response_json = self._get_point_indexing(x, y)

        # if the point is not in the area covered by NHD (likely in Canada)
        if response_json['output'] is None:
            return False

        else:

            # extract out the coordinates
            coordinates = response_json['output']['end_point']['coordinates']

            # construct a Point geometry along with sending back the ComID and Measure needed for tracing
            return {
                "geometry": Geometry({'x': coordinates[0], 'y': coordinates[1], 'spatialReference': {"wkid": 4326}}),
                "measure": response_json["output"]["ary_flowlines"][0]["fmeasure"],
                "id": response_json["output"]["ary_flowlines"][0]["comid"]
            }

    @staticmethod
    def _get_epa_downstream_navigation_response(putin_epa_reach_id, putin_epa_measure):
        """
        Make a call to the WATERS Navigation Service and trace downstream using the putin snapped using
            the EPA service with keys for geometry, measure and feature id.
        :param putin_epa_reach_id: Required - Integer or String
            Reach id of EPA NHD Plus reach to start from.
        :param putin_epa_measure: Required - Integer
            Measure along specified reach to start from.
        :return: Raw response object from REST call.
        """

        # url for the REST call
        url = "http://ofmpub.epa.gov/waters10/Navigation.Service"

        # input parameters as documented at https://www.epa.gov/waterdata/navigation-service
        query_string = {
            "pNavigationType": "DM",
            "pStartComID": putin_epa_reach_id,
            "pStartMeasure": putin_epa_measure,
            "pMaxDistanceKm": 5000,
            "pReturnFlowlineAttr": True,
            "f": "json"
        }

        # since requests don't always work, enable repeated tries up to 10
        attempts = 0
        status_code = 0

        while attempts < 10 and status_code != 200:

            # make the actual response to the REST endpoint
            resp = requests.get(url, query_string)

            # increment the attempts and pull out the status code
            attempts = attempts + 1
            status_code = resp.status_code

            # if the status code is anything other than 200, provide a message of status
            if status_code != 200:
                print('Attempt {:02d} failed with status code {}'.format(attempts, status_code))

        return resp

    @staticmethod
    def _get_epa_updown_ptp_response(putin_epa_reach_id, putin_epa_measure, takeout_epa_reach_id,
                                     takeout_epa_measure):
        """
        Make a call to the WATERS Navigation Service and trace downstream using the putin snapped using
            the EPA service with keys for geometry, measure and feature id.
        :param putin_epa_reach_id: Required - Integer or String
            Reach id of EPA NHD Plus reach to start from.
        :param putin_epa_measure: Required - Integer
            Measure along specified reach to start from.
        :param takeout_epa_reach_id: Required - Integer or String
            Reach id of EPA NHD Plus reach to end at.
        :param takeout_epa_measure: Required - Integer
            Measure along specified reach to end at.
        :return: Raw response object from REST call.
        """

        # url for the REST call
        url = "http://ofmpub.epa.gov/waters10/Navigation.Service"

        # input parameters as documented at https://www.epa.gov/waterdata/upstreamdownstream-search-service
        url = "http://ofmpub.epa.gov/waters10/UpstreamDownStream.Service"
        query_string = {
            "pNavigationType": "PP",
            "pStartComID": putin_epa_reach_id,
            "pStartMeasure": putin_epa_measure,
            "pStopComID": takeout_epa_reach_id,
            "pStopMeasure": takeout_epa_measure,
            "pFlowlinelist": True,
            "f": "json"
        }

        # since requests don't always work, enable repeated tries up to 10
        attempts = 0
        status_code = 0

        while attempts < 10 and status_code != 200:

            # make the actual response to the REST endpoint
            resp = requests.get(url, query_string)

            # increment the attempts and pull out the status code
            attempts = attempts + 1
            status_code = resp.status_code

            # if the status code is anything other than 200, provide a message of status
            if status_code != 200:
                print('Attempt {:02d} failed with status code {}'.format(attempts, status_code))

        return resp

    @staticmethod
    def _epa_navigation_response_to_esri_polyline(navigation_response):
        """
        From the raw response returned from the trace create a single ArcGIS Python API Line Geometry object.
        :param navigation_response: Raw trace response received from the REST endpoint.
        :return: Single continuous ArcGIS Python API Line Geometry object.
        """
        resp_json = navigation_response.json()

        # if any flowlines were found, combine all the coordinate pairs into a single continuous line
        if resp_json['output']['ntNavResultsStandard']:

            # extract the dict descriptions of the geometries and convert to Shapely geometries
            flowline_list = [shapely.geometry.shape(flowline['shape'])
                             for flowline in resp_json['output']['ntNavResultsStandard']]

            # use Shapely to combine all the lines into a single line
            flowline = shapely.ops.linemerge(flowline_list)

            # convert the LineString to a Polyline, and return the result
            arcgis_geometry = Polyline({'paths': [[c for c in flowline.coords]], 'spatialReference': {'wkid': 4326}})

            return arcgis_geometry

        # if no geometry is found, puke
        else:
            raise Exception('the tracing operation did not find any hydrolines')

    @staticmethod
    def _epa_updown_response_to_esri_polyline(updown_response):
        """
        From the raw response returned from the trace create a single ArcGIS Python API Line Geometry object.
        :param updown_response: Raw trace response received from the REST endpoint.
        :return: Single continuous ArcGIS Python API Line Geometry object.
        """
        resp_json = updown_response.json()

        # if any flowlines were found, combine all the coordinate pairs into a single continuous line
        if resp_json['output']['flowlines_traversed']:

            # extract the dict descriptions of the geometries and convert to Shapely geometries
            flowline_list = [shapely.geometry.shape(flowline['shape'])
                             for flowline in resp_json['output']['flowlines_traversed']]

            # use Shapely to combine all the lines into a single line
            flowline = shapely.ops.linemerge(flowline_list)

            # convert the LineString to a Polyline, and return the result
            arcgis_geometry = Polyline({'paths': [[c for c in flowline.coords]], 'spatialReference': {'wkid': 4326}})

            return arcgis_geometry

        # if no geometry is found, puke
        else:
            raise Exception('the tracing operation did not find any hydrolines')

    def get_downstream_navigation_polyline(self, putin_epa_reach_id, putin_epa_measure):
        """
        Make a call to the WATERS Navigation Search Service and trace downstream using the putin snapped using
            the EPA service with keys for geometry, measure and feature id.
        :param putin_epa_reach_id: Required - Integer or String
            Reach id of EPA NHD Plus reach to start from.
        :param putin_epa_measure: Required - Integer
            Measure along specified reach to start from.
        :return: Single continuous ArcGIS Python API Line Geometry object.
        """
        resp = self._get_epa_downstream_navigation_response(putin_epa_reach_id, putin_epa_measure)
        return self._epa_navigation_response_to_esri_polyline(resp)

    def get_updown_ptp_polyline(self, putin_epa_reach_id, putin_epa_measure, takeout_epa_reach_id, takeout_epa_measure):
        """
        Make a call to the WATERS Upstream/Downstream Search Service and trace downstream using the putin and takeout
            snapped using the EPA service with keys for measure and feature id.
        :param putin_epa_reach_id: Required - Integer or String
            Reach id of EPA NHD Plus reach to start from.
        :param putin_epa_measure: Required - Integer
            Measure along specified reach to start from.
        :param takeout_epa_reach_id: Required - Integer or String
            Reach id of EPA NHD Plus reach to end at.
        :param takeout_epa_measure: Required - Integer
            Measure along specified reach to end at.
        :return: Single continuous ArcGIS Python API Line Geometry object.
        """
        resp = self._get_epa_updown_ptp_response(putin_epa_reach_id, putin_epa_measure, takeout_epa_reach_id,
                                                 takeout_epa_measure)
        return self._epa_updown_response_to_esri_polyline(resp)
