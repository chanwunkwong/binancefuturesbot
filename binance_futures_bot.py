import websocket, json, pprint, talib, numpy
import config
import requests, time, hmac, hashlib
from binance.client import Client
from binance.enums import *

## Constants
TRADE_SYMBOL = "XRPUSDT"
ROLLING_PERIODS = 20
NUMBER_SD = 2
BB_RANGE_PERCENTILE = 95
AUM_TARGET_USD = 12800000
AUM_PERCENTAGE_STOP_GAIN = 0.125    # expected gain as a % of AUM after a win trade
AUM_PERCENTAGE_CUT_LOSS = 0.1       # expected gain as a % of AUM after a loss trade
TRADE_LEVERAGE = 5

## base end point for binance futures trading REST API
base_url_futures = "https://fapi.binance.com"

## Connect to websocket to get real time futures price streaming
SOCKET = "wss://fstream.binance.com/ws/" + TRADE_SYMBOL.lower() + "@kline_1m"

# Create a Client object
client = Client(config.API_KEY, config.API_SECRET)

###############################
# Functions within on_message #
###############################

#####################################################################################################

def fillPreviousPriceToCloses(client, closes, message):
    oldCandles = client.get_historical_klines(TRADE_SYMBOL, Client.KLINE_INTERVAL_1MINUTE, "1 hour ago UTC")
    if len(closes) == 0:
        for oldCandle in oldCandles:
            closes.append(float(oldCandle[4]))
    json_message = json.loads(message)
    candle = json_message['k']
    is_candle_closed = candle['x']
    close = candle['c']
    return closes, close, is_candle_closed

def calculateBollingerBandData(closes, rolling_periods, number_sd):
    np_closes = numpy.array(closes)
    upper, middle, lower = talib.BBANDS(np_closes, timeperiod = rolling_periods, nbdevup = number_sd, nbdevdn = number_sd, matype = 0)
    # store the 1m data series of bbRange, bbRangePercent and bbPercent
    bbRanges.append(round(upper[-1] - lower[-1], 4))           
    temp = (upper - lower) / np_closes * 100
    bbRangePercentsRaw = temp.tolist()
    bbRangePercents = [item for item in bbRangePercentsRaw if item == item]
    bbPercents.append(round((np_closes[-1] - middle[-1]) / (upper[-1] - middle[-1]) * 100, 2)) 
    return upper, middle, lower, bbRanges, bbRangePercents, bbPercents

def callAPI():
    data_timestamp = createTimeStamp()
    pResultAccount = {'timestamp': data_timestamp}
    pResultAccount['signature'] = hashing(param2string(pResultAccount))
    resultAccount = requests.get(url = base_url_futures + '/fapi/v2/account?' + param2string(pResultAccount), headers = {'X-MBX-APIKEY': config.API_KEY})
    pResultBookTicker = {'symbol': TRADE_SYMBOL, 'timestamp': data_timestamp}
    pResultBookTicker['signature'] = hashing(param2string(pResultBookTicker))
    resultBookTicker = requests.get(url = base_url_futures + '/fapi/v1/ticker/bookTicker?' + param2string(pResultBookTicker), headers = {'X-MBX-APIKEY': config.API_KEY})
    
    dict_balance_usdt = resultAccount.json()['assets'][1]
    for item in resultAccount.json()['positions']:
        if item['symbol'] == TRADE_SYMBOL:
            dict_balance_trade_symbol = item
    dict_order_book = resultBookTicker.json()
    
    return dict_balance_usdt, dict_balance_trade_symbol, dict_order_book

