import { Component, OnInit, OnDestroy, inject, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { BotService, Bot } from '../../services/bot.service';
import { ExchangeService, Exchange, Balance } from '../../services/exchange.service';
import { WebSocketService } from '../../services/websocket.service';
import { WalletService, WalletInfo, WalletTransaction } from '../../services/wallet.service';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';

interface BudgetPoint {
  timestamp: string;
  balance: number;
}

interface GridLevel {
  index: number;
  price: number;
  orderType: string | null;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, DropdownComponent],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly botService = inject(BotService);
  private readonly exchangeService = inject(ExchangeService);
  private readonly wsService = inject(WebSocketService);
  private readonly walletService = inject(WalletService);
  private wsSub?: Subscription;

  @ViewChild('budgetChart') budgetChartRef!: ElementRef<HTMLCanvasElement>;

  bots: Bot[] = [];
  exchanges: Exchange[] = [];
  exchangeBalances: { [key: number]: Balance[] } = {};

  // Wallet
  wallets: { [key: number]: WalletInfo } = {};
  walletTransactions: { [key: number]: WalletTransaction[] } = {};
  showWalletTx: { [key: number]: boolean } = {};
  depositAmount: { [key: number]: number } = {};
  withdrawAmount: { [key: number]: number } = {};
  walletActionLoading: { [key: number]: boolean } = {};

  openOrders: Record<string, unknown>[] = [];
  orderHistory: Record<string, unknown>[] = [];
  tradeHistory: Record<string, unknown>[] = [];
  activeOrderTab: 'open' | 'history' | 'trades' = 'open';

  // Budget trend
  budgetData: BudgetPoint[] = [];
  filteredBudgetData: BudgetPoint[] = [];
  selectedBudgetBot: string | number = 'overall';
  selectedTimeFilter = '1h';
  budgetBotOptions: DropdownOption[] = [{ value: 'overall', label: 'Overall' }];
  timeFilters = [
    { value: '30m', label: '30m' },
    { value: '1h', label: '1h' },
    { value: '2h', label: '2h' },
    { value: '6h', label: '6h' },
    { value: '12h', label: '12h' },
    { value: '24h', label: '24h' },
    { value: '7d', label: '7d' },
    { value: 'all', label: 'All' },
  ];
  chartPoints: { x: number; y: number; data: BudgetPoint }[] = [];
  chartTooltip = { visible: false, x: 0, y: 0, balance: '', time: '' };

  // Grid modal
  gridModalBot: Bot | null = null;
  gridLevels: GridLevel[] = [];

  get faultBots(): Bot[] {
    return this.bots.filter((b) => b.status === 'fault');
  }

  ngOnInit(): void {
    this.loadBots();
    this.loadExchanges();
    this.loadAllOrders();

    this.wsService.connect();
    this.wsSub = this.wsService.messages.subscribe((msg) =>
      this.handleWsMessage(msg)
    );
  }

  ngOnDestroy(): void {
    this.wsSub?.unsubscribe();
  }

  private handleWsMessage(msg: Record<string, unknown>): void {
    const type = msg['type'];
    if (type === 'status') {
      this.handleStatusMessage(msg);
      return;
    }
    if (type === 'order_update') {
      this.handleOrderUpdateMessage(msg);
    }
  }

  private handleStatusMessage(msg: Record<string, unknown>): void {
    const botId = msg['bot_id'] as number;
    const bot = this.bots.find((b) => b.id === botId);
    if (bot) {
      bot.status = msg['status'] as string;
    }

    // Refresh orders when a bot stops (not on start — let the
    // order_update WS messages handle real-time additions to
    // avoid racing with loadAllOrders).
    if ((msg['status'] as string) === 'stopped') {
      this.loadAllOrders();
    }
  }

  private handleOrderUpdateMessage(msg: Record<string, unknown>): void {
    const order = msg['order'] as Record<string, unknown> | undefined;
    if (!order) {
      return;
    }

    order['bot_id'] = msg['bot_id'];
    const status = order['status'] as string;
    const eid = order['exchange_order_id'];

    if (status === 'filled' || status === 'cancelled') {
      this.openOrders = this.openOrders.filter(
        (o) => o['exchange_order_id'] !== eid
      );
      if (status === 'filled') {
        this.orderHistory.unshift(order);
      }
      return;
    }

    if (eid && !this.openOrders.some((o) => o['exchange_order_id'] === eid)) {
      this.openOrders.unshift(order);
    }
  }

  loadBots(): void {
    this.botService.list().subscribe((bots) => {
      this.bots = bots;
      this.budgetBotOptions = [
        { value: 'overall', label: 'Overall' },
        ...bots.map((b) => ({ value: b.id, label: b.name })),
      ];
      this.loadBudgetHistory();
    });
  }

  loadExchanges(): void {
    this.exchangeService.list().subscribe((exs) => {
      this.exchanges = exs;
      for (const ex of exs) {
        this.exchangeService.getBalances(ex.id).subscribe((bals) => {
          this.exchangeBalances[ex.id] = bals;
        });
        this.loadWallet(ex.id);
      }
    });
  }

  loadWallet(exchangeId: number): void {
    this.walletService.getWallet(exchangeId).subscribe((w) => {
      this.wallets[exchangeId] = w;
    });
  }

  loadWalletTransactions(exchangeId: number): void {
    this.walletService.getTransactions(exchangeId).subscribe((txs) => {
      this.walletTransactions[exchangeId] = txs;
    });
  }

  toggleWalletTx(exchangeId: number): void {
    this.showWalletTx[exchangeId] = !this.showWalletTx[exchangeId];
    if (this.showWalletTx[exchangeId]) {
      this.loadWalletTransactions(exchangeId);
    }
  }

  doDeposit(exchangeId: number): void {
    const amount = this.depositAmount[exchangeId];
    if (!amount || amount <= 0) return;
    this.walletActionLoading[exchangeId] = true;
    this.walletService.deposit(exchangeId, amount).subscribe({
      next: (w) => {
        this.wallets[exchangeId] = w;
        this.depositAmount[exchangeId] = 0;
        this.walletActionLoading[exchangeId] = false;
        if (this.showWalletTx[exchangeId]) this.loadWalletTransactions(exchangeId);
        this.loadBudgetHistory();
      },
      error: () => { this.walletActionLoading[exchangeId] = false; },
    });
  }

  doWithdraw(exchangeId: number): void {
    const amount = this.withdrawAmount[exchangeId];
    if (!amount || amount <= 0) return;
    this.walletActionLoading[exchangeId] = true;
    this.walletService.withdraw(exchangeId, amount).subscribe({
      next: (w) => {
        this.wallets[exchangeId] = w;
        this.withdrawAmount[exchangeId] = 0;
        this.walletActionLoading[exchangeId] = false;
        if (this.showWalletTx[exchangeId]) this.loadWalletTransactions(exchangeId);
        this.loadBudgetHistory();
      },
      error: () => { this.walletActionLoading[exchangeId] = false; },
    });
  }

  loadAllOrders(): void {
    this.openOrders = [];
    this.orderHistory = [];
    this.tradeHistory = [];
    this.botService.list().subscribe((bots) => {
      for (const bot of bots) {
        // Fetch live open orders from exchange (single source of truth).
        this.botService.getOpenOrders(bot.id).subscribe({
          next: (orders) => {
            for (const o of orders) {
              const order = o as Record<string, unknown>;
              order['bot_id'] = bot.id;
              // Dedup by exchange_order_id.
              const eid = order['exchange_order_id'];
              if (eid && !this.openOrders.some((x) => x['exchange_order_id'] === eid)) {
                this.openOrders.push(order);
              }
            }
          },
          error: () => {},
        });
        // Fetch persisted order history (filled/cancelled).
        this.botService.getOrders(bot.id).subscribe((orders) => {
          for (const o of orders) {
            const order = o as Record<string, unknown>;
            order['bot_id'] = bot.id;
            this.orderHistory.push(order);
          }
        });
        this.botService.getTrades(bot.id).subscribe((trades) => {
          for (const t of trades) {
            const trade = t as Record<string, unknown>;
            trade['bot_id'] = bot.id;
            this.tradeHistory.push(trade);
          }
        });
      }
    });
  }

  loadBudgetHistory(): void {
    if (this.selectedBudgetBot === 'overall') {
      this.botService.getOverallBudgetHistory().subscribe((data) => {
        this.budgetData = (data as BudgetPoint[]);
        this.filterBudgetData();
      });
    } else {
      const botId = this.selectedBudgetBot as number;
      this.botService.getBudgetHistory(botId).subscribe((data) => {
        this.budgetData = (data as BudgetPoint[]);
        this.filterBudgetData();
      });
    }
  }

  filterBudgetData(): void {
    if (this.selectedTimeFilter === 'all') {
      this.filteredBudgetData = [...this.budgetData];
      setTimeout(() => this.drawChart());
      return;
    }

    const now = Date.now();
    const minutes: Record<string, number> = {
      '30m': 30, '1h': 60, '2h': 120, '6h': 360,
      '12h': 720, '24h': 1440, '7d': 10080,
    };
    const mins = minutes[this.selectedTimeFilter] || 60;
    const cutoff = now - mins * 60 * 1000;

    this.filteredBudgetData = this.budgetData.filter((p) => {
      // SQLite timestamps are UTC but lack the Z suffix
      const ts = p.timestamp.endsWith('Z') ? p.timestamp : p.timestamp + 'Z';
      return new Date(ts).getTime() >= cutoff;
    });
    setTimeout(() => this.drawChart());
  }

  selectTimeFilter(value: string): void {
    this.selectedTimeFilter = value;
    this.filterBudgetData();
  }

  drawChart(): void {
    if (!this.budgetChartRef) return;
    const canvas = this.budgetChartRef.nativeElement;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = canvas.parentElement?.getBoundingClientRect();
    canvas.width = rect?.width || 800;
    canvas.height = rect?.height || 250;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    this.chartPoints = [];

    const data = [...this.filteredBudgetData].reverse();
    if (data.length === 0) return;

    const values = data.map((d) => d.balance);
    const dataMin = Math.min(...values);
    const dataMax = Math.max(...values);

    // Y-axis: absolute scale with padding (10% or minimum 1 unit)
    const spread = dataMax - dataMin;
    const yPad = spread > 0 ? spread * 0.1 : Math.max(dataMax * 0.1, 1);
    const yMin = Math.max(0, dataMin - yPad);
    const yMax = dataMax + yPad;
    const yRange = yMax - yMin;

    const padding = { top: 20, right: 20, bottom: 30, left: 60 };
    const w = canvas.width - padding.left - padding.right;
    const h = canvas.height - padding.top - padding.bottom;

    // Compute nice tick values for Y-axis
    const tickCount = 5;
    const rawStep = yRange / tickCount;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep || 1)));
    const niceStep = Math.ceil(rawStep / magnitude) * magnitude;
    const tickStart = Math.floor(yMin / niceStep) * niceStep;

    // Grid lines and Y labels
    ctx.strokeStyle = 'rgba(42, 42, 68, 0.5)';
    ctx.lineWidth = 1;
    for (let tick = tickStart; tick <= yMax + niceStep; tick += niceStep) {
      const yPos = padding.top + h - ((tick - yMin) / yRange) * h;
      if (yPos < padding.top - 5 || yPos > padding.top + h + 5) continue;
      ctx.beginPath();
      ctx.moveTo(padding.left, yPos);
      ctx.lineTo(canvas.width - padding.right, yPos);
      ctx.stroke();

      ctx.fillStyle = '#666';
      ctx.font = '10px monospace';
      ctx.textAlign = 'right';
      ctx.fillText(tick.toFixed(2), padding.left - 8, yPos + 4);
    }

    // Helper: convert data value to canvas Y
    const toY = (val: number) => padding.top + h - ((val - yMin) / yRange) * h;

    // Single data point
    if (data.length === 1) {
      const px = padding.left + w / 2;
      const py = toY(data[0].balance);

      ctx.beginPath();
      ctx.strokeStyle = '#00aaff';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.moveTo(padding.left, py);
      ctx.lineTo(padding.left + w, py);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.beginPath();
      ctx.fillStyle = '#00aaff';
      ctx.shadowColor = 'rgba(0, 170, 255, 0.6)';
      ctx.shadowBlur = 8;
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;

      this.chartPoints.push({ x: px, y: py, data: data[0] });
      return;
    }

    // Compute point positions
    const points: { x: number; y: number }[] = [];
    for (let i = 0; i < data.length; i++) {
      const px = padding.left + (i / (data.length - 1)) * w;
      const py = toY(data[i].balance);
      points.push({ x: px, y: py });
      this.chartPoints.push({ x: px, y: py, data: data[i] });
    }

    // Line
    ctx.beginPath();
    ctx.strokeStyle = '#00aaff';
    ctx.lineWidth = 2;
    ctx.shadowColor = 'rgba(0, 170, 255, 0.5)';
    ctx.shadowBlur = 6;
    for (let i = 0; i < points.length; i++) {
      if (i === 0) ctx.moveTo(points[i].x, points[i].y);
      else ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.stroke();

    // Gradient fill
    ctx.shadowBlur = 0;
    const lastPoint = points.at(-1);
    if (!lastPoint) {
      return;
    }
    ctx.lineTo(lastPoint.x, padding.top + h);
    ctx.lineTo(points[0].x, padding.top + h);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + h);
    gradient.addColorStop(0, 'rgba(0, 170, 255, 0.15)');
    gradient.addColorStop(1, 'rgba(0, 170, 255, 0)');
    ctx.fillStyle = gradient;
    ctx.fill();

    // Draw dots at each data point
    for (const pt of points) {
      ctx.beginPath();
      ctx.fillStyle = '#00aaff';
      ctx.arc(pt.x, pt.y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  onChartMouseMove(event: MouseEvent): void {
    const canvas = this.budgetChartRef?.nativeElement;
    if (!canvas || this.chartPoints.length === 0) {
      this.chartTooltip.visible = false;
      return;
    }

    const canvasRect = canvas.getBoundingClientRect();
    const mx = event.clientX - canvasRect.left;
    const my = event.clientY - canvasRect.top;
    // Scale to canvas coordinates (canvas pixel size vs CSS size)
    const scaleX = canvas.width / canvasRect.width;
    const scaleY = canvas.height / canvasRect.height;
    const cx = mx * scaleX;
    const cy = my * scaleY;

    // Find closest point within 20px
    let closest: (typeof this.chartPoints)[0] | null = null;
    let minDist = 20 * scaleX;
    for (const pt of this.chartPoints) {
      const dist = Math.hypot(pt.x - cx, pt.y - cy);
      if (dist < minDist) {
        minDist = dist;
        closest = pt;
      }
    }

    if (closest) {
      const ts = closest.data.timestamp.endsWith('Z')
        ? closest.data.timestamp
        : closest.data.timestamp + 'Z';
      const date = new Date(ts);
      this.chartTooltip = {
        visible: true,
        x: closest.x / scaleX + 12,
        y: closest.y / scaleY - 30,
        balance: closest.data.balance.toFixed(2),
        time: date.toLocaleString(),
      };
    } else {
      this.chartTooltip.visible = false;
    }
  }

  onChartMouseLeave(): void {
    this.chartTooltip.visible = false;
  }

  getBotName(botId: unknown): string {
    const id = botId as number;
    return this.bots.find((b) => b.id === id)?.name || `Bot #${id}`;
  }

  getBalances(exchangeId: number): Balance[] {
    return this.exchangeBalances[exchangeId] || [];
  }

  startBot(bot: Bot): void {
    this.botService.start(bot.id).subscribe((b) => {
      const idx = this.bots.findIndex((x) => x.id === b.id);
      if (idx >= 0) this.bots[idx] = b;
    });
  }

  stopBot(bot: Bot): void {
    this.botService.stop(bot.id).subscribe((b) => {
      const idx = this.bots.findIndex((x) => x.id === b.id);
      if (idx >= 0) this.bots[idx] = b;
    });
  }

  deleteBot(bot: Bot): void {
    if (confirm(`Delete bot "${bot.name}"? This will cancel all open orders on the exchange.`)) {
      this.botService.delete(bot.id).subscribe(() => {
        this.loadBots();
        this.loadAllOrders();
      });
    }
  }

  botParamEntries(bot: Bot): [string, unknown][] {
    if (!bot.strategy_params) return [];
    return Object.entries(bot.strategy_params);
  }

  showGrid(bot: Bot): void {
    this.gridModalBot = bot;
    const params = bot.strategy_params || {};
    const upper = Number(params['upper_price'] || 0);
    const lower = Number(params['lower_price'] || 0);
    const num = Number(params['num_grids'] || 10);
    if (upper <= lower || num < 2) {
      this.gridLevels = [];
      return;
    }

    const spread = (upper - lower) / num;
    const levels: GridLevel[] = [];
    for (let i = 0; i <= num; i++) {
      levels.push({
        index: i,
        price: lower + spread * i,
        orderType: null,
      });
    }

    // Load open orders to mark active levels.
    this.botService.getOpenOrders(bot.id).subscribe((orders: any[]) => {
      const tolerance = spread / 2;
      for (const order of orders) {
        const orderPrice = Number(order.price);
        const side = (order.side || '').toLowerCase();
        for (const lvl of levels) {
          if (Math.abs(lvl.price - orderPrice) < tolerance && !lvl.orderType) {
            lvl.orderType = side;
            break;
          }
        }
      }
      this.gridLevels = [...levels];
    });

    this.gridLevels = levels;
  }
}
