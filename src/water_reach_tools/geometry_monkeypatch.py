from arcgis.features import GeoAccessor
from arcgis.geometry import Geometry, Point, Polyline, find_transformation, project, SpatialReference
from shapely import ops
import importlib

# check what packages are available
HASARCPY = True if importlib.util.find_spec("arcpy") else False
HASSHAPELY = True if importlib.util.find_spec("shapely") else False


@classmethod
def from_shapely(cls, shapely_geometry, spatial_reference=None):
    """
    Creates a Python API Geometry object from a Shapely geometry object.
    :param shapely_geometry: Required Shapely Geometry
        Single instance of Shapely Geometry to be converted to ArcGIS
        Python API geometry instance.
    :param spatial_reference: Optional SpatialReference
        Defines the spatial reference for the output geometry.
    :return: Python API Geometry object
    """
    if HASSHAPELY:
        geometry = cls(shapely_geometry.__geo_interface__)
        if spatial_reference:
            geometry.spatial_reference = spatial_reference
        return geometry
    else:
        raise Exception('Shapely is required to execute from_shapely.')


def snap_to_line(self, polyline_geometry):
    """
    Returns a new point snapped to the closest location along the input line geometry.
    :param polyline_geometry: Required arcgis.geometry.Polyline
        ArcGIS Polyline geometry the Point will be snapped to.
    :return: arcgis.geometry.Point
        ArcGIS Point geometry coincident with the nearest location along the input
        ArcGIS Polyline object
    """
    if not isinstance(self, Point):
        raise Exception('Snap to line can only be performed on a Point geometry object.')
    if polyline_geometry.type.lower() != 'polyline':
        raise Exception('Snapping target must be a single ArcGIS Polyline geometry object.')
    if self.spatial_reference is None:
        raise Warning('The spatial reference for the point to be snapped to a line is not defined.')
    if polyline_geometry.spatial_reference is None:
        raise Warning('The spatial reference of the line being snapped to is not defined.')
    if (self.spatial_reference != polyline_geometry.spatial_reference and
            self.spatial_reference.wkid != polyline_geometry.spatial_reference.wkid and
            self.spatial_reference.latestWkid != polyline_geometry.spatial_reference.wkid and
            self.spatial_reference.wkid != polyline_geometry.spatial_reference.latestWkid and
            self.spatial_reference.latestWkid != polyline_geometry.spatial_reference.latestWkid):
        raise Exception('The spatial reference for the point and the line are not the same.')

    if HASARCPY:
        polyline_geometry = polyline_geometry.as_arcpy
        return Point(self.as_arcpy.snapToLine(in_point=polyline_geometry))

    elif HASSHAPELY:
        polyline_geometry = polyline_geometry.as_shapely
        point_geometry = self.as_shapely
        snap_point = polyline_geometry.interpolate(polyline_geometry.project(point_geometry))
        snap_point = Point({'x': snap_point.x, 'y': snap_point.y, 'spatialReference': self.spatial_reference})
        return snap_point

    else:
        raise Exception('Either arcpy or Shapely is required to perform snap_to_line')


def split_at_point(self, point_geometry):
    """
    Returns two polyline geometry objects as a list split at the intersection of the line.
    :param point_geometry: Required arcgis.geometry.Point
        ArcGIS Point geometry defining the location the line will be split at.
    :return: Two item list of arcgis.geometry.Polyline objects
        List of two ArcGIS Polyline objects, one on either side of the input point location.
    """
    if not isinstance(self, Polyline):
        raise Exception('Split at point can only be performed on a Polyline geometry object.')
    if not isinstance(point_geometry, Point):
        raise Exception('Split at point requires a Point geometry object to define the split location.')
    if self.spatial_reference is None:
        raise Warning('The spatial reference for the line to be split is not defined.')
    if point_geometry.spatial_reference is None:
        raise Warning('The spatial reference of the point defining the split location is not defined.')
    if (self.spatial_reference != point_geometry.spatial_reference and
            self.spatial_reference.wkid != point_geometry.spatial_reference.wkid and
            self.spatial_reference.latestWkid != point_geometry.spatial_reference.wkid and
            self.spatial_reference.wkid != point_geometry.spatial_reference.latestWkid and
            self.spatial_reference.latestWkid != point_geometry.spatial_reference.latestWkid):
        raise Exception('The spatial reference for the line and point are not the same.')

    #     if HASARCPY:
    #         raise Exception('Not yet implemented')

    if HASSHAPELY:
        linestring_geometry = self.as_shapely
        point_geometry = point_geometry.as_shapely
        split_result = ops.split(linestring_geometry, point_geometry)
        polyline_list = [Geometry({
            'paths': [line_string.__geo_interface__['coordinates']],
            'spatialReference': self.spatial_reference})
            for line_string in split_result]
        return polyline_list

    else:
        raise Exception('Shapely is required to perform split_at_point')


