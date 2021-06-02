import config, csv, hashlib, hmac, json, numpy, requests, talib, time, websocket
from binance.client import Client
from binance.enums import *

## Constants
TRADE_SYMBOL = "XRPUSDT"
TRADE_SYMBOL_DECIMALS = 4
TRADE_SYMBOL_MIN_QUANTITY = 0.1
MODE = "REAL"                       # ["REAL", "TEST"]
ROLLING_PERIODS = 20
NUMBER_SD = 2
BB_RANGE_PERCENTILE = 95
AUM_TARGET_USD = 12800000
TRADE_LEVERAGE = 5
TRADE_QUANTITY_BUFFER = 0.02

if (MODE == "REAL"):
    AUM_PERCENTAGE_STOP_GAIN = 0.125    # expected gain as a % of AUM after a win trade
    AUM_PERCENTAGE_CUT_LOSS = 0.1       # expected gain as a % of AUM after a loss trade
elif (MODE == "TEST"): 
    AUM_PERCENTAGE_STOP_GAIN = 0.01
    AUM_PERCENTAGE_CUT_LOSS = 0.01

## Connect to websocket to get real time futures price streaming
SOCKET = "wss://fstream.binance.com/ws/" + TRADE_SYMBOL.lower() + "@kline_1m"
client = Client(config.API_KEY, config.API_SECRET)

