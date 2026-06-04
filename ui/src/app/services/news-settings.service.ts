import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface NewsFeed {
  id: number;
  name: string;
  url: string;
  enabled: boolean;
}

export interface CoinMapping {
  id: number;
  name: string;
  symbol: string;
  ambiguous: boolean;
}

export interface WordFilter {
  id: number;
  word: string;
  filter_type: 'include' | 'exclude';
}

@Injectable({ providedIn: 'root' })
export class NewsSettingsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/news`;

  // ── Feeds ──────────────────────────────────────────────────────

  getFeeds(): Observable<NewsFeed[]> {
    return this.http.get<NewsFeed[]>(`${this.base}/feeds`);
  }

  createFeed(name: string, url: string): Observable<NewsFeed> {
    return this.http.post<NewsFeed>(`${this.base}/feeds`, { name, url });
  }

  updateFeed(
    id: number,
    changes: Partial<{ name: string; enabled: boolean }>
  ): Observable<unknown> {
    return this.http.patch(`${this.base}/feeds/${id}`, changes);
  }

  deleteFeed(id: number): Observable<unknown> {
    return this.http.delete(`${this.base}/feeds/${id}`);
  }

  // ── Coin mappings ───────────────────────────────────────────────

  getCoinMappings(): Observable<CoinMapping[]> {
    return this.http.get<CoinMapping[]>(`${this.base}/coin-mappings`);
  }

  createCoinMapping(
    name: string,
    symbol: string,
    ambiguous: boolean
  ): Observable<CoinMapping> {
    return this.http.post<CoinMapping>(`${this.base}/coin-mappings`, {
      name,
      symbol,
      ambiguous,
    });
  }

  updateCoinMapping(
    id: number,
    changes: Partial<{ name: string; symbol: string; ambiguous: boolean }>
  ): Observable<unknown> {
    return this.http.patch(`${this.base}/coin-mappings/${id}`, changes);
  }

  deleteCoinMapping(id: number): Observable<unknown> {
    return this.http.delete(`${this.base}/coin-mappings/${id}`);
  }

  // ── Word filters ────────────────────────────────────────────────

  getWordFilters(): Observable<WordFilter[]> {
    return this.http.get<WordFilter[]>(`${this.base}/word-filters`);
  }

  createWordFilter(
    word: string,
    filter_type: 'include' | 'exclude'
  ): Observable<WordFilter> {
    return this.http.post<WordFilter>(`${this.base}/word-filters`, {
      word,
      filter_type,
    });
  }

  deleteWordFilter(id: number): Observable<unknown> {
    return this.http.delete(`${this.base}/word-filters/${id}`);
  }

  // ── Engine parameters ────────────────────────────────────────────

  getParams(): Observable<{ min_confidence: number }> {
    return this.http.get<{ min_confidence: number }>(
      `${this.base}/params`
    );
  }

  updateParams(params: { min_confidence: number }): Observable<unknown> {
    return this.http.put(`${this.base}/params`, params);
  }
}
