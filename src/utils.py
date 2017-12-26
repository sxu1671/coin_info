import csv
import pandas as pd
import numpy as np
import os
import time
import re
import requests
import gdax


api_input = open("APIKeyGDAX.txt", "r")
codes = api_input.readlines()
codes = [code.rstrip('\n') for code in codes]
GDAXapi_key = codes[0]
GDAXapi_secret = codes[1]
GDAXpass = codes[2]

auth_client = gdax.AuthenticatedClient(GDAXapi_key, GDAXapi_secret, GDAXpass)

request = auth_client.get_accounts()
