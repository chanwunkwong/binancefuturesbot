import config, hashlib, hmac, json, numpy, requests, talib, time, websocket
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
ORDER_BUFFER = 0.01

## Connect to websocket to get real time futures price streaming
SOCKET = "wss://fstream.binance.com/ws/" + TRADE_SYMBOL.lower() + "@kline_1m"
client = Client(config.API_KEY, config.API_SECRET)

class CallAPI:
    def __init__(self):
        self.symbol = TRADE_SYMBOL
        self.timestamp = int(time.time() * 1000)
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
    def ACCOUNT_INFO(self):
        p = {'recvWindow': 50000, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v2/account?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def BOOK_TICKER(self):
        p = {'recvWindow': 50000, 'symbol': self.symbol, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.get(url = self.__base_url_futures + '/fapi/v1/ticker/bookTicker?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
        return response.json()
    def dict_balance_usdt(self):
        return self.ACCOUNT_INFO()['assets'][1]
    def dict_balance_trade_symbol(self):
        for item in self.ACCOUNT_INFO()['positions']:
            if item['symbol'] == self.symbol:
                return item
    def dict_order_book(self):
        return self.BOOK_TICKER()
   ############################################################################################################
    def tradeOpen(self, direction, quantity):
        p = {'recvWindow': 50000, 'symbol': self.symbol, 'side': direction, 'type': 'MARKET', 'quantity': quantity, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.post(url = self.__base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': self.__key}, data = p)
        return (response.status_code == 200)
    def tradeClose(self, direction, price, quantity, type):
        p = {'recvWindow': 50000, 'symbol': self.symbol, 'side': direction, 'type': type, 'quantity': quantity, 'price': price, 'stopPrice': price, 'timeInForce': "GTC", 'reduceOnly': True, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        response = requests.post(url = self.__base_url_futures + '/fapi/v1/order', headers = {'X-MBX-APIKEY': self.__key}, data = p)
        return (response.status_code == 200)
    ############################################################################################################
    def getOpenOrder(self):
        p = {'recvWindow': 50000, 'symbol': self.symbol, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        return requests.get(url = self.__base_url_futures + '/fapi/v1/openOrders?' + self.__param2string(p), headers = {'X-MBX-APIKEY': self.__key})
    def killAllOrder(self):
        p = {'recvWindow': 50000, 'symbol': self.symbol, 'timestamp': self.timestamp}
        p['signature'] = self.__hashing(self.__param2string(p))
        requests.delete(url = self.__base_url_futures + '/fapi/v1/allOpenOrders', headers = {'X-MBX-APIKEY': self.__key}, data = p)

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
    bbRanges.append(round(upper[-1] - lower[-1], 4))           
    temp = (upper - lower) / np_closes * 100
    bbRangePercentsRaw = temp.tolist()
    bbRangePercents = [item for item in bbRangePercentsRaw if item == item]
    bbPercents.append(round((np_closes[-1] - middle[-1]) / (upper[-1] - middle[-1]) * 100, 2)) 
    return upper, middle, lower, bbRanges, bbRangePercents, bbPercents

def GeneratePortfolioSnapshot(bbRanges, bbPercents, bbRangePercents):
    callAPI = CallAPI()
    balanceBegin = round(float(callAPI.dict_balance_usdt()['walletBalance']), 2)
    balanceEnd = round(float(callAPI.dict_balance_usdt()['marginBalance']), 2)
    currentPNL = round(float(callAPI.dict_balance_usdt()['unrealizedProfit']), 2)
    gsScore = round(numpy.log(balanceEnd / AUM_TARGET_USD) / numpy.log(1.1), 2)
    quantityTradeSymbol = float(callAPI.dict_balance_trade_symbol()['positionAmt'])
    priceEntry = float(callAPI.dict_balance_trade_symbol()['entryPrice'])
    leverage = float(callAPI.dict_balance_trade_symbol()['leverage'])

    print("")
    print("{}".format(time.strftime("%a, %d %b %Y %H:%M:%S")))
    print("")
    print("Portfolio Snaphot")
    print("=================")
    print("Begin (USDT): {} / End (USDT): {} / P&L (USDT): {} ({}%)".format(balanceBegin, balanceEnd, currentPNL, round(currentPNL / balanceBegin * 100, 2)))
    print("Geometric Score (GS): {}".format(gsScore))
    print("")
    print("Balance ({}): {} / Entry Price (USDT): {} / Leverage: {}".format(TRADE_SYMBOL, quantityTradeSymbol, priceEntry, leverage))
    print("")
    print("bbRange: {} / bbPercent: {}% / bbRangePercent: {}% / bbRangePercent Percentile: {}%".format(bbRanges[-1], bbPercents[-1], round(bbRangePercents[-1], 4), round(numpy.percentile(bbRangePercents, BB_RANGE_PERCENTILE), 4)))
    print("")

def generateTradeSignal(closes, upper, middle, lower, bbRanges, bbRangePercents):
    callAPI = CallAPI()
    ### ALL logic
    # 1. last bbRangePercent < 95th percentile
    # 2. last bbRange >= $0.01
    # 3. No holding in TRADE_SYMBOL
    logicAll1 = True #(bbRangePercents[-1] <= numpy.percentile(bbRangePercents, BB_RANGE_PERCENTILE))
    logicAll2 = (bbRanges[-1] >= 0.01)
    logicAll3 = float(callAPI.dict_balance_trade_symbol()['positionAmt']) == 0
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

def TradeOrder(sideOpen):
    callAPI = CallAPI()
    # auto calculate trade quantity
    quantityTradeSymbol = float(callAPI.dict_balance_trade_symbol()['positionAmt'])
    balance = float(callAPI.dict_balance_usdt()['availableBalance'])
    leverage = float(callAPI.dict_balance_trade_symbol()['leverage'])
    print(sideOpen, quantityTradeSymbol, balance, leverage)
    if sideOpen == "BUY":
        tradePrice = float(callAPI.dict_order_book()['askPrice'])
        stopPriceCutLoss = round(tradePrice * (1 - AUM_PERCENTAGE_CUT_LOSS / leverage), 4)
        stopPriceStopGain = round(tradePrice * (1 + AUM_PERCENTAGE_STOP_GAIN / leverage), 4)
        sideClose = "SELL"
    elif sideOpen == "SELL":
        tradePrice = float(callAPI.dict_order_book()['bidPrice'])
        stopPriceCutLoss = round(tradePrice * (1 + AUM_PERCENTAGE_CUT_LOSS / leverage), 4)
        stopPriceStopGain = round(tradePrice * (1 - AUM_PERCENTAGE_STOP_GAIN / leverage), 4)
        sideClose = "BUY"

    # make sure no orders outstanding
    openOrder = len(callAPI.getOpenOrder().json())
    while (quantityTradeSymbol == 0) & (openOrder > 0):
        callAPI.killAllOrder()
    if (quantityTradeSymbol == 0):
        quantity = round(balance * leverage / tradePrice * (1 - ORDER_BUFFER), 1)
        tradeOpenOK = callAPI.tradeOpen(sideOpen, quantity)
        if tradeOpenOK:
            tradeMessage = "{} order is placed! Quantity: {} Cost: {}".format(sideOpen, quantity, tradePrice)
            tradeCloseCutLossOK = callAPI.tradeClose(sideClose, stopPriceCutLoss, quantity, "STOP")
            if tradeCloseCutLossOK:
                print("Cut Loss placed at {}".format(stopPriceCutLoss))
            tradeCloseStopGainOK = callAPI.tradeClose(sideClose, stopPriceStopGain, quantity, "TAKE_PROFIT")
            if tradeCloseStopGainOK:
                print("Stop Gain placed at {}".format(stopPriceStopGain))
        else:
            tradeMessage = "Cannot place trade!"

    else:
        tradeMessage = "Position existed, no new trade."
    
    return tradeMessage

if __name__ == "__main__":

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

        close, is_candle_closed = getClose(message)

        if is_candle_closed:
            
            closes.append(float(close))
            
            upper, middle, lower, bbRanges, bbRangePercents, bbPercents = calculateBollingerBandData(closes, ROLLING_PERIODS, NUMBER_SD)
            
            GeneratePortfolioSnapshot(bbRanges, bbPercents, bbRangePercents)
            
            direction = generateTradeSignal(closes, upper, middle, lower, bbRanges, bbRangePercents)
            
            if direction not in ["BUY", "SELL"]:
                print("No signal yet...")
            else:
                print("{} order triggered!!!".format(direction))
                tradeMessage = TradeOrder(direction)
                print(tradeMessage)

    ws = websocket.WebSocketApp(SOCKET, on_open = on_open, on_close = on_close, on_message = on_message)
    ws.run_forever()