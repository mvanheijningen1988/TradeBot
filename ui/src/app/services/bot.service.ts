import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface Bot {
  id: number;
  uuid: string;
  name: string;
  exchange_id: number;
  market: string;
  strategy: string;
  strategy_params: Record<string, unknown>;
  operator_id: number;
  budget_quote: number;
  profit_mode: string;
  profit_skim_pct: number;
  status: string;
  worker_id: number | null;
  manual_assign: boolean;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

export interface BotGridLevel {
  index: number;
  price: number;
  order_type: string | null;
}

@Injectable({ providedIn: 'root' })
export class BotService {
  private readonly http = inject(HttpClient);
  private readonly url = `${environment.apiUrl}/bots`;

  private buildBudgetHistoryParams(
    limit: number,
    sinceMinutes?: number
  ): URLSearchParams {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    if (sinceMinutes !== undefined) {
      params.set('since_minutes', String(sinceMinutes));
    }
    return params;
  }

  list(): Observable<Bot[]> {
    return this.http.get<Bot[]>(this.url);
  }

  get(id: number): Observable<Bot> {
    return this.http.get<Bot>(`${this.url}/${id}`);
  }

  create(data: Partial<Bot>): Observable<Bot> {
    return this.http.post<Bot>(this.url, data);
  }

  update(id: number, data: Partial<Bot>): Observable<Bot> {
    return this.http.put<Bot>(`${this.url}/${id}`, data);
  }

  start(id: number, workerId?: number): Observable<Bot> {
    return this.http.post<Bot>(`${this.url}/${id}/start`, {
      worker_id: workerId ?? null,
    });
  }

  stop(id: number): Observable<Bot> {
    return this.http.post<Bot>(`${this.url}/${id}/stop`, {});
  }

  delete(id: number, mode = 'stop_cancel'): Observable<void> {
    return this.http.delete<void>(
      `${this.url}/${id}?mode=${encodeURIComponent(mode)}`
    );
  }

  getOrders(id: number): Observable<unknown[]> {
    return this.http.get<unknown[]>(`${this.url}/${id}/orders`);
  }

  getOpenOrders(id: number): Observable<unknown[]> {
    return this.http.get<unknown[]>(`${this.url}/${id}/open-orders`);
  }

  getGridLevels(id: number): Observable<BotGridLevel[]> {
    return this.http.get<BotGridLevel[]>(`${this.url}/${id}/grid-levels`);
  }

  getTrades(id: number): Observable<unknown[]> {
    return this.http.get<unknown[]>(`${this.url}/${id}/trades`);
  }

  getBudgetHistory(
    id: number,
    limit = 500,
    sinceMinutes?: number
  ): Observable<unknown[]> {
    const params = this.buildBudgetHistoryParams(limit, sinceMinutes);
    return this.http.get<unknown[]>(
      `${this.url}/${id}/budget-history?${params.toString()}`
    );
  }

  getOverallBudgetHistory(
    limit = 500,
    sinceMinutes?: number
  ): Observable<unknown[]> {
    const params = this.buildBudgetHistoryParams(limit, sinceMinutes);
    return this.http.get<unknown[]>(
      `${this.url}/overview/budget-history?${params.toString()}`
    );
  }
}
