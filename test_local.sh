#!/bin/bash

if [ -z "$1" ]; then
    pytest tests/ -s -v --durations 0 -W ignore::DeprecationWarning
else
    pytest tests/ -s -v --durations 0 -W ignore::DeprecationWarning -k $1
fi