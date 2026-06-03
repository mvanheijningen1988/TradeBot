import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface Exchange {
  id: number;
  name: string;
  rate_limit: number;
  enabled: boolean;
  created_at: string;
}

export interface MarketInfo {
  market: string;
  base: string;
  quote: string;
  status: string;
  min_order_base: string;
  min_order_quote: string;
  quantity_decimals: number;
  tick_size: string;
  order_types: string[];
}

export interface Balance {
  symbol: string;
  available: string;
  in_order: string;
}

@Injectable({ providedIn: 'root' })
export class ExchangeService {
  private http = inject(HttpClient);
  private url = `${environment.apiUrl}/exchanges`;

  list(): Observable<Exchange[]> {
    return this.http.get<Exchange[]>(this.url);
  }

  create(data: {
    name: string;
    api_key: string;
    api_secret: string;
    rate_limit?: number;
  }): Observable<{ id: number; name: string }> {
    return this.http.post<{ id: number; name: string }>(this.url, data);
  }

  delete(id: number): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }

  update(
    id: number,
    data: { api_key?: string; api_secret?: string; rate_limit?: number }
  ): Observable<{ detail: string }> {
    return this.http.put<{ detail: string }>(`${this.url}/${id}`, data);
  }

  getMarkets(exchangeId: number): Observable<MarketInfo[]> {
    return this.http.get<MarketInfo[]>(`${this.url}/${exchangeId}/markets`);
  }

  getFees(exchangeId: number): Observable<{ taker: string; maker: string; volume: string }> {
    return this.http.get<{ taker: string; maker: string; volume: string }>(`${this.url}/${exchangeId}/fees`);
  }

  getBalances(exchangeId: number): Observable<Balance[]> {
    return this.http.get<Balance[]>(`${this.url}/${exchangeId}/balances`);
  }

  getIcons(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(`${this.url}/icons`);
  }
}