def trim_at_point(self, point_geometry):
    """
    Returns one polyline geometry object trimmed at a location defined by a point.
    :param point_geometry: Required arcgis.geometry.Point
        ArcGIS Point geometry defining the location the line will be trimmed at.
    :return: arcgis.geometry.Polyline object
        An trimmed ArcGIS Polyline object
    """
    return self.split_at_point(point_geometry)[0]


arcpy_avail = True if importlib.util.find_spec("arcpy") else False

if arcpy_avail:
    import arcpy


def change_spatial_reference_df(input_dataframe: pd.DataFrame, output_spatial_reference: [int, SpatialReference] = 4326,
                                input_spatial_reference: [int, SpatialReference] = None,
                                transformation_name: str = None) -> pd.DataFrame:
    """
    Project input Spatially Enabled Dataframe to a desired output spatial reference, applying a
        transformation if needed due to the geographic coordinate system changing.
    Args:
        input_dataframe: Valid Spatially Enabled DataFrame
        output_spatial_reference: Optional - Desired output Spatial Reference. Default is
            4326 (WGS84).
        input_spatial_reference: Optional - Only necessary if the Spatial Reference is not
            properly defined for the input data geometry.
        transformation_name: Optional - Transformation name to be used, if needed, to
            convert between spatial references. If not explicitly provided, this will be
            inferred based on the spatial reference of the input data and desired output
            spatial reference.
    Returns: Spatially Enabled DataFrame in the desired output spatial reference.
    """
    # ensure the geometry is set
    geom_col_lst = [c for c in input_dataframe.columns if input_dataframe[c].dtype.name.lower() == 'geometry']
    assert len(geom_col_lst) > 0, 'The DataFrame does not appear to have a geometry column defined. This can be ' \
                                  'accomplished using the "input_dataframe.spatial.set_geometry" method.'

    # save the geometry column to a variable
    geom_col = geom_col_lst[0]

    # ensure the input spatially enabled dataframe validates
    assert input_dataframe.spatial.validate(), 'The DataFrame does not appear to be valid.'

    # if a spatial reference is set for the dataframe, just use it
    if input_dataframe.spatial.sr is not None:
        in_sr = input_dataframe.spatial.sr

    # if a spatial reference is explicitly provided, but the data does not have one set, use the one provided
    elif input_spatial_reference is not None:

        # check the input
        assert isinstance(input_spatial_reference, int) or isinstance(input_spatial_reference, SpatialReference), \
            f'input_spatial_reference must be either an int referencing a wkid or a SpatialReference object, ' \
            f'not {type(input_spatial_reference)}.'

        if isinstance(input_spatial_reference, int):
            in_sr = SpatialReference(input_spatial_reference)
        else:
            in_sr = input_spatial_reference

    # if the spatial reference is not set, common for data coming from geojson, check if values are in lat/lon
    # range, and if so, go with WGS84, as this is likely the case if in this range
    else:

        # get the bounding values for the data
        x_min, y_min, x_max, y_max = input_dataframe.spatial.full_extent

        # check the range of the values, if in longitude and latitude range
        wgs_range = True if (x_min > -181 and y_min > -91 and x_max < 181 and y_max < 91) else False
        assert wgs_range, 'Input data for projection data must have a spatial reference, or one must be provided.'

        # if the values are in range, run with it
        in_sr = SpatialReference(4326)

    # ensure the output spatial reference is a SpatialReference object instance
    if isinstance(output_spatial_reference, SpatialReference):
        out_sr = output_spatial_reference
    else:
        out_sr = SpatialReference(output_spatial_reference)

    # copy the input spatially enabled dataframe since the project function changes the dataframe in place
    out_df = input_dataframe.copy()
    out_df.spatial.set_geometry(geom_col)

    # if arcpy is available, use it to find the transformation
    if arcpy_avail and transformation_name is None:

        # get any necessary transformations using arcpy, which returns only a list of transformation names
        trns_lst = arcpy.ListTransformations(in_sr.as_arcpy, out_sr.as_arcpy)

    # otherwise we will have to use the geometry rest endpoint to find transformations
    elif transformation_name is None:

        # explicitly ensure find_transformations has a gis instance
        gis = active_gis if active_gis else GIS()

        # get any transformations, if needed due to changing geographic spatial reference, as a list of dicts
        trns_lst = find_transformation(in_sr, out_sr, gis=gis)['transformations']

    # apply across the geometries using apply since it recognizes the transformation correctly if transformation
    # is necessary and also tries arcpy first, and if not available, rolls back to rest resources elegantly
    if len(trns_lst) or transformation_name is not None:
        trns = transformation_name if transformation_name is not None else trns_lst[0]
        out_df[geom_col] = out_df[geom_col].apply(lambda geom: geom.project_as(out_sr, trns))

    # otherwise, do the same thing using the apply method since the geoaccessor project method is not working reliably
    # and only if necessary if the spatial reference is being changed
    elif in_sr.wkid != out_sr.wkid:
        out_df[geom_col] = out_df[geom_col].apply(lambda geom: geom.project_as(out_sr))

    # ensure the spatial column is set
    if not len([c for c in out_df.columns if out_df[c].dtype.name.lower() == 'geometry']):
        out_df.spatial.set_geometry(geom_col)

    return out_df


