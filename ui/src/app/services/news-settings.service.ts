import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface NewsFeed {
  id: number;
  name: string;
  url: string;
  source_type: string;
  weight: number;
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

export interface NewsArticle {
  title: string;
  url: string;
  source: string;
  source_type: string;
  source_weight: number;
  timestamp: string;
  summary: string;
  content: string;
  sentiment_label: string;
  sentiment_score: number;
  coins: string[];
}

export interface NewsOverview {
  overall_score: number;
  label: string;
  positive_day: boolean;
  article_count: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
}

export interface NewsParams {
  min_confidence: number;
  poll_interval_minutes: number;
  finbert_enabled: boolean;
}

@Injectable({ providedIn: 'root' })
export class NewsSettingsService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/news`;

  // ── Feeds ──────────────────────────────────────────────────────

  getFeeds(): Observable<NewsFeed[]> {
    return this.http.get<NewsFeed[]>(`${this.base}/feeds`);
  }

  createFeed(
    name: string,
    url: string,
    sourceType: string,
    weight: number,
  ): Observable<NewsFeed> {
    return this.http.post<NewsFeed>(`${this.base}/feeds`, {
      name,
      url,
      source_type: sourceType,
      weight,
    });
  }

  updateFeed(
    id: number,
    changes: Partial<{
      name: string;
      enabled: boolean;
      source_type: string;
      weight: number;
    }>
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

  getParams(): Observable<NewsParams> {
    return this.http.get<NewsParams>(`${this.base}/params`);
  }

  updateParams(params: Partial<NewsParams>): Observable<unknown> {
    return this.http.put(`${this.base}/params`, params);
  }

  getArticles(limit = 100): Observable<NewsArticle[]> {
    return this.http.get<NewsArticle[]>(`${this.base}/articles`, {
      params: { limit: limit.toString() },
    });
  }

  getOverview(limit = 100): Observable<NewsOverview> {
    return this.http.get<NewsOverview>(`${this.base}/overview`, {
      params: { limit: limit.toString() },
    });
  }
}
