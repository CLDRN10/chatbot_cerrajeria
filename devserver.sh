#!/bin/sh
source .venv/bin/activate
python -u -m flask --app main run --debug --host=0.0.0.0 --port=5000
