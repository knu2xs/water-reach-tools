from setuptools import find_packages, setup

with open('README.md', 'r') as readme:
    long_description = readme.read()

setup(
    name='water_reach_tools',
    package_dir={"": "src"},
    packages=['water_reach_tools'],
    version='0.2.0-dev0',
    description='Tools for working with geographic data for linear water reaches.',
    long_description=long_description,
    author='Joel McCune',
    license='Apache 2.0',
)
