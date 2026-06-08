import { Component, OnInit, OnDestroy, inject, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';
import { BotService, Bot, BotGridLevel } from '../../services/bot.service';
import { ExchangeService, Exchange, Balance } from '../../services/exchange.service';
import { WebSocketService } from '../../services/websocket.service';
import { WalletService, WalletInfo, WalletTransaction } from '../../services/wallet.service';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';
import { AppDateTimePipe } from '../../shared/pipes/app-datetime.pipe';
import { DateTimeService } from '../../core/date-time.service';

interface BudgetPoint {
  timestamp: string;
  balance: number;
}

interface GridLevel {
  index: number;
  price: number;
  orderType: string | null;
}

type OrderDetailKind = 'open' | 'history' | 'trades';

interface OrderDetailField {
  label: string;
  value: string;
}

interface OrderDetailPopover {
  kind: OrderDetailKind;
  title: string;
  subtitle: string;
  fields: OrderDetailField[];
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    DropdownComponent,
    AppDateTimePipe,
  ],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly botService = inject(BotService);
  private readonly exchangeService = inject(ExchangeService);
  private readonly wsService = inject(WebSocketService);
  private readonly walletService = inject(WalletService);
  private readonly dateTimeService = inject(DateTimeService);
  private wsSub?: Subscription;

  @ViewChild('budgetChart') budgetChartRef!: ElementRef<HTMLCanvasElement>;

  bots: Bot[] = [];
  exchanges: Exchange[] = [];
  exchangeBalances: { [key: number]: Balance[] } = {};
  exchangeBalanceErrors: { [key: number]: string } = {};

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
  selectedOrderDetail: OrderDetailPopover | null = null;

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
  modalOffsetX = 0;
  modalOffsetY = 0;
  isModalDragging = false;
  private dragOriginX = 0;
  private dragOriginY = 0;

  private readonly onModalDragMove = (event: MouseEvent): void => {
    if (!this.isModalDragging) {
      return;
    }
    this.modalOffsetX = event.clientX - this.dragOriginX;
    this.modalOffsetY = event.clientY - this.dragOriginY;
  };

  private readonly onModalDragEnd = (): void => {
    if (!this.isModalDragging) {
      return;
    }
    this.isModalDragging = false;
    globalThis.removeEventListener('mousemove', this.onModalDragMove);
    globalThis.removeEventListener('mouseup', this.onModalDragEnd);
  };

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
    this.onModalDragEnd();
    this.wsSub?.unsubscribe();
  }

  startModalDrag(event: MouseEvent): void {
    if (event.button !== 0) {
      return;
    }
    this.isModalDragging = true;
    this.dragOriginX = event.clientX - this.modalOffsetX;
    this.dragOriginY = event.clientY - this.modalOffsetY;
    globalThis.addEventListener('mousemove', this.onModalDragMove);
    globalThis.addEventListener('mouseup', this.onModalDragEnd);
  }

  private handleWsMessage(msg: Record<string, unknown>): void {
    const type = msg['type'];
    if (type === 'status') {
      this.handleStatusMessage(msg);
      return;
    }
    if (type === 'order_update') {
      this.handleOrderUpdateMessage(msg);
      return;
    }
    if (type === 'budget_snapshot') {
      this.handleBudgetSnapshotMessage(msg);
    }
  }

  private handleBudgetSnapshotMessage(msg: Record<string, unknown>): void {
    const botId = msg['bot_id'] as number | undefined;
    const balance = Number(msg['balance']);
    if (!botId || !Number.isFinite(balance)) {
      return;
    }

    const point: BudgetPoint = {
      timestamp: new Date().toISOString(),
      balance,
    };

    if (this.selectedBudgetBot === 'overall') {
      this.budgetData.unshift(point);
      this.filterBudgetData();
      return;
    }

    if (this.selectedBudgetBot === botId) {
      this.budgetData.unshift(point);
      this.filterBudgetData();
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
        this.exchangeService.getBalances(ex.id).subscribe({
          next: (bals) => {
            this.exchangeBalances[ex.id] = bals;
            this.exchangeBalanceErrors[ex.id] = '';
          },
          error: (err) => {
            this.exchangeBalances[ex.id] = [];
            const detail = err?.error?.detail as string | undefined;
            this.exchangeBalanceErrors[ex.id] =
              detail || 'Failed to load balances for this exchange.';
          },
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
    this.closeOrderDetail();
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
    const sinceMinutes = this.getSelectedSinceMinutes();
    const limit = this.getHistoryLimit();

    if (this.selectedBudgetBot === 'overall') {
      this.botService.getOverallBudgetHistory(limit, sinceMinutes).subscribe((data) => {
        this.budgetData = (data as BudgetPoint[]);
        this.filterBudgetData();
      });
    } else {
      const botId = this.selectedBudgetBot as number;
      this.botService.getBudgetHistory(botId, limit, sinceMinutes).subscribe((data) => {
        this.budgetData = (data as BudgetPoint[]);
        this.filterBudgetData();
      });
    }
  }

  private getSelectedSinceMinutes(): number | undefined {
    return this.getTimeFilterConfig().windowMinutes;
  }

  private getTimeFilterConfig(): {
    windowMinutes?: number;
    aggregateBucketMinutes: number;
    axisTickMinutes: number;
  } {
    const configByFilter: Record<string, {
      windowMinutes?: number;
      aggregateBucketMinutes: number;
      axisTickMinutes: number;
    }> = {
      '30m': { windowMinutes: 30, aggregateBucketMinutes: 1, axisTickMinutes: 5 },
      '1h': { windowMinutes: 60, aggregateBucketMinutes: 1, axisTickMinutes: 10 },
      '2h': { windowMinutes: 120, aggregateBucketMinutes: 2, axisTickMinutes: 15 },
      '6h': { windowMinutes: 360, aggregateBucketMinutes: 5, axisTickMinutes: 30 },
      '12h': { windowMinutes: 720, aggregateBucketMinutes: 10, axisTickMinutes: 60 },
      '24h': { windowMinutes: 1440, aggregateBucketMinutes: 15, axisTickMinutes: 120 },
      '7d': { windowMinutes: 10080, aggregateBucketMinutes: 60, axisTickMinutes: 720 },
      'all': { aggregateBucketMinutes: 240, axisTickMinutes: 1440 },
    };
    return configByFilter[this.selectedTimeFilter] || configByFilter['1h'];
  }

  private getHistoryLimit(): number {
    if (this.selectedTimeFilter === 'all') {
      return 20000;
    }

    const sinceMinutes = this.getSelectedSinceMinutes();
    if (!sinceMinutes) {
      return 5000;
    }

    // Keep enough raw points for downsampling from high-frequency snapshots.
    return Math.min(20000, Math.max(3000, sinceMinutes * 90));
  }

  private parseBudgetTimestamp(rawTs: string): number {
    const trimmed = (rawTs || '').trim();
    if (!trimmed) {
      return Number.NaN;
    }
    const withT = trimmed.includes('T')
      ? trimmed
      : trimmed.replace(' ', 'T');
    const normalized = withT.endsWith('Z') ? withT : `${withT}Z`;
    return Date.parse(normalized);
  }

  private aggregateBudgetPoints(points: BudgetPoint[]): BudgetPoint[] {
    if (points.length <= 1) {
      return [...points];
    }

    const bucketMinutes = this.getTimeFilterConfig().aggregateBucketMinutes;
    if (bucketMinutes <= 1) {
      return [...points];
    }

    const bucketMs = bucketMinutes * 60 * 1000;
    const aggregates = new Map<number, { sum: number; count: number }>();

    for (const point of points) {
      const ts = this.parseBudgetTimestamp(point.timestamp);
      if (!Number.isFinite(ts) || !Number.isFinite(point.balance)) {
        continue;
      }
      const bucketKey = Math.floor(ts / bucketMs);
      const current = aggregates.get(bucketKey) || { sum: 0, count: 0 };
      current.sum += point.balance;
      current.count += 1;
      aggregates.set(bucketKey, current);
    }

    return [...aggregates.entries()]
      .sort((a, b) => b[0] - a[0])
      .map(([bucketKey, agg]) => ({
        timestamp: new Date(bucketKey * bucketMs).toISOString(),
        balance: agg.sum / agg.count,
      }));
  }

  private formatXAxisLabel(date: Date): string {
    if (this.selectedTimeFilter === '7d' || this.selectedTimeFilter === 'all') {
      const day = String(date.getDate()).padStart(2, '0');
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const hours = String(date.getHours()).padStart(2, '0');
      const mins = String(date.getMinutes()).padStart(2, '0');
      return `${day}/${month} ${hours}:${mins}`;
    }

    const hours = String(date.getHours()).padStart(2, '0');
    const mins = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${mins}`;
  }

  private getXAxisStepMinutes(): number {
    return this.getTimeFilterConfig().axisTickMinutes;
  }

  private drawYAxisGrid(
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    opts: {
      padding: { top: number; right: number; left: number };
      h: number;
      yMin: number;
      yRange: number;
      yMax: number;
      niceStep: number;
      tickStart: number;
    }
  ): void {
    const { padding, h, yMin, yRange, yMax, niceStep, tickStart } = opts;
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
  }

  private drawXAxisBase(
    ctx: CanvasRenderingContext2D,
    canvas: HTMLCanvasElement,
    padding: { left: number; right: number; top: number },
    h: number
  ): number {
    const xAxisY = padding.top + h;
    ctx.beginPath();
    ctx.strokeStyle = 'rgba(42, 42, 68, 0.8)';
    ctx.lineWidth = 1;
    ctx.moveTo(padding.left, xAxisY);
    ctx.lineTo(canvas.width - padding.right, xAxisY);
    ctx.stroke();
    return xAxisY;
  }

  private drawXAxisLabels(
    ctx: CanvasRenderingContext2D,
    padding: { left: number },
    w: number,
    tsMin: number,
    tsMax: number,
    xAxisY: number
  ): void {
    if (!Number.isFinite(tsMin) || !Number.isFinite(tsMax) || tsMax <= tsMin) {
      return;
    }

    const stepMs = this.getXAxisStepMinutes() * 60 * 1000;
    const firstTick = Math.ceil(tsMin / stepMs) * stepMs;

    ctx.fillStyle = '#666';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';

    for (let tickTs = firstTick; tickTs <= tsMax; tickTs += stepMs) {
      const x = padding.left + ((tickTs - tsMin) / (tsMax - tsMin)) * w;
      const label = this.formatXAxisLabel(new Date(tickTs));

      ctx.beginPath();
      ctx.strokeStyle = 'rgba(42, 42, 68, 0.5)';
      ctx.moveTo(x, xAxisY);
      ctx.lineTo(x, xAxisY + 4);
      ctx.stroke();

      ctx.fillText(label, x, xAxisY + 16);
    }
  }

  filterBudgetData(): void {
    const now = Date.now();
    const windowMinutes = this.getTimeFilterConfig().windowMinutes;
    const cutoff = windowMinutes
      ? now - windowMinutes * 60 * 1000
      : Number.NEGATIVE_INFINITY;

    const scoped = this.budgetData.filter((p) => {
      const ts = this.parseBudgetTimestamp(p.timestamp);
      return Number.isFinite(ts) && ts >= cutoff;
    });

    this.filteredBudgetData = this.aggregateBudgetPoints(scoped);
    setTimeout(() => this.drawChart());
  }

  selectTimeFilter(value: string): void {
    this.selectedTimeFilter = value;
    this.loadBudgetHistory();
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

    const padding = { top: 20, right: 20, bottom: 48, left: 60 };
    const w = canvas.width - padding.left - padding.right;
    const h = canvas.height - padding.top - padding.bottom;

    // Compute nice tick values for Y-axis
    const tickCount = 5;
    const rawStep = yRange / tickCount;
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep || 1)));
    const niceStep = Math.ceil(rawStep / magnitude) * magnitude;
    const tickStart = Math.floor(yMin / niceStep) * niceStep;

    this.drawYAxisGrid(
      ctx,
      canvas,
      {
        padding: { top: padding.top, right: padding.right, left: padding.left },
        h,
        yMin,
        yRange,
        yMax,
        niceStep,
        tickStart,
      }
    );

    const xAxisY = this.drawXAxisBase(
      ctx,
      canvas,
      { left: padding.left, right: padding.right, top: padding.top },
      h
    );

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

    const tsValues = data
      .map((d) => this.parseBudgetTimestamp(d.timestamp))
      .filter((v) => Number.isFinite(v));
    if (tsValues.length > 1) {
      const tsMin = Math.min(...tsValues);
      const tsMax = Math.max(...tsValues);
      this.drawXAxisLabels(
        ctx,
        { left: padding.left },
        w,
        tsMin,
        tsMax,
        xAxisY
      );
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
      const parsedTs = this.parseBudgetTimestamp(closest.data.timestamp);
      const date = Number.isFinite(parsedTs)
        ? new Date(parsedTs)
        : new Date();
      this.chartTooltip = {
        visible: true,
        x: closest.x / scaleX + 12,
        y: closest.y / scaleY - 30,
        balance: closest.data.balance.toFixed(2),
        time: this.dateTimeService.formatDateTime(date),
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

  openOrderDetail(
    event: MouseEvent,
    kind: OrderDetailKind,
    record: Record<string, unknown>
  ): void {
    event.stopPropagation();
    this.openOrderDetailState(kind, record);
  }

  openOrderDetailFromKeyboard(
    kind: OrderDetailKind,
    record: Record<string, unknown>
  ): void {
    this.openOrderDetailState(kind, record);
  }

  handleOrderDetailKeydown(
    event: KeyboardEvent,
    kind: OrderDetailKind,
    record: Record<string, unknown>
  ): void {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }

    event.preventDefault();
    this.openOrderDetailFromKeyboard(kind, record);
  }

  private openOrderDetailState(
    kind: OrderDetailKind,
    record: Record<string, unknown>
  ): void {
    const fields = this.buildOrderDetailFields(kind, record);
    const titleByKind: Record<OrderDetailKind, string> = {
      open: 'Open Order',
      history: 'Historic Order',
      trades: 'Historic Transaction',
    };
    const subtitleParts = [
      this.getBotName(record['bot_id']),
      this.formatSummaryValue(record['market']),
      this.formatSummaryValue(
        record['exchange_order_id'] || record['exchange_trade_id'] || record['id']
      ),
    ].filter(Boolean);

    this.selectedOrderDetail = {
      kind,
      title: titleByKind[kind],
      subtitle: subtitleParts.join(' · '),
      fields,
    };
  }

  closeOrderDetail(): void {
    this.selectedOrderDetail = null;
  }

  private buildOrderDetailFields(
    kind: OrderDetailKind,
    record: Record<string, unknown>
  ): OrderDetailField[] {
    const preferredKeys = kind === 'trades'
      ? [
        'id',
        'exchange_trade_id',
        'exchange_order_id',
        'bot_id',
        'operator_id',
        'client_order_id',
        'market',
        'side',
        'order_type',
        'order_status',
        'amount',
        'price',
        'fee',
        'fee_currency',
        'taker',
        'settled',
        'order_amount',
        'order_amount_remaining',
        'order_amount_quote',
        'order_amount_quote_remaining',
        'order_price',
        'filled_amount',
        'filled_amount_quote',
        'fee_paid',
        'time_in_force',
        'post_only',
        'visible',
        'created_at',
        'order_created_at',
        'order_updated_at',
      ]
      : [
        'id',
        'exchange_order_id',
        'bot_id',
        'operator_id',
        'client_order_id',
        'market',
        'side',
        'order_type',
        'status',
        'amount',
        'amount_remaining',
        'amount_quote',
        'amount_quote_remaining',
        'price',
        'on_hold',
        'on_hold_currency',
        'trigger_price',
        'trigger_amount',
        'trigger_type',
        'trigger_reference',
        'filled_amount',
        'filled_amount_quote',
        'fee_paid',
        'fee_currency',
        'self_trade_prevention',
        'time_in_force',
        'post_only',
        'visible',
        'fill_count',
        'created_at',
        'updated_at',
      ];

    const fields: OrderDetailField[] = [];
    const seen = new Set<string>();

    for (const key of preferredKeys) {
      if (key in record) {
        fields.push(this.toDetailField(key, record[key]));
        seen.add(key);
      }
    }

    for (const key of Object.keys(record).sort((left, right) => left.localeCompare(right))) {
      if (seen.has(key)) {
        continue;
      }
      fields.push(this.toDetailField(key, record[key]));
    }

    return fields;
  }

  private toDetailField(key: string, value: unknown): OrderDetailField {
    return {
      label: this.formatDetailLabel(key),
      value: this.formatDetailValue(key, value),
    };
  }

  private formatDetailLabel(key: string): string {
    const labelMap: Record<string, string> = {
      id: 'Id',
      bot_id: 'Bot',
      operator_id: 'Operator Id',
      exchange_order_id: 'Exchange Order Id',
      exchange_trade_id: 'Exchange Trade Id',
      client_order_id: 'Client Order Id',
      order_type: 'Order Type',
      order_status: 'Order Status',
      amount_remaining: 'Amount Remaining',
      amount_quote: 'Quote Amount',
      amount_quote_remaining: 'Quote Amount Remaining',
      on_hold: 'On Hold',
      on_hold_currency: 'On Hold Currency',
      trigger_price: 'Trigger Price',
      trigger_amount: 'Trigger Amount',
      trigger_type: 'Trigger Type',
      trigger_reference: 'Trigger Reference',
      filled_amount: 'Filled Amount',
      filled_amount_quote: 'Filled Quote Amount',
      fee_paid: 'Fee Paid',
      fee_currency: 'Fee Currency',
      self_trade_prevention: 'Self Trade Prevention',
      time_in_force: 'Time In Force',
      post_only: 'Post Only',
      fill_count: 'Fill Count',
      order_amount: 'Order Amount',
      order_amount_remaining: 'Order Amount Remaining',
      order_amount_quote: 'Order Quote Amount',
      order_amount_quote_remaining: 'Order Quote Remaining',
      order_price: 'Order Price',
      order_created_at: 'Order Created',
      order_updated_at: 'Order Updated',
      created_at: 'Created',
      updated_at: 'Updated',
    };

    if (labelMap[key]) {
      return labelMap[key];
    }

    return key
      .split('_')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  private formatDetailValue(key: string, value: unknown): string {
    if (value === null || value === undefined || value === '') {
      return '—';
    }

    if (key.endsWith('_at') || key.includes('time') || key.includes('timestamp')) {
      const date = this.parseDetailDate(value);
      if (date) {
        return this.dateTimeService.formatDateTime(date);
      }
    }

    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }

    return JSON.stringify(value);
  }

  private parseDetailDate(value: unknown): Date | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
      const millis = value < 1e12 ? value * 1000 : value;
      const date = new Date(millis);
      return Number.isNaN(date.getTime()) ? null : date;
    }

    if (typeof value !== 'string') {
      return null;
    }

    const parsed = Date.parse(value.includes('T') ? value : value.replace(' ', 'T'));
    if (Number.isNaN(parsed)) {
      return null;
    }

    return new Date(parsed);
  }

  private formatSummaryValue(value: unknown): string {
    if (value === null || value === undefined || value === '') {
      return '';
    }

    if (typeof value === 'string') {
      return value.trim();
    }

    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }

    return JSON.stringify(value);
  }

  getBalances(exchangeId: number): Balance[] {
    return this.exchangeBalances[exchangeId] || [];
  }

  getBalanceError(exchangeId: number): string {
    return this.exchangeBalanceErrors[exchangeId] || '';
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
    this.modalOffsetX = 0;
    this.modalOffsetY = 0;
    this.isModalDragging = false;
    this.gridModalBot = bot;
    this.gridLevels = [];
    this.botService.getGridLevels(bot.id).subscribe((levels: BotGridLevel[]) => {
      this.gridLevels = levels.map((lvl) => ({
        index: Number(lvl.index),
        price: Number(lvl.price),
        orderType: lvl.order_type,
      }));
    });
  }
}