def GeneratePortfolioSnapshot(bbRanges, bbPercents, bbRangePercents):

    dict_balance_usdt, dict_balance_trade_symbol, dict_order_book = callAPI()

    balanceBegin = round(float(dict_balance_usdt['walletBalance']), 2)
    balanceEnd = round(float(dict_balance_usdt['marginBalance']), 2)
    currentPNL = round(float(dict_balance_usdt['unrealizedProfit']), 2)
    gsScore = round(numpy.log(balanceEnd / AUM_TARGET_USD) / numpy.log(1.1), 2)
    quantityTradeSymbol = float(dict_balance_trade_symbol['positionAmt'])
    priceEntry = float(dict_balance_trade_symbol['entryPrice'])
    leverage = float(dict_balance_trade_symbol['leverage'])

    print("")
    print("{}".format(time.strftime("%a, %d %b %Y %H:%M:%S")))
    print("")
    print("Portfolio Snaphot")
    print("=================")
    print("Balance")
    print("Begin (USDT): {}".format(balanceBegin))
    print("End (USDT): {}".format(balanceEnd))
    print("P&L (USDT): {} ({}%)".format(currentPNL, round(currentPNL / balanceBegin * 100, 2)))
    print("Geometric Score (GS): {}".format(gsScore))
    print("")
    print("Balance ({}): {}".format(TRADE_SYMBOL, quantityTradeSymbol))
    print("Entry Price (USDT): {}".format(priceEntry))
    print("Leverage: {}".format(leverage))
    print("")
    print("Bollinger Band")
    print("==============")
    print("bbRange: {}".format(bbRanges[-1]))
    print("bbPercent: {}%".format(bbPercents[-1]))
    print("bbRangePercent: {}% / bbRangePercent Percentile: {}%".format(round(bbRangePercents[-1], 4), round(numpy.percentile(bbRangePercents, BB_RANGE_PERCENTILE), 4)))
    print("")

def generateTradeSignal(closes, upper, middle, lower, bbRanges, bbRangePercents):

    ### LONG logic
    # 1. 2nd last candle closed below LB
    # 2. last candle closed above LB
    # 3. last candle below MID, i.e. bbRangePecent < 0
    # 4. last bbRangePercent < 95th percentile
    # 5. last bbRange >= $0.01

    logicBuy1 = (closes[-2] < lower[-2])
    logicBuy2 = (closes[-1] > lower[-1])
    logicBuy3 = (closes[-1] < middle[-1])
    logicBuy4 = (bbRangePercents[-1] <= numpy.percentile(bbRangePercents, BB_RANGE_PERCENTILE))
    logicBuy5 = (bbRanges[-1] >= 0.01)

    logicBuy = logicBuy1 & logicBuy2 & logicBuy3 & logicBuy4 & logicBuy5  

    ### place buy market order
    # 0. check if current XRP quantity = 0, if yes continue, if no then exit
    # 1. get current balance
    # 2. make sure current leverage = 5
    # 3. trading size = 5x leverage on current balance, calculate XRP quantity to trade, round down to 1 d.p.
    # 4. set cut loss = market price (trade price) * 98%, round up to 4 d.p.
    # 5. set stop gain = market price (trade price) * 102.5%, round up to 4 d.p.
    
    
    # SHORT logic
    # 1. 2nd last candle closed above UB
    # 2. last candle closed below UB
    # 3. last candle above MID, i.e. bbRangePecent > 0
    # 4. last bbRangePercent < 95th percentile
    # 5. last bbRange >= $0.01

    logicSell1 = (closes[-2] > upper[-2])
    logicSell2 = (closes[-1] < upper[-1])
    logicSell3 = (closes[-1] > middle[-1])
    logicSell4 = (bbRangePercents[-1] <= numpy.percentile(bbRangePercents, BB_RANGE_PERCENTILE))
    logicSell5 = (bbRanges[-1] >= 0.01)

    logicSell = logicSell1 & logicSell2 & logicSell3 & logicSell4 & logicSell5  

    ### place sell market order
    # 0. check if current XRP quantity = 0, if yes continue, if no then exit
    # 1. get current balance
    # 2. make sure current leverage = 5
    # 3. trading size = 5x leverage on current balance, calculate XRP quantity to trade, round down to 1 d.p.
    # 4. set cut loss = market price (trade price) * 102%, round down to 4 d.p.
    # 5. set stop gain = market price (trade price) * 97.5%, round down to 4 d.p.

    return logicBuy, logicSell

#####################################################################################################

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
bbRangePercentsRaw = []
bbRangePercents = []
bbPercents = []

def on_open(ws):
    print('opened connection')

def on_close(ws):
    print('closed connection')

def on_message(ws, message):

    global closes, bbRanges, bbRangePercentsRaw, bbRangePercents, bbPercents

    # fill back the values of close price into list "closes"
    closes, close, is_candle_closed = fillPreviousPriceToCloses(client, closes, message)

    if True: #is_candle_closed:
        
        closes.append(float(close))

        if True:

            upper, middle, lower, bbRanges, bbRangePercents, bbPercents = calculateBollingerBandData(closes, ROLLING_PERIODS, NUMBER_SD)

            GeneratePortfolioSnapshot(bbRanges, bbPercents, bbRangePercents)

            logicBuy, logicSell = generateTradeSignal(closes, upper, middle, lower, bbRanges, bbRangePercents)

            if logicBuy:
                print("BUY!")

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