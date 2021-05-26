import websocket, json, pprint, talib, numpy
import config
import requests,time, hmac, hashlib
from binance.client import Client
from binance.enums import *

## Constants
TRADE_SYMBOL = "XRPUSDT"
ROLLING_PERIODS = 20
NUMBER_SD = 2
BB_RANGE_PERCENTILE = 95
AUM_TARGET_USD = 12800000


## base end point for binance futures trading REST API
base_url_futures = "https://fapi.binance.com"

## Connect to websocket to get real time futures price streaming
SOCKET = "wss://fstream.binance.com/ws/" + TRADE_SYMBOL.lower() + "@kline_1m"

# Create a Client object
# client = Client(config.API_KEY, config.API_SECRET)
# info = client.get_account()
# print(info)

######################################
# Functions for placing trade orders #
######################################

#####################################################################################################

def createTimeStamp():
    return int(time.time() * 1000)

def param2string(param):
    s = ""
    for k in param.keys():
        s += k
        s += "="
        s += str(param[k])
        s += "&"
    return s[:-1]

def hashing(query_string):
    return hmac.new(config.API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def TradeOrder(symbol, side, quantity):
    try:
        data_type = 'MARKET'
        data_timestamp = createTimeStamp()
        p = {'symbol': symbol, 'side': side, 'type': data_type, 'quantity': quantity, 'timestamp': data_timestamp}
        p['signature'] = hashing(param2string(p))
        requests.post(url = base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': config.API_KEY}, data = p)
        return True
    except Exception as e:
        return False

#####################################################################################################

###########################
# Functions for websocket #
###########################

#####################################################################################################

closes = []
bbRanges = []
bbRangePercents = []

def on_open(ws):
    print('opened connection')

def on_close(ws):
    print('closed connection')

def on_message(ws, message):

    global closes, bbRanges, bbRangePercents

    # print('received message')
    json_message = json.loads(message)
    # pprint.pprint(json_message)

    candle = json_message['k']

    is_candle_closed = candle['x']
    close = candle['c']

    if is_candle_closed:
        
        closes.append(float(close))

        if len(closes) >= 3: #ROLLING_PERIODS:

            np_closes = numpy.array(closes)
            upper, middle, lower = talib.BBANDS(np_closes, timeperiod = min(max(3, len(closes)), ROLLING_PERIODS), nbdevup = NUMBER_SD, nbdevdn = NUMBER_SD, matype = 0)
            bbRangePercent = (np_closes - middle) / (upper - middle) * 100
            ## store the 1m data series of bbRange and bbRangePercent
            bbRanges.append(round(upper[-1] - lower[-1], 4))
            bbRangePercents.append(round(bbRangePercent[-1], 2))

            print("{} minutue(s) passed. Latest BB range is {} and BB percent is {}.".format(len(closes), bbRanges[-1], bbRangePercents[-1]))
            print("BB Range percentile is {}".format(numpy.percentile(bbRanges, BB_RANGE_PERCENTILE)))
            
            # Trade Logic
            #================
            ### LONG logic
            # 1. 2nd last candle closed below LB
            # 2. last candle closed above LB
            # 3. last candle below MID, i.e. bbRangePecent < 0
            # 4. last bbRange < 95th percentile
            # 5. last bbRange >= $0.1

            logicBuy1 = (closes[-2] < lower[-2])
            logicBuy2 = (closes[-1] > lower[-1])
            logicBuy3 = (closes[-1] < middle[-1])
            logicBuy4 = (bbRanges[-1] <= numpy.percentile(bbRanges, BB_RANGE_PERCENTILE))
            logicBuy5 = (bbRanges[-1] >= 0.01)

            logicBuy = logicBuy1 & logicBuy2 & logicBuy3 & logicBuy4 & logicBuy5  

            ### place buy market order
            # 0. check if current XRP quantity = 0, if yes continue, if no then exit
            # 1. get current balance
            # 2. make sure current leverage = 5
            # 3. trading size = 5x leverage on current balance, calculate XRP quantity to trade, round down to 1 d.p.
            # 4. set cut loss = market price (trade price) * 98%, round up to 4 d.p.
            # 5. set stop gain = market price (trade price) * 102.5%, round up to 4 d.p.
            
            if logicBuy:
                print("BUY!")
            # SHORT logic
            # 1. 2nd last candle closed above UB
            # 2. last candle closed below UB
            # 3. last candle above MID, i.e. bbRangePecent > 0
            # 4. last bbRange < 95th percentile
            # 5. last bbRange >= $0.1

            logicSell1 = (closes[-2] > upper[-2])
            logicSell2 = (closes[-1] < upper[-1])
            logicSell3 = (closes[-1] > middle[-1])
            logicSell4 = (bbRanges[-1] <= numpy.percentile(bbRanges, BB_RANGE_PERCENTILE))
            logicSell5 = (bbRanges[-1] >= 0.01)

            logicSell = logicSell1 & logicSell2 & logicSell3 & logicSell4 & logicSell5  

            ### place sell market order
            # 0. check if current XRP quantity = 0, if yes continue, if no then exit
            # 1. get current balance
            # 2. make sure current leverage = 5
            # 3. trading size = 5x leverage on current balance, calculate XRP quantity to trade, round down to 1 d.p.
            # 4. set cut loss = market price (trade price) * 102%, round down to 4 d.p.
            # 5. set stop gain = market price (trade price) * 97.5%, round down to 4 d.p.

            if logicSell:
                print("SELL!")

            if (~logicBuy) & (~logicSell):
                print("No signal yet...")

            # if last_rsi > RSI_OVERBOUGHT:
            #     if  in_position:
            #         print("Overbought! Sell!")
            #         order_succeeded = order(TRADE_SYMBOL, TRADE_QUANTITY, SIDE_SELL)
            #         if order_succeeded:
            #             in_position = False
            #     else:
            #         print("It is overbought, but we don't have any. Nothing to do.")

        #     if last_rsi < RSI_OVERSOLD:
        #         if not in_position:
        #             print("Oversold! Buy!")
        #             order_succeeded = order(TRADE_SYMBOL, TRADE_QUANTITY, SIDE_BUY)
        #             if order_succeeded:
        #                 in_position = True
        #         else:
        #             print("It is oversold, but we already own it. Nothing to do.")

#####################################################################################################

ws = websocket.WebSocketApp(SOCKET, on_open = on_open, on_close = on_close, on_message = on_message)
ws.run_forever()

            # data_timestamp = createTimeStamp()
            # p = {'timestamp': data_timestamp}
            # p['signature'] = hashing(param2string(p))
            # result = requests.get(url = base_url_futures + '/fapi/v2/balance?' + param2string(p), headers = {'X-MBX-APIKEY': config.API_KEY})

