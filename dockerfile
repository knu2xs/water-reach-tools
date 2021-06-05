FROM thinkwhere/gdal-python:latest AS builder

RUN pip install \
    arcgis \
    jupyterlab \
    nodejs \
    numpy
