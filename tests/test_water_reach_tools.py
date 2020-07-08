#!/usr/bin/env python

"""Tests for `water_reach_tools` package."""
import os

from arcgis.gis import GIS
from dotenv import load_dotenv
import pytest

from water_reach_tools import water_reach_tools

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


@pytest.fixture
def response():
    """Sample pytest fixture.

    See more at: http://doc.pytest.org/en/latest/fixture.html
    """
    # import requests
    # return requests.get('https://github.com/audreyr/cookiecutter-pypackage')


def test_content(response):
    """Sample pytest test function with the pytest fixture as an argument."""
    # from bs4 import BeautifulSoup
    # assert 'GitHub' in BeautifulSoup(response.content).title.string
