#!/usr/bin/env python

"""Tests for `water_reach_tools` package."""
import os

from arcgis.gis import GIS
from arcgis.geometry import Polyline
from dotenv import load_dotenv
import pytest

from water_reach_tools import Reach

# load the environment variables using dotenv
load_dotenv('../.env')

@pytest.fixture
def gis():
    """Instantiate the GIS object"""
    gis = GIS(
        url=os.getenv('ARCGIS_URL', 'https://arcgis.com'),
        username=os.getenv('ARCGIS_USERNAME', None),
        password=os.getenv('ARCGIS_PASSWORD', None)
    )
    return gis


@pytest.fixture
def reach_centroid_lyr(gis):
    return gis.content.get(os.getenv('REACH_CENTROID_ID'))


@pytest.fixture
def reach_line_lyr(gis):
    return gis.content.get(os.getenv('REACH_LINE_ID'))


@pytest.fixture
def reach_points_lyr(gis):
    return gis.content.get(os.getenv('REACH_POINTS_ID'))


def test_parse_difficulty_string():
    difficulty = 'IV-V(V+)'
    reach = Reach(reach_id)
    reach._parse_difficulty_string(difficulty)
    if reach.difficulty_minimum != 'IV':
        status = False
    elif reach.difficulty_maximum != 'V':
        status = False
    elif reach.difficulty_outlier != 'V+':
        status = False
    else:
        status = True
    assert status


# Lower White Salmon testing
reach_id = 2156
putin_x = -121.629656
putin_y = 45.764117
takeout_x = -121.646106
takeout_y = 45.718817


def test_reach_init():
    reach = Reach(reach_id)
    assert str(reach_id) == reach.reach_id


def test_download_raw_json_from_aw():
    reach = Reach(reach_id)
    raw_json = reach._download_raw_json_from_aw()
    assert 'CContainerViewJSON_view' in raw_json


def test_get_from_aw():
    reach = Reach.get_from_aw(reach_id)
    assert reach.river_name == 'Little White Salmon'


def test_putin():
    reach = Reach.get_from_aw(reach_id)
    putin = reach.putin
    assert (putin_x, putin_y) == (putin.geometry.x, putin.geometry.y)


def test_takeout():
    reach = Reach.get_from_aw(reach_id)
    takeout = reach.takeout
    assert (takeout_x, takeout_y) == (takeout.geometry.x, takeout.geometry.y)


def test_trace_result():
    reach = Reach.get_from_aw(reach_id)
    reach.snap_putin_and_takeout_and_trace()
    assert isinstance(reach.geometry, Polyline)
