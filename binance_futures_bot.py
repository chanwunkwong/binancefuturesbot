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
ORDER_BUFFER = 0.005

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
    ### ALL logic
    # 1. last bbRangePercent < 95th percentile
    # 2. last bbRange >= $0.01
    # 3. No holding in TRADE_SYMBOL
    logicAll1 = (bbRangePercents[-1] <= numpy.percentile(bbRangePercents, BB_RANGE_PERCENTILE))
    logicAll2 = (bbRanges[-1] >= 0.01)
    dict_balance_usdt, dict_balance_trade_symbol, dict_order_book = callAPI()
    logicAll3 = float(dict_balance_trade_symbol['positionAmt']) == 0
    logicAll = logicAll1 & logicAll2 & logicAll3

    ### LONG logic
    # 1. 2nd last candle closed below LB
    # 2. last candle closed above LB
    # 3. last candle below MID, i.e. bbRangePecent < 0
    logicBuy1 = (closes[-2] < lower[-2])
    logicBuy2 = (closes[-1] > lower[-1])
    logicBuy3 = (closes[-1] < middle[-1])
    logicBuy = logicBuy1 & logicBuy2 & logicBuy3 & logicAll  
    
    # SHORT logic
    # 1. 2nd last candle closed above UB
    # 2. last candle closed below UB
    # 3. last candle above MID, i.e. bbRangePecent > 0
    logicSell1 = (closes[-2] > upper[-2])
    logicSell2 = (closes[-1] < upper[-1])
    logicSell3 = (closes[-1] > middle[-1])
    logicSell = logicSell1 & logicSell2 & logicSell3 & logicAll

    if logicBuy & ~logicSell:
        direction = "BUY"
    elif ~logicBuy & logicSell:
        direction = "SELL"
    else:
        direction = "NO SIGNAL"
    return direction

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

def TradeOrder(direction):
    # auto calculate trade quantity
    dict_balance_usdt, dict_balance_trade_symbol, dict_order_book = callAPI()
    quantityTradeSymbol = float(dict_balance_trade_symbol['positionAmt'])
    balance = float(dict_balance_usdt['availableBalance'])
    leverage = float(dict_balance_trade_symbol['leverage'])

    if direction == "BUY":
        tradePrice = float(dict_order_book['askPrice'])
        stopPriceCutLoss = round(tradePrice * (1 - AUM_PERCENTAGE_CUT_LOSS / leverage), 4)
        stopPriceStopGain = round(tradePrice * (1 + AUM_PERCENTAGE_STOP_GAIN / leverage), 4)
        sideCover = "SELL"
    elif direction == "SELL":
        tradePrice = float(dict_order_book['bidPrice'])
        stopPriceCutLoss = round(tradePrice * (1 + AUM_PERCENTAGE_CUT_LOSS / leverage), 4)
        stopPriceStopGain = round(tradePrice * (1 - AUM_PERCENTAGE_STOP_GAIN / leverage), 4)
        sideCover = "BUY"

    # make sure no position yet
    if (quantityTradeSymbol == 0):
        quantity = round(balance * leverage / tradePrice * (1 - ORDER_BUFFER), 1)
    
        try:
            data_timestamp = createTimeStamp()
            pTrade = {'symbol': TRADE_SYMBOL, 'side': direction, 'type': 'MARKET', 'quantity': quantity, 'timestamp': data_timestamp}
            pTrade['signature'] = hashing(param2string(pTrade))
            requests.post(url = base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': config.API_KEY}, data = pTrade)
            #send cut loss limit order
            data_timestamp = createTimeStamp()
            pCutLoss = {'symbol': TRADE_SYMBOL, 'side': sideCover, 'type': 'STOP', 'quantity': quantity, 'price': stopPriceCutLoss, 'stopPrice': stopPriceCutLoss, 'timeInForce': "GTC", 'reduceOnly': True, 'timestamp': data_timestamp}
            pCutLoss['signature'] = hashing(param2string(pCutLoss))
            requests.post(url = base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': config.API_KEY}, data = pCutLoss)
            #send stop gain limit order
            data_timestamp = createTimeStamp()
            pStopGain = {'symbol': TRADE_SYMBOL, 'side': sideCover, 'type': 'TAKE_PROFIT', 'quantity': quantity, 'price': stopPriceStopGain, 'stopPrice': stopPriceStopGain, 'timeInForce': "GTC", 'reduceOnly': True, 'timestamp': data_timestamp}
            pStopGain['signature'] = hashing(param2string(pStopGain))
            requests.post(url = base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': config.API_KEY}, data = pStopGain)
            return True
        except Exception as e:
            return False

def killSingleLeftCoverOrder():
    dict_balance_usdt, dict_balance_trade_symbol, dict_order_book = callAPI()
    quantityTradeSymbol = float(dict_balance_trade_symbol['positionAmt'])
    data_timestamp = createTimeStamp()
    p = {'symbol': TRADE_SYMBOL, 'timestamp': data_timestamp}
    p['signature'] = hashing(param2string(p))
    result = requests.get(url = base_url_futures + '/fapi/v1/openOrders?' + param2string(p), headers = {'X-MBX-APIKEY': config.API_KEY})
    numOutCoverOrder = len(result.json())
    # conditions to kill all outstanding orders
    # except the case (have position & have both 2 cut-loss/stop-gain orders), must kill all orders outstanding
    if not ((quantityTradeSymbol != 0) & (numOutCoverOrder == 2)):
        data_timestamp = createTimeStamp()
        pKill = {'symbol': TRADE_SYMBOL, 'timestamp': data_timestamp}
        pKill['signature'] = hashing(param2string(pKill))
        requests.delete(url = base_url_futures + '/fapi/v1/allOpenOrders', headers = {'X-MBX-APIKEY': config.API_KEY}, data = pKill)

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

    if is_candle_closed:
        ### always check if there is any single pending order 
        ### (the unfinished side of the cut-loos or stop-gain cover trade order)
        
        #killSingleLeftCoverOrder()

        closes.append(float(close))

        upper, middle, lower, bbRanges, bbRangePercents, bbPercents = calculateBollingerBandData(closes, ROLLING_PERIODS, NUMBER_SD)

        GeneratePortfolioSnapshot(bbRanges, bbPercents, bbRangePercents)

        direction = generateTradeSignal(closes, upper, middle, lower, bbRanges, bbRangePercents)

        if direction == "NO SIGNAL":
            print("No signal yet...")
        else:
            TradeOrder(direction)
            if direction == "BUY":
                print("BUY!!!!!!!!!!!!!!!!!!")
            elif direction == "SELL":
                print("SELL!!!!!!!!!!!!!!!!!!")

#####################################################################################################

ws = websocket.WebSocketApp(SOCKET, on_open = on_open, on_close = on_close, on_message = on_message)
ws.run_forever()