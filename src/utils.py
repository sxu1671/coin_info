import csv
import pandas as pd
import numpy as np
import os
import time
import re
import requests
import gdax # pip install python-gdax
from datetime import datetime


# need a text file named "APIKeyGDAX.txt" containing the codes in this format
"""
<API Key>\n
<API Secret>\n
<Passphrase>\n
"""
api_input = open("APIKeyGDAX.txt", "r")
codes = api_input.readlines()
codes = [code.rstrip('\n') for code in codes]
GDAXapi_key = codes[0]
GDAXapi_secret = codes[1]
GDAXpass = codes[2]

auth_client = gdax.AuthenticatedClient(GDAXapi_key, GDAXapi_secret, GDAXpass)

request = auth_client.get_accounts()
profile_ids = {account['currency']: account['id'] for account in request}

fills = auth_client.get_fills()

# appends extra columns with the average rolling price and coin balance
def get_average_price(table):
    #checks
    table = table.sort_values(by='created_at').reset_index(drop=True)
    unique_coins = table['product_id'].unique()
    unique_coins = [str(coin) for coin in unique_coins]
    if 'nan' in unique_coins and len(unique_coins) != 2:
        print("More than one currency in average price check")
        return
    elif 'nan' not in unique_coins and len(unique_coins) != 1:
        print("More than one currency in average price check")
        return
    start_index = 0
    table['price'] = table['price'].astype(float)
    table['size'] = table['size'].astype(float)
    if 'rolling_average' in table.columns:
        index = table['rolling_average'].index[table['rolling_average'].apply(np.isnan)]
        table_index = table.index.values.tolist()
        start_index = table_index.index(index[0])
    if start_index == 0:
        table['rolling_average'] = pd.Series(table.loc[0, 'price'])
        table['rolling_stash'] = pd.Series(table.loc[0, 'size'])
        start_index += 1
    curr_price_index = start_index
    while curr_price_index < len(table):
        if table['type'][curr_price_index] == 'buy' or table['type'][curr_price_index] == 'deposit':
            prev_price = table['rolling_average'][curr_price_index-1]
            prev_stash = table['rolling_stash'][curr_price_index-1]
            this_price = table['price'][curr_price_index]
            this_stash = table['size'][curr_price_index]
            total_stash = prev_stash + this_stash
            table.loc[curr_price_index, 'rolling_average'] = (prev_price*(prev_stash/total_stash)) + (this_price*(this_stash/total_stash))
            table.loc[curr_price_index, 'rolling_stash'] = total_stash
        else:
            remove_stash = table['size'][curr_price_index]
            table.loc[curr_price_index, 'rolling_average'] = table['rolling_average'][curr_price_index-1]
            table.loc[curr_price_index, 'rolling_stash'] = table['rolling_stash'][curr_price_index-1] + remove_stash
        curr_price_index += 1
    return table


# creates the trades data table
def create_fills_table(coin, fills):
    fills_df = pd.DataFrame(fills[0])
    fills_df.loc[:, 'created_at'] = fills_df['created_at'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%S.%fZ'))
    fills_df = fills_df.sort_values(by='created_at').reset_index(drop=True)
    product_id = coin + '-USD'
    coin_chart = fills_df[fills_df['product_id'] == product_id].reset_index(drop=True)
    coin_chart.rename(columns = {'side':'type'}, inplace = True)
    coin_chart['size'] = coin_chart['size'].astype(float)
    negated_sells = coin_chart.apply(lambda x: -x.loc['size'] if x.loc['type'] == 'sell' else x.loc['size'], axis=1).astype('float')
    coin_chart['size'] = negated_sells
    return coin_chart


# creates the transfers data table
def create_transfers_table(coin):
    coin_hist = auth_client.get_account_history(profile_ids[coin])
    coin_hist = pd.DataFrame(coin_hist[0])
    coin_transfers = coin_hist[coin_hist['type'] == 'transfer']
    coin_transfers.loc[:, 'created_at'] = coin_transfers['created_at'].apply(lambda x: datetime.strptime(x, '%Y-%m-%dT%H:%M:%S.%fZ'))
    coin_transfers.loc[:, 'transfer_id'] = coin_transfers['details'].apply(lambda x: x.get('transfer_id'))
    coin_transfers.rename(columns = {'amount': 'size'}, inplace=True)
    coin_transfers.loc[:, 'id'] = coin_transfers['id'].astype(str)
    coin_transfers.loc[:, 'size'] = coin_transfers['size'].astype(float)
    coin_transfers = coin_transfers.reset_index(drop=True)
    prices = []
    types = []
    for index, row in coin_transfers.iterrows():
        if row['size'] < 0:
            cost = float(input("What is the loss (in USD) of the {0} {1} for the withdrawal at {2}".format(-row['size'], coin, row['created_at'])))
            price = cost/(-row['size'])
            prices.append(price)
            types.append('withdrawal')
        else:
            cost = float(input("What is the gain (in USD) of the {0} {1} for the deposit at {2}".format(row['size'], coin, row['created_at'])))
            price = cost/row['size']
            prices.append(price)
            types.append('deposit')
    prices_series = pd.Series(prices)
    types_series = pd.Series(types)
    coin_transfers.loc[:, 'price'] = prices_series
    coin_transfers.loc[:, 'type'] = types_series
    return coin_transfers


# appends transfers data table onto fills data table
def append_transfers(transfers, main_table):
    transfers = transfers.loc[:, ['size', 'created_at', 'id', 'type', 'transfer_id', 'price']]
    main = pd.concat([main_table, transfers], ignore_index=True)
    return main


# for viewing purposes, filters out extra data, does not alter the original table
def drop_nonessential(table):
    columns_to_drop = set(['order_id', 'id', 'trade_id', 'user_id', 'liquidity', 'profile_id', 'transfer_id'])
    columns_exist = columns_to_drop.intersection(table.columns)
    if list(columns_exist) != []:
        dropped_table = table.drop(list(columns_exist), axis=1)
    return dropped_table


# calculates the gain for specific subtable (filter by coin first)
def get_gains(table):
    sells_withdraws = table[(table['type'] == 'sell') | (table['type'] == 'withdraw')]
    price_diff = (sells_withdraws['price'] - sells_withdraws['rolling_average'])*np.negative(sells_withdraws['size'])
    return price_diff.sum()


# uses above functions to create one continous table with transfers and trades data
def get_chart(coin):
    coin_transfers = create_transfers_table(coin)
    coin_fills = create_fills_table(coin, fills)
    coin_table = append_transfers(coin_transfers, coin_fills)
    coin_table = coin_table.sort_values(by='created_at').reset_index(drop=True)
    coin_avg = get_average_price(coin_table)
    return coin_avg

# Example call
LTC_avg = get_chart('LTC')
print(LTC_avg)