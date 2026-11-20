/**
 * KUCOIN HUNTER TERMINAL - Main Application
 * Real-time trading terminal with WebSocket feeds
 */
(function() {
  'use strict';

  // ==========================================================================
  // STATE MANAGEMENT
  // ==========================================================================
  
  const State = {
    // Connection
    ws: null,
    wsConnected: false,
    wsReconnectAttempts: 0,
    maxReconnectAttempts: 10,
    
    // Market Data
    symbols: new Map(),
    currentSymbol: 'BTC-USDT',
    currentTimeframe: '1m',
    klines: [],
    orderBook: { bids: [], asks: [] },
    recentTrades: [],
    tickers: new Map(),
    
    // Radar & Signals
    radarData: [],
    radarFilter: 'all',
    signals: [],
    selectedSignalId: null,
    positions: [],
    
    // Account
    equity: 0,
    pnl: 0,
    pnlPct: 0,
    balance: 0,
    
    // UI
    theme: 'dark',
    scanStatus: 'IDLE',
    lastUpdate: null,
    mode: 'SHADOW',
    
    // Chart
    chartCrosshair: null,
    equityData: [],
    
    // Toast queue
    toasts: []
  };

  // ==========================================================================
  // DOM ELEMENTS
  // ==========================================================================
  
  const Elements = {
    // Header
    connectionStatus: document.getElementById('connectionStatus'),
    statusText: document.querySelector('.status-text'),
    statusDot: document.querySelector('.status-dot'),
    marketClock: document.getElementById('marketClock'),
    clockTime: document.querySelector('.clock-time'),
    equityValue: document.getElementById('equityValue'),
    pnlValue: document.getElementById('pnlValue'),
    themeToggle: document.getElementById('themeToggle'),
    killSwitch: document.getElementById('killSwitch'),
    
    // Radar
    marketRadar: document.getElementById('marketRadar'),
    radarFilter: document.getElementById('radarFilter'),
    
    // Chart
    symbolInput: document.getElementById('symbolInput'),
    symbolSuggestions: document.getElementById('symbolSuggestions'),
    timeframeTabs: document.getElementById('timeframeTabs'),
    priceChart: document.getElementById('priceChart'),
    volumeChart: document.getElementById('volumeChart'),
    chartOverlay: document.getElementById('chartOverlay'),
    
    // Order Book
    asks: document.getElementById('asks'),
    bids: document.getElementById('bids'),
    spreadValue: document.getElementById('spreadValue'),
    spreadLine: document.getElementById('spreadLine'),
    
    // Trades
    tradesContent: document.getElementById('recentTrades'),
    tradesCount: document.getElementById('tradesCount'),
    
    // Signals
    signalsList: document.getElementById('signalsList'),
    refreshSignals: document.getElementById('refreshSignals'),
    
    // Positions
    positionsList: document.getElementById('positionsList'),
    
    // Trade Plan
    tradePlan: document.getElementById('tradePlan'),
    tradeModal: document.getElementById('tradeModal'),
    modalSymbol: document.getElementById('modalSymbol'),
    planEntry: document.getElementById('planEntry'),
    planSize: document.getElementById('planSize'),
    planValue: document.getElementById('planValue'),
    planSL: document.getElementById('planSL'),
    planRisk: document.getElementById('planRisk'),
    planRiskPct: document.getElementById('planRiskPct'),
    planTP1: document.getElementById('planTP1'),
    planTP2: document.getElementById('planTP2'),
    planTP3: document.getElementById('planTP3'),
    planRR: document.getElementById('planRR'),
    planWR: document.getElementById('planWR'),
    planExp: document.getElementById('planExp'),
    planRationale: document.getElementById('planRationale'),
    btnBuy: document.getElementById('btnBuy'),
    btnSell: document.getElementById('btnSell'),
    
    // Equity Modal
    equityModal: document.getElementById('equityModal'),
    equityChart: document.getElementById('equityChart'),
    equityStats: document.getElementById('equityStats'),
    
    // Footer
    scanStatus: document.getElementById('scanStatus'),
    apiStatus: document.getElementById('apiStatus'),
    wsStatus: document.getElementById('wsStatus'),
    modeIndicator: document.getElementById('modeIndicator'),
    lastUpdate: document.getElementById('lastUpdate'),
    
    // Toast
    toastContainer: document.getElementById('toastContainer')
  };

  // ==========================================================================
  // UTILITY FUNCTIONS
  // ==========================================================================
  
  const Utils = {
    formatNumber(num, decimals = 2) {
      if (num === null || num === undefined || isNaN(num)) return '--';
      return Number(num).toLocaleString(undefined, { 
        minimumFractionDigits: decimals, 
        maximumFractionDigits: decimals 
      });
    },
    
    formatCompact(num) {
      if (num === null || num === undefined || isNaN(num)) return '--';
      const n = Number(num);
      if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
      if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
      if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K';
      return n.toFixed(2);
    },
    
    formatPrice(price) {
      if (price === null || price === undefined) return '--';
      const p = Number(price);
      if (p < 0.0001) return p.toFixed(8);
      if (p < 0.01) return p.toFixed(6);
      if (p < 1) return p.toFixed(4);
      return p.toFixed(2);
    },
    
    formatChange(change) {
      if (change === null || change === undefined) return '--';
      const c = Number(change);
      const sign = c >= 0 ? '+' : '';
      return sign + c.toFixed(2) + '%';
    },
    
    formatTime(ts) {
      const date = new Date(ts);
      return date.toLocaleTimeString('en-US', { 
        hour12: false, 
        timeZone: 'UTC',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    },
    
    formatDateTime(ts) {
      const date = new Date(ts);
      return date.toLocaleString('en-US', { 
        hour12: false, 
        timeZone: 'UTC',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    },
    
    debounce(fn, ms) {
      let timeoutId;
      return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), ms);
      };
    },
    
    throttle(fn, ms) {
      let lastCall = 0;
      return (...args) => {
        const now = Date.now();
        if (now - lastCall >= ms) {
          lastCall = now;
          fn(...args);
        }
      };
    },
    
    clamp(val, min, max) {
      return Math.max(min, Math.min(max, val));
    },
    
    generateId() {
      return Math.random().toString(36).substr(2, 9);
    }
  };

  // ==========================================================================
  // API CLIENT
  // ==========================================================================
  
  const Api = {
    baseUrl: '/api',
    
    async request(endpoint, options = {}) {
      const url = this.baseUrl + endpoint;
      const config = {
        headers: { 'Content-Type': 'application/json' },
        ...options
      };
      
      try {
        const response = await fetch(url, config);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return await response.json();
      } catch (error) {
        console.error(`API Error [${endpoint}]:`, error);
        throw error;
      }
    },
    
    async getStatus() {
      return this.request('/status');
    },
    
    async getSymbols() {
      return this.request('/symbols');
    },
    
    async getKlines(symbol, interval, limit = 500) {
      return this.request(`/klines/${symbol}?interval=${interval}&limit=${limit}`);
    },
    
    async getOrderBook(symbol, limit = 20) {
      return this.request(`/orderbook/${symbol}?limit=${limit}`);
    },
    
    async getRecentTrades(symbol, limit = 100) {
      return this.request(`/trades/${symbol}?limit=${limit}`);
    },
    
    async getTicker(symbol) {
      return this.request(`/ticker/${symbol}`);
    },
    
    async getSignals() {
      return this.request('/signals');
    },
    
    async getPositions() {
      return this.request('/positions');
    },
    
    async getEquity() {
      return this.request('/equity');
    },
    
    async placeOrder(orderData) {
      return this.request('/order', {
        method: 'POST',
        body: JSON.stringify(orderData)
      });
    },
    
    async cancelOrder(orderId) {
      return this.request(`/order/${orderId}`, { method: 'DELETE' });
    }
  };

  // ==========================================================================
  // WEBSOCKET MANAGER
  // ==========================================================================
  
  const WS = {
    connect() {
      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
        return;
      }
      
      this.updateStatus('CONNECTING');
      
      // Get WS token from server
      fetch('/api/ws/token')
        .then(r => r.json())
        .then(data => {
          if (data.token && data.endpoint) {
            this.ws = new WebSocket(`${data.endpoint}?token=${data.token}`);
            this.setupHandlers();
          } else {
            throw new Error('Invalid WS token response');
          }
        })
        .catch(err => {
          console.error('WS token error:', err);
          this.scheduleReconnect();
        });
    },
    
    setupHandlers() {
      this.ws.onopen = () => {
        console.log('WS Connected');
        State.wsConnected = true;
        State.wsReconnectAttempts = 0;
        this.updateStatus('CONNECTED');
        this.subscribe();
      };
      
      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (e) {
          console.error('WS message parse error:', e);
        }
      };
      
      this.ws.onclose = () => {
        console.log('WS Disconnected');
        State.wsConnected = false;
        this.updateStatus('DISCONNECTED');
        this.scheduleReconnect();
      };
      
      this.ws.onerror = (err) => {
        console.error('WS Error:', err);
        this.updateStatus('ERROR');
      };
    },
    
    handleMessage(data) {
      if (data.type === 'welcome' || data.type === 'ack') return;
      
      if (data.topic && data.subject) {
        // KuCoin WS format
        switch (data.subject) {
          case 'trade.l2update':
            this.handleOrderBookUpdate(data.data);
            break;
          case 'trade.match':
            this.handleTradeMatch(data.data);
            break;
          case 'trade.ticker':
            this.handleTickerUpdate(data.data);
            break;
        }
      } else if (data.type) {
        // Custom server format
        switch (data.type) {
          case 'scan_update':
            State.scanStatus = data.status;
            UI.updateFooter();
            break;
          case 'signal':
            Signals.add(data.signal);
            break;
          case 'position_update':
            Positions.update(data.positions);
            break;
          case 'equity_update':
            Account.update(data.equity);
            break;
        }
      }
    },
    
    handleOrderBookUpdate(data) {
      if (data.symbol !== State.currentSymbol) return;
      
      // KuCoin level2 update format
      if (data.changes) {
        data.changes.asks?.forEach(([price, size]) => {
          this.updateOrderBookSide('asks', price, size);
        });
        data.changes.bids?.forEach(([price, size]) => {
          this.updateOrderBookSide('bids', price, size);
        });
        UI.renderOrderBook();
      }
    },
    
    updateOrderBookSide(side, price, size) {
      const book = State.orderBook[side];
      const priceNum = parseFloat(price);
      const sizeNum = parseFloat(size);
      
      if (sizeNum === 0) {
        // Remove level
        const idx = book.findIndex(l => l.price === priceNum);
        if (idx >= 0) book.splice(idx, 1);
      } else {
        // Update or add level
        const idx = book.findIndex(l => l.price === priceNum);
        if (idx >= 0) {
          book[idx].size = sizeNum;
        } else {
          book.push({ price: priceNum, size: sizeNum });
          // Sort: asks ascending, bids descending
          book.sort((a, b) => side === 'asks' ? a.price - b.price : b.price - a.price);
        }
      }
      // Keep top 50
      if (book.length > 50) book.length = 50;
    },
    
    handleTradeMatch(data) {
      if (data.symbol !== State.currentSymbol) return;
      
      const trade = {
        time: new Date(data.time).getTime(),
        price: parseFloat(data.price),
        size: parseFloat(data.size),
        side: data.side // 'buy' or 'sell'
      };
      
      State.recentTrades.unshift(trade);
      if (State.recentTrades.length > 100) State.recentTrades.pop();
      
      UI.renderTrades();
    },
    
    handleTickerUpdate(data) {
      const symbol = data.symbol;
      State.tickers.set(symbol, {
        price: parseFloat(data.price),
        change: parseFloat(data.changeRate || 0) * 100,
        volume: parseFloat(data.vol || 0),
        time: Date.now()
      });
      
      if (symbol === State.currentSymbol) {
        UI.updateHeaderTicker();
      }
      UI.updateRadarTicker(symbol);
    },
    
    subscribe() {
      if (!State.wsConnected) return;
      
      const symbol = State.currentSymbol;
      const topics = [
        `/market/level2:${symbol}`,
        `/market/match:${symbol}`,
        `/market/ticker:${symbol}`
      ];
      
      topics.forEach(topic => {
        this.ws.send(JSON.stringify({
          id: Utils.generateId(),
          type: 'subscribe',
          topic: topic,
          privateChannel: false,
          response: true
        }));
      });
      
      // Also subscribe to all tickers for radar
      this.ws.send(JSON.stringify({
        id: Utils.generateId(),
        type: 'subscribe',
        topic: '/market/ticker:all',
        privateChannel: false,
        response: true
      }));
    },
    
    unsubscribe() {
      if (!State.wsConnected) return;
      
      const symbol = State.currentSymbol;
      const topics = [
        `/market/level2:${symbol}`,
        `/market/match:${symbol}`,
        `/market/ticker:${symbol}`
      ];
      
      topics.forEach(topic => {
        this.ws.send(JSON.stringify({
          id: Utils.generateId(),
          type: 'unsubscribe',
          topic: topic,
          privateChannel: false,
          response: true
        }));
      });
    },
    
    resubscribe() {
      this.unsubscribe();
      setTimeout(() => this.subscribe(), 100);
    },
    
    scheduleReconnect() {
      if (State.wsReconnectAttempts >= State.maxReconnectAttempts) {
        this.updateStatus('FAILED');
        UI.showToast('WebSocket connection failed. Click to retry.', 'error', () => {
          State.wsReconnectAttempts = 0;
          this.connect();
        });
        return;
      }
      
      const delay = Math.min(1000 * Math.pow(2, State.wsReconnectAttempts), 30000);
      State.wsReconnectAttempts++;
      this.updateStatus(`RECONNECTING (${State.wsReconnectAttempts})`);
      
      setTimeout(() => this.connect(), delay);
    },
    
    updateStatus(status) {
      const statusEl = Elements.connectionStatus;
      const textEl = Elements.statusText;
      const dotEl = Elements.statusDot;
      
      statusEl.className = 'status-indicator';
      textEl.textContent = status;
      
      if (status === 'CONNECTED') {
        statusEl.classList.add('connected');
      } else if (status === 'ERROR' || status === 'FAILED') {
        statusEl.classList.add('error');
      }
      
      // Update footer WS status
      Elements.wsStatus.textContent = `WS: ${status}`;
    }
  };

  // ==========================================================================
  // UI RENDERING
  // ==========================================================================
  
  const UI = {
    init() {
      this.bindEvents();
      this.loadTheme();
      this.startClock();
      this.loadInitialData();
    },
    
    bindEvents() {
      // Theme toggle
      Elements.themeToggle.addEventListener('click', () => this.toggleTheme());
      
      // Kill switch
      Elements.killSwitch.addEventListener('click', () => this.toggleKillSwitch());
      
      // Symbol input
      Elements.symbolInput.addEventListener('input', Utils.debounce(() => this.handleSymbolSearch(), 150));
      Elements.symbolInput.addEventListener('focus', () => this.showSymbolSuggestions());
      Elements.symbolInput.addEventListener('blur', () => setTimeout(() => this.hideSymbolSuggestions(), 200));
      Elements.symbolInput.addEventListener('keydown', (e) => this.handleSymbolKeydown(e));
      
      // Timeframe tabs
      Elements.timeframeTabs.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-tf]');
        if (btn) this.setTimeframe(btn.dataset.tf);
      });
      
      // Radar filter
      Elements.radarFilter.addEventListener('change', (e) => {
        State.radarFilter = e.target.value;
        this.renderRadar();
      });
      
      // Refresh signals
      Elements.refreshSignals.addEventListener('click', () => Signals.load());
      
      // Trade modal buttons
      Elements.btnBuy.addEventListener('click', () => TradePlan.execute('buy'));
      Elements.btnSell.addEventListener('click', () => TradePlan.execute('sell'));
      Elements.tradeModal.addEventListener('close', () => TradePlan.close());
      
      // Chart crosshair
      Elements.priceChart.addEventListener('mousemove', (e) => Chart.showCrosshair(e));
      Elements.priceChart.addEventListener('mouseleave', () => Chart.hideCrosshair());
      Elements.priceChart.addEventListener('click', (e) => Chart.handleClick(e));
      
      // Equity modal
      Elements.equityValue.addEventListener('click', () => EquityModal.open());
      Elements.equityModal.addEventListener('close', () => EquityModal.close());
      
      // Toast clicks
      Elements.toastContainer.addEventListener('click', (e) => {
        const toast = e.target.closest('.toast');
        if (toast && toast.onclick) toast.onclick();
      });
    },
    
    loadTheme() {
      const saved = localStorage.getItem('theme') || 'dark';
      this.setTheme(saved);
    },
    
    setTheme(theme) {
      State.theme = theme;
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('theme', theme);
      Chart.render(); // Re-render charts with new colors
    },
    
    toggleTheme() {
      this.setTheme(State.theme === 'dark' ? 'light' : 'dark');
    },
    
    toggleKillSwitch() {
      const armed = Elements.killSwitch.classList.toggle('armed');
      if (armed) {
        this.showToast('KILL SWITCH ARMED - All trading halted', 'warning');
        // TODO: Send kill command to server
      } else {
        this.showToast('Kill switch disarmed', 'info');
      }
    },
    
    startClock() {
      const updateClock = () => {
        const now = new Date();
        Elements.clockTime.textContent = now.toLocaleTimeString('en-US', { 
          hour12: false, 
          timeZone: 'UTC',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit'
        });
      };
      updateClock();
      setInterval(updateClock, 1000);
    },
    
    async loadInitialData() {
      try {
        // Load symbols for suggestions
        const symbols = await Api.getSymbols();
        State.symbols = new Map(symbols.map(s => [s.symbol, s]));
        this.populateSymbolSuggestions();
        
        // Load initial market data
        await this.loadSymbolData(State.currentSymbol);
        
        // Load signals and positions
        await Signals.load();
        await Positions.load();
        await Account.load();
        
        // Connect WebSocket
        WS.connect();
        
        // Start periodic updates
        this.startPeriodicUpdates();
        
      } catch (error) {
        console.error('Initial load error:', error);
        this.showToast('Failed to load initial data', 'error');
      }
    },
    
    startPeriodicUpdates() {
      // Update radar every 10s
      setInterval(() => Radar.load(), 10000);
      
      // Update account every 30s
      setInterval(() => Account.load(), 30000);
      
      // Update last update time
      setInterval(() => this.updateLastUpdate(), 1000);
    },
    
    updateLastUpdate() {
      if (State.lastUpdate) {
        const diff = Math.floor((Date.now() - State.lastUpdate) / 1000);
        Elements.lastUpdate.textContent = `LAST: ${diff}s AGO`;
      }
    },
    
    async loadSymbolData(symbol) {
      State.currentSymbol = symbol;
      Elements.symbolInput.value = symbol;
      
      try {
        const [klines, orderBook, trades, ticker] = await Promise.all([
          Api.getKlines(symbol, State.currentTimeframe, 500),
          Api.getOrderBook(symbol, 50),
          Api.getRecentTrades(symbol, 100),
          Api.getTicker(symbol)
        ]);
        
        State.klines = klines;
        State.orderBook = orderBook;
        State.recentTrades = trades;
        State.tickers.set(symbol, ticker);
        
        State.lastUpdate = Date.now();
        
        Chart.render();
        this.renderOrderBook();
        this.renderTrades();
        this.updateHeaderTicker();
        this.updateSymbolInRadar(symbol);
        
        // Resubscribe WS
        WS.resubscribe();
        
      } catch (error) {
        console.error('Load symbol error:', error);
        this.showToast(`Failed to load ${symbol}`, 'error');
      }
    },
    
    handleSymbolSearch() {
      const query = Elements.symbolInput.value.toUpperCase().trim();
      if (query.length < 2) {
        this.hideSymbolSuggestions();
        return;
      }
      
      const matches = Array.from(State.symbols.values())
        .filter(s => s.symbol.includes(query) || s.baseCurrency.includes(query) || s.quoteCurrency.includes(query))
        .slice(0, 10);
      
      this.renderSymbolSuggestions(matches);
      this.showSymbolSuggestions();
    },
    
    populateSymbolSuggestions() {
      const majors = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT', 'XRP-USDT', 'ADA-USDT', 'DOGE-USDT', 'AVAX-USDT', 'DOT-USDT', 'LINK-USDT'];
      this.renderSymbolSuggestions(majors.map(s => State.symbols.get(s)).filter(Boolean));
    },
    
    renderSymbolSuggestions(symbols) {
      Elements.symbolSuggestions.innerHTML = symbols.map(s => `
        <div class="symbol-suggestion" data-symbol="${s.symbol}">
          <span class="sym">${s.symbol}</span>
          <span class="price">${Utils.formatPrice(s.lastPrice || s.price)}</span>
        </div>
      `).join('');
      
      Elements.symbolSuggestions.querySelectorAll('.symbol-suggestion').forEach(el => {
        el.addEventListener('click', () => {
          this.setSymbol(el.dataset.symbol);
        });
      });
    },
    
    showSymbolSuggestions() {
      Elements.symbolSuggestions.classList.add('open');
    },
    
    hideSymbolSuggestions() {
      Elements.symbolSuggestions.classList.remove('open');
    },
    
    handleSymbolKeydown(e) {
      if (e.key === 'Enter') {
        const highlighted = Elements.symbolSuggestions.querySelector('.highlighted');
        if (highlighted) {
          this.setSymbol(highlighted.dataset.symbol);
        } else {
          const val = Elements.symbolInput.value.toUpperCase().trim();
          if (State.symbols.has(val)) this.setSymbol(val);
        }
        this.hideSymbolSuggestions();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.navigateSuggestions(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.navigateSuggestions(-1);
      } else if (e.key === 'Escape') {
        this.hideSymbolSuggestions();
      }
    },
    
    navigateSuggestions(dir) {
      const items = Elements.symbolSuggestions.querySelectorAll('.symbol-suggestion');
      if (!items.length) return;
      
      const current = Elements.symbolSuggestions.querySelector('.highlighted');
      let index = current ? Array.from(items).indexOf(current) : -1;
      index = (index + dir + items.length) % items.length;
      
      items.forEach((el, i) => el.classList.toggle('highlighted', i === index));
      if (items[index]) items[index].scrollIntoView({ block: 'nearest' });
    },
    
    setSymbol(symbol) {
      this.loadSymbolData(symbol);
      this.hideSymbolSuggestions();
    },
    
    setTimeframe(tf) {
      State.currentTimeframe = tf;
      Elements.timeframeTabs.querySelectorAll('button').forEach(btn => {
        btn.setAttribute('aria-selected', btn.dataset.tf === tf);
      });
      this.loadSymbolData(State.currentSymbol);
    },
    
    updateHeaderTicker() {
      const ticker = State.tickers.get(State.currentSymbol);
      if (!ticker) return;
      
      // Update equity display (placeholder)
      // Real equity comes from Account.load()
    },
    
    updateRadarTicker(symbol) {
      const ticker = State.tickers.get(symbol);
      if (!ticker) return;
      
      const item = Elements.marketRadar.querySelector(`[data-symbol="${symbol}"]`);
      if (item) {
        const priceEl = item.querySelector('.radar-price');
        const changeEl = item.querySelector('.radar-change');
        const volEl = item.querySelector('.radar-volume');
        
        if (priceEl) priceEl.textContent = Utils.formatPrice(ticker.price);
        if (changeEl) {
          changeEl.textContent = Utils.formatChange(ticker.change);
          changeEl.className = 'radar-change ' + (ticker.change >= 0 ? 'positive' : 'negative');
        }
        if (volEl) volEl.textContent = Utils.formatCompact(ticker.volume);
      }
    },
    
    updateSymbolInRadar(symbol) {
      const items = Elements.marketRadar.querySelectorAll('.radar-item');
      items.forEach(item => {
        item.classList.toggle('selected', item.dataset.symbol === symbol);
      });
    },
    
    renderRadar() {
      let data = State.radarData;
      
      // Apply filter
      if (State.radarFilter === 'gainers') {
        data = data.filter(d => d.change > 0).sort((a, b) => b.change - a.change);
      } else if (State.radarFilter === 'volume') {
        data = data.sort((a, b) => b.volume - a.volume);
      } else if (State.radarFilter === 'coiled') {
        data = data.filter(d => d.coiled).sort((a, b) => b.volatility - a.volatility);
      }
      
      Elements.marketRadar.innerHTML = data.map(d => `
        <div class="radar-item ${d.symbol === State.currentSymbol ? 'selected' : ''}" 
             data-symbol="${d.symbol}">
          <span class="radar-symbol">${d.symbol}</span>
          <span class="radar-price">${Utils.formatPrice(d.price)}</span>
          <span class="radar-change ${d.change >= 0 ? 'positive' : 'negative'}">${Utils.formatChange(d.change)}</span>
          <span class="radar-volume">${Utils.formatCompact(d.volume)}</span>
        </div>
      `).join('');
      
      Elements.marketRadar.querySelectorAll('.radar-item').forEach(item => {
        item.addEventListener('click', () => this.setSymbol(item.dataset.symbol));
      });
    },
    
    renderOrderBook() {
      const { asks, bids } = State.orderBook;
      
      if (!asks.length && !bids.length) {
        Elements.asks.innerHTML = '<div class="empty-state">NO DATA</div>';
        Elements.bids.innerHTML = '<div class="empty-state">NO DATA</div>';
        return;
      }
      
      // Calculate spread
      const bestAsk = asks[0]?.price || 0;
      const bestBid = bids[0]?.price || 0;
      const spread = bestAsk && bestBid ? ((bestAsk - bestBid) / bestBid * 10000).toFixed(1) : '--';
      Elements.spreadValue.textContent = `SPRD: ${spread} BPS`;
      
      // Render asks (top to bottom: highest to lowest)
      Elements.asks.innerHTML = asks.slice(0, 25).reverse().map((level, i) => `
        <div class="depth-level ask">
          <span class="price">${Utils.formatPrice(level.price)}</span>
          <span class="size">${Utils.formatNumber(level.size, 4)}</span>
          <span class="total">${Utils.formatCompact(level.size * level.price)}</span>
        </div>
      `).join('');
      
      // Render bids (top to bottom: highest to lowest)
      Elements.bids.innerHTML = bids.slice(0, 25).map((level, i) => `
        <div class="depth-level bid">
          <span class="price">${Utils.formatPrice(level.price)}</span>
          <span class="size">${Utils.formatNumber(level.size, 4)}</span>
          <span class="total">${Utils.formatCompact(level.size * level.price)}</span>
        </div>
      `).join('');
    },
    
    renderTrades() {
      Elements.tradesCount.textContent = State.recentTrades.length;
      
      Elements.tradesContent.innerHTML = State.recentTrades.slice(0, 50).map(t => `
        <div class="trade-row ${t.side}">
          <span class="trade-time">${Utils.formatTime(t.time)}</span>
          <span class="trade-price">${Utils.formatPrice(t.price)}</span>
          <span class="trade-size">${Utils.formatNumber(t.size, 4)}</span>
        </div>
      `).join('');
      
      // Auto-scroll to top (newest)
      Elements.tradesContent.scrollTop = 0;
    },
    
    updateFooter() {
      Elements.scanStatus.textContent = `SCAN: ${State.scanStatus}`;
      Elements.modeIndicator.textContent = `MODE: ${State.mode}`;
      Elements.modeIndicator.classList.toggle('live', State.mode === 'LIVE');
    },
    
    showToast(message, type = 'info', action = null) {
      const toast = document.createElement('div');
      toast.className = `toast ${type}`;
      toast.textContent = message;
      if (action) toast.onclick = action;
      
      Elements.toastContainer.appendChild(toast);
      
      // Auto-remove
      setTimeout(() => {
        toast.style.animation = 'toastIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
      }, 5000);
    }
  };

  // ==========================================================================
  // CHART RENDERING
  // ==========================================================================
  
  const Chart = {
    priceCtx: null,
    volumeCtx: null,
    crosshairEl: null,
    priceLabelEl: null,
    timeLabelEl: null,
    
    init() {
      this.priceCtx = Elements.priceChart.getContext('2d');
      this.volumeCtx = Elements.volumeChart.getContext('2d');
      
      // Create crosshair elements
      this.crosshairEl = document.createElement('div');
      this.crosshairEl.className = 'crosshair';
      this.crosshairEl.innerHTML = `
        <div class="crosshair-h"></div>
        <div class="crosshair-v"></div>
        <div class="crosshair-label price-label"></div>
        <div class="crosshair-label time-label"></div>
      `;
      Elements.chartOverlay.appendChild(this.crosshairEl);
      this.priceLabelEl = this.crosshairEl.querySelector('.price-label');
      this.timeLabelEl = this.crosshairEl.querySelector('.time-label');
      
      // Handle resize
      window.addEventListener('resize', Utils.debounce(() => this.resize(), 100));
      this.resize();
    },
    
    resize() {
      const rect = Elements.priceChart.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      
      [Elements.priceChart, Elements.volumeChart].forEach(canvas => {
        canvas.width = rect.width * dpr;
        canvas.height = canvas.parentElement.clientHeight * dpr;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = canvas.parentElement.clientHeight + 'px';
        canvas.getContext('2d').scale(dpr, dpr);
      });
      
      this.render();
    },
    
    render() {
      if (!State.klines.length) return;
      
      const klines = State.klines;
      const priceRect = Elements.priceChart.getBoundingClientRect();
      const volumeRect = Elements.volumeChart.getBoundingClientRect();
      const w = priceRect.width;
      const h = priceRect.height;
      const vh = volumeRect.height;
      
      // Calculate price range
      const highs = klines.map(k => k[2]);
      const lows = klines.map(k => k[3]);
      const maxPrice = Math.max(...highs);
      const minPrice = Math.min(...lows);
      const priceRange = maxPrice - minPrice || 1;
      
      const maxVol = Math.max(...klines.map(k => k[5]));
      
      const candleWidth = Math.max(1, (w / klines.length) * 0.8);
      const spacing = w / klines.length;
      
      // Clear
      this.priceCtx.clearRect(0, 0, w, h);
      this.volumeCtx.clearRect(0, 0, w, vh);
      
      // Draw grid
      this.drawGrid(w, h, vh);
      
      // Draw candles
      klines.forEach((k, i) => {
        const x = i * spacing + spacing / 2;
        const open = k[1], high = k[2], low = k[3], close = k[4], vol = k[5];
        const isGreen = close >= open;
        const color = isGreen ? '#22c55e' : '#ef4444';
        const bodyTop = h - (Math.max(open, close) - minPrice) / priceRange * h;
        const bodyHeight = Math.max(1, Math.abs(close - open) / priceRange * h);
        const wickTop = h - (high - minPrice) / priceRange * h;
        const wickBottom = h - (low - minPrice) / priceRange * h;
        
        // Wick
        this.priceCtx.strokeStyle = color;
        this.priceCtx.lineWidth = 1;
        this.priceCtx.beginPath();
        this.priceCtx.moveTo(x, wickTop);
        this.priceCtx.lineTo(x, wickBottom);
        this.priceCtx.stroke();
        
        // Body
        this.priceCtx.fillStyle = color;
        this.priceCtx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
        
        // Volume
        const volHeight = (vol / maxVol) * vh * 0.9;
        this.volumeCtx.fillStyle = color + '80';
        this.volumeCtx.fillRect(x - candleWidth / 2, vh - volHeight, candleWidth, volHeight);
      });
      
      // Current price line
      const lastClose = klines[klines.length - 1][4];
      const lastY = h - (lastClose - minPrice) / priceRange * h;
      this.priceCtx.strokeStyle = '#22d3ee80';
      this.priceCtx.lineWidth = 1;
      this.priceCtx.setLineDash([4, 4]);
      this.priceCtx.beginPath();
      this.priceCtx.moveTo(0, lastY);
      this.priceCtx.lineTo(w, lastY);
      this.priceCtx.stroke();
      this.priceCtx.setLineDash([]);
    },
    
    drawGrid(w, h, vh) {
      const ctx = this.priceCtx;
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 1;
      
      // Horizontal lines (5)
      for (let i = 0; i <= 4; i++) {
        const y = (h / 4) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      
      // Vertical lines (6)
      for (let i = 0; i <= 6; i++) {
        const x = (w / 6) * i;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      
      // Volume grid
      const vctx = this.volumeCtx;
      vctx.strokeStyle = '#1e293b';
      vctx.lineWidth = 1;
      for (let i = 0; i <= 2; i++) {
        const y = (vh / 2) * i;
        vctx.beginPath();
        vctx.moveTo(0, y);
        vctx.lineTo(w, y);
        vctx.stroke();
      }
    },
    
    showCrosshair(e) {
      const rect = Elements.priceChart.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      
      const klines = State.klines;
      if (!klines.length) return;
      
      const spacing = rect.width / klines.length;
      const index = Math.floor(x / spacing);
      if (index < 0 || index >= klines.length) return;
      
      const k = klines[index];
      const price = k[4];
      const time = new Date(k[0]);
      
      this.crosshairEl.style.display = 'block';
      this.crosshairEl.querySelector('.crosshair-h').style.top = y + 'px';
      this.crosshairEl.querySelector('.crosshair-v').style.left = x + 'px';
      
      this.priceLabelEl.textContent = Utils.formatPrice(price);
      this.priceLabelEl.style.left = (x + 10) + 'px';
      this.priceLabelEl.style.top = (y - 20) + 'px';
      
      this.timeLabelEl.textContent = Utils.formatDateTime(k[0]);
      this.timeLabelEl.style.left = (x + 10) + 'px';
      this.timeLabelEl.style.top = (y + 10) + 'px';
    },
    
    hideCrosshair() {
      this.crosshairEl.style.display = 'none';
    },
    
    handleClick(e) {
      // Could add drawing tools here
    }
  };

  // ==========================================================================
  // RADAR MODULE
  // ==========================================================================
  
  const Radar = {
    async load() {
      try {
        const data = await Api.request('/radar');
        State.radarData = data.radar || [];
        UI.renderRadar();
      } catch (error) {
        console.error('Radar load error:', error);
      }
    }
  };

  // ==========================================================================
  // SIGNALS MODULE
  // ==========================================================================
  
  const Signals = {
    async load() {
      try {
        const data = await Api.getSignals();
        State.signals = data.signals || [];
        this.render();
      } catch (error) {
        console.error('Signals load error:', error);
      }
    },
    
    add(signal) {
      const exists = State.signals.find(s => s.id === signal.id);
      if (!exists) {
        State.signals.unshift(signal);
        if (State.signals.length > 50) State.signals.pop();
        this.render();
      }
    },
    
    render() {
      Elements.signalsList.innerHTML = State.signals.map(s => `
        <div class="signal-card ${s.id === State.selectedSignalId ? 'selected' : ''}" 
             data-signal-id="${s.id}">
          <div class="signal-header">
            <span class="signal-symbol">${s.symbol}</span>
            <span class="signal-type ${s.side}">${s.side.toUpperCase()}</span>
          </div>
          <div class="signal-meta">
            <div class="signal-meta-item">
              <span class="signal-meta-label">Entry</span>
              <span class="signal-meta-value">${Utils.formatPrice(s.entry)}</span>
            </div>
            <div class="signal-meta-item">
              <span class="signal-meta-label">SL</span>
              <span class="signal-meta-value danger">${Utils.formatPrice(s.stopLoss)}</span>
            </div>
            <div class="signal-meta-item">
              <span class="signal-meta-label">TP1</span>
              <span class="signal-meta-value success">${Utils.formatPrice(s.tp1)}</span>
            </div>
            <div class="signal-meta-item">
              <span class="signal-meta-label">R:R</span>
              <span class="signal-meta-value">${s.riskReward?.toFixed(2) || '--'}</span>
            </div>
          </div>
          <div class="signal-rationale">${s.rationale || 'No rationale provided'}</div>
        </div>
      `).join('');
      
      Elements.signalsList.querySelectorAll('.signal-card').forEach(card => {
        card.addEventListener('click', () => this.select(card.dataset.signalId));
      });
    },
    
    select(signalId) {
      State.selectedSignalId = signalId;
      const signal = State.signals.find(s => s.id === signalId);
      if (signal) {
        TradePlan.show(signal);
      }
      this.render();
    }
  };

  // ==========================================================================
  // POSITIONS MODULE
  // ==========================================================================
  
  const Positions = {
    async load() {
      try {
        const data = await Api.getPositions();
        State.positions = data.positions || [];
        this.render();
      } catch (error) {
        console.error('Positions load error:', error);
      }
    },
    
    update(positions) {
      State.positions = positions;
      this.render();
      Account.load(); // Refresh equity
    },
    
    render() {
      if (!State.positions.length) {
        Elements.positionsList.innerHTML = '<div class="empty-state">NO OPEN POSITIONS</div>';
        return;
      }
      
      Elements.positionsList.innerHTML = State.positions.map(p => `
        <div class="position-card">
          <div class="position-header">
            <span class="position-symbol">${p.symbol}</span>
            <span class="position-side ${p.side}">${p.side.toUpperCase()}</span>
          </div>
          <div class="position-meta">
            <div class="position-meta-item">
              <span class="position-meta-label">Entry</span>
              <span class="position-meta-value">${Utils.formatPrice(p.entryPrice)}</span>
            </div>
            <div class="position-meta-item">
              <span class="position-meta-label">Mark</span>
              <span class="position-meta-value">${Utils.formatPrice(p.markPrice)}</span>
            </div>
            <div class="position-meta-item">
              <span class="position-meta-label">Size</span>
              <span class="position-meta-value">${Utils.formatNumber(p.size, 4)}</span>
            </div>
          </div>
          <div class="position-meta">
            <div class="position-meta-item">
              <span class="position-meta-label">PnL</span>
              <span class="position-meta-value position-pnl ${p.unrealizedPnl >= 0 ? 'positive' : 'negative'}">${Utils.formatNumber(p.unrealizedPnl, 2)}</span>
            </div>
            <div class="position-meta-item">
              <span class="position-meta-label">PnL%</span>
              <span class="position-meta-value position-pnl ${p.unrealizedPnlPct >= 0 ? 'positive' : 'negative'}">${Utils.formatNumber(p.unrealizedPnlPct, 2)}%</span>
            </div>
            <div class="position-meta-item">
              <span class="position-meta-label">Value</span>
              <span class="position-meta-value">${Utils.formatNumber(p.positionValue, 2)}</span>
            </div>
          </div>
        </div>
      `).join('');
    }
  };

  // ==========================================================================
  // ACCOUNT MODULE
  // ==========================================================================
  
  const Account = {
    async load() {
      try {
        const data = await Api.getEquity();
        this.update(data);
      } catch (error) {
        console.error('Account load error:', error);
      }
    },
    
    update(data) {
      State.equity = data.equity || 0;
      State.pnl = data.pnl || 0;
      State.pnlPct = data.pnlPct || 0;
      State.balance = data.balance || 0;
      
      Elements.equityValue.textContent = Utils.formatNumber(State.equity, 2);
      Elements.pnlValue.textContent = `${State.pnl >= 0 ? '+' : ''}${Utils.formatNumber(State.pnl, 2)} (${State.pnlPct >= 0 ? '+' : ''}${Utils.formatNumber(State.pnlPct, 2)}%)`;
      Elements.pnlValue.className = 'pnl-value ' + (State.pnl >= 0 ? 'positive' : 'negative');
      
      // Update equity chart data
      if (data.equityHistory) {
        State.equityData = data.equityHistory;
      }
    }
  };

  // ==========================================================================
  // TRADE PLAN MODULE
  // ==========================================================================
  
  const TradePlan = {
    currentSignal: null,
    
    show(signal) {
      this.currentSignal = signal;
      
      Elements.modalSymbol.textContent = signal.symbol;
      Elements.planEntry.textContent = Utils.formatPrice(signal.entry);
      Elements.planSize.textContent = Utils.formatNumber(signal.size || 0, 4);
      Elements.planValue.textContent = Utils.formatNumber(signal.value || 0, 2);
      Elements.planSL.textContent = Utils.formatPrice(signal.stopLoss);
      Elements.planRisk.textContent = Utils.formatNumber(signal.risk || 0, 2);
      Elements.planRiskPct.textContent = Utils.formatNumber(signal.riskPct || 0, 2) + '%';
      Elements.planTP1.textContent = Utils.formatPrice(signal.tp1);
      Elements.planTP2.textContent = Utils.formatPrice(signal.tp2);
      Elements.planTP3.textContent = Utils.formatPrice(signal.tp3);
      Elements.planRR.textContent = Utils.formatNumber(signal.riskReward || 0, 2);
      Elements.planWR.textContent = Utils.formatNumber(signal.winRate || 0, 1) + '%';
      Elements.planExp.textContent = Utils.formatNumber(signal.expectancy || 0, 4);
      Elements.planRationale.textContent = signal.rationale || 'No rationale provided';
      
      // Enable/disable buttons based on mode
      const isLive = State.mode === 'LIVE';
      Elements.btnBuy.disabled = !isLive;
      Elements.btnSell.disabled = !isLive;
      if (!isLive) {
        Elements.btnBuy.textContent = 'BUY (SHADOW)';
        Elements.btnSell.textContent = 'SELL (SHADOW)';
      } else {
        Elements.btnBuy.textContent = 'BUY';
        Elements.btnSell.textContent = 'SELL';
      }
      
      // Update trade plan panel
      Elements.tradePlan.innerHTML = `
        <div class="plan-active">
          <div class="plan-row"><span>${signal.symbol} ${signal.side.toUpperCase()}</span><span class="value">${Utils.formatPrice(signal.entry)}</span></div>
          <div class="plan-row"><span>SL</span><span class="value danger">${Utils.formatPrice(signal.stopLoss)}</span></div>
          <div class="plan-row"><span>TP1</span><span class="value success">${Utils.formatPrice(signal.tp1)}</span></div>
          <div class="plan-row"><span>R:R</span><span class="value">${Utils.formatNumber(signal.riskReward || 0, 2)}</span></div>
        </div>
      `;
      
      Elements.tradeModal.showModal();
    },
    
    close() {
      this.currentSignal = null;
      State.selectedSignalId = null;
      Signals.render();
    },
    
    async execute(side) {
      if (!this.currentSignal) return;
      
      const signal = this.currentSignal;
      const orderData = {
        symbol: signal.symbol,
        side: side,
        type: 'market',
        size: signal.size || '0',
        clientOid: `hunter_${Date.now()}`
      };
      
      try {
        UI.showToast(`Placing ${side.toUpperCase()} order...`, 'info');
        const result = await Api.placeOrder(orderData);
        
        UI.showToast(`${side.toUpperCase()} order placed: ${result.orderId}`, 'success');
        this.close();
        await Positions.load();
        await Account.load();
        
      } catch (error) {
        UI.showToast(`Order failed: ${error.message}`, 'error');
      }
    }
  };

  // ==========================================================================
  // EQUITY MODAL
  // ==========================================================================
  
  const EquityModal = {
    equityChart: null,
    
    open() {
      Elements.equityModal.showModal();
      this.renderChart();
    },
    
    close() {
      Elements.equityModal.close();
    },
    
    renderChart() {
      const ctx = Elements.equityChart.getContext('2d');
      const data = State.equityData;
      
      if (!data || !data.length) {
        Elements.equityStats.innerHTML = '<div class="empty-state">NO EQUITY DATA</div>';
        return;
      }
      
      // Simple equity chart rendering
      const rect = Elements.equityChart.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      Elements.equityChart.width = rect.width * dpr;
      Elements.equityChart.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      
      const w = rect.width;
      const h = rect.height;
      
      const values = data.map(d => d.equity);
      const max = Math.max(...values);
      const min = Math.min(...values);
      const range = max - min || 1;
      
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = '#22c55e';
      ctx.lineWidth = 2;
      ctx.beginPath();
      
      data.forEach((d, i) => {
        const x = (i / (data.length - 1)) * w;
        const y = h - ((d.equity - min) / range) * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      
      // Stats
      const start = values[0];
      const end = values[values.length - 1];
      const totalReturn = ((end - start) / start * 100);
      const maxDD = this.calculateMaxDrawdown(values);
      const sharpe = this.calculateSharpe(values);
      
      Elements.equityStats.innerHTML = `
        <div class="equity-stat">
          <span class="equity-stat-label">TOTAL RETURN</span>
          <span class="equity-stat-value ${totalReturn >= 0 ? 'success' : 'danger'}">${totalReturn >= 0 ? '+' : ''}${totalReturn.toFixed(2)}%</span>
        </div>
        <div class="equity-stat">
          <span class="equity-stat-label">MAX DRAWDOWN</span>
          <span class="equity-stat-value danger">${maxDD.toFixed(2)}%</span>
        </div>
        <div class="equity-stat">
          <span class="equity-stat-label">SHARPE</span>
          <span class="equity-stat-value">${sharpe.toFixed(2)}</span>
        </div>
        <div class="equity-stat">
          <span class="equity-stat-label">CURRENT</span>
          <span class="equity-stat-value">${Utils.formatNumber(end, 2)}</span>
        </div>
      `;
    },
    
    calculateMaxDrawdown(values) {
      let peak = values[0];
      let maxDD = 0;
      for (const v of values) {
        if (v > peak) peak = v;
        const dd = (peak - v) / peak * 100;
        if (dd > maxDD) maxDD = dd;
      }
      return maxDD;
    },
    
    calculateSharpe(values) {
      if (values.length < 2) return 0;
      const returns = [];
      for (let i = 1; i < values.length; i++) {
        returns.push((values[i] - values[i-1]) / values[i-1]);
      }
      const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
      const std = Math.sqrt(returns.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / returns.length);
      return std ? mean / std * Math.sqrt(252) : 0;
    }
  };

  // ==========================================================================
  // INITIALIZATION
  // ==========================================================================
  
  document.addEventListener('DOMContentLoaded', () => {
    Chart.init();
    UI.init();
  });

  // Expose for debugging
  window.KuCoinHunter = {
    State,
    UI,
    Chart,
    Signals,
    Positions,
    Account,
    TradePlan,
    EquityModal,
    WS,
    Api,
    Utils
  };
})();