class CallAPI:
    def __init__(self):
        self.symbol = TRADE_SYMBOL
        self.timestamp = int(time.time() * 1000)
        self.RecvWindow = 50000
        self.__key = config.API_KEY
        self.__secret = config.API_SECRET
        self.__base_url_futures = "https://fapi.binance.com"
    def __param2string(self, param):
        s = ""
        for k in param.keys():
            s += k + "=" + str(param[k]) + "&"
        return s[:-1]
    def __hashing(self, query_string):
        return hmac.new(self.__secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    def getAccountInfo(self):
        p = {'recvWindow': self.RecvWindow, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v2/account?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def getBookTicker(self):
        p = {'recvWindow': self.RecvWindow, 'symbol': self.symbol, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v1/ticker/bookTicker?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def dict_balance_usdt(self):
        return self.getAccountInfo()['assets'][1]
    def dict_balance_trade_symbol(self):
        for item in self.getAccountInfo()['positions']:
            if item['symbol'] == self.symbol:
                return item
    def getPosition(self):
        p = {'symbol': self.symbol, 'recvWindow': self.RecvWindow, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v2/positionRisk?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()[0]   
   ############################################################################################################
    def tradeOpen(self, direction, quantity):
        p = {'recvWindow': self.RecvWindow, 'symbol': self.symbol, 'side': direction, 'type': 'MARKET', 'quantity': quantity, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.post(url = self.__base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': self.__key}, data = p)
        return (response.status_code)
    def tradeClose(self, direction, price, quantity, type):
        p = {'recvWindow': self.RecvWindow, 'symbol': self.symbol, 'side': direction, 'type': type, 'quantity': quantity, 'price': price, 'stopPrice': price, 'timeInForce': "GTC", 'reduceOnly': True, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.post(url = self.__base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': self.__key}, data = p)
        return (response.status_code)
    ############################################################################################################
    def getOpenOrder(self):
        p = {'recvWindow': self.RecvWindow, 'symbol': self.symbol, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v1/openOrders?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def killAllOrder(self):
        p = {'recvWindow': self.RecvWindow, 'symbol': self.symbol, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        requests.delete(url = self.__base_url_futures + '/fapi/v1/allOpenOrders', headers = {'X-MBX-APIKEY': self.__key}, data = p)
    def changeLeverage(self, leverage):
        p = {'symbol': TRADE_SYMBOL, 'leverage': leverage,'recvWindow': self.RecvWindow, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.post(url = self.__base_url_futures + '/fapi/v1/leverage', headers = {'X-MBX-APIKEY': self.__key}, data = p)
        return response.json()
    def checkLeverageBracket(self):
        p = {'symbol': self.symbol, 'recvWindow': self.RecvWindow, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v1/leverageBracket?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()[0]['brackets']
    def getMarketDepth(self, limit):
        p = {'symbol': self.symbol, 'limit': limit, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v1/depth?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def getTradeHistory(self):
        p = {'symbol': self.symbol, 'recvWindow': self.RecvWindow, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v1/userTrades?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def confirmCrossMargin(self):
        if self.getPosition()['marginType'] != 'cross':
            p = {'symbol': TRADE_SYMBOL, 'marginType': "CROSS", 'recvWindow': self.RecvWindow, 'timestamp': self.timestamp}
            p['signature'] = self.__hashing(self.__param2string(p))
            requests.post(url = self.__base_url_futures + '/fapi/v1/marginType', headers = {'X-MBX-APIKEY': self.__key}, data = p)

def getClose(message):
    json_message = json.loads(message)
    candle = json_message['k']
    is_candle_closed = candle['x']
    close = candle['c']
    return close, is_candle_closed

def calculateBollingerBandData(closes, rolling_periods, number_sd):
    np_closes = numpy.array(closes)
    upper, middle, lower = talib.BBANDS(np_closes, timeperiod = min(max(3, len(closes)), rolling_periods), nbdevup = number_sd, nbdevdn = number_sd, matype = 0)
    # store the 1m data series of bbRange, bbRangePercent and bbPercent
    bbRanges.append(round(upper[-1] - lower[-1], TRADE_SYMBOL_DECIMALS))           
    bbPercents.append(round((np_closes[-1] - middle[-1]) / (upper[-1] - middle[-1]) * 100, 2)) 
    return bbRanges, bbPercents

def GeneratePortfolioSnapshot(bbRanges, bbPercents):
    callAPI = CallAPI()
    balanceBegin = round(float(callAPI.dict_balance_usdt()['walletBalance']), 2)
    balanceEnd = round(float(callAPI.dict_balance_usdt()['marginBalance']), 2)
    currentPNL = round(float(callAPI.dict_balance_usdt()['unrealizedProfit']), 2)
    gsScore = round(numpy.log(balanceEnd / AUM_TARGET_USD) / numpy.log(1.1), 2)
    quantityTradeSymbol = float(callAPI.getPosition()['positionAmt'])
    priceEntry = round(float(callAPI.getPosition()['entryPrice']), TRADE_SYMBOL_DECIMALS)
    currentPrice = round(float(callAPI.getPosition()['markPrice']), TRADE_SYMBOL_DECIMALS)
    leverage = int(callAPI.getPosition()['leverage'])
    lastDirection = getLastDirection()

    print("")
    print("Portfolio Snaphot ({})".format(time.strftime("%a, %d %b %Y %H:%M:%S")))
    print("=================")
    print("Begin (USDT): {} / End (USDT): {} / P&L (USDT): {} ({}%) / Geometric Score (GS): {}".format(balanceBegin, balanceEnd, currentPNL, round(currentPNL / balanceBegin * 100, 2), gsScore))
    print("Balance ({}): {} / Entry Price (USDT): {} / Current Price (USDT): {} / Leverage: {}".format(TRADE_SYMBOL, quantityTradeSymbol, priceEntry, currentPrice, leverage))
    print("bbRange: {} / bbPercent: {}% / Last Trade Side: {}".format(bbRanges[-1], bbPercents[-1], lastDirection))
    print("")

def generateTradeSignal(bbPercents):
    callAPI = CallAPI()
    # new signal generation idea
    # get last trade direction & win/loss
    # when price trigger bbRange
    #if last trade is a win, then follow same direction, otherwise change direction
    logicAll1 = float(callAPI.getPosition()['positionAmt']) == 0
    logicAll2_1 = (bbPercents[-2] < -100) & (bbPercents[-1] > -100)
    logicAll2_2 = (bbPercents[-2] > 100) & (bbPercents[-1] < 100)
    logicAll2 = logicAll2_1 | logicAll2_2
    logicAll = logicAll1 & logicAll2

    lastDirection = getLastDirection()
    lastTradeWin = getLastPnL() > 0

    if logicAll:    # if bbRange triggered
        if lastTradeWin:
            return lastDirection
        else:
            return changeTradeDirection(lastDirection)

def changeTradeDirection(direction):
    if direction == "BUY":
        return "SELL"
    elif direction == "SELL":
        return "BUY"

def TradeOrder(sideOpen, bbRanges):
    callAPI = CallAPI()
    # check current quantity held, cash balance and current leverage
    quantityTradeSymbol = float(callAPI.getPosition()['positionAmt'])
    balance = float(callAPI.dict_balance_usdt()['availableBalance'])
    leverage = calcuateNewLeverage(bbRanges)

    if sideOpen == "BUY":
        tradePrice = float(callAPI.getBookTicker()['askPrice'])
        stopPriceCutLoss = round(tradePrice * (1 - AUM_PERCENTAGE_CUT_LOSS / leverage), TRADE_SYMBOL_DECIMALS)
        stopPriceStopGain = round(tradePrice * (1 + AUM_PERCENTAGE_STOP_GAIN / leverage), TRADE_SYMBOL_DECIMALS)
    elif sideOpen == "SELL":
        tradePrice = float(callAPI.getBookTicker()['bidPrice'])
        stopPriceCutLoss = round(tradePrice * (1 + AUM_PERCENTAGE_CUT_LOSS / leverage), TRADE_SYMBOL_DECIMALS)
        stopPriceStopGain = round(tradePrice * (1 - AUM_PERCENTAGE_STOP_GAIN / leverage), TRADE_SYMBOL_DECIMALS)
    sideClose = changeTradeDirection(sideOpen)

    if (quantityTradeSymbol == 0):
        openOrder = len(callAPI.getOpenOrder())
        if (openOrder > 0):
            callAPI.killAllOrder()
        quantity = float(balance * leverage / tradePrice * (1 - TRADE_QUANTITY_BUFFER), 1)
        tradeOpenOK = callAPI.tradeOpen(sideOpen, quantity)
        while (tradeOpenOK != 200):
            quantity -= TRADE_SYMBOL_MIN_QUANTITY
            tradeOpenOK = callAPI.tradeOpen(sideOpen, quantity)
        if (tradeOpenOK == 200):
            tradeMessage = "{} order is placed! Quantity: {} Cost: {}".format(sideOpen, quantity, tradePrice)
            tradeCloseCutLossOK = callAPI.tradeClose(sideClose, stopPriceCutLoss, quantity, "STOP")
            if (tradeCloseCutLossOK == 200):
                print("Cut Loss placed at {}".format(stopPriceCutLoss))
            tradeCloseStopGainOK = callAPI.tradeClose(sideClose, stopPriceStopGain, quantity, "TAKE_PROFIT")
            if (tradeCloseStopGainOK == 200):
                print("Stop Gain placed at {}".format(stopPriceStopGain))
            tradeInfo = {'TRADE_SYMBOL': TRADE_SYMBOL, 'tradeTime': callAPI.timestamp, 'tradeDirection': sideOpen, 'tradeQuantity': callAPI.getPosition()['positionAmt'], 'tradePrice': callAPI.getPosition()['entryPrice'], 'priceCutLoss': stopPriceCutLoss, 'priceStopGain': stopPriceStopGain, 'balance': balance,'leverage': leverage}
            TradeLog(tradeInfo)
        else:
            tradeMessage = "Cannot place trade!"
    else:
        tradeMessage = "Position existed, no new trade."
    return tradeMessage

# update the trade history once trade triggered
def TradeLog(tradeInfo):
    with open('Trade Log.csv', 'r+') as fileRead:
        reader = csv.DictReader(fileRead)
        oldList = [row for row in reader]
        oldList.append(tradeInfo)
    with open('Trade Log.csv', 'w+') as fileWrite:
        header = [head for head in oldList[0]]
        writer = csv.DictWriter(fileWrite, fieldnames = header)
        writer.writeheader()
        for item in oldList:
            writer.writerow(item)

def getLastDirection():
    with open('Trade Log.csv', 'r+') as fileRead:
        reader = csv.DictReader(fileRead)
        oldList = [row for row in reader]
        if (len(oldList) == 0):
            lastDirection = "NEW"
        else:
            lastDirection = oldList[-1]['tradeDirection']
    return lastDirection

def getLastPnL():
    lastPnL = 0
    callAPI = CallAPI()
    tradeHistory = callAPI.getTradeHistory()
    tradeHistoryReverse = tradeHistory[::-1]
    for item in tradeHistoryReverse:
        if float(item['realizedPnl']) != 0:
            orderId = item['orderId']
            break
    for item in tradeHistoryReverse:
        if (orderId == item['orderId']):
            lastPnL += float(item['realizedPnl'])
    return lastPnL

def calcuateNewLeverage(bbRanges):
    callAPI = CallAPI()
    listLeverageBracket = callAPI.checkLeverageBracket()
    balance = float(callAPI.dict_balance_usdt()['availableBalance'])
    # find max possible leverage for current trade order
    newBalance = balance * (1 + AUM_PERCENTAGE_STOP_GAIN)
    for item in listLeverageBracket:
        cap = int(item['notionalCap'])
        floor = int(item['notionalFloor'])
        if (newBalance < cap) & (newBalance > floor):
            maxLeverage = int(item['initialLeverage'])
    print("maxLeverage = {}".format(maxLeverage))
    # find implied leverage given bbRange
    curPrice = float(callAPI.getPosition()['markPrice'])
    # if (type(bbRanges[-1]) != float):
    #     bbRanges[-1] = 0.01
    moveRangePercent = float(bbRanges[-1] / curPrice * 0.5)
    impliedLeverage =  int(AUM_PERCENTAGE_STOP_GAIN / moveRangePercent)
    print("impliedLeverage = {}".format(impliedLeverage))
    # compare 2 leverage values and return better one
    # final adjusted leverage must be within (2, max)
    adjustedLeverage = max(2, min(maxLeverage, impliedLeverage))
    print("adjustedLeverage = {}".format(adjustedLeverage))
    callAPI.changeLeverage(adjustedLeverage)
    return adjustedLeverage

if __name__ == "__main__":

    closes = []
    bbRanges = []
    bbPercents = []

    def on_open(ws):
        print('opened connection')

    def on_close(ws):
        print('closed connection')

    def on_message(ws, message):

        global closes, bbRanges, bbPercents

        close, is_candle_closed = getClose(message)

        if is_candle_closed:
            
            closes.append(float(close))
            
            bbRanges, bbPercents = calculateBollingerBandData(closes, ROLLING_PERIODS, NUMBER_SD)
            
            GeneratePortfolioSnapshot(bbRanges, bbPercents)
            
            direction = generateTradeSignal(bbPercents)
          
            if direction not in ["BUY", "SELL"]:
                print("NO SIGNAL")
            else:
                print("{} order triggered!!!".format(direction))
                tradeMessage = TradeOrder(direction, bbRanges)
                print(tradeMessage)

    ws = websocket.WebSocketApp(SOCKET, on_open = on_open, on_close = on_close, on_message = on_message)
    ws.run_forever()