def change_spatial_reference_geom(self, output_spatial_reference):
    """
    Change the geometry to another spatial reference and automatically
    apply a transformation if necessary.
    :param output_spatial_reference: Required - SpatialReference
        Spatial reference object defining the output spatial reference.
    :return: Geometry object in new spatial reference.
    """
    # get the wkid for the input and output
    if type(output_spatial_reference) == int:
        wkid_out = output_spatial_reference
    elif type(output_spatial_reference) == SpatialReference:
        wkid_out = SpatialReference['wkid']
    else:
        raise Exception('Valid output spatial reference must be provided.')

    wkid_in = self.spatial_reference['wkid']

    # if the spatial references match, don't do anything
    if wkid_in == wkid_out:
        return self

    # get the best applicable transformation, if needed
    transformation_list = find_transformation(wkid_in, wkid_out)['transformations']

    # if a transformation IS needed, project using it
    if len(transformation_list):
        out_geom = project([self], wkid_in, wkid_out, transformation_list[0])[0]

    # if a transformation IS NOT needed, project without
    else:
        out_geom = project([self], wkid_in, wkid_out)[0]

    # add the spatial reference to the geometry, since it does not have it in the response
    out_geom.spatial_reference = SpatialReference(wkid=wkid_out)

    return out_geom


def match_spatial_reference(self, match_geometry):
    """
    Match the spatial reference of the calling geometry to another geometry.
    Typically used to get data into single spatial reference for subsequent
    analysis.
    :param match_geometry: Required arcgis.geometry.Geometry
        Another target geometry to ensure the source spatial reference matches to.
    :return: arcgis.geometry.Geometry
        Same geometry projected to new coordinate system.
    """
    # pull the wkid off the inputs
    wkid_in = self.spatial_reference['wkid']
    wkid_out = match_geometry.spatial_reference['wkid']

    # if the spatial references match, don't do anything
    if wkid_in == wkid_out:
        return self

    # get the best applicable transformation, if needed
    transformation_list = find_transformation(wkid_in, wkid_out)['transformations']

    # if a transformation IS needed, project using it
    if len(transformation_list):
        out_geom = project([self], wkid_in, wkid_out, transformation_list[0])[0]

    # if a transformation IS NOT needed, project without
    else:
        out_geom = project([self], wkid_in, wkid_out)[0]

    # add the spatial reference to the geometry, since it does not have it in the response
    out_geom.spatial_reference = match_geometry.spatial_reference

    return out_geom


Geometry.from_shapely = from_shapely
Geometry.snap_to_line = snap_to_line
Geometry.split_at_point = split_at_point
Geometry.trim_at_point = trim_at_point
Geometry.change_spatial_reference = change_spatial_reference_geom
Geometry.match_spatial_reference = match_spatial_reference

GeoAccessor.change_spatial_reference = change_spatial_reference_df
